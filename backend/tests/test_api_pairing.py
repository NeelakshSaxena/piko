"""Pairing: lifecycle, brute-force limits, no plaintext storage, race safety."""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.core.security import sha256_hex
from app.db.models import AuditEvent, DeviceCredential, FamilyMembership, PairingInvitation, User
from app.db.models import Family as FamilyRow

from .conftest import PASSWORD, Family, device_headers

PAIR = "/api/v1/devices/pair"
CODE = "/api/v1/devices/pairing-code"


def new_code(fam: Family) -> str:
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post(CODE, headers=fam.headers)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["pairing_code"])


def pair(client: TestClient, code: str, name: str = "Child Phone"):  # type: ignore[no-untyped-def]
    return client.post(PAIR, json={"pairing_code": code, "device_name": name})


def test_pairing_code_contract(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    resp = fam.client.post(CODE, headers=fam.headers)
    body = resp.json()
    assert resp.status_code == 201 and set(body) == {
        "pairing_code",
        "expires_at",
        "expires_in_seconds",
    }
    assert re.fullmatch(r"[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}", body["pairing_code"])
    assert 890 <= body["expires_in_seconds"] <= 900


def test_pair_success_contract_and_credential_works(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    resp = pair(fam.client, new_code(fam))
    body = resp.json()
    assert resp.status_code == 201
    assert set(body) == {
        "device_id",
        "device_credential",
        "api_endpoint",
        "polling_interval_seconds",
        "family_id",
    }
    assert body["family_id"] == str(fam.family_id) and body["polling_interval_seconds"] == 60
    assert body["api_endpoint"].endswith("/api/v1") and body["device_credential"].startswith("pkd_")
    me = fam.client.get(
        f"/api/v1/devices/{body['device_id']}", headers=device_headers(body["device_credential"])
    )
    assert (
        me.status_code == 200
        and me.json()["name"] == "Child Phone"
        and me.json()["status"] == "active"
    )


def test_code_is_accepted_case_and_separator_insensitively(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)
    assert pair(fam.client, code.lower().replace("-", " ")).status_code == 201


def test_only_hashes_are_stored_never_the_code_or_the_token(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)
    canonical = code.replace("-", "")
    inv = db.scalar(select(PairingInvitation).where(PairingInvitation.family_id == fam.family_id))
    assert inv is not None and re.fullmatch(r"[0-9a-f]{64}", inv.pairing_code_hash)
    assert (
        canonical not in inv.pairing_code_hash and sha256_hex(canonical) != inv.pairing_code_hash
    )  # keyed
    body = pair(fam.client, code).json()
    token = body["device_credential"]
    cred = db.scalar(
        select(DeviceCredential).where(DeviceCredential.device_id == uuid.UUID(body["device_id"]))
    )
    assert (
        cred is not None
        and cred.credential_hash == sha256_hex(token)
        and token not in cred.credential_hash
    )
    # Nothing anywhere in Piko's schema contains the raw secrets.
    for table in ("pairing_invitations", "device_credentials", "audit_events", "devices", "users"):
        dump = db.execute(text(f"SELECT t::text FROM {table} t")).scalars().all()
        blob = "\n".join(dump)
        assert token not in blob and canonical not in blob and code not in blob


def test_code_is_single_use(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)
    assert pair(fam.client, code).status_code == 201
    again = pair(fam.client, code)
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONFLICT"


def test_expired_code_rejected_and_marked_expired(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)
    db.execute(
        update(PairingInvitation)
        .where(PairingInvitation.family_id == fam.family_id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    resp = pair(fam.client, code)
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "AUTH_INVALID"
    db.expire_all()
    inv = db.scalar(select(PairingInvitation).where(PairingInvitation.family_id == fam.family_id))
    assert inv is not None and inv.status == "expired"
    assert pair(fam.client, code).status_code == 401  # still refused afterwards


def test_code_dies_with_its_issuers_membership_or_family(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]

    for target in ("membership", "family"):
        fam: Family = make_family()
        code = new_code(fam)
        if target == "membership":
            db.execute(
                update(FamilyMembership)
                .where(FamilyMembership.family_id == fam.family_id)
                .values(status="revoked")
            )
        else:
            db.execute(
                update(FamilyRow).where(FamilyRow.id == fam.family_id).values(status="archived")
            )
        db.commit()
        resp = pair(fam.client, code)
        assert resp.status_code == 401 and resp.json()["error"]["code"] == "AUTH_INVALID", target
        db.expire_all()
        inv = db.scalar(
            select(PairingInvitation).where(PairingInvitation.family_id == fam.family_id)
        )
        assert inv is not None and inv.status == "revoked", target


def test_wrong_expired_malformed_and_superseded_codes_look_identical(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    old = new_code(fam)
    new = new_code(fam)  # supersedes `old`
    assert new != old
    expired = new_code(fam)
    db.execute(
        update(PairingInvitation)
        .where(PairingInvitation.family_id == fam.family_id, PairingInvitation.status == "pending")
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    bodies = []
    for bad in ("AAA-AAA-AAA", "not a code", "ABC", old, expired, "'; DROP TABLE users;--"):
        fam.client.app.state.limiter = RateLimiter()
        r = pair(fam.client, bad)
        assert r.status_code == 401, bad
        err = r.json()["error"]
        bodies.append((err["code"], err["message"]))
    assert len(set(bodies)) == 1, "wrong/expired/malformed/superseded must be indistinguishable"


def test_pairing_attempts_are_rate_limited_per_ip(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    codes = [pair(fam.client, "AAA-AAA-AAA").status_code for _ in range(7)]
    assert codes == [401] * 5 + [429] * 2
    # Even the genuine code is refused while the limit is active: guessing cannot be outpaced.
    real = fam.client.post(CODE, headers=fam.headers)  # still allowed: different bucket
    assert real.status_code == 201
    assert pair(fam.client, real.json()["pairing_code"]).status_code == 429


def test_requesting_codes_is_rate_limited_per_user(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    assert fam.client.post(CODE, headers=fam.headers).status_code == 201
    resp = fam.client.post(CODE, headers=fam.headers)
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "RATE_LIMIT"


def test_pairing_requires_a_parent_session(client: TestClient) -> None:
    assert client.post(CODE).status_code == 401


def test_pair_validation_rejects_unknown_fields_and_overlong_names(client: TestClient) -> None:
    assert (
        client.post(
            PAIR, json={"pairing_code": "x", "device_name": "d", "family_id": "x"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            PAIR, json={"pairing_code": "AAA-AAA-AAA", "device_name": "d" * 101}
        ).status_code
        == 400
    )
    assert client.post(PAIR, json={"pairing_code": "AAA-AAA-AAA"}).status_code == 400


def test_concurrent_pairing_with_one_code_yields_exactly_one_device(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)

    def attempt(i: int) -> int:
        with TestClient(app) as c:
            return pair(c, code, f"racer-{i}").status_code

    with ThreadPoolExecutor(4) as pool:
        statuses = sorted(pool.map(attempt, range(4)))
    assert statuses == [201, 409, 409, 409]
    n = db.execute(
        text("SELECT count(*) FROM devices WHERE family_id = :f"), {"f": fam.family_id}
    ).scalar()
    assert n == 1


def test_paired_child_identity_cannot_log_in(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    pair(fam.client, new_code(fam))
    child_email = db.scalar(
        select(User.email)
        .where(User.email.like("device-%@piko.invalid"))
        .order_by(User.created_at.desc())
    )
    assert child_email is not None
    fam.client.app.state.limiter = RateLimiter()
    for password in (PASSWORD, "!"):
        r = fam.client.post(
            "/api/v1/auth/session", json={"email": child_email, "password": password}
        )
        assert r.status_code == 401


def test_pairing_is_audited_without_secrets(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    code = new_code(fam)
    pair(fam.client, "ZZZ-ZZZ-ZZZ")
    body = pair(fam.client, code).json()
    ok = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "device_paired",
            AuditEvent.resource_id == uuid.UUID(body["device_id"]),
        )
    )
    assert ok is not None and ok.outcome == "success" and ok.actor_user_id == fam.user_id
    fail = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action == "device_paired",
            AuditEvent.outcome == "failure",
            AuditEvent.reason == "invalid_code",
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    assert fail is not None
    assert "ZZZ" not in str(fail.meta) and code not in str(ok.meta)
