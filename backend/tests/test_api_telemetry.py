"""Phase 3: idempotent ingestion and offline reconciliation, against real PostgreSQL."""

import gzip
import json
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import DeviceLatestState, TelemetryEvent

from .conftest import Family, device_headers
from .helpers import batch, battery_event, iso, location_event

URL = "/api/v1/telemetry/batches"


def send(fam: Family, device_id: str, token: str, events, batch_id=None, reset=True):  # type: ignore[no-untyped-def]
    if reset:
        fam.client.app.state.limiter = RateLimiter()
    return fam.client.post(
        URL, json=batch(device_id, events, batch_id), headers=device_headers(token)
    )


@pytest.fixture
def paired(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


def stored_ids(db: Session, device_id: str) -> set[uuid.UUID]:
    db.expire_all()
    return set(
        db.scalars(
            select(TelemetryEvent.id).where(TelemetryEvent.device_id == uuid.UUID(device_id))
        )
    )


def latest(db: Session, device_id: str) -> DeviceLatestState | None:
    db.expire_all()
    return db.get(DeviceLatestState, uuid.UUID(device_id))


# 1 -----------------------------------------------------------------------------------------
def test_new_event_is_accepted_and_stored_with_both_timestamps(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event(ago=timedelta(minutes=3))
    resp = send(fam, device_id, token, [ev])
    body = resp.json()
    assert resp.status_code == 202
    assert body == {
        "batch_id": body["batch_id"], "status": "accepted", "accepted_event_ids": [ev["event_id"]],
        "duplicate_event_ids": [], "rejected_events": [],
    }  # fmt: skip
    row = db.get(TelemetryEvent, (uuid.UUID(device_id), uuid.UUID(ev["event_id"])))
    assert row is not None and row.family_id == fam.family_id and row.event_type == "location"
    assert row.received_at - row.occurred_at >= timedelta(minutes=2, seconds=50)  # kept separate
    assert row.data == {"latitude": 40.7128, "longitude": -74.006, "accuracy_meters": 15.0}


# 2 -----------------------------------------------------------------------------------------
def test_same_event_in_another_batch_is_a_duplicate_not_new_history(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event()
    send(fam, device_id, token, [ev])
    resp = send(fam, device_id, token, [ev])  # new batch_id, same event_id
    body = resp.json()
    assert resp.status_code == 202
    assert body["accepted_event_ids"] == [] and body["duplicate_event_ids"] == [ev["event_id"]]
    assert len(stored_ids(db, device_id)) == 1


def test_event_repeated_inside_one_batch_is_reported_exactly_once(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event()
    body = send(fam, device_id, token, [ev, ev]).json()
    assert body["accepted_event_ids"] == [ev["event_id"]] and body["status"] == "accepted"
    assert body["duplicate_event_ids"] == [] and body["rejected_events"] == []
    assert len(stored_ids(db, device_id)) == 1


def test_replaying_the_same_batch_returns_the_same_acknowledgement(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    events = [location_event(ago=timedelta(seconds=30 * i)) for i in range(5)]
    bid = str(uuid.uuid4())
    first = send(fam, device_id, token, events, bid).json()
    second = send(fam, device_id, token, events, bid).json()
    assert first == second and len(first["accepted_event_ids"]) == 5
    assert len(stored_ids(db, device_id)) == 5


def test_replay_after_partial_success_is_stable(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    good, bad = location_event(), location_event(lat=999)
    bid = str(uuid.uuid4())
    first = send(fam, device_id, token, [good, bad], bid).json()
    second = send(fam, device_id, token, [good, bad], bid).json()
    assert first == second
    assert second["accepted_event_ids"] == [good["event_id"]]
    assert [r["event_id"] for r in second["rejected_events"]] == [bad["event_id"]]


# 3 -----------------------------------------------------------------------------------------
def test_older_delayed_event_is_stored_but_never_overwrites_newer_latest_state(
    paired, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    newer = location_event(ago=timedelta(seconds=30), lat=10.0, lon=20.0)
    older = location_event(
        ago=timedelta(hours=5), lat=-33.0, lon=151.0
    )  # arrives late, offline backlog
    send(fam, device_id, token, [newer])
    body = send(fam, device_id, token, [older]).json()
    assert body["accepted_event_ids"] == [older["event_id"]]  # history is preserved
    assert stored_ids(db, device_id) == {uuid.UUID(newer["event_id"]), uuid.UUID(older["event_id"])}
    state = latest(db, device_id)
    assert (
        state is not None
        and float(state.location_latitude) == 10.0
        and float(state.location_longitude) == 20.0
    )  # type: ignore[arg-type]


def test_newer_event_after_older_does_advance_latest_state(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    send(fam, device_id, token, [location_event(ago=timedelta(hours=1), lat=1.0)])
    send(fam, device_id, token, [location_event(ago=timedelta(seconds=5), lat=2.0)])
    assert float(latest(db, device_id).location_latitude) == 2.0  # type: ignore[union-attr, arg-type]


def test_equal_timestamps_keep_the_first_writer(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    a, b = location_event(lat=1.0), location_event(lat=2.0)
    b["occurred_at"] = a["occurred_at"]
    send(fam, device_id, token, [a])
    send(fam, device_id, token, [b])
    assert float(latest(db, device_id).location_latitude) == 1.0  # type: ignore[union-attr, arg-type]


def test_state_groups_advance_independently(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    send(
        fam,
        device_id,
        token,
        [location_event(ago=timedelta(minutes=1)), battery_event(80, timedelta(minutes=10))],
    )
    send(fam, device_id, token, [battery_event(70, timedelta(minutes=1))])  # newer battery
    send(fam, device_id, token, [location_event(ago=timedelta(hours=2), lat=5.0)])  # stale location
    s = latest(db, device_id)
    assert s is not None and s.battery_percent == 70 and float(s.location_latitude) == 40.7128  # type: ignore[arg-type]


def test_shuffled_offline_backlog_converges_to_the_newest_state(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    # Three days offline: older than 24h but inside the retention window, so none are dropped.
    events = [
        location_event(ago=timedelta(hours=72) - timedelta(minutes=17 * i), lat=i / 10, lon=-i / 10)
        for i in range(60)
    ]
    newest_lat = max(e["data"]["latitude"] for e in events)
    random.Random(7).shuffle(events)
    for chunk in (events[:25], events[25:45], events[45:]):
        resp = send(fam, device_id, token, chunk)
        assert resp.status_code == 202 and resp.json()["rejected_events"] == []
    assert len(stored_ids(db, device_id)) == 60
    assert float(latest(db, device_id).location_latitude) == pytest.approx(newest_lat)  # type: ignore[union-attr, arg-type]


# 4 -----------------------------------------------------------------------------------------
def test_partial_batch_has_an_unambiguous_per_event_result(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    stored = location_event()
    send(fam, device_id, token, [stored])
    good = location_event()
    bad_range = location_event(lat=123.456789)
    bad_ts = location_event()
    bad_ts["occurred_at"] = "not-a-time"
    unknown_type = {**location_event(), "event_type": "teleport"}
    body = send(fam, device_id, token, [good, bad_range, stored, bad_ts, unknown_type]).json()
    assert body["status"] == "partial"
    assert body["accepted_event_ids"] == [good["event_id"]]
    assert body["duplicate_event_ids"] == [stored["event_id"]]
    rejected = {r["event_id"]: r["error_code"] for r in body["rejected_events"]}
    assert rejected == {
        bad_range["event_id"]: "VALIDATION_ERROR", bad_ts["event_id"]: "VALIDATION_ERROR",
        unknown_type["event_id"]: "VALIDATION_ERROR",
    }  # fmt: skip
    every = set(body["accepted_event_ids"]) | set(body["duplicate_event_ids"]) | set(rejected)
    assert every == {e["event_id"] for e in (good, bad_range, stored, bad_ts, unknown_type)}
    assert stored_ids(db, device_id) == {uuid.UUID(stored["event_id"]), uuid.UUID(good["event_id"])}


# 5 -----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("future", lambda e: e.update(occurred_at=iso(timedelta(hours=1)))),
        ("naive", lambda e: e.update(occurred_at="2026-10-16T10:00:00")),
        ("beyond retention", lambda e: e.update(occurred_at=iso(-timedelta(days=45)))),
        ("garbage time", lambda e: e.update(occurred_at="yesterday")),
        ("lat out of range", lambda e: e["data"].update(latitude=91)),
        ("lon out of range", lambda e: e["data"].update(longitude=-181)),
        ("accuracy too big", lambda e: e["data"].update(accuracy_meters=10001)),
        ("accuracy negative", lambda e: e["data"].update(accuracy_meters=-1)),
        ("string coordinate", lambda e: e["data"].update(latitude="40.7")),
        ("unknown field", lambda e: e["data"].update(battery_percent=85)),
        ("nested payload", lambda e: e["data"].update(extra={"a": [1, 2]})),
        ("negative sequence", lambda e: e.update(sequence_number=-5)),
        (
            "year 1 with positive offset",
            lambda e: e.update(occurred_at="0001-01-01T00:00:00+05:00"),
        ),
        (
            "year 9999 with negative offset",
            lambda e: e.update(occurred_at="9999-12-31T23:59:59-05:00"),
        ),
        ("integer beyond float range", lambda e: e["data"].update(latitude=10**400)),
        ("huge accuracy integer", lambda e: e["data"].update(accuracy_meters=-(10**400))),
    ],
)
def test_invalid_events_are_rejected_without_echoing_values(
    paired, db: Session, label: str, mutate
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event(lat=40.7128)
    mutate(ev)
    resp = send(fam, device_id, token, [ev])
    body = resp.json()
    assert resp.status_code == 202, label
    assert [r["error_code"] for r in body["rejected_events"]] == ["VALIDATION_ERROR"], label
    assert body["accepted_event_ids"] == [] and stored_ids(db, device_id) == set()
    assert "40.7128" not in resp.text and "-74.006" not in resp.text


def test_request_level_schema_errors_reject_the_whole_batch(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    good = location_event()
    for body in (
        {**batch(device_id, [good]), "schema_version": 2},
        {
            **batch(device_id, [good]),
            "family_id": str(fam.family_id),
        },  # client cannot name a family
        batch(device_id, []),
        batch(device_id, [{**good, "event_id": "not-a-uuid"}]),
        batch(device_id, [{**good, "unexpected": 1}]),
        {"batch_id": "x"},
    ):
        fam.client.app.state.limiter = RateLimiter()
        resp = fam.client.post(URL, json=body, headers=device_headers(token))
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert stored_ids(db, device_id) == set()


# 6 -----------------------------------------------------------------------------------------
def test_unenrolled_and_revoked_devices_are_rejected(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event()
    unknown = fam.client.post(
        URL, json=batch(device_id, [ev]), headers=device_headers("pkd_" + "A" * 43)
    )
    assert unknown.status_code == 401 and unknown.json()["error"]["code"] == "AUTH_INVALID"
    assert fam.client.post(URL, json=batch(device_id, [ev])).status_code == 401
    assert fam.client.delete(f"/api/v1/devices/{device_id}", headers=fam.headers).status_code == 204
    revoked = send(fam, device_id, token, [ev])
    assert revoked.status_code == 401 and revoked.json()["error"]["code"] == "AUTH_INVALID"
    assert stored_ids(db, device_id) == set()


def test_a_device_cannot_submit_as_another_device(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    d1, t1, _ = fam.pair_device("one")
    d2, _, _ = fam.pair_device("two")
    resp = send(fam, d2, t1, [location_event()])  # t1 claims to be d2
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "FORBIDDEN"
    assert stored_ids(db, d1) == set() and stored_ids(db, d2) == set()


def test_event_ids_are_scoped_per_device_and_leak_nothing(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a: Family = make_family("A")
    b: Family = make_family("B")
    da, ta, _ = a.pair_device()
    db_, tb, _ = b.pair_device()
    shared = uuid.uuid4()
    send(a, da, ta, [location_event(event_id=shared, lat=1.0)])
    resp = send(b, db_, tb, [location_event(event_id=shared, lat=2.0)])
    body = resp.json()  # accepted for B, not "duplicate": existence of A's event is not revealed
    assert body["accepted_event_ids"] == [str(shared)] and body["duplicate_event_ids"] == []
    assert stored_ids(db, da) == {shared} and stored_ids(db, db_) == {shared}
    fam_ids = set(db.scalars(select(TelemetryEvent.family_id).where(TelemetryEvent.id == shared)))
    assert fam_ids == {a.family_id, b.family_id}


# 7 -----------------------------------------------------------------------------------------
def test_batch_of_exactly_500_is_accepted_and_501_rejected_entirely(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    events = [location_event(ago=timedelta(seconds=i + 1)) for i in range(501)]
    too_big = send(fam, device_id, token, events)
    assert too_big.status_code == 400 and too_big.json()["error"]["code"] == "VALIDATION_ERROR"
    assert stored_ids(db, device_id) == set()
    ok = send(fam, device_id, token, events[:500])
    assert ok.status_code == 202 and len(ok.json()["accepted_event_ids"]) == 500
    assert len(stored_ids(db, device_id)) == 500


def test_oversized_and_compressed_bodies_are_bounded(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    h = {**device_headers(token), "Content-Type": "application/json"}
    huge = json.dumps(batch(device_id, [location_event()])) + " " * (600 * 1024)
    fam.client.app.state.limiter = RateLimiter()
    assert fam.client.post(URL, content=huge, headers=h).status_code == 400
    bomb = gzip.compress(b" " * (5 * 1024 * 1024))  # small on the wire, huge when inflated
    assert len(bomb) < 20_000
    r = fam.client.post(URL, content=bomb, headers={**h, "Content-Encoding": "gzip"})
    assert r.status_code == 400
    r = fam.client.post(URL, content=b"not gzip", headers={**h, "Content-Encoding": "gzip"})
    assert r.status_code == 400
    r = fam.client.post(URL, content=b"{}", headers={**h, "Content-Encoding": "br"})
    assert r.status_code == 400
    assert stored_ids(db, device_id) == set()


def test_gzip_requests_are_accepted_and_large_responses_compressed(paired, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    events = [location_event(ago=timedelta(seconds=i + 1)) for i in range(200)]
    payload = gzip.compress(json.dumps(batch(device_id, events)).encode())
    h = {**device_headers(token), "Content-Type": "application/json", "Content-Encoding": "gzip"}
    fam.client.app.state.limiter = RateLimiter()
    resp = fam.client.post(URL, content=payload, headers=h)
    assert resp.status_code == 202 and len(resp.json()["accepted_event_ids"]) == 200
    assert (
        resp.headers.get("content-encoding") == "gzip"
    )  # ack of 200 ids is compressed on the wire
    assert len(payload) < len(json.dumps(batch(device_id, events))) / 2


def test_telemetry_is_rate_limited_per_device(paired) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    fam.client.app.state.limiter = RateLimiter()
    codes = [
        send(fam, device_id, token, [battery_event(50)], reset=False).status_code for _ in range(11)
    ]
    assert codes[:10] == [202] * 10 and codes[10] == 429


def test_rate_limit_is_per_device_not_shared(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    d1, t1, _ = fam.pair_device("one")
    d2, t2, _ = fam.pair_device("two")
    fam.client.app.state.limiter = RateLimiter()
    for _ in range(10):
        send(fam, d1, t1, [battery_event(50)], reset=False)
    assert send(fam, d1, t1, [battery_event(50)], reset=False).status_code == 429
    assert send(fam, d2, t2, [battery_event(50)], reset=False).status_code == 202


# 8 -----------------------------------------------------------------------------------------
def test_ack_is_never_returned_unless_the_commit_succeeded(
    paired, app, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    ev = location_event()

    def failing_commit(self) -> None:  # type: ignore[no-untyped-def]
        raise OperationalError("COMMIT", {}, Exception("simulated commit failure"))

    with monkeypatch.context() as m:
        m.setattr("sqlalchemy.orm.Session.commit", failing_commit)
        app.state.limiter = RateLimiter()
        resp = TestClient(app, raise_server_exceptions=False).post(
            URL, json=batch(device_id, [ev]), headers=device_headers(token)
        )
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "accepted_event_ids" not in resp.text and "simulated" not in resp.text
    assert stored_ids(db, device_id) == set() and latest(db, device_id) is None
    # The device retries the identical batch later and it is accepted exactly once.
    retry = send(fam, device_id, token, [ev]).json()
    assert retry["accepted_event_ids"] == [ev["event_id"]] and len(stored_ids(db, device_id)) == 1


# state / liveness -----------------------------------------------------------------------------
def test_contact_updates_device_activity_and_status_endpoint(paired) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    before = fam.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token)).json()
    assert before["last_activity"] is None and before["connectivity_status"] == "unknown"
    send(fam, device_id, token, [battery_event(61)])
    after = fam.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token)).json()
    assert after["battery_percent"] == 61 and after["connectivity_status"] == "online"
    assert after["last_activity"] is not None and after["battery_updated_at"] is not None


def test_device_status_reports_charging_and_network_when_known_and_null_when_not(paired) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    url = f"/api/v1/devices/{device_id}"
    before = fam.client.get(url, headers=fam.headers).json()
    assert (
        before["battery_is_charging"] is None and before["network_type"] is None
    )  # unknown, not false
    battery = battery_event(55)
    battery["data"]["is_charging"] = True
    connectivity = {
        "event_id": str(uuid.uuid4()), "event_type": "connectivity",
        "occurred_at": iso(-timedelta(seconds=5)), "data": {"network_type": "wifi"},
    }  # fmt: skip
    send(fam, device_id, token, [battery, connectivity])
    after = fam.client.get(url, headers=fam.headers).json()
    assert after["battery_is_charging"] is True and after["network_type"] == "wifi"
    assert after["network_updated_at"] is not None


def test_rejected_only_batch_still_counts_as_device_contact(paired) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = paired
    send(fam, device_id, token, [location_event(lat=999)])
    me = fam.client.get(f"/api/v1/devices/{device_id}", headers=device_headers(token)).json()
    assert me["last_activity"] is not None and me["battery_percent"] is None


def test_concurrent_batches_cannot_regress_latest_state(paired, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    _fam, device_id, token = paired
    for round_no in range(3):
        newest = location_event(ago=timedelta(seconds=5), lat=50.0 + round_no)
        oldest = [location_event(ago=timedelta(hours=1, seconds=i), lat=-1.0) for i in range(20)]

        def post(events):  # type: ignore[no-untyped-def]
            with TestClient(app) as c:
                return c.post(
                    URL, json=batch(device_id, events), headers=device_headers(token)
                ).status_code

        app.state.limiter = RateLimiter()
        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(post, [[newest], oldest]))
        assert codes == [202, 202]
        assert float(latest(db, device_id).location_latitude) == 50.0 + round_no  # type: ignore[union-attr, arg-type]
    assert len(stored_ids(db, device_id)) == 3 + 60


def test_concurrent_duplicate_submission_stores_one_row(paired, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    _fam, device_id, token = paired
    ev = location_event()
    bid = str(uuid.uuid4())
    app.state.limiter = RateLimiter()

    def post(_: int):  # type: ignore[no-untyped-def]
        with TestClient(app) as c:
            r = c.post(URL, json=batch(device_id, [ev], bid), headers=device_headers(token))
            return r.status_code, r.json()["accepted_event_ids"]

    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(post, range(3)))
    assert all(code == 202 for code, _ in results)
    n = db.execute(
        text("SELECT count(*) FROM telemetry_events WHERE device_id = :d"),
        {"d": uuid.UUID(device_id)},
    ).scalar()
    assert n == 1
    assert db.scalar(select(func.count()).select_from(DeviceLatestState)) is not None
