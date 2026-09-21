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
    """Stripe is not configured, or refused the request.

    A 503, not a 500: nothing here is broken, something upstream is not
    ready. Stripe's own rejections belong in this class too — they are
    almost always account configuration ("you have not enabled Stripe
    Tax"), and letting one escape as an unhandled 500 replaced an
    actionable sentence with "an internal error occurred".
    """


def _stripe_error(exc: Exception) -> BillingUnavailable:
    """Stripe's message, which is written for the account holder.

    Not an internal detail: these say things like "You cannot use
    automatic_tax[enabled]=true because you have not enabled Stripe Tax",
    which is the entire fix. Hiding it leaves the owner with nothing.
    """
    message = getattr(exc, "user_message", None) or str(exc)
    return BillingUnavailable(f"Stripe refused this: {message}")


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
    try:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": user.id},
            # Stripe Tax needs somewhere to start; it refines this from the
            # address collected at checkout.
            tax={"validate_location": "deferred"},
        )
    except Exception as exc:  # noqa: BLE001 - a 503, like every other Stripe refusal
        log.warning("could not create a Stripe customer for %s: %s", user.id, exc)
        raise _stripe_error(exc) from exc
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

    try:
        created = stripe.checkout.Session.create(
            **params,
            # A double-clicked button must not create two checkouts.
            idempotency_key=idempotency_key,
        )
    except Exception as exc:  # noqa: BLE001 - every Stripe failure is a 503 here
        log.warning("checkout session refused for user %s: %s", user.id, exc)
        raise _stripe_error(exc) from exc
    log.info("checkout session %s for user %s plan %s", created["id"], user.id, item.id)
    return CheckoutSession(id=str(created["id"]), url=str(created["url"]))


def create_portal_session(session: Session, user: User, *, return_url: str) -> str:
    """Stripe's own billing portal: cards, invoices, cancellation.

    Deliberately not rebuilt in our UI. Card details and dunning are a
    compliance surface, and Stripe already operates one.
    """
    stripe = _client()
    customer_id = ensure_customer(session, user)
    try:
        portal = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    except Exception as exc:  # noqa: BLE001
        # The portal has its own configuration step in the dashboard, and
        # says so when it is missing. That sentence is the fix.
        log.warning("billing portal refused for user %s: %s", user.id, exc)
        raise _stripe_error(exc) from exc
    return str(portal["url"])
