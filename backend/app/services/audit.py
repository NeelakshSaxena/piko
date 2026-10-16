"""Audit trail. Metadata only: never coordinates, message bodies, passwords or tokens."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(
    db: Session,
    *,
    action: str,
    resource_type: str,
    outcome: str = "success",
    family_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_device_id: uuid.UUID | None = None,
    resource_id: uuid.UUID | None = None,
    reason: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Adds to the caller's transaction; the caller commits."""
    db.add(
        AuditEvent(
            action=action,
            resource_type=resource_type,
            outcome=outcome,
            family_id=family_id,
            actor_user_id=actor_user_id,
            actor_device_id=actor_device_id,
            resource_id=resource_id,
            reason=reason,
            meta=meta,
        )
    )
