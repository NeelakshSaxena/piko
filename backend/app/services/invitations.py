"""Inviting an adult (parent, family_admin or guardian) with a single-use code (ADR-017).

The inviter hands the code to the invitee out of band; Piko sends no email. The code is stored
only as a keyed HMAC. Redeeming it creates a *new* account bound to the invited email, so an
invitation can never attach an existing account (and its other family) to this family.
"""

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
    hash_password,
    keyed_digest,
    new_pairing_code,
    normalize_pairing_code,
)
from app.db.models import FamilyMembership, MemberInvitation, User
from app.services import audit
from app.services.authz import ADMIN_ROLES, issuer_is_authorised, require_family_role
from app.services.bootstrap import normalize_email
from app.services.principals import UserPrincipal

INVITE_LABEL = "member-invite"
INVITATION_TTL = timedelta(days=7)
INVITABLE_ROLES = ("parent", "family_admin", "guardian")


@dataclass(frozen=True)
class InvitationIssued:
    invitation_id: uuid.UUID
    email: str
    role: str
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class MemberJoined:
    user_id: uuid.UUID
    family_id: uuid.UUID
    membership_id: uuid.UUID
    role: str


class InvitationService:
    def __init__(self, settings: Settings, hmac_key: bytes) -> None:
        self._settings = settings
        self._hmac_key = hmac_key

    def _code_hash(self, canonical_code: str) -> str:
        return keyed_digest(self._hmac_key, INVITE_LABEL, canonical_code)

    def invite(
        self, db: Session, principal: UserPrincipal, family_id: uuid.UUID, email: str, role: str
    ) -> InvitationIssued:
        require_family_role(db, principal.user_id, family_id, ADMIN_ROLES)
        if role not in INVITABLE_ROLES:
            raise ApiError("VALIDATION_ERROR", "Invalid role for an invitation.")
        try:
            email = normalize_email(email)
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "Invalid email address.") from None
        now = datetime.now(UTC)
        # One live invitation per family and email: a new code supersedes the old one.
        db.execute(
            update(MemberInvitation)
            .where(
                MemberInvitation.family_id == family_id,
                MemberInvitation.invitee_email == email,
                MemberInvitation.status == "pending",
            )
            .values(status="revoked")
        )
        for _ in range(5):
            code = new_pairing_code()
            invitation = MemberInvitation(
                family_id=family_id,
                created_by_user_id=principal.user_id,
                invitee_email=email,
                role=role,
                code_hash=self._code_hash(code),
                expires_at=now + INVITATION_TTL,
            )
            try:
                with db.begin_nested():
                    db.add(invitation)
            except IntegrityError:  # astronomically unlikely hash collision: draw again
                continue
            audit.record(
                db, action="member_invited", resource_type="member", family_id=family_id,
                actor_user_id=principal.user_id, resource_id=invitation.id, meta={"role": role},
            )  # fmt: skip
            db.commit()
            return InvitationIssued(
                invitation.id, email, role, format_pairing_code(code), invitation.expires_at
            )
        raise ApiError("INTERNAL_ERROR")

    def accept(
        self,
        db: Session,
        *,
        code: str,
        email: str,
        password: str,
        full_name: str | None,
        ip: str,
    ) -> MemberJoined:
        """Unknown, malformed, used, expired, superseded and mismatched-email attempts all return
        the same AUTH_INVALID so the endpoint is not an oracle for codes or accounts."""
        now = datetime.now(UTC)
        canonical = normalize_pairing_code(code)
        invitation = (
            db.scalar(
                select(MemberInvitation)
                .where(MemberInvitation.code_hash == self._code_hash(canonical))
                .with_for_update()
            )
            if canonical is not None
            else None
        )
        reason = self._refusal(db, invitation, email, now)
        if reason is not None:
            if invitation is not None and reason == "expired":
                invitation.status = "expired"
            audit.record(
                db, action="member_joined", resource_type="member", outcome="failure",
                family_id=invitation.family_id if invitation else None, reason=reason,
                meta={"ip": ip},
            )  # fmt: skip
            db.commit()
            raise ApiError("AUTH_INVALID", "Invalid or expired invitation.")
        assert invitation is not None
        user = User(
            email=normalize_email(email),
            password_hash=hash_password(password, self._settings.bcrypt_rounds),
            full_name=full_name,
        )
        membership = FamilyMembership(
            family_id=invitation.family_id,
            role=invitation.role,
            invited_by_user_id=invitation.created_by_user_id,
            invited_at=invitation.created_at,
        )
        try:
            db.add(user)
            db.flush()
            membership.user_id = user.id
            db.add(membership)
            db.flush()
        except IntegrityError:  # the email was registered concurrently
            db.rollback()
            raise ApiError("AUTH_INVALID", "Invalid or expired invitation.") from None
        invitation.status = "used"
        invitation.used_at = now
        invitation.used_by_member_id = membership.id
        audit.record(
            db, action="member_joined", resource_type="member", family_id=invitation.family_id,
            actor_user_id=user.id, resource_id=membership.id, meta={"role": invitation.role},
        )  # fmt: skip
        db.commit()
        return MemberJoined(user.id, invitation.family_id, membership.id, invitation.role)

    @staticmethod
    def _refusal(
        db: Session, invitation: MemberInvitation | None, email: str, now: datetime
    ) -> str | None:
        if invitation is None:
            return "invalid_code"
        if invitation.status != "pending":
            return "not_pending"
        if invitation.expires_at <= now:
            return "expired"
        try:
            if normalize_email(email) != invitation.invitee_email:
                return "email_mismatch"
        except ValueError:
            return "email_mismatch"
        if db.scalar(select(User.id).where(User.email == invitation.invitee_email)) is not None:
            return "email_registered"
        ok = issuer_is_authorised(db, invitation.family_id, invitation.created_by_user_id)
        return None if ok else "issuer_not_authorised"
