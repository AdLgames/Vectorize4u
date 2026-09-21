# The first deploy

Written to be followed in order, by someone with a Fly account and nothing
else set up. You run the commands; the only ones that need judgement are
marked **decide**.

**No terminal?** [docs/deploy-from-github.md](deploy-from-github.md) does
all of this from GitHub's web UI, which works from a phone.

The plan is deliberately in two halves: **get it converting images first,
then add payments.** `VEC_PAYMENTS_ENABLED=0` exists for exactly this —
a staging deployment that works end to end without a Stripe account, so
the first deploy is not blocked on one. It is refused in `prod`.

---

## 0. What you need before starting

- A Fly.io account and `flyctl` installed (`fly auth login`).
- A Cloudflare R2 bucket, plus an S3-compatible endpoint and a key pair
  scoped to it.
- A Supabase project (free tier is fine). You need its URL only — the
  anon key goes in the web app, never here.

Everything else this repository provides.

## 1. Create the apps

```sh
fly apps create vectorize-api
fly apps create vectorize-worker-preview
fly apps create vectorize-worker-sync
fly apps create vectorize-worker-batch
```

**Decide:** a region. `infra/*.toml` all say `lhr`; change them together
if you want somewhere else, and put the database in the same place —
the API talks to Postgres on every request, and cross-region latency here
is felt on every page.

## 2. Postgres and Redis

```sh
fly postgres create --name vectorize-db --region lhr

# Attach once, naming the database and the user explicitly. Both default
# to the name of the app doing the attaching, so attaching the API and
# then the workers gives each of them a separate, empty database — and
# nothing says so. The API migrates and writes a job, the worker connects
# to a different database and raises on a `jobs` table that was never
# created there, and the preview just sits in 'queued' forever.
fly postgres attach vectorize-db -a vectorize-api \
  --database-name vectorize --database-user vectorize

# Redis: a machine we own, not `fly redis create` (that is Upstash, and it
# is metered per command — three idle workers polling all day is a lot of
# commands for no work done). The stronger reason is eviction: a broker
# that evicts silently drops paid jobs, so infra/fly.redis.toml pins
# noeviction and keeps an append-only file on a volume.
fly apps create vectorize-redis
fly volumes create redis_data --size 1 --region lhr -a vectorize-redis
fly deploy -c infra/fly.redis.toml --image redis:7-alpine .
```

The workers reach it at `redis://vectorize-redis.internal:6379/0` — private
network only, never exposed publicly, which is why it has no password.

Note the connection strings. The workers need both; the API needs both.
Set the workers' `DATABASE_URL` to the exact string the attach printed —
one database, one user, shared. Do not attach the workers separately, for
the reason in the comment above; and do not give them a user of their own
either, because table privileges belong to whoever created the tables, so
a second user reaches the right database and is then refused by every
table the migrations made.

## 3. Secrets

Generate the two secrets rather than inventing them:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"   # ip hash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # webhook signing
```

Then, for each of the four apps (`-a vectorize-api`, and each worker):

```sh
fly secrets set -a <app> \
  VEC_DATABASE_URL="postgresql+psycopg://…" \
  VEC_REDIS_URL="redis://…" \
  VEC_R2_BUCKET="vectorize" \
  VEC_R2_ENDPOINT_URL="https://<account>.r2.cloudflarestorage.com" \
  VEC_R2_ACCESS_KEY_ID="…" \
  VEC_R2_SECRET_ACCESS_KEY="…" \
  VEC_SUPABASE_URL="https://<project>.supabase.co" \
  VEC_IP_HASH_SECRET="…" \
  VEC_WEBHOOK_SIGNING_SECRET="…" \
  VEC_JWT_DEV_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  VEC_PAYMENTS_ENABLED="0"
