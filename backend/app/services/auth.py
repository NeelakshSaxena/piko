"""Session lifecycle: login, refresh, revoke."""

import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import (
    TokenClaims,
    TokenService,
    hash_password,
    keyed_digest,
    sha256_hex,
    verify_password,
)
from app.db.models import AuditEvent, Family, FamilyMembership, RefreshSession, User
from app.services import audit
from app.services.authz import VIEW_ROLES
from app.services.principals import UserPrincipal


@dataclass(frozen=True)
class FamilyRole:
    id: uuid.UUID
    name: str
    role: str


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: uuid.UUID
    family_id: uuid.UUID
    role: str
    families: list[FamilyRole]


class AuthService:
    def __init__(self, settings: Settings, tokens: TokenService, hmac_key: bytes) -> None:
        self._settings = settings
        self._tokens = tokens
        self._hmac_key = hmac_key
        # Verified against when the email is unknown so response time does not reveal accounts.
        self._dummy_hash = hash_password("not-a-real-password", settings.bcrypt_rounds)

    def login(
        self, db: Session, *, email: str, password: str, fingerprint: str | None, ip: str
    ) -> LoginResult:
        now = datetime.now(UTC)
        email = email.strip().lower()
        email_key = keyed_digest(self._hmac_key, "login-email", email)
        self._reject_if_locked(db, email_key, now)

        user = db.scalar(select(User).where(User.email == email, User.status == "active"))
        ok = verify_password(password, user.password_hash if user else self._dummy_hash)
        if user is None or not ok:
            audit.record(
                db,
                action="login",
                resource_type="user",
                outcome="failure",
                actor_user_id=user.id if user else None,
                resource_id=user.id if user else None,
                reason="invalid_credentials",
                meta={"email_key": email_key, "ip": ip},
            )
            db.commit()
            raise ApiError("AUTH_INVALID")

        roles = self._family_roles(db, user.id)
        if not roles:
            raise ApiError("FORBIDDEN", "Account is not a member of any family.")
        primary = roles[0]
        session_id = uuid.uuid4()
        claims = TokenClaims(user.id, session_id, primary.id)
        refresh = self._tokens.issue_refresh(claims, now)
        db.add(
            RefreshSession(
                id=session_id,
                user_id=user.id,
                family_id=primary.id,
                token_hash=sha256_hex(refresh),
                device_fingerprint=fingerprint[:255] if fingerprint else None,
                expires_at=now + timedelta(seconds=self._tokens.refresh_ttl),
            )
        )
        audit.record(
            db, action="login", resource_type="user", actor_user_id=user.id, resource_id=user.id,
            family_id=primary.id, meta={"ip": ip},
        )  # fmt: skip
        db.commit()
        return LoginResult(
            access_token=self._tokens.issue_access(claims, now),
            refresh_token=refresh,
            expires_in=self._tokens.access_ttl,
            user_id=user.id,
            family_id=primary.id,
            role=primary.role,
            families=roles,
        )

    def refresh(self, db: Session, refresh_token: str) -> tuple[str, str, int, uuid.UUID]:
        """Rotates the refresh token. Returns (access_token, refresh_token, expires_in, user_id).

        Only the newest refresh token of a session is valid. A validly signed token that is not the
        newest was already replaced, so it has been copied or replayed: the whole session is
        revoked (audit M-3, ADR-019).
        """
        now = datetime.now(UTC)
        claims = self._tokens.verify(refresh_token, "refresh")
        if claims is None:
            raise ApiError("AUTH_INVALID")
        session = db.scalar(
            select(RefreshSession)
            .join(User, User.id == RefreshSession.user_id)
            .where(
                RefreshSession.id == claims.session_id,
                RefreshSession.user_id == claims.user_id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now,
                User.status == "active",
            )
            .with_for_update()
        )
        if session is None or not self._family_roles(db, claims.user_id):
            raise ApiError("AUTH_INVALID")
        if not hmac.compare_digest(session.token_hash, sha256_hex(refresh_token)):
            session.revoked_at = now
            audit.record(
                db, action="session_revoked", resource_type="user", outcome="failure",
                actor_user_id=session.user_id, resource_id=session.user_id,
                reason="refresh_token_reuse",
            )  # fmt: skip
            db.commit()
            raise ApiError("AUTH_INVALID")
        new_refresh = self._tokens.issue_refresh(claims, now)
        session.token_hash = sha256_hex(new_refresh)
        session.expires_at = now + timedelta(seconds=self._tokens.refresh_ttl)
        session.last_used_at = now
        db.commit()
        access = self._tokens.issue_access(claims, now)
        return access, new_refresh, self._tokens.access_ttl, claims.user_id

    def revoke(self, db: Session, principal: UserPrincipal) -> None:
        now = datetime.now(UTC)
        session = db.get(RefreshSession, principal.session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now
        audit.record(
            db, action="session_revoked", resource_type="user", actor_user_id=principal.user_id,
            resource_id=principal.user_id,
        )  # fmt: skip
        db.commit()

    def _reject_if_locked(self, db: Session, email_key: str, now: datetime) -> None:
        window = self._settings.login_failure_window_seconds
        failures = db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "login",
                AuditEvent.outcome == "failure",
                AuditEvent.meta["email_key"].astext == email_key,
                AuditEvent.created_at > now - timedelta(seconds=window),
            )
        )
        if (failures or 0) >= self._settings.login_failure_limit:
            raise ApiError("RATE_LIMIT", headers={"Retry-After": str(window)})

    @staticmethod
    def _family_roles(db: Session, user_id: uuid.UUID) -> list[FamilyRole]:
        rows = db.execute(
            select(Family.id, Family.name, FamilyMembership.role)
            .join(FamilyMembership, FamilyMembership.family_id == Family.id)
            .where(
                FamilyMembership.user_id == user_id,
                FamilyMembership.status == "active",
                FamilyMembership.role.in_(VIEW_ROLES),
                Family.status == "active",
            )
            .order_by(FamilyMembership.joined_at, FamilyMembership.id)
        ).all()
        return [FamilyRole(r.id, r.name, r.role) for r in rows]
