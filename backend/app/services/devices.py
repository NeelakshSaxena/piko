"""Device pairing, status, and revocation."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import (
    format_pairing_code,
    keyed_digest,
    new_device_token,
    new_pairing_code,
    normalize_pairing_code,
    sha256_hex,
)
from app.db.models import (
    Device,
    DeviceCredential,
    DeviceLatestState,
    Family,
    FamilyMembership,
    PairingInvitation,
    User,
)
from app.domain.freshness import DeviceStatus, device_status
from app.services import audit
from app.services.authz import (
    ADMIN_ROLES,
    admin_device,
    issuer_is_authorised,
    primary_family_id,
    require_family_role,
    visible_device,
)
from app.services.principals import Principal, UserPrincipal

PAIRING_LABEL = "pairing-code"


@dataclass(frozen=True)
class PairingCode:
    code: str  # formatted; returned once and never stored
    expires_at: datetime


@dataclass(frozen=True)
class PairResult:
    device_id: uuid.UUID
    credential: str  # returned once; only its SHA-256 is stored
    family_id: uuid.UUID


@dataclass(frozen=True)
class PairRequest:
    code: str
    device_name: str
    device_model: str | None
    android_version: str | None
    app_version: str | None


@dataclass(frozen=True)
class DeviceView:
    id: uuid.UUID
    family_id: uuid.UUID
    name: str
    owner_member_id: uuid.UUID
    device_model: str | None
    android_version: str | None
    app_version: str | None
    paired_at: datetime
    last_activity: datetime | None
    connectivity_status: DeviceStatus
    battery_percent: int | None
    battery_updated_at: datetime | None
    battery_is_charging: bool | None
    network_type: str | None
    network_updated_at: datetime | None
    status: str


class DeviceService:
    def __init__(self, settings: Settings, hmac_key: bytes) -> None:
        self._settings = settings
        self._hmac_key = hmac_key

    def _code_hash(self, canonical_code: str) -> str:
        return keyed_digest(self._hmac_key, PAIRING_LABEL, canonical_code)

    def create_pairing_code(self, db: Session, principal: UserPrincipal) -> PairingCode:
        family_id = principal.family_hint or primary_family_id(db, principal.user_id)
        if family_id is None:
            raise ApiError("FORBIDDEN")
        require_family_role(db, principal.user_id, family_id, ADMIN_ROLES)
        now = datetime.now(UTC)
        # One live code per user per family: supersede any earlier pending code.
        db.execute(
            update(PairingInvitation)
            .where(
                PairingInvitation.family_id == family_id,
                PairingInvitation.created_by_user_id == principal.user_id,
                PairingInvitation.status == "pending",
            )
            .values(status="revoked")
        )
        expires_at = now + timedelta(seconds=self._settings.pairing_code_ttl_seconds)
        for _ in range(5):
            code = new_pairing_code()
            invitation = PairingInvitation(
                family_id=family_id,
                created_by_user_id=principal.user_id,
                pairing_code_hash=self._code_hash(code),
                expires_at=expires_at,
            )
            try:
                with db.begin_nested():
                    db.add(invitation)
            except IntegrityError:  # astronomically unlikely hash collision: draw again
                continue
            db.commit()
            return PairingCode(format_pairing_code(code), expires_at)
        raise ApiError("INTERNAL_ERROR")

    def pair(self, db: Session, req: PairRequest, ip: str) -> PairResult:
        now = datetime.now(UTC)
        invitation = self._lock_invitation(db, req.code)
        failure = self._pairing_failure(invitation, now)
        if failure is not None:
            audit.record(
                db, action="device_paired", resource_type="device", outcome="failure",
                family_id=invitation.family_id if invitation else None,
                reason=failure, meta={"ip": ip},
            )  # fmt: skip
            if invitation is not None and failure == "expired":
                invitation.status = "expired"
            db.commit()
            # A used code is reported distinctly (contract: 409); all else looks identical.
            if failure == "used":
                raise ApiError("CONFLICT", "Pairing code already used.")
            raise ApiError("AUTH_INVALID", "Invalid or expired pairing code.")
        assert invitation is not None
        creator = db.get_one(User, invitation.created_by_user_id)
        if not issuer_is_authorised(db, invitation.family_id, invitation.created_by_user_id):
            invitation.status = "revoked"
            audit.record(
                db, action="device_paired", resource_type="device", outcome="failure",
                family_id=invitation.family_id, reason="issuer_not_authorised", meta={"ip": ip},
            )  # fmt: skip
            db.commit()
            raise ApiError("AUTH_INVALID", "Invalid or expired pairing code.")

        child = User(
            email=f"device-{uuid.uuid4()}@piko.invalid",
            password_hash="!",  # child identities can never log in with a password
            full_name=req.device_name,
        )
        db.add(child)
        db.flush()
        membership = FamilyMembership(
            family_id=invitation.family_id,
            user_id=child.id,
            role="child",
            invited_by_user_id=creator.id,
            invited_at=invitation.created_at,
        )
        db.add(membership)
        db.flush()
        device = Device(
            family_id=invitation.family_id,
            owner_member_id=membership.id,
            name=req.device_name,
            device_model=req.device_model,
            android_version=req.android_version,
            app_version=req.app_version,
        )
        db.add(device)
        db.flush()
        credential = new_device_token()
        db.add(
            DeviceCredential(
                device_id=device.id,
                family_id=invitation.family_id,
                credential_hash=sha256_hex(credential),
            )
        )
        invitation.status = "used"
        invitation.used_at = now
        invitation.used_by_member_id = membership.id
        audit.record(
            db, action="device_paired", resource_type="device", family_id=invitation.family_id,
            actor_user_id=creator.id, resource_id=device.id, meta={"ip": ip},
        )  # fmt: skip
        db.commit()
        return PairResult(device.id, credential, invitation.family_id)

    def _lock_invitation(self, db: Session, raw_code: str) -> PairingInvitation | None:
        canonical = normalize_pairing_code(raw_code)
        if canonical is None:
            return None
        return db.scalar(
            select(PairingInvitation)
            .join(Family, Family.id == PairingInvitation.family_id)
            .where(PairingInvitation.pairing_code_hash == self._code_hash(canonical))
            .with_for_update(of=PairingInvitation)
        )

    @staticmethod
    def _pairing_failure(invitation: PairingInvitation | None, now: datetime) -> str | None:
        if invitation is None:
            return "invalid_code"
        if invitation.status == "used":
            return "used"
        if invitation.status != "pending":
            return "invalid_code"
        if invitation.expires_at <= now:
            return "expired"
        return None

    def view(self, db: Session, principal: Principal, device_id: uuid.UUID) -> DeviceView:
        device = visible_device(db, principal, device_id)
        state = db.get(DeviceLatestState, device.id)
        return DeviceView(
            id=device.id,
            family_id=device.family_id,
            name=device.name,
            owner_member_id=device.owner_member_id,
            device_model=device.device_model,
            android_version=device.android_version,
            app_version=device.app_version,
            paired_at=device.paired_at,
            last_activity=device.last_activity_at,
            connectivity_status=device_status(device.last_activity_at, datetime.now(UTC)),
            battery_percent=state.battery_percent if state else None,
            battery_updated_at=state.battery_updated_at if state else None,
            battery_is_charging=state.battery_is_charging if state else None,
            network_type=state.connectivity_network_type if state else None,
            network_updated_at=state.connectivity_updated_at if state else None,
            status=device.status,
        )

    def revoke(self, db: Session, principal: UserPrincipal, device_id: uuid.UUID) -> None:
        device = admin_device(db, principal, device_id)
        now = datetime.now(UTC)
        if device.status != "revoked":
            device.status = "revoked"
            device.revoked_at = now
            db.execute(
                update(DeviceCredential)
                .where(DeviceCredential.device_id == device.id)
                .values(status="revoked", revoked_at=now)
            )
            audit.record(
                db, action="device_revoked", resource_type="device", family_id=device.family_id,
                actor_user_id=principal.user_id, resource_id=device.id,
            )  # fmt: skip
        db.commit()
