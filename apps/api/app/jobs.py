"""Job creation, idempotency, retention and the charge rules.

Charging, stated once (§6, §10):
  API jobs are debited on **successful completion**.
  Web jobs are debited at **unlock**.
  Failed jobs are never billed.
  Re-runs under one `root_job_id` bill once.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import errors
from app.auth import Principal
from app.config import settings
from app.models import IdempotencyRecord, Job, JobEvent, utcnow
from app.schemas import JobOptions

# Outputs a job that is not unlocked may never expose. §13: "No route
# returns SVG or any vector output for a job that is not unlocked."
VECTOR_FORMATS = frozenset({"svg", "dxf", "pdf", "eps", "ai"})


def retention_expiry(principal: Principal) -> Any:
    cfg = settings()
    if principal.user is not None and principal.user.plan != "free":
        return utcnow() + timedelta(days=cfg.retention_paid_days)
    return utcnow() + timedelta(hours=cfg.retention_free_hours)


def storage_tier(principal: Principal) -> str:
    """Free work lands under `free/`, paid under `paid/`.

    The R2 lifecycle rules key on this prefix and are the backstop for the
    retention promise: a dead sweeper must not be able to break it (§8).
    """
    if principal.user is not None and principal.user.plan != "free":
        return "paid"
    return "free"


def assert_can_afford(session: Session, principal: Principal) -> None:
    """Refuse an API job at the door when there is no way to pay for it.

    Charging happens on successful completion (§6), which means a customer
    past their cap would otherwise have the work done, the CPU spent and
    the result delivered before anyone noticed. The cap exists to stop a
    bill running away; checking it only after the work is pointless.

    Web jobs are not checked here: they are charged at unlock, and a
    preview the customer cannot yet afford to download is exactly the free
    preview the product is built around.
    """
    from app import credits
    from app.catalog import OVERAGE_UNIT_CENTS, overage_cap_credits, plan_for

    user = principal.user
    if user is None or not principal.is_api:
        return

    if credits.balance(session, user.id) > 0:
        return

    plan = plan_for(user.plan)
    if not plan.allows_overage:
        raise errors.payment_required("out of credits", balance=0)

    if user.overage_cap_opt_out:
        return

    cap = overage_cap_credits(user.plan)
    used = credits.overage_used(session, user.id)
    if used >= cap:
        raise errors.ProblemError(
            402,
            "overage_cap_reached",
            (
                f"this account has used its ${cap * OVERAGE_UNIT_CENTS / 100:.2f} "
                "overage limit for the month. Raise the cap in your account "
                "settings, or buy credits."
            ),
            extra={"overage_used": used, "overage_cap": cap},
        )


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def claim_idempotency(
    session: Session,
    *,
    scope: str,
    principal: Principal,
    key: str | None,
    request_payload: dict[str, Any],
) -> Job | None:
    """Return the original job for a repeated key, or None to proceed.

    A repeated key with a *different* body is a client bug, and returning the
    old job would hide it. That is a 409, which is what the header is for.
    """
    if not key:
        return None

    user_key = principal.user_id or "anonymous"
    digest = fingerprint(request_payload)
    existing = session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.user_key == user_key,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()

    if existing is None:
        return None
    if existing.request_fingerprint != digest:
        raise errors.conflict(
            "idempotency_key_reused",
            "this Idempotency-Key was used with a different request body",
        )
    job = session.get(Job, existing.response_id)
    if job is None:  # pragma: no cover - only if a job was hard-deleted
        return None
    return job


def record_idempotency(
    session: Session,
    *,
    scope: str,
    principal: Principal,
    key: str | None,
    request_payload: dict[str, Any],
    job: Job,
) -> None:
    if not key:
        return
    session.add(
        IdempotencyRecord(
            scope=scope,
            user_key=principal.user_id or "anonymous",
            key=key,
            request_fingerprint=fingerprint(request_payload),
            response_id=job.id,
        )
    )
    try:
        session.flush()
    except IntegrityError:
        # Lost a race with a concurrent identical request. The other one won;
        # both callers end up with a job, and only one was created.
        session.rollback()


def create_job(
    session: Session,
    *,
    principal: Principal,
    kind: str,
    options: JobOptions,
    source_key: str | None,
    source_bytes: int | None,
    ip_hash: str | None,
    parent: Job | None = None,
) -> Job:
    job = Job(
        user_id=principal.user_id,
        kind=kind,
        status="queued",
        options=options.model_dump(),
        source_key=source_key,
        source_bytes=source_bytes,
        ip_hash=ip_hash,
        expires_at=retention_expiry(principal),
        root_job_id="",
        parent_job_id=parent.id if parent else None,
    )
    session.add(job)
    session.flush()
    # A tweak is a child of the same source image, so one unlock covers every
    # revision for the retention window (§5, §7.6).
    job.root_job_id = parent.root_job_id if parent else job.id
    if parent is not None:
        job.unlocked_at = parent.unlocked_at
        job.source_key = parent.source_key
        job.source_bytes = parent.source_bytes
    session.flush()
    return job


def log_event(
    session: Session,
    job: Job,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Behaviour is the only signal in the system that is not self-referential.

    It is the ground truth for weight tuning in Phase 8 (§5), so it is
    recorded even for anonymous users — the row carries no pixels and no
    plaintext IP.
    """
    session.add(
        JobEvent(
            job_id=job.id,
            user_id=job.user_id,
            type=event_type,
            payload=payload or {},
        )
    )


def visible_outputs(job: Job) -> dict[str, str]:
    """Output keys the caller is allowed to see, given the unlock state."""
    keys = job.output_keys or {}
    if job.is_unlocked or job.kind == "api":
        return dict(keys)
    return {k: v for k, v in keys.items() if k not in VECTOR_FORMATS}


def assert_owner(job: Job, principal: Principal) -> None:
    if job.user_id is None:
        # Anonymous preview jobs are reachable by id: the id is the secret,
        # they carry no vector output before unlock, and they expire in 24h.
        return
    if principal.user_id != job.user_id:
        raise errors.not_found("job")
