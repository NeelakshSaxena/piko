"""Unit tests: telemetry validation and freshness rules (pure domain, no database)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain.freshness import classify_freshness, device_status
from app.domain.telemetry import EventRejected, validate_event

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(days=30)
SKEW = timedelta(seconds=60)


def check(
    event_type: str = "location",
    occurred_at: str = "2026-10-16T11:59:00Z",
    sequence: int | None = None,
    data: dict[str, Any] | None = None,
):  # type: ignore[no-untyped-def]
    if data is None:
        data = {"latitude": 10.5, "longitude": 20.5, "accuracy_meters": 12}
    return validate_event(
        event_type=event_type, occurred_at=occurred_at, sequence_number=sequence, data=data,
        now=NOW, max_age=MAX_AGE, future_skew=SKEW,
    )  # fmt: skip


def reason(**kw: Any) -> str:
    with pytest.raises(EventRejected) as exc:
        check(**kw)
    return exc.value.reason


def test_valid_location_normalised_to_utc() -> None:
    ev = check(occurred_at="2026-10-16T17:29:00+05:30")
    assert ev.occurred_at == datetime(2026, 10, 16, 11, 59, tzinfo=UTC)
    assert ev.data == {"latitude": 10.5, "longitude": 20.5, "accuracy_meters": 12.0}


def test_accuracy_is_optional_and_null_allowed() -> None:
    assert check(data={"latitude": 1, "longitude": 2}).data["accuracy_meters"] is None
    assert (
        check(data={"latitude": 1, "longitude": 2, "accuracy_meters": None}).data["accuracy_meters"]
        is None
    )


@pytest.mark.parametrize(
    "data",
    [
        {"latitude": 91, "longitude": 0}, {"latitude": -91, "longitude": 0},
        {"latitude": 0, "longitude": 181}, {"latitude": 0, "longitude": -181},
        {"latitude": "1", "longitude": 0}, {"latitude": True, "longitude": 0},
        {"latitude": float("nan"), "longitude": 0}, {"latitude": 0, "longitude": float("inf")},
        {"latitude": 0}, {"longitude": 0}, {},
        {"latitude": 0, "longitude": 0, "accuracy_meters": -1},
        {"latitude": 0, "longitude": 0, "accuracy_meters": 10001},
        {"latitude": 0, "longitude": 0, "accuracy_meters": "5"},
        {"latitude": 0, "longitude": 0, "battery_percent": 85},  # unknown field
        {"latitude": 0, "longitude": 0, "extra": {"nested": 1}},
    ],
)  # fmt: skip
def test_invalid_location_payloads_rejected(data: dict[str, Any]) -> None:
    reason(data=data)


def test_rejection_reasons_never_echo_values() -> None:
    r = reason(data={"latitude": 123.456789, "longitude": 0})
    assert "123" not in r


@pytest.mark.parametrize(
    "when",
    ["", "yesterday", "2026-10-16T11:59:00", "2026-10-16", "1760000000", "2026-13-01T00:00:00Z"],
)
def test_invalid_or_naive_timestamps_rejected(when: str) -> None:
    reason(occurred_at=when)


def test_future_beyond_skew_rejected_but_small_skew_tolerated() -> None:
    assert "future" in reason(occurred_at="2026-10-16T12:02:00Z")
    check(occurred_at="2026-10-16T12:00:30Z")


def test_age_limit_is_the_retention_window_not_24_hours() -> None:
    check(occurred_at=(NOW - timedelta(days=29)).isoformat())  # offline backlog accepted
    assert "retention" in reason(occurred_at=(NOW - timedelta(days=31)).isoformat())


@pytest.mark.parametrize("seq", [-1, 2**63])
def test_sequence_bounds(seq: int) -> None:
    reason(sequence=seq)


def test_battery_and_connectivity() -> None:
    assert check("battery", data={"percent": 0}).data == {"percent": 0, "is_charging": None}
    assert check("battery", data={"percent": 100, "is_charging": True}).data["is_charging"] is True
    for bad in (
        {"percent": 101},
        {"percent": -1},
        {"percent": 50.5},
        {"percent": True},
        {"percent": 5, "is_charging": "yes"},
    ):
        reason(event_type="battery", data=bad)
    ok = check("connectivity", data={"network_type": "wifi", "signal_strength": -60})
    assert ok.data["network_type"] == "wifi"
    for bad in (
        {"network_type": "WiFi!"},
        {"network_type": ""},
        {"signal_strength": 1},
        {"network_type": "a" * 33},
    ):
        reason(event_type="connectivity", data=bad)


def test_unknown_event_type_rejected() -> None:
    assert "unsupported" in reason(event_type="custom")


def test_freshness_thresholds() -> None:
    assert classify_freshness(None, NOW) == ("unknown", None)
    assert classify_freshness(NOW - timedelta(seconds=300), NOW)[0] == "fresh"
    assert classify_freshness(NOW - timedelta(seconds=301), NOW)[0] == "stale"
    assert classify_freshness(NOW - timedelta(hours=24), NOW)[0] == "stale"
    assert classify_freshness(NOW - timedelta(hours=24, seconds=1), NOW)[0] == "unknown"
    assert classify_freshness(NOW + timedelta(seconds=30), NOW) == ("fresh", 0)  # clock skew


def test_device_status_is_inferred_from_silence() -> None:
    assert device_status(None, NOW) == "unknown"
    assert device_status(NOW - timedelta(seconds=299), NOW) == "online"
    assert device_status(NOW - timedelta(seconds=301), NOW) == "offline"
