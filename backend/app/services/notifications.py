"""Durable notification outbox and its worker (ADR-023).

The intent to notify is written in the same transaction as the event it announces, so a crash,
restart or provider outage can never lose it. A worker (in-process after a request, a CLI loop, or an
external scheduler calling the protected endpoint) delivers due rows one at a time, each in its own
transaction: one failing row cannot block the others. Retries back off exponentially with jitter and
are bounded. A provider's acceptance is recorded as `accepted`; it is never reported as delivered or seen.

Payloads carry only a type and an id. Message text, notes and coordinates never enter this table or a
push payload: the receiving app fetches the authoritative data from the API.
"""

import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import (
    DevicePushToken,
    FamilyMembership,
    NotificationOutbox,
    User,
    WebPushSubscription,
)
from app.services.authz import VIEW_ROLES
from app.services.push import PushRegistry

KINDS = ("sos_created", "sos_update", "message")


# ---- transport boundary -----------------------------------------------------------------------
@dataclass(frozen=True)
class Accepted:
    """The push service took the message. Not a delivery receipt."""


@dataclass(frozen=True)
class InvalidTarget:
    """The address is permanently gone (unregistered token, expired subscription): remove it."""

    code: str


@dataclass(frozen=True)
class Permanent:
    """Retrying this message cannot succeed (rejected payload, bad credentials)."""

    code: str


@dataclass(frozen=True)
class Transient:
    """Try again later (rate limit, outage, network)."""

    code: str


SendResult = Accepted | InvalidTarget | Permanent | Transient


class PushTransport(Protocol):
    def send(self, address: str, payload: dict[str, str], ttl_seconds: int) -> SendResult: ...


@dataclass
class DrainResult:
    accepted: int = 0
    retried: int = 0
    dead: int = 0
    skipped: int = 0
    expired: int = 0
    waiting_for_transport: int = 0
    codes: dict[str, int] = field(default_factory=dict)

    @property
    def processed(self) -> int:
        return self.accepted + self.retried + self.dead + self.skipped + self.expired

    def count(self, code: str) -> None:
        self.codes[code] = self.codes.get(code, 0) + 1


def build_payload(kind: str, subject_id: uuid.UUID) -> dict[str, str]:
    return {"v": "1", "type": kind, "id": str(subject_id)}


