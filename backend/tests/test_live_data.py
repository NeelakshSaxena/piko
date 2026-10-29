"""Live flight/train lookups (ADR-027), against MOCKED provider HTTP only.

Nothing here contacts Aviationstack or RailRadar: the fixtures follow their published response shapes and the
handlers below stand in for the network. A pass here is not evidence that a real key or the live service works.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.live_data import LiveData, LiveState, parse_aviationstack, parse_railradar

from .conftest import build_settings, device_headers

KEY = "FAKE-TEST-KEY-do-not-log-0123456789"
DAY = date(2026, 11, 2)
TODAY = datetime.now(UTC).date().isoformat()


def cfg(tmp_path: Path, **over: object) -> Settings:
    # Explicit values (also None) so a developer's real .env cannot change what a test means.
    base: dict[str, object] = {
        "flight_data_provider": "aviationstack",
        "aviationstack_api_key": SecretStr(KEY),
        "rail_data_provider": "railradar",
        "railradar_api_key": SecretStr(KEY),
    }
    base.update(over)
    return build_settings(tmp_path, "unused", **base)


class Net:
    """A fake network: records requests, answers from a queue (the last answer repeats)."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def live(tmp_path: Path, net: Net, clock=None, **over: object) -> LiveData:  # type: ignore[no-untyped-def]
    return LiveData(
        cfg(tmp_path, **over), client=net.client(), clock=clock or (lambda: 1_000_000.0)
    )


def flight_row(
    date_: str = "2026-11-02", iata: str = "AI101", **extra: object
) -> dict[str, object]:
    row: dict[str, object] = {
        "flight_date": date_,
        "flight_status": "active",
        "departure": {
            "airport": "Indira Gandhi International",
            "timezone": "Asia/Kolkata",
            "iata": "DEL",
            "terminal": "3",
            "gate": "A12",
            "delay": 10,
            "scheduled": "2026-11-02T08:30:00+00:00",
        },
        "arrival": {
            "airport": "Chhatrapati Shivaji",
            "timezone": "Asia/Kolkata",
            "iata": "BOM",
            "terminal": "2",
            "gate": None,
            "baggage": None,
            "delay": 25,
            "scheduled": "2026-11-02T10:45:00+00:00",
        },
        "airline": {"name": "Air India", "iata": "AI", "icao": "AIC"},
        "flight": {"number": "101", "iata": iata, "icao": "AIC101", "codeshared": None},
        "aircraft": None,
        "live": None,
    }
    row.update(extra)
    return row


def avs(*rows: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "pagination": {"limit": 25, "offset": 0, "count": len(rows), "total": len(rows)},
            "data": list(rows),
        },
    )


RAIL_OK = {
    "success": True,
    "data": {
        "trainNumber": "12919",
        "trainName": "Malwa SF Express",
        "startDate": "2026-11-02",
        "lastUpdatedAt": "2026-11-02T07:14:00+05:30",
        "status": "running",
        "delayMinutes": 12,
        "exceptions": [{"type": "DIVERTED", "message": "free text that must not be passed on"}],
        "isLive": True,
        "trackingMode": "real-time",
    },
    "meta": {"traceId": "x", "timestamp": "2026-11-02T07:20:00+05:30"},
}


def rail_err(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status, json={"success": False, "error": {"code": code, "message": "m"}, "meta": {}}
    )


# ---- Aviationstack ----
def test_aviationstack_normalizes_and_authenticates_with_the_documented_parameters(
    tmp_path: Path,
) -> None:
    net = Net(avs(flight_row()))
    r = live(tmp_path, net).flight("AI101", DAY)
    assert r.state is LiveState.OK and r.provider == "aviationstack"
    st = r.status
    assert st is not None
    assert (st.status, st.departure_delay_minutes, st.arrival_delay_minutes) == ("active", 10, 25)
    assert (st.departure_gate, st.departure_terminal, st.arrival_gate, st.arrival_terminal) == (
        "A12",
        "3",
        None,
        "2",
    )
    req = net.requests[0]
    assert req.url.host == "api.aviationstack.com" and req.url.path == "/v1/flights"
    assert req.url.params["access_key"] == KEY and req.url.params["flight_iata"] == "AI101"
    assert (
        "flight_date" not in req.url.params
    )  # historical dates are a paid-plan feature; we filter instead


