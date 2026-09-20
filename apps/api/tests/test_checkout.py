"""§10 — starting a purchase.

Stripe is stubbed. What is being tested is *our* half: that a checkout
session carries the metadata the webhook needs, that a customer is created
once and reused, that the return URL cannot be pointed somewhere else, and
above all that **starting a checkout grants nothing** — credits come from
the webhook, because a browser coming back from Stripe says the browser
came back, not that the payment settled.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import billing, credits
from app.catalog import CATALOG
from app.models import User


class FakeStripe:
    """Records what we asked Stripe to do, and answers plausibly."""

    def __init__(self) -> None:
        self.customers: list[dict[str, Any]] = []
        self.sessions: list[dict[str, Any]] = []
        self.portals: list[dict[str, Any]] = []
        self.api_key = ""

        outer = self

        class Customer:
            @staticmethod
            def create(**params: Any) -> dict[str, Any]:
                record = {"id": f"cus_{len(outer.customers) + 1}", **params}
                outer.customers.append(record)
                return record

        class CheckoutSessionApi:
            @staticmethod
            def create(**params: Any) -> dict[str, Any]:
                record = {
                    "id": f"cs_{len(outer.sessions) + 1}",
                    "url": f"https://checkout.stripe.test/{len(outer.sessions) + 1}",
                    **params,
                }
                outer.sessions.append(record)
                return record

        # Named apart from the attribute: inside a class body, `X = X` makes
        # X local to that body and the lookup skips the enclosing function
        # scope entirely, so the obvious spelling raises NameError.
        class Checkout:
            Session = CheckoutSessionApi

        class PortalSessionApi:
            @staticmethod
            def create(**params: Any) -> dict[str, Any]:
                record = {"url": "https://billing.stripe.test/portal", **params}
                outer.portals.append(record)
                return record

        class BillingPortal:
            Session = PortalSessionApi

        self.Customer = Customer
        self.checkout = Checkout
        self.billing_portal = BillingPortal


@pytest.fixture()
def stripe(tmp_env, monkeypatch):
    fake = FakeStripe()
    cfg = billing.settings()
    monkeypatch.setattr(cfg, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(
        cfg,
        "stripe_prices",
        {plan: f"price_{plan}" for plan in CATALOG},
    )
    monkeypatch.setattr(billing, "_client", lambda: fake)
    return fake


def test_checkout_returns_a_stripe_url(client, auth, user, stripe):
    response = client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("https://checkout.stripe.test/")


def test_checkout_grants_nothing_on_its_own(client, auth, user, stripe, session):
    """The whole point. Credits come from the webhook, not the redirect."""
    client.post("/v1/checkout", json={"plan": "pro"}, headers=auth)
    session.expire_all()
    assert credits.balance(session, user.id) == 0

    account = client.get("/v1/account", headers=auth).json()
    assert account["plan"] == "starter"  # unchanged by starting a checkout


def test_the_session_carries_what_the_webhook_needs(client, auth, user, stripe):
    client.post("/v1/checkout", json={"plan": "starter"}, headers=auth)
    created = stripe.sessions[-1]
    assert created["metadata"]["plan"] == "starter"
    assert created["metadata"]["user_id"] == user.id
    assert created["client_reference_id"] == user.id
    # The subscription carries it too: invoice.paid on renewal arrives with
    # the subscription, not with the original checkout session.
    assert created["subscription_data"]["metadata"]["plan"] == "starter"


def test_a_pack_is_a_one_off_payment_not_a_subscription(client, auth, user, stripe):
    client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    created = stripe.sessions[-1]
    assert created["mode"] == "payment"
    assert created["payment_intent_data"]["metadata"]["credits"] == "50"


def test_a_plan_is_a_subscription(client, auth, user, stripe):
    client.post("/v1/checkout", json={"plan": "pro"}, headers=auth)
    assert stripe.sessions[-1]["mode"] == "subscription"


def test_stripe_tax_is_on(client, auth, user, stripe):
    """§10 asks for it, and retrofitting tax after the first sale is painful."""
    client.post("/v1/checkout", json={"plan": "starter"}, headers=auth)
    assert stripe.sessions[-1]["automatic_tax"] == {"enabled": True}


def test_the_customer_is_created_once_and_reused(client, auth, user, stripe, session):
    client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    client.post("/v1/checkout", json={"plan": "starter"}, headers=auth)
    assert len(stripe.customers) == 1
    session.expire_all()
    assert session.get(User, user.id).stripe_customer_id == "cus_1"


def test_an_unknown_plan_is_rejected(client, auth, user, stripe):
    response = client.post("/v1/checkout", json={"plan": "enterprise"}, headers=auth)
    assert response.status_code == 400
    assert response.json()["error_code"] == "unknown_plan"


def test_a_return_url_must_point_at_this_site(client, auth, user, stripe):
    """success_url comes back as a redirect the browser follows after
    paying: unchecked, it is an open redirect wearing a payment flow's
    credibility."""
    response = client.post(
        "/v1/checkout",
        json={"plan": "pack", "return_to": "https://phishing.example/collect"},
        headers=auth,
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "bad_return_url"


def test_a_return_url_on_this_site_is_allowed(client, auth, user, stripe):
    from app.config import settings

    base = settings().checkout_success_url.rsplit("/", 1)[0]
    response = client.post(
        "/v1/checkout",
        json={"plan": "pack", "return_to": f"{base}/back-to-my-job"},
        headers=auth,
    )
    assert response.status_code == 200
    assert stripe.sessions[-1]["success_url"].endswith("/back-to-my-job")


def test_a_frozen_account_cannot_buy_more(client, auth, user, stripe, session):
    user.plan = "frozen"
    session.commit()
    response = client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    assert response.status_code == 403


def test_checkout_requires_sign_in(client, stripe):
    assert client.post("/v1/checkout", json={"plan": "pack"}).status_code == 401


def test_billing_unavailable_is_503_not_500(client, auth, user, tmp_env, monkeypatch):
    """Nothing is broken; Stripe is simply not configured here."""
    monkeypatch.setattr(billing.settings(), "stripe_secret_key", "")
    response = client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    assert response.status_code == 503
    assert response.json()["error_code"] == "billing_unavailable"


def test_the_portal_needs_a_prior_purchase(client, auth, user, stripe):
    response = client.post("/v1/billing/portal", headers=auth)
    assert response.status_code == 409
    assert response.json()["error_code"] == "no_billing_account"


def test_the_portal_returns_a_stripe_url(client, auth, user, stripe, session):
    user.stripe_customer_id = "cus_existing"
    session.commit()
    response = client.post("/v1/billing/portal", headers=auth)
    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://billing.stripe.test/portal"


def test_the_public_price_list_matches_what_is_charged(client):
    listed = {p["id"]: p for p in client.get("/v1/plans").json()}
    assert listed["pack"]["amount"] == 900
    assert listed["pack"]["credits"] == 50
    assert listed["starter"]["amount"] == 1200
    assert listed["pro"]["amount"] == 2900
    for plan, item in CATALOG.items():
        assert listed[plan]["amount"] == item.amount
        assert listed[plan]["credits"] == item.credits


def test_checkout_then_webhook_is_what_actually_grants(client, auth, user, stripe, session):
    """The full shape: start a checkout, then deliver the event Stripe would
    send. Only the second step moves the balance."""
    client.post("/v1/checkout", json={"plan": "pack"}, headers=auth)
    session.expire_all()
    assert credits.balance(session, user.id) == 0

    created = stripe.sessions[-1]
    client.post(
        "/v1/stripe/webhook",
        json={
            "id": "evt_pack_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": created["customer"],
                    "mode": "payment",
                    "metadata": created["metadata"],
                }
            },
        },
    )
    session.expire_all()
    assert credits.balance(session, user.id) == 50
