# Getting it running, end to end

From a clone to a card payment turning into credits on your machine.
Nothing here costs money: Stripe test mode is free and needs no business
details or bank account.

Roughly 20 minutes, most of it waiting on installs.

---

## 1. Prerequisites

- **Python 3.11+** and **Node 20+**
- **Rust toolchain** (`rustup`) — two of the three tracer binaries are
  installed with `cargo`
- **Stripe CLI** — [stripe.com/docs/stripe-cli](https://stripe.com/docs/stripe-cli).
  `brew install stripe/stripe-cli/stripe` on macOS.

## 2. The code

```bash
git clone <this repo>
cd Vectorize4u
git checkout claude/build-product-from-md-l4re45

make setup          # venv + the engine, with dev extras
make setup-service  # the API and the worker
cd apps/web && npm install && cd ../..
```

## 3. The tracer binaries

The engine shells out to three programs. They are not pip-installable.

```bash
cargo install vtracer resvg     # MIT / MPL-2.0
brew install potrace            # macOS.  Linux: sudo apt install potrace
```

`potrace` is GPLv2 and is only ever invoked as a subprocess, never linked —
see `docs/licensing.md`. If you would rather not have it at all, skip it:
line-art jobs fall back to vtracer presets and everything still runs.

Check they are all on your `PATH`:

```bash
vtracer --version && resvg --version && potrace --version
```

## 4. Prove it works before adding Stripe

```bash
make check    # lint, types, ~210 tests
make bench    # per-category quality scores against the corpus
```

Then, in **two terminals**:

```bash
make api      # terminal 1 — API on :8000, worker inline, dev sign-in on
make web      # terminal 2 — Next.js on :3000
```

Open <http://localhost:3000>, drop in any PNG, and you should get a preview
with a quality score. Sign-in at this point is the **development** one: any
address signs you straight in. It is not authentication, it is off by
default, and production refuses to boot with it enabled.

You now have a working app. Everything below is about taking money.

---

## 5. Stripe, in test mode

### 5a. Get the keys

1. Create a Stripe account at <https://dashboard.stripe.com/register>.
   You do **not** need to complete business verification for test mode.
2. **Developers → API keys** → reveal and copy the **Secret key**. It
   starts with `sk_test_`.

Create `apps/api/.env`:

```bash
cp apps/api/.env.example apps/api/.env
```

and set:

```
VEC_STRIPE_SECRET_KEY=sk_test_...
```

> Never paste a **live** key (`sk_live_…`) into a repository, a chat, or a
> container. Test keys on your own machine are fine.

### 5b. Create the products

```bash
make stripe-bootstrap
```

It creates four products and prints a line to paste back into
`apps/api/.env`:

```
VEC_STRIPE_PRICES={"api":"price_...","pack":"price_...","pro":"price_...","starter":"price_..."}
```

| Plan | Billing | Price | Grants |
|---|---|---|---|
| `pack` | one-off | $9 | 50 credits, never expire |
| `starter` | monthly | $12 | 100 credits/month |
| `pro` | monthly | $29 | 1,000 credits/month |
| `api` | monthly | $29 | 500 credits/month (Phase 6; nothing sells it yet) |

Re-running is safe: every object is tagged, so it finds what it made rather
than creating duplicates.

### 5c. Forward the webhooks

**This is the step people skip, and skipping it means payments never become
credits.** A purchase grants nothing until the webhook arrives.

In a **third terminal**:

```bash
stripe login
stripe listen --forward-to 127.0.0.1:8000/v1/stripe/webhook
```

It prints `Ready! Your webhook signing secret is whsec_...`. Put that in
`apps/api/.env`:

```
VEC_STRIPE_WEBHOOK_SECRET=whsec_...
```

Leave `stripe listen` running for as long as you are testing.

### 5d. Restart the API

`apps/api/.env` is read at startup. Stop `make api` and start it again.

---

## 6. Buy something

1. <http://localhost:3000> → **Buy 50 credits**.
2. Sign in (any address — development sign-in).
3. Stripe's checkout page: card **4242 4242 4242 4242**, any future expiry,
   any CVC, any postcode.
4. You land back on `/checkout/success`, which waits for the webhook and
   then shows your new balance.
5. Watch the `stripe listen` terminal — you should see
   `checkout.session.completed` forwarded and answered `200`.
6. <http://localhost:3000/account> → the credit pack shows 50/50, never
   expiring.

Convert an image and download it: the balance drops by one, and
re-downloading or taking another format of the same file is free.

### If the credits do not appear

| Symptom | Cause |
|---|---|
| Success page still says "adding your credits" after a minute | `stripe listen` is not running, or the signing secret is missing or stale |
| `stripe listen` shows `400` | `VEC_STRIPE_WEBHOOK_SECRET` does not match the one it printed — it changes each time you start it |
| "Payments aren't switched on yet" | `VEC_STRIPE_SECRET_KEY` is missing, or the API was not restarted after editing `.env` |
| Checkout button does nothing | `VEC_STRIPE_PRICES` is missing that plan |

## 7. Drive the whole thing automatically

With all three terminals running:

```bash
make e2e
```

Three browser suites: the anonymous path, the signed-in path that spends a
credit, and the purchase paths.

---

## 8. Real accounts, later

Two things are deliberately not part of the above, because neither is
needed to see the product work:

**Supabase** replaces the development sign-in. Create a project, add
`http://localhost:3000/auth/callback` to Authentication → URL
Configuration → Redirect URLs, and put the project URL and anon key in
`apps/web/.env.local` plus `VEC_SUPABASE_URL` in `apps/api/.env`. Sign-in
becomes a real magic link. See `docs/runbook.md`.

**Live Stripe** needs business details, a bank account, Stripe Tax switched
on, and your presentment currencies enabled — otherwise non-US buyers only
ever see USD. Re-run `make stripe-bootstrap` against the live key, and
point the three return URLs at your real domain. Production refuses to boot
while they say localhost, or while the secret key is a test key.
