"""Member invitations (invite code, ADR-017) and the limited `guardian` role."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent, FamilyMembership, MemberInvitation
from app.db.models import Family as FamilyRow

from .conftest import PASSWORD, Family, device_headers, unique_email

ACCEPT = "/api/v1/invitations/accept"
NEW_PASSWORD = "an entirely different passphrase"


def members_url(fam: Family) -> str:
    return f"/api/v1/families/{fam.family_id}/members"


def invite(fam: Family, role: str = "guardian", email: str | None = None):  # type: ignore[no-untyped-def]
    fam.client.app.state.limiter = RateLimiter()
    return fam.client.post(
        members_url(fam), json={"email": email or unique_email("kin"), "role": role},
        headers=fam.headers,
    )  # fmt: skip


def accept(fam: Family, code: str, email: str, password: str = NEW_PASSWORD):  # type: ignore[no-untyped-def]
    fam.client.app.state.limiter = RateLimiter()
    return fam.client.post(
        ACCEPT, json={"invite_code": code, "email": email, "password": password, "full_name": "Kin"}
    )


def login_headers(fam: Family, email: str, password: str = NEW_PASSWORD) -> dict[str, str]:
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post("/api/v1/auth/session", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def join(fam: Family, role: str) -> tuple[str, dict[str, str]]:
    email = unique_email("kin")
    issued = invite(fam, role, email)
    assert issued.status_code == 201, issued.text
    assert accept(fam, issued.json()["invite_code"], email).status_code == 201
    return email, login_headers(fam, email)


def test_invite_contract_and_code_format(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    resp = invite(fam, "guardian", "Sibling@Example.com")
    body = resp.json()
    assert resp.status_code == 201
    assert set(body) == {"invitation_id", "email", "role", "status", "invite_code", "expires_at"}
    assert body["email"] == "sibling@example.com" and body["status"] == "pending"
    assert re.fullmatch(r"[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}", body["invite_code"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)


@pytest.mark.parametrize("role", ["parent", "family_admin", "guardian"])
def test_accepted_invitation_creates_an_active_member_who_can_log_in(
    make_family, db: Session, role: str
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    _, headers = join(fam, role)
    me = fam.client.get(f"/api/v1/families/{fam.family_id}", headers=headers).json()
    assert me["my_role"] == role
    assert sorted(m["role"] for m in me["members"]) == sorted(["parent", role])
    db.expire_all()
    inv = db.scalar(select(MemberInvitation).where(MemberInvitation.family_id == fam.family_id))
    assert inv is not None and inv.status == "used" and inv.used_by_member_id is not None


def test_only_the_keyed_hash_is_stored_never_the_code_or_the_email_in_audit(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    email = unique_email("kin")
    code = invite(fam, "guardian", email).json()["invite_code"]
    assert accept(fam, code, email).status_code == 201
    canonical = code.replace("-", "")
    for table in ("member_invitations", "audit_events", "users", "family_memberships"):
        blob = "\n".join(db.execute(text(f"SELECT t::text FROM {table} t")).scalars().all())
        assert canonical not in blob and code not in blob and NEW_PASSWORD not in blob
    audit_blob = "\n".join(
        db.execute(text("SELECT t::text FROM audit_events t WHERE action LIKE 'member_%'"))
        .scalars()
        .all()
    )
    assert email not in audit_blob


def test_code_is_single_use(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    email = unique_email("kin")
    code = invite(fam, "guardian", email).json()["invite_code"]
    assert accept(fam, code, email).status_code == 201
    again = accept(fam, code, email, "yet another long passphrase")
    assert again.status_code == 401 and again.json()["error"]["code"] == "AUTH_INVALID"


def test_every_refusal_looks_identical(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    email = unique_email("kin")
    old = invite(fam, "guardian", email).json()["invite_code"]
    current = invite(fam, "guardian", email).json()["invite_code"]  # supersedes `old`
    other = invite(fam, "guardian", unique_email("kin")).json()["invite_code"]
    expired_email = unique_email("kin")
    expired = invite(fam, "guardian", expired_email).json()["invite_code"]
    db.execute(
        update(MemberInvitation)
        .where(MemberInvitation.invitee_email == expired_email)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    registered = fam.email  # already an account
    registered_code = invite(fam, "guardian", registered).json()["invite_code"]
    attempts = [
        (old, email), (current, unique_email("wrong")), (other, email), ("AAA-AAA-AAA", email),
        ("not a code", email), (expired, expired_email), (registered_code, registered),
    ]  # fmt: skip
    bodies = []
    for code, who in attempts:
        r = accept(fam, code, who)
        assert r.status_code == 401, (code, who)
        err = r.json()["error"]
        bodies.append((err["code"], err["message"]))
    assert len(set(bodies)) == 1
    assert accept(fam, current, email).status_code == 201  # the right pair still works


def test_weak_or_oversized_passwords_are_rejected(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    email = unique_email("kin")
    code = invite(fam, "guardian", email).json()["invite_code"]
    assert accept(fam, code, email, "short").status_code == 400
    assert accept(fam, code, email, "x" * 73).status_code == 400
    assert accept(fam, code, email).status_code == 201  # the code was not burned by the failures


def test_code_dies_with_its_issuer(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    for target in ("membership", "family"):
        fam: Family = make_family()
        email = unique_email("kin")
        code = invite(fam, "guardian", email).json()["invite_code"]
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
        assert accept(fam, code, email).status_code == 401, target


def test_accept_is_rate_limited_per_ip(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    codes = [
        fam.client.post(
            ACCEPT,
            json={"invite_code": "AAA-AAA-AAA", "email": "a@example.com", "password": NEW_PASSWORD},
        ).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]


def test_invite_validation(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    for bad in (
        {"email": unique_email(), "role": "child"},
        {"email": unique_email(), "role": "operator"},
        {"email": "not-an-email", "role": "guardian"},
        {"email": unique_email(), "role": "guardian", "family_id": str(uuid.uuid4())},
    ):
        fam.client.app.state.limiter = RateLimiter()
        r = fam.client.post(members_url(fam), json=bad, headers=fam.headers)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", bad


def test_inviting_requires_authentication_and_membership(make_family) -> None:  # type: ignore[no-untyped-def]
    a, b = make_family(), make_family()
    anon = a.client.post(members_url(a), json={"email": unique_email(), "role": "guardian"})
    assert anon.status_code == 401
    cross = a.client.post(
        members_url(b), json={"email": unique_email(), "role": "guardian"}, headers=a.headers
    )
    assert cross.status_code == 404  # another family's id is indistinguishable from nonexistent
    device = device_headers(b.pair_device()[1])
    assert (
        a.client.post(
            members_url(b), json={"email": unique_email(), "role": "guardian"}, headers=device
        ).status_code
        == 401
    )  # a device credential is not a user


def test_invitations_are_rate_limited_per_user(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    fam.client.app.state.limiter = RateLimiter()
    statuses = [
        fam.client.post(
            members_url(fam),
            json={"email": unique_email(), "role": "guardian"},
            headers=fam.headers,
        ).status_code
        for _ in range(11)
    ]
    assert statuses == [201] * 10 + [429]


def test_guardian_can_view_but_not_manage(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    owner = fam.client.get(f"/api/v1/devices/{device_id}", headers=fam.headers).json()[
        "owner_member_id"
    ]
    _, guardian = join(fam, "guardian")

    detail = fam.client.get(f"/api/v1/families/{fam.family_id}", headers=guardian)
    assert detail.status_code == 200 and len(detail.json()["members"]) == 3
    assert [
        f["my_role"]
        for f in fam.client.get("/api/v1/families", headers=guardian).json()["families"]
    ] == ["guardian"]
    assert fam.client.get(f"/api/v1/devices/{device_id}", headers=guardian).status_code == 200
    assert fam.client.get(f"/api/v1/members/{owner}/location", headers=guardian).status_code == 200

    fam.client.app.state.limiter = RateLimiter()
    assert fam.client.post("/api/v1/devices/pairing-code", headers=guardian).status_code == 403
    assert fam.client.delete(f"/api/v1/devices/{device_id}", headers=guardian).status_code == 403
    invite_try = fam.client.post(
        members_url(fam), json={"email": unique_email(), "role": "guardian"}, headers=guardian
    )
    assert invite_try.status_code == 403
    # The device was not revoked by the refused call.
    assert (
        fam.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token)).json()[
            "status"
        ]
        == "active"
    )


def test_guardian_cannot_reach_another_family(make_family) -> None:  # type: ignore[no-untyped-def]
    a, b = make_family(), make_family()
    _, guardian = join(a, "guardian")
    other_device, _, _ = b.pair_device()
    owner = b.client.get(f"/api/v1/devices/{other_device}", headers=b.headers).json()[
        "owner_member_id"
    ]
    assert a.client.get(f"/api/v1/families/{b.family_id}", headers=guardian).status_code == 404
    assert a.client.get(f"/api/v1/devices/{other_device}", headers=guardian).status_code == 404
    assert a.client.get(f"/api/v1/members/{owner}/location", headers=guardian).status_code == 404


def test_invited_parent_has_full_management(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    _, parent2 = join(fam, "parent")
    fam.client.app.state.limiter = RateLimiter()
    assert fam.client.post("/api/v1/devices/pairing-code", headers=parent2).status_code == 201


def test_invited_member_cannot_log_in_with_the_inviters_password(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    email = unique_email("kin")
    assert (
        accept(fam, invite(fam, "guardian", email).json()["invite_code"], email).status_code == 201
    )
    fam.client.app.state.limiter = RateLimiter()
    wrong = fam.client.post("/api/v1/auth/session", json={"email": email, "password": PASSWORD})
    assert wrong.status_code == 401


def test_invitation_audit_trail(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    join(fam, "guardian")
    db.expire_all()
    actions = list(
        db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.family_id == fam.family_id, AuditEvent.action.like("member_%"))
            .order_by(AuditEvent.created_at)
        )
    )
    assert actions == ["member_invited", "member_joined"]
