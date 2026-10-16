"""Telemetry event validation (pure; no framework or database).

Validation failures return a fixed, value-free reason string so coordinates and other payload
content never reach responses or logs.
"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_DATA_KEYS = 8
MAX_SEQUENCE = 2**63 - 1
_NETWORK_TYPE_RE = re.compile(r"^[a-z0-9_]{1,32}$")

LOCATION_KEYS = {"latitude", "longitude", "accuracy_meters"}
BATTERY_KEYS = {"percent", "is_charging"}
CONNECTIVITY_KEYS = {"network_type", "signal_strength"}
EVENT_TYPES = {"location", "battery", "connectivity"}


@dataclass(frozen=True)
class ValidEvent:
    event_type: str
    occurred_at: datetime
    sequence_number: int | None
    data: dict[str, Any]


class EventRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)  # an int beyond the float range raises OverflowError
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def parse_occurred_at(raw: str) -> datetime:
    """ISO 8601 with an explicit offset, normalised to UTC."""
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise EventRejected("occurred_at is not a valid ISO 8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventRejected("occurred_at must include a timezone offset")
    try:
        return parsed.astimezone(UTC)
    except OverflowError:  # e.g. 0001-01-01T00:00:00+05:00 cannot be expressed in UTC
        raise EventRejected("occurred_at is not a valid ISO 8601 timestamp") from None


def _validate_location(data: dict[str, Any]) -> dict[str, Any]:
    lat, lon = _number(data.get("latitude")), _number(data.get("longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise EventRejected("location coordinates missing or out of range")
    out: dict[str, Any] = {"latitude": lat, "longitude": lon, "accuracy_meters": None}
    if data.get("accuracy_meters") is not None:
        acc = _number(data["accuracy_meters"])
        if acc is None or not (0 <= acc <= 10000):
            raise EventRejected("accuracy_meters must be between 0 and 10000")
        out["accuracy_meters"] = acc
    return out


def _validate_battery(data: dict[str, Any]) -> dict[str, Any]:
    pct = data.get("percent")
    if isinstance(pct, bool) or not isinstance(pct, int) or not (0 <= pct <= 100):
        raise EventRejected("battery percent must be an integer between 0 and 100")
    charging = data.get("is_charging")
    if charging is not None and not isinstance(charging, bool):
        raise EventRejected("is_charging must be a boolean")
    return {"percent": pct, "is_charging": charging}


def _validate_connectivity(data: dict[str, Any]) -> dict[str, Any]:
    net = data.get("network_type")
    if not isinstance(net, str) or not _NETWORK_TYPE_RE.fullmatch(net):
        raise EventRejected("network_type is invalid")
    sig = data.get("signal_strength")
    if sig is not None and (
        isinstance(sig, bool) or not isinstance(sig, int) or not -200 <= sig <= 100
    ):
        raise EventRejected("signal_strength is out of range")
    return {"network_type": net, "signal_strength": sig}


_VALIDATORS = {
    "location": (LOCATION_KEYS, _validate_location),
    "battery": (BATTERY_KEYS, _validate_battery),
    "connectivity": (CONNECTIVITY_KEYS, _validate_connectivity),
}


def validate_event(
    *,
    event_type: str,
    occurred_at: str,
    sequence_number: int | None,
    data: dict[str, Any],
    now: datetime,
    max_age: timedelta,
    future_skew: timedelta,
) -> ValidEvent:
    if event_type not in EVENT_TYPES:
        raise EventRejected("unsupported event_type")
    if sequence_number is not None and not (0 <= sequence_number <= MAX_SEQUENCE):
        raise EventRejected("sequence_number out of range")
    when = parse_occurred_at(occurred_at)
    if when > now + future_skew:
        raise EventRejected("occurred_at is in the future")
    if when < now - max_age:
        raise EventRejected("occurred_at is older than the retention window")
    allowed_keys, validator = _VALIDATORS[event_type]
    if len(data) > MAX_DATA_KEYS or not set(data) <= allowed_keys:
        raise EventRejected("data contains unsupported fields")
    return ValidEvent(event_type, when, sequence_number, validator(data))
