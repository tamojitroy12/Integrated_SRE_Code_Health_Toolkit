"""Core helpers: crypto, redaction, validators, SSRF guard, subprocess runner, HTTP client."""

from __future__ import annotations

import base64
import json
import logging
import sys

import httpx
import pytest

from toolkit.core.crypto import DecryptionError, KeyRing
from toolkit.core.http import HostNotAllowedError, HttpClient, UpstreamError
from toolkit.core.logging import JsonFormatter, redact, request_id_var
from toolkit.core.netguard import UnsafeUrlError, mask_url_host, validate_outbound_url
from toolkit.core.process import UnsafeArgumentError, check_argv, run
from toolkit.core.validators import (
    allowed_test_argv,
    is_valid_fix_branch,
    is_valid_git_ref,
    is_valid_package_name,
    is_valid_version,
    parse_github_url,
)


@pytest.mark.nt("SEC-02")
def test_keyring_roundtrip_wrong_aad_and_rotation() -> None:
    ring = KeyRing({"k1": b"a" * 32}, "k1")
    sealed = ring.encrypt("ghp_secret_value", aad="credential:1")
    assert b"ghp_secret_value" not in sealed.ciphertext
    assert ring.decrypt(sealed, aad="credential:1") == "ghp_secret_value"
    with pytest.raises(DecryptionError):
        ring.decrypt(sealed, aad="credential:2")
    with pytest.raises(DecryptionError):
        KeyRing({"k1": b"b" * 32}, "k1").decrypt(sealed, aad="credential:1")
    rotated = KeyRing({"k2": b"c" * 32, "k1": b"a" * 32}, "k2")
    assert rotated.decrypt(sealed, aad="credential:1") == "ghp_secret_value"
    assert rotated.needs_rotation(sealed)


@pytest.mark.nt("SEC-08")
@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer abcdefghijklmnop1234",
        "token=ghp_abcdefghijklmnopqrstuvwxyz0123",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
        '{"password": "hunter2hunter2"}',
        "sk-ant-api03-abcdefghijklmnop",
        "https://user:s3cretpw@example.com/hook",
    ],
)
def test_redaction_removes_secrets(text: str) -> None:
    out = redact(text)
    for secret in ("abcdefghijklmnop1234", "ghp_abcdefghij", "github_pat_11", "hunter2", "sk-ant-api03", "s3cretpw"):
        assert secret not in out
    assert "[REDACTED]" in out


@pytest.mark.nt("OBS-01")
def test_json_log_contains_request_id_and_redacts() -> None:
    token = request_id_var.set("req-12345678")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "calling with Bearer abcdefghijklmnopqr", None, None)
        record.api_key = "sk-ant-zzzzzzzzzzzz"
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req-12345678"
    assert "abcdefghijklmnopqr" not in json.dumps(line)
    assert line["api_key"] == "[REDACTED]"


@pytest.mark.at("FR-REM-08")
@pytest.mark.nt("SEC-06")
@pytest.mark.parametrize(
    "value", ["lodash; rm -rf /", "$(id)", "a|b", "`id`", "--registry=evil", "../x", "a b", "pkg\nnext", "", "UPPER"]
)
def test_package_name_fuzz_rejects_metacharacters(value: str) -> None:
    assert not is_valid_package_name("npm", value)


@pytest.mark.at("FR-REM-08")
@pytest.mark.parametrize("value", ["1.2.3; ls", "-1.0.0", "1.0.0 && x", "$(x)", "1.0", "latest"])
def test_npm_version_fuzz(value: str) -> None:
    assert not is_valid_version("npm", value)


def test_valid_names_and_versions() -> None:
    assert is_valid_package_name("npm", "@scope/pkg-name")
    assert is_valid_package_name("pypi", "Flask_Login")
    assert is_valid_version("npm", "1.2.3-beta.1")
    assert is_valid_version("pypi", "2.25.0")
    assert not is_valid_version("pypi", "2.25.0;rm")


