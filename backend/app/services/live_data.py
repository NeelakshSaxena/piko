"""Optional live flight and train status for Journeys (ADR-027).

Manual entry is the default and the source of truth. This module only *reports what a provider said*, once
per request from the device; it never writes to a journey, and it never fills a gap with a guess. Every
failure collapses to a fixed `LiveState` (no provider text, URL, key or body is kept), so a caller cannot
leak a credential by logging a result or an exception.

Providers (endpoints and fields were read from their documentation, see docs/JOURNEYS.md):
  * Aviationstack  GET https://api.aviationstack.com/v1/flights?access_key=...&flight_iata=...
  * RailRadar      GET https://api.railradar.in/v1/trains/{number}/live   (Authorization: Bearer ...)
"""

import logging
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import LiveDataUsage

log = logging.getLogger("piko.live")
# httpx logs every request URL at INFO, and Aviationstack authenticates with a query parameter.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

AVIATIONSTACK_URL = "https://api.aviationstack.com/v1/flights"
RAILRADAR_URL = "https://api.railradar.in/v1/trains/{number}/live"

FLIGHT_RE = re.compile(r"^[A-Z0-9]{2}[0-9]{1,4}[A-Z]?$")
TRAIN_RE = re.compile(r"^[0-9]{5}$")
_FLIGHT_STATUSES = {"scheduled", "active", "landed", "cancelled", "incident", "diverted"}
_TOKEN_RE = re.compile(r"^[a-z][a-z _-]{0,23}$")
_NOTICE_RE = re.compile(r"^[A-Z][A-Z_]{0,23}$")
_GATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 -]{0,7}$")
_CACHE_MAX = 512


class LiveState(StrEnum):
    OK = "ok"
    DISABLED = "disabled"  # provider is "manual": nothing was called
    NOT_CONFIGURED = "not_configured"  # a provider is selected but its key is missing
    NOT_FOUND = "not_found"  # the provider answered and has no matching flight/train
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"  # timeout, network error or provider 5xx
    UNUSABLE = "unusable"  # an answer arrived but it was not in the documented shape


@dataclass(frozen=True)
class LiveStatus:
    status: str | None = None
    departure_delay_minutes: int | None = None
    arrival_delay_minutes: int | None = None
    running_delay_minutes: int | None = (
        None  # trains: the delay "now", only when the provider says it is live
    )
    departure_gate: str | None = None
    departure_terminal: str | None = None
    arrival_gate: str | None = None
    arrival_terminal: str | None = None
    provider_updated_at: datetime | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiveResult:
    state: LiveState
    provider: str | None
    checked_at: datetime
    status: LiveStatus | None = None


def _minutes(value: Any, low: int, high: int) -> int | None:
    # bool is an int subclass; a boolean is never a delay.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None  # NaN/inf from a provider is not a delay (int() would raise)
    if value != int(value):
        return None
    return int(value) if low <= value <= high else None


def _gate(value: Any) -> str | None:
    return value if isinstance(value, str) and _GATE_RE.fullmatch(value) else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None  # a time with no offset cannot be placed


def _error_state(body: Any, http_status: int) -> LiveState:
    code = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        raw = body["error"].get("code")
        code = raw.lower() if isinstance(raw, str) else ""
    if code in {
        "invalid_access_key",
        "missing_access_key",
        "inactive_user",
        "function_access_restricted",
    }:
        return LiveState.AUTH_FAILED
    if code in {"usage_limit_reached", "rate_limit_reached", "rate_limited"}:
        return LiveState.RATE_LIMITED
    if code in {"404_not_found", "not_found"}:
        return LiveState.NOT_FOUND
    if http_status in (401, 403):
        return LiveState.AUTH_FAILED
    if http_status == 429:
        return LiveState.RATE_LIMITED
    if http_status >= 500 or code == "internal_error":
        return LiveState.UNAVAILABLE
    return LiveState.UNUSABLE


