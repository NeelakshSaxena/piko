"""Authentication: turn a bearer token into a verified principal, or fail closed.

User tokens (RS256 JWT) and device tokens (opaque `pkd_...`) are distinct credential types; a
principal of the wrong type is rejected by the endpoint dependency, never silently accepted.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import TokenService, is_device_token, sha256_hex
from app.db.models import Device, DeviceCredential, Family, RefreshSession, User


@dataclass(frozen=True)
class UserPrincipal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    family_hint: uuid.UUID | None  # advisory; roles and membership are always re-read from the DB


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: uuid.UUID
    family_id: uuid.UUID  # from server-side enrollment, never from the request
    owner_member_id: uuid.UUID


Principal = UserPrincipal | DevicePrincipal


def authenticate(db: Session, tokens: TokenService, token: str, now: datetime) -> Principal:
    if is_device_token(token):
        return _authenticate_device(db, token)
    return _authenticate_user(db, tokens, token, now)


def _authenticate_user(
    db: Session, tokens: TokenService, token: str, now: datetime
) -> UserPrincipal:
    claims = tokens.verify(token, "access")
    if claims is None:
        raise ApiError("AUTH_INVALID")
    # Revocation and account status are checked on every request: revocation is immediate.
    row = db.execute(
        select(RefreshSession.id)
        .join(User, User.id == RefreshSession.user_id)
        .where(
            RefreshSession.id == claims.session_id,
            RefreshSession.user_id == claims.user_id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
            User.status == "active",
        )
    ).first()
    if row is None:
        raise ApiError("AUTH_INVALID")
    return UserPrincipal(claims.user_id, claims.session_id, claims.family_hint)


def _authenticate_device(db: Session, token: str) -> DevicePrincipal:
    row = db.execute(
        select(Device.id, Device.family_id, Device.owner_member_id)
        .join(DeviceCredential, DeviceCredential.device_id == Device.id)
        .join(Family, Family.id == Device.family_id)
        .where(
            DeviceCredential.credential_hash == sha256_hex(token),
            DeviceCredential.status == "active",
            Device.status != "revoked",
            Family.status == "active",
        )
    ).first()
    if row is None:
        raise ApiError("AUTH_INVALID")
    return DevicePrincipal(row.id, row.family_id, row.owner_member_id)
