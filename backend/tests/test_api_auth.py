"""Authentication: login, lockout, refresh, revoke, token confusion. Real API + real PostgreSQL."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.core.security import TokenClaims
from app.db.models import AuditEvent, RefreshSession, User

from .conftest import PASSWORD, Family, device_headers, unique_email

LOGIN = "/api/v1/auth/session"


def login(client: TestClient, email: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return client.post(LOGIN, json={"email": email, "password": password})


def assert_error(resp, status: int, code: str) -> None:  # type: ignore[no-untyped-def]
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    assert err["code"] == code
    assert err["request_id"] == resp.headers["x-request-id"]
    assert set(err) == {"code", "message", "request_id", "timestamp"}


def test_login_success_returns_contract_shape(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family("Smiths")
    body = fam.client.post(LOGIN, json={"email": fam.email.upper(), "password": PASSWORD}).json()
    assert set(body) == {
        "access_token", "refresh_token", "expires_in", "user_id", "family_id", "role", "families",
    }  # fmt: skip
    assert body["expires_in"] == 3600
    assert body["family_id"] == str(fam.family_id) and body["role"] == "parent"
    assert body["families"] == [{"id": str(fam.family_id), "name": "Smiths", "role": "parent"}]


def test_wrong_password_and_unknown_email_are_indistinguishable(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    wrong = login(fam.client, fam.email, "definitely the wrong one")
    unknown = login(fam.client, unique_email("ghost"))
    assert_error(wrong, 401, "AUTH_INVALID")
    assert_error(unknown, 401, "AUTH_INVALID")
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_validation_errors_do_not_echo_input(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    resp = fam.client.post(LOGIN, json={"email": fam.email, "password": "s3cret-value", "extra": 1})
    assert_error(resp, 400, "VALIDATION_ERROR")
    assert "s3cret-value" not in resp.text and fam.email not in resp.text


def test_overlong_password_rejected_without_hashing(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    assert_error(login(fam.client, fam.email, "x" * 73), 401, "AUTH_INVALID")


def test_per_ip_login_rate_limit(client: TestClient) -> None:
    statuses = [login(client, unique_email("nobody")).status_code for _ in range(7)]
    assert statuses[:5] == [401] * 5 and statuses[5:] == [429, 429]
    resp = login(client, unique_email("nobody"))
    assert_error(resp, 429, "RATE_LIMIT")
    assert int(resp.headers["retry-after"]) >= 1


def test_account_locks_after_ten_failures_even_for_correct_password(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    for _ in range(10):
        fam.client.app.state.limiter = (
            RateLimiter()
        )  # isolate the durable lockout from the IP limit
        assert login(fam.client, fam.email, "wrong password!!").status_code == 401
    fam.client.app.state.limiter = RateLimiter()
    locked = login(fam.client, fam.email)  # correct password, still refused
    assert_error(locked, 429, "RATE_LIMIT")


def test_lockout_also_applies_to_unknown_emails_so_existence_is_not_leaked(
    client: TestClient,
) -> None:
    ghost = unique_email("ghost")
    for _ in range(10):
        client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]
        assert login(client, ghost).status_code == 401
    client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]
    assert_error(login(client, ghost), 429, "RATE_LIMIT")


def test_failed_logins_are_audited_without_the_password(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    login(fam.client, fam.email, "wrong password!!")
    row = db.scalars(
        select(AuditEvent).where(
            AuditEvent.actor_user_id == fam.user_id, AuditEvent.outcome == "failure"
        )
    ).first()
    assert row is not None and row.action == "login" and row.reason == "invalid_credentials"
    assert "wrong password" not in str(row.meta) and fam.email not in str(row.meta)


def test_user_without_family_cannot_log_in(client: TestClient, db: Session, settings) -> None:  # type: ignore[no-untyped-def]
    from app.core.security import hash_password

    email = unique_email("orphan")
    db.add(User(email=email, password_hash=hash_password(PASSWORD, 4)))
    db.commit()
    assert_error(login(client, email), 403, "FORBIDDEN")


def test_suspended_user_cannot_log_in_and_existing_tokens_die(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    assert fam.client.get("/api/v1/families", headers=fam.headers).status_code == 200
    db.execute(update(User).where(User.id == fam.user_id).values(status="suspended"))
    db.commit()
    assert_error(fam.client.get("/api/v1/families", headers=fam.headers), 401, "AUTH_INVALID")
    assert_error(login(fam.client, fam.email), 401, "AUTH_INVALID")


# ---- refresh ----
def test_refresh_issues_a_working_access_token(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    resp = fam.client.post(
        "/api/v1/auth/session/refresh", headers={"Authorization": f"Bearer {fam.refresh}"}
    )
    assert resp.status_code == 200
    assert set(resp.json()) == {"access_token", "refresh_token", "expires_in"}
    new = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert fam.client.get("/api/v1/families", headers=new).status_code == 200


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_refresh_rotates_and_the_new_token_works_in_turn(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    token = fam.refresh
    seen = {token}
    for _ in range(3):
        body = fam.client.post("/api/v1/auth/session/refresh", headers=bearer(token)).json()
        assert body["refresh_token"] not in seen
        seen.add(body["refresh_token"])
        token = body["refresh_token"]
    assert (
        fam.client.get("/api/v1/families", headers=bearer(body["access_token"])).status_code == 200
    )


def test_replaying_a_superseded_refresh_token_revokes_the_whole_session(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    first = fam.client.post("/api/v1/auth/session/refresh", headers=bearer(fam.refresh)).json()
    # An attacker (or a stale copy) replays the original, already-replaced token.
    assert_error(
        fam.client.post("/api/v1/auth/session/refresh", headers=bearer(fam.refresh)),
        401,
        "AUTH_INVALID",
    )
    # The session is dead for everyone: the newest refresh token and its access token too.
    assert_error(
        fam.client.post("/api/v1/auth/session/refresh", headers=bearer(first["refresh_token"])),
        401,
        "AUTH_INVALID",
    )
    assert_error(
        fam.client.get("/api/v1/families", headers=bearer(first["access_token"])),
        401,
        "AUTH_INVALID",
    )
    db.expire_all()
    reuse = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.actor_user_id == fam.user_id,
            AuditEvent.reason == "refresh_token_reuse",
        )
    )
    assert reuse == 1
    # A fresh login still works: only the compromised session was revoked.
    fam.client.app.state.limiter = RateLimiter()
    assert login(fam.client, fam.email).status_code == 200


def test_reuse_does_not_touch_other_sessions(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    other = login(fam.client, fam.email).json()
    fam.client.post("/api/v1/auth/session/refresh", headers=bearer(fam.refresh))
    fam.client.post("/api/v1/auth/session/refresh", headers=bearer(fam.refresh))  # reuse
    ok = fam.client.post("/api/v1/auth/session/refresh", headers=bearer(other["refresh_token"]))
    assert ok.status_code == 200


def test_refresh_requires_a_token(client: TestClient) -> None:
    assert_error(client.post("/api/v1/auth/session/refresh"), 401, "AUTH_REQUIRED")


def test_access_token_cannot_refresh_and_refresh_token_cannot_access(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    assert_error(
        fam.client.post("/api/v1/auth/session/refresh", headers=fam.headers), 401, "AUTH_INVALID"
    )
    as_access = {"Authorization": f"Bearer {fam.refresh}"}
    assert_error(fam.client.get("/api/v1/families", headers=as_access), 401, "AUTH_INVALID")


def test_expired_refresh_token_rejected(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    old = datetime.now(UTC) - timedelta(seconds=app.state.tokens.refresh_ttl + 60)
    session_id = db.scalar(select(RefreshSession.id).where(RefreshSession.user_id == fam.user_id))
    stale = app.state.tokens.issue_refresh(TokenClaims(fam.user_id, session_id, None), now=old)
    resp = fam.client.post(
        "/api/v1/auth/session/refresh", headers={"Authorization": f"Bearer {stale}"}
    )
    assert_error(resp, 401, "AUTH_INVALID")


def test_session_expired_in_database_rejected_even_with_valid_jwt(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == fam.user_id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert_error(fam.client.get("/api/v1/families", headers=fam.headers), 401, "AUTH_INVALID")
    resp = fam.client.post(
        "/api/v1/auth/session/refresh", headers={"Authorization": f"Bearer {fam.refresh}"}
    )
    assert_error(resp, 401, "AUTH_INVALID")


def test_expired_access_token_rejected(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    old = datetime.now(UTC) - timedelta(seconds=app.state.tokens.access_ttl + 60)
    session_id = db.scalar(select(RefreshSession.id).where(RefreshSession.user_id == fam.user_id))
    stale = app.state.tokens.issue_access(TokenClaims(fam.user_id, session_id, None), now=old)
    assert_error(
        fam.client.get("/api/v1/families", headers={"Authorization": f"Bearer {stale}"}),
        401,
        "AUTH_INVALID",
    )


def test_refresh_rate_limit_per_user(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    token, codes = fam.refresh, []
    for _ in range(11):
        resp = fam.client.post("/api/v1/auth/session/refresh", headers=bearer(token))
        codes.append(resp.status_code)
        if resp.status_code == 200:
            token = resp.json()["refresh_token"]  # tokens rotate, so chain them
    assert codes[:10] == [200] * 10 and codes[10] == 429
    # The 429 happened before rotation, so the last good token is still valid (not "reuse").
    fam.client.app.state.limiter = RateLimiter()
    assert fam.client.post("/api/v1/auth/session/refresh", headers=bearer(token)).status_code == 200


# ---- revoke ----
def test_revoke_is_immediate_for_access_and_refresh_tokens(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    assert fam.client.post("/api/v1/auth/session/revoke", headers=fam.headers).status_code == 204
    assert_error(fam.client.get("/api/v1/families", headers=fam.headers), 401, "AUTH_INVALID")
    resp = fam.client.post(
        "/api/v1/auth/session/refresh", headers={"Authorization": f"Bearer {fam.refresh}"}
    )
    assert_error(resp, 401, "AUTH_INVALID")


def test_revoking_one_session_leaves_other_sessions_alone(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    second = login(fam.client, fam.email).json()["access_token"]
    fam.client.post("/api/v1/auth/session/revoke", headers=fam.headers)
    h2 = {"Authorization": f"Bearer {second}"}
    assert fam.client.get("/api/v1/families", headers=h2).status_code == 200


def test_revoke_requires_authentication(client: TestClient) -> None:
    assert_error(client.post("/api/v1/auth/session/revoke"), 401, "AUTH_REQUIRED")


# ---- credential-type separation ----
def test_device_credential_is_rejected_on_parent_endpoints(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    _, token, _ = fam.pair_device()
    for path in ("/api/v1/families", f"/api/v1/families/{fam.family_id}"):
        assert_error(fam.client.get(path, headers=device_headers(token)), 401, "AUTH_INVALID")
    assert_error(
        fam.client.post("/api/v1/devices/pairing-code", headers=device_headers(token)),
        401,
        "AUTH_INVALID",
    )


def test_user_token_is_rejected_on_device_endpoint(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    body = {"batch_id": str(uuid.uuid4()), "schema_version": 1, "device_id": str(uuid.uuid4()),
            "events": [{"event_id": str(uuid.uuid4()), "event_type": "battery",
                        "occurred_at": "2026-01-01T00:00:00Z", "data": {"percent": 5}}]}  # fmt: skip
    assert_error(
        fam.client.post("/api/v1/telemetry/batches", json=body, headers=fam.headers),
        401,
        "AUTH_INVALID",
    )


def test_malformed_authorization_headers(client: TestClient) -> None:
    for header in ("", "Basic abc", "Bearer", "Bearer  ", "bearer not.a.jwt", "Token abc"):
        resp = client.get("/api/v1/families", headers={"Authorization": header})
        assert resp.status_code == 401, header
    assert_error(
        client.get("/api/v1/families", headers={"Authorization": "Bearer not.a.jwt"}),
        401,
        "AUTH_INVALID",
    )
