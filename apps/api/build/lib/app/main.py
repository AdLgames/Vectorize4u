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
from app.routers import (
    account,
    batch,
    checkout,
    dev_auth,
    files,
    jobs,
    stripe_webhooks,
    uploads,
)

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
    expose_headers=[
        "X-Preview-Remaining",
        "X-Turnstile-Required",
        "Retry-After",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
    ],
)

app.include_router(uploads.router)
app.include_router(jobs.router)
app.include_router(batch.router)
app.include_router(account.router)
app.include_router(checkout.router)
app.include_router(stripe_webhooks.router)
app.include_router(files.router)

if not settings().is_production and settings().dev_auth_enabled:
    # Mounted only outside production, and only when explicitly switched on.
    # Settings.check() additionally refuses to boot production with it set.
    log.warning("development sign-in is enabled at POST /v1/dev/session — this is an auth bypass")
    app.include_router(dev_auth.router)


@app.middleware("http")
async def _rate_limit_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Tell clients where they stand before they hit the wall.

    A 429 that arrives with no warning is indistinguishable from an outage
    to the integration on the other end; RateLimit-Remaining lets a well
    -behaved client slow down on its own.
    """
    response = await call_next(request)
    state = getattr(request.state, "rate_limit", None)
    if state:
        limit, remaining, reset = state
        response.headers["RateLimit-Limit"] = str(limit)
        response.headers["RateLimit-Remaining"] = str(remaining)
        response.headers["RateLimit-Reset"] = str(reset)
    return response


@app.exception_handler(HTTPException)
async def _http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return errors.http_exception_response(request, exc)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Never leak an internal message to the caller; Sentry gets the trace.
    log.exception("unhandled error on %s", request.url.path)
    return errors.problem_response(request, errors.internal(detail="an internal error occurred"))


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
        # Whether this deployment can take money. A client needs it to know
        # if offering a plan leads anywhere, and it is the only way to tell
        # a configured deployment from one where checkout answers 503 —
        # /v1/plans is served from the catalogue and reads the same either
        # way. It says nothing secret: a visitor discovers it by clicking
        # Buy, and the price list is public already.
        "payments_enabled": cfg.payments_enabled,
    }
