"""Freshness and device-status rules. Thresholds come from docs/API_CONTRACTS.md."""

from datetime import datetime
from typing import Literal

Freshness = Literal["fresh", "stale", "unknown"]
DeviceStatus = Literal["online", "offline", "unknown"]

FRESH_SECONDS = 5 * 60
UNKNOWN_AFTER_SECONDS = 24 * 3600
# A device that has not contacted the server within this window is reported offline. This is an
# inference from silence, not a device-reported fact; the API says so via the field name.
ONLINE_WINDOW_SECONDS = 5 * 60


def classify_freshness(occurred_at: datetime | None, now: datetime) -> tuple[Freshness, int | None]:
    """Age is measured from when the reading was captured (occurred_at), never from receipt."""
    if occurred_at is None:
        return "unknown", None
    age = max(0, int((now - occurred_at).total_seconds()))
    if age <= FRESH_SECONDS:
        return "fresh", age
    if age <= UNKNOWN_AFTER_SECONDS:
        return "stale", age
    return "unknown", age


def device_status(last_activity_at: datetime | None, now: datetime) -> DeviceStatus:
    if last_activity_at is None:
        return "unknown"
    age = (now - last_activity_at).total_seconds()
    return "online" if age <= ONLINE_WINDOW_SECONDS else "offline"
