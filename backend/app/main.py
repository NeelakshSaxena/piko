"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import (
    BodyLimitMiddleware,
    HostMiddleware,
    OriginMiddleware,
    RequestContextMiddleware,
)
from app.core.ratelimit import RateLimiter
from app.core.security import TokenService
from app.db.session import make_engine, make_session_factory
from app.services.auth import AuthService
from app.services.devices import DeviceService
from app.services.invitations import InvitationService
from app.services.telemetry import TelemetryService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings)
    hmac_key = settings.hmac_key_file.read_bytes()
    if len(hmac_key) < 32:
        raise RuntimeError("hmac key file must contain at least 32 bytes")
    tokens = TokenService(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="Piko API",
        version="0.1.0",
        docs_url=None if settings.env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "production" else "/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.tokens = tokens
    app.state.limiter = RateLimiter()
    app.state.auth = AuthService(settings, tokens, hmac_key)
    app.state.devices = DeviceService(settings, hmac_key)
    app.state.invitations = InvitationService(settings, hmac_key)
    app.state.telemetry = TelemetryService(settings)

    install_error_handlers(app)
    app.include_router(router)
    # Added last = outermost. Order outermost-first: context, host, origin, body limit, CORS, gzip.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.allowed_origin_set),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(OriginMiddleware, allowed=settings.allowed_origin_set)
    app.add_middleware(HostMiddleware, allowed=settings.allowed_host_set)
    app.add_middleware(RequestContextMiddleware)

    return app
