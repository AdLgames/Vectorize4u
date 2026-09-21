# Turning payments on

`docs/first-deploy.md` says to run `make stripe-bootstrap`, which assumes a
terminal. This is the same thing from Actions, because the deployment it
configures was driven from a phone and there is no reason payments should
be the one step that needs a laptop.

Nothing here can be done by accident. The stage is opt-in by name, is
never part of `everything`, and refuses a live key outright unless the run
says `confirm_live: yes`.

## Test mode first

1. Stripe dashboard, **Test mode toggle on** → Developers → API keys →
   copy the secret key (`sk_test_…`).
2. Put it in the `VEC_STRIPE_SECRET_KEY` repository secret.
3. Actions → Deploy → Run workflow, **stage: `stripe`**, with `site` set
   to your site.
4. Then **stage: `deploy`**. Staged secrets only reach the machines on a
   deploy, so payments are not on until this runs.
5. Actions → Verify the site, with `payments: yes`.

## What the stripe stage does

It runs `apps/api/scripts/bootstrap_stripe.py`, which is idempotent, and
then hands the results to the API itself — no price ids to copy between
a log and a settings page.

- **Products and prices**, from `app/catalog.py`, tagged with
  `vectorize_plan` metadata so a re-run finds what it made last time
  rather than creating a second $12 Starter that looks identical in the
  dashboard. Prices are immutable in Stripe: changing an amount means a
  new price and repointing at it, which is why this is a script and not
  a dashboard task.
- **The webhook endpoint**, at `https://<api>.fly.dev/v1/stripe/webhook`,
  subscribed to exactly the events the handler handles — imported from
  the handler, so an endpoint cannot end up subscribed to an event
  nothing handles, or missing one that would silently drop paid work.
- **The secrets**: the key, the price ids, the signing secret, the three
  return URLs (derived from `site`, because the startup check refuses
  production while they still say `localhost`), and finally
  `VEC_PAYMENTS_ENABLED=1` — last, so a failure earlier leaves payments
  off rather than half on.

The signing secret is written to a file and read by the workflow, never
printed. Stripe returns it **only when the endpoint is created**, which
makes re-runs delicate, so the stage decides before it creates anything:

- **The API already holds a signing secret** → any existing endpoint is
  left exactly as it is. Deleting one that is in use stops every paid
  event, and the first sign would be a customer who paid and got nothing.
- **The API holds none** → an existing endpoint is replaced. Its secret is
  unrecoverable, so it can never verify anything; replacing it costs
  nothing and is the only way to obtain a secret without a human in a
  dashboard.

That second case is not hypothetical — it is the state a half-finished
run leaves behind, with the endpoint created and its secret lost to the
error that followed.

## What the check can and cannot prove

`scripts/verify_payments.py` establishes everything that must be true
before a purchase can succeed: payments reported on, the site's prices
matching what the API charges, checkout refusing an anonymous caller, and
the webhook refusing an unsigned event — an endpoint that accepts one
grants credits to anybody who can reach the URL.

It cannot buy anything. `/v1/checkout` needs a session and a card belongs
to a person, so the last step is yours: sign in, pick a plan, and pay with
Stripe's test card `4242 4242 4242 4242` and any future expiry. The
credits are granted by the webhook, so they should be there by the time
the success page has loaded. If they are not, the webhook is the place to
look — Stripe → Developers → Webhooks shows every delivery and its
response.

## Then live

Same three steps with the live key, plus `confirm_live: yes`. Before that:

- Switch `VEC_ENVIRONMENT` from `"staging"` to `"prod"` in the four
  `infra/*.toml` files. The two harden identically; the only difference is
  that `prod` refuses to run with payments disabled, so it cannot be left
  half-configured.
- Stripe Tax (Dashboard → Tax) and the currencies you want presented, or
  non-US buyers see USD only.
- A real domain, and the API's CORS narrowed to it.

The startup check lists everything missing or unsafe in one message, so a
half-finished live switch fails at boot rather than at the first customer.