def parse_aviationstack(body: Any, flight: str, day: date) -> tuple[LiveState, LiveStatus | None]:
    """Normalises a /v1/flights answer. Only a row for this flight number *on this date* counts."""
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return LiveState.UNUSABLE, None
    rows = [
        r
        for r in body["data"]
        if isinstance(r, dict)
        and r.get("flight_date") == day.isoformat()
        and isinstance(r.get("flight"), dict)
        and str(r["flight"].get("iata") or "").upper() == flight
    ]
    if not rows:
        return LiveState.NOT_FOUND, None
    # A codeshare row repeats an operating flight under another number; prefer the operating one.
    rows.sort(key=lambda r: r["flight"].get("codeshared") is not None)
    row = rows[0]
    dep: dict[str, Any] = row["departure"] if isinstance(row.get("departure"), dict) else {}
    arr: dict[str, Any] = row["arrival"] if isinstance(row.get("arrival"), dict) else {}
    raw_status = row.get("flight_status")
    status = LiveStatus(
        status=raw_status if raw_status in _FLIGHT_STATUSES else None,
        departure_delay_minutes=_minutes(dep.get("delay"), 0, 2880),
        arrival_delay_minutes=_minutes(arr.get("delay"), 0, 2880),
        departure_gate=_gate(dep.get("gate")),
        departure_terminal=_gate(dep.get("terminal")),
        arrival_gate=_gate(arr.get("gate")),
        arrival_terminal=_gate(arr.get("terminal")),
    )
    if (
        status.status is None
        and status.departure_delay_minutes is None
        and status.arrival_delay_minutes is None
    ):
        return LiveState.UNUSABLE, None
    return LiveState.OK, status


def parse_railradar(body: Any, number: str) -> tuple[LiveState, LiveStatus | None]:
    if (
        not isinstance(body, dict)
        or body.get("success") is not True
        or not isinstance(body.get("data"), dict)
    ):
        return LiveState.UNUSABLE, None
    data = body["data"]
    if str(data.get("trainNumber")) != number:
        return LiveState.UNUSABLE, None
    raw_status = data.get("status")
    status_word = (
        raw_status.lower()
        if isinstance(raw_status, str) and _TOKEN_RE.fullmatch(raw_status.lower())
        else None
    )
    notices: list[str] = []
    exceptions = data.get("exceptions")
    if isinstance(exceptions, list):
        for item in exceptions[:5]:
            kind = item.get("type") if isinstance(item, dict) else None
            if isinstance(kind, str) and _NOTICE_RE.fullmatch(kind):
                notices.append(kind)
    # A delay is reported as "current" only when the provider says the run is live; a missing flag is not assumed.
    live = data.get("isLive")
    delay = _minutes(data.get("delayMinutes"), -60, 2880) if live is True else None
    # Only what the provider itself said makes an answer usable; the notices below are ours.
    if status_word is None and delay is None and not notices:
        return LiveState.UNUSABLE, None
    if live is False:
        notices.append("NOT_LIVE")
    elif live is not True:
        notices.append("LIVE_UNCONFIRMED")
    return LiveState.OK, LiveStatus(
        status=status_word,
        running_delay_minutes=delay,
        provider_updated_at=_when(data.get("lastUpdatedAt")),
        notices=tuple(notices),
    )


class DatabaseBudget:
    """Counts provider calls per UTC day in the database, so the limit holds across serverless instances
    and restarts. One advisory lock per provider makes the day and month checks one atomic decision."""

    def __init__(self, settings: Settings, factory: "sessionmaker[Session]") -> None:
        self._daily = settings.live_data_daily_budget
        self._monthly = settings.live_data_monthly_budget
        self._factory = factory

    def __call__(self, provider: str) -> bool:
        if self._daily <= 0 or self._monthly <= 0:
            return False
        today = datetime.now(UTC).date()
        with self._factory() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": provider})
            month = db.scalar(
                select(func.coalesce(func.sum(LiveDataUsage.calls), 0)).where(
                    LiveDataUsage.provider == provider, LiveDataUsage.day >= today.replace(day=1)
                )
            )
            if (month or 0) >= self._monthly:
                return False
            counted = db.scalar(
                pg_insert(LiveDataUsage)
                .values(provider=provider, day=today, calls=1)
                .on_conflict_do_update(
                    index_elements=["provider", "day"],
                    set_={"calls": LiveDataUsage.calls + 1},
                    where=LiveDataUsage.calls < self._daily,
                )
                .returning(LiveDataUsage.calls)
            )
            db.commit()
            return counted is not None


