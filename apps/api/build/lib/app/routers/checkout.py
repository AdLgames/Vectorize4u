"""§10 — starting a purchase.

Two endpoints, both of which only ever hand back a Stripe URL to redirect
to. **Neither grants anything.** Credits appear when the webhook arrives
and maps to a grant: a browser coming back from Stripe says the browser
came back, not that the payment settled, and treating the redirect as proof
is how people end up with credits they did not pay for.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import errors
from app.auth import Principal, required_principal
from app.billing import BillingUnavailable, create_checkout_session, create_portal_session
from app.catalog import purchasable
from app.config import settings
from app.db import get_session

router = APIRouter(prefix="/v1", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str
    #: Optional override, so a cut-intent page can return the buyer to the
    #: job they were looking at rather than to a generic success page.
    return_to: str | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PlanView(BaseModel):
    id: str
    name: str
    kind: str
    amount: int
    currency: str
    credits: int
    description: str
    batch_limit: int


class PortalResponse(BaseModel):
    portal_url: str


@router.get("/plans", response_model=list[PlanView])
def plans() -> list[PlanView]:
    """The price list, served from the same source checkout charges from.

    The web app renders its own copy for speed and for SEO, but this is
    what a client should trust — and what a test can compare against, so a
    marketing page quietly drifting away from the real price is catchable.
    """
    return [
        PlanView(
            id=p.id,
            name=p.name,
            kind=p.kind,
            amount=p.amount,
            currency=p.currency,
            credits=p.credits,
            description=p.description,
            batch_limit=p.batch_limit,
        )
        for p in purchasable()
    ]


def _safe_return_url(candidate: str | None, fallback: str) -> str:
    """Only allow returns to our own site.

    `success_url` goes to Stripe and comes back as a redirect the browser
    follows after paying. An unchecked value here is an open redirect with
    a payment flow's credibility attached to it.
    """
    if not candidate:
        return fallback
    from urllib.parse import urlparse

    allowed = urlparse(fallback)
    target = urlparse(candidate)
    if target.scheme != allowed.scheme or target.netloc != allowed.netloc:
        raise errors.bad_image("return_to must point at this site", "bad_return_url")
    return candidate


@router.post("/checkout", response_model=CheckoutResponse)
def checkout(
    body: CheckoutRequest,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckoutResponse:
    cfg = settings()
    user = principal.user
    assert user is not None

    if user.plan == "frozen":
        # A disputed account does not get to buy more while under review.
        raise errors.forbidden("this account is on hold pending review")

    try:
        created = create_checkout_session(
            session,
            user,
            body.plan,
            success_url=_safe_return_url(body.return_to, cfg.checkout_success_url),
            cancel_url=cfg.checkout_cancel_url,
            idempotency_key=idempotency_key,
        )
    except BillingUnavailable as exc:
        raise errors.ProblemError(503, "billing_unavailable", str(exc)) from exc

    return CheckoutResponse(checkout_url=created.url, session_id=created.id)


@router.post("/billing/portal", response_model=PortalResponse)
def portal(
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> PortalResponse:
    user = principal.user
    assert user is not None
    if not user.stripe_customer_id:
        raise errors.conflict("no_billing_account", "this account has never made a purchase")
    try:
        url = create_portal_session(
            session, user, return_url=settings().billing_portal_return_url
        )
    except BillingUnavailable as exc:
        raise errors.ProblemError(503, "billing_unavailable", str(exc)) from exc
    return PortalResponse(portal_url=url)
