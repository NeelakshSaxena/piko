"""Request/response DTOs. Requests forbid unknown fields; nothing here is reused by the ORM."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


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