class LiveData:
    """Looks up one flight or train. Never raises; every outcome is a `LiveResult`."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        budget: Callable[[str], bool] | None = None,
    ) -> None:
        """`budget(provider)` spends one provider call from a limit shared by every server instance and says
        whether it was allowed. None means unlimited (tests only; the app always passes one)."""
        self._s = settings
        self._client = client or httpx.Client(
            timeout=settings.live_data_timeout_seconds, follow_redirects=False
        )
        self._clock = clock
        self._budget = budget
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, str, str], threading.Lock] = {}
        self._cache: dict[tuple[str, str, str], tuple[float, LiveResult]] = {}
        self._cooldown: dict[str, tuple[float, LiveState]] = {}

    def flight(self, flight: str, day: date) -> LiveResult:
        provider = self._s.flight_data_provider
        key = self._s.aviationstack_api_key
        return self._lookup(
            "aviationstack" if provider == "aviationstack" else None,
            key.get_secret_value() if key else "",
            flight,
            day.isoformat(),
            lambda secret: self._get(
                AVIATIONSTACK_URL,
                {"access_key": secret, "flight_iata": flight, "limit": 25},
                {},
                lambda body: parse_aviationstack(body, flight, day),
            ),
        )

    def train(self, number: str) -> LiveResult:
        provider = self._s.rail_data_provider
        key = self._s.railradar_api_key
        return self._lookup(
            "railradar" if provider == "railradar" else None,
            key.get_secret_value() if key else "",
            number,
            "",
            lambda secret: self._get(
                RAILRADAR_URL.format(number=number),
                {},
                {"Authorization": f"Bearer {secret}"},
                lambda body: parse_railradar(body, number),
            ),
        )

    def _lookup(
        self,
        provider: str | None,
        secret: str,
        ident: str,
        day: str,
        fetch: Callable[[str], tuple[LiveState, LiveStatus | None]],
    ) -> LiveResult:
        now = self._clock()
        stamp = datetime.fromtimestamp(now).astimezone()
        if provider is None:
            return LiveResult(LiveState.DISABLED, None, stamp)
        if not secret.strip():
            return LiveResult(LiveState.NOT_CONFIGURED, provider, stamp)
        cache_key = (provider, ident, day)
        early = self._answer_without_calling(cache_key, provider, now, stamp)
        if early is not None:
            return early
        # Single flight: identical simultaneous lookups share one provider call. The first fetches, the
        # others wait and then find its answer in the cache (or its cooldown).
        with self._lock:
            flight = self._inflight.setdefault(cache_key, threading.Lock())
        try:
            with flight:
                now = self._clock()
                early = self._answer_without_calling(cache_key, provider, now, stamp)
                if early is not None:
                    return early
                result = self._call(provider, secret, fetch, now, stamp)
                self._remember(cache_key, provider, result, now)
                return result
        finally:
            with self._lock:
                self._inflight.pop(cache_key, None)

    def _answer_without_calling(
        self, cache_key: tuple[str, str, str], provider: str, now: float, stamp: datetime
    ) -> LiveResult | None:
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and hit[0] > now:
                return hit[1]
            cooling = self._cooldown.get(provider)
            if cooling and cooling[0] > now:
                return LiveResult(cooling[1], provider, stamp)
        return None

    def _call(
        self,
        provider: str,
        secret: str,
        fetch: Callable[[str], tuple[LiveState, LiveStatus | None]],
        now: float,
        stamp: datetime,
    ) -> LiveResult:
        if self._budget is not None:
            try:
                allowed = self._budget(provider)
            except Exception:  # noqa: BLE001 - if the budget cannot be checked, no call is made
                return LiveResult(LiveState.UNAVAILABLE, provider, stamp)
            if not allowed:
                log.info("live lookup provider=%s budget exhausted", provider)
                return LiveResult(
                    LiveState.RATE_LIMITED, provider, stamp
                )  # cooldown set by _remember
        try:
            state, status = fetch(secret.strip())
        except Exception:  # noqa: BLE001 - nothing from an exception (it can hold the URL and key) is kept
            state, status = LiveState.UNAVAILABLE, None
        return LiveResult(state, provider, stamp, status)

    def _remember(
        self, cache_key: tuple[str, str, str], provider: str, result: LiveResult, now: float
    ) -> None:
        state = result.state
        log.info("live lookup provider=%s state=%s", provider, state.value)
        with self._lock:
            if state in (LiveState.OK, LiveState.NOT_FOUND) and self._s.live_data_cache_seconds:
                if len(self._cache) >= _CACHE_MAX:
                    self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
                    if len(self._cache) >= _CACHE_MAX:
                        self._cache.clear()
                self._cache[cache_key] = (now + self._s.live_data_cache_seconds, result)
            elif state in (LiveState.AUTH_FAILED, LiveState.RATE_LIMITED):
                self._cooldown[provider] = (now + self._s.live_data_cooldown_seconds, state)
            elif (
                state
                in (
                    LiveState.UNAVAILABLE,
                    LiveState.UNUSABLE,
                )
            ):  # may be a blip: back off briefly, not for the full cooldown (and spend no more budget)
                self._cooldown[provider] = (
                    now + min(60, self._s.live_data_cooldown_seconds),
                    state,
                )

    def _get(
        self,
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        parse: Callable[[Any], tuple[LiveState, LiveStatus | None]],
    ) -> tuple[LiveState, LiveStatus | None]:
        try:
            response = self._client.get(url, params=params, headers=headers)
        except httpx.HTTPError:
            return LiveState.UNAVAILABLE, None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or (isinstance(body, dict) and "error" in body):
            return _error_state(body, response.status_code), None
        return parse(body)