@pytest.mark.parametrize(
    "ref,ok",
    [
        ("main", True),
        ("release/1.2", True),
        ("-x", False),
        ("a..b", False),
        ("a b", False),
        ("a;b", False),
        ("x" * 201, False),
    ],
)
def test_git_ref_grammar(ref: str, ok: bool) -> None:
    assert is_valid_git_ref(ref) is ok


def test_fix_branch_pattern() -> None:
    assert is_valid_fix_branch("toolkit/fix/0b8f0c1e-1234-4abc-9def-001122334455")
    assert not is_valid_fix_branch("main")
    assert not is_valid_fix_branch("toolkit/fix/../main")
    assert not is_valid_fix_branch("toolkit/fix/0b8f0c1e-1234-4abc-9def-001122334455x")


def test_github_url_and_test_commands() -> None:
    assert parse_github_url("https://github.com/org/repo.git") == ("org", "repo")
    assert parse_github_url("https://evil.com/org/repo") is None
    assert allowed_test_argv("npm   test") == ("npm", "test")
    assert allowed_test_argv("rm -rf /") is None


@pytest.mark.nt("SEC-09")
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x",
        "https://127.0.0.1/x",
        "https://10.0.0.5/x",
        "https://169.254.169.254/latest",
        "https://[::1]/x",
        "https://user:pw@hooks.example.com/x",
        "ftp://example.com",
        "https://localhost/x",
        "https://metadata.internal/x",
        "https://[::ffff:127.0.0.1]/x",
    ],
)
def test_ssrf_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url(url, resolve=False)


def test_public_literal_ip_allowed_and_mask() -> None:
    assert validate_outbound_url("https://93.184.216.34/hook", resolve=False)
    assert mask_url_host("https://hooks.slack.com:8443/services/T/B/X") == {"host": "hooks.slack.com", "port": 8443}
    assert mask_url_host("https://hooks.slack.com/services/T/B/X") == {"host": "hooks.slack.com"}


def test_private_allowed_with_flag() -> None:
    assert validate_outbound_url("http://127.0.0.1:9/x", allow_private=True)


@pytest.mark.nt("SEC-06")
def test_process_runner_argv_only_and_timeout() -> None:
    with pytest.raises(UnsafeArgumentError):
        check_argv([])
    with pytest.raises(UnsafeArgumentError):
        check_argv(["echo", "a\0b"])
    # Shell metacharacters are passed literally, never interpreted.
    res = run([sys.executable, "-c", "import sys; print(sys.argv[1])", "$(whoami); echo pwned"], timeout=10)
    assert res.ok and res.stdout.strip() == "$(whoami); echo pwned"
    slow = run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    assert slow.timed_out and not slow.ok


def test_http_client_retries_and_allowlist() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503) if attempts["n"] < 3 else httpx.Response(200, json={"ok": True})

    client = HttpClient(allowed_hosts={"api.example.com"}, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert client.get_json("https://api.example.com/x") == {"ok": True}
    assert attempts["n"] == 3
    with pytest.raises(HostNotAllowedError):
        client.get_json("https://evil.example.com/")
    bad = HttpClient(
        allowed_hosts={"a.test"}, transport=httpx.MockTransport(lambda r: httpx.Response(404)), sleep=lambda s: None
    )
    with pytest.raises(UpstreamError) as exc:
        bad.get_json("https://a.test/x")
    assert exc.value.status == 404 and not exc.value.transient


def test_settings_encryption_key_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.core.config import Settings

    s = Settings(
        encryption_key=base64.b64encode(b"x" * 32).decode(),
        encryption_old_keys=f"old:{base64.b64encode(b'y' * 32).decode()}",
    )
    keys = s.encryption_keys()
    assert set(keys) == {"k1", "old"}
    with pytest.raises(ValueError):
        Settings(encryption_key=base64.b64encode(b"short").decode()).encryption_keys()
    with pytest.raises(ValueError):
        Settings(app_env="production", secret_key="short", public_base_url="https://x")
