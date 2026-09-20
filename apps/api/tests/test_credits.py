"""§5 / §13 — the ledger reconciles with zero drift, or the money is wrong."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app import credits
from app.models import CreditGrant, CreditLedger, User, utcnow


@pytest.fixture()
def u(session):
    record = User(id="usr_ledger", email="ledger@example.com")
    session.add(record)
    session.commit()
    return record


def _reconciles(session, user_id: str) -> bool:
    """`remaining` must rebuild exactly from credit_ledger (§13)."""
    stored = {
        g.id: g.remaining
        for g in session.query(CreditGrant).filter(CreditGrant.user_id == user_id)
    }
    credits.rebuild_projections(session, user_id)
    rebuilt = {
        g.id: g.remaining
        for g in session.query(CreditGrant).filter(CreditGrant.user_id == user_id)
    }
    return stored == rebuilt


def test_grant_then_spend_reconciles(session, u):
    credits.grant(session, u.id, source="pack", amount=50)
    credits.spend(session, u.id, amount=3, reason="unlock", root_job_id="job_a")
    assert credits.balance(session, u.id) == 47
    assert _reconciles(session, u.id)


def test_expiring_grants_are_consumed_first(session, u):
    """Spending a never-expiring pack while a plan grant lapses destroys
    credits the customer paid for."""
    credits.grant(session, u.id, source="pack", amount=10, expires_at=None)
    credits.grant(
        session, u.id, source="plan_monthly", amount=10,
        expires_at=utcnow() + timedelta(days=5),
    )
    credits.spend(session, u.id, amount=10, reason="unlock", root_job_id="job_b")

    by_source = {g.source: g.remaining for g in credits.grants_view(session, u.id)}
    assert by_source.get("pack") == 10, "the never-expiring pack was spent first"
    assert "plan_monthly" not in by_source
    assert _reconciles(session, u.id)


def test_soonest_expiring_first_among_expiring(session, u):
    credits.grant(
        session, u.id, source="plan_monthly", amount=5,
        expires_at=utcnow() + timedelta(days=20),
    )
    later = utcnow() + timedelta(days=2)
    credits.grant(session, u.id, source="promo", amount=5, expires_at=later)
    credits.spend(session, u.id, amount=5, reason="unlock", root_job_id="job_c")
    remaining = {g.source: g.remaining for g in credits.grants_view(session, u.id)}
    assert remaining == {"plan_monthly": 5}


def test_one_charge_per_root_job(session, u):
    """Re-runs under one root_job_id bill once (§13)."""
    credits.grant(session, u.id, source="pack", amount=10)
    credits.spend(session, u.id, amount=1, reason="unlock", root_job_id="job_root")
    with pytest.raises(credits.AlreadyCharged):
        credits.spend(session, u.id, amount=1, reason="unlock", root_job_id="job_root")
    assert credits.balance(session, u.id) == 9


def test_out_of_credits_raises(session, u):
    credits.grant(session, u.id, source="pack", amount=1)
    credits.spend(session, u.id, amount=1, reason="unlock", root_job_id="job_d")
    with pytest.raises(credits.InsufficientCredits):
        credits.spend(session, u.id, amount=1, reason="unlock", root_job_id="job_e")


def test_api_rollover_caps_at_three_months(session, u):
    for _ in range(5):
        credits.grant(session, u.id, source="api_monthly", amount=500)
    expired = credits.apply_api_rollover_cap(session, u.id, 500)
    assert expired == 1000
    assert credits.balance(session, u.id) == 1500
    entries = [
        e.reason
        for e in session.query(CreditLedger).filter(CreditLedger.user_id == u.id)
    ]
    assert "rollover_cap" in entries
    assert _reconciles(session, u.id)


def test_refund_reverses_only_the_unspent_part(session, u):
    record = credits.grant(session, u.id, source="pack", amount=50)
    credits.spend(session, u.id, amount=20, reason="unlock", root_job_id="job_f")
    spent = credits.refund(session, u.id, grant_id=record.id)
    assert spent == 20
    assert credits.balance(session, u.id) == 0
    assert _reconciles(session, u.id)


def test_refund_of_spent_credits_flags_rather_than_going_negative(session, u):
    record = credits.grant(session, u.id, source="pack", amount=10)
    credits.spend(session, u.id, amount=10, reason="unlock", root_job_id="job_g")
    credits.refund(session, u.id, grant_id=record.id)
    assert credits.balance(session, u.id) == 0
    reasons = [
        e.reason for e in session.query(CreditLedger).filter(CreditLedger.user_id == u.id)
    ]
    assert "refund_flagged_for_review" in reasons


def test_expired_grants_are_not_spendable(session, u):
    credits.grant(
        session, u.id, source="plan_monthly", amount=10,
        expires_at=utcnow() - timedelta(days=1),
    )
    assert credits.balance(session, u.id) == 0
    with pytest.raises(credits.InsufficientCredits):
        credits.spend(session, u.id, amount=1, reason="unlock", root_job_id="job_h")


def test_expire_lapsed_writes_a_ledger_entry(session, u):
    credits.grant(
        session, u.id, source="plan_monthly", amount=7,
        expires_at=utcnow() - timedelta(days=1),
    )
    assert credits.expire_lapsed(session, u.id) == 7
    reasons = [
        e.reason for e in session.query(CreditLedger).filter(CreditLedger.user_id == u.id)
    ]
    assert "grant_expired" in reasons
    assert _reconciles(session, u.id)


def test_monthly_free_grant_is_once_per_month(session, u):
    first = credits.monthly_free_grant(session, u.id, amount=3)
    second = credits.monthly_free_grant(session, u.id, amount=3)
    assert first is not None
    assert second is None
    assert credits.balance(session, u.id) == 3


def test_grant_is_idempotent_on_stripe_event(session, u):
    """Stripe redelivers. A replay must not hand out a second month."""
    credits.grant(session, u.id, source="pack", amount=50, stripe_event_id="evt_1")
    credits.grant(session, u.id, source="pack", amount=50, stripe_event_id="evt_1")
    assert credits.balance(session, u.id) == 50


def test_credits_cached_is_a_projection(session, u):
    credits.grant(session, u.id, source="pack", amount=25)
    credits.spend(session, u.id, amount=5, reason="unlock", root_job_id="job_i")
    session.flush()
    assert session.get(User, u.id).credits_cached == 20
