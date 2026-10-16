"""Telemetry ingestion and reconciliation (ADR-009..011).

Ordering rule: every accepted event is appended to history regardless of arrival order. The
derived latest state for each group (location / battery / connectivity) advances only for an
event whose occurred_at is strictly newer than the stored one, via a single conditional UPDATE
so concurrent batches cannot regress it. Acknowledgement is built only after COMMIT succeeds.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Device, DeviceLatestState, Family, TelemetryEvent
from app.domain.telemetry import EventRejected, ValidEvent, validate_event
from app.services.principals import DevicePrincipal


@dataclass(frozen=True)
class RawEvent:
    event_id: uuid.UUID
    event_type: str
    sequence_number: int | None
    occurred_at: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Rejection:
    event_id: uuid.UUID
    error_code: str
    reason: str


@dataclass
class IngestResult:
    accepted_event_ids: list[uuid.UUID] = field(default_factory=list)
    duplicate_event_ids: list[uuid.UUID] = field(default_factory=list)
    rejected_events: list[Rejection] = field(default_factory=list)


def _order_key(ev: ValidEvent) -> tuple[datetime, int]:
    # Within one batch only: occurred_at decides; sequence breaks exact-timestamp ties.
    return ev.occurred_at, -1 if ev.sequence_number is None else ev.sequence_number


def _location_values(e: ValidEvent, now: datetime) -> dict[str, Any]:
    accuracy = e.data["accuracy_meters"]
    return {
        "location_latitude": _dec(e.data["latitude"], 7),
        "location_longitude": _dec(e.data["longitude"], 7),
        "location_accuracy_meters": None if accuracy is None else _dec(accuracy, 2),
        "location_occurred_at": e.occurred_at,
        "location_received_at": now,
    }


def _battery_values(e: ValidEvent, now: datetime) -> dict[str, Any]:
    return {
        "battery_percent": e.data["percent"],
        "battery_is_charging": e.data["is_charging"],
        "battery_updated_at": e.occurred_at,
    }


def _connectivity_values(e: ValidEvent, now: datetime) -> dict[str, Any]:
    return {
        "connectivity_network_type": e.data["network_type"],
        "connectivity_updated_at": e.occurred_at,
    }


def _dec(value: float, places: int) -> Decimal:
    return Decimal(str(round(value, places)))


class TelemetryService:
    def __init__(self, settings: Settings) -> None:
        self._skew = timedelta(seconds=settings.telemetry_future_skew_seconds)

    def ingest(
        self, db: Session, principal: DevicePrincipal, batch_id: uuid.UUID, events: list[RawEvent]
    ) -> IngestResult:
        now = datetime.now(UTC)
        retention_days = db.scalar(
            select(Family.retention_days).where(Family.id == principal.family_id)
        )
        max_age = timedelta(days=retention_days or 30)

        result = IngestResult()
        valid: dict[uuid.UUID, ValidEvent] = {}
        seen: set[uuid.UUID] = set()
        for raw in events:
            if raw.event_id in seen:
                continue  # the first copy decides the outcome; each id is reported exactly once
            seen.add(raw.event_id)
            try:
                valid[raw.event_id] = validate_event(
                    event_type=raw.event_type,
                    occurred_at=raw.occurred_at,
                    sequence_number=raw.sequence_number,
                    data=raw.data,
                    now=now,
                    max_age=max_age,
                    future_skew=self._skew,
                )
            except EventRejected as exc:
                result.rejected_events.append(
                    Rejection(raw.event_id, "VALIDATION_ERROR", exc.reason)
                )

        inserted = self._append_history(db, principal, batch_id, valid, now)
        self._classify_existing(db, principal, batch_id, valid, inserted, result)
        result.accepted_event_ids.extend(e for e in valid if e in inserted)
        self._advance_latest_state(db, principal, {i: valid[i] for i in inserted}, now)
        db.execute(
            update(Device).where(Device.id == principal.device_id).values(last_activity_at=now)
        )
        db.commit()  # acknowledgement below is only reachable after a durable commit
        return result

    @staticmethod
    def _append_history(
        db: Session,
        principal: DevicePrincipal,
        batch_id: uuid.UUID,
        valid: dict[uuid.UUID, ValidEvent],
        now: datetime,
    ) -> set[uuid.UUID]:
        if not valid:
            return set()
        rows = [
            {
                "device_id": principal.device_id,
                "id": event_id,
                "family_id": principal.family_id,
                "batch_id": batch_id,
                "sequence_number": ev.sequence_number,
                "event_type": ev.event_type,
                "occurred_at": ev.occurred_at,
                "received_at": now,
                "schema_version": 1,
                "data": ev.data,
            }
            for event_id, ev in valid.items()
        ]
        stmt = (
            pg_insert(TelemetryEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["device_id", "id"])
            .returning(TelemetryEvent.id)
        )
        return set(db.scalars(stmt))

    @staticmethod
    def _classify_existing(
        db: Session,
        principal: DevicePrincipal,
        batch_id: uuid.UUID,
        valid: dict[uuid.UUID, ValidEvent],
        inserted: set[uuid.UUID],
        result: IngestResult,
    ) -> None:
        """Events already stored: a replay of this same batch is re-acknowledged as accepted
        (same answer as the first time); anything stored by another batch is a duplicate."""
        existing = [i for i in valid if i not in inserted]
        if not existing:
            return
        rows = db.execute(
            select(TelemetryEvent.id, TelemetryEvent.batch_id).where(
                TelemetryEvent.device_id == principal.device_id, TelemetryEvent.id.in_(existing)
            )
        ).all()
        stored = {row.id: row.batch_id for row in rows}
        for event_id in existing:
            if stored.get(event_id) == batch_id:
                result.accepted_event_ids.append(event_id)
            else:
                result.duplicate_event_ids.append(event_id)

    @staticmethod
    def _advance_latest_state(
        db: Session, principal: DevicePrincipal, new: dict[uuid.UUID, ValidEvent], now: datetime
    ) -> None:
        if not new:
            return
        db.execute(
            pg_insert(DeviceLatestState)
            .values(device_id=principal.device_id, family_id=principal.family_id)
            .on_conflict_do_nothing(index_elements=["device_id"])
        )
        newest: dict[str, ValidEvent] = {}
        for ev in new.values():
            cur = newest.get(ev.event_type)
            if cur is None or _order_key(ev) > _order_key(cur):
                newest[ev.event_type] = ev

        table = DeviceLatestState
        specs: dict[str, tuple[Any, Callable[[ValidEvent, datetime], dict[str, Any]]]] = {
            "location": (table.location_occurred_at, _location_values),
            "battery": (table.battery_updated_at, _battery_values),
            "connectivity": (table.connectivity_updated_at, _connectivity_values),
        }
        for event_type, ev in newest.items():
            stamp_col, values = specs[event_type]
            db.execute(
                update(DeviceLatestState)
                .where(
                    DeviceLatestState.device_id == principal.device_id,
                    or_(stamp_col.is_(None), stamp_col < ev.occurred_at),
                )
                .values(updated_at=now, **values(ev, now))
            )
