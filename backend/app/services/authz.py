"""Central authorization. Every family-scoped read or write resolves access through here.

Unauthorized and nonexistent resources are indistinguishable (NOT_FOUND_OR_NOT_VISIBLE) so IDs
cannot be enumerated. A caller who is a member of the family but lacks the role gets FORBIDDEN.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import Device, Family, FamilyMembership, User
from app.services.principals import DevicePrincipal, Principal, UserPrincipal

ADMIN_ROLES = frozenset({"parent", "family_admin"})  # manage: pair, revoke, invite
# A guardian (e.g. an elder sibling) may see the family and its members' locations but cannot
# pair or revoke devices or invite anyone (ADR-017).
VIEW_ROLES = ADMIN_ROLES | {"guardian"}
ALL_ROLES = VIEW_ROLES | {"child"}


def require_family_role(
    db: Session, user_id: uuid.UUID, family_id: uuid.UUID, roles: frozenset[str]
) -> FamilyMembership:
    membership = db.scalar(
        select(FamilyMembership)
        .join(Family, Family.id == FamilyMembership.family_id)
        .where(
            FamilyMembership.family_id == family_id,
            FamilyMembership.user_id == user_id,
            Family.status == "active",
        )
    )
    if membership is None or membership.status == "pending":
        raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
    if membership.status == "revoked":
        raise ApiError("FORBIDDEN")
    if membership.role not in roles:
        raise ApiError("FORBIDDEN")
    return membership


def issuer_is_authorised(db: Session, family_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether a pairing/invitation code's creator may still issue it: active family, active user,
    active parent/family_admin membership. Codes die with their issuer's authority."""
    return (
        db.scalar(
            select(FamilyMembership.id)
            .join(Family, Family.id == FamilyMembership.family_id)
            .join(User, User.id == FamilyMembership.user_id)
            .where(
                FamilyMembership.family_id == family_id,
                FamilyMembership.user_id == user_id,
                FamilyMembership.status == "active",
                FamilyMembership.role.in_(ADMIN_ROLES),
                Family.status == "active",
                User.status == "active",
            )
        )
        is not None
    )


def primary_family_id(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(FamilyMembership.family_id)
        .join(Family, Family.id == FamilyMembership.family_id)
        .where(
            FamilyMembership.user_id == user_id,
            FamilyMembership.status == "active",
            FamilyMembership.role.in_(ADMIN_ROLES),
            Family.status == "active",
        )
        .order_by(FamilyMembership.joined_at, FamilyMembership.id)
        .limit(1)
    )


def visible_device(db: Session, principal: Principal, device_id: uuid.UUID) -> Device:
    """Device the principal may see: a family parent/admin/guardian sees all family devices; a
    child sees only the device it owns; a device sees only itself."""
    not_visible = ApiError("NOT_FOUND_OR_NOT_VISIBLE")
    if isinstance(principal, DevicePrincipal):
        if device_id != principal.device_id:
            raise not_visible
        device = db.get(Device, device_id)
        if device is None:
            raise not_visible
        return device
    device = db.get(Device, device_id)
    if device is None:
        raise not_visible
    membership = _active_membership(db, principal, device.family_id)
    if membership is None:
        raise not_visible
    if membership.role in VIEW_ROLES or device.owner_member_id == membership.id:
        return device
    raise not_visible


def admin_device(db: Session, principal: UserPrincipal, device_id: uuid.UUID) -> Device:
    """Device in a family where the caller is parent/family_admin (for mutations)."""
    device = db.get(Device, device_id)
    if device is None:
        raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
    require_family_role(db, principal.user_id, device.family_id, ADMIN_ROLES)
    return device


def viewable_member(
    db: Session, principal: UserPrincipal, member_id: uuid.UUID
) -> FamilyMembership:
    """A member of a family in which the caller is parent/family_admin/guardian (read access)."""
    member = db.get(FamilyMembership, member_id)
    if member is None:
        raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
    require_family_role(db, principal.user_id, member.family_id, VIEW_ROLES)
    if member.status != "active":
        raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
    return member


def _active_membership(
    db: Session, principal: UserPrincipal, family_id: uuid.UUID
) -> FamilyMembership | None:
    return db.scalar(
        select(FamilyMembership)
        .join(Family, Family.id == FamilyMembership.family_id)
        .where(
            FamilyMembership.family_id == family_id,
            FamilyMembership.user_id == principal.user_id,
            FamilyMembership.status == "active",
            Family.status == "active",
        )
    )
