"""Create this product's Stripe products and prices, idempotently.

Run it once per Stripe environment (test, then live):

    VEC_STRIPE_SECRET_KEY=sk_test_... python scripts/bootstrap_stripe.py

It prints the `VEC_STRIPE_PRICES` line to paste into your env.

Why a script rather than the dashboard:

- **Prices are immutable in Stripe.** Changing $12 to $9 means creating a
  new price and repointing at it; doing that by hand in two environments is
  how test and live drift apart.
- Every object is tagged with `vectorize_plan` metadata, so a re-run finds
  what it made last time instead of creating a second $12 Starter that
  looks identical in the dashboard.
- The amounts come from `app/catalog.py`, which is also what the webhook
  handlers grant against. One source of truth, three consumers.

It never deletes or edits an existing price. If an amount here no longer
matches Stripe, it says so and creates the new price alongside — archiving
the old one is a decision with billing consequences for existing
subscribers, so it stays manual.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog import Product, purchasable  # noqa: E402

TAG = "vectorize_plan"


def client():  # type: ignore[no-untyped-def]
    key = os.environ.get("VEC_STRIPE_SECRET_KEY", "")
    if not key:
        print("VEC_STRIPE_SECRET_KEY is not set", file=sys.stderr)
        raise SystemExit(2)
    import stripe

    stripe.api_key = key
    return stripe, key.startswith("sk_live_")


def find_product(stripe, plan: str):  # type: ignore[no-untyped-def]
    for product in stripe.Product.search(query=f'metadata["{TAG}"]:"{plan}"').auto_paging_iter():
        return product
    return None


def find_price(stripe, product_id: str, item: Product):  # type: ignore[no-untyped-def]
    for price in stripe.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        recurring = price.get("recurring")
        wants_recurring = item.is_subscription
        if bool(recurring) != wants_recurring:
            continue
        if price["unit_amount"] == item.amount and price["currency"] == item.currency:
            return price
    return None


def main() -> int:
    stripe, is_live = client()
    mode = "LIVE" if is_live else "test"
    print(f"Stripe {mode} mode\n")

    prices: dict[str, str] = {}
    for item in purchasable():
        product = find_product(stripe, item.id)
        if product is None:
            product = stripe.Product.create(
                name=f"Vectorize4u {item.name}",
                description=item.description,
                metadata={TAG: item.id, "credits": str(item.credits)},
            )
            print(f"  created product  {item.id:8s} {product['id']}")
        else:
            print(f"  found product    {item.id:8s} {product['id']}")

        price = find_price(stripe, product["id"], item)
        if price is None:
            params = {
                "product": product["id"],
                "unit_amount": item.amount,
                "currency": item.currency,
                "metadata": {TAG: item.id, "credits": str(item.credits)},
                # §10: multi-currency presentment. Stripe converts from this
                # amount for buyers outside the currency below.
                "tax_behavior": "exclusive",
            }
            if item.is_subscription:
                params["recurring"] = {"interval": "month"}
            price = stripe.Price.create(**params)
            print(
                f"  created price    {item.id:8s} {price['id']} "
                f"({item.amount / 100:.2f} {item.currency.upper()})"
            )
        else:
            print(f"  found price      {item.id:8s} {price['id']}")
        prices[item.id] = price["id"]

    import json

    print("\nAdd this to your environment:\n")
    print(f"VEC_STRIPE_PRICES={json.dumps(prices, sort_keys=True, separators=(',', ':'))}")

    if is_live:
        print(
            "\nLive mode: switch on Stripe Tax (Dashboard -> Tax) and enable the "
            "currencies you want presented, or non-US buyers see USD only."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
