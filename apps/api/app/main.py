"""The FastAPI application.

§2: this service owns **all** of `/v1`, the credit ledger, Stripe webhooks
and the database migrations. Nothing else writes them.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import errors
from app.config import settings
from app.routers import account, batch, dev_auth, files, jobs, stripe_webhooks, uploads

log = logging.getLogger("vectorize.api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    cfg = settings()
    cfg.check()
    if not cfg.is_production:
        # Dev/test convenience only. Production schema changes go through
        # Alembic, which is the only place schema changes happen (§11).
        from app.db import engine
        from app.models import Base

        Base.metadata.create_all(engine())
    yield


app = FastAPI(
    title="Vectorize API",
    version="1.0.0",
    description=(
        "Raster → vector. Quality scores are returned with a `score_version`; "
        "never compare scores across versions."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Preview-Remaining", "X-Turnstile-Required", "Retry-After"],
)

app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(batch.router)
app.include_router(account.router)
app.include_router(stripe_webhooks.router)
app.include_router(files.router)

if not settings().is_production and settings().dev_auth_enabled:
    # Mounted only outside production, and only when explicitly switched on.
    # Settings.check() additionally refuses to boot production with it set.
    log.warning(
        "development sign-in is enabled at POST /v1/dev/session — this is an auth bypass"
    )
    app.include_router(dev_auth.router)


@app.exception_handler(HTTPException)
async def _http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return errors.http_exception_response(request, exc)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Never leak an internal message to the caller; Sentry gets the trace.
    log.exception("unhandled error on %s", request.url.path)
    return errors.problem_response(
        request, errors.internal(detail="an internal error occurred")
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "environment": settings().environment}


@app.get("/v1/limits")
def limits() -> dict[str, Any]:
    """Stated once, in the spec and here, so marketing copy can quote it.

    Previews are free and rate-limited — "free previews", never "unlimited".
    """
    cfg = settings()
    return {
        "preview_per_hour_anonymous": cfg.preview_limit_anonymous_per_hour,
        "preview_per_hour_signed_in": cfg.preview_limit_signed_in_per_hour,
        "turnstile_after_anonymous_previews": cfg.preview_turnstile_after,
        "tiles_per_hour": cfg.tile_limit_per_hour,
        "max_upload_bytes": cfg.max_upload_bytes,
        "retention_free_hours": cfg.retention_free_hours,
        "retention_paid_days": cfg.retention_paid_days,
    }
