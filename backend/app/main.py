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
    ApiHeadersMiddleware,
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
from app.services.messages import MessageService
from app.services.notifications import NotificationService, PushTransport
from app.services.push import PushRegistry
from app.services.retention import RetentionService
from app.services.sos import SosService
from app.services.telemetry import TelemetryService


def build_transports(settings: Settings) -> dict[str, PushTransport]:
    """Only what is configured. A missing credential means that kind of push is simply off."""
    transports: dict[str, PushTransport] = {}
    if settings.fcm_project_id and settings.fcm_service_account_file:
        from app.services.push_transports import FcmTransport

        transports["device_token"] = FcmTransport.from_file(
            settings.fcm_project_id, settings.fcm_service_account_file
        )
    if settings.vapid_private_key_file and settings.vapid_public_key:
        from app.services.push_transports import WebPushTransport

        transports["web_subscription"] = WebPushTransport(
            settings.vapid_private_key_file, settings.vapid_subject
        )
    return transports


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
    app.state.push = PushRegistry(settings, hmac_key)
    app.state.notifier = NotificationService(settings, app.state.push, build_transports(settings))
    outbox_token = (
        settings.outbox_run_token_file.read_bytes().strip()
        if settings.outbox_run_token_file
        else None
    )
    if outbox_token is not None and len(outbox_token) < 32:
        raise RuntimeError("The outbox run token must be at least 32 bytes; regenerate it.")
    app.state.outbox_token = outbox_token
    app.state.retention = RetentionService(settings)
    app.state.sos = SosService(settings, app.state.notifier)
    app.state.messages = MessageService(settings, app.state.notifier)

    install_error_handlers(app)
    app.include_router(router)
    # Added last = outermost. Order outermost-first: no-store, context, host, origin, body limit, CORS, gzip.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    cors_origins = [o for o in sorted(settings.allowed_origin_set) if "*" not in o]
    cors_regex = (
        r"^https://.*\.vercel\.app$"
        if any("*.vercel.app" in o for o in settings.allowed_origins)
        else None
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_regex,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(OriginMiddleware, allowed=settings.allowed_origin_set)
    app.add_middleware(HostMiddleware, allowed=settings.allowed_host_set)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(ApiHeadersMiddleware)

    return app
