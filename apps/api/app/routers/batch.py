"""§4.2 / §5 — batches as many per-file jobs, never one big task.

A 500-file batch is 500 tasks on `queue_batch`, which has its own capped
pool. One task per batch would mean a single failure loses the whole run and
a single slow file blocks 499 others.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import errors, ratelimit
from app import jobs as jobsvc
from app.auth import Principal, client_ip, rate_limited_principal, required_principal
from app.config import settings
from app.db import get_session
from app.models import Batch, Job, Upload, new_id
from app.queue import dispatcher
from app.schemas import (
    BatchCreateRequest,
    BatchCreateResponse,
    BatchFile,
    BatchResponse,
    BatchSlot,
    BatchStartRequest,
)
from app.storage import ObjectNotFound, object_key, storage

router = APIRouter(prefix="/v1", tags=["batch"])

PLAN_BATCH_LIMITS = {"free": 1, "starter": 25, "pro": 500, "api": 500}


def _batch_limit(principal: Principal) -> int:
    plan = principal.user.plan if principal.user else "free"
    return PLAN_BATCH_LIMITS.get(plan, 1)


@router.post("/batch", response_model=BatchCreateResponse)
def create_batch(
    body: BatchCreateRequest,
    principal: Principal = Depends(rate_limited_principal),
    session: Session = Depends(get_session),
) -> BatchCreateResponse:
    cfg = settings()
    limit = _batch_limit(principal)
    if body.count > limit:
        raise errors.forbidden(
            f"your plan allows batches of up to {limit} files; requested {body.count}"
        )
    if body.content_length > cfg.max_upload_bytes:
        raise errors.too_large(f"{body.content_length} bytes exceeds the per-file limit")

    assert principal.user is not None
    batch = Batch(
        user_id=principal.user.id,
        total=body.count,
        status="pending",
        webhook_url=body.webhook_url,
        options=body.options.model_dump(),
    )
    session.add(batch)
    session.flush()

    slots: list[BatchSlot] = []
    tier = jobsvc.storage_tier(principal)
    for _ in range(body.count):
        upload_id = new_id("upl")
        key = object_key(tier, "source", upload_id, "source.bin")  # type: ignore[arg-type]
        presigned = storage().presign_put(
            key,
            content_type=body.content_type,
            content_length=body.content_length,
            expires_in=cfg.upload_url_ttl_s,
        )
        session.add(
            Upload(
                id=upload_id,
                user_id=principal.user.id,
                key=key,
                content_type=body.content_type,
                declared_bytes=body.content_length,
            )
        )
        slots.append(
            BatchSlot(upload_id=upload_id, put_url=presigned.url, headers=presigned.headers)
        )

    session.flush()
    return BatchCreateResponse(batch_id=batch.id, slots=slots, expires_in=cfg.upload_url_ttl_s)


@router.post("/batch/{batch_id}/start", response_model=BatchResponse)
def start_batch(
    request: Request,
    batch_id: str,
    body: BatchStartRequest,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> BatchResponse:
    batch = session.get(Batch, batch_id)
    if batch is None or batch.user_id != principal.user_id:
        raise errors.not_found("batch")
    if batch.status != "pending":
        raise errors.conflict("batch_already_started", f"batch is {batch.status}")

    from app.schemas import JobOptions

    options = JobOptions.model_validate(batch.options or {})
    ip = ratelimit.ip_hash(client_ip(request))

    created: list[Job] = []
    for upload_id in body.upload_ids:
        upload = session.get(Upload, upload_id)
        if upload is None or upload.user_id != principal.user_id:
            raise errors.not_found(f"upload {upload_id}")
        try:
            info = storage().head(upload.key)
        except ObjectNotFound:
            # A slot the client never filled. Skipping beats failing the
            # whole batch — the progress grid shows what did not arrive.
            continue
        upload.consumed_at = jobsvc.utcnow()  # type: ignore[attr-defined]
        job = jobsvc.create_job(
            session,
            principal=principal,
            kind="batch",
            options=options,
            source_key=upload.key,
            source_bytes=info.size,
            ip_hash=ip,
        )
        job.batch_id = batch.id
        created.append(job)

    if not created:
        raise errors.bad_image("no uploaded files were found for this batch", "batch_empty")

    batch.total = len(created)
    batch.status = "processing"
    session.commit()

    # One Celery task per file, never one per batch (§4.1).
    for job in created:
        dispatcher().send(job.id, "batch")

    return _batch_response(session, batch)


@router.get("/batch/{batch_id}", response_model=BatchResponse)
def get_batch(
    batch_id: str,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> BatchResponse:
    batch = session.get(Batch, batch_id)
    if batch is None or batch.user_id != principal.user_id:
        raise errors.not_found("batch")
    return _batch_response(session, batch)


@router.post("/batch/{batch_id}/retry/{job_id}", response_model=BatchResponse)
def retry_file(
    batch_id: str,
    job_id: str,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> BatchResponse:
    """Per-file retry (§7). Closing the tab must not lose work."""
    batch = session.get(Batch, batch_id)
    if batch is None or batch.user_id != principal.user_id:
        raise errors.not_found("batch")
    job = session.get(Job, job_id)
    if job is None or job.batch_id != batch.id:
        raise errors.not_found("job")
    if job.status != "failed":
        raise errors.conflict("job_not_failed", f"job is {job.status}")

    job.status = "queued"
    job.error_code = None
    job.attempts = 0
    batch.failed = max(0, batch.failed - 1)
    session.commit()
    dispatcher().send(job.id, "batch")
    return _batch_response(session, batch)


def _batch_response(session: Session, batch: Batch) -> BatchResponse:
    # populate_existing is load-bearing: this session created these Job rows,
    # so its identity map still holds them with status="queued". The worker
    # has since completed them in its own transaction, and without this the
    # response reports a finished batch as untouched.
    rows = (
        session.execute(
            select(Job).where(Job.batch_id == batch.id).execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    completed = sum(1 for j in rows if j.status == "complete")
    failed = sum(1 for j in rows if j.status == "failed")
    batch.completed = completed
    batch.failed = failed
    if rows and completed + failed == len(rows) and batch.status == "processing":
        batch.status = "complete"
    session.flush()

    zip_url = None
    if batch.zip_key:
        zip_url = storage().presign_get(
            batch.zip_key,
            expires_in=settings().download_url_ttl_s,
            filename=f"{batch.id}.zip",
        )

    return BatchResponse(
        id=batch.id,
        status=batch.status,
        total=batch.total,
        completed=completed,
        failed=failed,
        files=[BatchFile(job_id=j.id, status=j.status, error_code=j.error_code) for j in rows],
        zip_url=zip_url,
    )


def count_active(session: Session, user_id: str) -> int:
    return int(
        session.execute(
            select(func.count(Job.id)).where(
                Job.user_id == user_id, Job.status.in_(("queued", "processing"))
            )
        ).scalar_one()
    )
