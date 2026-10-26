"""Operator preflight for a configured install (`python -m app.cli doctor`).

Read-only: it opens one database connection to read the migration revision and changes nothing. Output
names settings and files, never their values, so it is safe to paste into a bug report.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config import LOOPBACK_HOSTS, Settings
from app.core.security import TokenService
from app.db.session import make_engine

Status = Literal["ok", "warn", "fail"]
MIN_KEY_BYTES = 32
BACKEND = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Check:
    status: Status
    name: str
    detail: str


def _key_file(label: str, path: Path, min_bytes: int) -> list[Check]:
    if not path.is_file():
        return [Check("fail", label, "file not found; run: python -m app.cli generate-keys")]
    out: list[Check] = []
    if path.stat().st_size < min_bytes:
        out.append(Check("fail", label, f"shorter than {min_bytes} bytes; regenerate it"))
    else:
        out.append(Check("ok", label, "present"))
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        out.append(Check("fail", f"{label} permissions", "readable by group or others; chmod 600"))
    return out


def _head_revision() -> str:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head() or "unknown"


def _network_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    public = settings.bind_host not in LOOPBACK_HOSTS
    if not public:
        checks.append(Check("ok", "network binding", "loopback only"))
    elif settings.allow_public_bind:
        checks.append(
            Check(
                "warn", "network binding", "public bind: needs a TLS reverse proxy and a firewall"
            )
        )
    else:
        checks.append(
            Check("fail", "network binding", "non-loopback bind without allow_public_bind")
        )
    if settings.public_base_url.startswith("https://"):
        checks.append(Check("ok", "public URL", "https"))
    elif settings.env == "production" or public:
        checks.append(Check("fail", "public URL", "must be https"))
    else:
        checks.append(Check("warn", "public URL", "http is acceptable only on this machine"))
    if settings.env == "production" and settings.bcrypt_rounds < 12:
        checks.append(Check("fail", "password hashing", "bcrypt rounds below 12"))
    return checks


def _database_checks(settings: Settings) -> list[Check]:
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks = [Check("ok", "database", "reachable")]
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception as exc:  # noqa: BLE001 - only the type is shown: messages can contain the URL
        return [Check("fail", "database", f"cannot read ({type(exc).__name__})")]
    finally:
        engine.dispose()
    head = _head_revision()
    if row is None:
        checks.append(Check("fail", "migrations", "not applied; run: alembic upgrade head"))
    elif row[0] == head:
        checks.append(Check("ok", "migrations", f"at head ({head})"))
    else:
        checks.append(Check("fail", "migrations", f"at {row[0]}, head is {head}; upgrade"))
    return checks


def run_checks(settings: Settings) -> list[Check]:
    checks = _network_checks(settings)
    checks += _key_file("JWT signing key", settings.jwt_private_key_file, MIN_KEY_BYTES)
    checks += _key_file("HMAC key", settings.hmac_key_file, MIN_KEY_BYTES)
    try:
        TokenService(settings)
        checks.append(Check("ok", "JWT key loads", "valid RSA private key"))
    except Exception as exc:  # noqa: BLE001 - the key's problem is reported, never its content
        checks.append(Check("fail", "JWT key loads", f"unreadable ({type(exc).__name__})"))
    checks += _database_checks(settings)
    checks.append(
        Check("warn", "MCP adapter", "enabled (local stdio only)")
        if settings.mcp_enabled
        else Check("ok", "MCP adapter", "disabled")
    )
    web_push = bool(settings.vapid_private_key_file and settings.vapid_public_key)
    phone_push = bool(settings.fcm_project_id and settings.fcm_service_account_file)
    checks.append(
        Check(
            "ok" if web_push or phone_push else "warn",
            "push notifications",
            f"web push {'on' if web_push else 'off'}, phone push {'on' if phone_push else 'off'}",
        )
    )
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0
