"""§5 data model.

Two invariants this file exists to protect:

1. **Credits are ledger-derived, never a mutable counter.** `users.credits_cached`
   and `credit_grants.remaining` are projections, rebuildable from
   `credit_ledger`. Getting this wrong means giving away free work or
   charging twice, and both are fatal at this scale.
2. **The dataset survives file deletion.** Sources and outputs are hard
   -deleted on schedule, so the accumulating asset is `jobs.profile` plus
   every candidate's params and scores plus `job_events`. None of it
   contains pixels.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres, JSON on SQLite. The test suite runs on SQLite so the
# whole service is testable without a database server; production is
# Postgres and gets the indexable type.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # A projection of credit_ledger, kept for cheap reads. Never authoritative.
    credits_cached: Mapped[int] = mapped_column(Integer, default=0)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    # §8 caps API overage at 3x the plan price unless a customer explicitly
    # opts out. Opting out is a deliberate, recorded act — never a default,
    # and never something a runaway loop can do on the customer's behalf.
    overage_cap_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sub"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("key"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 of the key. The plaintext is shown once and never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(120), default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bat"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    zip_key: Mapped[str | None] = mapped_column(String(512))
    webhook_url: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # A retried POST with the same Idempotency-Key must create one job
        # and one charge, never two.
        UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_idempotency"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_expires_at", "expires_at"),
        Index("ix_jobs_root", "root_job_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("job"))
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"))
    # Every revision of one source image shares a root_job_id, so one unlock
    # covers them all (§5: one charge per source image).
    root_job_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_job_id: Mapped[str | None] = mapped_column(String(64))

    kind: Mapped[str] = mapped_column(String(16))  # preview | sync | batch | api
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    webhook_url: Mapped[str | None] = mapped_column(Text)

    source_key: Mapped[str | None] = mapped_column(String(512))
    source_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_w: Mapped[int | None] = mapped_column(Integer)
    source_h: Mapped[int | None] = mapped_column(Integer)

    # Statistics only — no pixels. This is what survives file deletion.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    classification: Mapped[str | None] = mapped_column(String(32))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    engine_version: Mapped[str | None] = mapped_column(String(64))
    score_version: Mapped[str | None] = mapped_column(String(16))
    chosen_params: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    score: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    warnings: Mapped[list[str] | None] = mapped_column(JSONType)

    physical_w_mm: Mapped[float | None] = mapped_column(Float)
    physical_size_source: Mapped[str | None] = mapped_column(String(16))

    output_keys: Mapped[dict[str, str] | None] = mapped_column(JSONType)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    credits_charged: Mapped[int] = mapped_column(Integer, default=0)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64))

    candidates: Mapped[list[JobCandidate]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    @property
    def is_unlocked(self) -> bool:
        return self.unlocked_at is not None


class JobCandidate(Base):
    __tablename__ = "job_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cnd"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONType)
    score: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    fidelity: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float | None] = mapped_column(Float)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    node_count: Mapped[int | None] = mapped_column(Integer)
    path_count: Mapped[int | None] = mapped_column(Integer)
    exit_status: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    job: Mapped[Job] = relationship(back_populates="candidates")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # preview_viewed | param_tweaked | rerun | unlocked | downloaded | deleted
    # | refund_requested. Behaviour is the only signal in the system that is
    # not self-referential — it is the ground truth for weight tuning (§5).
    type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditGrant(Base):
    __tablename__ = "credit_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("grt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # free_monthly | plan_monthly | api_monthly | pack | promo
    source: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_event_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditLedger(Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        # One unlock covers every revision of one source image.
        UniqueConstraint("root_job_id", "reason", name="uq_ledger_root_job_reason"),
        # A replayed Stripe event must not grant twice.
        UniqueConstraint("stripe_event_id", "reason", name="uq_ledger_stripe_event_reason"),
        Index("ix_ledger_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("led"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("credit_grants.id"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(48))
    stripe_event_id: Mapped[str | None] = mapped_column(String(128))
    root_job_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_usage_user_date"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("usg"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[Any] = mapped_column(Date)
    jobs: Mapped[int] = mapped_column(Integer, default=0)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    bytes_in: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_out: Mapped[int] = mapped_column(BigInteger, default=0)


class Upload(Base):
    """A presigned upload slot.

    Tracked so `/v1/vectorize` can verify that the object it is about to
    ingest is one we actually issued a URL for, and by whom.
    """

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("upl"))
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    declared_bytes: Mapped[int] = mapped_column(BigInteger)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    """§6 — a retried POST returns the original job and never charges twice."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "user_key", "key", name="uq_idempotency"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("idm"))
    scope: Mapped[str] = mapped_column(String(64))
    user_key: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("whd"))
    target_url: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StripeEvent(Base):
    """Dedupe table. Stripe redelivers; the ledger must not double-grant."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


__all__ = [
    "ApiKey",
    "Base",
    "Batch",
    "CreditGrant",
    "CreditLedger",
    "IdempotencyRecord",
    "Job",
    "JobCandidate",
    "JobEvent",
    "StripeEvent",
    "Subscription",
    "Upload",
    "UsageDaily",
    "User",
    "WebhookDelivery",
    "func",
    "new_id",
    "utcnow",
]
