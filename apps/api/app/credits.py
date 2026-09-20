"""§5 credits: grants, ledger, and the consumption order.

**Credits are ledger-derived, never a mutable counter.** `CreditGrant.remaining`
and `User.credits_cached` are projections; `rebuild_projections` recomputes
both from `credit_ledger` alone, and the test suite asserts they match. If
they ever diverge, the ledger is right.

Why grants at all: a single summed ledger cannot express "100 downloads that
expire at period end" alongside "50 that never expire" alongside "API credits
that roll over up to 3×".

Consumption order is soonest-expiring first, never-expiring last. Spending a
never-expiring pack while a plan grant is about to lapse silently destroys
credits the customer paid for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog import overage_cap_credits
from app.models import CreditGrant, CreditLedger, User, func, utcnow

# Grants that never expire, in the order they are consumed *last*.
NEVER_EXPIRES = ("pack", "promo")
API_ROLLOVER_MULTIPLE = 3

#: Overage rides the grant system so the ledger stays the only truth.
OVERAGE_SOURCE = "api_overage"


class InsufficientCredits(Exception):
    pass


class OverageCapReached(Exception):
    """Past the hard ceiling on billable overage (§8).

    Distinct from InsufficientCredits: the customer *could* have kept
    going, and stopping them is a deliberate protection rather than an
    empty wallet. The two want different words in the API response.
    """

    def __init__(self, used: int, cap: int) -> None:
        super().__init__(f"overage cap reached: {used} of {cap} credits")
        self.used = used
        self.cap = cap


class AlreadyCharged(Exception):
    """The (root_job_id, reason) pair is already in the ledger."""

    def __init__(self, entry: CreditLedger) -> None:
        super().__init__(f"already charged: {entry.id}")
        self.entry = entry


@dataclass(frozen=True)
class GrantView:
    id: str
    source: str
    amount: int
    remaining: int
    expires_at: datetime | None


def _now() -> datetime:
    return utcnow()


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; Postgres hands back aware ones."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def open_grants(session: Session, user_id: str, *, for_update: bool = False) -> list[CreditGrant]:
    """Grants with credit left, in consumption order.

    Soonest-expiring first, never-expiring last. `for_update` takes row locks
    so two concurrent unlocks cannot both see the same last credit — on
    SQLite the clause is ignored, which is fine because the test suite is
    single-writer by construction.
    """
    stmt = select(CreditGrant).where(CreditGrant.user_id == user_id, CreditGrant.remaining > 0)
    if for_update and session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    grants = list(session.execute(stmt).scalars())

    now = _now()
    live = [g for g in grants if (_as_aware(g.expires_at) or now) >= now or g.expires_at is None]

    def sort_key(grant: CreditGrant) -> tuple[int, float, str]:
        expires = _as_aware(grant.expires_at)
        if expires is None:
            return (1, 0.0, grant.created_at.isoformat())
        return (0, expires.timestamp(), grant.created_at.isoformat())

    return sorted(live, key=sort_key)


def balance(session: Session, user_id: str) -> int:
    return sum(g.remaining for g in open_grants(session, user_id))


def grant(
    session: Session,
    user_id: str,
    *,
    source: str,
    amount: int,
    expires_at: datetime | None = None,
    stripe_event_id: str | None = None,
    reason: str | None = None,
) -> CreditGrant:
    """Create a grant and its ledger entry.

    Idempotent on `stripe_event_id`: Stripe redelivers, and a redelivery must
    not hand out a second month of credit.
    """
    if amount <= 0:
        raise ValueError("grant amount must be positive")

    if stripe_event_id:
        existing = session.execute(
            select(CreditGrant).where(CreditGrant.stripe_event_id == stripe_event_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    record = CreditGrant(
        user_id=user_id,
        source=source,
        amount=amount,
        remaining=amount,
        expires_at=expires_at,
        stripe_event_id=stripe_event_id,
    )
    session.add(record)
    session.flush()
    session.add(
        CreditLedger(
            user_id=user_id,
            grant_id=record.id,
            delta=amount,
            reason=reason or f"grant_{source}",
            stripe_event_id=stripe_event_id,
        )
    )
    _refresh_cache(session, user_id)
    return record


def spend(
    session: Session,
    user_id: str,
    *,
    amount: int = 1,
    reason: str,
    root_job_id: str | None = None,
) -> list[CreditLedger]:
    """Debit `amount` credits inside the caller's transaction.

    The unique `(root_job_id, reason)` constraint is what makes one unlock
    cover every revision of one source image: a second attempt raises
    `AlreadyCharged` carrying the original entry rather than charging again.
    """
    if amount <= 0:
        raise ValueError("spend amount must be positive")

    if root_job_id is not None:
        existing = session.execute(
            select(CreditLedger).where(
                CreditLedger.root_job_id == root_job_id, CreditLedger.reason == reason
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AlreadyCharged(existing)

    grants = open_grants(session, user_id, for_update=True)
    available = sum(g.remaining for g in grants)
    if available < amount:
        raise InsufficientCredits(f"have {available}, need {amount}")

    entries: list[CreditLedger] = []
    outstanding = amount
    for record in grants:
        if outstanding == 0:
            break
        take = min(record.remaining, outstanding)
        record.remaining -= take
        outstanding -= take
        entry = CreditLedger(
            user_id=user_id,
            grant_id=record.id,
            delta=-take,
            reason=reason,
            root_job_id=root_job_id,
        )
        session.add(entry)
        entries.append(entry)

    try:
        session.flush()
    except IntegrityError:
        # Lost a race on (root_job_id, reason). The other writer charged.
        session.rollback()
        raise

    _refresh_cache(session, user_id)
    return entries


def overage_used(session: Session, user_id: str, *, since: datetime | None = None) -> int:
    """Billable overage in the current period.

    Overage is modelled as a grant we hand out and bill for afterwards,
    rather than as a negative balance. That keeps the one rule the whole
    ledger rests on intact — every balance is the sum of its entries — and
    it means the amount to invoice is a query, not a reconstruction.
    """
    start = since or _period_start()
    total = session.execute(
        select(func.coalesce(func.sum(CreditGrant.amount), 0)).where(
            CreditGrant.user_id == user_id,
            CreditGrant.source == OVERAGE_SOURCE,
            CreditGrant.created_at >= start,
        )
    ).scalar_one()
    return int(total)


def grant_overage(
    session: Session,
    user_id: str,
    *,
    plan: str,
    amount: int = 1,
    opted_out_of_cap: bool = False,
) -> CreditGrant:
    """Extend credit past a zero balance, up to the plan's hard cap.

    Raises OverageCapReached rather than letting the bill run: §8 sets this
    ceiling precisely so that a customer's runaway retry loop costs them a
    known maximum instead of a surprise invoice.
    """
    cap = overage_cap_credits(plan)
    if cap <= 0:
        raise InsufficientCredits("this plan does not allow overage")

    used = overage_used(session, user_id)
    if not opted_out_of_cap and used + amount > cap:
        raise OverageCapReached(used, cap)

    return grant(
        session,
        user_id,
        source=OVERAGE_SOURCE,
        amount=amount,
        expires_at=None,
        reason="grant_api_overage",
    )


def spend_with_overage(
    session: Session,
    user_id: str,
    *,
    plan: str,
    amount: int = 1,
    reason: str,
    root_job_id: str | None = None,
    opted_out_of_cap: bool = False,
) -> list[CreditLedger]:
    """Spend credits, falling through to billable overage if allowed.

    The order matters: prepaid credit is always consumed before overage is
    created, or a customer with an unspent pack would be invoiced for usage
    they had already paid for.
    """
    try:
        return spend(session, user_id, amount=amount, reason=reason, root_job_id=root_job_id)
    except InsufficientCredits:
        pass

    available = balance(session, user_id)
    shortfall = amount - available
    grant_overage(session, user_id, plan=plan, amount=shortfall, opted_out_of_cap=opted_out_of_cap)
    return spend(session, user_id, amount=amount, reason=reason, root_job_id=root_job_id)


def _period_start() -> datetime:
    """Billing periods are calendar months here.

    Stripe's own period boundaries differ per subscription; when invoicing
    is wired up, pass the subscription's `current_period_start` instead of
    relying on this.
    """
    now = _now()
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def refund(
    session: Session,
    user_id: str,
    *,
    grant_id: str,
    stripe_event_id: str | None = None,
) -> int:
    """Reverse the **unspent** part of a purchase's grant.

    If it was already spent, the account is flagged for review rather than
    driven negative — a negative balance is a support problem either way, and
    a silently negative one is a support problem nobody notices.
    """
    record = session.get(CreditGrant, grant_id)
    if record is None:
        raise ValueError(f"no such grant: {grant_id}")

    unspent = record.remaining
    spent = record.amount - unspent
    if unspent:
        record.remaining = 0
        session.add(
            CreditLedger(
                user_id=user_id,
                grant_id=record.id,
                delta=-unspent,
                reason="refund",
                stripe_event_id=stripe_event_id,
            )
        )
    if spent:
        session.add(
            CreditLedger(
                user_id=user_id,
                grant_id=record.id,
                delta=0,
                reason="refund_flagged_for_review",
                stripe_event_id=stripe_event_id,
            )
        )
    session.flush()
    _refresh_cache(session, user_id)
    return spent


def apply_api_rollover_cap(session: Session, user_id: str, monthly_amount: int) -> int:
    """On renewal, cap total remaining api_monthly credits at 3× the monthly.

    Expires the oldest excess with a `rollover_cap` ledger entry, so the
    ledger explains the balance without anyone having to reconstruct policy.
    """
    cap = monthly_amount * API_ROLLOVER_MULTIPLE
    grants = [g for g in open_grants(session, user_id) if g.source == "api_monthly"]
    total = sum(g.remaining for g in grants)
    excess = total - cap
    if excess <= 0:
        return 0

    expired = 0
    for record in sorted(grants, key=lambda g: g.created_at):
        if excess <= 0:
            break
        take = min(record.remaining, excess)
        record.remaining -= take
        excess -= take
        expired += take
        session.add(
            CreditLedger(
                user_id=user_id,
                grant_id=record.id,
                delta=-take,
                reason="rollover_cap",
            )
        )
    session.flush()
    _refresh_cache(session, user_id)
    return expired


def expire_lapsed(session: Session, user_id: str) -> int:
    """Zero out grants past their expiry, with a ledger entry for each."""
    now = _now()
    stmt = select(CreditGrant).where(CreditGrant.user_id == user_id, CreditGrant.remaining > 0)
    expired = 0
    for record in session.execute(stmt).scalars():
        expires = _as_aware(record.expires_at)
        if expires is not None and expires < now:
            expired += record.remaining
            session.add(
                CreditLedger(
                    user_id=user_id,
                    grant_id=record.id,
                    delta=-record.remaining,
                    reason="grant_expired",
                )
            )
            record.remaining = 0
    session.flush()
    if expired:
        _refresh_cache(session, user_id)
    return expired


def monthly_free_grant(session: Session, user_id: str, amount: int) -> CreditGrant | None:
    """The free tier's monthly allowance, granted at most once per month.

    A non-positive allowance means the plan has none — paid plans get their
    credits from Stripe events, not from here.
    """
    if amount <= 0:
        return None
    now = _now()
    period = now.strftime("%Y-%m")
    reason = f"grant_free_monthly:{period}"
    existing = session.execute(
        select(CreditLedger).where(CreditLedger.user_id == user_id, CreditLedger.reason == reason)
    ).scalar_one_or_none()
    if existing is not None:
        return None
    return grant(
        session,
        user_id,
        source="free_monthly",
        amount=amount,
        expires_at=_end_of_month(now),
        reason=reason,
    )


def _end_of_month(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return datetime(now.year, now.month + 1, 1, tzinfo=UTC)


def period_end(days: int = 30) -> datetime:
    return _now() + timedelta(days=days)


def _refresh_cache(session: Session, user_id: str) -> None:
    user = session.get(User, user_id)
    if user is not None:
        user.credits_cached = sum(g.remaining for g in open_grants(session, user_id))


def rebuild_projections(session: Session, user_id: str) -> dict[str, int]:
    """Recompute `remaining` and `credits_cached` from the ledger alone.

    §13 requires `remaining` to rebuild *exactly* from `credit_ledger`. This
    is that rebuild, and the reconciliation test calls it after every
    scenario. If it ever disagrees with the stored projection, the stored
    projection is the thing that is wrong.
    """
    totals: dict[str, int] = {}
    entries = session.execute(select(CreditLedger).where(CreditLedger.user_id == user_id)).scalars()
    for entry in entries:
        if entry.grant_id is None:
            continue
        totals[entry.grant_id] = totals.get(entry.grant_id, 0) + entry.delta

    for grant_id, remaining in totals.items():
        record = session.get(CreditGrant, grant_id)
        if record is not None:
            record.remaining = max(0, remaining)

    session.flush()
    _refresh_cache(session, user_id)
    return totals


def grants_view(session: Session, user_id: str) -> list[GrantView]:
    return [
        GrantView(
            id=g.id,
            source=g.source,
            amount=g.amount,
            remaining=g.remaining,
            expires_at=_as_aware(g.expires_at),
        )
        for g in open_grants(session, user_id)
    ]