class NotificationService:
    def __init__(
        self, settings: Settings, registry: PushRegistry, transports: dict[str, PushTransport]
    ) -> None:
        self._s = settings
        self._registry = registry
        # keys: "device_token" (FCM) and "web_subscription" (Web Push)
        self.transports = transports

    # ---- enqueue: called inside the caller's transaction; the caller commits ----------------------
    def enqueue_to_family_browsers(
        self, db: Session, *, family_id: uuid.UUID, kind: str, subject_id: uuid.UUID
    ) -> int:
        targets = list(
            db.scalars(
                select(WebPushSubscription.id)
                .join(
                    FamilyMembership,
                    (FamilyMembership.user_id == WebPushSubscription.user_id)
                    & (FamilyMembership.family_id == WebPushSubscription.family_id),
                )
                .join(User, User.id == WebPushSubscription.user_id)
                .where(
                    WebPushSubscription.family_id == family_id,
                    FamilyMembership.status == "active",
                    FamilyMembership.role.in_(VIEW_ROLES),
                    User.status == "active",
                )
            )
        )
        for target in targets:
            self._insert(db, family_id, kind, "web_subscription", target, subject_id, "")
        return len(targets)

    def enqueue_to_device(
        self,
        db: Session,
        *,
        family_id: uuid.UUID,
        device_id: uuid.UUID,
        kind: str,
        subject_id: uuid.UUID,
        variant: str = "",
    ) -> int:
        exists = db.scalar(
            select(DevicePushToken.device_id).where(
                DevicePushToken.device_id == device_id, DevicePushToken.family_id == family_id
            )
        )
        if exists is None:
            return 0
        self._insert(db, family_id, kind, "device_token", device_id, subject_id, variant)
        return 1

    def _insert(
        self,
        db: Session,
        family_id: uuid.UUID,
        kind: str,
        target_kind: str,
        target_id: uuid.UUID,
        subject_id: uuid.UUID,
        variant: str,
    ) -> None:
        now = datetime.now(UTC)
        ttl = (
            self._s.sos_notification_ttl_seconds
            if kind != "message"
            else self._s.message_notification_ttl_seconds
        )
        # One row per (event, state, target): replaying the event cannot create a second notification.
        key = f"{kind}:{variant}:{subject_id}:{target_id}"
        db.execute(
            pg_insert(NotificationOutbox)
            .values(
                id=uuid.uuid4(),
                family_id=family_id,
                kind=kind,
                target_kind=target_kind,
                target_id=target_id,
                subject_id=subject_id,
                dedupe_key=key,
                status="pending",
                attempts=0,
                next_attempt_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )

    # ---- worker ------------------------------------------------------------------------------------
    def drain(
        self, factory: sessionmaker[Session], limit: int | None = None, now: datetime | None = None
    ) -> DrainResult:
        result = DrainResult()
        budget = limit if limit is not None else self._s.outbox_batch_size
        when = now or datetime.now(UTC)
        for _ in range(budget):
            with factory() as db:
                row = db.scalar(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.status == "pending",
                        NotificationOutbox.next_attempt_at <= when,
                    )
                    .order_by(
                        case((NotificationOutbox.kind == "sos_created", 0), else_=1),
                        NotificationOutbox.next_attempt_at,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row is None:
                    break
                self._deliver(db, row, when, result)
                db.commit()
        return result

    def _deliver(
        self, db: Session, row: NotificationOutbox, now: datetime, out: DrainResult
    ) -> None:
        if row.expires_at <= now:
            row.status, row.last_error = "expired", "expired"
            out.expired += 1
            return
        address = self._address_for(db, row)
        if address is None:
            row.status, row.last_error = "skipped", "target_gone"
            out.skipped += 1
            return
        transport = self.transports.get(row.target_kind)
        if transport is None:
            # Not configured here: leave it pending and look again soon; nothing is attempted.
            row.next_attempt_at = now + timedelta(seconds=60)
            row.last_error = "transport_unconfigured"
            out.waiting_for_transport += 1
            return
        ttl = max(1, int((row.expires_at - now).total_seconds()))
        try:
            outcome = transport.send(address, build_payload(row.kind, row.subject_id), ttl)
        except Exception:  # noqa: BLE001 - a transport bug is a retryable failure of this row only
            outcome = Transient("transport_exception")
        row.attempts += 1
        if isinstance(outcome, Accepted):
            row.status, row.accepted_at, row.last_error = "accepted", now, None
            out.accepted += 1
        elif isinstance(outcome, InvalidTarget):
            self._drop_target(db, row)
            row.status, row.last_error = "dead", outcome.code
            out.dead += 1
            out.count(outcome.code)
        elif isinstance(outcome, Permanent):
            row.status, row.last_error = "dead", outcome.code
            out.dead += 1
            out.count(outcome.code)
        else:
            row.last_error = outcome.code
            out.count(outcome.code)
            if row.attempts >= self._s.outbox_max_attempts:
                row.status = "dead"
                out.dead += 1
            else:
                row.next_attempt_at = now + timedelta(seconds=self._backoff(row.attempts))
                out.retried += 1

    def _backoff(self, attempts: int) -> float:
        ceiling = min(
            self._s.outbox_backoff_cap_seconds,
            self._s.outbox_backoff_base_seconds * 2 ** (attempts - 1),
        )
        return float(ceiling) * random.uniform(0.5, 1.0)

    def _address_for(self, db: Session, row: NotificationOutbox) -> str | None:
        """The delivery address, or None if the target no longer exists or lost its right to be told."""
        if row.target_kind == "device_token":
            token_row = db.get(DevicePushToken, row.target_id)
            if token_row is None or token_row.family_id != row.family_id:
                return None
            return self._registry.open_device_token(token_row)
        sub = db.get(WebPushSubscription, row.target_id)
        if sub is None or sub.family_id != row.family_id:
            return None
        still_allowed = db.scalar(
            select(FamilyMembership.id)
            .join(User, User.id == FamilyMembership.user_id)
            .where(
                FamilyMembership.user_id == sub.user_id,
                FamilyMembership.family_id == row.family_id,
                FamilyMembership.status == "active",
                FamilyMembership.role.in_(VIEW_ROLES),
                User.status == "active",
            )
        )
        if still_allowed is None:
            return None  # a revoked member is not notified, even by an older subscription
        opened = self._registry.open_web_subscription(sub)
        return None if opened is None else _encode_web_address(opened)

    def _drop_target(self, db: Session, row: NotificationOutbox) -> None:
        if row.target_kind == "device_token":
            obj: DevicePushToken | WebPushSubscription | None = db.get(
                DevicePushToken, row.target_id
            )
        else:
            obj = db.get(WebPushSubscription, row.target_id)
        if obj is not None:
            db.delete(obj)

    # ---- health (no ids, no content) ----------------------------------------------------------------
    def health(self, db: Session) -> dict[str, object]:
        now = datetime.now(UTC)
        counts = dict(
            db.execute(
                select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status)
            ).all()
        )
        oldest = db.scalar(
            select(func.min(NotificationOutbox.created_at)).where(
                NotificationOutbox.status == "pending"
            )
        )
        due = db.scalar(
            select(func.count())
            .select_from(NotificationOutbox)
            .where(
                NotificationOutbox.status == "pending", NotificationOutbox.next_attempt_at <= now
            )
        )
        return {
            "by_status": {
                s: int(counts.get(s, 0))
                for s in ("pending", "accepted", "dead", "skipped", "expired")
            },
            "pending_due_now": int(due or 0),
            "oldest_pending_age_seconds": None
            if oldest is None
            else int((now - oldest).total_seconds()),
            "transports_configured": sorted(self.transports),
        }


def _encode_web_address(sub: dict[str, str]) -> str:
    """The Web Push transport receives the whole subscription as one opaque string."""
    return json.dumps(sub)
