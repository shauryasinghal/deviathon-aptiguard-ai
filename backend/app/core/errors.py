"""Consistent error envelope: {"error": {"code", "message", "details"}}. No stack traces leak."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("aptiguard.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: Any = None, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code:
            self.status_code = status_code
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unprocessable(AppError):
    status_code = 422
    code = "unprocessable"


def _envelope(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message, exc.details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_envelope("validation_error", "Request validation failed", details))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        ref = uuid.uuid4().hex[:12]
        log.exception("unhandled error ref=%s", ref)
        return JSONResponse(
            status_code=500, content=_envelope("internal_error", f"Internal server error (ref {ref})")
        )
