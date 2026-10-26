"""Shared test infrastructure (TEST_STRATEGY §2.1).

* a real PostgreSQL database, migrated once per session with Alembic;
* every test runs inside an outer transaction that is rolled back (savepoint mode), so
  application code may call ``commit()`` freely without leaking data between tests;
* an injectable ``FakeClock``; the FastAPI app is built with dependency overrides.
"""

from __future__ import annotations

import base64
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest

# --- environment must be set before toolkit modules read settings -----------------------
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://toolkit:toolkit@127.0.0.1:55432/toolkit_test")
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DB_URL,
        "SECRET_KEY": "test-secret-key-that-is-long-enough-0123456789",
        "ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
        "OTLP_INGEST_TOKEN": "test-ingest-token",
        "ARGON2_TIME_COST": "1",
        "ARGON2_MEMORY_KIB": "1024",
        "ARGON2_PARALLELISM": "1",
        "AI_ENABLED": "false",
        "ANTHROPIC_API_KEY": "",
        "REMEDIATION_ENABLED": "false",
        "PROMETHEUS_URL": "http://prometheus.test:9090",
        "WORK_DIR": tempfile.mkdtemp(prefix="toolkit-work-"),
        "ALERT_EVAL_INTERVAL_SECONDS": "30",
        "LOG_LEVEL": "WARNING",
        "TRUSTED_PROXY_COUNT": "0",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from toolkit.core.clock import FakeClock  # noqa: E402
from toolkit.core.config import get_settings  # noqa: E402
from toolkit.core.crypto import reset_keyring  # noqa: E402
from toolkit.core.security import create_access_token, hash_password  # noqa: E402
from toolkit.db.models import User  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-live", action="store_true", help="run tests that call real external services")
    parser.addoption("--run-sandbox", action="store_true", help="run tests that need the sandbox daemon")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = config.getoption("--run-live") or os.environ.get("TEST_RUN_LIVE") == "1"
    sandbox = config.getoption("--run-sandbox") or os.environ.get("REMEDIATION_TEST_SANDBOX") == "1"
    for item in items:
        if "live" in item.keywords and not live:
            item.add_marker(pytest.mark.skip(reason="live test; pass --run-live"))
        if "sandbox" in item.keywords and not sandbox:
            item.add_marker(pytest.mark.skip(reason="sandbox test; pass --run-sandbox"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Any]:
    url = make_url(TEST_DB_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    eng = create_engine(url)
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.attributes["url"] = TEST_DB_URL
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Any) -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    session = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False
    )()
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def clock() -> FakeClock:
    from datetime import UTC, datetime

    return FakeClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    get_settings.cache_clear()
    reset_keyring()
    from toolkit.core import security

    security._hasher.cache_clear()
    yield
    get_settings.cache_clear()
    reset_keyring()


def set_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for k, v in values.items():
        monkeypatch.setenv(k.upper(), v)
    get_settings.cache_clear()
    reset_keyring()


@pytest.fixture
def session_factory(db: Session) -> Any:
    @contextmanager
    def factory() -> Iterator[Session]:
        try:
            yield db
            db.commit()  # releases the savepoint only
        except BaseException:
            db.rollback()
            raise

    return factory


@pytest.fixture
def app(db: Session, clock: FakeClock) -> Any:
    from toolkit.api.deps import get_clock, get_db
    from toolkit.api.main import create_app

    application = create_app()

    def override_db() -> Iterator[Session]:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_clock] = lambda: clock
    return application


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class Users:
    def __init__(self, db: Session, clock: FakeClock) -> None:
        self.db = db
        self.clock = clock
        self.cache: dict[str, User] = {}

    def make(
        self,
        role: str = "maintainer",
        email: str | None = None,
        password: str = "correct horse battery",
        active: bool = True,
    ) -> User:
        user = User(
            email=email or f"{role}-{uuid.uuid4().hex[:8]}@example.edu",
            display_name=role.title(),
            role=role,
            password_hash=hash_password(password),
            is_active=active,
        )
        self.db.add(user)
        # Commit releases the test savepoint so a later request rollback cannot undo setup rows.
        self.db.commit()
        return user

    def get(self, role: str) -> User:
        if role not in self.cache:
            self.cache[role] = self.make(role)
        return self.cache[role]

    def headers(self, role_or_user: str | User) -> dict[str, str]:
        user = self.get(role_or_user) if isinstance(role_or_user, str) else role_or_user
        token, _ = create_access_token(user.id, self.clock.now())
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def users(db: Session, clock: FakeClock) -> Users:
    return Users(db, clock)


@pytest.fixture
def project(client: TestClient, users: Users) -> dict[str, Any]:
    r = client.post(
        "/api/v1/projects", json={"name": f"proj-{uuid.uuid4().hex[:6]}"}, headers=users.headers("maintainer")
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


@pytest.fixture
def target(client: TestClient, users: Users, project: dict[str, Any]) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/projects/{project['id']}/monitoring-targets",
        json={"name": "Demo API", "service_name": "demo-api", "environment": "dev"},
        headers=users.headers("maintainer"),
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def advance(clock: FakeClock, seconds: float) -> None:
    clock.advance(seconds)


__all__ = ["Users", "advance", "set_env", "timedelta"]