def test_a_row_for_another_date_or_flight_is_not_a_match(tmp_path: Path) -> None:
    other_day = flight_row(date_="2026-11-01")
    other_flight = flight_row(iata="AI102")
    r = live(tmp_path, Net(avs(other_day, other_flight))).flight("AI101", DAY)
    assert (r.state, r.status) == (LiveState.NOT_FOUND, None)
    assert live(tmp_path, Net(avs())).flight("AI101", DAY).state is LiveState.NOT_FOUND


def test_the_operating_flight_wins_over_a_codeshare_row(tmp_path: Path) -> None:
    shared = flight_row(
        flight={"number": "101", "iata": "AI101", "codeshared": {"airline_iata": "UK"}}
    )
    shared["arrival"] = {"delay": 99}  # a different story; must not be chosen
    r = live(tmp_path, Net(avs(shared, flight_row()))).flight("AI101", DAY)
    assert r.status is not None and r.status.arrival_delay_minutes == 25


@pytest.mark.parametrize(
    ("response", "state"),
    [
        (
            httpx.Response(401, json={"error": {"code": "invalid_access_key", "message": "m"}}),
            LiveState.AUTH_FAILED,
        ),
        (
            httpx.Response(401, json={"error": {"code": "missing_access_key", "message": "m"}}),
            LiveState.AUTH_FAILED,
        ),
        (
            httpx.Response(
                403, json={"error": {"code": "function_access_restricted", "message": "m"}}
            ),
            LiveState.AUTH_FAILED,
        ),
        (
            httpx.Response(429, json={"error": {"code": "usage_limit_reached", "message": "m"}}),
            LiveState.RATE_LIMITED,
        ),
        (
            httpx.Response(429, json={"error": {"code": "rate_limit_reached", "message": "m"}}),
            LiveState.RATE_LIMITED,
        ),
        (
            httpx.Response(200, json={"error": {"code": "usage_limit_reached"}}),
            LiveState.RATE_LIMITED,
        ),
        (
            httpx.Response(500, json={"error": {"code": "internal_error", "message": "m"}}),
            LiveState.UNAVAILABLE,
        ),
        (httpx.Response(502, text="<html>bad gateway</html>"), LiveState.UNAVAILABLE),
        (httpx.Response(404, json={"error": {"code": "404_not_found"}}), LiveState.NOT_FOUND),
        (httpx.Response(404, json={"error": {"code": "invalid_api_function"}}), LiveState.UNUSABLE),
        (httpx.Response(200, text="not json at all"), LiveState.UNUSABLE),
        (httpx.Response(200, json={"data": "not a list"}), LiveState.UNUSABLE),
        (httpx.Response(200, json=[1, 2, 3]), LiveState.UNUSABLE),
        (
            avs(
                flight_row(
                    flight_status="weird", departure={"delay": None}, arrival={"delay": "late"}
                )
            ),
            LiveState.UNUSABLE,
        ),
        (httpx.Response(418, json={"error": {"code": "something_new"}}), LiveState.UNUSABLE),
    ],
)
def test_aviationstack_failures_map_to_a_fixed_state(
    tmp_path: Path, response: httpx.Response, state: LiveState
) -> None:
    r = live(tmp_path, Net(response)).flight("AI101", DAY)
    assert r.state is state and r.status is None


def test_timeouts_and_network_errors_are_unavailable_and_keep_no_text(tmp_path: Path) -> None:
    for exc in (
        httpx.ConnectTimeout(f"timed out for https://x/?access_key={KEY}"),
        httpx.ConnectError("refused"),
    ):
        r = live(tmp_path, Net(exc)).flight("AI101", DAY)
        assert r.state is LiveState.UNAVAILABLE and KEY not in repr(r)


