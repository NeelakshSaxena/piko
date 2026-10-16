"""Shared builders for API tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.db.models import FamilyMembership, RefreshSession, User

from .conftest import unique_email


def iso(delta: timedelta = timedelta(0)) -> str:
    return (datetime.now(UTC) + delta).isoformat().replace("+00:00", "Z")


def location_event(
    ago: timedelta = timedelta(seconds=10),
    lat: float = 40.7128,
    lon: float = -74.006,
    accuracy: float | None = 15,
    event_id: uuid.UUID | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "event_type": "location",
        "sequence_number": sequence,
        "occurred_at": iso(-ago),
        "data": {"latitude": lat, "longitude": lon, "accuracy_meters": accuracy},
    }


def battery_event(percent: int, ago: timedelta = timedelta(seconds=10)) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "battery",
        "occurred_at": iso(-ago),
        "data": {"percent": percent, "is_charging": False},
    }


def batch(
    device_id: str, events: list[dict[str, Any]], batch_id: str | None = None
) -> dict[str, Any]:
    return {
        "batch_id": batch_id or str(uuid.uuid4()),
        "schema_version": 1,
        "device_id": device_id,
        "events": events,
    }


def child_user_token(app: FastAPI, db: Session, family_id: uuid.UUID) -> tuple[str, uuid.UUID]:
    """A valid access token for a user whose only membership is `child` (children cannot log in,
    so this is the only way to exercise role checks). Returns (token, membership_id)."""
    user = User(email=unique_email("kid"), password_hash="!")
    db.add(user)
    db.flush()
    membership = FamilyMembership(family_id=family_id, user_id=user.id, role="child")
    session = RefreshSession(
        user_id=user.id,
        family_id=family_id,
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add_all([membership, session])
    db.commit()
    token = app.state.tokens.issue_access(TokenClaims(user.id, session.id, family_id))
    return token, membership.id
