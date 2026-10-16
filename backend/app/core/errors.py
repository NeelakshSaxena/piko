"""Stable, safe error responses. Never echoes request input, SQL, paths, or secrets."""

import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("piko.errors")

STATUS_BY_CODE = {
    "AUTH_REQUIRED": 401,
    "AUTH_INVALID": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND_OR_NOT_VISIBLE": 404,
    "VALIDATION_ERROR": 400,
    "RATE_LIMIT": 429,
    "CONFLICT": 409,
    "SERVICE_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
}

DEFAULT_MESSAGES = {
    "AUTH_REQUIRED": "Authentication required.",
    "AUTH_INVALID": "Invalid credentials.",
    "FORBIDDEN": "Not permitted.",
    "NOT_FOUND_OR_NOT_VISIBLE": "Resource not found.",
    "VALIDATION_ERROR": "Request validation failed.",
    "RATE_LIMIT": "Too many requests.",
    "CONFLICT": "Conflict.",
    "SERVICE_UNAVAILABLE": "Service temporarily unavailable.",
    "INTERNAL_ERROR": "Internal error.",
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = STATUS_BY_CODE[code]
        self.message = message or DEFAULT_MESSAGES[code]
        self.headers = headers or {}


def error_response(
    request: Request, code: str, message: str | None = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message or DEFAULT_MESSAGES[code],
            "request_id": getattr(request.state, "request_id", None),
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }
    return JSONResponse(body, status_code=STATUS_BY_CODE[code], headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field locations are reported: pydantic's `input`/`msg` could echo secrets or
        # coordinates back to the caller or into logs.
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()})
        message = "Request validation failed: " + ", ".join(fields[:10])
        return error_response(request, "VALIDATION_ERROR", message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND_OR_NOT_VISIBLE"}.get(
            exc.status_code, "VALIDATION_ERROR" if exc.status_code < 500 else "INTERNAL_ERROR"
        )
        resp = error_response(request, code)
        resp.status_code = exc.status_code if exc.status_code in (405, 413) else resp.status_code
        return resp

    @app.exception_handler(OperationalError)
    async def _db_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        log.error("database unavailable (%s)", type(exc.orig).__name__)
        return error_response(request, "SERVICE_UNAVAILABLE")

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        log.error("database error (%s)", type(exc.orig).__name__)
        return error_response(request, "INTERNAL_ERROR")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error (%s)", type(exc).__name__)
        return error_response(request, "INTERNAL_ERROR")
