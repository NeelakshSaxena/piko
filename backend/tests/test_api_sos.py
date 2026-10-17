"""Phase 6: SOS lifecycle, idempotency and authorization, against real PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent, SosIncident

from .conftest import Family, device_headers
from .helpers import batch, child_user_token, iso, location_event
from .test_api_invitations import join

URL = "/api/v1/sos/incidents"


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def sos_body(device_id: str, incident_id: str | None = None, **extra):  # type: ignore[no-untyped-def]
    body = {
        "incident_id": incident_id or str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=5)),
    }
    body.update(extra)
    return body


def raise_sos(fam: Family, device_id: str, token: str, body=None):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.post(URL, json=body or sos_body(device_id), headers=device_headers(token))


def update(fam: Family, incident_id: str, status: str, headers=None, notes=None):  # type: ignore[no-untyped-def]
    reset(fam)
    payload = {"status": status} | ({"notes": notes} if notes else {})
    return fam.client.put(f"{URL}/{incident_id}", json=payload, headers=headers or fam.headers)


def listing(fam: Family, headers=None, **params):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.get(URL, params=params, headers=headers or fam.headers)


def make(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


def test_device_creates_an_open_incident_with_both_timestamps(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    triggered = iso(-timedelta(hours=3))  # queued offline for hours
    body = sos_body(
        device_id, message="Help", triggered_at=triggered,
        location={"latitude": 40.7, "longitude": -74.0, "accuracy_meters": 20},
    )  # fmt: skip
    resp = raise_sos(fam, device_id, token, body)
    out = resp.json()
    assert resp.status_code == 201
    assert out["status"] == "open" and out["incident_id"] == body["incident_id"]
    assert (
        out["message"] == "Help" and out["acknowledged_at"] is None and out["resolved_at"] is None
    )
    assert out["location"]["is_latest_known"] is False
    assert out["location"]["latitude"] == 40.7
    assert "parent_notes" in out and out["parent_notes"] is None
    assert out["received_at"] > out["triggered_at"]  # occurrence kept apart from receipt
    assert out["family_id"] == str(fam.family_id)
    db.expire_all()
    assert db.get(SosIncident, uuid.UUID(body["incident_id"])) is not None


def test_replay_returns_the_same_incident_and_creates_no_second_row(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    body = sos_body(device_id, message="first")
    first = raise_sos(fam, device_id, token, body)
    again = raise_sos(fam, device_id, token, sos_body(device_id, body["incident_id"], message="x"))
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["incident_id"] == first.json()["incident_id"]
    assert again.json()["message"] == "first"  # a replay never rewrites the stored incident
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(SosIncident)
        .where(SosIncident.device_id == uuid.UUID(device_id))
    )
    assert count == 1
    audits = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "sos_created",
            AuditEvent.resource_id == uuid.UUID(body["incident_id"]),
        )
    )
    assert audits == 1


def test_concurrent_duplicate_sends_create_exactly_one_incident(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    body = sos_body(device_id)
    reset(fam)

    def send(_: int) -> int:
        return fam.client.post(URL, json=body, headers=device_headers(token)).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(send, range(6)))
    assert sorted(set(codes)) <= [200, 201] and codes.count(201) == 1
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(SosIncident)
            .where(SosIncident.id == uuid.UUID(body["incident_id"]))
        )
        == 1
    )


def test_incident_id_owned_by_another_device_conflicts(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_a, token_a = make(make_family)
    device_b, token_b, _ = fam.pair_device("Second")
    body = sos_body(device_a)
    assert raise_sos(fam, device_a, token_a, body).status_code == 201
    clash = raise_sos(fam, device_b, token_b, sos_body(device_b, body["incident_id"]))
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "CONFLICT"


def test_creation_authorization(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    other_id = str(uuid.uuid4())
    assert raise_sos(fam, device_id, token, sos_body(other_id)).status_code == 403  # not its id
    reset(fam)
    assert fam.client.post(URL, json=sos_body(device_id)).status_code == 401  # anonymous
    # parents do not raise SOS on a child's behalf (ADR-022)
    assert fam.client.post(URL, json=sos_body(device_id), headers=fam.headers).status_code == 401
    stranger: Family = make_family()
    _s_dev, s_tok, _ = stranger.pair_device()
    assert raise_sos(stranger, device_id, s_tok, sos_body(device_id)).status_code == 403


def test_revoked_device_cannot_raise_sos(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    reset(fam)
    assert fam.client.delete(f"/api/v1/devices/{device_id}", headers=fam.headers).status_code == 204
    assert raise_sos(fam, device_id, token).status_code == 401


def test_validation_rejects_bad_input(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    bad = [
        sos_body(device_id, triggered_at="yesterday"),
        sos_body(device_id, triggered_at="2026-10-16T10:00:00"),
        sos_body(device_id, message="x" * 281),
        sos_body(device_id, location={"latitude": 91, "longitude": 0}),
        sos_body(device_id, location={"latitude": 0, "longitude": 181}),
        sos_body(device_id, location={"latitude": 0, "longitude": 0, "accuracy_meters": -1}),
        sos_body(device_id, status="resolved"),  # unknown field
        sos_body(device_id, incident_id="not-a-uuid"),
    ]
    for body in bad:
        r = raise_sos(fam, device_id, token, body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", body


def test_missing_location_uses_latest_known_and_says_so(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    reset(fam)
    ev = location_event(ago=timedelta(minutes=20), lat=12.5, lon=45.5)
    assert (
        fam.client.post(
            "/api/v1/telemetry/batches", json=batch(device_id, [ev]), headers=device_headers(token)
        ).status_code
        == 202
    )
    out = raise_sos(fam, device_id, token).json()
    assert out["location"]["is_latest_known"] is True
    assert out["location"]["latitude"] == 12.5
    age = out["triggered_at"] > out["location"]["captured_at"]
    assert age  # the position is older than the SOS and is labelled with its own capture time


def test_no_location_at_all_is_reported_as_none(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    assert raise_sos(fam, device_id, token).json()["location"] is None


def test_parent_acknowledges_then_resolves_explicitly(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    acked = update(fam, iid, "acknowledged", notes="calling now")
    assert acked.status_code == 200
    assert acked.json()["status"] == "acknowledged" and acked.json()["resolved_at"] is None
    assert acked.json()["acknowledged_at"] is not None
    # acknowledgement never resolves anything by itself
    assert listing(fam, status="resolved").json()["total_count"] == 0
    assert listing(fam, status="acknowledged").json()["total_count"] == 1
    done = update(fam, iid, "resolved", notes="all safe")
    assert done.json()["status"] == "resolved" and done.json()["resolved_at"] is not None
    assert done.json()["parent_notes"] == "all safe"


def test_repeating_a_state_is_a_noop_and_resolved_never_reopens(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    first = update(fam, iid, "acknowledged").json()
    second = update(fam, iid, "acknowledged", notes="ignored on repeat").json()
    assert first["acknowledged_at"] == second["acknowledged_at"] and second["parent_notes"] is None
    assert update(fam, iid, "resolved").status_code == 200
    again = update(fam, iid, "acknowledged")
    assert again.status_code == 409 and again.json()["error"]["code"] == "CONFLICT"
    assert update(fam, iid, "resolved").status_code == 200  # idempotent repeat
    db.expire_all()
    assert db.get_one(SosIncident, uuid.UUID(iid)).status == "resolved"


def test_open_can_be_resolved_directly_without_a_fake_acknowledgement(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    out = update(fam, iid, "resolved").json()
    assert out["status"] == "resolved" and out["acknowledged_at"] is None


def test_bad_status_values_are_rejected(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    for status in ("open", "deleted", ""):
        assert update(fam, iid, status).status_code == 400


def test_other_families_cannot_read_or_change_incidents(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    stranger: Family = make_family()
    reset(stranger)
    cross = stranger.client.get(f"{URL}/{iid}", headers=stranger.headers)
    ghost = stranger.client.get(f"{URL}/{uuid.uuid4()}", headers=stranger.headers)
    assert cross.status_code == ghost.status_code == 404
    assert cross.json()["error"]["message"] == ghost.json()["error"]["message"]
    assert update(stranger, iid, "resolved", headers=stranger.headers).status_code == 404
    assert update(stranger, iid, "acknowledged", headers=stranger.headers).status_code == 404
    assert listing(stranger).json()["total_count"] == 0
    assert listing(fam).json()["total_count"] == 1
    assert update(fam, iid, "acknowledged").status_code == 200  # still untouched by the stranger


def test_guardian_reads_but_cannot_acknowledge_or_resolve(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    _, guardian = join(fam, "guardian")
    assert listing(fam, headers=guardian).json()["total_count"] == 1
    reset(fam)
    assert fam.client.get(f"{URL}/{iid}", headers=guardian).status_code == 200
    assert update(fam, iid, "acknowledged", headers=guardian).status_code == 403
    assert update(fam, iid, "resolved", headers=guardian).status_code == 403
    assert listing(fam, status="open").json()["total_count"] == 1


def test_child_role_user_cannot_read_or_change(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    kid, _ = child_user_token(app, db, fam.family_id)
    kid_headers = {"Authorization": f"Bearer {kid}"}
    assert listing(fam, headers=kid_headers).status_code == 403
    reset(fam)
    assert fam.client.get(f"{URL}/{iid}", headers=kid_headers).status_code == 403
    assert update(fam, iid, "resolved", headers=kid_headers).status_code == 403


def test_a_device_cannot_acknowledge_or_resolve(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    r = update(fam, iid, "resolved", headers=device_headers(token))
    assert r.status_code == 401
    assert listing(fam).json()["incidents"][0]["status"] == "open"


def test_unauthenticated_requests_are_refused(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    reset(fam)
    assert fam.client.get(URL).status_code == 401
    assert fam.client.get(f"{URL}/{iid}").status_code == 401
    assert fam.client.put(f"{URL}/{iid}", json={"status": "resolved"}).status_code == 401


def test_device_sees_only_its_own_incidents_and_never_parent_notes(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_a, token_a = make(make_family)
    device_b, token_b, _ = fam.pair_device("Second")
    a_id = raise_sos(fam, device_a, token_a).json()["incident_id"]
    b_id = raise_sos(fam, device_b, token_b).json()["incident_id"]
    update(fam, a_id, "acknowledged", notes="private note")
    mine = listing(fam, headers=device_headers(token_a)).json()
    assert [i["incident_id"] for i in mine["incidents"]] == [a_id]
    assert mine["incidents"][0]["status"] == "acknowledged"  # the child learns it was acknowledged
    assert mine["incidents"][0]["parent_notes"] is None
    reset(fam)
    assert fam.client.get(f"{URL}/{b_id}", headers=device_headers(token_a)).status_code == 404
    assert (
        fam.client.get(f"{URL}/{a_id}", headers=device_headers(token_a)).json()["parent_notes"]
        is None
    )


def test_paging_and_status_filter(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    ids = [raise_sos(fam, device_id, token).json()["incident_id"] for _ in range(3)]
    update(fam, ids[0], "resolved")
    page = listing(fam, limit=2).json()
    assert len(page["incidents"]) == 2 and page["has_more"] is True and page["total_count"] == 3
    assert listing(fam, status="open").json()["total_count"] == 2
    assert listing(fam, limit=501).status_code == 400
    assert listing(fam, status="bogus").status_code == 400


def test_audit_records_transitions_without_message_or_coordinates(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    body = sos_body(
        device_id, message="secret words here",
        location={"latitude": 33.123456, "longitude": 44.654321},
    )  # fmt: skip
    iid = raise_sos(fam, device_id, token, body).json()["incident_id"]
    update(fam, iid, "acknowledged", notes="private note")
    update(fam, iid, "resolved")
    listing(fam)
    db.expire_all()
    rows = list(db.scalars(select(AuditEvent).where(AuditEvent.family_id == fam.family_id)))
    actions = [r.action for r in rows if r.resource_type == "incident"]
    assert {"sos_created", "sos_acknowledged", "sos_resolved", "location_accessed"} <= set(actions)
    actor = next(r for r in rows if r.action == "sos_acknowledged")
    assert actor.actor_user_id == fam.user_id
    dump = " ".join(str(r.meta) + str(r.reason) for r in rows)
    for secret in ("secret words", "33.12", "44.65", "private note"):
        assert secret not in dump
