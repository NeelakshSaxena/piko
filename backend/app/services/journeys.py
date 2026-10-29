"""Journeys (ADR-026): trips that belong to one device and sync from it.

Authorization is ownership: only the device that owns a journey can read, change, delete or add events to
it. A family relationship grants nothing, and a journey of another device is indistinguishable from a
missing one. Writes are whole-journey upserts decided by the owner's `revision` (a counter the phone adds
1 to on every saved edit), so a delayed, replayed or clock-skewed upload never overwrites newer state, and
a deleted journey cannot be brought back.

Tombstones: a deleted journey keeps a bare row so an older upload still on the wire cannot recreate it.
An HTTP request does not outlive its timeout, so a tombstone is useless after `TOMBSTONE_RETENTION` and is
purged (here, per device, and by the retention job). A device may hold at most `MAX_TOMBSTONES_PER_DEVICE`;
past that it can neither create journeys nor leave tombstones for ids the server never saw.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.core.errors import ApiError
from app.db.models import Journey, JourneyEvent, JourneyLeg
from app.domain.telemetry import EventRejected, parse_occurred_at
from app.services.principals import DevicePrincipal

MAX_JOURNEYS_PER_DEVICE = 200
MAX_EVENT_PAYLOAD_BYTES = 1024
MAX_EVENTS_PER_JOURNEY = 5000
MAX_TOMBSTONES_PER_DEVICE = 1000
TOMBSTONE_RETENTION = timedelta(days=30)
CLOCK_SKEW = timedelta(seconds=60)


@dataclass
class EventResult:
    accepted: list[uuid.UUID] = field(default_factory=list)
    duplicates: list[uuid.UUID] = field(default_factory=list)
    rejected: list[tuple[uuid.UUID, str]] = field(default_factory=list)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ApiError("VALIDATION_ERROR", "Timestamps must include a time zone.")
    return value.astimezone(UTC)


def _check_leg(leg: s.JourneyLegIn) -> None:
    for at, zone in ((leg.departure_at, leg.departure_zone), (leg.arrival_at, leg.arrival_zone)):
        if at is not None:
            _utc(at)
            if zone is None:
                raise ApiError("VALIDATION_ERROR", "A time needs its time zone.")


class JourneyService:
    def _tombstone_room(self, db: Session, device: DevicePrincipal, now: datetime) -> bool:
        """Purges this device's expired tombstones, then says whether it may leave another one."""
        db.execute(
            delete(Journey).where(
                Journey.device_id == device.device_id,
                Journey.deleted_at.is_not(None),
                Journey.deleted_at < now - TOMBSTONE_RETENTION,
            )
        )
        held = db.scalar(
            select(func.count())
            .select_from(Journey)
            .where(Journey.device_id == device.device_id, Journey.deleted_at.is_not(None))
        )
        return (held or 0) < MAX_TOMBSTONES_PER_DEVICE

    def _owned(
        self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID, *, lock: bool
    ) -> Journey | None:
        stmt = select(Journey).where(Journey.id == journey_id)
        if lock:
            stmt = stmt.with_for_update()
        row = db.scalar(stmt)
        if row is not None and row.device_id != device.device_id:
            raise ApiError(
                "NOT_FOUND_OR_NOT_VISIBLE"
            )  # another device's journey looks like a missing one
        return row

    def _live(self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID) -> Journey:
        row = self._owned(db, device, journey_id, lock=False)
        if row is None or row.deleted_at is not None:
            raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
        return row

    def _out(self, db: Session, row: Journey) -> s.JourneyOut:
        return self._out_many(db, [row])[0]

    def _out_many(self, db: Session, rows: list[Journey]) -> list[s.JourneyOut]:
        """One legs query for any number of journeys (a list must not cost a query per journey)."""
        legs_by_journey: dict[uuid.UUID, list[s.JourneyLegOut]] = {row.id: [] for row in rows}
        if rows:
            legs = db.scalars(
                select(JourneyLeg)
                .where(JourneyLeg.journey_id.in_(legs_by_journey))
                .order_by(JourneyLeg.journey_id, JourneyLeg.sequence)
            ).all()
            for leg in legs:
                legs_by_journey[leg.journey_id].append(
                    s.JourneyLegOut(
                        id=leg.id,
                        sequence=leg.sequence,
                        mode=leg.mode,
                        service_number=leg.service_number,
                        origin=leg.origin,
                        destination=leg.destination,
                        departure_at=leg.departure_at,
                        departure_zone=leg.departure_zone,
                        arrival_at=leg.arrival_at,
                        arrival_zone=leg.arrival_zone,
                    )
                )
        return [
            s.JourneyOut(
                id=row.id,
                title=row.title,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                revision=row.revision,
                legs=legs_by_journey[row.id],
            )
            for row in rows
        ]

    def put(
        self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID, body: s.JourneyPutRequest
    ) -> tuple[s.JourneyOut, bool]:
        result = self._put(db, device, journey_id, body)
        db.commit()  # the 200 is only reachable after a durable commit
        return result

    def _put(
        self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID, body: s.JourneyPutRequest
    ) -> tuple[s.JourneyOut, bool]:
        now = datetime.now(UTC)
        created = min(_utc(body.created_at), now)
        updated = min(_utc(body.updated_at), now)  # a fast clock must not win every later edit
        for leg in body.legs:
            _check_leg(leg)
        if len({leg.id for leg in body.legs}) != len(body.legs):
            raise ApiError("VALIDATION_ERROR", "Leg ids must be unique.")

        row = self._owned(db, device, journey_id, lock=True)
        if row is None:
            live = db.scalar(
                select(func.count())
                .select_from(Journey)
                .where(Journey.device_id == device.device_id, Journey.deleted_at.is_(None))
            )
            if (live or 0) >= MAX_JOURNEYS_PER_DEVICE:
                raise ApiError("CONFLICT", "Too many journeys on this device.")
            if not self._tombstone_room(db, device, now):
                raise ApiError("CONFLICT", "Too many recently deleted journeys on this device.")
            created_id = db.scalar(
                pg_insert(Journey)
                .values(
                    id=journey_id,
                    family_id=device.family_id,
                    device_id=device.device_id,
                    title=body.title,
                    status=body.status,
                    created_at=created,
                    updated_at=updated,
                    received_at=now,
                    revision=body.revision,
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(Journey.id)
            )
            if created_id is not None:
                new = db.get(Journey, journey_id)
                assert new is not None
                return self._replace_legs(db, new, body), True
            row = self._owned(db, device, journey_id, lock=True)  # lost a first-insert race
            if row is None:
                raise ApiError("CONFLICT", "Journey id is already in use.")
        if row.deleted_at is not None:
            raise ApiError("CONFLICT", "This journey was deleted.")
        if body.revision <= row.revision:
            # Equal: the same edit again. Lower: an older request that arrived late. Either way the stored
            # copy stands, and the answer carries its revision so the phone can tell which it was.
            return self._out(db, row), False
        row.title, row.status, row.received_at, row.revision = (
            body.title,
            body.status,
            now,
            body.revision,
        )
        row.updated_at = max(row.updated_at, updated)  # display order only; never goes backwards
        return self._replace_legs(db, row, body), True

    def _replace_legs(self, db: Session, row: Journey, body: s.JourneyPutRequest) -> s.JourneyOut:
        ids = [leg.id for leg in body.legs]
        taken = db.scalar(
            select(JourneyLeg.id)
            .where(JourneyLeg.id.in_(ids), JourneyLeg.journey_id != row.id)
            .limit(1)
        )
        if taken is not None:
            raise ApiError("CONFLICT", "A leg id is already in use.")
        db.execute(delete(JourneyLeg).where(JourneyLeg.journey_id == row.id))
        db.flush()
        for sequence, leg in enumerate(body.legs):
            db.add(
                JourneyLeg(
                    id=leg.id,
                    journey_id=row.id,
                    sequence=sequence,
                    mode=leg.mode,
                    service_number=leg.service_number,
                    origin=leg.origin,
                    destination=leg.destination,
                    departure_at=_utc(leg.departure_at) if leg.departure_at else None,
                    departure_zone=leg.departure_zone,
                    arrival_at=_utc(leg.arrival_at) if leg.arrival_at else None,
                    arrival_zone=leg.arrival_zone,
                )
            )
        db.flush()
        return self._out(db, row)

    def get(self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID) -> s.JourneyOut:
        return self._out(db, self._live(db, device, journey_id))

    def list_all(self, db: Session, device: DevicePrincipal) -> list[s.JourneyOut]:
        rows = db.scalars(
            select(Journey)
            .where(Journey.device_id == device.device_id, Journey.deleted_at.is_(None))
            .order_by(Journey.updated_at.desc(), Journey.id)
            .limit(MAX_JOURNEYS_PER_DEVICE)
        ).all()
        return self._out_many(db, list(rows))

    def delete(self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID) -> None:
        self._delete(db, device, journey_id)
        db.commit()

    def _delete(self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID) -> None:
        """Idempotent. An id the server never saw still gets a tombstone, so an older upload that is
        still in flight cannot create it afterwards."""
        now = datetime.now(UTC)
        row = self._owned(db, device, journey_id, lock=True)
        if row is None:
            if not self._tombstone_room(db, device, now):
                return  # over the cap: no bare tombstone for an id this server never saw
            db.execute(
                pg_insert(Journey)
                .values(
                    id=journey_id,
                    family_id=device.family_id,
                    device_id=device.device_id,
                    title="",
                    status="DRAFT",
                    created_at=now,
                    updated_at=now,
                    received_at=now,
                    deleted_at=now,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            if self._owned(db, device, journey_id, lock=True) is None:
                raise ApiError("CONFLICT", "Journey id is already in use.")
            return
        if row.deleted_at is not None:
            return
        db.execute(delete(JourneyLeg).where(JourneyLeg.journey_id == row.id))
        db.execute(delete(JourneyEvent).where(JourneyEvent.journey_id == row.id))
        row.title, row.deleted_at, row.updated_at, row.received_at = "", now, now, now

    def add_events(
        self,
        db: Session,
        device: DevicePrincipal,
        journey_id: uuid.UUID,
        events: list[s.JourneyEventIn],
    ) -> EventResult:
        self._live(db, device, journey_id)
        now = datetime.now(UTC)
        result = EventResult()
        stored = (
            db.scalar(
                select(func.count())
                .select_from(JourneyEvent)
                .where(JourneyEvent.journey_id == journey_id)
            )
            or 0
        )
        for event in events:
            try:
                occurred = min(parse_occurred_at(event.occurred_at), now + CLOCK_SKEW)
            except EventRejected:
                result.rejected.append((event.event_id, "occurred_at is not a valid timestamp."))
                continue
            if len(json.dumps(event.data)) > MAX_EVENT_PAYLOAD_BYTES:
                result.rejected.append((event.event_id, "data is too large."))
                continue
            if stored >= MAX_EVENTS_PER_JOURNEY:
                result.rejected.append((event.event_id, "This journey has too many events."))
                continue
            inserted = db.scalar(
                pg_insert(JourneyEvent)
                .values(
                    id=event.event_id,
                    journey_id=journey_id,
                    device_id=device.device_id,
                    event_type=event.event_type,
                    occurred_at=occurred,
                    received_at=now,
                    payload=event.data,
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(JourneyEvent.id)
            )
            if inserted is not None:
                stored += 1
                result.accepted.append(event.event_id)
                continue
            existing = db.get(JourneyEvent, event.event_id)
            if (
                existing is not None
                and existing.journey_id == journey_id
                and existing.device_id == device.device_id
            ):
                result.duplicates.append(event.event_id)
            else:
                result.rejected.append((event.event_id, "Event id is already in use."))
        db.commit()  # acknowledged only after durable acceptance
        return result

    def list_events(
        self, db: Session, device: DevicePrincipal, journey_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[JourneyEvent], bool]:
        self._live(db, device, journey_id)
        rows = db.scalars(
            select(JourneyEvent)
            .where(JourneyEvent.journey_id == journey_id)
            .order_by(JourneyEvent.occurred_at, JourneyEvent.id)
            .limit(limit + 1)
            .offset(offset)
        ).all()
        return list(rows[:limit]), len(rows) > limit
