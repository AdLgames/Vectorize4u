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
from app.models import Batch, Job, JobCandidate, UsageDaily, User, utcnow
from app.queue import dispatcher
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
        _fail_job(
            job_id,
            "tracer_crash",
            f"delivery cap {MAX_DELIVERIES} exceeded",
            unless="complete",
        )
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
            pending = _job_callback(job)
            session.commit()
            _notify(pending)
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
        _fail_job(job_id, "source_deleted", "the source object is missing")
        return {"status": "failed"}

    started = time.perf_counter()
    try:
        result = run_engine(data, _engine_options(options_blob))
    except BadImage as exc:
        # 400 class: the image is the problem. Never retried, never alerted.
        _fail_job(job_id, exc.error_code, str(exc))
        return {"status": "failed", "error_code": exc.error_code}
    except EngineError as exc:
        # 500 class: ours. Alert, and let the delivery cap bound the retries.
        log.exception("engine failure on job %s", job_id)
        _fail_job(job_id, exc.error_code, str(exc))
        return {"status": "failed", "error_code": exc.error_code}

    duration_ms = int((time.perf_counter() - started) * 1000)

    tier = source_key.split("/", 1)[0]
    output_keys: dict[str, str] = {}
    output_bytes = 0
    for fmt, blob in result.outputs.items():
        key = object_key(tier, "output", job_id, f"{job_id}.{fmt}")  # type: ignore[arg-type]
        storage().put(key, blob, content_type=CONTENT_TYPES.get(fmt, "application/octet-stream"))
        output_keys[fmt] = key
        output_bytes += len(blob)

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
            owner = session.get(User, job.user_id)
            plan = owner.plan if owner else "free"
            try:
                credits.spend_with_overage(
                    session,
                    job.user_id,
                    plan=plan,
                    amount=1,
                    reason="api_job",
                    root_job_id=job.root_job_id,
                    opted_out_of_cap=bool(owner and owner.overage_cap_opt_out),
                )
                job.credits_charged = 1
            except credits.AlreadyCharged:
                job.credits_charged = 0
            except (credits.InsufficientCredits, credits.OverageCapReached) as exc:
                # The work is done and the customer already has the result,
                # so deleting it now would be theatre. Record the shortfall;
                # the *next* request is refused at the door by
                # `assert_can_afford`, which is where a cap belongs.
                log_event(
                    session,
                    job,
                    "credit_shortfall",
                    {"amount": 1, "reason": type(exc).__name__},
                )

        _record_usage(session, job, output_bytes, duration_ms)

        log_event(
            session, job, "completed",
            {"duration_ms": duration_ms, "timings": result.timings_ms},
        )

        batch_id = job.batch_id
        callback = _job_callback(job)

    _notify(callback)
    if batch_id:
        _maybe_finish_batch(batch_id)

    return {"status": "complete", "duration_ms": duration_ms}


def _job_callback(job: Job) -> tuple[str, dict[str, Any]] | None:
    """The payload for a job's own `webhook_url`, or None if it has none.

    Read inside the session and delivered outside it: the callback is a
    network call, and holding a database transaction open across one is how
    a slow customer endpoint becomes our outage.
    """
    if not job.webhook_url:
        return None
    return job.webhook_url, {
        "type": f"job.{job.status}",
        "job_id": job.id,
        "status": job.status,
        "error_code": job.error_code,
        "credits_charged": job.credits_charged or 0,
    }


def _notify(callback: tuple[str, dict[str, Any]] | None) -> None:
    """Hand a callback to the queue.

    Routed through the same dispatcher as the jobs themselves, so the inline
    mode used by tests and by local development has nothing to special-case.
    """
    if callback is None:
        return
    dispatcher().send_webhook(callback[0], callback[1])


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


def _record_usage(session: Any, job: Job, bytes_out: int, duration_ms: int = 0) -> None:
    """Roll the job into `usage_daily`.

    This is what an invoice and the account page are built from, and it has
    to survive the job itself being deleted on schedule (§8) — so it is
    written when the work completes, not derived from jobs later.
    """
    if not job.user_id:
        return
    from sqlalchemy import select

    day = (job.finished_at or utcnow()).date()
    row = session.execute(
        select(UsageDaily).where(
            UsageDaily.user_id == job.user_id, UsageDaily.date == day
        )
    ).scalar_one_or_none()
    if row is None:
        row = UsageDaily(user_id=job.user_id, date=day)
        session.add(row)

    row.jobs = (row.jobs or 0) + 1
    row.credits = (row.credits or 0) + (job.credits_charged or 0)
    row.bytes_in = (row.bytes_in or 0) + (job.source_bytes or 0)
    row.bytes_out = (row.bytes_out or 0) + bytes_out
    row.compute_ms = (row.compute_ms or 0) + duration_ms


