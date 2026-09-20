"""§6 — `/v1/vectorize`, `/v1/preview`, job status, unlock, tiles, delete."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credits, errors, ratelimit
from app import jobs as jobsvc
from app.auth import Principal, client_ip, optional_principal, required_principal
from app.config import settings
from app.db import get_session, session_factory
from app.fetcher import UnsafeUrl, fetch
from app.models import Job, Upload, utcnow
from app.queue import dispatcher
from app.schemas import (
    JobOptions,
    JobResponse,
    PhysicalSize,
    Quality,
    TweakRequest,
    VectorizeRequest,
)
from app.storage import ObjectNotFound, object_key, storage

router = APIRouter(prefix="/v1", tags=["jobs"])

TERMINAL = ("complete", "failed", "expired")


def job_response(job: Job, *, principal: Principal) -> JobResponse:
    outputs: dict[str, str] = {}
    cfg = settings()
    for fmt, key in jobsvc.visible_outputs(job).items():
        outputs[fmt] = storage().presign_get(
            key, expires_in=cfg.download_url_ttl_s, filename=f"{job.id}.{fmt}"
        )

    quality = None
    if job.score:
        quality = Quality(
            total=job.score["total"],
            fidelity=job.score["fidelity"],
            ssim=job.score["ssim"],
            edge_f1=job.score["edge_f1"],
            color=job.score["color"],
            alpha_iou=job.score.get("alpha_iou"),
            nodes=job.score["nodes"],
            paths=job.score["paths"],
            score_version=job.score["score_version"],
        )

    physical = None
    if job.physical_w_mm is not None and job.profile:
        aspect = (job.profile.get("height") or 1) / (job.profile.get("width") or 1)
        physical = PhysicalSize(
            width_mm=job.physical_w_mm,
            height_mm=round(job.physical_w_mm * aspect, 4),
            source=job.physical_size_source or "assumed",  # type: ignore[arg-type]
        )

    return JobResponse(
        id=job.id,
        status=job.status,  # type: ignore[arg-type]
        kind=job.kind,
        source_width=job.source_w,
        source_height=job.source_h,
        classification=job.classification,
        classification_confidence=job.classification_confidence,
        quality=quality,
        physical_size=physical,
        warnings=job.warnings or [],
        outputs=outputs,
        preview_url=f"/v1/jobs/{job.id}/preview" if job.status == "complete" else None,
        credits_charged=job.credits_charged,
        unlocked=job.is_unlocked,
        error_code=job.error_code,
        engine_version=job.engine_version,
        created_at=job.created_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
    )


def _resolve_source(
    session: Session,
    *,
    principal: Principal,
    body: VectorizeRequest,
    tier: str,
) -> tuple[str, int]:
    """Return (source_key, size). Enforces the size limit before any work."""
    cfg = settings()

    if body.upload_id:
        upload = session.get(Upload, body.upload_id)
        if upload is None:
            raise errors.not_found("upload")
        if upload.user_id != principal.user_id:
            raise errors.not_found("upload")
        try:
            info = storage().head(upload.key)
        except ObjectNotFound as exc:
            raise errors.bad_image("the upload was never completed", "upload_missing") from exc
        if info.size > cfg.max_upload_bytes:
            # Delete on violation: a client that ignores the signed
            # Content-Length does not get to keep the bytes.
            storage().delete(upload.key)
            raise errors.too_large(f"{info.size} bytes exceeds the limit")
        upload.consumed_at = utcnow()
        return upload.key, info.size

    if body.url:
        try:
            fetched = fetch(body.url)
        except UnsafeUrl as exc:
            raise errors.bad_image(str(exc), "unsafe_url") from exc
        key = object_key(tier, "source", f"url_{int(time.time() * 1000)}", "source.bin")  # type: ignore[arg-type]
        storage().put(
            key,
            fetched.data,
            content_type=fetched.content_type or "application/octet-stream",
        )
        return key, len(fetched.data)

    raise errors.bad_image("one of upload_id or url is required", "missing_source")


def _wait_for_completion(job_id: str, hold_s: float) -> Job | None:
    """Hold the connection up to `hold_s`, then hand back a 202 (§6).

    Polling a fresh session rather than refreshing the request's session: the
    worker commits in its own transaction, and the request's snapshot would
    never see it.
    """
    deadline = time.monotonic() + hold_s
    delay = 0.05
    while time.monotonic() < deadline:
        with session_factory()() as watcher:
            job = watcher.get(Job, job_id)
            if job is not None and job.status in TERMINAL:
                watcher.expunge(job)
                return job
        time.sleep(delay)
        delay = min(delay * 1.5, 0.4)
    return None


@router.post("/vectorize", response_model=JobResponse)
def vectorize(
    request: Request,
    response: Response,
    body: VectorizeRequest,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    prefer: Annotated[str | None, Header()] = None,
) -> JobResponse:
    payload = body.model_dump()
    existing = jobsvc.claim_idempotency(
        session, scope="vectorize", principal=principal, key=idempotency_key,
        request_payload=payload,
    )
    if existing is not None:
        # A retried request returns the original job and never charges twice.
        return job_response(existing, principal=principal)

    tier = jobsvc.storage_tier(principal)
    source_key, size = _resolve_source(session, principal=principal, body=body, tier=tier)

    kind = "api" if principal.is_api else "sync"
    job = jobsvc.create_job(
        session,
        principal=principal,
        kind=kind,
        options=body.options,
        source_key=source_key,
        source_bytes=size,
        ip_hash=ratelimit.ip_hash(client_ip(request)),
    )
    jobsvc.record_idempotency(
        session, scope="vectorize", principal=principal, key=idempotency_key,
        request_payload=payload, job=job,
    )
    session.commit()

    dispatcher().send(job.id, "sync")

    if prefer and "respond-async" in prefer.lower():
        response.status_code = 202
        session.refresh(job)
        return job_response(job, principal=principal)

    finished = _wait_for_completion(job.id, settings().sync_hold_window_s)
    if finished is None:
        # Not finished inside the hold window. The server never has to guess
        # a duration in advance (§6).
        response.status_code = 202
        session.refresh(job)
        return job_response(job, principal=principal)

    session.refresh(job)
    return job_response(job, principal=principal)


@router.post("/preview", response_model=JobResponse)
def preview(
    request: Request,
    response: Response,
    body: VectorizeRequest,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> JobResponse:
    """Free, rate-limited, anonymous-friendly (§7, §8).

    Runs on `queue_preview`, which has its own always-warm pool so a 500-file
    batch cannot delay it.
    """
    cfg = settings()
    identity = principal.user_id or ratelimit.ip_hash(client_ip(request))
    limit = (
        cfg.preview_limit_signed_in_per_hour
        if principal.user
        else cfg.preview_limit_anonymous_per_hour
    )
    decision = ratelimit.hit("preview", identity, limit)
    if not decision.allowed:
        raise errors.rate_limited(decision.retry_after, "preview limit reached for this hour")

    if principal.is_anonymous and decision.count > cfg.preview_turnstile_after:
        # Turnstile after 5 anonymous previews. The header tells the web app
        # to present the challenge; enforcement lands with the web app's
        # Turnstile integration (Phase 3).
        response.headers["X-Turnstile-Required"] = "1"

    tier = jobsvc.storage_tier(principal)
    source_key, size = _resolve_source(session, principal=principal, body=body, tier=tier)

    options = body.options.model_copy(update={"format": ["svg"]})
    job = jobsvc.create_job(
        session,
        principal=principal,
        kind="preview",
        options=options,
        source_key=source_key,
        source_bytes=size,
        ip_hash=ratelimit.ip_hash(client_ip(request)),
    )
    jobsvc.log_event(session, job, "preview_viewed", {"anonymous": principal.is_anonymous})
    session.commit()

    dispatcher().send(job.id, "preview")
    finished = _wait_for_completion(job.id, settings().sync_hold_window_s)
    if finished is None:
        response.status_code = 202
    session.refresh(job)
    response.headers["X-Preview-Remaining"] = str(decision.remaining)
    return job_response(job, principal=principal)


@router.post("/vectorize/multipart", response_model=JobResponse)
def vectorize_multipart(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    options: Annotated[str | None, Form()] = None,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> JobResponse:
    """Direct multipart, for small API clients (§4.3).

    The web app always uses the presigned flow; this exists so `curl -F` works.
    """
    cfg = settings()
    data = file.file.read(cfg.max_upload_bytes + 1)
    if len(data) > cfg.max_upload_bytes:
        raise errors.too_large(f"body exceeds {cfg.max_upload_bytes} bytes")

    parsed = JobOptions.model_validate_json(options) if options else JobOptions()
    tier = jobsvc.storage_tier(principal)
    key = object_key(tier, "source", f"mp_{int(time.time() * 1000)}", "source.bin")  # type: ignore[arg-type]
    storage().put(key, data, content_type=file.content_type or "application/octet-stream")

    job = jobsvc.create_job(
        session, principal=principal, kind="api" if principal.is_api else "sync",
        options=parsed, source_key=key, source_bytes=len(data),
        ip_hash=ratelimit.ip_hash(client_ip(request)),
    )
    session.commit()
    dispatcher().send(job.id, "sync")
    if _wait_for_completion(job.id, cfg.sync_hold_window_s) is None:
        response.status_code = 202
    session.refresh(job)
    return job_response(job, principal=principal)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> JobResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise errors.not_found("job")
    jobsvc.assert_owner(job, principal)
    return job_response(job, principal=principal)


@router.post("/jobs/{job_id}/unlock", response_model=JobResponse)
def unlock(
    job_id: str,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> JobResponse:
    """Spend a credit and enable downloads (§7.5).

    One charge per source image: every revision shares a `root_job_id`, and
    the unique `(root_job_id, reason)` ledger constraint makes the second
    unlock free rather than a second charge.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise errors.not_found("job")
    if job.user_id is not None and job.user_id != principal.user_id:
        raise errors.not_found("job")
    if job.status != "complete":
        raise errors.conflict("job_not_complete", f"job is {job.status}")

    user = principal.user
    assert user is not None

    # An anonymous preview becomes this user's job at unlock: they are the
    # one paying for it, and re-downloads must survive the session.
    if job.user_id is None:
        job.user_id = user.id
        job.expires_at = jobsvc.retention_expiry(principal)

    if job.is_unlocked:
        return job_response(job, principal=principal)

    already_unlocked = session.execute(
        select(Job).where(
            Job.root_job_id == job.root_job_id, Job.unlocked_at.is_not(None)
        )
    ).scalars().first()

    if already_unlocked is not None:
        job.unlocked_at = already_unlocked.unlocked_at
        session.flush()
        return job_response(job, principal=principal)

    try:
        credits.spend(session, user.id, amount=1, reason="unlock", root_job_id=job.root_job_id)
        job.credits_charged = 1
    except credits.AlreadyCharged:
        # Another revision of the same image already paid.
        job.credits_charged = 0
    except credits.InsufficientCredits as exc:
        raise errors.payment_required(
            "out of credits", balance=credits.balance(session, user.id)
        ) from exc

    job.unlocked_at = utcnow()
    jobsvc.log_event(session, job, "unlocked", {"credits": job.credits_charged})
    session.flush()
    return job_response(job, principal=principal)


