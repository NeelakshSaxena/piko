"""Request/response DTOs. Requests forbid unknown fields; nothing here is reused by the ORM."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue

_ALLOWED_WHITESPACE = (chr(10), chr(13), chr(9))


def _plain_text(value: str) -> str:
    """Free text may hold newlines and tabs but no other control character. A NUL byte cannot be
    stored by PostgreSQL and used to surface as an HTTP 500 that a phone would retry forever (F-02)."""
    if any((ord(c) < 32 and c not in _ALLOWED_WHITESPACE) or ord(c) == 127 for c in value):
        raise ValueError("control characters are not allowed")
    return value


PlainText = Annotated[str, AfterValidator(_plain_text)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- auth ---
class SessionRequest(Request):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    device_fingerprint: str | None = Field(default=None, max_length=255)


class FamilyRoleOut(Response):
    id: uuid.UUID
    name: str
    role: str


class SessionResponse(Response):
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: uuid.UUID
    family_id: uuid.UUID
    role: str
    families: list[FamilyRoleOut]


class RefreshResponse(Response):
    access_token: str
    refresh_token: str  # rotated: the previous refresh token is now void
    expires_in: int


# --- families ---
class FamilySummaryOut(Response):
    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    device_count: int
    my_role: str
    status: str


class FamilyListResponse(Response):
    families: list[FamilySummaryOut]


class MemberOut(Response):
    id: uuid.UUID
    email: str | None
    name: str | None
    role: str
    joined_at: datetime
    status: str


class FamilyDeviceOut(Response):
    id: uuid.UUID
    name: str
    device_type: Literal["android"] = "android"
    owner_member_id: uuid.UUID
    paired_at: datetime
    last_seen: datetime | None
    status: str


class FamilyDetailResponse(Response):
    id: uuid.UUID
    name: str
    created_at: datetime
    my_role: str
    members: list[MemberOut]
    devices: list[FamilyDeviceOut]


# --- devices ---
class PairingCodeResponse(Response):
    pairing_code: str
    expires_at: datetime
    expires_in_seconds: int


class PairRequest(Request):
    pairing_code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(min_length=1, max_length=100)
    device_model: str | None = Field(default=None, max_length=100)
    android_version: str | None = Field(default=None, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)


class InviteRequest(Request):
    email: str = Field(min_length=3, max_length=255)
    role: Literal["parent", "family_admin", "guardian"]


class InviteResponse(Response):
    invitation_id: uuid.UUID
    email: str
    role: str
    status: Literal["pending"]
    invite_code: str  # shown once; share it with the invitee yourself
    expires_at: datetime


class AcceptInvitationRequest(Request):
    invite_code: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class AcceptInvitationResponse(Response):
    user_id: uuid.UUID
    family_id: uuid.UUID
    membership_id: uuid.UUID
    role: str


class PairResponse(Response):
    device_id: uuid.UUID
    device_credential: str
    api_endpoint: str
    polling_interval_seconds: int
    family_id: uuid.UUID


class DeviceOut(Response):
    id: uuid.UUID
    family_id: uuid.UUID
    name: str
    owner_member_id: uuid.UUID
    device_model: str | None
    android_version: str | None
    app_version: str | None
    paired_at: datetime
    last_activity: datetime | None
    connectivity_status: Literal["online", "offline", "unknown"]
    battery_percent: int | None
    battery_updated_at: datetime | None
    battery_is_charging: bool | None
    network_type: str | None
    network_updated_at: datetime | None
    status: str


# --- telemetry ---
class EventIn(Request):
    event_id: uuid.UUID
    event_type: str = Field(max_length=32)
    sequence_number: int | None = None
    occurred_at: str = Field(max_length=64)
    # Deliberately loose here: semantic validation is per event so one bad event cannot
    # poison a whole batch of otherwise valid offline history.
    data: dict[str, JsonValue]


class BatchRequest(Request):
    batch_id: uuid.UUID
    schema_version: int
    device_id: uuid.UUID
    events: list[EventIn] = Field(min_length=1)


class RejectedEventOut(Response):
    event_id: uuid.UUID
    error_code: Literal["VALIDATION_ERROR", "DUPLICATE"]
    reason: str


class BatchResponse(Response):
    batch_id: uuid.UUID
    status: Literal["accepted", "partial"]
    accepted_event_ids: list[uuid.UUID]
    duplicate_event_ids: list[uuid.UUID]
    rejected_events: list[RejectedEventOut]


# --- member location ---
class HistoryItemOut(Response):
    event_id: uuid.UUID
    occurred_at: datetime
    received_at: datetime
    event_type: Literal["location", "battery", "connectivity"]
    freshness: Literal["fresh", "stale", "unknown"]
    data: dict[str, JsonValue]


class HistoryResponse(Response):
    member_id: uuid.UUID
    device_status: Literal["online", "offline", "unknown"]
    history: list[HistoryItemOut]
    total_count: int
    has_more: bool


class CoordinatesOut(Response):
    latitude: float
    longitude: float


class LocationResponse(Response):
    member_id: uuid.UUID
    device_id: uuid.UUID | None
    available: bool
    freshness: Literal["fresh", "stale", "unknown"]
    freshness_seconds: int | None
    device_status: Literal["online", "offline", "unknown"]
    coordinates: CoordinatesOut | None = None
    accuracy_meters: float | None = None
    occurred_at: datetime | None = None
    received_at: datetime | None = None


# --- SOS ---
class SosLocationIn(Request):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)


class SosCreateRequest(Request):
    incident_id: uuid.UUID  # generated on the device before the first send; makes retries safe
    device_id: uuid.UUID
    triggered_at: str = Field(max_length=64)
    message: PlainText | None = Field(default=None, max_length=280)
    location: SosLocationIn | None = None


class SosLocationOut(Response):
    latitude: float
    longitude: float
    accuracy_meters: float | None
    captured_at: datetime
    is_latest_known: bool  # true: the last known position, not captured at the moment of the SOS


class IncidentOut(Response):
    incident_id: uuid.UUID
    device_id: uuid.UUID
    family_id: uuid.UUID
    status: Literal["open", "acknowledged", "resolved"]
    triggered_at: datetime
    received_at: datetime
    message: str | None
    location: SosLocationOut | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    parent_notes: str | None = None  # only included for family members, never for the device


class IncidentListResponse(Response):
    incidents: list[IncidentOut]
    total_count: int
    has_more: bool


class SosUpdateRequest(Request):
    status: Literal["acknowledged", "resolved"]
    notes: PlainText | None = Field(default=None, max_length=500)


# --- messages ---
class MessageSendRequest(Request):
    message_id: uuid.UUID  # generated by the sender before the first send
    body: PlainText = Field(min_length=1, max_length=500)
    sent_at: str = Field(max_length=64)
    device_id: uuid.UUID | None = None  # parents name the child device; a device may omit it


class MessageOut(Response):
    message_id: uuid.UUID
    device_id: uuid.UUID
    sender: Literal["device", "parent"]
    body: str
    sent_at: datetime
    received_at: datetime
    status: Literal["delivered", "acknowledged"]
    acknowledged_at: datetime | None


class MessageListResponse(Response):
    messages: list[MessageOut]
    total_count: int
    has_more: bool


# --- push registration (ADR-023) ---
class PushTokenRequest(Request):
    token: str = Field(min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9_:\-.]+$")
    platform: Literal["fcm"] = "fcm"


class WebPushKeys(Request):
    p256dh: str = Field(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_\-=]+$")
    auth: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_\-=]+$")


class WebPushSubscriptionRequest(Request):
    endpoint: str = Field(min_length=10, max_length=2048)
    keys: WebPushKeys


class WebPushRemoveRequest(Request):
    endpoint: str = Field(min_length=10, max_length=2048)


class PushConfigResponse(Response):
    web_push_enabled: bool
    vapid_public_key: str | None


class OutboxRunResponse(Response):
    accepted: int
    retried: int
    dead: int
    skipped: int
    expired: int
    waiting_for_transport: int


class RetentionRunResponse(Response):
    deleted: dict[str, int]
    more_remaining: bool


# --- journeys (ADR-026): owned by one device; whole-journey upsert so every write is atomic ---
JourneyMode = Literal["FLIGHT", "TRAIN", "TAXI", "BIKE_TAXI", "METRO", "BUS", "WALKING", "OTHER"]
JourneyEventType = Literal[
    "tracking_started",
    "tracking_paused",
    "tracking_resumed",
    "tracking_stopped",
    "arrival_detected",
    "arrival_confirmed",
    "observation",
    "network_restored",
    "journey_completed",
]
ZoneName = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+\-/]+$")]
ShortText = Annotated[PlainText, Field(min_length=1, max_length=80)]


class JourneyLegIn(Request):
    id: uuid.UUID
    mode: JourneyMode
    service_number: ShortText | None = None
    origin: ShortText
    destination: ShortText
    departure_at: datetime | None = None
    departure_zone: ZoneName | None = None
    arrival_at: datetime | None = None
    arrival_zone: ZoneName | None = None


class JourneyPutRequest(Request):
    title: ShortText
    status: Literal["DRAFT", "PLANNED"]
    created_at: datetime
    updated_at: datetime
    revision: int = Field(
        strict=True, ge=1, le=2**53
    )  # +1 per saved edit on the phone; only a higher one applies
    legs: list[JourneyLegIn] = Field(max_length=20)


class JourneyLegOut(Response):
    id: uuid.UUID
    sequence: int
    mode: JourneyMode
    service_number: str | None
    origin: str
    destination: str
    departure_at: datetime | None
    departure_zone: str | None
    arrival_at: datetime | None
    arrival_zone: str | None


class JourneyOut(Response):
    id: uuid.UUID
    title: str
    status: Literal["DRAFT", "PLANNED"]
    created_at: datetime
    updated_at: datetime
    revision: int
    legs: list[JourneyLegOut]


class LiveStatusOut(Response):
    """What one provider said, right now (ADR-027). Never merged into a journey by the server.

    `state` is always present; the fields below are set only when it is "ok". Nothing here is a schedule:
    delays are minutes the provider reported, and a missing value means the provider did not say."""

    state: Literal[
        "ok",
        "disabled",
        "not_configured",
        "not_found",
        "auth_failed",
        "rate_limited",
        "unavailable",
        "unusable",
    ]
    provider: Literal["aviationstack", "railradar"] | None
    checked_at: datetime
    status: str | None = None
    departure_delay_minutes: int | None = None
    arrival_delay_minutes: int | None = None
    running_delay_minutes: int | None = None
    departure_gate: str | None = None
    departure_terminal: str | None = None
    arrival_gate: str | None = None
    arrival_terminal: str | None = None
    provider_updated_at: datetime | None = None
    notices: list[str] = []


class JourneyPutResponse(Response):
    journey: JourneyOut
    # False: the server already held a newer (or identical) version and kept it. Not an error.
    applied: bool


class JourneyListResponse(Response):
    journeys: list[JourneyOut]


EventValue = str | int | Annotated[float, Field(allow_inf_nan=False)] | bool | None


class JourneyEventIn(Request):
    event_id: uuid.UUID
    event_type: JourneyEventType
    occurred_at: str = Field(max_length=64)
    data: dict[Annotated[str, Field(max_length=40)], EventValue] = Field(
        default_factory=dict, max_length=12
    )


class JourneyEventBatchRequest(Request):
    batch_id: uuid.UUID
    events: list[JourneyEventIn] = Field(min_length=1, max_length=100)


class JourneyEventOut(Response):
    event_id: uuid.UUID
    event_type: JourneyEventType
    occurred_at: datetime
    received_at: datetime
    data: dict[str, EventValue]


class JourneyEventListResponse(Response):
    events: list[JourneyEventOut]
    has_more: bool
