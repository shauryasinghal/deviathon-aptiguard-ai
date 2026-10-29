"""AptiGuard AI — FastAPI application (modular monolith)."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import assembly, assessment, auth, calibration, dashboard, exposure, leaks, questions, reports, system, variants
from app.core.config import APP_VERSION, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("aptiguard.http")

app = FastAPI(
    title="AptiGuard AI API",
    version=APP_VERSION,
    description="Assessment-integrity platform: parallel item generation, human review, calibration, exposure-aware "
                "assembly and evidence-backed leak detection (IM-107).",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
install_error_handlers(app)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", "")
    rid = rid if rid.isalnum() and len(rid) <= 64 else uuid.uuid4().hex[:16]  # never echo untrusted header content
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > settings.max_request_mb * 1024 * 1024:
        return JSONResponse(status_code=413, content={"error": {"code": "payload_too_large",
                                                                "message": f"Request exceeds {settings.max_request_mb} MB"}})
    t0 = time.perf_counter()
    response = await call_next(request)
    dur = round((time.perf_counter() - t0) * 1000, 1)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    # only method/path/status/timing are logged — never bodies, answers or tokens
    log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                               "status": response.status_code, "duration_ms": dur})
    return response


api = APIRouter(prefix="/api/v1")
for r in (system, auth, dashboard, questions, variants, calibration, exposure, leaks, assembly, assessment, reports):
    api.include_router(r.router)
app.include_router(api)
