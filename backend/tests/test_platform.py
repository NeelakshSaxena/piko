"""Health, error shape, middleware, deployment defaults, and secret/coordinate log hygiene."""

import gzip
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.__main__ as launcher
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.db.session import make_engine, make_session_factory
from app.main import create_app

from .conftest import PASSWORD, Family, build_settings, device_headers
from .helpers import batch, location_event


@pytest.fixture
def paired_device(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


# ---- health ----
def test_liveness_needs_no_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


def test_readiness_reports_database_ok_without_details(client: TestClient) -> None:
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ready", "database": "ok", "checks": {"database": {"status": "ok"}},
    }  # fmt: skip


def test_readiness_degrades_to_503_and_leaks_nothing(app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    dead = settings.model_copy(
        update={
            "database_url": SecretStr(
                "postgresql+psycopg://leaky_user:leaky_pw@127.0.0.1:1/leaky_db"
            )
        }
    )
    good_factory = app.state.session_factory
    app.state.session_factory = make_session_factory(make_engine(dead))
    try:
        resp = TestClient(app).get("/api/v1/health/ready")
    finally:
        app.state.session_factory = good_factory
    assert resp.status_code == 503 and resp.json()["status"] == "degraded"
    for secret in ("leaky", "127.0.0.1", "refused", "psycopg", "Traceback"):
        assert secret not in resp.text


# ---- error shape ----
def test_unknown_route_and_wrong_method_return_the_standard_error_shape(client: TestClient) -> None:
    missing = client.get("/api/v1/nope")
    assert (
        missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND_OR_NOT_VISIBLE"
    )
    wrong = client.put("/api/v1/health/live")
    assert wrong.status_code == 405 and set(wrong.json()["error"]) == {
        "code", "message", "request_id", "timestamp",
    }  # fmt: skip


def test_request_ids_are_server_generated_and_unique(client: TestClient) -> None:
    a = client.get("/api/v1/health/live", headers={"X-Request-ID": "attacker-chosen\r\nX: y"})
    b = client.get("/api/v1/health/live")
    ids = {a.headers["x-request-id"], b.headers["x-request-id"]}
    assert len(ids) == 2 and all(re.fullmatch(r"[0-9a-f-]{36}", i) for i in ids)


def test_validation_errors_never_echo_submitted_values(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/session", json={"email": ["x"], "password": {"p": "hunter2-secret"}}
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "hunter2-secret" not in resp.text
    bad_json = client.post(
        "/api/v1/auth/session",
        content=b'{"password": "hunter2-secret"',
        headers={"Content-Type": "application/json"},
    )
    assert bad_json.status_code == 400 and "hunter2-secret" not in bad_json.text


def test_internal_errors_are_generic(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("secret-internal-detail /srv/app/secret.py SELECT * FROM users")

    monkeypatch.setattr(type(app.state.auth), "login", boom)
    app.state.limiter = RateLimiter()
    resp = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/auth/session", json={"email": "a@example.com", "password": "whatever-pw"}
    )
    assert resp.status_code == 500 and resp.json()["error"]["code"] == "INTERNAL_ERROR"
    for leak in ("secret-internal", "/srv/app", "SELECT", "RuntimeError", "Traceback"):
        assert leak not in resp.text


# ---- origin / CORS ----
def test_disallowed_origin_is_rejected_allowed_origin_gets_cors_headers(client: TestClient) -> None:
    bad = client.get("/api/v1/health/live", headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "FORBIDDEN"
    assert "access-control-allow-origin" not in bad.headers
    good = client.get("/api/v1/health/live", headers={"Origin": "http://127.0.0.1:3000"})
    assert good.status_code == 200
    assert good.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_cors_preflight(client: TestClient) -> None:
    ok = client.options(
        "/api/v1/families",
        headers={"Origin": "http://127.0.0.1:3000", "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "authorization"},
    )  # fmt: skip
    assert (
        ok.status_code == 200
        and ok.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    )
    bad = client.options(
        "/api/v1/families",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert bad.status_code == 403


def test_native_clients_without_an_origin_header_are_unaffected(client: TestClient) -> None:
    assert client.get("/api/v1/health/live").status_code == 200


# ---- body bounds ----
def test_invalid_content_length_and_oversized_declared_length_rejected(client: TestClient) -> None:
    big = client.post("/api/v1/auth/session", content=b"x" * (600 * 1024))
    assert big.status_code == 400
    corrupt = client.post(
        "/api/v1/auth/session",
        content=gzip.compress(b'{"a":1}')[:-4],
        headers={"Content-Encoding": "gzip"},
    )
    assert corrupt.status_code == 400


# ---- deployment defaults ----
def test_docs_are_disabled_in_production(tmp_keys, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    prod = build_settings(
        tmp_keys, "piko_test_prod", env="production", bcrypt_rounds=12,
        public_base_url="https://piko.example.com", allowed_origins=["https://piko.example.com"],
    )  # fmt: skip
    client = TestClient(create_app(prod))
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_launcher_refuses_public_bind_unless_explicitly_allowed(
    settings: Settings, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    called = []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *a, **k: called.append(k))
    monkeypatch.setattr(
        launcher, "get_settings", lambda: settings.model_copy(update={"bind_host": "0.0.0.0"})
    )
    assert launcher.main() == 1 and called == []
    assert "non-loopback" in capsys.readouterr().err
    monkeypatch.setattr(
        launcher, "get_settings", lambda: settings.model_copy(update={"bind_host": "127.0.0.1"})
    )
    assert (
        launcher.main() == 0
        and called[0]["host"] == "127.0.0.1"
        and called[0]["access_log"] is False
    )
    # X-Forwarded-For must never choose the client IP used by per-IP rate limits (audit M-2).
    assert called[0]["proxy_headers"] is False


def test_default_bind_is_loopback_and_secrets_are_not_in_repr(settings: Settings) -> None:
    assert Settings.model_fields["bind_host"].default == "127.0.0.1"
    assert Settings.model_fields["allow_public_bind"].default is False
    url = settings.database_url.get_secret_value()
    password = url.split("://", 1)[1].rsplit("@", 1)[0].split(":", 1)[1]
    assert password not in repr(settings) and password not in str(settings.model_dump())


# ---- logs must not contain secrets or coordinates ----
def server_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Everything the server side logged; excludes the test client's own request logging."""
    return " | ".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    )


def test_logs_contain_no_credentials_tokens_codes_or_coordinates(
    make_family, caplog, settings: Settings
) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    fam: Family = make_family("Logs")
    fam.client.post(
        "/api/v1/auth/session", json={"email": fam.email, "password": "wrong-password-xyz"}
    )
    fam.client.app.state.limiter = RateLimiter()
    device_id, device_token, code = fam.pair_device("Log Phone")
    fam.client.app.state.limiter = RateLimiter()
    fam.client.post(
        "/api/v1/telemetry/batches",
        json=batch(
            device_id, [location_event(lat=40.712812, lon=-74.006015), location_event(lat=999)]
        ),
        headers=device_headers(device_token),
    )
    fam.client.get("/api/v1/telemetry/batches", headers=device_headers(device_token))
    secret_url = settings.database_url.get_secret_value()
    db_password = secret_url.split("://", 1)[1].rsplit("@", 1)[0].split(":", 1)[1]
    forbidden = [
        PASSWORD, "wrong-password-xyz", fam.access, fam.refresh, device_token, code,
        code.replace("-", ""), "40.712812", "-74.006015", db_password,
    ]  # fmt: skip
    text = server_log_text(caplog)
    assert "request_id=" in text, "request logging is active, so this test is meaningful"
    for needle in forbidden:
        assert needle not in text, f"log leaked a sensitive value ({needle[:4]}...)"
    assert fam.email not in text


@pytest.mark.parametrize("path", ["/api/v1/health/live"])
def test_request_log_line_omits_query_strings(client: TestClient, caplog, path: str) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.INFO)
    client.get(path + "?token=super-secret-query-token")
    text = server_log_text(caplog)
    assert "super-secret-query-token" not in text and "GET " + path in text


# ---- review findings F-01 (global limit), F-02 (deep nesting), F-03 (host validation) ----
def test_global_rate_limit_applies_before_authentication(client: TestClient) -> None:
    codes = [client.get("/api/v1/families").status_code for _ in range(102)]
    assert codes[:100] == [401] * 100, "unauthenticated requests are counted too"
    assert codes[100:] == [429, 429]
    limited = client.get("/api/v1/families")
    assert limited.json()["error"]["code"] == "RATE_LIMIT" and "retry-after" in limited.headers
    assert limited.headers["x-ratelimit-remaining"] == "0"


def test_rate_limit_headers_are_reported_on_successful_responses(client: TestClient) -> None:
    resp = client.get("/api/v1/health/live")
    assert (
        resp.headers["x-ratelimit-limit"] == "100"
        and int(resp.headers["x-ratelimit-remaining"]) <= 99
    )


def test_unexpected_host_headers_are_rejected(client: TestClient) -> None:
    for host in ("evil.example", "evil.example:8000", "", "127.0.0.1.evil.example"):
        resp = client.get("/api/v1/health/live", headers={"Host": host})
        assert resp.status_code == 400, host
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    for host in ("testserver", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST"):
        assert client.get("/api/v1/health/live", headers={"Host": host}).status_code == 200, host


def test_deeply_nested_json_is_a_client_error_never_a_500(paired_device) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired_device
    h = {**device_headers(token), "Content-Type": "application/json"}
    for body in (b"[" * 100_000, b'{"a":' * 50_000, b'{"batch_id":"x","events":' + b"[" * 100_000):
        fam.client.app.state.limiter = RateLimiter()
        resp = fam.client.post("/api/v1/telemetry/batches", content=body, headers=h)
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "VALIDATION_ERROR"
    # Valid JSON, deeply nested inside a data object: rejected per event or as a batch, not a 500.
    nested = "[" * 400 + "]" * 400
    doc = batch(device_id, [location_event()])
    doc["events"][0]["data"] = {"latitude": "@@NESTED@@"}
    raw = json.dumps(doc).replace('"@@NESTED@@"', nested)
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post("/api/v1/telemetry/batches", content=raw, headers=h)
    assert resp.status_code in (202, 400) and resp.status_code != 500
