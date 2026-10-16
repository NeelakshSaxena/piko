"""Event history for one family member (newest first), with the same authorization as `locations`."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Device, TelemetryEvent
from app.domain.freshness import DeviceStatus, Freshness, classify_freshness, device_status
from app.services import audit
from app.services.authz import viewable_member
from app.services.principals import UserPrincipal


@dataclass(frozen=True)
class HistoryItem:
    event_id: uuid.UUID
    occurred_at: datetime
    received_at: datetime
    event_type: str
    freshness: Freshness
    data: dict[str, Any]


@dataclass(frozen=True)
class HistoryPage:
    member_id: uuid.UUID
    device_status: DeviceStatus
    items: list[HistoryItem]
    total_count: int
    has_more: bool


def member_history(
    db: Session,
    principal: UserPrincipal,
    member_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime,
    limit: int,
    offset: int,
    event_type: str | None,
) -> HistoryPage:
    member = viewable_member(
        db, principal, member_id
    )  # 404 for anything not in the caller's family
    now = datetime.now(UTC)
    devices = list(db.scalars(select(Device).where(Device.owner_member_id == member.id)))
    live = [d for d in devices if d.status != "revoked" and d.last_activity_at is not None]
    status: DeviceStatus = (
        device_status(max(d.last_activity_at for d in live if d.last_activity_at), now)
        if live
        else "unknown"
    )
    where = [
        TelemetryEvent.device_id.in_([d.id for d in devices]),
        TelemetryEvent.family_id == member.family_id,
        TelemetryEvent.occurred_at >= start,
        TelemetryEvent.occurred_at <= end,
    ]
    if event_type is not None:
        where.append(TelemetryEvent.event_type == event_type)
    total = 0
    rows: list[TelemetryEvent] = []
    if devices:
        total = db.scalar(select(func.count()).select_from(TelemetryEvent).where(*where)) or 0
        rows = list(
            db.scalars(
                select(TelemetryEvent)
                .where(*where)
                .order_by(TelemetryEvent.occurred_at.desc(), TelemetryEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
    # Metadata only: the audit row records that history was read, never what it contained.
    audit.record(
        db, action="location_accessed", resource_type="member", family_id=member.family_id,
        actor_user_id=principal.user_id, resource_id=member.id,
        meta={"scope": "history", "returned": len(rows)},
    )  # fmt: skip
    db.commit()
    items = [
        HistoryItem(
            e.id,
            e.occurred_at,
            e.received_at,
            e.event_type,
            classify_freshness(e.occurred_at, now)[0],
            dict(e.data),
        )
        for e in rows
    ]
    return HistoryPage(member.id, status, items, total, offset + len(items) < total)
