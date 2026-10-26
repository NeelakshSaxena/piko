"""Who is calling the MCP adapter. Identity comes only from a server-issued, revocable credential.

The credential is an RS256 JWT with its own audience (`piko-mcp`) and scope (`mcp:read`), backed by a
`refresh_sessions` row marked `mcp`. It is verified and re-checked against the database on every tool
call, so revoking the session or deactivating the user takes effect immediately. A model never supplies
or alters identity: the family is derived from the principal's memberships, not from any argument.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import TokenClaims, TokenService, sha256_hex
from app.db.models import RefreshSession, User
from app.services import audit
from app.services.authz import view_family_id
from app.services.principals import UserPrincipal

MCP_SESSION_LABEL = "mcp"


class McpAuthError(Exception):
    """The credential is missing, invalid, expired, revoked or not allowed. Carries no detail on purpose."""


@dataclass(frozen=True)
class IssuedMcpToken:
    session_id: uuid.UUID
    token: str  # shown once; only its SHA-256 is stored
    expires_at: datetime


def issue_token(
    db: Session,
    tokens: TokenService,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    ttl_hours: int,
    now: datetime | None = None,
) -> IssuedMcpToken:
    if not 1 <= ttl_hours <= settings.mcp_max_token_ttl_hours:
        raise ValueError(f"ttl_hours must be between 1 and {settings.mcp_max_token_ttl_hours}")
    now = now or datetime.now(UTC)
    user = db.scalar(select(User).where(User.id == user_id, User.status == "active"))
    if user is None:
        raise ValueError("no active user with that id")
    try:
        family_id = view_family_id(db, user_id)  # parent, family_admin or guardian; never a child
    except ApiError as exc:
        raise ValueError("that user may not read any family's safety data") from exc
    session_id = uuid.uuid4()
    expires_at = now + timedelta(hours=ttl_hours)
    token = tokens.issue_mcp(TokenClaims(user_id, session_id, family_id), ttl_hours * 3600, now)
    db.add(
        RefreshSession(
            id=session_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=sha256_hex(token),
            device_fingerprint=MCP_SESSION_LABEL,
            expires_at=expires_at,
        )
    )
    audit.record(
        db, action="mcp_token_issued", resource_type="user", family_id=family_id,
        actor_user_id=user_id, resource_id=user_id, meta={"session_id": str(session_id)},
    )  # fmt: skip
    db.commit()
    return IssuedMcpToken(session_id, token, expires_at)


def revoke_token(db: Session, session_id: uuid.UUID) -> bool:
    """Revokes one MCP credential. A normal login session cannot be revoked here."""
    now = datetime.now(UTC)
    session = db.scalar(
        select(RefreshSession)
        .where(RefreshSession.id == session_id, RefreshSession.device_fingerprint == MCP_SESSION_LABEL)
        .with_for_update()
    )  # fmt: skip
    if session is None:
        return False
    if session.revoked_at is None:
        session.revoked_at = now
        audit.record(
            db, action="mcp_token_revoked", resource_type="user", family_id=session.family_id,
            actor_user_id=session.user_id, resource_id=session.user_id,
            meta={"session_id": str(session_id)},
        )  # fmt: skip
    db.commit()
    return True


def authenticate(db: Session, tokens: TokenService, token: str, now: datetime) -> UserPrincipal:
    claims = tokens.verify(token, "mcp")
    if claims is None:
        raise McpAuthError
    row = db.execute(
        select(RefreshSession.id)
        .join(User, User.id == RefreshSession.user_id)
        .where(
            RefreshSession.id == claims.session_id,
            RefreshSession.user_id == claims.user_id,
            RefreshSession.device_fingerprint == MCP_SESSION_LABEL,
            RefreshSession.token_hash == sha256_hex(token),
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > now,
            User.status == "active",
        )
    ).first()
    if row is None:
        raise McpAuthError
    try:
        view_family_id(db, claims.user_id)  # membership may have been revoked since issuance
    except ApiError as exc:
        raise McpAuthError from exc
    return UserPrincipal(claims.user_id, claims.session_id, claims.family_hint)