def test_out_of_range_and_boolean_delays_are_ignored() -> None:
    row = flight_row()
    row["flight_status"] = "weird"
    row["departure"] = {"delay": True}
    row["arrival"] = {"delay": 100000}
    state, status = parse_aviationstack({"data": [row]}, "AI101", DAY)
    assert (
        state is LiveState.UNUSABLE and status is None
    )  # nothing believable left: not "OK with zero delay"


def test_a_missing_delay_stays_missing_not_zero(tmp_path: Path) -> None:
    row = flight_row()
    row["arrival"] = {"gate": "B3"}
    r = live(tmp_path, Net(avs(row))).flight("AI101", DAY)
    assert (
        r.status is not None
        and r.status.arrival_delay_minutes is None
        and r.status.arrival_gate == "B3"
    )


# ---- RailRadar ----
def test_railradar_normalizes_and_uses_the_bearer_header(tmp_path: Path) -> None:
    net = Net(httpx.Response(200, json=RAIL_OK))
    r = live(tmp_path, net).train("12919")
    assert r.state is LiveState.OK and r.provider == "railradar"
    st = r.status
    assert st is not None
    assert (st.status, st.running_delay_minutes, st.notices) == ("running", 12, ("DIVERTED",))
    assert st.provider_updated_at is not None and st.provider_updated_at.utcoffset() is not None
    req = net.requests[0]
    assert req.url.host == "api.railradar.in" and req.url.path == "/v1/trains/12919/live"
    assert req.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(req.url)
    assert "message" not in repr(st) and "free text" not in repr(
        st
    )  # provider prose is never passed on


@pytest.mark.parametrize(
    ("response", "state"),
    [
        (rail_err(401, "UNAUTHORIZED"), LiveState.AUTH_FAILED),
        (rail_err(404, "NOT_FOUND"), LiveState.NOT_FOUND),
        (rail_err(429, "RATE_LIMITED"), LiveState.RATE_LIMITED),
        (rail_err(503, "UPSTREAM"), LiveState.UNAVAILABLE),
        (rail_err(400, "BAD_REQUEST"), LiveState.UNUSABLE),
        (httpx.Response(200, json={"success": False, "error": {"code": "X"}}), LiveState.UNUSABLE),
        (httpx.Response(200, json={"success": True, "data": []}), LiveState.UNUSABLE),
        (httpx.Response(200, text="<html>"), LiveState.UNUSABLE),
        (
            httpx.Response(200, json={"success": True, "data": {"trainNumber": "12919"}}),
            LiveState.UNUSABLE,
        ),
    ],
)
def test_railradar_failures_map_to_a_fixed_state(
    tmp_path: Path, response: httpx.Response, state: LiveState
) -> None:
    r = live(tmp_path, Net(response)).train("12919")
    assert r.state is state and r.status is None


def test_an_answer_for_a_different_train_is_refused() -> None:
    body = {"success": True, "data": {**RAIL_OK["data"], "trainNumber": "12920"}}  # type: ignore[dict-item]
    assert parse_railradar(body, "12919") == (LiveState.UNUSABLE, None)


def test_a_delay_the_provider_does_not_call_live_is_not_reported_as_current() -> None:
    body = {"success": True, "data": {**RAIL_OK["data"], "isLive": False}}  # type: ignore[dict-item]
    state, st = parse_railradar(body, "12919")
    assert state is LiveState.OK and st is not None
    assert st.running_delay_minutes is None and "NOT_LIVE" in st.notices


def test_a_time_without_an_offset_is_not_trusted() -> None:
    data = {**RAIL_OK["data"], "lastUpdatedAt": "2026-11-02T07:14:00"}  # type: ignore[dict-item]
    _, st = parse_railradar({"success": True, "data": data}, "12919")
    assert st is not None and st.provider_updated_at is None


# ---- configuration, caching, cooldown, redaction ----
def test_manual_mode_never_calls_a_provider_even_when_a_key_exists(tmp_path: Path) -> None:
    net = Net(avs(flight_row()))
    svc = live(tmp_path, net, flight_data_provider="manual", rail_data_provider="manual")
    assert svc.flight("AI101", DAY).state is LiveState.DISABLED
    assert svc.train("12919").state is LiveState.DISABLED
    assert net.requests == []


