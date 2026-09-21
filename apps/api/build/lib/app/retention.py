"""§8 retention.

Sources and outputs are hard-deleted after 24h (free) / 30 days (paid),
driven by `expires_at` and this sweeper. The R2 lifecycle rules on the
`free/` and `paid/` prefixes are the **backstop**: a dead sweeper must not
be able to break the retention promise, because that promise is exactly what
a print shop under NDA is buying.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs import log_event
from app.models import Batch, Job, utcnow
from app.storage import storage


def purge_job(session: Session, job: Job, *, reason: str = "deleted") -> int:
    """Delete every stored byte for this job, immediately.

    The statistical rows (`profile`, candidates, events) stay: they contain
    no pixels and they are the dataset that survives deletion (§5). But
    `user_id` is nulled, so what remains is not attributable to a person.
    """
    removed = 0
    store = storage()
    for key in list((job.output_keys or {}).values()):
        store.delete(key)
        removed += 1
    if job.source_key:
        store.delete(job.source_key)
        removed += 1

    log_event(session, job, "deleted", {"reason": reason, "objects": removed})

    job.output_keys = {}
    job.source_key = None
    job.user_id = None
    job.status = "expired" if reason == "expired" else job.status
    session.flush()
    return removed


def sweep(session: Session, *, now: datetime | None = None, limit: int = 500) -> int:
    """Purge everything past `expires_at`. Idempotent; safe to run often."""
    now = now or utcnow()
    stmt = (
        select(Job)
        .where(Job.expires_at.is_not(None), Job.expires_at < now, Job.source_key.is_not(None))
        .limit(limit)
    )
    purged = 0
    for job in session.execute(stmt).scalars():
        purge_job(session, job, reason="expired")
        purged += 1

    # Zip artifacts follow the owner's retention, not a longer one (§8).
    batch_stmt = select(Batch).where(Batch.zip_key.is_not(None)).limit(limit)
    for batch in session.execute(batch_stmt).scalars():
        jobs = session.execute(select(Job).where(Job.batch_id == batch.id)).scalars().all()
        if jobs and all(
            j.expires_at is not None and _aware(j.expires_at) < now for j in jobs
        ):
            storage().delete(batch.zip_key or "")
            batch.zip_key = None
            purged += 1

    session.flush()
    return purged


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
