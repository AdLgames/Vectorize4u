# infra — deploying this

Two images and five apps: the API, three worker lanes, and the web app on
Vercel. Everything here is declarative and checked by
`apps/api/tests/test_deployment.py`, which is what stops the pinned tracer
versions, the queue lanes and the retention windows drifting apart from the
code that assumes them.

**These files have not been run against a real Fly account.** They are
correct as far as they can be checked without one — the invariants are
tested, the versions match CI, the Dockerfiles install what the engine
imports — but the first `fly deploy` will still be the first time flyctl
sees them. Budget an afternoon, not five minutes.

## What has to exist first

| Thing | Why | Notes |
|---|---|---|
| Cloudflare R2 bucket | Sources and outputs | Zero egress. Get the S3-compatible endpoint and a scoped key pair |
| Postgres | The ledger, jobs, idempotency | Fly Postgres or any managed instance. One writer: the API |
| Redis | Celery broker | **Fixed-price, on the private network.** Celery polls constantly, so per-command pricing bills you for idling |
| Supabase project | Auth | Only the anon key ever reaches the browser |
| Stripe account | Money | `make stripe-bootstrap` creates the products and prices |

## Secrets

Set on every app that needs them (`fly secrets set -a <app> KEY=value`).
The API refuses to start in production if any of these still holds its
development default — see `Settings.check()`, which fails at boot rather
than at the first paid request.

```
VEC_DATABASE_URL          postgresql+psycopg://…
VEC_REDIS_URL             redis://…               # private network address
VEC_R2_BUCKET             vectorize
VEC_R2_ENDPOINT_URL       https://<account>.r2.cloudflarestorage.com
VEC_R2_ACCESS_KEY_ID      …
VEC_R2_SECRET_ACCESS_KEY  …
VEC_SUPABASE_URL          https://<project>.supabase.co
VEC_STRIPE_SECRET_KEY     sk_live_…               # API only
VEC_STRIPE_WEBHOOK_SECRET whsec_…                 # API only
VEC_IP_HASH_SECRET        <32+ random bytes>
VEC_WEBHOOK_SIGNING_SECRET <32+ random bytes>
VEC_PUBLIC_API_URL        https://api.example.com
VEC_ALERT_WEBHOOK_URL     https://hooks.slack.com/services/…   # §8 cost alerts
```

`VEC_IP_HASH_SECRET` does **not** need a rotation job: `ratelimit.ip_hash`
mixes the UTC date into the key, so the effective secret changes every day
on its own. It does need to be a real random value — a plain hash of an
IPv4 address is brute-forceable in seconds, and a guessable secret is the
same thing.

## Order of operations

```sh
make images            # build both images locally first — a broken build
                       # is cheaper to find here than in a deploy
make deploy-api        # runs `alembic upgrade head` as its release command
make deploy-workers    # all three lanes
make r2-lifecycle      # check the retention backstop; --apply writes it
```

Then, once:

```sh
cd apps/api && python ../../infra/r2_lifecycle.py --apply
fly scale count worker=2 -c infra/fly.worker-batch.toml
```

## The five things this deployment must get right

1. **Three worker pools, not one.** `make worker` consumes all three lanes
   locally for convenience. In production each lane is its own Fly app with
   its own `QUEUES`, and the image *refuses to start* without one — a
   worker that quietly took every queue would pass every test and break
   §4.2's guarantee that a 500-file batch never delays a preview. The
   batch pool is scaled manually and deliberately, because an uncapped
   batch pool is the same failure with extra steps.

2. **Pinned tracers.** `infra/tracers.env` holds the versions; the worker
   image and both CI workflows read the same numbers, and a test fails if
   they diverge. A tracer bump changes output geometry, which moves every
   benchmark score — so after a bump, re-run `make bench` and regenerate
   the baseline in the same change, or the next regression is unattributable.

3. **`potrace` is GPLv2.** It is installed as a binary and invoked as a
   subprocess; it is never linked and never imported. Read
   `docs/licensing.md` before changing how it gets into the image.

4. **R2 lifecycle rules are the retention backstop.** `free/` at 2 days,
   `paid/` at 31 — one day longer than the promise in each case, so the
   sweeper does the deleting and the bucket only catches what a dead
   sweeper missed. `infra/r2_lifecycle.py --check` reports the live state;
   a test fails if someone raises the retention settings without raising
   these windows, because the bucket deleting first would mean handing out
   signed URLs for objects that are already gone.

5. **Verify the sandbox on the host.** The worker logs `sandbox_mode()`,
   the tracer versions and the lanes it is actually consuming at startup.
   Read that on the first deploy: cgroup control inside a Firecracker VM is
   exactly the thing not to assume, and `rlimit-only` means the process
   limits are the whole isolation story.

## Not covered here

- **Cost alerting is built but has no destination by default.** The daily
  check runs on the batch lane and logs; set `VEC_ALERT_WEBHOOK_URL` to a
  Slack incoming webhook to have it say so somewhere a person will see.


- **The web app** is a Vercel project pointed at `apps/web`, with
  `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_SITE_URL` and the Supabase anon key
  set. Uploads never pass through it (§4.3), so its 4.5 MB body limit does
  not matter.
- **A CDN in front of outputs** is deliberately absent. Every output is a
  unique file downloaded once, so there is no hit rate to win, and a
  path-keyed cache would serve deleted files past their retention — which
  is the one promise the buyers under NDA actually care about.
