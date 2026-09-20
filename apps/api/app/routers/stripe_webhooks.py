"""§10 — Stripe webhooks, received by FastAPI because it is the ledger's
only writer (§2). Two backends writing one ledger is how drift happens.

Every event maps to **grant operations**, never to a direct balance edit.
Signatures are verified, and events are deduped on `stripe_event_id`
uniqueness because Stripe redelivers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credits, errors
from app.config import settings
from app.db import get_session
from app.models import CreditGrant, StripeEvent, Subscription, User, utcnow

router = APIRouter(prefix="/v1", tags=["billing"])

# §10 pricing. Formats are never tier-gated on paid plans: DXF is the reason
# cutters show up, and gating it behind Pro contradicts §0.
PLAN_CREDITS = {"starter": 100, "pro": 1000, "api": 500}
PACK_CREDITS = 50

HANDLED = {
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "charge.refunded",
    "charge.dispute.created",
}


def _verify(payload: bytes, signature: str | None) -> dict[str, Any]:
    cfg = settings()
    if not cfg.stripe_webhook_secret:
        if cfg.is_production:  # pragma: no cover - blocked by Settings.check()
            raise errors.forbidden("stripe webhook secret is not configured")
        # Dev/test: accept the body as-is so the mapping can be tested
        # without Stripe's SDK in the loop.
        import json

        return dict(json.loads(payload))
    import stripe

    try:
        return dict(
            stripe.Webhook.construct_event(payload, signature or "", cfg.stripe_webhook_secret)
        )
    except Exception as exc:
        raise errors.forbidden(f"invalid stripe signature: {exc}") from exc


def _user_for(session: Session, customer_id: str | None, email: str | None) -> User | None:
    if customer_id:
        user = session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        ).scalar_one_or_none()
        if user is not None:
            return user
    if email:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is not None and customer_id and not user.stripe_customer_id:
            user.stripe_customer_id = customer_id
        return user
    return None


@router.post("/stripe/webhook", status_code=200)
async def stripe_webhook(
    request: Request,
    session: Session = Depends(get_session),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, str]:
    event = _verify(await request.body(), stripe_signature)
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")

    if not event_id:
        raise errors.bad_image("event has no id", "bad_event")

    # Dedupe. A replay must not grant a second month of credit.
    if session.get(StripeEvent, event_id) is not None:
        return {"status": "duplicate"}
    session.add(StripeEvent(id=event_id, type=event_type))

    if event_type not in HANDLED:
        return {"status": "ignored"}

    obj = (event.get("data") or {}).get("object") or {}
    customer_id = obj.get("customer")
    email = (obj.get("customer_details") or {}).get("email") or obj.get("receipt_email")
    user = _user_for(session, customer_id, email)
    if user is None:
        # Nothing to attribute this to. Recorded as seen so it is not
        # retried forever; surfaced for manual reconciliation.
        return {"status": "unattributed"}

    handler = {
        "checkout.session.completed": _checkout_completed,
        "invoice.paid": _invoice_paid,
        "invoice.payment_failed": _payment_failed,
        "customer.subscription.updated": _subscription_updated,
        "customer.subscription.deleted": _subscription_deleted,
        "charge.refunded": _charge_refunded,
        "charge.dispute.created": _dispute_created,
    }[event_type]

    handler(session, user, obj, event_id)
    session.flush()
    return {"status": "ok"}


def _plan_of(obj: dict[str, Any]) -> str:
    metadata = obj.get("metadata") or {}
    return str(metadata.get("plan") or obj.get("plan") or "starter")


def _checkout_completed(
    session: Session, user: User, obj: dict[str, Any], event_id: str
) -> None:
    mode = obj.get("mode")
    if mode == "payment":
        # One-off credit pack: never expires. This tier is the one clear gap
        # in the competitor's line-up and most traffic is a person with a
        # single logo who will never subscribe (§10).
        amount = int((obj.get("metadata") or {}).get("credits") or PACK_CREDITS)
        credits.grant(
            session, user.id, source="pack", amount=amount,
            expires_at=None, stripe_event_id=event_id,
        )
        return

    plan = _plan_of(obj)
    user.plan = plan
    _grant_plan_credits(session, user, plan, event_id)


def _invoice_paid(session: Session, user: User, obj: dict[str, Any], event_id: str) -> None:
    plan = _plan_of(obj) if obj.get("metadata") else user.plan
    if plan == "free":
        return
    _grant_plan_credits(session, user, plan, event_id)


def _grant_plan_credits(session: Session, user: User, plan: str, event_id: str) -> None:
    amount = PLAN_CREDITS.get(plan)
    if not amount:
        return
    if plan == "api":
        # API credits do not expire while the subscription is active, but
        # roll over at most 3× the monthly amount (§5).
        credits.grant(
            session, user.id, source="api_monthly", amount=amount,
            expires_at=None, stripe_event_id=event_id,
        )
        credits.apply_api_rollover_cap(session, user.id, amount)
    else:
        credits.grant(
            session, user.id, source="plan_monthly", amount=amount,
            expires_at=credits.period_end(), stripe_event_id=event_id,
        )


def _payment_failed(session: Session, user: User, obj: dict[str, Any], event_id: str) -> None:
    """`past_due` suspends new unlocks (§10). Existing credits are untouched."""
    record = _subscription_row(session, user, obj)
    if record is not None:
        record.status = "past_due"
    user.plan = "free"


def _subscription_updated(
    session: Session, user: User, obj: dict[str, Any], event_id: str
) -> None:
    record = _subscription_row(session, user, obj)
    status = str(obj.get("status") or "active")
    plan = _plan_of(obj)
    if record is None:
        record = Subscription(
            user_id=user.id,
            stripe_subscription_id=str(obj.get("id") or f"sub_{event_id}"),
            plan=plan,
            status=status,
        )
        session.add(record)
    record.status = status
    record.plan = plan
    record.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    user.plan = plan if status in ("active", "trialing") else "free"


def _subscription_deleted(
    session: Session, user: User, obj: dict[str, Any], event_id: str
) -> None:
    record = _subscription_row(session, user, obj)
    if record is not None:
        record.status = "canceled"
    user.plan = "free"
    # Plan grants lapse at period end on their own; nothing is clawed back.
    credits.expire_lapsed(session, user.id)


def _charge_refunded(session: Session, user: User, obj: dict[str, Any], event_id: str) -> None:
    """Reverse the unspent part of that purchase's grant (§5).

    If it was already spent, the account is flagged for review rather than
    driven negative.
    """
    source_event = (obj.get("metadata") or {}).get("grant_event_id")
    stmt = select(CreditGrant).where(CreditGrant.user_id == user.id)
    if source_event:
        stmt = stmt.where(CreditGrant.stripe_event_id == source_event)
    else:
        stmt = stmt.where(CreditGrant.source == "pack").order_by(CreditGrant.created_at.desc())
    record = session.execute(stmt).scalars().first()
    if record is None:
        return
    credits.refund(session, user.id, grant_id=record.id, stripe_event_id=event_id)


def _dispute_created(session: Session, user: User, obj: dict[str, Any], event_id: str) -> None:
    """A dispute freezes the account pending review (§10)."""
    user.plan = "frozen"
    record = _subscription_row(session, user, obj)
    if record is not None:
        record.status = "disputed"
        record.updated_at = utcnow()


def _subscription_row(
    session: Session, user: User, obj: dict[str, Any]
) -> Subscription | None:
    subscription_id = obj.get("subscription") or obj.get("id")
    if not subscription_id:
        return None
    return session.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == str(subscription_id)
        )
    ).scalar_one_or_none()
