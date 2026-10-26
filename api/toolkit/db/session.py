"""Engine and session factory. One pooled engine per process."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from toolkit.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": 5, "application_name": "toolkit"},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background code: commit on success, roll back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def ping(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