def _fail_job(job_id: str, error_code: str, detail: str, *, unless: str | None = None) -> None:
    """Fail a job in its own transaction, then fire its callback.

    The callback goes out after the commit, never inside it: a webhook that
    announces a state the database then rolls back is worse than a late one.
    """
    callback = None
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None or (unless is not None and job.status == unless):
            return
        _fail(session, job, error_code, detail)
        callback = _job_callback(job)
    _notify(callback)


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
        _notify((webhook_url, {"type": "batch.complete", "batch_id": batch_id}))


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


@celery_app.task(name="worker.tasks.check_cost_anomaly")
def check_cost_anomaly() -> dict[str, Any]:
    """§8: does yesterday's compute look like the week before it?

    Yesterday rather than today: a partial day is always "below average",
    and an alert that cries wolf every morning is one nobody reads.
    """
    from datetime import date, timedelta

    from app import costs

    yesterday = date.today() - timedelta(days=1)
    with session_scope() as session:
        report = costs.report(session, yesterday)

    log.info(
        "cost check %s: %.0fs vs %.0fs baseline (%s)",
        report.day,
        report.compute_ms / 1000,
        report.baseline_ms / 1000,
        report.reason,
    )
    delivered = costs.notify(report.message()) if report.alerting else False
    return {
        "day": report.day.isoformat(),
        "compute_ms": report.compute_ms,
        "baseline_ms": round(report.baseline_ms),
        "deviation": round(report.deviation, 4),
        "alerting": report.alerting,
        "delivered": delivered,
        "reason": report.reason,
    }


@celery_app.task(name="worker.tasks.deliver_webhook", bind=True, max_retries=5)
def deliver_webhook(self: Any, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Retried with backoff (§6); see `deliver_webhook_inline` for the rules."""
    try:
        return deliver_webhook_inline(url, payload)
    except WebhookDeliveryFailed as exc:  # pragma: no cover - network dependent
        raise self.retry(exc=exc, countdown=min(300, 2**self.request.retries * 5)) from exc


class WebhookDeliveryFailed(Exception):
    """The endpoint was reachable-in-principle but did not accept the call."""


def _webhook_client() -> Any:
    """The HTTP client used for callbacks. A seam, but a narrow one.

    Tests swap the *transport* under this rather than replacing the call,
    so the real request-building path — and its real keyword arguments —
    is the one under test. Replacing `httpx.post` wholesale is what let a
    TypeError ship.
    """
    import httpx

    return httpx.Client(timeout=10.0, follow_redirects=False)


def _resolve_callback(url: str) -> tuple[str, str]:
    """(ip, host) for a callback URL, or raise UnsafeUrl. A seam for tests."""
    from app.fetcher import validate

    ip, host = validate(url)
    return str(ip), str(host)


def deliver_webhook_inline(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a signed callback. HMAC-SHA256 over `timestamp.body` (§6).

    The destination is re-checked here, not only when the job was accepted:
    a callback host that resolved publicly an hour ago can point at our own
    metadata service by the time we deliver. Redirects are not followed for
    the same reason.
    """
    import hashlib
    import hmac
    import json
    from urllib.parse import urlparse, urlunparse

    from app.config import settings
    from app.fetcher import UnsafeUrl

    try:
        ip, host = _resolve_callback(url)
    except UnsafeUrl as exc:
        # Not retried: a private address does not become public on a retry.
        log.warning("refusing webhook delivery to %s: %s", url, exc)
        return {"status": "refused", "reason": str(exc)}

    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        settings().webhook_signing_secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()

    parsed = urlparse(url)
    connect_host = f"[{ip}]" if ":" in ip else ip
    target = urlunparse(parsed._replace(netloc=connect_host))

    try:
        # A Client, not httpx.post: the module-level helpers do not accept
        # `extensions`, and `sni_hostname` is what lets us connect to the
        # address we checked while still presenting the real hostname for
        # TLS. Passing it to httpx.post raised TypeError on every single
        # delivery — caught by the retry below, so it looked exactly like
        # a customer endpoint that was always down.
        with _webhook_client() as client:
            response = client.request(
                "POST",
                target,
                content=body,
                headers={
                    "Host": host,
                    "Content-Type": "application/json",
                    "X-Vectorize-Timestamp": timestamp,
                    "X-Vectorize-Signature": f"sha256={signature}",
                },
                extensions={"sni_hostname": host},
            )
        response.raise_for_status()
    except Exception as exc:
        raise WebhookDeliveryFailed(str(exc)) from exc
    return {"status": "delivered"}
