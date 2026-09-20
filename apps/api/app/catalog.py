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
    #: API requests per minute for a key on this plan. A limit exists on
    #: every plan, including free: an unmetered key is a way to spend our
    #: CPU budget by accident (§8).
    rate_per_minute: int
    #: Whether jobs may continue past a zero balance and be billed after
    #: the fact. Only the API plan, because only it has a usage price.
    allows_overage: bool = False

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
        rate_per_minute=30,
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
        rate_per_minute=60,
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
        rate_per_minute=120,
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
        rate_per_minute=300,
        allows_overage=True,
    ),
}

#: What a purchase grants, keyed the way the webhook handlers expect.
PLAN_CREDITS: dict[str, int] = {p.id: p.credits for p in CATALOG.values() if p.is_subscription}
PACK_CREDITS: int = CATALOG["pack"].credits


#: The free tier is not purchasable, but it still needs limits.
FREE = Product(
    id="free",
    name="Free",
    kind="pack",
    amount=0,
    currency="usd",
    credits=3,
    description="Watermarked previews, 3 downloads a month, one file at a time.",
    batch_limit=1,
    rate_per_minute=10,
)

#: Cents per credit once a plan's monthly allowance is exhausted (§10).
OVERAGE_UNIT_CENTS = 4

#: §8: hard-cap overage at this multiple of the plan's monthly price,
#: "so nobody gets a surprise $4,000 invoice". A runaway loop against the
#: API is not a hypothetical — it is the default failure mode of a retry
#: with no ceiling.
OVERAGE_CAP_MULTIPLE = 3


def product(plan: str) -> Product | None:
    return CATALOG.get(plan)


def plan_for(plan: str) -> Product:
    """The plan a user is on, falling back to free.

    Never raises: an unrecognised plan string (a rename, a frozen account)
    must still get *some* limit rather than an unmetered one.
    """
    return CATALOG.get(plan, FREE)


def overage_cap_credits(plan: str) -> int:
    """How many credits of overage a plan may run up before we stop it."""
    item = plan_for(plan)
    if not item.allows_overage:
        return 0
    return (item.amount * OVERAGE_CAP_MULTIPLE) // OVERAGE_UNIT_CENTS


def purchasable() -> list[Product]:
    """Everything a customer can buy. `free` is not a product."""
    return list(CATALOG.values())
