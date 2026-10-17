"""Authorization: default-deny, cross-family isolation, role checks, revocation."""

import uuid

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.routes import router
from app.db.models import (
    AuditEvent,
    Device,
    DeviceCredential,
    FamilyMembership,
)
from app.db.models import (
    Family as FamilyRow,
)

from .conftest import Family, device_headers
from .helpers import child_user_token

PUBLIC = {
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/session"),  # credentials in body
    ("POST", "/api/v1/devices/pair"),  # pairing code in body
    ("POST", "/api/v1/invitations/accept"),  # invite code + invited email in body (ADR-017)
    ("POST", "/api/v1/internal/outbox/run"),  # shared-secret header (ADR-023), tested separately
    ("GET", "/api/v1/internal/outbox/health"),  # same
    ("POST", "/api/v1/internal/retention/run"),  # same
}


def not_visible(resp) -> dict:  # type: ignore[no-untyped-def, type-arg]
    assert resp.status_code == 404, resp.text
    err = resp.json()["error"]
    assert err["code"] == "NOT_FOUND_OR_NOT_VISIBLE"
    return {k: v for k, v in err.items() if k not in ("request_id", "timestamp")}


def test_every_route_denies_unauthenticated_requests_by_default(client: TestClient) -> None:
    """New routes are private unless deliberately added to PUBLIC above."""
    checked = 0
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path.replace("{device_id}", str(uuid.uuid4()))
        path = path.replace("{family_id}", str(uuid.uuid4())).replace(
            "{member_id}", str(uuid.uuid4())
        )
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in PUBLIC:
                continue
            resp = client.request(method, path)
            assert resp.status_code == 401, f"{method} {route.path} -> {resp.status_code}"
            assert resp.json()["error"]["code"] == "AUTH_REQUIRED"
            checked += 1
    assert checked >= 9


def test_parent_cannot_read_another_familys_data(make_family) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    a_device, _, _ = a.pair_device()
    ghost = not_visible(b.client.get(f"/api/v1/families/{uuid.uuid4()}", headers=b.headers))
    # Guessing A's real id is indistinguishable from guessing a nonexistent one.
    assert not_visible(b.client.get(f"/api/v1/families/{a.family_id}", headers=b.headers)) == ghost
    assert not_visible(b.client.get(f"/api/v1/devices/{a_device}", headers=b.headers)) == ghost
    assert not_visible(b.client.delete(f"/api/v1/devices/{a_device}", headers=b.headers)) == ghost


def test_cross_family_member_location_is_not_visible(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    a_device, _, _ = a.pair_device()
    member_id = db.scalar(select(Device.owner_member_id).where(Device.id == uuid.UUID(a_device)))
    ghost = not_visible(b.client.get(f"/api/v1/members/{uuid.uuid4()}/location", headers=b.headers))
    assert (
        not_visible(b.client.get(f"/api/v1/members/{member_id}/location", headers=b.headers))
        == ghost
    )


def test_failed_cross_family_delete_leaves_device_intact(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    device_id, token, _ = a.pair_device()
    b.client.delete(f"/api/v1/devices/{device_id}", headers=b.headers)
    assert db.get(Device, uuid.UUID(device_id)).status == "active"  # type: ignore[union-attr]
    assert (
        a.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token)).status_code
        == 200
    )


def test_pairing_code_binds_the_device_to_the_issuers_family_only(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    device_id, _, _ = b.pair_device()
    assert db.get(Device, uuid.UUID(device_id)).family_id == b.family_id  # type: ignore[union-attr]
    ids_a = [
        d["id"]
        for d in a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers).json()[
            "devices"
        ]
    ]
    assert device_id not in ids_a


def test_family_listing_only_contains_own_families(make_family) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    make_family("B")
    body = a.client.get("/api/v1/families", headers=a.headers).json()
    assert [f["id"] for f in body["families"]] == [str(a.family_id)]
    f = body["families"][0]
    assert f["my_role"] == "parent" and f["member_count"] == 1 and f["device_count"] == 0
    assert set(f) == {
        "id",
        "name",
        "created_at",
        "member_count",
        "device_count",
        "my_role",
        "status",
    }


