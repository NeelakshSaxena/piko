"""Family messages (ADR-022): text between a family's parents and one child device.

`delivered` means the server durably stored the message and the recipient can fetch it. It does not
mean the recipient has seen it; only an explicit acknowledgement by the recipient side sets
`acknowledged`. Message bodies are never logged or audited.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import AuditEvent, Device, Message
from app.domain.telemetry import EventRejected, parse_occurred_at
from app.services import audit
from app.services.authz import ADMIN_ROLES, require_family_role, visible_device
from app.services.notifications import NotificationService
from app.services.principals import DevicePrincipal, Principal, UserPrincipal

READ_AUDIT_SPACING_SECONDS = 60


@dataclass(frozen=True)
class MessagePage:
    messages: list[Message]
    total_count: int
    has_more: bool


class MessageService:
    def __init__(self, settings: Settings, notifier: NotificationService) -> None:
        self._daily_cap = settings.messages_max_per_device_per_day
        self._notifier = notifier

    def send(
        self,
        db: Session,
        principal: Principal,
        *,
        message_id: uuid.UUID,
        body: str,
        sent_at: str,
        device_id: uuid.UUID | None,
    ) -> tuple[Message, bool]:
        """Returns (message, created). Replaying an id the same sender already sent returns the
        stored message unchanged; an id already used elsewhere is a conflict."""
        now = datetime.now(UTC)
        try:
            sent = parse_occurred_at(sent_at)
        except EventRejected:
            raise ApiError("VALIDATION_ERROR", "sent_at is not a valid timestamp.") from None
        sent = min(sent, now)  # a fast clock must not make a message unsendable (audit F-01)

        if isinstance(principal, DevicePrincipal):
            if device_id is not None and device_id != principal.device_id:
                raise ApiError("FORBIDDEN", "A device can only message for itself.")
            device_row = db.get(Device, principal.device_id)
            sender, sender_member_id, family_id = "device", None, principal.family_id
            conversation = principal.device_id
            if device_row is None:
                raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
        else:
            if device_id is None:
                raise ApiError("VALIDATION_ERROR", "device_id is required.")
            device_row = db.get(Device, device_id)
            if device_row is None or device_row.status == "revoked":
                raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
            membership = require_family_role(
                db, principal.user_id, device_row.family_id, ADMIN_ROLES
            )
            sender, sender_member_id, family_id = "parent", membership.id, device_row.family_id
            conversation = device_row.id

        replay = db.get(Message, message_id)
        if replay is None:
            # Volume cap per conversation (audit F-04): a stuck or hostile client cannot fill the table.
            recent = db.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.device_id == conversation, Message.received_at > now - timedelta(days=1)
                )
            )
            if (recent or 0) >= self._daily_cap:
                raise ApiError(
                    "RATE_LIMIT", "Too many messages today.", headers={"Retry-After": "3600"}
                )

        inserted = db.scalar(
            pg_insert(Message)
            .values(
                id=message_id,
                family_id=family_id,
                device_id=conversation,
                sender=sender,
                sender_member_id=sender_member_id,
                body=body,
                status="delivered",
                sent_at=sent,
                received_at=now,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(Message.id)
        )
        if inserted is None:
            existing = db.get(Message, message_id)
            if (
                existing is None
                or existing.device_id != conversation
                or existing.sender != sender
                or existing.sender_member_id != sender_member_id
            ):
                raise ApiError("CONFLICT", "Message id is already in use.")
            return existing, False
        if isinstance(principal, DevicePrincipal):
            db.execute(
                update(Device).where(Device.id == principal.device_id).values(last_activity_at=now)
            )
        # Notification intent commits with the message; the payload will carry only a type and an id.
        if sender == "device":
            self._notifier.enqueue_to_family_browsers(
                db, family_id=family_id, kind="message", subject_id=message_id
            )
        else:
            self._notifier.enqueue_to_device(
                db,
                family_id=family_id,
                device_id=conversation,
                kind="message",
                subject_id=message_id,
            )
        db.commit()  # the 201 is only reachable after a durable commit
        return db.get_one(Message, message_id), True

    def list(
        self,
        db: Session,
        principal: Principal,
        *,
        device_id: uuid.UUID | None,
        sender: str | None,
        limit: int,
        offset: int,
    ) -> MessagePage:
        if isinstance(principal, DevicePrincipal):
            if device_id is not None and device_id != principal.device_id:
                raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
            conversation = principal.device_id
        else:
            if device_id is None:
                raise ApiError("VALIDATION_ERROR", "device_id is required.")
            conversation = visible_device(db, principal, device_id).id
        conditions = [Message.device_id == conversation]
        if sender is not None:
            conditions.append(
                Message.sender == sender
            )  # lets a phone ask for parents' messages only
        if isinstance(principal, UserPrincipal):
            self._audit_read(db, principal, conversation)
        total = db.scalar(select(func.count()).select_from(Message).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(Message)
                .where(*conditions)
                .order_by(Message.received_at.desc(), Message.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return MessagePage(rows, total, offset + len(rows) < total)

    def acknowledge(self, db: Session, principal: Principal, message_id: uuid.UUID) -> Message:
        """The recipient side confirms it has seen a message. A device acknowledges parents'
        messages; a parent/family_admin acknowledges the child's. Senders cannot acknowledge their
        own messages. Repeating an acknowledgement changes nothing."""
        message = db.scalar(select(Message).where(Message.id == message_id).with_for_update())
        if message is None:
            raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
        member_id: uuid.UUID | None = None
        if isinstance(principal, DevicePrincipal):
            if message.device_id != principal.device_id:
                raise ApiError("NOT_FOUND_OR_NOT_VISIBLE")
            if message.sender != "parent":
                raise ApiError("FORBIDDEN", "You cannot acknowledge your own message.")
        else:
            assert isinstance(principal, UserPrincipal)
            member_id = require_family_role(
                db, principal.user_id, message.family_id, ADMIN_ROLES
            ).id
            if message.sender != "device":
                raise ApiError("FORBIDDEN", "You cannot acknowledge your own message.")
        if message.status != "acknowledged":
            message.status = "acknowledged"
            message.acknowledged_at = datetime.now(UTC)
            message.acknowledged_by_member_id = member_id
            db.commit()
        else:
            db.rollback()
        return db.get_one(Message, message_id)

    @staticmethod
    def _audit_read(db: Session, user: UserPrincipal, conversation: uuid.UUID) -> None:
        """Who read a child's conversation, and when (audit F-06). Metadata only: no text, and at
        most one row per user and conversation per minute, so a polling dashboard does not flood it."""
        recent = db.scalar(
            select(AuditEvent.id)
            .where(
                AuditEvent.action == "message_read",
                AuditEvent.actor_user_id == user.user_id,
                AuditEvent.resource_id == conversation,
                AuditEvent.created_at
                > datetime.now(UTC) - timedelta(seconds=READ_AUDIT_SPACING_SECONDS),
            )
            .limit(1)
        )
        if recent is not None:
            return
        family_id = db.scalar(select(Device.family_id).where(Device.id == conversation))
        audit.record(
            db, action="message_read", resource_type="device", family_id=family_id,
            actor_user_id=user.user_id, resource_id=conversation,
        )  # fmt: skip
        db.commit()
