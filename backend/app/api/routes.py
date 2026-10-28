"""HTTP routes (/api/v1). Thin: parse, rate-limit, call a service, map to a DTO."""

import hmac
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response
from sqlalchemy import text

from app.api import schemas as s
from app.api.deps import (
    AnyPrincipal,
    BearerToken,
    CurrentDevice,
    CurrentUser,
    Db,
    client_ip,
    rate_limit,
)
from app.core.errors import ApiError
from app.core.security import password_is_acceptable_length
from app.db.models import Message, SosIncident
from app.services import families as family_service
from app.services import history, locations
from app.services.auth import AuthService
from app.services.devices import DeviceService, PairRequest
from app.services.live_data import FLIGHT_RE, TRAIN_RE, LiveResult
from app.services.principals import UserPrincipal
from app.services.sos import SosCreate, SosLocation, SosService
from app.services.telemetry import RawEvent, TelemetryService

log = logging.getLogger("piko.api")


def global_rate_limit(request: Request, response: Response) -> None:
    """Contract fallback: 100 requests/minute per client IP, enforced before authentication so
    unauthenticated floods cannot drive database lookups."""
    rate_limit(request, response, "global", client_ip(request), 100)


router = APIRouter(prefix="/api/v1", dependencies=[Depends(global_rate_limit)])


# ---- health (no auth, no secrets) ----
@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Db, response: Response) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness reports degraded, never the cause
        log.error("readiness check failed (%s)", type(exc).__name__)
        response.status_code = 503
        return {
            "status": "degraded",
            "database": "degraded",
            "checks": {"database": {"status": "degraded"}},
        }
    return {"status": "ready", "database": "ok", "checks": {"database": {"status": "ok"}}}


# ---- auth ----
@router.post("/auth/session", response_model=s.SessionResponse)
def create_session(body: s.SessionRequest, request: Request, response: Response, db: Db) -> object:
    ip = client_ip(request)
    rate_limit(request, response, "login", ip, 5)
    if not password_is_acceptable_length(body.password):
        raise ApiError("AUTH_INVALID")
    auth: AuthService = request.app.state.auth
    result = auth.login(
        db, email=body.email, password=body.password, fingerprint=body.device_fingerprint, ip=ip
    )
    return s.SessionResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user_id=result.user_id,
        family_id=result.family_id,
        role=result.role,
        families=[s.FamilyRoleOut(id=f.id, name=f.name, role=f.role) for f in result.families],
    )


@router.post("/auth/session/refresh", response_model=s.RefreshResponse)
def refresh_session(request: Request, response: Response, db: Db, token: BearerToken) -> object:
    rate_limit(request, response, "refresh-ip", client_ip(request), 60)
    claims = request.app.state.tokens.verify(token, "refresh")
    if claims is None:
        raise ApiError("AUTH_INVALID")
    # Before rotating: a 429 after rotation would lose the new token and look like token reuse.
    rate_limit(request, response, "refresh", str(claims.user_id), 10)
    auth: AuthService = request.app.state.auth
    access, new_refresh, expires_in, _ = auth.refresh(db, token)
    return s.RefreshResponse(access_token=access, refresh_token=new_refresh, expires_in=expires_in)


@router.post("/auth/session/revoke", status_code=204)
def revoke_session(request: Request, db: Db, user: CurrentUser) -> Response:
    request.app.state.auth.revoke(db, user)
    return Response(status_code=204)


# ---- families ----
@router.get("/families", response_model=s.FamilyListResponse)
def list_families(db: Db, user: CurrentUser) -> object:
    return s.FamilyListResponse(
        families=[s.FamilySummaryOut(**vars(f)) for f in family_service.list_families(db, user)]
    )


@router.get("/families/{family_id}", response_model=s.FamilyDetailResponse)
def get_family(family_id: uuid.UUID, db: Db, user: CurrentUser) -> object:
    d = family_service.family_detail(db, user, family_id)
    return s.FamilyDetailResponse(
        id=d.id,
        name=d.name,
        created_at=d.created_at,
        my_role=d.my_role,
        members=[s.MemberOut(**vars(m)) for m in d.members],
        devices=[s.FamilyDeviceOut(**vars(x)) for x in d.devices],
    )