def test_family_detail_contract_shape_and_hides_child_email(make_family) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("Fam")
    device_id, _, _ = a.pair_device("Kid Phone")
    body = a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers).json()
    assert body["my_role"] == "parent" and len(body["members"]) == 2
    child = next(m for m in body["members"] if m["role"] == "child")
    assert child["email"] is None and child["name"] == "Kid Phone"
    parent = next(m for m in body["members"] if m["role"] == "parent")
    assert parent["email"] == a.email
    (dev,) = body["devices"]
    assert dev["id"] == device_id and dev["device_type"] == "android" and dev["status"] == "active"


# ---- membership changes take effect on the next request ----
def test_revoked_membership_loses_access_immediately(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    assert a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers).status_code == 200
    db.execute(
        update(FamilyMembership)
        .where(FamilyMembership.family_id == a.family_id, FamilyMembership.user_id == a.user_id)
        .values(status="revoked")
    )
    db.commit()
    resp = a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers)
    # L-4: a revoked member sees the same 404 as a stranger, so ids of a former family do not leak.
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "NOT_FOUND_OR_NOT_VISIBLE"
    assert a.client.get("/api/v1/families", headers=a.headers).json() == {"families": []}
    # no family is visible to a revoked member, so there is nothing to create a code in (L-4)
    assert a.client.post("/api/v1/devices/pairing-code", headers=a.headers).status_code == 404


def test_archived_family_is_not_visible(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    db.execute(update(FamilyRow).where(FamilyRow.id == a.family_id).values(status="archived"))
    db.commit()
    not_visible(a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers))


# ---- role checks (child-role principals) ----
def test_child_role_cannot_use_parent_operations(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    device_id, _, _ = a.pair_device()
    token, kid_member = child_user_token(app, db, a.family_id)
    h = {"Authorization": f"Bearer {token}"}
    assert a.client.get("/api/v1/families", headers=h).json() == {"families": []}
    assert a.client.post("/api/v1/devices/pairing-code", headers=h).status_code == 403
    assert a.client.delete(f"/api/v1/devices/{device_id}", headers=h).status_code == 403
    assert a.client.get(f"/api/v1/members/{kid_member}/location", headers=h).status_code == 403
    # A child sees the family but only itself, and cannot see devices it does not own.
    detail = a.client.get(f"/api/v1/families/{a.family_id}", headers=h).json()
    assert [m["role"] for m in detail["members"]] == ["child"] and detail["devices"] == []
    assert not_visible(a.client.get(f"/api/v1/devices/{device_id}", headers=h))


# ---- device principal scope ----
def test_device_sees_only_itself(make_family) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    d1, t1, _ = a.pair_device("One")
    d2, _, _ = a.pair_device("Two")
    ok = a.client.get(f"/api/v1/devices/{d1}", headers=device_headers(t1))
    assert ok.status_code == 200 and ok.json()["id"] == d1
    assert ok.json()["connectivity_status"] == "unknown" and ok.json()["battery_percent"] is None
    not_visible(a.client.get(f"/api/v1/devices/{d2}", headers=device_headers(t1)))


def test_revoking_a_device_kills_its_credential_and_keeps_the_record(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    device_id, token, _ = a.pair_device()
    assert a.client.delete(f"/api/v1/devices/{device_id}", headers=a.headers).status_code == 204
    resp = a.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token))
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "AUTH_INVALID"
    device = db.get(Device, uuid.UUID(device_id))
    assert device is not None and device.status == "revoked" and device.revoked_at is not None
    cred = db.scalar(select(DeviceCredential).where(DeviceCredential.device_id == device.id))
    assert cred is not None and cred.status == "revoked"
    assert (
        a.client.delete(f"/api/v1/devices/{device_id}", headers=a.headers).status_code == 204
    )  # idempotent
    assert db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.action == "device_revoked", AuditEvent.resource_id == device.id
        )
    )
    # The parent still sees the revoked device, flagged as revoked, in the family view.
    listed = a.client.get(f"/api/v1/families/{a.family_id}", headers=a.headers).json()["devices"]
    assert listed[0]["status"] == "revoked"


def test_unknown_device_token_rejected(client: TestClient) -> None:
    resp = client.get(f"/api/v1/devices/{uuid.uuid4()}", headers=device_headers("pkd_" + "x" * 43))
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "AUTH_INVALID"
