"""Request-scoped dependencies: database session, authenticated principal, rate limits."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.db.session import session_scope
from app.services.principals import DevicePrincipal, Principal, UserPrincipal, authenticate

_bearer = HTTPBearer(auto_error=False, description="User access token or device token")


def get_db(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.session_factory)


Db = Annotated[Session, Depends(get_db)]


def bearer_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    if creds is None or not creds.credentials:
        raise ApiError("AUTH_REQUIRED")
    return creds.credentials


BearerToken = Annotated[str, Depends(bearer_token)]


def current_principal(request: Request, db: Db, token: BearerToken) -> Principal:
    return authenticate(db, request.app.state.tokens, token, datetime.now(UTC))


def current_user(principal: Annotated[Principal, Depends(current_principal)]) -> UserPrincipal:
    if not isinstance(principal, UserPrincipal):
        raise ApiError("AUTH_INVALID", "Wrong credential type for this endpoint.")
    return principal


def current_device(principal: Annotated[Principal, Depends(current_principal)]) -> DevicePrincipal:
    if not isinstance(principal, DevicePrincipal):
        raise ApiError("AUTH_INVALID", "Wrong credential type for this endpoint.")
    return principal


AnyPrincipal = Annotated[Principal, Depends(current_principal)]
CurrentUser = Annotated[UserPrincipal, Depends(current_user)]
CurrentDevice = Annotated[DevicePrincipal, Depends(current_device)]


def client_ip(request: Request) -> str:
    # Forwarded headers are deliberately not trusted; a reverse-proxy mode is a Phase 8 decision.
    return request.client.host if request.client else "unknown"


def rate_limit(
    request: Request, response: Response, bucket: str, key: str, limit: int, window: int = 60
) -> None:
    limiter: RateLimiter = request.app.state.limiter
    allowed, remaining, retry_after = limiter.check(bucket, key, limit, window)
    headers = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining)}
    if not allowed:
        headers["Retry-After"] = str(retry_after)
        headers["X-RateLimit-Reset"] = str(retry_after)
        raise ApiError("RATE_LIMIT", headers=headers)
    for name, value in headers.items():
        response.headers[name] = value
