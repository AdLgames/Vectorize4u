# Deploying without a terminal

Everything in `docs/first-deploy.md` assumes a laptop with `flyctl`. This
is the same deployment driven entirely from a browser — which also means
the only place the Fly credential ever exists is this repository's
secrets, not a shell history and not a chat window.

## Once: four things to create

| Where | What | What you need from it |
|---|---|---|
| fly.io | An account | An API token: **User → Access Tokens → Create** |
| Cloudflare R2 | A bucket named `vectorize` | Bucket name, S3 endpoint, access key id, secret |
| Supabase | A free project | Its URL only. The anon key belongs to the web app |
| GitHub | This repository | Nothing — you are already here |

## Once: the repository secrets

**Settings → Secrets and variables → Actions → New repository secret**, six
times:

| Name | Value |
|---|---|
| `FLY_API_TOKEN` | the Fly token |
| `R2_BUCKET` | `vectorize` |
| `R2_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | from R2 |
| `R2_SECRET_ACCESS_KEY` | from R2 |
| `SUPABASE_URL` | `https://<project>.supabase.co` |

That is the whole list. The three secrets that are ours rather than a
vendor's — the IP hash key, the webhook signing key, the JWT secret — are
generated during bootstrap and set on every app at once, because a
signing key that differs between two apps is a silent, intermittent
failure and not something anyone should be typing by hand.

## Do not use Fly's own launch wizard

`fly launch`, and the "deploy from GitHub" flow in Fly's dashboard, exist
to take one repository and make one app out of it. This is five apps, and
three of them are the same image with different `QUEUES` — the whole point
of §4.2 is that batch work runs somewhere a preview is not. A wizard
cannot infer that, and if it guesses it will produce one app that consumes
every lane, which passes every test and breaks the one guarantee the
product sells.

It will also fail before it gets that far, with:

```
Could not find a Dockerfile, nor detect a runtime or framework from source code.
```

There *is* now a `Dockerfile` at the root — it builds the API — so
detection works. But the wizard still only knows how to make one app.
Use the workflow below instead.

## Then: run it

**Actions → Deploy → Run workflow.** It asks for a region, an
organisation and a name prefix — the defaults are already the ones this
account uses. Four stages, in order, because they fail differently and
you want to know which one broke:

1. **`bootstrap`** — creates the five apps, the Postgres cluster and the
   Redis machine, attaches the database to each app, generates the
   secrets. Safe to re-run; everything in it checks first.
2. **`secrets`** — writes configuration to all four apps.
3. **`deploy`** — builds both images, ships the API (running
   `alembic upgrade head` as its release command) and the three worker
   lanes, then curls `/health` and fails if it does not answer.
4. **`verify`** — converts a real image end to end against whatever is
   live: `scripts/verify_live.py` asks for an upload slot, PUTs the bytes
   to R2, starts an anonymous preview, waits for the job and fetches the
   watermarked tile. It runs automatically at the end of `deploy`, and is
   selectable on its own because the question after a settings change is
   "does it still work?" and answering that should not need a redeploy.

`everything` runs all four in sequence. Prefer the stages the first time.

`/health` is a much weaker claim than it looks: it answers before the
worker has consumed a job, before R2 has accepted a byte and before any
tracer binary has been exec'd. `verify` is the stage that fails when one
of those is wrong, and it names which one.

## Then: payments, later

Nothing above involves Stripe. The API runs with `VEC_PAYMENTS_ENABLED=0`,
`/v1/checkout` answers 503, and everything else — conversion, preview,
accounts, batch — works. That is a site that cannot sell yet, rather than
a site that will not boot.

When Stripe exists, add these repository secrets and re-run `secrets`:

- `VEC_STRIPE_SECRET_KEY`
- `VEC_STRIPE_WEBHOOK_SECRET`
- `VEC_STRIPE_PRICES` (the line `make stripe-bootstrap` prints)
- `VEC_CHECKOUT_SUCCESS_URL`, `VEC_CHECKOUT_CANCEL_URL`,
  `VEC_BILLING_PORTAL_RETURN_URL`

Their presence is what turns payments on. In the same change, edit
`VEC_ENVIRONMENT` from `"staging"` to `"prod"` in the four `infra/*.toml`
files: the two harden identically, and the only difference is that
`prod` refuses to run with payments disabled.

## When something fails

The Actions log is the whole story, and it is readable on a phone. The two
likely failures:

- **`make images` equivalent fails in the deploy stage.** A missing system
  library in `infra/Dockerfile.worker`. The log names it.
- **The API boots and dies.** Its startup check lists every missing or
  unsafe setting at once — that message is the checklist, not a puzzle.
- **`verify` hangs with the job in `queued`.** Nothing is consuming
  `queue_preview`: either the worker app has no running machine, or it
  cannot reach Redis. `flyctl logs -a <prefix>-worker`.
- **`verify` fails on the presigned PUT.** The R2 credentials or the
  bucket name, not the code. Re-run `secrets` after fixing them.

`flyctl logs -a vectorize-api` is the follow-up, and fly.io's dashboard
shows the same logs in a browser.
