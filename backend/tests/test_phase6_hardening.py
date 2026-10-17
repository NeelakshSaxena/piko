"""Phase 6 hardening and Phase 2-3 backlog closure: caching headers, log hygiene, lockout, audit volume,
and the SOS location rules (fresh / latest known / stale) against real PostgreSQL."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.db.models import AuditEvent, SosIncident
from app.db.session import make_engine

from .conftest import PASSWORD, Family, device_headers
from .helpers import batch, iso, location_event

SOS = "/api/v1/sos/incidents"


def reset(fam: Family) -> None:
    fam.client.app.state.limiter = RateLimiter()  # type: ignore[attr-defined]


def raise_sos(fam: Family, device_id: str, token: str, **extra):  # type: ignore[no-untyped-def]
    reset(fam)
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": iso(-timedelta(seconds=3)),
    }
    body.update(extra)
    return fam.client.post(SOS, json=body, headers=device_headers(token))


def upload(fam: Family, device_id: str, token: str, events):  # type: ignore[no-untyped-def]
    reset(fam)
    r = fam.client.post(
        "/api/v1/telemetry/batches", json=batch(device_id, events), headers=device_headers(token)
    )
    assert r.status_code == 202, r.text


# ---- L-3: no-store ------------------------------------------------------------------------
def test_every_api_response_forbids_caching(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    reset(fam)
    responses = [
        fam.client.get("/api/v1/health/live"),
        fam.client.get("/api/v1/families", headers=fam.headers),
        fam.client.get("/api/v1/families"),  # 401
        fam.client.get(f"/api/v1/devices/{uuid.uuid4()}", headers=fam.headers),  # 404
        fam.client.post("/api/v1/auth/session", json={"email": fam.email, "password": PASSWORD}),
        raise_sos(fam, device_id, token),
    ]
    for r in responses:
        assert r.headers["cache-control"] == "no-store", r.request.url
        assert r.headers["pragma"] == "no-cache"


# ---- L-1: bind values never appear in database errors ------------------------------------
def test_database_errors_do_not_carry_bound_values(settings) -> None:  # type: ignore[no-untyped-def]
    engine = make_engine(settings)
    secret = "SECRET-COORDINATE-40.7128"
    with pytest.raises(DBAPIError) as caught, engine.connect() as conn:
        conn.execute(text("SELECT CAST(:v AS integer)"), {"v": secret})
    engine.dispose()
    # SQLAlchemy's own "[parameters: ...]" dump is gone. (PostgreSQL itself may quote an offending
    # value in its message; the app logs only the exception type for database errors, and every value
    # is validated before it reaches a statement.)
    text_of_error = str(caught.value)
    assert "[parameters:" not in text_of_error
    assert "SQL parameters hidden" in text_of_error


# ---- L-2: lockout counts failures since the last success; parallel guesses cannot overshoot ----
def login(fam: Family, password: str):  # type: ignore[no-untyped-def]
    reset(fam)
    return fam.client.post("/api/v1/auth/session", json={"email": fam.email, "password": password})


def test_a_successful_login_resets_the_failure_count(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    for _ in range(9):
        assert login(fam, "wrong-password-xx").status_code == 401
    assert login(fam, PASSWORD).status_code == 200  # the legitimate owner gets in
    for _ in range(9):
        assert login(fam, "wrong-password-xx").status_code == 401  # nine more are still allowed
    assert login(fam, PASSWORD).status_code == 200


def test_parallel_wrong_guesses_cannot_exceed_the_limit(make_family, app) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    limit = app.state.settings.login_failure_limit

    def guess(_: int) -> str:
        with app.state.session_factory() as session:
            try:
                app.state.auth.login(
                    session,
                    email=fam.email,
                    password="wrong-password-xx",
                    fingerprint=None,
                    ip="10.0.0.1",
                )
            except ApiError as exc:
                return exc.code
        return "OK"

    with ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(guess, range(limit + 10)))
    assert codes.count("AUTH_INVALID") == limit  # exactly the allowed number of recorded failures
    assert codes.count("RATE_LIMIT") == 10
    assert "OK" not in codes


# ---- audit volume: polling the list does not flood the trail --------------------------------
def test_listing_incidents_is_audited_once_a_minute_but_a_detail_read_always(  # type: ignore[no-untyped-def]
    make_family, db: Session
) -> None:
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    incident_id = raise_sos(fam, device_id, token).json()["incident_id"]
    for _ in range(4):
        reset(fam)
        assert fam.client.get(SOS, headers=fam.headers).status_code == 200
    for _ in range(2):
        reset(fam)
        assert fam.client.get(f"{SOS}/{incident_id}", headers=fam.headers).status_code == 200
    db.expire_all()
    rows = list(
        db.scalars(
            select(AuditEvent).where(
                AuditEvent.family_id == fam.family_id,
                AuditEvent.action == "location_accessed",
                AuditEvent.resource_type == "incident",
            )
        )
    )
    assert sum(1 for r in rows if r.resource_id is None) == 1
    assert sum(1 for r in rows if r.resource_id == uuid.UUID(incident_id)) == 2


# ---- SOS location rules: fresh vs latest known vs stale ---------------------------------------
def test_latest_known_position_is_attached_and_flagged_with_its_own_time(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    upload(fam, device_id, token, [location_event(ago=timedelta(hours=23), lat=11.0, lon=22.0)])
    out = raise_sos(fam, device_id, token).json()
    loc = out["location"]
    assert loc["is_latest_known"] is True and loc["latitude"] == 11.0
    assert loc["captured_at"] < out["triggered_at"]  # measured long before the SOS, and says so


def test_a_position_older_than_24_hours_is_not_attached(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    upload(fam, device_id, token, [location_event(ago=timedelta(hours=25))])
    assert raise_sos(fam, device_id, token).json()["location"] is None


def test_no_known_position_means_no_location_not_zero_zero(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    assert raise_sos(fam, device_id, token).json()["location"] is None


def test_an_old_offline_fix_cannot_replace_a_newer_position_in_the_sos(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    upload(fam, device_id, token, [location_event(ago=timedelta(minutes=2), lat=50.0, lon=8.0)])
    upload(fam, device_id, token, [location_event(ago=timedelta(hours=3), lat=1.0, lon=1.0)])
    loc = raise_sos(fam, device_id, token).json()["location"]
    assert loc["latitude"] == 50.0 and loc["is_latest_known"] is True


def test_a_position_sent_with_the_sos_is_stamped_with_the_sos_time_and_not_flagged(  # type: ignore[no-untyped-def]
    make_family,
) -> None:
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    upload(fam, device_id, token, [location_event(ago=timedelta(minutes=10), lat=5.0, lon=5.0)])
    out = raise_sos(
        fam, device_id, token, location={"latitude": 6.5, "longitude": 7.5, "accuracy_meters": 9}
    ).json()
    assert out["location"]["latitude"] == 6.5 and out["location"]["is_latest_known"] is False
    assert out["location"]["captured_at"] == out["triggered_at"]


# ---- unpaired or forged device credentials ------------------------------------------------
@pytest.mark.parametrize("token", ["pkd_" + "A" * 43, "not-a-token", ""])
def test_unpaired_devices_cannot_raise_an_sos_or_message(make_family, token: str) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    reset(fam)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": str(uuid.uuid4()),
        "triggered_at": "2026-10-17T00:00:00Z",
    }
    assert fam.client.post(SOS, json=body, headers=headers).status_code == 401
    msg = {"message_id": str(uuid.uuid4()), "body": "x", "sent_at": "2026-10-17T00:00:00Z"}
    reset(fam)
    assert fam.client.post("/api/v1/messages", json=msg, headers=headers).status_code == 401


def test_no_incident_rows_are_created_by_refused_requests(make_family, db: Session) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    device_id, token, _ = fam.pair_device()
    reset(fam)
    body = {
        "incident_id": str(uuid.uuid4()),
        "device_id": device_id,
        "triggered_at": "2026-10-17T00:00:00Z",
    }
    assert (
        fam.client.post(SOS, json=body, headers=fam.headers).status_code == 401
    )  # a parent session
    reset(fam)
    other = dict(body, device_id=str(uuid.uuid4()))  # a device may only raise an SOS for itself
    assert fam.client.post(SOS, json=other, headers=device_headers(token)).status_code == 403
    db.expire_all()
    count = db.scalar(
        select(func.count()).select_from(SosIncident).where(SosIncident.family_id == fam.family_id)
    )
    assert count == 0


# ---- F-10: framing, sniffing and referrer headers ---------------------------------------------------
def test_api_responses_forbid_framing_sniffing_and_referrers(make_family) -> None:  # type: ignore[no-untyped-def]
    fam: Family = make_family()
    reset(fam)
    for r in (
        fam.client.get("/api/v1/health/live"),
        fam.client.get("/api/v1/families", headers=fam.headers),
        fam.client.get("/api/v1/families"),  # 401
    ):
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    docs = fam.client.get("/docs")  # development docs page: framing/sniffing headers only
    assert docs.headers["x-frame-options"] == "DENY" and "no-store" not in docs.headers.get(
        "cache-control", ""
    )