def test_a_selected_provider_without_a_key_is_not_configured_and_makes_no_call(
    tmp_path: Path,
) -> None:
    net = Net(avs(flight_row()))
    for key in (None, SecretStr(""), SecretStr("   ")):
        svc = live(tmp_path, net, aviationstack_api_key=key, railradar_api_key=key)
        assert svc.flight("AI101", DAY).state is LiveState.NOT_CONFIGURED
        assert svc.train("12919").state is LiveState.NOT_CONFIGURED
    assert net.requests == []


def test_defaults_are_manual_with_no_keys() -> None:
    s = Settings.model_construct()  # class defaults, ignoring any real .env
    assert (s.flight_data_provider, s.rail_data_provider) == ("manual", "manual")
    assert s.aviationstack_api_key is None and s.railradar_api_key is None


def test_answers_are_cached_so_a_small_quota_is_not_spent_twice(tmp_path: Path) -> None:
    now = [1_000_000.0]
    net = Net(avs(flight_row()))
    svc = live(tmp_path, net, clock=lambda: now[0], live_data_cache_seconds=300)
    first = svc.flight("AI101", DAY)
    assert svc.flight("AI101", DAY) is first and len(net.requests) == 1
    svc.flight("AI102", DAY)  # a different flight is a different question
    assert len(net.requests) == 2
    now[0] += 301
    svc.flight("AI101", DAY)
    assert len(net.requests) == 3


def test_failures_are_not_cached_but_auth_and_quota_failures_pause_the_provider(
    tmp_path: Path,
) -> None:
    now = [1_000_000.0]
    net = Net(
        httpx.Response(429, json={"error": {"code": "usage_limit_reached"}}), avs(flight_row())
    )
    svc = live(tmp_path, net, clock=lambda: now[0], live_data_cooldown_seconds=900)
    assert svc.flight("AI101", DAY).state is LiveState.RATE_LIMITED
    assert (
        svc.flight("AI101", DAY).state is LiveState.RATE_LIMITED and len(net.requests) == 1
    )  # no hammering
    now[0] += 901
    assert svc.flight("AI101", DAY).state is LiveState.OK and len(net.requests) == 2


def test_a_transient_failure_backs_off_briefly_only(tmp_path: Path) -> None:
    now = [1_000_000.0]
    net = Net(httpx.ConnectTimeout("t"), avs(flight_row()))
    svc = live(tmp_path, net, clock=lambda: now[0])
    assert svc.flight("AI101", DAY).state is LiveState.UNAVAILABLE
    now[0] += 61
    assert svc.flight("AI101", DAY).state is LiveState.OK


def test_an_unusable_answer_pauses_the_provider_briefly_so_it_cannot_drain_the_budget(
    tmp_path: Path,
) -> None:
    now = [1_000_000.0]
    net = Net(httpx.Response(200, text="not json at all"), avs(flight_row()))
    spent: list[str] = []
    svc = LiveData(
        cfg(tmp_path), client=net.client(), clock=lambda: now[0],
        budget=lambda p: spent.append(p) or True,
    )  # fmt: skip
    assert svc.flight("AI101", DAY).state is LiveState.UNUSABLE
    assert svc.flight("AI101", DAY).state is LiveState.UNUSABLE  # paused: no call, no budget
    assert len(net.requests) == 1 and len(spent) == 1
    now[0] += 61
    assert svc.flight("AI101", DAY).state is LiveState.OK