@router.post("/jobs/{job_id}/tweak", response_model=JobResponse)
def tweak(
    request: Request,
    response: Response,
    job_id: str,
    body: TweakRequest,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> JobResponse:
    """The advanced panel (§7.6): re-run a *single* trace as a child job.

    Not the full search — the point is instant feedback. Every tweak is
    logged as `param_tweaked`, which is Phase 8's training signal.
    """
    parent = session.get(Job, job_id)
    if parent is None:
        raise errors.not_found("job")
    jobsvc.assert_owner(parent, principal)
    if not parent.source_key:
        raise errors.conflict("source_deleted", "the source image is no longer available")

    options = body.options.model_copy(update={"quality_tier": "fast"})
    child = jobsvc.create_job(
        session,
        principal=principal,
        kind=parent.kind,
        options=options,
        source_key=parent.source_key,
        source_bytes=parent.source_bytes,
        ip_hash=ratelimit.ip_hash(client_ip(request)),
        parent=parent,
    )
    jobsvc.log_event(session, child, "param_tweaked", {"parent": parent.id})
    session.commit()

    dispatcher().send(child.id, "preview")
    if _wait_for_completion(child.id, settings().sync_hold_window_s) is None:
        response.status_code = 202
    session.refresh(child)
    return job_response(child, principal=principal)


@router.get("/jobs/{job_id}/preview")
def preview_tile(
    job_id: str,
    request: Request,
    x: int = 0,
    y: int = 0,
    w: int = 512,
    h: int = 512,
    scale: float = 1.0,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> Response:
    """Watermarked raster tile (§7.4).

    **The SVG never reaches the browser before unlock.** An SVG in the DOM
    *is* the download, watermark or not — anyone can copy it out of DevTools.
    So the preview is raster tiles rendered on demand from the stored SVG,
    and the watermark is composited server-side.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise errors.not_found("job")
    jobsvc.assert_owner(job, principal)
    if job.status != "complete" or not job.output_keys:
        raise errors.conflict("job_not_complete", f"job is {job.status}")

    identity = principal.user_id or ratelimit.ip_hash(client_ip(request))
    decision = ratelimit.hit("tile", identity, settings().tile_limit_per_hour)
    if not decision.allowed:
        raise errors.rate_limited(decision.retry_after, "tile limit reached for this hour")

    scale = min(max(scale, 0.05), 8.0)  # max 8× (§7.4)
    w = min(max(w, 16), 2048)
    h = min(max(h, 16), 2048)

    svg_key = job.output_keys.get("svg")
    if not svg_key:
        raise errors.not_found("output")
    try:
        svg = storage().get(svg_key).decode("utf-8")
    except ObjectNotFound as exc:
        raise errors.not_found("output") from exc

    from app.tiles import render_tile_png

    png = render_tile_png(
        svg, x=x, y=y, w=w, h=h, scale=scale, watermark=not job.is_unlocked
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={
            # Short-lived and private. User artwork never goes into a
            # long-lived shared cache (§8).
            "Cache-Control": "private, max-age=60",
        },
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> Response:
    """Purge source and outputs now, and null `user_id` on the retained rows.

    The statistical rows stay — they contain no pixels — but they stop being
    attributable to a person (§5).
    """
    job = session.get(Job, job_id)
    if job is None:
        raise errors.not_found("job")
    jobsvc.assert_owner(job, principal)

    from app.retention import purge_job

    purge_job(session, job)
    return Response(status_code=204)
