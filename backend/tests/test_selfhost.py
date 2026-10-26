"""Phase 8: operator tooling (doctor, backup/restore, unsafe-default refusal, .env.example).

Backup and restore run against real PostgreSQL: a populated schema is backed up and restored into a
second, empty, migrated schema, and the restored copy is then used through the real API.
"""

import gzip
import json
import os
import re
import secrets
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.core.ratelimit import RateLimiter
from app.db.models import Base, Message, SosIncident, TelemetryEvent, User
from app.db.session import make_engine
from app.main import create_app
from app.services.backup import BackupError, backup, restore
from app.services.doctor import exit_code, run_checks

from .conftest import (
    PASSWORD,
    TEST_SCHEMA_PREFIX,
    Family,
    alembic_config,
    build_settings,
    device_headers,
    drop_test_schema,
)
from .helpers import batch, battery_event, iso, location_event


@pytest.fixture
def scratch_schema(tmp_keys) -> Iterator[Callable[..., tuple[Settings, Engine]]]:  # type: ignore[no-untyped-def]
    made: list[tuple[Engine, str]] = []

    def make(revision: str = "head", **overrides: Any) -> tuple[Settings, Engine]:
        schema = TEST_SCHEMA_PREFIX + "ops_" + secrets.token_hex(3)
        s = build_settings(tmp_keys, schema, **overrides)
        engine = make_engine(s)
        made.append((engine, schema))
        command.upgrade(alembic_config(s), revision)
        return s, engine

    yield make
    for engine, schema in made:
        drop_test_schema(engine, schema)
        engine.dispose()


def populate(fam: Family) -> None:
    device_id, token, _ = fam.pair_device("Backup Kid")
    client: TestClient = fam.client
    client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]
    client.post(
        "/api/v1/telemetry/batches",
        json=batch(device_id, [location_event(), battery_event(70)]),
        headers=device_headers(token),
    )
    client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]
    created = client.post(
        "/api/v1/sos/incidents",
        json={
            "incident_id": str(uuid.uuid4()),
            "device_id": device_id,
            "triggered_at": iso(-timedelta(seconds=2)),
        },
        headers=device_headers(token),
    )
    assert created.status_code in (200, 201), created.text


def counts_of(engine: Engine) -> dict[str, int]:
    out: dict[str, int] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            out[table.name] = conn.execute(select(func.count()).select_from(table)).scalar_one()
    return out


# ---- backup and restore ------------------------------------------------------------------------


def test_a_populated_schema_restores_into_a_fresh_one_and_works_through_the_api(  # type: ignore[no-untyped-def]
    make_family, settings, app, tmp_path, scratch_schema
) -> None:
    fam: Family = make_family("Backup Home")
    populate(fam)
    report = backup(app.state.engine, tmp_path / "piko.backup.gz")
    assert report.counts["users"] >= 1 and report.counts["sos_incidents"] >= 1

    target_settings, target_engine = scratch_schema()
    assert sum(counts_of(target_engine).values()) == 0
    restored = restore(target_engine, report.path)
    assert restored.counts == report.counts
    assert counts_of(target_engine) == counts_of(app.state.engine)

    # Content, not just counts: exact rows survive, including timestamps and decimals.
    with app.state.engine.connect() as a, target_engine.connect() as b:
        for table in (TelemetryEvent.__table__, SosIncident.__table__, Message.__table__):
            query = select(table).order_by(*table.primary_key.columns)
            assert [tuple(r) for r in a.execute(query)] == [tuple(r) for r in b.execute(query)]

    # The restored copy is a working install: the same password logs in and the family is visible.
    restored_app = create_app(target_settings)
    try:
        client = TestClient(restored_app)
        login = client.post("/api/v1/auth/session", json={"email": fam.email, "password": PASSWORD})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        families = client.get("/api/v1/families", headers=headers).json()["families"]
        assert [f["name"] for f in families] == ["Backup Home"]
    finally:
        restored_app.state.engine.dispose()


