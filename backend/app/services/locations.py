"""Latest-known location for a family member, with honest freshness."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Device, DeviceLatestState
from app.domain.freshness import DeviceStatus, Freshness, classify_freshness, device_status
from app.services import audit
from app.services.authz import viewable_member
from app.services.principals import UserPrincipal


@dataclass(frozen=True)
class LocationView:
    member_id: uuid.UUID
    device_id: uuid.UUID | None
    available: bool
    freshness: Freshness
    freshness_seconds: int | None
    device_status: DeviceStatus
    latitude: float | None = None
    longitude: float | None = None
    accuracy_meters: float | None = None
    occurred_at: datetime | None = None
    received_at: datetime | None = None


def member_location(db: Session, principal: UserPrincipal, member_id: uuid.UUID) -> LocationView:
    member = viewable_member(db, principal, member_id)
    now = datetime.now(UTC)
    row = db.execute(
        select(Device, DeviceLatestState)
        .outerjoin(DeviceLatestState, DeviceLatestState.device_id == Device.id)
        .where(Device.owner_member_id == member.id, Device.status != "revoked")
        .order_by(DeviceLatestState.location_occurred_at.desc().nulls_last(), Device.paired_at)
        .limit(1)
    ).first()
    # Metadata only: the audit row never carries coordinates.
    audit.record(
        db, action="location_accessed", resource_type="member", family_id=member.family_id,
        actor_user_id=principal.user_id, resource_id=member.id,
    )  # fmt: skip
    db.commit()
    if row is None:
        return LocationView(member.id, None, False, "unknown", None, "unknown")
    device, state = row
    status = device_status(device.last_activity_at, now)
    occurred = state.location_occurred_at if state else None
    freshness, age = classify_freshness(occurred, now)
    if state is None or freshness == "unknown":
        # No data, or older than 24h: coordinates are withheld rather than shown as current.
        return LocationView(
            member.id, device.id, False, "unknown", age, status, occurred_at=occurred
        )
    return LocationView(
        member_id=member.id,
        device_id=device.id,
        available=True,
        freshness=freshness,
        freshness_seconds=age,
        device_status=status,
        latitude=float(state.location_latitude) if state.location_latitude is not None else None,
        longitude=float(state.location_longitude) if state.location_longitude is not None else None,
        accuracy_meters=(
            float(state.location_accuracy_meters)
            if state.location_accuracy_meters is not None
            else None
        ),
        occurred_at=occurred,
        received_at=state.location_received_at,
    )