```

The API also needs `VEC_PUBLIC_API_URL="https://vectorize-api.fly.dev"`.

`VEC_JWT_DEV_SECRET` is not used when payments and Supabase are configured,
but the startup check refuses its development default — set it to anything
random and forget it.

`VEC_IP_HASH_SECRET` needs no rotation job: `ratelimit.ip_hash` mixes the
UTC date into the key, so it rotates daily on its own.

## 4. Build the images locally first

```sh
make images
```

The API's image is the `Dockerfile` at the repository root — that name and
that place, so build detection finds it. The worker's is
`infra/Dockerfile.worker`: it carries the three tracer binaries, and it is
never the image a detector should reach for by default.

A broken build is much cheaper to find here than inside a deploy. This is
also the step that has never run in CI, so expect it to be where a missing
system library shows up; the fix is a line in `infra/Dockerfile.*`.

## 5. Deploy the API

```sh
make deploy-api
```

This runs `alembic upgrade head` as its release command — once per deploy,
in its own machine, before any new machine takes traffic.

**Expect the startup check to fail the first time** if anything above is
missing. It fails loudly and lists everything at once, for example:

```
unsafe configuration: VEC_STORAGE_BACKEND must be 'r2' in production;
R2 bucket/endpoint are not configured; VEC_IP_HASH_SECRET still holds its
development default; …
```

That message is the checklist. Fix, redeploy.

Then:

```sh
curl -fsS https://vectorize-api.fly.dev/health
```

## 6. Deploy the three worker lanes

```sh
make deploy-workers
fly scale count worker=2 -c infra/fly.worker-batch.toml
```

Read the first worker's startup log. It prints three things that are
properties of the host rather than the code, and all three are assumptions
made everywhere else:

```
worker lanes: queue_preview
sandbox mode: unshare          # or bwrap, or rlimit-only
tracer vtracer: visioncortex VTracer 0.6.5 (/usr/local/bin/vtracer)
```

`rlimit-only` means process limits are the whole isolation story — worth
knowing, and not worth blocking on. `worker lanes` showing more than one
queue on a machine means the `QUEUES` env did not take, and §4.2's promise
is gone.

## 7. The retention backstop

```sh
cd apps/api && python ../../infra/r2_lifecycle.py --apply
```

This is what keeps "we delete your files after 24 hours" true when the
sweeper is dead. `--check` reports the live state.

## 8. Prove it works

```sh
# a real conversion, end to end
curl -X POST https://vectorize-api.fly.dev/v1/vectorize/multipart \
  -F "file=@benchmarks/corpus/logo_flat.png" \
  -F 'options={"format":["svg"]}'
```

Anonymous previews are free and rate-limited, so this should come back
with a score and a preview URL, and no vector output — that is the unlock
gate doing its job.

Then deploy the web app to Vercel, pointed at `apps/web`, with
`NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_SITE_URL` and the Supabase **anon**
key. Uploads never pass through it (§4.3), so its 4.5 MB body cap does not
matter.

## 9. Only now, payments

```sh
# test mode first; nothing here touches live money
cd apps/api && cp .env.example .env    # add VEC_STRIPE_SECRET_KEY=sk_test_…
make stripe-bootstrap                   # creates products and prices
```

`make stripe-bootstrap` prints the price ids. Set them, turn payments on,
and redeploy:

```sh
fly secrets set -a vectorize-api \
  VEC_PAYMENTS_ENABLED="1" \
  VEC_STRIPE_SECRET_KEY="sk_live_…" \
  VEC_STRIPE_WEBHOOK_SECRET="whsec_…" \
  VEC_STRIPE_PRICES='{"pack":"price_…","starter":"price_…","pro":"price_…","api":"price_…"}' \
  VEC_CHECKOUT_SUCCESS_URL="https://yourdomain/checkout/success" \
  VEC_CHECKOUT_CANCEL_URL="https://yourdomain/#pricing" \
  VEC_BILLING_PORTAL_RETURN_URL="https://yourdomain/account"
```

The webhook endpoint to register in Stripe is
`https://vectorize-api.fly.dev/v1/stripe/webhook`. **Starting a checkout
grants nothing; the webhook does** — so if credits never arrive, that
registration is the first thing to check.

## What to watch in the first week

- `worker lanes` in each worker's log, after every deploy.
- The daily cost check (§8). It logs by default; set
  `VEC_ALERT_WEBHOOK_URL` to a Slack incoming webhook to have it reach a
  person.
- `python infra/r2_lifecycle.py --check`, once, a week in — the backstop is
  the kind of thing that is either configured or silently is not.