def test_backup_never_overwrites_and_is_private(app, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "b.gz"
    report = backup(app.state.engine, path)
    assert (tmp_path / "b.gz.sha256").read_text().split()[0] == report.sha256
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(BackupError, match="refusing to overwrite"):
        backup(app.state.engine, path)


def test_restore_refuses_a_schema_that_already_holds_data(app, tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = backup(app.state.engine, tmp_path / "b.gz")
    with pytest.raises(BackupError, match="already holds rows"):
        restore(app.state.engine, report.path)


def test_restore_refuses_a_different_migration_revision(  # type: ignore[no-untyped-def]
    app, tmp_path, scratch_schema
) -> None:
    report = backup(app.state.engine, tmp_path / "b.gz")
    _, older = scratch_schema("0004")
    with pytest.raises(BackupError, match="migrate the schema to the backup's revision"):
        restore(older, report.path)
    with older.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_a_damaged_or_truncated_backup_is_refused_and_changes_nothing(  # type: ignore[no-untyped-def]
    make_family, app, tmp_path, scratch_schema
) -> None:
    populate(make_family())
    good = backup(app.state.engine, tmp_path / "good.gz").path
    raw = good.read_bytes()

    flipped = tmp_path / "flipped.gz"
    flipped.write_bytes(raw[:-12] + bytes([raw[-12] ^ 0xFF]) + raw[-11:])
    (tmp_path / "flipped.gz.sha256").write_text((tmp_path / "good.gz.sha256").read_text())
    _, engine = scratch_schema()
    with pytest.raises(BackupError, match="checksum"):
        restore(engine, flipped)

    # Cut a valid gzip stream short after the data lines: no end marker, so it must not commit.
    lines = gzip.decompress(raw).decode().splitlines()
    cut = tmp_path / "cut.gz"
    cut.write_bytes(gzip.compress(("\n".join(lines[:-1]) + "\n").encode()))
    with pytest.raises(BackupError, match="incomplete"):
        restore(engine, cut)
    assert sum(counts_of(engine).values()) == 0

    other = tmp_path / "other.gz"
    other.write_bytes(gzip.compress(json.dumps({"format": "something-else"}).encode() + b"\n"))
    with pytest.raises(BackupError, match="not a Piko backup"):
        restore(engine, other)


# ---- doctor ------------------------------------------------------------------------------------


def test_doctor_passes_on_a_healthy_install_and_prints_no_secrets(settings: Settings) -> None:
    checks = run_checks(settings)
    by_name = {c.name: c for c in checks}
    assert by_name["database"].status == "ok" and by_name["migrations"].status == "ok"
    assert by_name["MCP adapter"].detail == "disabled"
    assert exit_code(checks) == 0
    printed = "\n".join(f"{c.name} {c.detail}" for c in checks)
    assert settings.database_url.get_secret_value() not in printed
    assert "postgresql" not in printed and "BEGIN" not in printed


def test_doctor_fails_on_missing_keys_and_behind_migrations(  # type: ignore[no-untyped-def]
    settings, scratch_schema, tmp_path
) -> None:
    missing = settings.model_copy(update={"jwt_private_key_file": tmp_path / "nope.pem"})
    checks = run_checks(missing)
    assert exit_code(checks) == 1
    assert any(
        c.status == "fail" and c.name in ("JWT signing key", "JWT key loads") for c in checks
    )

    behind, _ = scratch_schema("0004")
    stale = {c.name: c for c in run_checks(behind)}["migrations"]
    assert stale.status == "fail" and "head is" in stale.detail


def test_doctor_flags_an_unreachable_database_without_leaking_the_url(settings: Settings) -> None:
    broken = settings.model_copy(update={"db_schema": "piko_test_x"})
    bad_url = settings.database_url.get_secret_value().replace("@", "@invalid.invalid.", 1)
    broken = broken.model_copy(update={"database_url": type(settings.database_url)(bad_url)})
    checks = run_checks(broken)
    db_check = {c.name: c for c in checks}["database"]
    assert db_check.status == "fail" and "invalid.invalid" not in db_check.detail


# ---- unsafe defaults are refused ---------------------------------------------------------------


def make_settings(tmp_keys: Path, **overrides: Any) -> Settings:
    return build_settings(tmp_keys, "piko_test_cfg", **overrides)


def test_a_public_bind_requires_the_explicit_flag_and_an_https_url(tmp_keys: Path) -> None:
    make_settings(
        tmp_keys, bind_host="0.0.0.0"
    )  # allowed to construct; __main__ refuses to start it
    with pytest.raises(ValidationError, match="https public_base_url"):
        make_settings(tmp_keys, bind_host="0.0.0.0", allow_public_bind=True)
    ok = make_settings(
        tmp_keys,
        bind_host="0.0.0.0",
        allow_public_bind=True,
        public_base_url="https://piko.example.org",
    )
    assert ok.allow_public_bind


def test_the_server_entrypoint_refuses_a_public_bind_without_the_flag(  # type: ignore[no-untyped-def]
    tmp_keys, monkeypatch, capsys
) -> None:
    from app import __main__ as entry

    monkeypatch.setattr(entry, "get_settings", lambda: make_settings(tmp_keys, bind_host="0.0.0.0"))
    assert entry.main() == 1
    assert "refusing to bind" in capsys.readouterr().err


def test_production_rejects_http_and_wildcards(tmp_keys: Path) -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings(tmp_keys, env="production", bcrypt_rounds=12)
    with pytest.raises(ValidationError, match="wildcard"):
        make_settings(
            tmp_keys, env="production", bcrypt_rounds=12, public_base_url="https://p.example.org",
            allowed_hosts=["*"],
        )  # fmt: skip


def test_mcp_and_public_bind_are_off_by_default() -> None:
    fields = Settings.model_fields
    assert fields["mcp_enabled"].default is False and fields["allow_public_bind"].default is False
    assert fields["bind_host"].default == "127.0.0.1"


# ---- .env.example stays in step with the settings ----------------------------------------------


def test_env_example_documents_every_setting_and_invents_none() -> None:
    text_ = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*PIKO_([A-Z0-9_]+)=", text_, flags=re.MULTILINE))
    known = {name.upper() for name in Settings.model_fields}
    assert known - documented == set(), f"undocumented settings: {sorted(known - documented)}"
    assert documented - known == set(), (
        f"unknown settings in .env.example: {sorted(documented - known)}"
    )


def test_env_example_holds_no_real_secrets() -> None:
    text_ = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "USER:PASSWORD@HOST" in text_
    assert re.search(r"PIKO_MCP_TOKEN\s*=", text_) is None
    assert re.search(r"-----BEGIN|eyJ[A-Za-z0-9_-]{20,}", text_) is None


def test_users_table_is_untouched_by_reading_the_schema(settings: Settings, db: Session) -> None:
    # Guards the doctor/backup read paths: a read must not change anything.
    before = db.scalar(select(func.count()).select_from(User))
    run_checks(settings)
    assert db.scalar(select(func.count()).select_from(User)) == before
