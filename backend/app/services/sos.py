"""SOS incidents (ADR-022).

Lifecycle: open -> acknowledged -> resolved, or open -> resolved. Nothing resolves itself and a
resolved incident never reopens. Only a paired device creates an incident, with an id it generated
before sending, so a retry or replay can never create a second incident. Only a parent or
family_admin acknowledges or resolves; a guardian may read.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import AuditEvent, Device, DeviceLatestState, SosIncident
from app.domain.freshness import classify_freshness
from app.domain.telemetry import EventRejected, parse_occurred_at
from app.services import audit
from app.services.authz import ADMIN_ROLES, VIEW_ROLES, require_family_role, view_family_id
from app.services.notifications import NotificationService
from app.services.principals import DevicePrincipal, Principal, UserPrincipal

LIST_AUDIT_SPACING_SECONDS = 60


@dataclass(frozen=True)
class SosLocation:
    latitude: float
    longitude: float
    accuracy_meters: float | None


@dataclass(frozen=True)
class SosCreate:
    incident_id: uuid.UUID
    triggered_at: str
    message: str | None
    location: SosLocation | None


@dataclass(frozen=True)
class IncidentPage:
    incidents: list[SosIncident]
    total_count: int
    has_more: bool


def _dec(value: float, places: int) -> Decimal:
    return Decimal(str(round(value, places)))


class SosService:
    def __init__(self, settings: Settings, notifier: NotificationService) -> None:
        self._max_unresolved = settings.sos_max_unresolved_per_device
        self._notifier = notifier

    def create(
        self, db: Session, device: DevicePrincipal, req: SosCreate
    ) -> tuple[SosIncident, bool]:
        """Returns (incident, created). A replay of the same id from the same device returns the
        stored incident unchanged; an id already used by another device is a conflict."""
        now = datetime.now(UTC)
        try:
            triggered = parse_occurred_at(req.triggered_at)
        except EventRejected:
            raise ApiError("VALIDATION_ERROR", "triggered_at is not a valid timestamp.") from None
        # A phone whose clock runs fast must never lose an SOS (audit F-01): a time in the future is
        # capped at the moment the server received it instead of being refused.
        triggered = min(triggered, now)

        replay = db.get(SosIncident, req.incident_id)
        if replay is not None:
            if replay.device_id != device.device_id:
                raise ApiError("CONFLICT", "Incident id is already in use.")
            return replay, False
        # Volume cap (audit F-04). A device that already has this many unresolved incidents is not
        # given another row: the family already has a long list to act on, and the SOS is answered
        # with the newest one, so a real emergency is never refused.
        unresolved = db.scalar(
            select(func.count())
            .select_from(SosIncident)
            .where(SosIncident.device_id == device.device_id, SosIncident.status != "resolved")
        )
        if (unresolved or 0) >= self._max_unresolved:
            newest = db.scalar(
                select(SosIncident)
                .where(SosIncident.device_id == device.device_id, SosIncident.status != "resolved")
                .order_by(SosIncident.received_at.desc())
                .limit(1)
            )
            if newest is not None:
                return newest, False

        values: dict[str, object] = {
            "id": req.incident_id,
            "family_id": device.family_id,
            "device_id": device.device_id,
            "status": "open",
            "message": req.message,
            "triggered_at": triggered,
            "received_at": now,
            "location_is_latest_known": False,
        }
        if req.location is not None:
            values.update(
                location_latitude=_dec(req.location.latitude, 7),
                location_longitude=_dec(req.location.longitude, 7),
                location_accuracy_meters=(
                    None
                    if req.location.accuracy_meters is None
                    else _dec(req.location.accuracy_meters, 2)
                ),
                location_captured_at=triggered,
            )
        else:
            values.update(self._latest_known_location(db, device.device_id, now))

        inserted = db.scalar(
            pg_insert(SosIncident)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(SosIncident.id)
        )
        if inserted is None:
            existing = db.get(SosIncident, req.incident_id)
            if existing is None or existing.device_id != device.device_id:
                raise ApiError("CONFLICT", "Incident id is already in use.")
            return existing, False

        audit.record(
            db, action="sos_created", resource_type="incident", family_id=device.family_id,
            actor_device_id=device.device_id, resource_id=req.incident_id,
        )  # fmt: skip
        db.execute(update(Device).where(Device.id == device.device_id).values(last_activity_at=now))
        # The notification intent commits with the incident: it cannot be lost to a crash or outage.
        self._notifier.enqueue_to_family_browsers(
            db, family_id=device.family_id, kind="sos_created", subject_id=req.incident_id
        )
        db.commit()  # the 201 below is only reachable after a durable commit
        return db.get_one(SosIncident, req.incident_id), True

    @staticmethod
    def _latest_known_location(
        db: Session, device_id: uuid.UUID, now: datetime
    ) -> dict[str, object]:
        state = db.get(DeviceLatestState, device_id)
        if state is None or state.location_latitude is None:
            return {}
        freshness, _ = classify_freshness(state.location_occurred_at, now)
        if freshness == "unknown":
            return {}  # older than 24h: not offered as where the child is
        return {
            "location_latitude": state.location_latitude,
            "location_longitude": state.location_longitude,
            "location_accuracy_meters": state.location_accuracy_meters,
            "location_captured_at": state.location_occurred_at,
            "location_is_latest_known": True,
        }

    def list(
        self,
        db: Session,
        principal: Principal,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> IncidentPage:
        """Parents/admins/guardians see their family's incidents; a device sees its own."""
        if isinstance(principal, DevicePrincipal):
            scope = SosIncident.device_id == principal.device_id
        else:
            scope = SosIncident.family_id == view_family_id(db, principal.user_id)
        conditions = [scope]
        if status is not None:
            conditions.append(SosIncident.status == status)
        total = db.scalar(select(func.count()).select_from(SosIncident).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(SosIncident)
                .where(*conditions)
                .order_by(SosIncident.received_at.desc(), SosIncident.id)
                .limit(limit)
                .offset(offset)
            )
        )
        if isinstance(principal, UserPrincipal) and rows:
            self._audit_read(db, principal, rows[0].family_id, None)
        return IncidentPage(rows, total, offset + len(rows) < total)

    def get(self, db: Session, principal: Principal, incident_id: uuid.UUID) -> SosIncident:
        incident = db.get(SosIncident, incident_id)
        if incident is None:
            raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
        if isinstance(principal, DevicePrincipal):
            if incident.device_id != principal.device_id:
                raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
            return incident
        require_family_role(db, principal.user_id, incident.family_id, VIEW_ROLES)
        self._audit_read(db, principal, incident.family_id, incident.id)
        return incident

    def transition(
        self,
        db: Session,
        user: UserPrincipal,
        incident_id: uuid.UUID,
        target: str,
        notes: str | None,
    ) -> SosIncident:
        """Explicit parent action. Repeating the current state is a harmless no-op; any other
        backwards or sideways move is a conflict."""
        incident = db.scalar(
            select(SosIncident).where(SosIncident.id == incident_id).with_for_update()
        )
        if incident is None:
            raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
        membership = require_family_role(db, user.user_id, incident.family_id, ADMIN_ROLES)
        if incident.status == target:
            db.rollback()
            return db.get_one(SosIncident, incident_id)
        allowed = {"open": ("acknowledged", "resolved"), "acknowledged": ("resolved",)}
        if target not in allowed.get(incident.status, ()):
            db.rollback()
            raise ApiError("CONFLICT", "That status change is not allowed.")
        now = datetime.now(UTC)
        incident.status = target
        if notes:
            incident.parent_notes = notes
        if target == "acknowledged":
            incident.acknowledged_at, incident.acknowledged_by_member_id = now, membership.id
            action = "sos_acknowledged"
        else:
            incident.resolved_at, incident.resolved_by_member_id = now, membership.id
            action = "sos_resolved"
        audit.record(
            db, action=action, resource_type="incident", family_id=incident.family_id,
            actor_user_id=user.user_id, resource_id=incident.id,
        )  # fmt: skip
        self._notifier.enqueue_to_device(
            db, family_id=incident.family_id, device_id=incident.device_id,
            kind="sos_update", subject_id=incident.id, variant=target,
        )  # fmt: skip
        db.commit()
        return db.get_one(SosIncident, incident_id)

    @staticmethod
    def _audit_read(
        db: Session, user: UserPrincipal, family_id: uuid.UUID, incident_id: uuid.UUID | None
    ) -> None:
        # Incidents carry coordinates, so a read is recorded like a location read: metadata only.
        # A dashboard polls the list every ~30 s; one row per user per minute keeps the audit trail
        # readable instead of flooding it. Reading a single incident is always recorded.
        if incident_id is None:
            recent = db.scalar(
                select(AuditEvent.id)
                .where(
                    AuditEvent.action == "location_accessed",
                    AuditEvent.resource_type == "incident",
                    AuditEvent.resource_id.is_(None),
                    AuditEvent.actor_user_id == user.user_id,
                    AuditEvent.created_at
                    > datetime.now(UTC) - timedelta(seconds=LIST_AUDIT_SPACING_SECONDS),
                )
                .limit(1)
            )
            if recent is not None:
                return
        audit.record(
            db, action="location_accessed", resource_type="incident", family_id=family_id,
            actor_user_id=user.user_id, resource_id=incident_id,
        )  # fmt: skip
        db.commit()