@router.post("/families/{family_id}/members", status_code=201, response_model=s.InviteResponse)
def invite_member(
    family_id: uuid.UUID,
    body: s.InviteRequest,
    request: Request,
    response: Response,
    db: Db,
    user: CurrentUser,
) -> object:
    rate_limit(request, response, "invite", str(user.user_id), 10, 3600)
    issued = request.app.state.invitations.invite(db, user, family_id, body.email, body.role)
    return s.InviteResponse(
        invitation_id=issued.invitation_id,
        email=issued.email,
        role=issued.role,
        status="pending",
        invite_code=issued.code,
        expires_at=issued.expires_at,
    )


@router.post("/invitations/accept", status_code=201, response_model=s.AcceptInvitationResponse)
def accept_invitation(
    body: s.AcceptInvitationRequest, request: Request, response: Response, db: Db
) -> object:
    ip = client_ip(request)
    rate_limit(request, response, "accept-invite", ip, 5)
    if not password_is_acceptable_length(body.password):
        raise ApiError("VALIDATION_ERROR", "Password must be at most 72 bytes.")
    joined = request.app.state.invitations.accept(
        db,
        code=body.invite_code,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        ip=ip,
    )
    return s.AcceptInvitationResponse(
        user_id=joined.user_id,
        family_id=joined.family_id,
        membership_id=joined.membership_id,
        role=joined.role,
    )


# ---- devices ----
@router.post("/devices/pairing-code", status_code=201, response_model=s.PairingCodeResponse)
def request_pairing_code(request: Request, response: Response, db: Db, user: CurrentUser) -> object:
    rate_limit(request, response, "pairing-code", str(user.user_id), 1)
    devices: DeviceService = request.app.state.devices
    issued = devices.create_pairing_code(db, user)
    ttl = int((issued.expires_at - datetime.now(UTC)).total_seconds())
    return s.PairingCodeResponse(
        pairing_code=issued.code, expires_at=issued.expires_at, expires_in_seconds=max(ttl, 0)
    )


@router.post("/devices/pair", status_code=201, response_model=s.PairResponse)
def pair_device(body: s.PairRequest, request: Request, response: Response, db: Db) -> object:
    ip = client_ip(request)
    rate_limit(request, response, "pair", ip, 5)
    settings = request.app.state.settings
    paired = request.app.state.devices.pair(
        db,
        PairRequest(
            body.pairing_code,
            body.device_name,
            body.device_model,
            body.android_version,
            body.app_version,
        ),
        ip,
    )
    return s.PairResponse(
        device_id=paired.device_id,
        device_credential=paired.credential,
        api_endpoint=settings.public_base_url.rstrip("/") + "/api/v1",
        polling_interval_seconds=settings.polling_interval_seconds,
        family_id=paired.family_id,
    )


@router.get("/devices/{device_id}", response_model=s.DeviceOut)
def get_device(device_id: uuid.UUID, request: Request, db: Db, principal: AnyPrincipal) -> object:
    return s.DeviceOut(**vars(request.app.state.devices.view(db, principal, device_id)))


@router.delete("/devices/{device_id}", status_code=204)
def revoke_device(device_id: uuid.UUID, request: Request, db: Db, user: CurrentUser) -> Response:
    request.app.state.devices.revoke(db, user, device_id)
    return Response(status_code=204)


# ---- member location ----
@router.get(
    "/members/{member_id}/location",
    response_model=s.LocationResponse,
    response_model_exclude_none=True,
)
def get_member_location(
    member_id: uuid.UUID, request: Request, response: Response, db: Db, user: CurrentUser
) -> object:
    rate_limit(request, response, "location", str(user.user_id), 30)
    loc = locations.member_location(db, user, member_id)
    coordinates = (
        s.CoordinatesOut(latitude=loc.latitude, longitude=loc.longitude)
        if loc.available and loc.latitude is not None and loc.longitude is not None
        else None
    )
    return s.LocationResponse(
        member_id=loc.member_id,
        device_id=loc.device_id,
        available=loc.available,
        freshness=loc.freshness,
        freshness_seconds=loc.freshness_seconds,
        device_status=loc.device_status,
        coordinates=coordinates,
        accuracy_meters=loc.accuracy_meters,
        occurred_at=loc.occurred_at,
        received_at=loc.received_at,
    )


