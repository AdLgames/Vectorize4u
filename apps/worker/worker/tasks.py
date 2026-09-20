"""Celery tasks. One task per file, never one per batch (§4.1).

Task bodies are idempotent, keyed on `job_id`: a requeue must not
double-charge or double-write outputs.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from typing import Any

from app import credits
from app.db import session_scope
from app.jobs import log_event
from app.models import Batch, Job, JobCandidate, utcnow
from app.storage import ObjectNotFound, object_key, storage
from celery.exceptions import Reject
from sqlalchemy import select

from worker.celery_app import MAX_DELIVERIES, celery_app

log = logging.getLogger("vectorize.worker")

CONTENT_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "pdf": "application/pdf",
    "eps": "application/postscript",
    "dxf": "image/vnd.dxf",
}


def _deliveries(job_id: str) -> int:
    """Increment and return this job's delivery count.

    Redis when it is available, the `jobs.attempts` column otherwise — the
    cap must hold even if the counter store is down, because the failure
    mode it guards against is an infinite redelivery loop.
    """
    try:
        import redis
        from app.config import settings

        client = redis.Redis.from_url(settings().redis_url, decode_responses=True)
        count = int(client.incr(f"attempts:{job_id}"))  # type: ignore[arg-type]
        client.expire(f"attempts:{job_id}", 3600)
        return count
    except Exception:  # pragma: no cover - depends on Redis being reachable
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return MAX_DELIVERIES
            job.attempts += 1
            return int(job.attempts)


@celery_app.task(name="worker.tasks.vectorize_job", bind=True, acks_late=True)
def vectorize_job(self: Any, job_id: str) -> dict[str, Any]:
    deliveries = _deliveries(job_id)
    if deliveries > MAX_DELIVERIES:
        # Poison pill. An image that kills its worker would otherwise be
        # redelivered forever under late acks + requeue-on-loss (§4.1).
        log.error("job %s exceeded the delivery cap (%d)", job_id, MAX_DELIVERIES)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None and job.status != "complete":
                _fail(session, job, "tracer_crash", f"delivery cap {MAX_DELIVERIES} exceeded")
        raise Reject(f"job {job_id} exceeded the delivery cap", requeue=False)

    return run_job_inline(job_id, delivery=deliveries)


def run_job_inline(job_id: str, *, delivery: int = 1) -> dict[str, Any]:
    """The task body, callable without Celery so it can be tested directly."""
    from engine.errors import BadImage, EngineError
    from engine.pipeline import run as run_engine

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return {"status": "missing"}
        # Idempotent on job_id: a requeue of an already-finished job is a
        # no-op, not a second charge and a second set of outputs.
        if job.status == "complete":
            return {"status": "already_complete"}
        if not job.source_key:
            _fail(session, job, "source_deleted", "the source image is gone")
            return {"status": "failed"}

        job.status = "processing"
        job.started_at = utcnow()
        job.attempts = delivery
        source_key = job.source_key
        options_blob = dict(job.options or {})
        kind = job.kind

    try:
        data = storage().get(source_key)
    except ObjectNotFound:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                _fail(session, job, "source_deleted", "the source object is missing")
        return {"status": "failed"}

    started = time.perf_counter()
    try:
        result = run_engine(data, _engine_options(options_blob))
    except BadImage as exc:
        # 400 class: the image is the problem. Never retried, never alerted.
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                _fail(session, job, exc.error_code, str(exc))
        return {"status": "failed", "error_code": exc.error_code}
    except EngineError as exc:
        # 500 class: ours. Alert, and let the delivery cap bound the retries.
        log.exception("engine failure on job %s", job_id)
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                _fail(session, job, exc.error_code, str(exc))
        return {"status": "failed", "error_code": exc.error_code}

    duration_ms = int((time.perf_counter() - started) * 1000)

    tier = source_key.split("/", 1)[0]
    output_keys: dict[str, str] = {}
    for fmt, blob in result.outputs.items():
        key = object_key(tier, "output", job_id, f"{job_id}.{fmt}")  # type: ignore[arg-type]
        storage().put(key, blob, content_type=CONTENT_TYPES.get(fmt, "application/octet-stream"))
        output_keys[fmt] = key

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:  # pragma: no cover - deleted mid-flight
            return {"status": "missing"}

        job.profile = result.profile.as_dict()
        job.classification = result.profile.classification
        job.classification_confidence = result.profile.classification_confidence
        job.engine_version = result.engine_version
        job.score_version = result.score_version
        job.chosen_params = result.chosen_params.as_dict()
        job.score = result.score.as_dict()
        job.warnings = result.warnings
        job.physical_w_mm = result.physical_size.width_mm
        job.physical_size_source = result.physical_size.source
        job.source_w = result.profile.width
        job.source_h = result.profile.height
        job.output_keys = output_keys
        job.status = "complete"
        job.finished_at = utcnow()
        job.error_code = None

        # Every candidate's params and scores are persisted: with `profile`
        # and `job_events`, this is the dataset that survives file deletion
        # and the input to profile → best-params priors (§5).
        session.execute(
            JobCandidate.__table__.delete().where(JobCandidate.job_id == job_id)
        )
        for candidate in result.candidates:
            row = candidate.as_row()
            session.add(
                JobCandidate(
                    job_id=job.id,
                    params=row["params"],
                    score=row["score"],
                    fidelity=row["fidelity"],
                    total=row["total"],
                    selected=row["selected"],
                    node_count=row["node_count"],
                    path_count=row["path_count"],
                    exit_status=row["exit_status"],
                    duration_ms=row["duration_ms"],
                )
            )

        # Charging, stated once: API jobs are debited on successful
        # completion; web jobs at unlock; failed jobs never (§6).
        if kind == "api" and job.user_id and job.credits_charged == 0:
            try:
                credits.spend(
                    session, job.user_id, amount=1, reason="api_job",
                    root_job_id=job.root_job_id,
                )
                job.credits_charged = 1
            except credits.AlreadyCharged:
                job.credits_charged = 0
            except credits.InsufficientCredits:
                # The work is done and the customer has the result; flag it
                # rather than deleting output they can already see.
                log_event(session, job, "credit_shortfall", {"amount": 1})

        log_event(
            session, job, "completed",
            {"duration_ms": duration_ms, "timings": result.timings_ms},
        )

        batch_id = job.batch_id

    if batch_id:
        _maybe_finish_batch(batch_id)

    return {"status": "complete", "duration_ms": duration_ms}


def _engine_options(blob: dict[str, Any]) -> Any:
    from engine.types import Options

    formats = tuple(blob.get("format") or ("svg",))
    return Options(
        mode=blob.get("mode", "auto"),
        quality_tier=blob.get("quality_tier", "standard"),
        detail=blob.get("detail", "balanced"),
        max_colors=blob.get("max_colors"),
        simplify=blob.get("simplify", True),
        keep_background=blob.get("keep_background", True),
        despeckle=blob.get("despeckle"),
        alpha_mode=blob.get("alpha_mode", "auto"),
        output_width=blob.get("output_width"),
        output_height=blob.get("output_height"),
        units=blob.get("units", "mm"),
        dxf_tolerance=blob.get("dxf_tolerance", 0.1),
        min_node_spacing_mm=blob.get("min_node_spacing_mm", 0.1),
        formats=formats,
    )


def _fail(session: Any, job: Job, error_code: str, detail: str) -> None:
    job.status = "failed"
    job.error_code = error_code
    job.finished_at = utcnow()
    # A failed job is never billed (§6, §10, §13).
    job.credits_charged = 0
    log_event(session, job, "failed", {"error_code": error_code, "detail": detail[:500]})


def _maybe_finish_batch(batch_id: str) -> None:
    with session_scope() as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            return
        rows = session.execute(select(Job).where(Job.batch_id == batch_id)).scalars().all()
        completed = sum(1 for j in rows if j.status == "complete")
        failed = sum(1 for j in rows if j.status == "failed")
        batch.completed = completed
        batch.failed = failed
        if not rows or completed + failed < len(rows):
            return
        batch.status = "complete"
        webhook_url = batch.webhook_url

    build_zip_inline(batch_id)
    if webhook_url:
        deliver_webhook.delay(webhook_url, {"type": "batch.complete", "batch_id": batch_id})


@celery_app.task(name="worker.tasks.build_batch_zip")
def build_batch_zip(batch_id: str) -> dict[str, Any]:
    return build_zip_inline(batch_id)


def build_zip_inline(batch_id: str) -> dict[str, Any]:
    """Zip artifacts follow the owner's retention, not a longer one (§8)."""
    with session_scope() as session:
        batch = session.get(Batch, batch_id)
        if batch is None:
            return {"status": "missing"}
        rows = session.execute(
            select(Job).where(Job.batch_id == batch_id, Job.status == "complete")
        ).scalars().all()
        entries = [(j.id, dict(j.output_keys or {})) for j in rows]
        tier = "paid"

    if not entries:
        return {"status": "empty"}

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for job_id, outputs in entries:
            for fmt, key in outputs.items():
                try:
                    archive.writestr(f"{job_id}.{fmt}", storage().get(key))
                except ObjectNotFound:  # pragma: no cover - raced with a purge
                    continue

    key = object_key(tier, "batch", batch_id, f"{batch_id}.zip")  # type: ignore[arg-type]
    storage().put(key, buffer.getvalue(), content_type="application/zip")

    with session_scope() as session:
        batch = session.get(Batch, batch_id)
        if batch is not None:
            batch.zip_key = key
    return {"status": "ok", "files": len(entries)}


@celery_app.task(name="worker.tasks.sweep_expired")
def sweep_expired() -> dict[str, int]:
    from app.retention import sweep

    with session_scope() as session:
        return {"purged": sweep(session)}


@celery_app.task(name="worker.tasks.deliver_webhook", bind=True, max_retries=5)
def deliver_webhook(self: Any, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Signed with HMAC-SHA256 and a timestamp, retried with backoff (§6)."""
    import hashlib
    import hmac
    import json

    import httpx
    from app.config import settings

    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        settings().webhook_signing_secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    try:
        response = httpx.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Vectorize-Timestamp": timestamp,
                "X-Vectorize-Signature": f"sha256={signature}",
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network dependent
        raise self.retry(exc=exc, countdown=min(300, 2 ** self.request.retries * 5)) from exc
    return {"status": "delivered"}
