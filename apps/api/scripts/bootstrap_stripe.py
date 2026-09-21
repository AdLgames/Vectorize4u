"""Create this product's Stripe products and prices, idempotently.

Run it once per Stripe environment (test, then live):

    VEC_STRIPE_SECRET_KEY=sk_test_... python scripts/bootstrap_stripe.py

It prints the `VEC_STRIPE_PRICES` line to paste into your env. Actions
runs it too (`.github/workflows/deploy.yml`, the `stripe` stage), because
"open a terminal" is not a step everyone can take — so it can also
register the webhook endpoint and write what it made to a file with
`--emit`, which is how the workflow sets the Fly secrets without a
signing secret ever passing through a log or a clipboard.

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
from app.config import settings  # noqa: E402

TAG = "vectorize_plan"


def client():  # type: ignore[no-untyped-def]
    # Via settings, not os.environ, so `apps/api/.env` works here exactly
    # as it does for the service — otherwise the key has to be exported
    # separately and the two disagree about which account you are on.
    key = settings().stripe_secret_key or os.environ.get("VEC_STRIPE_SECRET_KEY", "")
    if not key:
        print(
            "VEC_STRIPE_SECRET_KEY is not set.\n"
            "Put it in apps/api/.env or export it, then run this again.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    import stripe

    stripe.api_key = key
    return stripe, key.startswith("sk_live_")


def fields(obj) -> dict:  # type: ignore[no-untyped-def]
    """A Stripe resource as a plain dict.

    stripe-python resources support `obj["x"]` but *not* `obj.get("x")` —
    the latter raises, telling you to call `.to_dict()`. That distinction
    cost a run of the stripe stage, after it had already created every
    product, price and the webhook endpoint.
    """
    to_dict = getattr(obj, "to_dict", None)
    return to_dict() if callable(to_dict) else dict(obj)


def find_product(stripe, plan: str):  # type: ignore[no-untyped-def]
    for product in stripe.Product.search(query=f'metadata["{TAG}"]:"{plan}"').auto_paging_iter():
        return product
    return None


def find_price(stripe, product_id: str, item: Product):  # type: ignore[no-untyped-def]
    for price in stripe.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        recurring = fields(price).get("recurring")
        wants_recurring = item.is_subscription
        if bool(recurring) != wants_recurring:
            continue
        if price["unit_amount"] == item.amount and price["currency"] == item.currency:
            return price
    return None


def ensure_webhook(stripe, url: str, *, recreate: bool = False) -> tuple[str, str | None]:  # type: ignore[no-untyped-def]
    """Register the endpoint, subscribed to exactly the events we handle.

    Imported from the handler rather than restated: an endpoint subscribed
    to an event nothing handles is noise, and one missing an event we do
    handle silently drops paid work.

    Stripe returns a signing secret only when the endpoint is *created*.
    So an endpoint that already exists is left exactly as it is, and the
    caller is told there is no secret to collect — rolling it is a
    decision that breaks the running deployment until the new value is
    set, which is not something to do unasked.
    """
    from app.routers.stripe_webhooks import HANDLED

    events = sorted(HANDLED)
    for endpoint in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if endpoint["url"] == url:
            if recreate:
                # Only when the caller has established that nothing holds
                # this endpoint's secret — an endpoint whose secret is lost
                # verifies nothing, so replacing it costs nothing, and it is
                # the only way to obtain a secret without a human in a
                # dashboard. Deleting one that *is* in use would silently
                # stop every paid event, so the decision is never made here.
                stripe.WebhookEndpoint.delete(endpoint["id"])
                print(f"  replaced webhook {endpoint['id']} (its secret was unrecoverable)")
                break
            have = fields(endpoint).get("enabled_events") or []
            missing = sorted(set(events) - set(have))
            if missing:
                stripe.WebhookEndpoint.modify(endpoint["id"], enabled_events=events)
                print(f"  updated webhook  {endpoint['id']} (added {', '.join(missing)})")
            else:
                print(f"  found webhook    {endpoint['id']}")
            return endpoint["id"], None

    created = stripe.WebhookEndpoint.create(
        url=url,
        enabled_events=events,
        description="Vectorize4u — created by scripts/bootstrap_stripe.py",
    )
    print(f"  created webhook  {created['id']} ({len(events)} events)")
    return created["id"], fields(created).get("secret")


def main() -> int:
    try:
        return _run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - this is a CLI, not a library
        name = type(exc).__name__
        if "Auth" in name or "Permission" in name:
            print(
                f"\nStripe rejected the key ({name}). Check you copied the whole "
                "secret key, and that it is the one for the account you meant.",
                file=sys.stderr,
            )
        elif "Connection" in name:
            print(
                f"\nCould not reach Stripe ({name}). Check your network or proxy "
                "and run it again — nothing was created.",
                file=sys.stderr,
            )
        else:
            print(f"\n{name}: {exc}", file=sys.stderr)
        return 1


def _run() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create this product's Stripe objects")
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("VEC_STRIPE_WEBHOOK_URL", ""),
        help="register a webhook endpoint at this URL, e.g. https://api.example/v1/stripe/webhook",
    )
    parser.add_argument(
        "--recreate-webhook",
        action="store_true",
        help="replace an existing endpoint at that URL. Only pass this when "
        "nothing holds its signing secret: Stripe returns one at creation only, "
        "so an endpoint whose secret was lost can never be used again.",
    )
    parser.add_argument(
        "--emit",
        default="",
        help="write what was made to this JSON file. Use it rather than reading "
        "stdout: the webhook signing secret goes in here and must not reach a log.",
    )
    args = parser.parse_args()

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

    price_line = json.dumps(prices, sort_keys=True, separators=(",", ":"))

    webhook_secret: str | None = None
    if args.webhook_url:
        print()
        _, webhook_secret = ensure_webhook(stripe, args.webhook_url, recreate=args.recreate_webhook)
        if webhook_secret is None:
            print(
                "  (that endpoint already existed, so Stripe did not hand back its\n"
                "   signing secret — Stripe only returns it at creation. If the\n"
                "   deployment does not have VEC_STRIPE_WEBHOOK_SECRET, roll it in\n"
                "   the dashboard and set the new value.)"
            )

    if args.emit:
        # Not stdout: the signing secret is in here.
        payload = {"mode": "live" if is_live else "test", "prices": prices}
        if webhook_secret:
            payload["webhook_secret"] = webhook_secret
        Path(args.emit).write_text(json.dumps(payload))
        print(f"\nwrote {args.emit}")

    print("\nAdd this to your environment:\n")
    print(f"VEC_STRIPE_PRICES={price_line}")

    if is_live:
        print(
            "\nLive mode: switch on Stripe Tax (Dashboard -> Tax) and enable the "
            "currencies you want presented, or non-US buyers see USD only."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
