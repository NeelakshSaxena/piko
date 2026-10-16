"""ORM models. Status/role vocabularies are VARCHAR + CHECK (cheap to evolve, unlike PG enums).

Deviations from docs/DATA_MODEL.md are recorded in docs/DECISIONS.md (ADR-007..ADR-011).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TS = DateTime(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("status", ("active", "suspended", "deleted"))),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))  # bcrypt, or "!" = cannot log in
    full_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(TS)


class Family(Base):
    __tablename__ = "families"
    __table_args__ = (
        CheckConstraint(_in("status", ("active", "archived"))),
        CheckConstraint("retention_days BETWEEN 1 AND 365"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    retention_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class FamilyMembership(Base):
    __tablename__ = "family_memberships"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id"),
        CheckConstraint(_in("role", ("parent", "family_admin", "guardian", "child"))),
        CheckConstraint(_in("status", ("active", "pending", "revoked"))),
        Index("ix_memberships_user_active", "user_id", postgresql_where=text("status = 'active'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    joined_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    invited_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(_in("status", ("active", "inactive", "revoked"))),
        Index("ix_devices_family", "family_id"),
        Index("ix_devices_owner", "owner_member_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    owner_member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family_memberships.id"))
    name: Mapped[str] = mapped_column(String(255))
    device_model: Mapped[str | None] = mapped_column(String(255))
    android_version: Mapped[str | None] = mapped_column(String(255))
    app_version: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    paired_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    last_activity_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class DeviceCredential(Base):
    """Opaque bearer token; only its SHA-256 is stored (ADR-007)."""

    __tablename__ = "device_credentials"
    __table_args__ = (CheckConstraint(_in("status", ("active", "revoked"))),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class PairingInvitation(Base):
    __tablename__ = "pairing_invitations"
    __table_args__ = (
        CheckConstraint(_in("status", ("pending", "used", "expired", "revoked"))),
        Index(
            "ix_pairing_family_creator_pending",
            "family_id",
            "created_by_user_id",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    pairing_code_hash: Mapped[str] = mapped_column(String(64), unique=True)  # keyed HMAC
    used_by_member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family_memberships.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)


class MemberInvitation(Base):
    """Single-use invite code for a new adult member (ADR-017). Only a keyed HMAC is stored."""

    __tablename__ = "member_invitations"
    __table_args__ = (
        CheckConstraint(_in("status", ("pending", "used", "expired", "revoked"))),
        CheckConstraint(_in("role", ("parent", "family_admin", "guardian"))),
        Index(
            "ix_invitations_family_email_pending",
            "family_id",
            "invitee_email",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    invitee_email: Mapped[str] = mapped_column(String(255))  # normalised, lower-case
    role: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)  # keyed HMAC
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    used_by_member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family_memberships.id"))


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (Index("ix_sessions_user", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("families.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)


AUDIT_ACTIONS = (
    "login", "logout", "device_paired", "device_revoked", "member_invited", "member_revoked",
    "location_accessed", "sos_created", "sos_resolved", "credential_rotated", "session_revoked",
    "settings_changed", "member_joined",
)  # fmt: skip
AUDIT_RESOURCES = ("user", "family", "device", "member", "incident")


class AuditEvent(Base):
    """Metadata only. Never coordinates, message bodies, passwords, or tokens."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(_in("action", AUDIT_ACTIONS)),
        CheckConstraint(_in("resource_type", AUDIT_RESOURCES)),
        CheckConstraint(_in("outcome", ("success", "failure"))),
        Index("ix_audit_family_created", "family_id", "created_at"),
        Index(
            "ix_audit_login_failures",
            text("(meta->>'email_key')"),
            "created_at",
            postgresql_where=text("action = 'login' AND outcome = 'failure'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("families.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("devices.id"))
    action: Mapped[str] = mapped_column(String(32))
    resource_type: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(16), default="success", server_default="success")
    reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column("meta", JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class TelemetryEvent(Base):
    """Append-only history. PK is (device_id, id) so one device's ids can never collide with,
    or reveal, another device's (ADR-010)."""

    __tablename__ = "telemetry_events"
    __table_args__ = (
        CheckConstraint(_in("event_type", ("location", "battery", "connectivity"))),
        CheckConstraint("sequence_number IS NULL OR sequence_number >= 0"),
        Index("ix_events_device_occurred", "device_id", text("occurred_at DESC")),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)  # device-generated, stable
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    sequence_number: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DeviceLatestState(Base):
    """Derived snapshot. Each group advances only for a strictly newer occurred_at (ADR-011).
    Never used for authorization."""

    __tablename__ = "device_latest_state"
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"))
    location_latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    location_longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    location_accuracy_meters: Mapped[float | None] = mapped_column(Numeric(8, 2))
    location_occurred_at: Mapped[datetime | None] = mapped_column(TS)
    location_received_at: Mapped[datetime | None] = mapped_column(TS)
    battery_percent: Mapped[int | None] = mapped_column(Integer)
    battery_is_charging: Mapped[bool | None] = mapped_column()
    battery_updated_at: Mapped[datetime | None] = mapped_column(TS)
    connectivity_network_type: Mapped[str | None] = mapped_column(String(32))
    connectivity_updated_at: Mapped[datetime | None] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
