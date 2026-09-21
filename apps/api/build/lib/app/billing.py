"""Stripe: customers, Checkout sessions, and the billing portal.

The API is the ledger's only writer (§2), so it is also the only thing that
talks to Stripe. The web app never holds a Stripe key of any kind —
**hosted Checkout** means the server creates a session and the browser is
redirected to the URL Stripe returns, so there is nothing Stripe-shaped in
the bundle at all.

Nothing here grants credits. Purchases become credits only when the
matching webhook arrives and maps to a grant (§10), because a redirect back
from Stripe is a statement about the browser, not about whether the payment
settled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app import errors
from app.catalog import Product, product
from app.config import settings
from app.models import User

log = logging.getLogger("vectorize.api.billing")


class BillingUnavailable(Exception):
    """Stripe is not configured. A 503, not a 500: nothing is broken."""


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


def _client() -> Any:
    cfg = settings()
    if not cfg.payments_enabled:
        raise BillingUnavailable("payments are disabled in this environment")
    if not cfg.stripe_secret_key:
        raise BillingUnavailable("VEC_STRIPE_SECRET_KEY is not set")
    import stripe

    stripe.api_key = cfg.stripe_secret_key
    return stripe


def price_id(plan: str) -> str:
    """The Stripe price for a plan, from config.

    Prices are created once by `scripts/bootstrap_stripe.py` and referenced
    by id, never looked up by name: a lookup would silently pick a
    duplicate the first time someone makes one in the dashboard.
    """
    configured = settings().stripe_prices.get(plan, "")
    if not configured:
        raise BillingUnavailable(
            f"no Stripe price configured for {plan!r} — "
            "run scripts/bootstrap_stripe.py and set VEC_STRIPE_PRICES"
        )
    return configured


def ensure_customer(session: Session, user: User) -> str:
    """Return this user's Stripe customer id, creating it if needed.

    The link is stored on our side so a second checkout does not create a
    second customer — which would split their payment history and their
    saved cards across two records that look identical in the dashboard.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    stripe = _client()
    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": user.id},
        # Stripe Tax needs somewhere to start; it refines this from the
        # address collected at checkout.
        tax={"validate_location": "deferred"},
    )
    user.stripe_customer_id = customer["id"]
    session.flush()
    return str(customer["id"])


def create_checkout_session(
    session: Session,
    user: User,
    plan: str,
    *,
    success_url: str,
    cancel_url: str,
    idempotency_key: str | None = None,
) -> CheckoutSession:
    item: Product | None = product(plan)
    if item is None:
        raise errors.bad_image(f"no such plan: {plan}", "unknown_plan")

    stripe = _client()
    customer_id = ensure_customer(session, user)

    # The plan travels on the *session*, the subscription and the payment
    # intent. The webhook reads it back from whichever object the event
    # carries, and an event without it cannot be turned into a grant.
    metadata = {"plan": item.id, "user_id": user.id, "credits": str(item.credits)}

    params: dict[str, Any] = {
        "customer": customer_id,
        "line_items": [{"price": price_id(item.id), "quantity": 1}],
        "mode": "subscription" if item.is_subscription else "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
        "client_reference_id": user.id,
        # §10: Stripe Tax on, multi-currency presentment on.
        "automatic_tax": {"enabled": True},
        "customer_update": {"address": "auto", "name": "auto"},
        "allow_promotion_codes": True,
    }
    if item.is_subscription:
        params["subscription_data"] = {"metadata": metadata}
    else:
        params["payment_intent_data"] = {"metadata": metadata}

    created = stripe.checkout.Session.create(
        **params,
        # A double-clicked button must not create two checkouts.
        idempotency_key=idempotency_key,
    )
    log.info("checkout session %s for user %s plan %s", created["id"], user.id, item.id)
    return CheckoutSession(id=str(created["id"]), url=str(created["url"]))


def create_portal_session(session: Session, user: User, *, return_url: str) -> str:
    """Stripe's own billing portal: cards, invoices, cancellation.

    Deliberately not rebuilt in our UI. Card details and dunning are a
    compliance surface, and Stripe already operates one.
    """
    stripe = _client()
    customer_id = ensure_customer(session, user)
    portal = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url
    )
    return str(portal["url"])
