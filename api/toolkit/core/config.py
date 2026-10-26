"""Typed runtime configuration loaded from environment variables (DEPLOYMENT.md §3)."""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- application -------------------------------------------------------------
    app_env: Literal["development", "production", "test"] = "development"
    public_base_url: str = "http://localhost:3000"
    cors_origins: str = ""
    log_level: str = "INFO"
    api_docs_enabled: bool = True
    trusted_proxy_count: int = Field(default=1, ge=0, le=5)

    # --- persistence -------------------------------------------------------------
    database_url: str = "postgresql+psycopg://toolkit:toolkit@localhost:5432/toolkit"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)

    # --- secrets -----------------------------------------------------------------
    secret_key: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")
    encryption_key_id: str = "k1"
    # Previous keys kept for decryption during rotation: "k0:<base64>,k-1:<base64>"
    encryption_old_keys: SecretStr = SecretStr("")
    admin_bootstrap_email: str | None = None
    admin_bootstrap_password: SecretStr | None = None

    # --- auth --------------------------------------------------------------------
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=900)
    refresh_session_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=3600, le=7 * 24 * 3600)
    login_max_failures: int = 5
    login_window_seconds: int = 900
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4

    # --- monitoring --------------------------------------------------------------
    prometheus_url: str = "http://prometheus:9090"
    prometheus_timeout_seconds: float = 10.0
    otlp_ingest_token: SecretStr = SecretStr("")
    otlp_public_endpoint: str = "http://localhost:4318"
    alert_eval_interval_seconds: int = Field(default=30, ge=5, le=3600)
    enable_monitoring_loop: bool = True
    target_stale_after_seconds: int = Field(default=300, ge=30)
    notification_cooldown_seconds: int = Field(default=300, ge=0)
    notification_max_attempts: int = Field(default=3, ge=1, le=10)
    allow_private_webhooks: bool = False
    metrics_scrape_token: SecretStr = SecretStr("")
    worker_metrics_port: int = 9100

    # --- jobs --------------------------------------------------------------------
    worker_concurrency: int = Field(default=2, ge=1, le=5)
    job_lease_seconds: int = Field(default=1200, ge=30)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_poll_interval_seconds: float = Field(default=1.0, gt=0)

    # --- scanning ----------------------------------------------------------------
    scan_timeout_seconds: int = Field(default=900, ge=30)
    clone_max_mb: int = Field(default=200, ge=1)
    clone_timeout_seconds: int = Field(default=180, ge=10)
    work_dir: str = "/work"
    semgrep_timeout_seconds: int = 600
    semgrep_max_file_bytes: int = 1_000_000
    semgrep_rules: str = "bundled"  # "bundled" or a registry config such as "p/default"
    trivy_cache_dir: str = "/var/cache/trivy"
    trivy_skip_db_update: bool = False
    provider_http_timeout_seconds: float = 30.0
    provider_parallelism: int = Field(default=8, ge=1, le=32)
    osv_api_url: str = "https://api.osv.dev"
    npm_registry_url: str = "https://registry.npmjs.org"
    pypi_url: str = "https://pypi.org"
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    scheduled_scan_interval_hours: int = Field(default=0, ge=0)  # 0 disables FR-DEP-08 scheduling

    # --- AI ----------------------------------------------------------------------
    ai_enabled: bool = True
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str | None = None
    claude_model: str = "claude-sonnet-5-5"
    ai_daily_request_cap: int = Field(default=50, ge=0)
    ai_max_input_tokens: int = Field(default=12000, ge=1000)
    ai_max_output_tokens: int = Field(default=2000, ge=256)
    ai_request_timeout_seconds: float = 120.0

    # --- remediation -------------------------------------------------------------
    remediation_enabled: bool = False
    sandbox_docker_host: str | None = None
    sandbox_stage_timeout_seconds: int = 900
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    sandbox_pids_limit: int = 512
    sandbox_node_image: str = "node:22.22.0-alpine3.23"
    sandbox_python_image: str = "python:3.13.12-slim-trixie"
    sandbox_allow_sdist: bool = False

    # --- retention (days; DATA_MODEL §7) -----------------------------------------
    retention_scans_per_project: int = 20
    retention_resolved_findings_days: int = 365
    retention_snippet_days: int = 90
    retention_raw_output_days: int = 30
    retention_fix_proposals_days: int = 180
    retention_output_tail_days: int = 90
    retention_alerts_days: int = 180
    retention_deliveries_days: int = 90
    retention_jobs_days: int = 90
    retention_sessions_days: int = 30
    retention_audit_days: int = 365

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check(self) -> Settings:
        if self.app_env == "production":
            if len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL must use https:// in production (NFR-SEC-03)")
            if self.allow_private_webhooks:
                raise ValueError("ALLOW_PRIVATE_WEBHOOKS cannot be enabled in production")
        return self

    # --- derived -----------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins or self.public_base_url
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]

    @property
    def ai_available(self) -> bool:
        return self.ai_enabled and bool(self.anthropic_api_key.get_secret_value())

    def encryption_keys(self) -> dict[str, bytes]:
        """Return {key_id: 32-byte key}; the primary key is ``encryption_key_id``."""
        keys: dict[str, bytes] = {}
        primary = self.encryption_key.get_secret_value()
        if primary:
            keys[self.encryption_key_id] = _decode_key(primary)
        for raw in self.encryption_old_keys.get_secret_value().split(","):
            item = raw.strip()
            if not item:
                continue
            kid, _, value = item.partition(":")
            keys.setdefault(kid.strip(), _decode_key(value.strip()))
        return keys


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("encryption keys must be base64") from exc
    if len(raw) != 32:
        raise ValueError("encryption keys must decode to exactly 32 bytes")
    return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
