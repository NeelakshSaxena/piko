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
