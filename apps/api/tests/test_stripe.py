"""§10 — every event maps to grant operations, never a direct balance edit."""

from __future__ import annotations

import pytest

from app import credits
from app.models import CreditGrant, CreditLedger, Subscription, User


@pytest.fixture()
def customer(session):
    record = User(
        id="usr_stripe", email="pays@example.com", stripe_customer_id="cus_1", plan="free"
    )
    session.add(record)
    session.commit()
    return record


def _event(client, event_id: str, event_type: str, obj: dict) -> dict:
    response = client.post(
        "/v1/stripe/webhook",
        json={"id": event_id, "type": event_type, "data": {"object": obj}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _balance(user_id: str) -> int:
    from app.db import session_factory

    with session_factory()() as s:
        return credits.balance(s, user_id)


def _reconciles(user_id: str) -> bool:
    from app.db import session_factory

    with session_factory()() as s:
        before = {g.id: g.remaining for g in s.query(CreditGrant).all()}
        credits.rebuild_projections(s, user_id)
        after = {g.id: g.remaining for g in s.query(CreditGrant).all()}
        return before == after


def test_subscription_checkout_grants_plan_credits(client, customer):
    _event(client, "evt_1", "checkout.session.completed",
           {"customer": "cus_1", "mode": "subscription", "metadata": {"plan": "starter"}})
    assert _balance(customer.id) == 100
    assert _reconciles(customer.id)

    from app.db import session_factory

    with session_factory()() as s:
        assert s.get(User, customer.id).plan == "starter"


def test_credit_pack_never_expires(client, customer):
    _event(client, "evt_2", "checkout.session.completed",
           {"customer": "cus_1", "mode": "payment", "metadata": {"credits": "50"}})
    from app.db import session_factory

    with session_factory()() as s:
        grant = s.query(CreditGrant).filter(CreditGrant.source == "pack").one()
        assert grant.expires_at is None
        assert grant.remaining == 50


def test_replayed_event_does_not_grant_twice(client, customer):
    _event(client, "evt_3", "invoice.paid", {"customer": "cus_1", "metadata": {"plan": "pro"}})
    duplicate = _event(client, "evt_3", "invoice.paid",
                       {"customer": "cus_1", "metadata": {"plan": "pro"}})
    assert duplicate["status"] == "duplicate"
    assert _balance(customer.id) == 1000


def test_renewal_grants_expire_at_period_end(client, customer):
    _event(client, "evt_4", "invoice.paid", {"customer": "cus_1", "metadata": {"plan": "starter"}})
    from app.db import session_factory

    with session_factory()() as s:
        grant = s.query(CreditGrant).filter(CreditGrant.source == "plan_monthly").one()
        assert grant.expires_at is not None


def test_api_plan_rolls_over_but_caps_at_three_months(client, customer):
    for i in range(5):
        _event(client, f"evt_api_{i}", "invoice.paid",
               {"customer": "cus_1", "metadata": {"plan": "api"}})
    assert _balance(customer.id) == 1500  # 3 × 500
    from app.db import session_factory

    with session_factory()() as s:
        reasons = {e.reason for e in s.query(CreditLedger).all()}
        assert "rollover_cap" in reasons
    assert _reconciles(customer.id)


def test_payment_failure_suspends_the_plan(client, customer):
    _event(client, "evt_5", "checkout.session.completed",
           {"customer": "cus_1", "mode": "subscription", "metadata": {"plan": "pro"}})
    _event(client, "evt_6", "invoice.payment_failed", {"customer": "cus_1"})
    from app.db import session_factory

    with session_factory()() as s:
        assert s.get(User, customer.id).plan == "free"
    # past_due suspends new unlocks; it does not confiscate bought credits.
    assert _balance(customer.id) == 1000


def test_subscription_deleted_drops_to_free(client, customer):
    _event(client, "evt_7", "customer.subscription.updated",
           {"customer": "cus_1", "id": "sub_x", "status": "active", "metadata": {"plan": "pro"}})
    _event(client, "evt_8", "customer.subscription.deleted",
           {"customer": "cus_1", "id": "sub_x"})
    from app.db import session_factory

    with session_factory()() as s:
        assert s.get(User, customer.id).plan == "free"
        assert s.query(Subscription).one().status == "canceled"


def test_refund_reverses_the_unspent_part(client, customer):
    _event(client, "evt_9", "checkout.session.completed",
           {"customer": "cus_1", "mode": "payment", "metadata": {"credits": "50"}})

    from app.db import session_factory

    with session_factory()() as s:
        credits.spend(s, customer.id, amount=10, reason="unlock", root_job_id="job_x")
        s.commit()

    _event(client, "evt_10", "charge.refunded",
           {"customer": "cus_1", "metadata": {"grant_event_id": "evt_9"}})
    assert _balance(customer.id) == 0
    with session_factory()() as s:
        reasons = {e.reason for e in s.query(CreditLedger).all()}
        assert "refund" in reasons
        assert "refund_flagged_for_review" in reasons
    assert _reconciles(customer.id)


def test_dispute_freezes_the_account(client, customer):
    _event(client, "evt_11", "charge.dispute.created", {"customer": "cus_1"})
    from app.db import session_factory

    with session_factory()() as s:
        assert s.get(User, customer.id).plan == "frozen"


def test_unknown_event_type_is_ignored(client, customer):
    result = _event(client, "evt_12", "customer.created", {"customer": "cus_1"})
    assert result["status"] == "ignored"


def test_unattributable_event_is_not_retried_forever(client):
    result = _event(client, "evt_13", "invoice.paid", {"customer": "cus_unknown"})
    assert result["status"] == "unattributed"


def test_full_lifecycle_reconciles_with_zero_drift(client, customer):
    """§13: subscribe / renew / cancel / refund / dispute / pack all reconcile."""
    _event(client, "l1", "checkout.session.completed",
           {"customer": "cus_1", "mode": "subscription", "metadata": {"plan": "starter"}})
    _event(client, "l2", "invoice.paid", {"customer": "cus_1", "metadata": {"plan": "starter"}})
    _event(client, "l3", "checkout.session.completed",
           {"customer": "cus_1", "mode": "payment", "metadata": {"credits": "50"}})

    from app.db import session_factory

    with session_factory()() as s:
        credits.spend(s, customer.id, amount=30, reason="unlock", root_job_id="job_y")
        s.commit()

    _event(
        client, "l4", "customer.subscription.updated",
        {
            "customer": "cus_1", "id": "sub_y", "status": "active",
            "metadata": {"plan": "starter"},
        },
    )
    _event(client, "l5", "charge.refunded",
           {"customer": "cus_1", "metadata": {"grant_event_id": "l3"}})
    _event(client, "l6", "customer.subscription.deleted", {"customer": "cus_1", "id": "sub_y"})

    assert _reconciles(customer.id)
    with session_factory()() as s:
        # Balance is never negative, whatever order the events arrived in.
        assert credits.balance(s, customer.id) >= 0


# --- staging without Stripe -------------------------------------------


def _staging_settings(**overrides):
    """A production-shaped configuration, minus whatever the test removes."""
    from app.config import Settings

    base = {
        "environment": "staging",
        "storage_backend": "r2",
        "r2_bucket": "b",
        "r2_endpoint_url": "https://example.r2.cloudflarestorage.com",
        "ip_hash_secret": "x" * 40,
        "webhook_signing_secret": "y" * 40,
        "jwt_dev_secret": "z" * 40,
        "supabase_url": "https://project.supabase.co",
        "checkout_success_url": "https://app.example.com/ok",
        "checkout_cancel_url": "https://app.example.com/no",
        "billing_portal_return_url": "https://app.example.com/account",
    }
    base.update(overrides)
    return Settings(**base)


def test_staging_can_run_without_stripe_at_all():
    """A deployment that converts images but cannot sell them is a useful
    thing to have before Stripe exists — otherwise the first deploy is
    blocked on a payments account."""
    _staging_settings(payments_enabled=False).check()


def test_production_may_never_disable_payments():
    """A live site that silently cannot take money is not a mode anyone
    wants to discover by accident."""
    with pytest.raises(RuntimeError, match="never in production"):
        _staging_settings(environment="prod", payments_enabled=False).check()


def test_staging_with_payments_on_still_demands_stripe():
    with pytest.raises(RuntimeError, match="VEC_STRIPE_SECRET_KEY"):
        _staging_settings(payments_enabled=True).check()


def test_checkout_refuses_cleanly_when_payments_are_off(client, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setenv("VEC_PAYMENTS_ENABLED", "0")
    settings.cache_clear()
    try:
        response = client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
        assert response.status_code == 503
        assert response.json()["error_code"] == "billing_unavailable"
    finally:
        settings.cache_clear()
