"""Retention job (backlog item 11): deletes only what has outlived its documented period, never SOS."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.ratelimit import RateLimiter
from app.db.models import (
    AuditEvent,
    Message,
    NotificationOutbox,
    SosIncident,
    TelemetryEvent,
)
from app.db.models import (
    Family as FamilyRow,
)
from app.services.retention import RetentionService

from .conftest import Family, device_headers
from .helpers import batch, iso, location_event

NOW = datetime.now(UTC)


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def seed(make_family, db: Session):  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, _token, _ = fam.pair_device()
    dev = uuid.UUID(device_id)
    # telemetry: one 40-day-old and one fresh event (family retention 30 days)
    for age_days, ev_id in ((40, uuid.uuid4()), (1, uuid.uuid4())):
        db.add(
            TelemetryEvent(
                device_id=dev, id=ev_id, family_id=fam.family_id, batch_id=uuid.uuid4(),
                event_type="battery", occurred_at=NOW - timedelta(days=age_days),
                received_at=NOW - timedelta(days=age_days), data={"percent": 50, "is_charging": False},
            )
        )  # fmt: skip
    # messages: 100 days old and fresh
    for age_days in (100, 1):
        db.add(
            Message(
                id=uuid.uuid4(), family_id=fam.family_id, device_id=dev, sender="device", body=f"m{age_days}",
                sent_at=NOW - timedelta(days=age_days), received_at=NOW - timedelta(days=age_days),
            )
        )  # fmt: skip
    # audit: 400 days old and fresh
    for age_days in (400, 2):
        db.add(
            AuditEvent(
                family_id=fam.family_id, action="login", resource_type="user",
                created_at=NOW - timedelta(days=age_days),
            )
        )  # fmt: skip
    # outbox: old finished, old pending, fresh finished
    for status, age_days in (("accepted", 60), ("pending", 60), ("accepted", 1)):
        db.add(
            NotificationOutbox(
                id=uuid.uuid4(), family_id=fam.family_id, kind="message", target_kind="device_token",
                target_id=dev, subject_id=uuid.uuid4(), dedupe_key=str(uuid.uuid4()), status=status,
                next_attempt_at=NOW, expires_at=NOW, created_at=NOW - timedelta(days=age_days),
            )
        )  # fmt: skip
    # an SOS that is two years old and resolved: must survive
    db.add(
        SosIncident(
            id=uuid.uuid4(), family_id=fam.family_id, device_id=dev, status="resolved",
            triggered_at=NOW - timedelta(days=700), received_at=NOW - timedelta(days=700),
        )
    )  # fmt: skip
    db.commit()
    return fam, dev


def counts(db: Session, fam: Family, dev: uuid.UUID) -> dict[str, int]:
    db.expire_all()

    def n(model, *where):  # type: ignore[no-untyped-def]
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return {
        "telemetry": n(TelemetryEvent, TelemetryEvent.device_id == dev),
        "messages": n(Message, Message.device_id == dev),
        "audit_login": n(
            AuditEvent, AuditEvent.family_id == fam.family_id, AuditEvent.action == "login"
        ),
        "outbox": n(NotificationOutbox, NotificationOutbox.family_id == fam.family_id),
        "sos": n(SosIncident, SosIncident.device_id == dev),
    }


def test_a_dry_run_reports_but_deletes_nothing(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, dev = seed(make_family, db)
    before = counts(db, fam, dev)
    report = RetentionService(app.state.settings).run(app.state.session_factory, apply=False)
    assert report.dry_run is True
    assert report.counts["telemetry_events"] >= 1 and report.counts["messages"] >= 1
    assert counts(db, fam, dev) == before


def test_apply_deletes_only_expired_rows_and_never_an_sos(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam, dev = seed(make_family, db)
    before = counts(db, fam, dev)
    report = RetentionService(app.state.settings).run(app.state.session_factory, apply=True)
    after = counts(db, fam, dev)
    assert report.dry_run is False
    assert after["telemetry"] == before["telemetry"] - 1  # only the 40-day-old event
    assert after["messages"] == before["messages"] - 1  # only the 100-day-old message
    assert after["audit_login"] == before["audit_login"] - 1  # only the 400-day-old audit row
    assert (
        after["outbox"] == before["outbox"] - 1
    )  # the old *finished* row; the old pending one stays
    assert after["sos"] == before["sos"] == 1  # the two-year-old resolved SOS is a safety record


def test_each_family_keeps_its_own_telemetry_window(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    short, dev_short = seed(make_family, db)
    long_, dev_long = seed(make_family, db)
    db.execute(update(FamilyRow).where(FamilyRow.id == short.family_id).values(retention_days=7))
    db.execute(update(FamilyRow).where(FamilyRow.id == long_.family_id).values(retention_days=90))
    db.commit()
    RetentionService(app.state.settings).run(app.state.session_factory, apply=True)
    db.expire_all()
    short_events = db.scalar(
        select(func.count())
        .select_from(TelemetryEvent)
        .where(TelemetryEvent.device_id == dev_short)
    )
    long_events = db.scalar(
        select(func.count()).select_from(TelemetryEvent).where(TelemetryEvent.device_id == dev_long)
    )
    assert short_events == 1  # the 1-day-old event survives a 7-day window; the 40-day one went
    assert long_events == 2  # a 90-day window keeps both


def test_it_is_idempotent_and_bounded(make_family, app, db: Session) -> None:  # type: ignore[no-untyped-def]
    _fam, _dev = seed(make_family, db)
    service = RetentionService(app.state.settings)
    service.run(app.state.session_factory, apply=True)
    again = service.run(app.state.session_factory, apply=True)
    assert again.more_remaining is False
    # a tiny batch budget leaves work for the next run instead of running unbounded
    fam2, dev2 = seed(make_family, db)
    one_batch = service.run(app.state.session_factory, apply=True, max_batches=1)
    assert one_batch.dry_run is False
    assert counts(db, fam2, dev2)["sos"] == 1


def test_ordinary_traffic_still_works_after_retention(make_family, app) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    RetentionService(app.state.settings).run(app.state.session_factory, apply=True)
    reset(fam)
    r = fam.client.post(
        "/api/v1/telemetry/batches",
        json=batch(device_id, [location_event()]),
        headers=device_headers(token),
    )
    assert r.status_code == 202
    reset(fam)
    assert (
        fam.client.post(
            "/api/v1/sos/incidents",
            json={
                "incident_id": str(uuid.uuid4()),
                "device_id": device_id,
                "triggered_at": iso(-timedelta(seconds=2)),
            },
            headers=device_headers(token),
        ).status_code
        == 201
    )


def test_the_retention_endpoint_needs_the_scheduler_secret(make_family, app) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    reset(fam)
    assert (
        fam.client.post(
            "/api/v1/internal/retention/run", headers={"X-Piko-Outbox-Token": "x"}
        ).status_code
        == 503
    )
    app.state.outbox_token = b"retention-token-123"
    try:
        reset(fam)
        assert fam.client.post("/api/v1/internal/retention/run").status_code == 401
        assert (
            fam.client.post("/api/v1/internal/retention/run", headers=fam.headers).status_code
            == 401
        )
        ok = fam.client.post(
            "/api/v1/internal/retention/run", headers={"X-Piko-Outbox-Token": "retention-token-123"}
        )
        assert ok.status_code == 200 and "telemetry_events" in ok.json()["deleted"]
    finally:
        app.state.outbox_token = None
