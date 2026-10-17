"""Pure-ASGI middleware: request correlation, Origin validation, bounded (gzip-aware) bodies."""

import logging
import time
import uuid
import zlib

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response

log = logging.getLogger("piko.request")
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RequestContextMiddleware:
    """Assigns a server-generated request id (client-supplied ids are ignored) and logs one
    metadata-only line per request: no query string, headers, or body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.monotonic()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "%s %s -> %s in %dms request_id=%s",
                scope["method"],
                scope["path"],
                status,
                (time.monotonic() - started) * 1000,
                request_id,
            )


class ApiHeadersMiddleware:
    """Headers every browser-reachable response should carry.

    `/api/` responses (tokens, pairing and invite codes, coordinates, message text) must never sit in a
    browser or proxy cache (audit L-3), and must not be framed, sniffed or leak a referrer (audit F-10).
    The interactive docs page (development only) gets the non-caching-neutral subset."""

    API_HEADERS = (
        (b"cache-control", b"no-store"),
        (b"pragma", b"no-cache"),
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    )
    COMMON_HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/")
        added = (self.API_HEADERS if is_api else ()) + self.COMMON_HEADERS
        names = {name for name, _ in added}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message["headers"] = [*kept, *added]
            await send(message)

        await self.app(scope, receive, send_wrapper)


class HostMiddleware:
    """Rejects requests whose Host header is not an expected name (Host-header attacks)."""

    def __init__(self, app: ASGIApp, allowed: set[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw = dict(scope["headers"]).get(b"host", b"").decode("latin-1").lower()
            # Strip an optional :port without breaking bracketed IPv6 literals like [::1]:8000.
            host = raw.rsplit(":", 1)[0] if ":" in raw and not raw.endswith("]") else raw
            if host not in self.allowed:
                await error_response(Request(scope), "VALIDATION_ERROR", "Invalid host.")(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class OriginMiddleware:
    """Browsers always send Origin on cross-origin requests; reject any not on the allowlist.
    Native clients (the Android app) send none and are unaffected."""

    def __init__(self, app: ASGIApp, allowed: set[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            origin = dict(scope["headers"]).get(b"origin")
            if origin is not None and origin.decode("latin-1").rstrip("/") not in self.allowed:
                await error_response(Request(scope), "FORBIDDEN", "Origin not allowed.")(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    """Caps request bodies (also after gzip decompression) before any parsing happens."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await self._reject(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        encoding = headers.get(b"content-encoding", b"identity").lower()
        payload = bytes(body)
        if encoding == b"gzip":
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            try:
                payload = decoder.decompress(payload, self.max_bytes + 1)
            except zlib.error:
                await self._reject(scope, receive, send)
                return
            if len(payload) > self.max_bytes or decoder.unconsumed_tail or not decoder.eof:
                await self._reject(scope, receive, send)  # bomb or truncated stream
                return
        elif encoding != b"identity":
            await self._reject(scope, receive, send)
            return

        new_scope = dict(scope)
        new_scope["headers"] = [
            (k, v) for k, v in scope["headers"] if k not in (b"content-length", b"content-encoding")
        ] + [(b"content-length", str(len(payload)).encode())]
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return await receive()

        await self.app(new_scope, replay, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(Request(scope), "VALIDATION_ERROR", "Request body rejected.")
        await response(scope, receive, send)
