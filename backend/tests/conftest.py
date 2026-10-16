"""Test harness: real PostgreSQL, isolated per-session schema, no mocks of the database.

The database comes from PIKO_DATABASE_URL (.env). Every session creates `piko_test_<random>`,
migrates it with Alembic, and drops only that schema afterwards. If the database is unreachable
the suite FAILS; it never silently skips integration tests.
"""

import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.core.ratelimit import RateLimiter
from app.core.security import generate_rsa_private_pem
from app.db.session import make_engine
from app.main import create_app
from app.services.bootstrap import create_family_with_parent

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery staple"
TEST_SCHEMA_PREFIX = "piko_test_"


def build_settings(tmp_dir: Path, schema: str, **overrides: object) -> Settings:
    jwt_file, hmac_file = tmp_dir / "jwt.pem", tmp_dir / "hmac.key"
    if not jwt_file.exists():
        jwt_file.write_bytes(generate_rsa_private_pem())
        hmac_file.write_bytes(os.urandom(32))
    values: dict[str, object] = {
        "env": "test",
        "allowed_hosts": ["testserver", "127.0.0.1", "localhost", "[::1]"],
        "db_schema": schema,
        "bcrypt_rounds": 4,  # speed only; production enforces >= 12 (see test_config)
        "jwt_private_key_file": jwt_file,
        "hmac_key_file": hmac_file,
    }
    values.update(overrides)
    return Settings(_env_file=PROJECT_ROOT / ".env", **values)  # type: ignore[arg-type]


def alembic_config(settings: Settings) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["settings"] = settings
    return cfg


def drop_test_schema(engine: Engine, schema: str) -> None:
    assert schema.startswith(TEST_SCHEMA_PREFIX), "refusing to drop a non-test schema"
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.fixture(scope="session")
def tmp_keys(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("keys")


@pytest.fixture(scope="session")
def settings(tmp_keys: Path) -> Iterator[Settings]:
    schema = TEST_SCHEMA_PREFIX + secrets.token_hex(4)
    s = build_settings(tmp_keys, schema)
    engine = make_engine(s)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure here must fail the suite, not skip
        pytest.fail(f"PostgreSQL unreachable ({type(exc).__name__}); integration tests cannot run")
    command.upgrade(alembic_config(s), "head")
    yield s
    drop_test_schema(engine, schema)
    engine.dispose()


@pytest.fixture(scope="session")
def app(settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app) -> TestClient:  # type: ignore[no-untyped-def]
    app.state.limiter = RateLimiter()  # fresh per test; rate-limit tests set their own
    return TestClient(app)


@pytest.fixture
def db(app) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        yield session


def unique_email(prefix: str = "parent") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


class Family:
    """A parent account + family created through the bootstrap service."""

    def __init__(
        self, client: TestClient, db: Session, settings: Settings, name: str = "Test"
    ) -> None:
        self.client = client
        self.email = unique_email()
        self.user_id, self.family_id = create_family_with_parent(
            db, settings, email=self.email, password=PASSWORD, family_name=name
        )
        resp = client.post("/api/v1/auth/session", json={"email": self.email, "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        self.access = body["access_token"]
        self.refresh = body["refresh_token"]
        self.headers = {"Authorization": f"Bearer {self.access}"}

    def pair_device(self, name: str = "Child Phone") -> tuple[str, str, str]:
        """Returns (device_id, device_token, formatted_code)."""
        self.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]
        code = self.client.post("/api/v1/devices/pairing-code", headers=self.headers)
        assert code.status_code == 201, code.text
        formatted = code.json()["pairing_code"]
        paired = self.client.post(
            "/api/v1/devices/pair", json={"pairing_code": formatted, "device_name": name}
        )
        assert paired.status_code == 201, paired.text
        body = paired.json()
        return body["device_id"], body["device_credential"], formatted


@pytest.fixture
def make_family(client: TestClient, db: Session, settings: Settings):  # type: ignore[no-untyped-def]
    def factory(name: str = "Test") -> Family:
        client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]  # logins are limited
        return Family(client, db, settings, name)

    return factory


def device_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