def test_the_key_never_reaches_a_log_even_at_info(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    svc = live(
        tmp_path,
        Net(avs(flight_row()), httpx.Response(401, json={"error": {"code": "invalid_access_key"}})),
    )
    svc.flight("AI101", DAY)
    live(tmp_path, Net(httpx.Response(401, json={"error": {"code": "invalid_access_key"}}))).train(
        "12919"
    )
    live(tmp_path, Net(httpx.ConnectTimeout(f"x {KEY}"))).flight("AI103", DAY)
    assert KEY not in caplog.text
    assert any(r.name == "piko.live" for r in caplog.records)  # we did log; just not the secret


def test_the_secret_is_not_in_the_settings_repr(tmp_path: Path) -> None:
    s = cfg(tmp_path)
    assert KEY not in repr(s) and KEY not in str(s.model_dump())


# ---- HTTP API ----
def _install(client, settings: Settings, net: Net, **over: object) -> None:  # type: ignore[no-untyped-def]
    client.app.state.live_data = LiveData(settings.model_copy(update=over), client=net.client())


def test_api_lookup_returns_normalized_data_and_never_the_key(
    make_family, client, settings
) -> None:  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    h = device_headers(token)
    _install(
        client,
        settings,
        Net(avs(flight_row(date_=TODAY))),
        flight_data_provider="aviationstack",
        aviationstack_api_key=SecretStr(KEY),
    )
    r = client.get(
        "/api/v1/journeys/live/flight", params={"flight": "ai 101", "day": TODAY}, headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["state"] == "ok"
        and body["provider"] == "aviationstack"
        and body["arrival_delay_minutes"] == 25
    )
    assert KEY not in r.text and "access_key" not in r.text

    _install(
        client,
        settings,
        Net(httpx.Response(200, json=RAIL_OK)),
        rail_data_provider="railradar",
        railradar_api_key=SecretStr(KEY),
    )
    t = client.get("/api/v1/journeys/live/train", params={"number": "12919"}, headers=h)
    assert t.status_code == 200 and t.json()["running_delay_minutes"] == 12 and KEY not in t.text


def test_api_default_is_manual_and_calls_nothing(make_family, client, settings) -> None:  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    net = Net(avs(flight_row(date_=TODAY)))
    _install(
        client,
        settings,
        net,
        flight_data_provider="manual",
        rail_data_provider="manual",
        aviationstack_api_key=None,
        railradar_api_key=None,
    )
    h = device_headers(token)
    f = client.get(
        "/api/v1/journeys/live/flight", params={"flight": "AI101", "day": TODAY}, headers=h
    )
    t = client.get("/api/v1/journeys/live/train", params={"number": "12919"}, headers=h)
    assert (f.status_code, f.json()["state"], f.json()["provider"]) == (200, "disabled", None)
    assert (t.status_code, t.json()["state"]) == (200, "disabled")
    assert net.requests == []


def test_api_requires_a_device_credential_and_validates_input(
    make_family, client, settings
) -> None:  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    _install(
        client,
        settings,
        Net(avs(flight_row(date_=TODAY))),
        flight_data_provider="aviationstack",
        aviationstack_api_key=SecretStr(KEY),
    )
    url, q = "/api/v1/journeys/live/flight", {"flight": "AI101", "day": TODAY}
    assert client.get(url, params=q).status_code == 401  # no credential
    assert client.get(url, params=q, headers=fam.headers).status_code in (
        401,
        403,
    )  # a parent token is not a device
    h = device_headers(token)
    for bad in ("", "A", "AI-101", "AI10000", "../x", "AI101&x=1"):
        assert client.get(url, params={**q, "flight": bad}, headers=h).status_code in (400, 422), (
            bad
        )
    assert client.get(url, params={**q, "day": "tomorrow"}, headers=h).status_code in (400, 422)
    for bad in ("1291", "129190", "abcde", "12919/live"):
        assert client.get(
            "/api/v1/journeys/live/train", params={"number": bad}, headers=h
        ).status_code in (400, 422), bad


def test_api_lookup_is_rate_limited_per_device_and_changes_no_journey(
    make_family, client, settings
) -> None:  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    h = device_headers(token)
    _install(
        client,
        settings,
        Net(avs(flight_row(date_=TODAY))),
        flight_data_provider="aviationstack",
        aviationstack_api_key=SecretStr(KEY),
    )
    before = client.get("/api/v1/journeys", headers=h).json()
    codes = [
        client.get(
            "/api/v1/journeys/live/flight",
            params={"flight": "AI101", "day": TODAY},
            headers=h,
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [200] * 10 and 429 in codes[10:]
    assert (
        client.get("/api/v1/journeys", headers=h).json() == before
    )  # a lookup never writes a journey


# ---- audit follow-ups ----
def test_the_provider_url_is_https_so_the_key_never_travels_in_clear() -> None:
    from app.services.live_data import AVIATIONSTACK_URL, RAILRADAR_URL

    assert AVIATIONSTACK_URL.startswith("https://") and RAILRADAR_URL.startswith("https://")


def test_a_nan_or_infinite_delay_from_a_provider_is_ignored_not_fatal() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        row = flight_row(flight_status="active")
        row["arrival"] = {"delay": bad}
        state, status = parse_aviationstack({"data": [row]}, "AI101", DAY)
        assert state is LiveState.OK and status is not None and status.arrival_delay_minutes is None


def test_a_missing_islive_flag_is_not_assumed_live() -> None:
    data = {k: v for k, v in RAIL_OK["data"].items() if k != "isLive"}  # type: ignore[union-attr]
    state, st = parse_railradar({"success": True, "data": data}, "12919")
    assert state is LiveState.OK and st is not None
    assert st.running_delay_minutes is None and "LIVE_UNCONFIRMED" in st.notices


def test_api_rejects_a_trailing_newline_and_far_dates(make_family, client, settings) -> None:  # type: ignore[no-untyped-def]
    fam = make_family()
    _id, token, _ = fam.pair_device()
    h = device_headers(token)
    net = Net(avs(flight_row(date_=TODAY)))
    _install(
        client,
        settings,
        net,
        flight_data_provider="aviationstack",
        aviationstack_api_key=SecretStr(KEY),
    )
    url = "/api/v1/journeys/live/flight"
    assert client.get(url, params={"flight": "AI101\n", "day": TODAY}, headers=h).status_code == 400
    assert (
        client.get(
            "/api/v1/journeys/live/train", params={"number": "12919\n"}, headers=h
        ).status_code
        == 400
    )
    far = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()
    assert client.get(url, params={"flight": "AI101", "day": far}, headers=h).status_code == 400
    assert net.requests == []  # none of those reached the provider


# ---- audit M6: a bounded provider budget and single-flight lookups ----
def test_an_exhausted_budget_makes_no_provider_call_and_reports_rate_limited(
    tmp_path: Path,
) -> None:
    net = Net(avs(flight_row()))
    spent: list[str] = []

    def budget(provider: str) -> bool:
        spent.append(provider)
        return len(spent) <= 1

    svc = LiveData(cfg(tmp_path), client=net.client(), clock=lambda: 1_000_000.0, budget=budget)
    assert svc.flight("AI101", DAY).state == LiveState.OK
    second = svc.flight("AI102", DAY)  # a different flight: not cached, so it needs budget
    assert second.state == LiveState.RATE_LIMITED
    assert len(net.requests) == 1
    # And the provider is now paused: no further budget checks or calls until the cooldown ends.
    assert svc.flight("AI103", DAY).state == LiveState.RATE_LIMITED
    assert len(spent) == 2 and len(net.requests) == 1


def test_cached_answers_and_manual_mode_spend_no_budget(tmp_path: Path) -> None:
    net = Net(avs(flight_row()))
    spent: list[str] = []
    svc = LiveData(
        cfg(tmp_path), client=net.client(), clock=lambda: 1_000_000.0,
        budget=lambda p: spent.append(p) or True,
    )  # fmt: skip
    svc.flight("AI101", DAY)
    svc.flight("AI101", DAY)  # cache hit
    assert spent == ["aviationstack"]
    manual = LiveData(
        cfg(tmp_path, flight_data_provider="manual"), client=net.client(),
        budget=lambda p: spent.append(p) or True,
    )  # fmt: skip
    assert manual.flight("AI101", DAY).state == LiveState.DISABLED
    assert spent == ["aviationstack"]


def test_a_budget_that_cannot_be_checked_fails_closed(tmp_path: Path) -> None:
    net = Net(avs(flight_row()))

    def broken(provider: str) -> bool:
        raise RuntimeError("database down")

    svc = LiveData(cfg(tmp_path), client=net.client(), budget=broken)
    assert svc.flight("AI101", DAY).state == LiveState.UNAVAILABLE
    assert net.requests == []


def test_simultaneous_identical_lookups_share_one_provider_call(tmp_path: Path) -> None:
    import threading

    release = threading.Event()
    calls: list[int] = []

    def slow(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        release.wait(5)
        return avs(flight_row())

    spent: list[str] = []
    svc = LiveData(
        cfg(tmp_path), client=httpx.Client(transport=httpx.MockTransport(slow)),
        budget=lambda p: spent.append(p) or True,
    )  # fmt: skip
    results: list[LiveState] = []
    threads = [
        threading.Thread(target=lambda: results.append(svc.flight("AI101", DAY).state))
        for _ in range(6)
    ]
    for t in threads:
        t.start()
    release.set()
    for t in threads:
        t.join(10)
    assert results == [LiveState.OK] * 6
    assert len(calls) == 1 and len(spent) == 1


def test_database_budget_enforces_daily_and_monthly_limits_across_instances(
    client, settings
) -> None:  # type: ignore[no-untyped-def]
    import secrets

    from app.db.models import LiveDataUsage
    from app.services.live_data import DatabaseBudget

    factory = client.app.state.session_factory
    daily = DatabaseBudget(settings.model_copy(update={"live_data_daily_budget": 2}), factory)
    other_instance = DatabaseBudget(
        settings.model_copy(update={"live_data_daily_budget": 2}), factory
    )
    provider = "t" + secrets.token_hex(6)
    assert [daily(provider), other_instance(provider), daily(provider), other_instance(provider)] == [
        True, True, False, False,
    ]  # fmt: skip
    # Another provider has its own count.
    assert daily("t" + secrets.token_hex(6)) is True
    # The monthly limit counts earlier days of the month too.
    month_provider = "t" + secrets.token_hex(6)
    today = datetime.now(UTC).date()
    with factory() as db:
        db.add(LiveDataUsage(provider=month_provider, day=today.replace(day=1), calls=3))
        db.commit()
    monthly = DatabaseBudget(
        settings.model_copy(update={"live_data_daily_budget": 50, "live_data_monthly_budget": 3}),
        factory,
    )
    assert monthly(month_provider) is False
    # Zero disables live lookups outright.
    assert (
        DatabaseBudget(settings.model_copy(update={"live_data_daily_budget": 0}), factory)(
            "t" + secrets.token_hex(6)
        )
        is False
    )
    assert settings.live_data_daily_budget == 10 and settings.live_data_monthly_budget == 90


def test_api_lookups_stop_at_the_server_wide_budget(make_family, client, settings) -> None:  # type: ignore[no-untyped-def]
    from app.services.live_data import DatabaseBudget

    fam = make_family()
    _id, token, _ = fam.pair_device()
    h = device_headers(token)
    net = Net(avs(flight_row(date_=TODAY)))
    custom = settings.model_copy(
        update={
            "flight_data_provider": "aviationstack",
            "aviationstack_api_key": SecretStr(KEY),
            "live_data_daily_budget": 2,
            "live_data_monthly_budget": 1000,
        }
    )
    # Isolate this test's count from the shared schema by using a provider-scoped budget wrapper.
    inner = DatabaseBudget(custom, client.app.state.session_factory)
    tag = "t" + __import__("secrets").token_hex(6)
    client.app.state.live_data = LiveData(
        custom, client=net.client(), budget=lambda provider: inner(tag)
    )
    states = [
        client.get(
            "/api/v1/journeys/live/flight",
            params={"flight": f"AI{100 + n}", "day": TODAY},
            headers=h,
        ).json()["state"]
        for n in range(4)
    ]
    assert set(states[:2]) <= {"ok", "not_found"} and states[2:] == ["rate_limited", "rate_limited"]
    assert len(net.requests) == 2
