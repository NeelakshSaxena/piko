"""Application settings, loaded from PIKO_* environment variables and `.env`."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MIN_BCRYPT_ROUNDS = 12
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Managed by Supabase/Postgres; Piko must never create tables in or alter these.
RESERVED_SCHEMAS = {
    "public", "auth", "storage", "extensions", "realtime", "graphql", "graphql_public",
    "vault", "pgbouncer", "supabase_functions", "cron", "net",
}  # fmt: skip


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIKO_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    bind_host: str = "127.0.0.1"
    port: int = 8000
    allow_public_bind: bool = False
    log_level: str = "INFO"
    public_base_url: str = "http://127.0.0.1:8000"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:3000"])
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost", "[::1]"])

    database_url: SecretStr
    db_schema: str = "piko"

    # Secret material lives in files (never in env dumps). Generate with `python -m app.cli`.
    jwt_private_key_file: Path
    hmac_key_file: Path

    jwt_issuer: str = "piko"
    access_ttl_seconds: int = 3600
    refresh_ttl_seconds: int = 7 * 24 * 3600
    bcrypt_rounds: int = MIN_BCRYPT_ROUNDS

    max_body_bytes: int = 512 * 1024
    login_failure_limit: int = 10
    login_failure_window_seconds: int = 15 * 60
    pairing_code_ttl_seconds: int = 15 * 60
    polling_interval_seconds: int = 60

    telemetry_max_batch_events: int = 500
    telemetry_future_skew_seconds: int = 60

    # Push (ADR-023). Everything is optional: unset means "not configured" and nothing is sent.
    fcm_project_id: str | None = None
    fcm_service_account_file: Path | None = None  # secret file, never in env dumps or the repo
    vapid_private_key_file: Path | None = None
    vapid_public_key: str | None = None  # public, handed to browsers
    vapid_subject: str = "mailto:operator@example.invalid"
    outbox_run_token_file: Path | None = None  # shared secret for the external scheduler endpoint
    outbox_max_attempts: int = 8
    outbox_batch_size: int = 25
    outbox_backoff_base_seconds: int = 10
    outbox_backoff_cap_seconds: int = 3600
    sos_notification_ttl_seconds: int = 24 * 3600
    message_notification_ttl_seconds: int = 24 * 3600
    # Read-only MCP adapter (ADR-024). Off unless the operator turns it on; there is no network listener.
    mcp_enabled: bool = False
    mcp_max_calls_per_minute: int = Field(default=30, ge=1, le=600)
    mcp_call_timeout_seconds: int = Field(default=10, ge=1, le=60)
    mcp_max_token_ttl_hours: int = Field(default=24 * 30, ge=1)
    # Volume caps and retention (audit F-04, backlog item 11).
    sos_max_unresolved_per_device: int = 50
    messages_max_per_device_per_day: int = 500
    message_retention_days: int = 90
    audit_retention_days: int = 365
    outbox_retention_days: int = 30

    @field_validator("db_schema")
    @classmethod
    def _schema_is_safe_identifier(cls, v: str) -> str:
        if not SCHEMA_RE.fullmatch(v):
            raise ValueError("db_schema must match [a-z_][a-z0-9_]{0,40}")
        if v in RESERVED_SCHEMAS or v.startswith("pg_"):
            raise ValueError("db_schema is reserved")
        return v

    @model_validator(mode="after")
    def _enforce_safe_defaults(self) -> "Settings":
        if self.env != "test" and self.bcrypt_rounds < MIN_BCRYPT_ROUNDS:
            raise ValueError(f"bcrypt_rounds must be >= {MIN_BCRYPT_ROUNDS} outside tests")
        if self.env == "production" and self.public_base_url.startswith("http://"):
            raise ValueError("production requires an https public_base_url")
        if (
            self.allow_public_bind
            and self.bind_host not in LOOPBACK_HOSTS
            and not self.public_base_url.startswith("https://")
        ):
            raise ValueError(
                "a public bind needs an https public_base_url (TLS ends at your reverse proxy)"
            )
        if self.env == "production" and "*" in {*self.allowed_hosts, *self.allowed_origins}:
            raise ValueError("production does not allow wildcard hosts or origins")
        return self

    @property
    def allowed_host_set(self) -> set[str]:
        public_host = urlsplit(self.public_base_url).hostname or ""
        return {h.lower() for h in self.allowed_hosts} | {public_host.lower()}

    @property
    def allowed_origin_set(self) -> set[str]:
        return {o.rstrip("/") for o in self.allowed_origins} | {self.public_base_url.rstrip("/")}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required fields come from env
