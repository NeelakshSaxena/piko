"""Member history: ordering, paging, filters, authorization, audit hygiene."""

import uuid
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent

from .conftest import Family, device_headers
from .helpers import batch, battery_event, child_user_token, iso, location_event
from .test_api_invitations import join


def member_of(fam: Family, device_id: str) -> str:
    return str(
        fam.client.get(f"/api/v1/devices/{device_id}", headers=fam.headers).json()[
            "owner_member_id"
        ]
    )


def upload(fam: Family, device_id: str, token: str, events: list[dict]) -> None:  # type: ignore[type-arg]
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post(
        "/api/v1/telemetry/batches", json=batch(device_id, events), headers=device_headers(token)
    )
    assert resp.status_code == 202, resp.text


def history(fam: Family, member: str, headers: dict[str, str] | None = None, **params):  # type: ignore[no-untyped-def]
    fam.client.app.state.limiter = RateLimiter()
    return fam.client.get(
        f"/api/v1/members/{member}/history", params=params, headers=headers or fam.headers
    )


def seeded(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    events = [
        location_event(ago=timedelta(minutes=m), lat=10 + m / 100, lon=20.0) for m in (1, 2, 3, 40)
    ] + [battery_event(70, ago=timedelta(minutes=5))]
    upload(fam, device_id, token, events)
    return fam, device_id, token, member_of(fam, device_id), events


def test_history_is_newest_first_and_labels_freshness(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _, _, member, _ = seeded(make_family)
    resp = history(fam, member)
    body = resp.json()
    assert resp.status_code == 200 and body["total_count"] == 5 and body["has_more"] is False
    times = [h["occurred_at"] for h in body["history"]]
    assert times == sorted(times, reverse=True)
    assert body["history"][0]["event_type"] == "location"
    assert body["history"][0]["freshness"] == "fresh"
    assert body["history"][-1]["freshness"] == "stale"  # 40 minutes old is never "fresh"
    assert body["device_status"] == "online"
    assert set(body["history"][0]) == {
        "event_id", "occurred_at", "received_at", "event_type", "freshness", "data",
    }  # fmt: skip


def test_paging_filters_and_window(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _, _, member, _ = seeded(make_family)
    first = history(fam, member, limit=2).json()
    assert len(first["history"]) == 2 and first["has_more"] is True and first["total_count"] == 5
    third = history(fam, member, limit=2, offset=4).json()
    assert len(third["history"]) == 1 and third["has_more"] is False
    assert {
        h["event_type"] for h in history(fam, member, event_type="battery").json()["history"]
    } == {"battery"}
    recent = history(fam, member, start_time=iso(-timedelta(minutes=10))).json()
    assert recent["total_count"] == 4  # the 40-minute-old fix is outside the window


def test_bad_parameters_are_client_errors(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _, _, member, _ = seeded(make_family)
    for params in (
        {"limit": 501}, {"limit": 0}, {"offset": -1}, {"event_type": "sos"},
        {"start_time": "2026-10-16T10:00:00"},  # no timezone
        {"start_time": iso(timedelta(hours=1)), "end_time": iso()},  # start after end
        {"start_time": "yesterday"},
    ):  # fmt: skip
        r = history(fam, member, **params)
        assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", params


def test_a_paired_child_that_never_uploaded_has_an_empty_history(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, _, _ = fam.pair_device()
    body = history(fam, member_of(fam, device_id)).json()
    assert body["history"] == [] and body["total_count"] == 0 and body["has_more"] is False
    assert body["device_status"] == "unknown"  # never heard from: unknown, not offline


def test_other_families_cannot_read_it_and_the_error_does_not_leak(make_family) -> None:  # type: ignore[no-untyped-def]
    _, _, _, member, _ = seeded(make_family)
    stranger: Family = make_family()
    cross = history(stranger, member)
    ghost = history(stranger, str(uuid.uuid4()))
    assert cross.status_code == ghost.status_code == 404
    assert cross.json()["error"]["message"] == ghost.json()["error"]["message"]


def test_guardian_can_read_but_child_and_device_cannot(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _, token, member, _ = seeded(make_family)
    _, guardian = join(fam, "guardian")
    assert history(fam, member, headers=guardian).status_code == 200
    kid_token, _ = child_user_token(app, db, fam.family_id)
    assert history(fam, member, headers={"Authorization": f"Bearer {kid_token}"}).status_code == 403
    assert history(fam, member, headers=device_headers(token)).status_code == 401
    assert fam.client.get(f"/api/v1/members/{member}/history").status_code == 401  # anonymous


def test_audit_records_the_read_but_never_coordinates(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _, _, member, _ = seeded(make_family)
    history(fam, member)
    db.expire_all()
    rows = db.scalars(
        select(AuditEvent).where(
            AuditEvent.family_id == fam.family_id, AuditEvent.action == "location_accessed"
        )
    ).all()
    assert rows and rows[-1].meta == {"scope": "history", "returned": 5}
    blob = "\n".join(db.execute(text("SELECT t::text FROM audit_events t")).scalars().all())
    assert "latitude" not in blob and "longitude" not in blob


def test_history_is_rate_limited(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _, _, member, _ = seeded(make_family)
    fam.client.app.state.limiter = RateLimiter()
    codes = [
        fam.client.get(f"/api/v1/members/{member}/history", headers=fam.headers).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429
