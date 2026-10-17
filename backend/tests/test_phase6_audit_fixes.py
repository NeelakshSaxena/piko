"""Regression tests for the independent Phase 6 audit (docs/verification/phase-06-independent-audit.md):
F-01 clock skew, F-02 control characters, F-05 detail rate limit, F-07 sender filter, and the negative
cases the audit listed as missing (revoked member, concurrent ack/resolve, cross-device reads)."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import FamilyMembership, Message, SosIncident

from .conftest import Family, device_headers
from .helpers import child_user_token, iso

SOS = "/api/v1/sos/incidents"
MSG = "/api/v1/messages"


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def make(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


def sos_body(device_id: str, **extra):  # type: ignore[no-untyped-def]
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=2)),
    }
    body.update(extra)
    return body


def msg_body(**extra):  # type: ignore[no-untyped-def]
    body = {"message_id": str(uuid.uuid4()), "body": "hi", "sent_at": iso(-timedelta(seconds=2))}
    body.update(extra)
    return body


def post_sos(fam, token, body):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.post(SOS, json=body, headers=device_headers(token))


# ---- F-01: a fast clock never loses an SOS or a message ------------------------------------
@pytest.mark.parametrize("ahead", [timedelta(seconds=61), timedelta(hours=2), timedelta(days=400)])
def test_an_sos_from_a_fast_clock_is_stored_and_capped_at_receipt_time(make_family, ahead) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    r = post_sos(fam, token, sos_body(device_id, triggered_at=iso(ahead)))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["triggered_at"] <= out["received_at"]  # never later than the server's own clock
    assert out["status"] == "open"


def test_a_message_from_a_fast_clock_is_stored_and_capped(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    reset(fam)
    r = fam.client.post(
        MSG, json=msg_body(sent_at=iso(timedelta(hours=3))), headers=device_headers(token)
    )
    assert r.status_code == 201
    assert r.json()["sent_at"] <= r.json()["received_at"]


def test_a_garbled_timestamp_is_still_a_client_error(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    assert post_sos(fam, token, sos_body(device_id, triggered_at="soon")).status_code == 400
    assert (
        post_sos(fam, token, sos_body(device_id, triggered_at="2026-10-17T10:00:00")).status_code
        == 400
    )


def test_a_very_old_claimed_time_is_stored_as_claimed_and_both_times_are_visible(
    make_family,
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    out = post_sos(fam, token, sos_body(device_id, triggered_at="1970-01-01T00:00:00Z")).json()
    assert out["triggered_at"].startswith("1970-01-01") and out["received_at"] > out["triggered_at"]


# ---- F-02: control characters are a 400, never a 500 ----------------------------------------
BAD_TEXT = ["a\u0000b", "bell\u0007", "del\u007f", "\u0000"]


@pytest.mark.parametrize("text", BAD_TEXT)
def test_control_characters_are_rejected_everywhere_with_400(
    make_family, db: Session, text: str
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    r = post_sos(fam, token, sos_body(device_id, message=text))
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert text not in r.text  # the offending value is not echoed
    reset(fam)
    r = fam.client.post(MSG, json=msg_body(body=text), headers=device_headers(token))
    assert r.status_code == 400
    ok = post_sos(fam, token, sos_body(device_id))
    assert ok.status_code == 201
    reset(fam)
    r = fam.client.put(
        f"{SOS}/{ok.json()['incident_id']}",
        json={"status": "acknowledged", "notes": text},
        headers=fam.headers,
    )
    assert r.status_code == 400
    db.expire_all()
    assert (
        db.get_one(SosIncident, uuid.UUID(ok.json()["incident_id"])).status == "open"
    )  # nothing changed


def test_newlines_tabs_and_unicode_text_are_fine(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    text = "line one\nline two\ttabbed अमित \U0001f198"
    r = post_sos(fam, token, sos_body(device_id, message=text))
    assert r.status_code == 201 and r.json()["message"] == text


# ---- F-05: detail reads are rate limited per user ---------------------------------------------
def test_incident_detail_reads_are_rate_limited(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = post_sos(fam, token, sos_body(device_id)).json()["incident_id"]
    now = 1000.0
    fam.client.app.state.limiter = RateLimiter(clock=lambda: now)
    codes = [fam.client.get(f"{SOS}/{iid}", headers=fam.headers).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429


# ---- F-07: the phone can ask for parents' messages only ---------------------------------------
def test_messages_can_be_filtered_by_sender_and_counts_follow_the_filter(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    for _ in range(3):
        reset(fam)
        assert (
            fam.client.post(MSG, json=msg_body(), headers=device_headers(token)).status_code == 201
        )
    reset(fam)
    assert (
        fam.client.post(
            MSG, json=msg_body(device_id=device_id, body="from parent"), headers=fam.headers
        ).status_code
        == 201
    )
    reset(fam)
    only = fam.client.get(
        MSG, params={"sender": "parent", "limit": 1}, headers=device_headers(token)
    ).json()
    assert [m["body"] for m in only["messages"]] == ["from parent"] and only["total_count"] == 1
    reset(fam)
    both = fam.client.get(MSG, headers=device_headers(token)).json()
    assert both["total_count"] == 4
    reset(fam)
    assert (
        fam.client.get(MSG, params={"sender": "robot"}, headers=device_headers(token)).status_code
        == 400
    )


# ---- gaps the audit listed: revoked / inactive members, cross-device reads, concurrency ----------
def test_a_revoked_member_loses_sos_and_message_access(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = post_sos(fam, token, sos_body(device_id)).json()["incident_id"]
    db.execute(
        update(FamilyMembership)
        .where(FamilyMembership.family_id == fam.family_id, FamilyMembership.user_id == fam.user_id)
        .values(status="revoked")
    )
    db.commit()
    reset(fam)
    h = fam.headers
    assert fam.client.get(SOS, headers=h).status_code == 403
    # id-addressed routes answer a revoked member exactly like a stranger (404, L-4)
    ghost = fam.client.get(f"{SOS}/{uuid.uuid4()}", headers=h)
    revoked = fam.client.get(f"{SOS}/{iid}", headers=h)
    assert revoked.status_code == ghost.status_code == 404
    assert revoked.json()["error"]["message"] == ghost.json()["error"]["message"]
    assert fam.client.put(f"{SOS}/{iid}", json={"status": "resolved"}, headers=h).status_code == 404
    assert fam.client.post(MSG, json=msg_body(device_id=device_id), headers=h).status_code == 404
    assert fam.client.get(MSG, params={"device_id": device_id}, headers=h).status_code == 404
    db.expire_all()
    assert db.get_one(SosIncident, uuid.UUID(iid)).status == "open"


def test_a_pending_member_cannot_see_incidents(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = post_sos(fam, token, sos_body(device_id)).json()["incident_id"]
    db.execute(
        update(FamilyMembership)
        .where(FamilyMembership.family_id == fam.family_id, FamilyMembership.user_id == fam.user_id)
        .values(status="pending")
    )
    db.commit()
    reset(fam)
    assert fam.client.get(f"{SOS}/{iid}", headers=fam.headers).status_code == 404
    assert fam.client.get(SOS, headers=fam.headers).status_code == 403


def test_an_archived_family_exposes_no_incidents(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import Family as FamilyRow

    fam, device_id, token = make(make_family)
    iid = post_sos(fam, token, sos_body(device_id)).json()["incident_id"]
    db.execute(update(FamilyRow).where(FamilyRow.id == fam.family_id).values(status="archived"))
    db.commit()
    reset(fam)
    assert fam.client.get(f"{SOS}/{iid}", headers=fam.headers).status_code == 404
    assert fam.client.get(SOS, headers=fam.headers).status_code == 403
    assert (
        post_sos(fam, token, sos_body(device_id)).status_code == 401
    )  # the device credential dies too


def test_a_device_cannot_read_another_devices_conversation(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_a, token_a = make(make_family)
    _device_b, token_b, _ = fam.pair_device("Second")
    reset(fam)
    assert (
        fam.client.post(
            MSG, json=msg_body(body="secret-a"), headers=device_headers(token_a)
        ).status_code
        == 201
    )
    reset(fam)
    r = fam.client.get(MSG, params={"device_id": device_a}, headers=device_headers(token_b))
    assert r.status_code == 404 and "secret-a" not in r.text


def test_concurrent_acknowledge_and_resolve_never_error_or_go_backwards(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    iid = post_sos(fam, token, sos_body(device_id)).json()["incident_id"]
    reset(fam)

    def act(status: str) -> int:
        return fam.client.put(
            f"{SOS}/{iid}", json={"status": status}, headers=fam.headers
        ).status_code

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(act, ["acknowledged", "resolved"] * 4))
    assert set(codes) <= {200, 409}, codes  # a lost race is a conflict, never a 500
    assert 500 not in codes
    db.expire_all()
    assert (
        db.get_one(SosIncident, uuid.UUID(iid)).status == "resolved"
    )  # resolved always wins and stays


def test_concurrent_message_acks_record_one_acknowledgement(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    mid = msg_body()["message_id"]
    reset(fam)
    assert (
        fam.client.post(
            MSG, json=msg_body(message_id=mid), headers=device_headers(token)
        ).status_code
        == 201
    )
    reset(fam)

    def ack(_: int) -> int:
        return fam.client.post(f"{MSG}/{mid}/ack", headers=fam.headers).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(ack, range(6)))
    assert set(codes) == {200}
    db.expire_all()
    row = db.get_one(Message, uuid.UUID(mid))
    assert row.status == "acknowledged" and row.acknowledged_at is not None


def test_a_child_role_user_cannot_read_a_conversation_of_another_device(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, _token = make(make_family)
    kid, _ = child_user_token(app, db, fam.family_id)
    reset(fam)
    r = fam.client.get(
        MSG, params={"device_id": device_id}, headers={"Authorization": f"Bearer {kid}"}
    )
    assert r.status_code == 404  # a child user sees only the device it owns


def test_stored_incident_time_is_never_after_receipt(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    for ahead in (timedelta(minutes=5), timedelta(seconds=30)):
        post_sos(fam, token, sos_body(device_id, triggered_at=iso(ahead)))
    db.expire_all()
    rows = list(db.scalars(select(SosIncident).where(SosIncident.family_id == fam.family_id)))
    assert rows and all(r.triggered_at <= r.received_at + timedelta(seconds=0) for r in rows)
    assert all(r.received_at <= datetime.now(UTC) for r in rows)


# ---- L-5: device clocks are advisory --------------------------------------------------------------
def test_a_reading_dated_in_the_future_is_capped_and_cannot_block_the_next_real_one(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    import time

    from app.db.models import DeviceLatestState, TelemetryEvent

    from .helpers import batch, location_event

    fam, device_id, token = make(make_family)
    ahead = location_event(ago=-timedelta(seconds=50), lat=1.0, lon=1.0)
    reset(fam)
    r = fam.client.post(
        "/api/v1/telemetry/batches", json=batch(device_id, [ahead]), headers=device_headers(token)
    )
    assert r.status_code == 202 and r.json()["accepted_event_ids"] == [ahead["event_id"]]
    db.expire_all()
    stored = db.get_one(TelemetryEvent, (uuid.UUID(device_id), uuid.UUID(ahead["event_id"])))
    assert stored.occurred_at <= stored.received_at  # never ahead of the server's own clock
    time.sleep(2)
    real = location_event(ago=timedelta(seconds=0), lat=2.0, lon=2.0)
    reset(fam)
    assert (
        fam.client.post(
            "/api/v1/telemetry/batches",
            json=batch(device_id, [real]),
            headers=device_headers(token),
        ).status_code
        == 202
    )
    db.expire_all()
    state = db.get_one(DeviceLatestState, uuid.UUID(device_id))
    assert float(state.location_latitude) == 2.0  # before the cap it stayed 1.0 for another 50 s


def test_a_reading_beyond_the_skew_is_still_rejected(make_family) -> None:  # type: ignore[no-untyped-def]
    from .helpers import batch, location_event

    fam, device_id, token = make(make_family)
    reset(fam)
    far = location_event(ago=-timedelta(minutes=10))
    r = fam.client.post(
        "/api/v1/telemetry/batches", json=batch(device_id, [far]), headers=device_headers(token)
    )
    assert (
        r.status_code == 202 and r.json()["rejected_events"][0]["error_code"] == "VALIDATION_ERROR"
    )
