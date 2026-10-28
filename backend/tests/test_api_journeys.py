"""Journeys (ADR-026): device ownership, idempotent last-edit-wins upserts, tombstones, event batches."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import JourneyEvent
from app.services.retention import RetentionService

from .conftest import Family, device_headers
from .helpers import iso


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def leg(leg_id: uuid.UUID | None = None, **extra):  # type: ignore[no-untyped-def]
    body = {
        "id": str(leg_id or uuid.uuid4()),
        "mode": "TRAIN",
        "origin": "Katpadi",
        "destination": "Bengaluru",
        "departure_at": "2026-11-01T07:45:00+05:30",
        "departure_zone": "Asia/Kolkata",
        "arrival_at": "2026-11-01T11:30:00+05:30",
        "arrival_zone": "Asia/Kolkata",
    }
    body.update(extra)
    return body


def journey(legs=None, age: timedelta = timedelta(minutes=5), **extra):  # type: ignore[no-untyped-def]
    body = {
        "title": "Vellore to Lucknow",
        "status": "DRAFT",
        "created_at": iso(timedelta(hours=-1)),
        "updated_at": iso(-age),
        "legs": [leg(), leg()] if legs is None else legs,
    }
    body.update(extra)
    return body


def event(kind: str = "tracking_started", event_id: uuid.UUID | None = None, **extra):  # type: ignore[no-untyped-def]
    body = {
        "event_id": str(event_id or uuid.uuid4()),
        "event_type": kind,
        "occurred_at": iso(-timedelta(seconds=30)),
        "data": {},
    }
    body.update(extra)
    return body


def make(make_family):  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    return fam, device_headers(token)


def put(fam: Family, headers, jid, body):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.put(f"/api/v1/journeys/{jid}", json=body, headers=headers)


def test_create_and_read_back_in_order(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    legs = [leg(mode="FLIGHT", service_number="6E 123"), leg(mode="TAXI"), leg(mode="WALKING")]
    r = put(fam, h, jid, journey(legs))
    assert r.status_code == 200 and r.json()["applied"] is True
    got = fam.client.get(f"/api/v1/journeys/{jid}", headers=h).json()
    assert [x["id"] for x in got["legs"]] == [x["id"] for x in legs]
    assert [x["sequence"] for x in got["legs"]] == [0, 1, 2]
    assert got["legs"][0]["service_number"] == "6E 123"
    assert got["legs"][0]["departure_zone"] == "Asia/Kolkata"
    assert [j["id"] for j in fam.client.get("/api/v1/journeys", headers=h).json()["journeys"]] == [
        str(jid)
    ]


def test_replay_and_older_edits_do_not_overwrite_newer_state(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    legs = [leg(), leg(), leg()]
    newer = journey(legs, age=timedelta(minutes=1), title="Newest")
    assert put(fam, h, jid, newer).json()["applied"] is True
    # The same upload again (lost acknowledgement) and an older offline edit both change nothing.
    for body in (newer, journey(legs[:1], age=timedelta(minutes=30), title="Stale")):
        r = put(fam, h, jid, body)
        assert r.status_code == 200 and r.json()["applied"] is False
        assert r.json()["journey"]["title"] == "Newest" and len(r.json()["journey"]["legs"]) == 3
    # A genuinely newer edit with the legs reordered wins.
    reordered = journey([legs[2], legs[0], legs[1]], age=timedelta(seconds=5), title="Reordered")
    r = put(fam, h, jid, reordered)
    assert r.json()["applied"] is True
    assert [x["id"] for x in r.json()["journey"]["legs"]] == [
        legs[2]["id"],
        legs[0]["id"],
        legs[1]["id"],
    ]


def test_a_clock_in_the_future_cannot_win_every_later_edit(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    r = put(fam, h, jid, journey(age=timedelta(days=-3), title="Future"))
    assert r.json()["applied"] is True
    stored = datetime.fromisoformat(r.json()["journey"]["updated_at"])
    assert stored <= datetime.now(UTC)
    assert (
        put(fam, h, jid, journey(age=timedelta(seconds=-1), title="Later")).json()["applied"]
        is True
    )


def test_only_the_owning_device_can_touch_a_journey(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, owner = make(make_family)
    jid = uuid.uuid4()
    assert put(fam, owner, jid, journey()).status_code == 200
    _id2, token2, _ = fam.pair_device("Second Phone")  # same family, different device
    other_family, stranger = make(make_family)
    for who, headers in ((fam, device_headers(token2)), (other_family, stranger)):
        reset(who)
        c = who.client
        url = f"/api/v1/journeys/{jid}"
        assert c.get(url, headers=headers).status_code == 404
        assert put(who, headers, jid, journey(title="Hijack")).status_code == 404
        assert c.delete(url, headers=headers).status_code == 404
        assert (
            c.post(
                url + "/events",
                json={"batch_id": str(uuid.uuid4()), "events": [event()]},
                headers=headers,
            ).status_code
            == 404
        )
        assert c.get(url + "/events", headers=headers).status_code == 404
        assert c.get("/api/v1/journeys", headers=headers).json()["journeys"] == []
    assert (
        fam.client.get(f"/api/v1/journeys/{jid}", headers=owner).json()["title"]
        == "Vellore to Lucknow"
    )


def test_second_device_in_family_lists_only_its_own(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, first = make(make_family)
    put(fam, first, uuid.uuid4(), journey())
    _id2, token2, _ = fam.pair_device("Second Phone")
    reset(fam)
    assert (
        fam.client.get("/api/v1/journeys", headers=device_headers(token2)).json()["journeys"] == []
    )


def test_parents_and_anonymous_callers_get_nothing(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    put(fam, h, jid, journey())
    reset(fam)
    # A parent in the same family is not the owner: membership grants no access.
    for call in (
        lambda: fam.client.get("/api/v1/journeys", headers=fam.headers),
        lambda: fam.client.get(f"/api/v1/journeys/{jid}", headers=fam.headers),
        lambda: fam.client.put(f"/api/v1/journeys/{jid}", json=journey(), headers=fam.headers),
        lambda: fam.client.get(f"/api/v1/journeys/{jid}/events", headers=fam.headers),
    ):
        assert call().status_code == 401
    assert fam.client.get("/api/v1/journeys").status_code == 401


def test_delete_is_idempotent_and_cannot_be_undone_by_a_late_upload(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    put(fam, h, jid, journey())
    fam.client.post(
        f"/api/v1/journeys/{jid}/events",
        json={"batch_id": str(uuid.uuid4()), "events": [event()]},
        headers=h,
    )
    assert fam.client.delete(f"/api/v1/journeys/{jid}", headers=h).status_code == 204
    assert fam.client.delete(f"/api/v1/journeys/{jid}", headers=h).status_code == 204
    assert fam.client.get(f"/api/v1/journeys/{jid}", headers=h).status_code == 404
    assert fam.client.get("/api/v1/journeys", headers=h).json()["journeys"] == []
    assert put(fam, h, jid, journey(title="Late")).status_code == 409
    # Deleting an id the server never saw also leaves a tombstone.
    ghost = uuid.uuid4()
    assert fam.client.delete(f"/api/v1/journeys/{ghost}", headers=h).status_code == 204
    assert put(fam, h, ghost, journey()).status_code == 409


def test_deleting_removes_the_content(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import Journey, JourneyLeg

    fam, h = make(make_family)
    jid = uuid.uuid4()
    put(fam, h, jid, journey())
    fam.client.delete(f"/api/v1/journeys/{jid}", headers=h)
    db.expire_all()
    row = db.get(Journey, jid)
    assert row is not None and row.title == "" and row.deleted_at is not None
    assert (
        db.scalar(select(func.count()).select_from(JourneyLeg).where(JourneyLeg.journey_id == jid))
        == 0
    )


def test_validation(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    shared = uuid.uuid4()
    bad = [
        journey(legs=[leg(departure_zone=None)]),  # a time without its zone
        journey(legs=[leg(departure_at="2026-11-01T07:45:00")]),  # no offset
        journey(legs=[leg(), leg()] * 11),  # 22 legs
        journey(legs=[leg(shared), leg(shared)]),  # repeated leg id
        journey(legs=[leg(mode="SPACESHIP")]),
        journey(legs=[leg(origin="")]),
        journey(legs=[leg(departure_zone="Not a zone!")]),
        journey(title=" "),
        journey(status="ACTIVE"),
        journey(extra_field=1),
    ]
    for body in bad:
        r = put(fam, h, jid, body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", body
    assert put(fam, h, jid, journey(legs=[])).status_code == 200  # a draft may have no legs


def test_a_leg_id_cannot_be_borrowed_from_another_journey(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    lid = uuid.uuid4()
    assert put(fam, h, uuid.uuid4(), journey([leg(lid)])).status_code == 200
    assert put(fam, h, uuid.uuid4(), journey([leg(lid)])).status_code == 409


def test_event_batches_are_idempotent(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    put(fam, h, jid, journey())
    url = f"/api/v1/journeys/{jid}/events"
    first, second = (
        event("tracking_started"),
        event("observation", data={"battery_percent": 41, "connected": False}),
    )
    batch = {"batch_id": str(uuid.uuid4()), "events": [first, second]}
    reset(fam)
    r = fam.client.post(url, json=batch, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "accepted"
    assert sorted(r.json()["accepted_event_ids"]) == sorted([first["event_id"], second["event_id"]])
    # The same batch again (acknowledgement lost): nothing is stored twice.
    r = fam.client.post(url, json=batch, headers=h)
    assert r.json()["accepted_event_ids"] == [] and len(r.json()["duplicate_event_ids"]) == 2
    listed = fam.client.get(url, headers=h).json()
    assert listed["has_more"] is False
    assert {e["event_id"] for e in listed["events"]} == {first["event_id"], second["event_id"]}


def test_event_validation_and_isolation(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    a, b = uuid.uuid4(), uuid.uuid4()
    put(fam, h, a, journey())
    put(fam, h, b, journey())
    reset(fam)
    shared = event("tracking_started")
    fam.client.post(
        f"/api/v1/journeys/{a}/events",
        json={"batch_id": str(uuid.uuid4()), "events": [shared]},
        headers=h,
    )
    # The same event id under another journey is refused, not silently merged.
    r = fam.client.post(
        f"/api/v1/journeys/{b}/events",
        json={"batch_id": str(uuid.uuid4()), "events": [shared]},
        headers=h,
    )
    assert (
        r.json()["status"] == "partial"
        and r.json()["rejected_events"][0]["event_id"] == shared["event_id"]
    )
    # Bad timestamp and oversize data reject only that event.
    mixed = {
        "batch_id": str(uuid.uuid4()),
        "events": [
            event(occurred_at="yesterday"),
            event(data={"k": "x" * 2000}),
            event("tracking_paused"),
        ],
    }
    r = fam.client.post(f"/api/v1/journeys/{b}/events", json=mixed, headers=h)
    assert len(r.json()["rejected_events"]) == 2 and len(r.json()["accepted_event_ids"]) == 1
    # Unknown types, nested data and empty batches are request errors.
    for body in (
        {"batch_id": str(uuid.uuid4()), "events": [event("self_destruct")]},
        {"batch_id": str(uuid.uuid4()), "events": [event(data={"a": {"b": 1}})]},
        {"batch_id": str(uuid.uuid4()), "events": []},
    ):
        assert (
            fam.client.post(f"/api/v1/journeys/{b}/events", json=body, headers=h).status_code == 400
        )


def test_old_journey_events_are_retained_for_ninety_days_only(
    make_family, db: Session, app
) -> None:  # type: ignore[no-untyped-def]
    fam, h = make(make_family)
    jid = uuid.uuid4()
    put(fam, h, jid, journey())
    from app.db.models import Device

    dev = db.scalars(select(Device).where(Device.family_id == fam.family_id)).first()
    assert dev is not None
    now = datetime.now(UTC)
    old, fresh = uuid.uuid4(), uuid.uuid4()
    for eid, days in ((old, 100), (fresh, 1)):
        db.add(
            JourneyEvent(
                id=eid, journey_id=jid, device_id=dev.id, event_type="observation",
                occurred_at=now - timedelta(days=days), received_at=now - timedelta(days=days), payload={},
            )
        )  # fmt: skip
    db.commit()
    RetentionService(app.state.settings).run(app.state.session_factory, apply=True)
    db.expire_all()
    assert db.get(JourneyEvent, old) is None
    assert db.get(JourneyEvent, fresh) is not None