@router.get("/members/{member_id}/history", response_model=s.HistoryResponse)
def get_member_history(
    member_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Db,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    event_type: Literal["location", "battery", "connectivity"] | None = None,
) -> object:
    rate_limit(request, response, "history", str(user.user_id), 10)
    now = datetime.now(UTC)
    for given in (start_time, end_time):
        if given is not None and given.tzinfo is None:
            raise ApiError("VALIDATION_ERROR", "Timestamps must include a timezone offset.")
    end = end_time or now
    start = start_time or end - timedelta(days=30)
    if start > end:
        raise ApiError("VALIDATION_ERROR", "start_time must not be after end_time.")
    page = history.member_history(
        db, user, member_id, start=start, end=end, limit=limit, offset=offset, event_type=event_type
    )
    return s.HistoryResponse(
        member_id=page.member_id,
        device_status=page.device_status,
        history=[
            s.HistoryItemOut(
                event_id=i.event_id,
                occurred_at=i.occurred_at,
                received_at=i.received_at,
                event_type=i.event_type,
                freshness=i.freshness,
                data=i.data,
            )
            for i in page.items
        ],
        total_count=page.total_count,
        has_more=page.has_more,
    )


# ---- telemetry ----
@router.post("/telemetry/batches", status_code=202, response_model=s.BatchResponse)
def ingest_batch(
    body: s.BatchRequest, request: Request, response: Response, db: Db, device: CurrentDevice
) -> object:
    settings = request.app.state.settings
    rate_limit(request, response, "telemetry", str(device.device_id), 10)
    if body.device_id != device.device_id:
        raise ApiError("FORBIDDEN", "Batch device_id does not match the authenticated device.")
    if body.schema_version != 1:
        raise ApiError("VALIDATION_ERROR", "Unsupported schema_version.")
    if len(body.events) > settings.telemetry_max_batch_events:
        raise ApiError("VALIDATION_ERROR", "Batch exceeds the maximum number of events.")
    service: TelemetryService = request.app.state.telemetry
    result = service.ingest(
        db,
        device,
        body.batch_id,
        [
            RawEvent(e.event_id, e.event_type, e.sequence_number, e.occurred_at, dict(e.data))
            for e in body.events
        ],
    )
    return s.BatchResponse(
        batch_id=body.batch_id,
        status="partial" if result.rejected_events else "accepted",
        accepted_event_ids=result.accepted_event_ids,
        duplicate_event_ids=result.duplicate_event_ids,
        rejected_events=[
            s.RejectedEventOut(event_id=r.event_id, error_code=r.error_code, reason=r.reason)
            for r in result.rejected_events
        ],
    )


def _kick_outbox(request: Request, background: BackgroundTasks) -> None:
    """Best-effort immediate delivery after the response. Not the delivery guarantee: the committed
    outbox row is, and the scheduler / CLI / next request will pick it up if this never runs."""
    notifier = request.app.state.notifier
    background.add_task(notifier.drain, request.app.state.session_factory, 10)


# ---- SOS ----
def _incident_out(row: SosIncident, *, for_family: bool) -> s.IncidentOut:
    location = None
    if (
        row.location_latitude is not None
        and row.location_longitude is not None
        and row.location_captured_at is not None
    ):
        location = s.SosLocationOut(
            latitude=float(row.location_latitude),
            longitude=float(row.location_longitude),
            accuracy_meters=(
                None
                if row.location_accuracy_meters is None
                else float(row.location_accuracy_meters)
            ),
            captured_at=row.location_captured_at,
            is_latest_known=row.location_is_latest_known,
        )
    return s.IncidentOut(
        incident_id=row.id,
        device_id=row.device_id,
        family_id=row.family_id,
        status=row.status,
        triggered_at=row.triggered_at,
        received_at=row.received_at,
        message=row.message,
        location=location,
        acknowledged_at=row.acknowledged_at,
        resolved_at=row.resolved_at,
        parent_notes=row.parent_notes if for_family else None,
    )


@router.post("/sos/incidents", response_model=s.IncidentOut)
def create_sos(
    body: s.SosCreateRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Db,
    device: CurrentDevice,
) -> object:
    rate_limit(request, response, "sos-create", str(device.device_id), 10)
    if body.device_id != device.device_id:
        raise ApiError("FORBIDDEN", "A device can only raise an SOS for itself.")
    service: SosService = request.app.state.sos
    location = (
        SosLocation(body.location.latitude, body.location.longitude, body.location.accuracy_meters)
        if body.location
        else None
    )
    incident, created = service.create(
        db, device, SosCreate(body.incident_id, body.triggered_at, body.message, location)
    )
    response.status_code = 201 if created else 200  # 200: a replay of an incident already stored
    if created:
        _kick_outbox(request, background)
    return _incident_out(incident, for_family=False)


