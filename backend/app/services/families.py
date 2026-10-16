"""Family reads. Parents/admins see everything in their family; children only themselves."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Device, Family, FamilyMembership, User
from app.services.authz import ALL_ROLES, VIEW_ROLES, require_family_role
from app.services.principals import UserPrincipal


@dataclass(frozen=True)
class FamilySummary:
    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    device_count: int
    my_role: str
    status: str


@dataclass(frozen=True)
class MemberView:
    id: uuid.UUID
    email: str | None
    name: str | None
    role: str
    joined_at: datetime
    status: str


@dataclass(frozen=True)
class DeviceSummary:
    id: uuid.UUID
    name: str
    owner_member_id: uuid.UUID
    paired_at: datetime
    last_seen: datetime | None
    status: str


@dataclass(frozen=True)
class FamilyDetail:
    id: uuid.UUID
    name: str
    created_at: datetime
    my_role: str
    members: list[MemberView]
    devices: list[DeviceSummary]


def list_families(db: Session, principal: UserPrincipal) -> list[FamilySummary]:
    members = (
        select(func.count())
        .select_from(FamilyMembership)
        .where(FamilyMembership.family_id == Family.id, FamilyMembership.status == "active")
        .correlate(Family)
        .scalar_subquery()
        .label("member_count")
    )
    devices = (
        select(func.count())
        .select_from(Device)
        .where(Device.family_id == Family.id, Device.status != "revoked")
        .correlate(Family)
        .scalar_subquery()
        .label("device_count")
    )
    rows = db.execute(
        select(Family, FamilyMembership.role.label("role"), members, devices)
        .join(FamilyMembership, FamilyMembership.family_id == Family.id)
        .where(
            FamilyMembership.user_id == principal.user_id,
            FamilyMembership.status == "active",
            FamilyMembership.role.in_(VIEW_ROLES),  # children see no families
            Family.status == "active",
        )
        .order_by(Family.created_at, Family.id)
    ).all()
    return [
        FamilySummary(
            r.Family.id,
            r.Family.name,
            r.Family.created_at,
            r.member_count,
            r.device_count,
            r.role,
            r.Family.status,
        )
        for r in rows
    ]


def family_detail(db: Session, principal: UserPrincipal, family_id: uuid.UUID) -> FamilyDetail:
    me = require_family_role(db, principal.user_id, family_id, ALL_ROLES)
    family = db.get_one(Family, family_id)
    sees_all = me.role in VIEW_ROLES

    member_q = (
        select(FamilyMembership, User)
        .join(User, User.id == FamilyMembership.user_id)
        .where(FamilyMembership.family_id == family_id)
        .order_by(FamilyMembership.joined_at, FamilyMembership.id)
    )
    device_q = select(Device).where(Device.family_id == family_id).order_by(Device.paired_at)
    if not sees_all:
        member_q = member_q.where(FamilyMembership.id == me.id)
        device_q = device_q.where(Device.owner_member_id == me.id)

    members = [
        MemberView(
            m.id,
            None if m.role == "child" else u.email,
            u.full_name,
            m.role,
            m.joined_at,
            m.status,
        )
        for m, u in db.execute(member_q).all()
    ]
    devices = [
        DeviceSummary(d.id, d.name, d.owner_member_id, d.paired_at, d.last_activity_at, d.status)
        for d in db.scalars(device_q)
    ]
    return FamilyDetail(family.id, family.name, family.created_at, me.role, members, devices)
