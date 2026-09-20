"""The price list, in one place.

§10's decision lives here as data: Free, a $9 one-off credit pack, Starter
at $12 and Pro at $29. The pack is the lead offer — most traffic is a
person with one logo who will never subscribe, and it is the one clear gap
in the competitor's line-up.

Three things have to agree about what a plan costs and grants: this file,
Stripe, and the pricing section in the web app. This is the source of
truth; `scripts/bootstrap_stripe.py` pushes it into Stripe, and the plan
metadata on every Stripe object points back at the ids used here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["subscription", "pack"]


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    kind: Kind
    #: Cents, in the presentment currency Stripe is configured for.
    amount: int
    currency: str
    #: Credits granted per purchase or per billing period.
    credits: int
    description: str
    batch_limit: int

    @property
    def is_subscription(self) -> bool:
        return self.kind == "subscription"


CATALOG: dict[str, Product] = {
    "pack": Product(
        id="pack",
        name="Credit pack",
        kind="pack",
        amount=900,
        currency="usd",
        credits=50,
        description="50 downloads that never expire. Every format, including DXF.",
        batch_limit=1,
    ),
    "starter": Product(
        id="starter",
        name="Starter",
        kind="subscription",
        amount=1200,
        currency="usd",
        credits=100,
        description="100 downloads a month, every format, batches up to 25 files.",
        batch_limit=25,
    ),
    "pro": Product(
        id="pro",
        name="Pro",
        kind="subscription",
        amount=2900,
        currency="usd",
        credits=1000,
        description="1,000 downloads a month, batches up to 500, priority queue.",
        batch_limit=500,
    ),
    "api": Product(
        id="api",
        name="API",
        kind="subscription",
        amount=2900,
        currency="usd",
        credits=500,
        description="500 API credits a month, rolling over up to 3x.",
        batch_limit=500,
    ),
}

#: What a purchase grants, keyed the way the webhook handlers expect.
PLAN_CREDITS: dict[str, int] = {
    p.id: p.credits for p in CATALOG.values() if p.is_subscription
}
PACK_CREDITS: int = CATALOG["pack"].credits


def product(plan: str) -> Product | None:
    return CATALOG.get(plan)


def purchasable() -> list[Product]:
    """Everything a customer can buy. `free` is not a product."""
    return list(CATALOG.values())
