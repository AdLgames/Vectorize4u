"""Prove the deployment can take money, without taking any.

There is no way to make a real purchase from a check: `/v1/checkout` needs
a signed-in session, and a card belongs to a person. What *can* be
established is everything that has to be true before a purchase can
succeed, all of which is configuration and all of which fails quietly:

  * the API reports payments on — the one outward sign that the Stripe
    secrets actually reached the machines, since /v1/plans is served from
    the catalogue and reads identically either way
  * the price list the API charges from matches the price list the site
    advertises, so a marketing page cannot drift away from the real price
  * checkout refuses an anonymous caller with 401 rather than 500
  * the webhook endpoint rejects an unsigned body, because an endpoint
    that accepts one grants credits to anybody who posts to it

    python scripts/verify_payments.py https://vectorize4u.vercel.app \\
        --api https://vectorize4u-api.fly.dev

Standard library only, so it runs on a bare CI runner.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 30.0


class StepFailed(Exception):
    pass


def _request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise StepFailed(f"{method} {url} did not connect: {error.reason}")


def payments_are_on(api: str) -> None:
    status, raw = _request("GET", f"{api}/v1/limits")
    if status != 200:
        raise StepFailed(f"GET /v1/limits answered {status}")
    body = json.loads(raw)
    if "payments_enabled" not in body:
        raise StepFailed(
            "this API is too old to report payments_enabled, so it cannot be "
            "checked from outside. Deploy the current build first."
        )
    if not body["payments_enabled"]:
        raise StepFailed(
            "the API reports payments off, so /v1/checkout answers 503 and nothing "
            "can be bought.\n"
            "      Run the stripe stage, then deploy: staged secrets only reach the "
            "machines on a deploy."
        )
    print("  payments    ok  (the API reports them enabled)")


def plans(api: str) -> list[dict]:
    status, raw = _request("GET", f"{api}/v1/plans")
    if status != 200:
        raise StepFailed(f"GET /v1/plans answered {status}")
    items = json.loads(raw)
    if not items:
        raise StepFailed("the API offers no plans at all")
    shown = ", ".join(
        f"{p['id']} {p['amount'] / 100:.2f} {p['currency'].upper()}" for p in items
    )
    print(f"  plans       ok  ({shown})")
    return items


def site_prices_match(site: str, items: list[dict]) -> None:
    """The pricing page is hand-written copy; the API is the source of truth.

    A price changed in the catalogue and forgotten in the copy is the kind
    of mistake that gets noticed by a customer rather than by us.
    """
    status, raw = _request("GET", site + "/")
    if status != 200:
        raise StepFailed(f"GET / answered {status}")
    html = raw.decode("utf-8", "replace")

    missing = []
    for plan in items:
        if plan["currency"].lower() != "usd":
            continue
        amount = plan["amount"] / 100
        # "$12" and "$12.00" and "$12.50" all count; the copy chooses.
        whole = f"{amount:.0f}" if amount == int(amount) else f"{amount:.2f}"
        patterns = (rf"\${whole}\b", rf"\${amount:.2f}".replace(".", r"\."))
        if not any(re.search(pattern, html) for pattern in patterns):
            missing.append(f"{plan['id']} (${whole})")
    if missing:
        raise StepFailed(
            "the home page does not show the price the API charges for: "
            + ", ".join(missing)
            + ".\n      Either the copy drifted from app/catalog.py, or the page "
            "needs a rebuild."
        )
    print(
        f"  pricing     ok  (the page shows what the API charges, {len(items)} plans)"
    )


def checkout_needs_a_session(api: str) -> None:
    status, raw = _request(
        "POST",
        f"{api}/v1/checkout",
        body=json.dumps({"plan": "pack"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    if status == 500:
        raise StepFailed(
            f"checkout answered 500 for an anonymous caller: {raw[:300]!r}"
        )
    if status == 503:
        raise StepFailed(
            "checkout answered 503, which is what it does when payments are off — "
            "the machines are probably running an older release than the secrets"
        )
    if status != 401:
        raise StepFailed(
            f"expected 401 from an anonymous checkout, got {status}: {raw[:300]!r}"
        )
    print("  checkout    ok  (401 without a session)")


def webhook_rejects_forgery(api: str) -> None:
    """An endpoint that accepts an unsigned body grants credits for free."""
    body = json.dumps(
        {
            "id": "evt_verify_forged",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_forged", "mode": "payment"}},
        }
    ).encode()

    status, raw = _request(
        "POST",
        f"{api}/v1/stripe/webhook",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    if status in (200, 204):
        raise StepFailed(
            "the webhook accepted an unsigned event. Anyone who can reach this URL "
            "can grant themselves credits.\n"
            "      VEC_STRIPE_WEBHOOK_SECRET is missing or the signature check is "
            "not running."
        )
    if status >= 500:
        raise StepFailed(
            f"the webhook answered {status} rather than refusing: {raw[:300]!r}"
        )
    print(f"  webhook     ok  ({status} for an unsigned event)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_url")
    parser.add_argument("--api", required=True)
    args = parser.parse_args()

    site = args.site_url.rstrip("/")
    api = args.api.rstrip("/")
    print(f"verifying payments on {api}, priced against {site}")

    try:
        payments_are_on(api)
        items = plans(api)
        site_prices_match(site, items)
        checkout_needs_a_session(api)
        webhook_rejects_forgery(api)
    except StepFailed as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1

    print(
        "\npayments are configured. What no check can do is buy something:\n"
        "sign in, pick a plan, and use Stripe's test card 4242 4242 4242 4242\n"
        "with any future expiry. The credits should land before the success\n"
        "page finishes loading, because the webhook grants them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
