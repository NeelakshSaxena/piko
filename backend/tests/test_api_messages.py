"""Phase 6: family messages: delivery states, idempotency and authorization."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent, Message

from .conftest import Family, device_headers
from .helpers import child_user_token, iso
from .test_api_invitations import join

URL = "/api/v1/messages"


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def msg(body: str = "hello", message_id: str | None = None, **extra):  # type: ignore[no-untyped-def]
    out = {
        "message_id": message_id or str(uuid.uuid4()),
        "body": body,
        "sent_at": iso(-timedelta(seconds=2)),
    }
    out.update(extra)
    return out


def post(fam: Family, headers, payload):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.post(URL, json=payload, headers=headers)


def make(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


def test_device_to_parents_and_parent_to_device(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    up = post(fam, device_headers(token), msg("I am at school"))
    assert up.status_code == 201
    assert up.json()["sender"] == "device" and up.json()["status"] == "delivered"
    assert up.json()["acknowledged_at"] is None
    down = post(fam, fam.headers, msg("ok", device_id=device_id))
    assert down.status_code == 201 and down.json()["sender"] == "parent"
    reset(fam)
    parent_view = fam.client.get(URL, params={"device_id": device_id}, headers=fam.headers).json()
    assert parent_view["total_count"] == 2
    reset(fam)
    device_view = fam.client.get(URL, headers=device_headers(token)).json()
    assert {m["body"] for m in device_view["messages"]} == {"I am at school", "ok"}


def test_replay_is_idempotent(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    payload = msg("once")
    first = post(fam, device_headers(token), payload)
    again = post(fam, device_headers(token), dict(payload, body="changed"))
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["body"] == "once"
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.id == uuid.UUID(payload["message_id"]))
        )
        == 1
    )


def test_message_id_used_elsewhere_conflicts(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    _other_id, other_token, _ = fam.pair_device("Second")
    payload = msg()
    assert post(fam, device_headers(token), payload).status_code == 201
    clash = post(fam, device_headers(other_token), payload)
    assert clash.status_code == 409
    as_parent = post(fam, fam.headers, dict(payload, device_id=device_id))
    assert as_parent.status_code == 409  # same id, different sender


def test_ack_by_recipient_only_and_it_is_idempotent(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    from_child = post(fam, device_headers(token), msg("hi")).json()["message_id"]
    from_parent = post(fam, fam.headers, msg("yo", device_id=device_id)).json()["message_id"]
    reset(fam)
    # a sender cannot acknowledge its own message
    assert (
        fam.client.post(f"{URL}/{from_child}/ack", headers=device_headers(token)).status_code == 403
    )
    reset(fam)
    assert fam.client.post(f"{URL}/{from_parent}/ack", headers=fam.headers).status_code == 403
    reset(fam)
    ok = fam.client.post(f"{URL}/{from_child}/ack", headers=fam.headers)
    assert ok.status_code == 200 and ok.json()["status"] == "acknowledged"
    stamp = ok.json()["acknowledged_at"]
    reset(fam)
    assert (
        fam.client.post(f"{URL}/{from_child}/ack", headers=fam.headers).json()["acknowledged_at"]
        == stamp
    )
    reset(fam)
    got = fam.client.post(f"{URL}/{from_parent}/ack", headers=device_headers(token))
    assert got.status_code == 200 and got.json()["status"] == "acknowledged"


def test_other_families_and_other_devices_are_walled_off(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    _other_id, other_token, _ = fam.pair_device("Second")
    mid = post(fam, device_headers(token), msg("private")).json()["message_id"]
    stranger: Family = make_family()
    assert post(stranger, stranger.headers, msg(device_id=device_id)).status_code == 404
    reset(stranger)
    assert (
        stranger.client.get(
            URL, params={"device_id": device_id}, headers=stranger.headers
        ).status_code
        == 404
    )
    reset(stranger)
    assert stranger.client.post(f"{URL}/{mid}/ack", headers=stranger.headers).status_code == 404
    reset(fam)
    assert (
        fam.client.post(f"{URL}/{mid}/ack", headers=device_headers(other_token)).status_code == 404
    )
    reset(fam)
    mine = fam.client.get(URL, headers=device_headers(other_token)).json()
    assert mine["total_count"] == 0  # a sibling device never sees this conversation
    assert post(fam, device_headers(other_token), msg(device_id=device_id)).status_code == 403


def test_guardian_can_read_but_not_send_or_acknowledge(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    mid = post(fam, device_headers(token), msg("hi")).json()["message_id"]
    _, guardian = join(fam, "guardian")
    reset(fam)
    assert (
        fam.client.get(URL, params={"device_id": device_id}, headers=guardian).json()["total_count"]
        == 1
    )
    assert post(fam, guardian, msg(device_id=device_id)).status_code == 403
    reset(fam)
    assert fam.client.post(f"{URL}/{mid}/ack", headers=guardian).status_code == 403


def test_child_role_and_anonymous_are_refused(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, _token = make(make_family)
    kid, _ = child_user_token(app, db, fam.family_id)
    assert (
        post(fam, {"Authorization": f"Bearer {kid}"}, msg(device_id=device_id)).status_code == 403
    )
    assert post(fam, {}, msg(device_id=device_id)).status_code == 401
    reset(fam)
    assert fam.client.get(URL).status_code == 401


def test_validation(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    bad = [
        msg(""), msg("x" * 501), msg(sent_at="soon"),
        msg(message_id="nope"), msg(extra_field=1),
    ]  # fmt: skip
    for payload in bad:
        r = post(fam, device_headers(token), payload)
        assert r.status_code == 400, payload
    assert post(fam, fam.headers, msg()).status_code == 400  # a parent must name the device
    reset(fam)
    assert (
        fam.client.get(URL, params={"limit": 0}, headers=device_headers(token)).status_code == 400
    )


def test_revoked_device_is_cut_off_both_ways(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    reset(fam)
    fam.client.delete(f"/api/v1/devices/{device_id}", headers=fam.headers)
    assert post(fam, device_headers(token), msg()).status_code == 401
    assert post(fam, fam.headers, msg(device_id=device_id)).status_code == 404


def test_bodies_are_never_audited(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    post(fam, device_headers(token), msg("confidential text"))
    db.expire_all()
    rows = list(db.scalars(select(AuditEvent).where(AuditEvent.family_id == fam.family_id)))
    assert "confidential" not in " ".join(str(r.meta) + str(r.reason) for r in rows)
