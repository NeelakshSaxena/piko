"""ADR-023: push registration, the durable notification outbox, delivery outcomes and privacy.

Transports are scripted fakes (the real FCM and Web Push providers are NOT contacted here); what is
real is PostgreSQL, the HTTP API, authorization, the outbox state machine and its concurrency.
"""

import itertools
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import (
    AuditEvent,
    DevicePushToken,
    FamilyMembership,
    NotificationOutbox,
    WebPushSubscription,
)
from app.services.notifications import (
    Accepted,
    InvalidTarget,
    NotificationService,
    Permanent,
    Transient,
)
from app.services.push_secrets import PushSecretBox

from .conftest import Family, device_headers
from .helpers import child_user_token, iso
from .test_api_invitations import join

TOKEN = "fcm-token-" + "A" * 60
ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
P256DH = "B" + "A" * 86
AUTH = "A" * 22


class Fake:
    """A scripted transport. Outcomes are keyed by the subject id so rows left behind by other tests
    in the shared schema can never consume them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], int]] = []
        self.plan: dict[str, list[Any]] = {}

    def script(self, subject_id: str, *outcomes: Any) -> None:
        self.plan[subject_id] = list(outcomes)

    def send(self, address: str, payload: dict[str, str], ttl: int):  # type: ignore[no-untyped-def]
        self.calls.append((address, payload, ttl))
        queue = self.plan.get(payload["id"])
        outcome = queue.pop(0) if queue else Accepted()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def for_subject(self, subject_id: str) -> list[tuple[str, dict[str, str], int]]:
        return [c for c in self.calls if c[1]["id"] == subject_id]


@pytest.fixture
def push(app):  # type: ignore[no-untyped-def]
    web, device = Fake(), Fake()
    notifier: NotificationService = app.state.notifier
    old = notifier.transports
    notifier.transports = {"web_subscription": web, "device_token": device}
    yield web, device
    notifier.transports = old


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def make(make_family):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    return fam, device_id, token


def sub_body(endpoint: str = ENDPOINT, p256dh: str = P256DH, auth: str = AUTH) -> dict[str, Any]:
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def subscribe(fam: Family, headers: dict[str, str] | None = None, endpoint: str = ENDPOINT):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.put(
        "/api/v1/push/web-subscription", json=sub_body(endpoint), headers=headers or fam.headers
    )


def register_token(fam: Family, device_token: str, token: str = TOKEN):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.put(
        "/api/v1/push/device-token", json={"token": token}, headers=device_headers(device_token)
    )


def rows(db: Session, family_id: uuid.UUID, **where: Any) -> list[NotificationOutbox]:
    db.expire_all()
    stmt = select(NotificationOutbox).where(NotificationOutbox.family_id == family_id)
    for key, value in where.items():
        stmt = stmt.where(getattr(NotificationOutbox, key) == value)
    return list(db.scalars(stmt.order_by(NotificationOutbox.created_at)))


def raise_sos(fam: Family, device_id: str, token: str, **extra: Any):  # type: ignore[no-untyped-def]
    reset(fam)
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=3)),
    }
    body.update(extra)
    return fam.client.post("/api/v1/sos/incidents", json=body, headers=device_headers(token))


def raise_sos_as(fam: Family, device_id: str, token: str, incident_id: str):  # type: ignore[no-untyped-def]
    reset(fam)
    body = {
        "incident_id": incident_id,
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=3)),
    }
    return fam.client.post("/api/v1/sos/incidents", json=body, headers=device_headers(token))


def drain(app, limit: int = 500):  # type: ignore[no-untyped-def]
    return app.state.notifier.drain(app.state.session_factory, limit)


# ---- registration ---------------------------------------------------------------------------------
def test_device_token_is_stored_sealed_and_rotation_replaces_it(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    assert register_token(fam, token).status_code == 204
    db.expire_all()
    row = db.get_one(DevicePushToken, uuid.UUID(device_id))
    assert row.family_id == fam.family_id and TOKEN not in row.token_cipher
    assert app.state.push.open_device_token(row) == TOKEN
    rotated = "rotated-" + "B" * 60
    assert register_token(fam, token, rotated).status_code == 204
    db.expire_all()
    only = list(
        db.scalars(select(DevicePushToken).where(DevicePushToken.device_id == uuid.UUID(device_id)))
    )
    assert len(only) == 1 and app.state.push.open_device_token(only[0]) == rotated


def test_a_token_moves_to_the_device_that_now_presents_it(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _device_a, token_a = make(make_family)
    device_b, token_b, _ = fam.pair_device("Second")
    assert register_token(fam, token_a).status_code == 204
    assert register_token(fam, token_b).status_code == 204  # same install token now presented by B
    db.expire_all()
    owners = list(
        db.scalars(
            select(DevicePushToken.device_id).where(DevicePushToken.family_id == fam.family_id)
        )
    )
    assert owners == [uuid.UUID(device_b)]


def test_registration_requires_a_device_credential_and_a_sane_token(make_family) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    reset(fam)
    assert fam.client.put("/api/v1/push/device-token", json={"token": TOKEN}).status_code == 401
    assert (
        fam.client.put(
            "/api/v1/push/device-token", json={"token": TOKEN}, headers=fam.headers
        ).status_code
        == 401
    )
    for bad in ("short", "x" * 5000, "has space " + "a" * 30, "line\nbreak" + "a" * 30):
        assert register_token(fam, token, bad).status_code == 400, bad
    reset(fam)
    extra = fam.client.put(
        "/api/v1/push/device-token",
        json={"token": TOKEN, "device_id": device_id},
        headers=device_headers(token),
    )
    assert extra.status_code == 400  # a caller cannot name a device or family


def test_a_token_cannot_be_registered_for_another_familys_device(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    a_fam, a_dev, a_tok = make(make_family)
    b_fam, b_dev, b_tok = make(make_family)
    assert register_token(b_fam, b_tok, "b-token-" + "C" * 60).status_code == 204
    assert register_token(a_fam, a_tok).status_code == 204
    db.expire_all()
    a_row = db.get_one(DevicePushToken, uuid.UUID(a_dev))
    b_row = db.get_one(DevicePushToken, uuid.UUID(b_dev))
    assert a_row.family_id == a_fam.family_id and b_row.family_id == b_fam.family_id


def test_revoking_a_device_removes_its_token_and_blocks_registration(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    assert register_token(fam, token).status_code == 204
    reset(fam)
    assert fam.client.delete(f"/api/v1/devices/{device_id}", headers=fam.headers).status_code == 204
    db.expire_all()
    assert db.get(DevicePushToken, uuid.UUID(device_id)) is None
    assert register_token(fam, token).status_code == 401


def test_logout_style_removal_deletes_the_token_and_is_audited(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    reset(fam)
    assert (
        fam.client.delete("/api/v1/push/device-token", headers=device_headers(token)).status_code
        == 204
    )
    db.expire_all()
    assert db.get(DevicePushToken, uuid.UUID(device_id)) is None
    actions = {
        a.action
        for a in db.scalars(select(AuditEvent).where(AuditEvent.family_id == fam.family_id))
    }
    assert {"push_registered", "push_revoked"} <= actions


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",  # not https
        "https://127.0.0.1/hook",  # loopback (SSRF)
        "https://localhost/hook",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://evil.example.com/fcm/send/x",
        "https://fcm.googleapis.com.evil.com/fcm/send/x",  # look-alike suffix
        "https://user:pw@fcm.googleapis.com/fcm/send/x",  # userinfo
        "https://fcm.googleapis.com:8443/fcm/send/x",  # port
        "https://notfcm.googleapis.com/x",
        "https://fcm.googleapis.com/" + "a" * 2100,
    ],
)
def test_web_push_endpoints_off_the_allow_list_are_refused(make_family, endpoint: str) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    r = subscribe(fam, endpoint=endpoint)
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/xyz",
        "https://web.push.apple.com/QJ",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_the_major_browser_push_services_are_accepted(make_family, endpoint: str) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    assert subscribe(fam, endpoint=endpoint).status_code == 204


def test_web_subscription_roles_and_ownership(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    _, guardian = join(fam, "guardian")
    assert subscribe(fam).status_code == 204
    assert (
        subscribe(fam, guardian, "https://fcm.googleapis.com/fcm/send/guardian").status_code == 204
    )
    kid, _ = child_user_token(app, db, fam.family_id)
    assert subscribe(fam, {"Authorization": f"Bearer {kid}"}).status_code == 403
    reset(fam)
    assert (
        fam.client.put(
            "/api/v1/push/web-subscription", json=sub_body(), headers=device_headers(token)
        ).status_code
        == 401
    )
    assert fam.client.put("/api/v1/push/web-subscription", json=sub_body()).status_code == 401
    # a guardian cannot remove the parent's subscription
    reset(fam)
    r = fam.client.post(
        "/api/v1/push/web-subscription/remove", json={"endpoint": ENDPOINT}, headers=guardian
    )
    assert r.status_code == 204
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(WebPushSubscription)
            .where(WebPushSubscription.family_id == fam.family_id)
        )
        == 2
    )
    reset(fam)
    assert (
        fam.client.post(
            "/api/v1/push/web-subscription/remove", json={"endpoint": ENDPOINT}, headers=fam.headers
        ).status_code
        == 204
    )
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(WebPushSubscription)
            .where(WebPushSubscription.family_id == fam.family_id)
        )
        == 1
    )


def test_only_the_five_newest_subscriptions_per_user_are_kept(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    for i in range(7):
        assert (
            subscribe(fam, endpoint=f"https://fcm.googleapis.com/fcm/send/n{i}").status_code == 204
        )
    db.expire_all()
    count = db.scalar(
        select(func.count())
        .select_from(WebPushSubscription)
        .where(WebPushSubscription.user_id == fam.user_id)
    )
    assert count == 5


def test_stored_subscriptions_are_sealed(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    subscribe(fam)
    db.expire_all()
    row = db.scalar(select(WebPushSubscription).where(WebPushSubscription.user_id == fam.user_id))
    assert row is not None and ENDPOINT not in row.secret_cipher and P256DH not in row.secret_cipher
    assert app.state.push.open_web_subscription(row) == {
        "endpoint": ENDPOINT,
        "p256dh": P256DH,
        "auth": AUTH,
    }


def test_sealed_values_fail_closed_for_another_key_context_or_corruption() -> None:
    box = PushSecretBox(b"k" * 32)
    sealed = box.seal("secret", "fcm-token")
    assert box.open(sealed, "fcm-token") == "secret"
    assert box.open(sealed, "webpush") is None  # wrong context
    assert PushSecretBox(b"j" * 32).open(sealed, "fcm-token") is None  # wrong key
    assert box.open(sealed[:-4] + "AAAA", "fcm-token") is None
    assert box.open("not base64 !!", "fcm-token") is None
    assert box.seal("secret", "fcm-token") != sealed  # fresh nonce every time


def test_push_config_reports_what_is_really_configured(make_family, app, push) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    reset(fam)
    assert fam.client.get("/api/v1/push/config", headers=fam.headers).json() == {
        "web_push_enabled": False,
        "vapid_public_key": None,
    }
    app.state.settings.vapid_public_key = "PUBLIC-KEY"
    try:
        reset(fam)
        assert fam.client.get("/api/v1/push/config", headers=fam.headers).json() == {
            "web_push_enabled": True,
            "vapid_public_key": "PUBLIC-KEY",
        }
    finally:
        app.state.settings.vapid_public_key = None
    reset(fam)
    assert fam.client.get("/api/v1/push/config").status_code == 401


# ---- outbox: enqueue ------------------------------------------------------------------------------
def test_sos_enqueues_one_notification_per_allowed_browser_in_the_same_family_only(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    _, guardian = join(fam, "guardian")
    subscribe(fam)
    subscribe(fam, guardian, "https://fcm.googleapis.com/fcm/send/guardian")
    stranger: Family = make_family()
    subscribe(stranger, endpoint="https://fcm.googleapis.com/fcm/send/stranger")
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    mine = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert len(mine) == 2 and {r.kind for r in mine} == {"sos_created"}
    assert all(r.target_kind == "web_subscription" for r in mine)
    assert rows(db, stranger.family_id) == []  # nothing crosses a family boundary


def test_replaying_an_sos_does_not_create_more_notifications(
    make_family, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    subscribe(fam)
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=2)),
    }
    for _ in range(3):
        reset(fam)
        assert fam.client.post(
            "/api/v1/sos/incidents", json=body, headers=device_headers(token)
        ).status_code in (200, 201)
    assert len(rows(db, fam.family_id, subject_id=uuid.UUID(body["incident_id"]))) == 1


def test_no_subscriptions_means_nothing_is_queued(make_family, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    raise_sos(fam, device_id, token)
    assert rows(db, fam.family_id) == []


def test_status_changes_notify_the_phone_once_per_change(make_family, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    for status in ("acknowledged", "acknowledged", "resolved", "resolved"):
        reset(fam)
        fam.client.put(f"/api/v1/sos/incidents/{iid}", json={"status": status}, headers=fam.headers)
    updates = rows(db, fam.family_id, kind="sos_update")
    assert len(updates) == 2 and all(r.target_kind == "device_token" for r in updates)


def test_refused_or_invalid_actions_queue_nothing(make_family, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    _, guardian = join(fam, "guardian")
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    reset(fam)
    assert (
        fam.client.put(
            f"/api/v1/sos/incidents/{iid}", json={"status": "resolved"}, headers=guardian
        ).status_code
        == 403
    )
    reset(fam)
    assert (
        fam.client.put(
            f"/api/v1/sos/incidents/{iid}", json={"status": "bogus"}, headers=fam.headers
        ).status_code
        == 400
    )
    assert rows(db, fam.family_id, kind="sos_update") == []


def test_messages_notify_the_other_side(make_family, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    subscribe(fam)
    reset(fam)
    up = fam.client.post(
        "/api/v1/messages",
        json={"message_id": str(uuid.uuid4()), "body": "hi parents", "sent_at": iso()},
        headers=device_headers(token),
    )
    reset(fam)
    down = fam.client.post(
        "/api/v1/messages",
        json={
            "message_id": str(uuid.uuid4()),
            "body": "hi child",
            "device_id": device_id,
            "sent_at": iso(),
        },
        headers=fam.headers,
    )
    assert up.status_code == down.status_code == 201
    by_subject = {r.subject_id: r for r in rows(db, fam.family_id, kind="message")}
    assert by_subject[uuid.UUID(up.json()["message_id"])].target_kind == "web_subscription"
    assert by_subject[uuid.UUID(down.json()["message_id"])].target_kind == "device_token"


# ---- delivery ----------------------------------------------------------------------------------------
def test_delivery_sends_only_a_type_and_an_id_and_records_acceptance_not_delivery(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    web, _device = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    secret_note = "PRIVATE-NOTE-xyz 51.5074,-0.1278"
    iid = raise_sos(
        fam,
        device_id,
        token,
        message=secret_note,
        location={"latitude": 51.5074, "longitude": -0.1278},
    ).json()["incident_id"]
    drain(app)
    calls = web.for_subject(iid)
    assert len(calls) == 1
    _address, payload, ttl = calls[0]
    assert payload == {"v": "1", "type": "sos_created", "id": iid}
    assert secret_note not in str(payload) and "51.5" not in str(payload)
    assert 0 < ttl <= 86400
    (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert row.status == "accepted" and row.accepted_at is not None and row.attempts == 1
    assert secret_note not in " ".join(str(v) for v in (row.dedupe_key, row.last_error, row.kind))


def test_an_in_request_drain_delivers_without_any_scheduler(make_family, push) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    iid = raise_sos(fam, device_id, token).json()[
        "incident_id"
    ]  # BackgroundTasks drains after the response
    assert len(web.for_subject(iid)) == 1


def test_a_transient_failure_backs_off_retries_and_eventually_dies(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    iid = str(uuid.uuid4())
    web.script(iid, *[Transient("fcm_http_503")] * 20)  # scripted before the in-request drain runs
    assert raise_sos_as(fam, device_id, token, iid).status_code == 201
    now = datetime.now(UTC)
    max_attempts = app.state.settings.outbox_max_attempts
    waits: list[float] = []
    (first,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert first.attempts == 1 and first.status == "pending"  # the in-request drain was attempt 1
    now = first.next_attempt_at + timedelta(seconds=1)
    waits.append((first.next_attempt_at - datetime.now(UTC)).total_seconds())
    for attempt in range(2, max_attempts + 1):
        app.state.notifier.drain(app.state.session_factory, 500, now=now)
        (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
        assert row.attempts == attempt
        if row.status == "dead":
            break
        waits.append((row.next_attempt_at - now).total_seconds())
        now = row.next_attempt_at + timedelta(seconds=1)
    (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert (
        row.status == "dead" and row.attempts == max_attempts and row.last_error == "fcm_http_503"
    )
    assert all(b >= a * 0.9 for a, b in itertools.pairwise(waits))  # grows (within jitter)
    assert waits[-1] <= app.state.settings.outbox_backoff_cap_seconds
    assert len(web.for_subject(iid)) == max_attempts  # bounded: never retried beyond the limit


def test_a_not_yet_due_retry_is_not_attempted_early(make_family, app, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    iid = str(uuid.uuid4())
    web.script(iid, Transient("fcm_http_503"))
    assert (
        raise_sos_as(fam, device_id, token, iid).status_code == 201
    )  # attempt 1 happens in the request
    before = len(web.for_subject(iid))
    drain(app)  # immediately again: the retry is in the future
    assert len(web.for_subject(iid)) == before == 1


def test_one_failing_notification_does_not_block_the_others(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    _, guardian = join(fam, "guardian")
    subscribe(fam)
    subscribe(fam, guardian, "https://fcm.googleapis.com/fcm/send/second")
    iid = str(uuid.uuid4())
    web.script(
        iid, RuntimeError("boom"), Accepted()
    )  # first send explodes, the other target is fine
    reset(fam)
    fam.client.post(
        "/api/v1/sos/incidents",
        json={
            "incident_id": iid,
            "device_id": device_id,
            "triggered_at": iso(-timedelta(seconds=1)),
        },
        headers=device_headers(token),
    )
    drain(app)
    statuses = sorted(r.status for r in rows(db, fam.family_id, subject_id=uuid.UUID(iid)))
    assert (
        "accepted" in statuses and "pending" in statuses
    )  # the exception became a retry for one row only
    assert (
        next(
            r for r in rows(db, fam.family_id, subject_id=uuid.UUID(iid)) if r.status == "pending"
        ).last_error
        == "transport_exception"
    )


def test_an_invalid_token_is_removed_and_the_row_ends(make_family, app, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    _, device = push
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    iid = str(uuid.uuid4())
    assert raise_sos_as(fam, device_id, token, iid).status_code == 201
    device.script(
        iid, InvalidTarget("fcm_unregistered")
    )  # scripted before the acknowledgement's in-request drain
    reset(fam)
    fam.client.put(
        f"/api/v1/sos/incidents/{iid}", json={"status": "acknowledged"}, headers=fam.headers
    )
    drain(app)
    (row,) = rows(db, fam.family_id, kind="sos_update")
    assert row.status == "dead" and row.last_error == "fcm_unregistered"
    db.expire_all()
    assert db.get(DevicePushToken, uuid.UUID(device_id)) is None  # a dead token is never used again


def test_a_permanent_refusal_ends_the_row_but_keeps_the_token(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    _, device = push
    fam, device_id, token = make(make_family)
    register_token(fam, token)
    reset(fam)
    mid = str(uuid.uuid4())
    device.script(mid, Permanent("fcm_http_400"))
    fam.client.post(
        "/api/v1/messages",
        json={"message_id": mid, "body": "x", "device_id": device_id, "sent_at": iso()},
        headers=fam.headers,
    )
    drain(app)
    (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(mid))
    assert row.status == "dead" and row.last_error == "fcm_http_400"
    db.expire_all()
    assert db.get(DevicePushToken, uuid.UUID(device_id)) is not None


def test_a_revoked_member_is_not_notified_by_an_old_subscription(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    _, guardian = join(fam, "guardian")
    subscribe(fam, guardian, "https://fcm.googleapis.com/fcm/send/guardian-only")
    notifier: NotificationService = app.state.notifier
    notifier.transports = {}  # nothing is delivered while the row is created ("provider down")
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    guardian_row = db.scalar(
        select(FamilyMembership).where(
            FamilyMembership.family_id == fam.family_id, FamilyMembership.role == "guardian"
        )
    )
    assert guardian_row is not None
    db.execute(
        update(FamilyMembership)
        .where(FamilyMembership.id == guardian_row.id)
        .values(status="revoked")
    )
    db.commit()
    notifier.transports = {"web_subscription": web}
    notifier.drain(app.state.session_factory, 500, now=datetime.now(UTC) + timedelta(minutes=5))
    pending = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert web.for_subject(iid) == []  # the revoked guardian was never contacted
    assert [r.status for r in pending] == ["skipped"] and pending[0].last_error == "target_gone"


def test_unconfigured_transports_leave_rows_pending_without_attempts(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    notifier: NotificationService = app.state.notifier
    old = notifier.transports
    notifier.transports = {}
    try:
        fam, device_id, token = make(make_family)
        subscribe(fam)
        iid = raise_sos(fam, device_id, token).json()[
            "incident_id"
        ]  # the in-request drain finds no transport
        (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
        assert (
            row.status == "pending"
            and row.attempts == 0
            and row.last_error == "transport_unconfigured"
        )
        result = notifier.drain(
            app.state.session_factory, 500, now=datetime.now(UTC) + timedelta(minutes=5)
        )
        assert result.waiting_for_transport >= 1
        (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
        assert row.status == "pending" and row.attempts == 0  # waiting is not a failed attempt
    finally:
        notifier.transports = old


def test_an_expired_notification_is_not_sent(make_family, app, db: Session, push) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    notifier: NotificationService = app.state.notifier
    old = notifier.transports
    notifier.transports = {}
    try:
        iid = raise_sos(fam, device_id, token).json()["incident_id"]
    finally:
        notifier.transports = old
    app.state.notifier.drain(
        app.state.session_factory, 500, now=datetime.now(UTC) + timedelta(days=3)
    )
    (row,) = rows(db, fam.family_id, subject_id=uuid.UUID(iid))
    assert row.status == "expired" and web.for_subject(iid) == []


def test_pending_rows_survive_a_restart_and_are_delivered_exactly_once(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    """Backend restart / worker restart with queued rows: a brand-new service instance drains them."""
    fam, device_id, token = make(make_family)
    subscribe(fam)
    notifier: NotificationService = app.state.notifier
    old = notifier.transports
    notifier.transports = {}  # "the provider was down / the worker was not running"
    try:
        iid = raise_sos(fam, device_id, token).json()["incident_id"]
    finally:
        notifier.transports = old
    assert rows(db, fam.family_id, subject_id=uuid.UUID(iid))[0].status == "pending"
    web = Fake()
    fresh = NotificationService(
        app.state.settings, app.state.push, {"web_subscription": web}
    )  # the "restarted" worker
    later = datetime.now(UTC) + timedelta(minutes=5)
    fresh.drain(app.state.session_factory, 500, now=later)
    fresh.drain(app.state.session_factory, 500, now=later)
    assert len(web.for_subject(iid)) == 1
    assert rows(db, fam.family_id, subject_id=uuid.UUID(iid))[0].status == "accepted"


def test_concurrent_workers_send_each_notification_once(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    for i in range(4):
        subscribe(fam, endpoint=f"https://fcm.googleapis.com/fcm/send/c{i}")
    web = Fake()
    notifier: NotificationService = app.state.notifier
    old = notifier.transports
    notifier.transports = {}
    try:
        iid = raise_sos(fam, device_id, token).json()["incident_id"]
    finally:
        notifier.transports = old
    worker = NotificationService(app.state.settings, app.state.push, {"web_subscription": web})
    later = datetime.now(UTC) + timedelta(minutes=5)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: worker.drain(app.state.session_factory, 100, now=later), range(4)))
    calls = web.for_subject(iid)
    assert len(calls) == 4 and len({c[0] for c in calls}) == 4  # one per subscription, none twice


def test_a_duplicate_provider_delivery_cannot_come_from_the_outbox_itself(
    make_family, app, db: Session, push
) -> None:  # type: ignore[no-untyped-def]
    web, _ = push
    fam, device_id, token = make(make_family)
    subscribe(fam)
    iid = raise_sos(fam, device_id, token).json()["incident_id"]
    drain(app)
    drain(app)
    drain(app)
    assert len(web.for_subject(iid)) == 1  # accepted rows are final


# ---- operations endpoints ---------------------------------------------------------------------------------
def test_outbox_endpoints_are_disabled_without_a_secret_and_guarded_with_one(
    make_family, app, push
) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    reset(fam)
    assert (
        fam.client.post(
            "/api/v1/internal/outbox/run", headers={"X-Piko-Outbox-Token": "anything"}
        ).status_code
        == 503
    )
    app.state.outbox_token = b"sekret-run-token"
    try:
        reset(fam)
        assert fam.client.post("/api/v1/internal/outbox/run").status_code == 401
        assert (
            fam.client.post(
                "/api/v1/internal/outbox/run", headers={"X-Piko-Outbox-Token": "wrong"}
            ).status_code
            == 401
        )
        assert (
            fam.client.get("/api/v1/internal/outbox/health", headers=fam.headers).status_code == 401
        )  # a user token is not enough
        ok = fam.client.post(
            "/api/v1/internal/outbox/run", headers={"X-Piko-Outbox-Token": "sekret-run-token"}
        )
        assert ok.status_code == 200 and set(ok.json()) == {
            "accepted",
            "retried",
            "dead",
            "skipped",
            "expired",
            "waiting_for_transport",
        }
        health = fam.client.get(
            "/api/v1/internal/outbox/health", headers={"X-Piko-Outbox-Token": "sekret-run-token"}
        )
        assert health.status_code == 200
        body = health.json()
        assert set(body["by_status"]) == {"pending", "accepted", "dead", "skipped", "expired"}
        assert set(body["transports_configured"]) == {"device_token", "web_subscription"}
        assert "id" not in str(body) and "token" not in str(body["by_status"])
    finally:
        app.state.outbox_token = None


# ---- F-04 volume caps and F-06 audit ------------------------------------------------------------------------
def test_an_sos_beyond_the_unresolved_cap_returns_the_newest_open_one(
    make_family, app, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    cap = app.state.settings.sos_max_unresolved_per_device
    app.state.settings.sos_max_unresolved_per_device = 3
    app.state.sos._max_unresolved = 3
    try:
        ids = [raise_sos(fam, device_id, token).json()["incident_id"] for _ in range(3)]
        over = raise_sos(fam, device_id, token)
        assert (
            over.status_code == 200 and over.json()["incident_id"] in ids
        )  # answered, not refused
        db.expire_all()
        total = db.scalar(
            select(func.count())
            .select_from(__import__("app.db.models", fromlist=["SosIncident"]).SosIncident)
            .where(
                __import__("app.db.models", fromlist=["SosIncident"]).SosIncident.family_id
                == fam.family_id
            )
        )
        assert total == 3
        reset(fam)
        fam.client.put(
            f"/api/v1/sos/incidents/{ids[0]}", json={"status": "resolved"}, headers=fam.headers
        )
        assert raise_sos(fam, device_id, token).status_code == 201  # a resolved one frees a slot
    finally:
        app.state.settings.sos_max_unresolved_per_device = cap
        app.state.sos._max_unresolved = cap


def test_a_conversation_has_a_daily_message_cap(make_family, app) -> None:  # type: ignore[no-untyped-def]
    fam, _device_id, token = make(make_family)
    cap = app.state.messages._daily_cap
    app.state.messages._daily_cap = 3
    try:
        codes = []
        for _ in range(5):
            reset(fam)
            codes.append(
                fam.client.post(
                    "/api/v1/messages",
                    json={"message_id": str(uuid.uuid4()), "body": "x", "sent_at": iso()},
                    headers=device_headers(token),
                ).status_code
            )
        assert codes == [201, 201, 201, 429, 429]
    finally:
        app.state.messages._daily_cap = cap


def test_reading_a_conversation_is_audited_without_text_and_throttled(
    make_family, db: Session
) -> None:  # type: ignore[no-untyped-def]
    fam, device_id, token = make(make_family)
    _, guardian = join(fam, "guardian")
    reset(fam)
    fam.client.post(
        "/api/v1/messages",
        json={"message_id": str(uuid.uuid4()), "body": "AUDIT-PROBE-TEXT", "sent_at": iso()},
        headers=device_headers(token),
    )
    for headers in (fam.headers, guardian):
        for _ in range(3):
            reset(fam)
            assert (
                fam.client.get(
                    "/api/v1/messages", params={"device_id": device_id}, headers=headers
                ).status_code
                == 200
            )
    db.expire_all()
    reads = list(
        db.scalars(
            select(AuditEvent).where(
                AuditEvent.family_id == fam.family_id, AuditEvent.action == "message_read"
            )
        )
    )
    assert len(reads) == 2  # one per reader, however often they poll
    assert {r.actor_user_id for r in reads} != {None} and all(
        r.resource_id == uuid.UUID(device_id) for r in reads
    )
    assert "AUDIT-PROBE-TEXT" not in " ".join(str(r.meta) + str(r.reason) for r in reads)
    # the phone reading its own conversation is not a "someone read it" event
    reset(fam)
    fam.client.get("/api/v1/messages", headers=device_headers(token))
    db.expire_all()
    assert (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.family_id == fam.family_id, AuditEvent.action == "message_read")
        )
        == 2
    )
