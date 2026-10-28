"""Migration validation against real PostgreSQL, each in its own throwaway schema."""

import secrets
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.core.config import Settings
from app.db.models import Base
from app.db.session import make_engine

from .conftest import TEST_SCHEMA_PREFIX, alembic_config, build_settings, drop_test_schema

PHASE2_TABLES = {
    "users", "families", "family_memberships", "devices", "device_credentials",
    "pairing_invitations", "refresh_sessions", "audit_events", "alembic_version",
}  # fmt: skip
PHASE3_TABLES = {"telemetry_events", "device_latest_state"}
INVITATION_TABLES = {"member_invitations"}
SAFETY_TABLES = {"sos_incidents", "messages"}
PUSH_TABLES = {"device_push_tokens", "web_push_subscriptions", "notification_outbox"}
JOURNEY_TABLES = {"journeys", "journey_legs", "journey_events"}
HEAD_TABLES = (
    PHASE2_TABLES | PHASE3_TABLES | INVITATION_TABLES | SAFETY_TABLES | PUSH_TABLES | JOURNEY_TABLES
)


@pytest.fixture
def scratch(tmp_keys) -> Iterator[tuple[Settings, Engine]]:  # type: ignore[no-untyped-def]
    schema = TEST_SCHEMA_PREFIX + "mig_" + secrets.token_hex(3)
    s = build_settings(tmp_keys, schema)
    engine = make_engine(s)
    yield s, engine
    drop_test_schema(engine, schema)
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_head_creates_all_tables_in_the_isolated_schema(settings: Settings) -> None:
    engine = make_engine(settings)
    assert tables(engine) == HEAD_TABLES
    with engine.connect() as conn:
        public_has = conn.execute(
            text("SELECT count(*) FROM information_schema.tables "
                 "WHERE table_schema = 'public' AND table_name = 'users'")
        ).scalar()  # fmt: skip
    assert public_has == 0, "Piko tables must never be created in the public schema"
    engine.dispose()


def test_models_and_migrations_agree(settings: Settings) -> None:
    engine = make_engine(settings)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"schema drift between models and migrations: {diff}"


def test_upgrade_from_previous_schema_preserves_data(scratch: tuple[Settings, Engine]) -> None:
    s, engine = scratch
    cfg = alembic_config(s)
    command.upgrade(cfg, "0001")
    assert tables(engine) == PHASE2_TABLES  # previous supported version
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:i, :e, '!')"),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    command.upgrade(cfg, "head")
    assert tables(engine) == HEAD_TABLES
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM users WHERE id = :i"), {"i": user_id}).scalar()
            == 1
        )
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0007"


def test_0004_applies_to_a_populated_0003_schema_without_touching_existing_rows(  # type: ignore[no-untyped-def]
    scratch: tuple[Settings, Engine],
) -> None:
    """The persistent schema is at 0003 with real rows: 0004 must be additive (audit action list widens)."""
    s, engine = scratch
    cfg = alembic_config(s)
    command.upgrade(cfg, "0003")
    user_id, family_id, audit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:i, :e, '!')"),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
        conn.execute(text("INSERT INTO families (id, name) VALUES (:i, 'F')"), {"i": family_id})
        conn.execute(
            text(
                "INSERT INTO audit_events (id, family_id, actor_user_id, action, resource_type) "
                "VALUES (:a, :f, :u, 'login', 'user')"
            ),
            {"a": audit_id, "f": family_id, "u": user_id},
        )
    command.upgrade(cfg, "head")
    assert {"sos_incidents", "messages"} <= tables(engine)
    with engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM audit_events WHERE id = :a"), {"a": audit_id}
            ).scalar()
            == 1
        )
        assert (
            conn.execute(text("SELECT count(*) FROM users WHERE id = :u"), {"u": user_id}).scalar()
            == 1
        )
        conn.execute(  # the widened constraint now accepts the new action
            text(
                "INSERT INTO audit_events (id, family_id, actor_user_id, action, resource_type) "
                "VALUES (:a, :f, :u, 'sos_acknowledged', 'incident')"
            ),
            {"a": uuid.uuid4(), "f": family_id, "u": user_id},
        )
    with pytest.raises(Exception, match="check"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_events (id, action, resource_type) VALUES (:a, 'bogus', 'incident')"
            ),
            {"a": uuid.uuid4()},
        )


def test_upgrade_is_idempotent_and_downgrades_cleanly(scratch: tuple[Settings, Engine]) -> None:
    s, engine = scratch
    cfg = alembic_config(s)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # no-op, no error
    command.downgrade(cfg, "0004")
    assert tables(engine) == PHASE2_TABLES | PHASE3_TABLES | INVITATION_TABLES | SAFETY_TABLES
    command.downgrade(cfg, "0003")
    assert tables(engine) == PHASE2_TABLES | PHASE3_TABLES | INVITATION_TABLES
    command.downgrade(cfg, "0002")
    assert tables(engine) == PHASE2_TABLES | PHASE3_TABLES
    command.downgrade(cfg, "0001")
    assert tables(engine) == PHASE2_TABLES
    command.downgrade(cfg, "base")
    assert tables(engine) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert tables(engine) == HEAD_TABLES


def test_check_constraints_reject_invalid_states(settings: Settings) -> None:
    engine = make_engine(settings)
    with pytest.raises(Exception, match="check"), engine.begin() as conn:
        conn.execute(
            text("INSERT INTO families (id, name, status) VALUES (:i, 'x', 'bogus')"),
            {"i": uuid.uuid4()},
        )
    with pytest.raises(Exception, match="check"), engine.begin() as conn:
        conn.execute(
            text("INSERT INTO families (id, name, retention_days) VALUES (:i, 'x', 0)"),
            {"i": uuid.uuid4()},
        )
    engine.dispose()


def test_supabase_api_roles_cannot_use_the_piko_schema(settings: Settings) -> None:
    """PostgREST roles must have no access to our schema (the Data API must not expose it)."""
    engine = make_engine(settings)
    with engine.connect() as conn:
        roles = [
            r[0]
            for r in conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
            )
        ]
        for role in roles:
            usable = conn.execute(
                text("SELECT has_schema_privilege(:r, :s, 'USAGE')"),
                {"r": role, "s": settings.db_schema},
            ).scalar()
            assert usable is False, f"{role} can use schema {settings.db_schema}"
    engine.dispose()
