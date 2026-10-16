"""HTTP routes (/api/v1). Thin: parse, rate-limit, call a service, map to a DTO."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
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
from app.services import families as family_service
from app.services import history, locations
from app.services.auth import AuthService
from app.services.devices import DeviceService, PairRequest
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