@router.get("/sos/incidents", response_model=s.IncidentListResponse)
def list_sos(
    request: Request,
    response: Response,
    db: Db,
    principal: AnyPrincipal,
    status: Literal["open", "acknowledged", "resolved"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> object:
    rate_limit(request, response, "sos-list", _principal_key(principal), 60)
    page = request.app.state.sos.list(db, principal, status=status, limit=limit, offset=offset)
    family_view = isinstance(principal, UserPrincipal)
    return s.IncidentListResponse(
        incidents=[_incident_out(i, for_family=family_view) for i in page.incidents],
        total_count=page.total_count,
        has_more=page.has_more,
    )


@router.get("/sos/incidents/{incident_id}", response_model=s.IncidentOut)
def get_sos(
    incident_id: uuid.UUID, request: Request, response: Response, db: Db, principal: AnyPrincipal
) -> object:
    rate_limit(request, response, "sos-get", _principal_key(principal), 60)
    incident = request.app.state.sos.get(db, principal, incident_id)
    return _incident_out(incident, for_family=isinstance(principal, UserPrincipal))


@router.put("/sos/incidents/{incident_id}", response_model=s.IncidentOut)
def update_sos(
    incident_id: uuid.UUID,
    body: s.SosUpdateRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Db,
    user: CurrentUser,
) -> object:
    rate_limit(request, response, "sos-update", str(user.user_id), 30)
    incident = request.app.state.sos.transition(db, user, incident_id, body.status, body.notes)
    _kick_outbox(request, background)
    return _incident_out(incident, for_family=True)


# ---- messages ----
def _message_out(row: Message) -> s.MessageOut:
    return s.MessageOut(
        message_id=row.id,
        device_id=row.device_id,
        sender=row.sender,
        body=row.body,
        sent_at=row.sent_at,
        received_at=row.received_at,
        status=row.status,
        acknowledged_at=row.acknowledged_at,
    )


def _principal_key(principal: AnyPrincipal) -> str:
    if isinstance(principal, UserPrincipal):
        return str(principal.user_id)
    return str(principal.device_id)


@router.post("/messages", response_model=s.MessageOut)
def send_message(
    body: s.MessageSendRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Db,
    principal: AnyPrincipal,
) -> object:
    rate_limit(request, response, "message-send", _principal_key(principal), 30)
    message, created = request.app.state.messages.send(
        db,
        principal,
        message_id=body.message_id,
        body=body.body,
        sent_at=body.sent_at,
        device_id=body.device_id,
    )
    response.status_code = 201 if created else 200
    if created:
        _kick_outbox(request, background)
    return _message_out(message)


@router.get("/messages", response_model=s.MessageListResponse)
def list_messages(
    request: Request,
    response: Response,
    db: Db,
    principal: AnyPrincipal,
    device_id: uuid.UUID | None = None,
    sender: Literal["device", "parent"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> object:
    rate_limit(request, response, "message-list", _principal_key(principal), 60)
    page = request.app.state.messages.list(
        db, principal, device_id=device_id, sender=sender, limit=limit, offset=offset
    )
    return s.MessageListResponse(
        messages=[_message_out(m) for m in page.messages],
        total_count=page.total_count,
        has_more=page.has_more,
    )


@router.post("/messages/{message_id}/ack", response_model=s.MessageOut)
def acknowledge_message(
    message_id: uuid.UUID, request: Request, response: Response, db: Db, principal: AnyPrincipal
) -> object:
    rate_limit(request, response, "message-ack", _principal_key(principal), 60)
    return _message_out(request.app.state.messages.acknowledge(db, principal, message_id))


# ---- push registration (ADR-023) ----
@router.put("/push/device-token", status_code=204)
def register_device_token(
    body: s.PushTokenRequest, request: Request, response: Response, db: Db, device: CurrentDevice
) -> Response:
    rate_limit(request, response, "push-token", str(device.device_id), 20, 3600)
    request.app.state.push.register_device_token(db, device, body.token)
    return Response(status_code=204)


@router.delete("/push/device-token", status_code=204)
def remove_device_token(request: Request, db: Db, device: CurrentDevice) -> Response:
    request.app.state.push.remove_device_token(db, device)
    return Response(status_code=204)


@router.get("/push/config", response_model=s.PushConfigResponse)
def push_config(request: Request, user: CurrentUser) -> object:
    settings = request.app.state.settings
    enabled = "web_subscription" in request.app.state.notifier.transports and bool(
        settings.vapid_public_key
    )
    return s.PushConfigResponse(
        web_push_enabled=enabled, vapid_public_key=settings.vapid_public_key if enabled else None
    )


@router.put("/push/web-subscription", status_code=204)
def register_web_subscription(
    body: s.WebPushSubscriptionRequest,
    request: Request,
    response: Response,
    db: Db,
    user: CurrentUser,
) -> Response:
    rate_limit(request, response, "push-sub", str(user.user_id), 20, 3600)
    request.app.state.push.register_web_subscription(
        db, user, body.endpoint, body.keys.p256dh, body.keys.auth
    )
    return Response(status_code=204)


@router.post("/push/web-subscription/remove", status_code=204)
def remove_web_subscription(
    body: s.WebPushRemoveRequest, request: Request, response: Response, db: Db, user: CurrentUser
) -> Response:
    rate_limit(request, response, "push-sub", str(user.user_id), 20, 3600)
    request.app.state.push.remove_web_subscription(db, user, body.endpoint)
    return Response(status_code=204)


# ---- outbox operations: for an external scheduler, authenticated by a shared secret ----
def _require_outbox_token(request: Request, presented: str | None) -> None:
    expected: bytes | None = request.app.state.outbox_token
    if expected is None:
        raise ApiError("SERVICE_UNAVAILABLE", "Outbox operations are not enabled.")
    if presented is None or not hmac.compare_digest(presented.encode(), expected):
        raise ApiError("AUTH_INVALID")


@router.post("/internal/outbox/run", response_model=s.OutboxRunResponse)
def run_outbox(
    request: Request,
    response: Response,
    x_piko_outbox_token: Annotated[str | None, Header()] = None,
) -> object:
    _require_outbox_token(request, x_piko_outbox_token)
    rate_limit(request, response, "outbox-run", client_ip(request), 30)
    result = request.app.state.notifier.drain(request.app.state.session_factory)
    return s.OutboxRunResponse(
        accepted=result.accepted, retried=result.retried, dead=result.dead, skipped=result.skipped,
        expired=result.expired, waiting_for_transport=result.waiting_for_transport,
    )  # fmt: skip


@router.get("/internal/outbox/health")
def outbox_health(
    request: Request,
    response: Response,
    db: Db,
    x_piko_outbox_token: Annotated[str | None, Header()] = None,
) -> object:
    _require_outbox_token(request, x_piko_outbox_token)
    rate_limit(request, response, "outbox-health", client_ip(request), 30)
    return request.app.state.notifier.health(db)


@router.post("/internal/retention/run", response_model=s.RetentionRunResponse)
def run_retention(
    request: Request,
    response: Response,
    x_piko_outbox_token: Annotated[str | None, Header()] = None,
) -> object:
    """Deletes data past its retention period, in bounded batches (an external scheduler calls this)."""
    _require_outbox_token(request, x_piko_outbox_token)
    rate_limit(request, response, "retention-run", client_ip(request), 6)
    report = request.app.state.retention.run(
        request.app.state.session_factory, apply=True, max_batches=10
    )
    return s.RetentionRunResponse(deleted=report.counts, more_remaining=report.more_remaining)


# ---- live flight/train status (ADR-027): a read-only lookup for the calling device; stores nothing ----
def _live_out(result: LiveResult) -> s.LiveStatusOut:
    st = result.status
    return s.LiveStatusOut(
        state=result.state.value,
        provider=result.provider,
        checked_at=result.checked_at,
        status=st.status if st else None,
        departure_delay_minutes=st.departure_delay_minutes if st else None,
        arrival_delay_minutes=st.arrival_delay_minutes if st else None,
        running_delay_minutes=st.running_delay_minutes if st else None,
        departure_gate=st.departure_gate if st else None,
        departure_terminal=st.departure_terminal if st else None,
        arrival_gate=st.arrival_gate if st else None,
        arrival_terminal=st.arrival_terminal if st else None,
        provider_updated_at=st.provider_updated_at if st else None,
        notices=list(st.notices) if st else [],
    )


@router.get("/journeys/live/flight", response_model=s.LiveStatusOut)
def live_flight(
    request: Request, response: Response, device: CurrentDevice, flight: str, day: date
) -> object:
    rate_limit(request, response, "live", str(device.device_id), 10)
    code = flight.replace(" ", "").upper()
    if not FLIGHT_RE.fullmatch(code):
        raise ApiError("VALIDATION_ERROR", "flight must look like AI101.")
    # A tiny provider quota must not be spendable on arbitrary dates (the cache key includes the date).
    if abs((day - datetime.now(UTC).date()).days) > 2:
        raise ApiError("VALIDATION_ERROR", "day must be within two days of today.")
    return _live_out(request.app.state.live_data.flight(code, day))


@router.get("/journeys/live/train", response_model=s.LiveStatusOut)
def live_train(request: Request, response: Response, device: CurrentDevice, number: str) -> object:
    rate_limit(request, response, "live", str(device.device_id), 10)
    if not TRAIN_RE.fullmatch(number):
        raise ApiError("VALIDATION_ERROR", "number must be a 5-digit train number.")
    return _live_out(request.app.state.live_data.train(number))


# ---- journeys (ADR-026): device-owned; a user token or another device sees nothing ----
@router.put("/journeys/{journey_id}", response_model=s.JourneyPutResponse)
def put_journey(
    journey_id: uuid.UUID,
    body: s.JourneyPutRequest,
    request: Request,
    response: Response,
    db: Db,
    device: CurrentDevice,
) -> object:
    rate_limit(request, response, "journeys", str(device.device_id), 60)
    journey, applied = request.app.state.journeys.put(db, device, journey_id, body)
    return s.JourneyPutResponse(journey=journey, applied=applied)


@router.get("/journeys", response_model=s.JourneyListResponse)
def list_journeys(request: Request, response: Response, db: Db, device: CurrentDevice) -> object:
    rate_limit(request, response, "journeys", str(device.device_id), 60)
    return s.JourneyListResponse(journeys=request.app.state.journeys.list_all(db, device))


@router.get("/journeys/{journey_id}", response_model=s.JourneyOut)
def get_journey(
    journey_id: uuid.UUID, request: Request, response: Response, db: Db, device: CurrentDevice
) -> object:
    rate_limit(request, response, "journeys", str(device.device_id), 60)
    return request.app.state.journeys.get(db, device, journey_id)


@router.delete("/journeys/{journey_id}", status_code=204)
def delete_journey(
    journey_id: uuid.UUID, request: Request, response: Response, db: Db, device: CurrentDevice
) -> Response:
    rate_limit(request, response, "journeys", str(device.device_id), 60)
    request.app.state.journeys.delete(db, device, journey_id)
    return Response(status_code=204)


@router.post("/journeys/{journey_id}/events", status_code=202, response_model=s.BatchResponse)
def add_journey_events(
    journey_id: uuid.UUID,
    body: s.JourneyEventBatchRequest,
    request: Request,
    response: Response,
    db: Db,
    device: CurrentDevice,
) -> object:
    rate_limit(request, response, "journey-events", str(device.device_id), 30)
    result = request.app.state.journeys.add_events(db, device, journey_id, body.events)
    return s.BatchResponse(
        batch_id=body.batch_id,
        status="partial" if result.rejected else "accepted",
        accepted_event_ids=result.accepted,
        duplicate_event_ids=result.duplicates,
        rejected_events=[
            s.RejectedEventOut(event_id=i, error_code="VALIDATION_ERROR", reason=reason)
            for i, reason in result.rejected
        ],
    )


@router.get("/journeys/{journey_id}/events", response_model=s.JourneyEventListResponse)
def list_journey_events(
    journey_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Db,
    device: CurrentDevice,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> object:
    rate_limit(request, response, "journeys", str(device.device_id), 60)
    rows, more = request.app.state.journeys.list_events(db, device, journey_id, limit, offset)
    return s.JourneyEventListResponse(
        events=[
            s.JourneyEventOut(
                event_id=r.id,
                event_type=r.event_type,
                occurred_at=r.occurred_at,
                received_at=r.received_at,
                data=r.payload,
            )
            for r in rows
        ],
        has_more=more,
    )
