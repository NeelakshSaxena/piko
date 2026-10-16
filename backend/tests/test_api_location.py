"""Latest location with honest freshness: fresh / stale / unknown, and who may see it."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent, Device

from .conftest import Family, device_headers
from .helpers import batch, location_event


def member_of(db: Session, device_id: str) -> uuid.UUID:
    member = db.scalar(select(Device.owner_member_id).where(Device.id == uuid.UUID(device_id)))
    assert member is not None
    return member


def push(fam: Family, device_id: str, token: str, events):  # type: ignore[no-untyped-def]
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post(
        "/api/v1/telemetry/batches", json=batch(device_id, events), headers=device_headers(token)
    )
    assert resp.status_code == 202 and resp.json()["rejected_events"] == [], resp.text


def get_location(fam: Family, member: uuid.UUID):  # type: ignore[no-untyped-def]
    fam.client.app.state.limiter = RateLimiter()
    return fam.client.get(f"/api/v1/members/{member}/location", headers=fam.headers)


def test_fresh_location_includes_coordinates_accuracy_and_both_timestamps(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(
        fam,
        device_id,
        token,
        [location_event(ago=timedelta(seconds=20), lat=40.7128, lon=-74.006, accuracy=15)],
    )
    resp = get_location(fam, member_of(db, device_id))
    body = resp.json()
    assert resp.status_code == 200
    assert body["available"] is True and body["freshness"] == "fresh"
    assert 15 <= body["freshness_seconds"] <= 120
    assert body["coordinates"] == {"latitude": 40.7128, "longitude": -74.006}
    assert body["accuracy_meters"] == 15 and body["device_status"] == "online"
    assert body["device_id"] == device_id and body["occurred_at"] and body["received_at"]


def test_older_location_is_labelled_stale_not_live(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(fam, device_id, token, [location_event(ago=timedelta(minutes=45))])
    body = get_location(fam, member_of(db, device_id)).json()
    assert body["available"] is True and body["freshness"] == "stale"
    assert 2600 <= body["freshness_seconds"] <= 2800
    assert "coordinates" in body


def test_location_older_than_24h_is_withheld_as_unknown(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(fam, device_id, token, [location_event(ago=timedelta(hours=30), lat=12.3456, lon=65.4321)])
    resp = get_location(fam, member_of(db, device_id))
    body = resp.json()
    assert body["available"] is False and body["freshness"] == "unknown"
    assert "coordinates" not in body and "accuracy_meters" not in body
    assert "12.3456" not in resp.text and "65.4321" not in resp.text


def test_no_data_reports_unknown_not_an_error_or_null_coordinates(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, _, _ = fam.pair_device()
    body = get_location(fam, member_of(db, device_id)).json()
    assert (
        body["available"] is False
        and body["freshness"] == "unknown"
        and body["device_status"] == "unknown"
    )
    assert body.get("freshness_seconds") is None
    assert "coordinates" not in body


def test_silent_device_is_reported_offline_and_old_data_stays_stale(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    from sqlalchemy import update

    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(fam, device_id, token, [location_event(ago=timedelta(minutes=20))])
    db.execute(
        update(Device)
        .where(Device.id == uuid.UUID(device_id))
        .values(last_activity_at=datetime.now(UTC) - timedelta(minutes=20))
    )
    db.commit()
    body = get_location(fam, member_of(db, device_id)).json()
    assert body["device_status"] == "offline" and body["freshness"] == "stale"


def test_delayed_older_event_does_not_make_location_look_older(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(fam, device_id, token, [location_event(ago=timedelta(seconds=10), lat=1.5)])
    push(fam, device_id, token, [location_event(ago=timedelta(hours=3), lat=9.5)])
    body = get_location(fam, member_of(db, device_id)).json()
    assert body["freshness"] == "fresh" and body["coordinates"]["latitude"] == 1.5


def test_other_family_cannot_see_the_location_and_gets_no_hint_it_exists(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    device_id, token, _ = a.pair_device()
    push(a, device_id, token, [location_event()])
    real = get_location(b, member_of(db, device_id))
    ghost = get_location(b, uuid.uuid4())
    assert real.status_code == ghost.status_code == 404
    assert (
        real.json()["error"]["code"] == ghost.json()["error"]["code"] == "NOT_FOUND_OR_NOT_VISIBLE"
    )
    assert "40.71" not in real.text


def test_device_credential_cannot_read_locations(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    resp = fam.client.get(
        f"/api/v1/members/{member_of(db, device_id)}/location", headers=device_headers(token)
    )
    assert resp.status_code == 401


def test_location_reads_are_audited_without_coordinates(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    push(fam, device_id, token, [location_event(lat=40.7128)])
    member = member_of(db, device_id)
    get_location(fam, member)
    row = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "location_accessed", AuditEvent.resource_id == member
        )
    )
    assert row is not None and row.actor_user_id == fam.user_id and row.family_id == fam.family_id
    assert "40.71" not in str(row.meta) and "40.71" not in str(row.reason)


def test_location_endpoint_is_rate_limited_per_user(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, _, _ = fam.pair_device()
    member = member_of(db, device_id)
    fam.client.app.state.limiter = RateLimiter()
    path = f"/api/v1/members/{member}/location"
    codes = [fam.client.get(path, headers=fam.headers).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
