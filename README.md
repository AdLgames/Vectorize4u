# Raster → Vector

A scored parameter search around off-the-shelf tracers, built to the
specification in [`VECTORIZER_SPEC_V3.md`](VECTORIZER_SPEC_V3.md).

The product thesis is in §0 of that file and constrains everything here: the
competitor is Vectorizer.AI, not `vtracer`, and we do not win on raw trace
quality alone. We win on batch workflow, cut-correctness (physical scale,
node spacing, cutter-safe DXF) and an honest, exposed quality score.

## What is built

**The engine** (`/packages/engine`) — Phases 0 and 1. A pure library with no
web dependencies.

**The service** (`/apps/api`, `/apps/worker`) — Phase 2. FastAPI owns all of
`/v1`, the credit ledger, Stripe webhooks and the migrations; Celery runs the
engine on three separate queue lanes.

**The web app** (`/apps/web`) — Phase 3. Next.js 15: drag-and-drop converter
with a zoomable preview slider, batch grid, and the two SEO landing pages
§9 requires at this phase.

**[docs/getting-started.md](docs/getting-started.md) walks through it from
a clone to a test card turning into credits** — about 20 minutes, no money.
The short version:

```bash
make setup setup-service     # Python side
cd apps/web && npm install   # web side
cargo install vtracer resvg  # the tracers; plus potrace from your package manager
make api                     # terminal 1 — API with the worker inline
make web                     # terminal 2 — Next.js
make e2e                     # terminal 3 — drive it in a real browser
```

Sign-in is Supabase magic link. With no Supabase project configured those
two targets fall back to a local development sign-in, so a fresh clone is a
working app rather than a sign-in wall — see `docs/runbook.md` for the real
setup and for why that fallback cannot reach production.

The engine on its own:

```bash
make setup
cargo install vtracer resvg && apt-get install potrace
make check                       # lint, typecheck, 100 tests
make bench                       # per-category means + regression gate
python -m engine logo.png out.svg --width 120 --units mm --format dxf --json
```

It ingests PNG/JPEG/WEBP/BMP/GIF/TIFF/HEIC, classifies the image, cleans it,
traces 1–8 candidate parameter vectors in parallel subprocesses, scores each
one against the *cleaned reference* with SSIM + ΔE2000 + dilated-edge F1 +
alpha IoU + node/path penalties, post-processes the winner and emits SVG,
DXF, PDF, EPS or PNG at a physical size the user specified.

See [`docs/architecture.md`](docs/architecture.md) for the decisions that
are load-bearing, and [`docs/runbook.md`](docs/runbook.md) for how to run,
tune and debug it.

## The guarantees, and where they are enforced

| Promise | Enforced by | Tested by |
|---|---|---|
| No vector output for a job that is not unlocked | `app/jobs.py: visible_outputs`, raster preview tiles | `test_locked_job_never_exposes_vector_output` |
| Credits rebuild exactly from the ledger | `app/credits.py` | every test in `test_credits.py` |
| One charge per source image | unique `(root_job_id, reason)` | `test_second_unlock_of_the_same_image_is_free` |
| A retried POST creates one job and one charge | `Idempotency-Key` | `test_idempotency_creates_one_job_and_one_charge` |
| Failed jobs are never billed | `worker/tasks.py: _fail` | `test_failed_job_is_never_billed` |
| `{url}` cannot reach internal services | `app/fetcher.py` | 25 cases in `test_fetcher.py` |
| Deleted jobs are unreachable immediately | `app/retention.py` | `test_delete_purges_immediately` |
| A session cannot be forged, replayed or downgraded | `app/auth.py` | 17 cases in `test_auth_supabase.py` |
| Starting a checkout grants nothing; the webhook does | `app/routers/checkout.py` | `test_checkout_grants_nothing_on_its_own` |
| LCP < 2.0s, CLS < 0.05, Lighthouse ≥ 95 | `lighthouserc.json` | measured: 99/100/96/100, LCP 1.9s, CLS 0 |

## What is not built

Phases 5–8 beyond batch: the public API product (keys exist; docs and
overage caps do not), SEO expansion, and the Phase 8 refinement loop.

One step remains before money can move: **Stripe has never run against a
real account.** Checkout, the billing portal and the price list are built
and tested against a stub, and `make stripe-bootstrap` creates the products
and prices — but it needs your keys. Test mode is enough, and is free.
See `docs/runbook.md`.

## The evidence, not the metric

`make bench` grades our own selector against our own metric. It detects
regressions; it is **not** evidence the product is good — selecting by a
metric and then reporting that metric is circular.

The evidence is the blind A/B in §12: randomised pairs voted by people who
did not write the code, gated at **≥ 70%** against a single default
`vtracer` call.

```bash
make ab          # builds the voting page
make ab-report   # applies the kill switch
```

The owner reports this vote has been run and passed, which is why
development continued past Phase 0. The votes file is not in the repository
yet — commit `benchmarks/ab/votes.json` so the number is auditable, and
re-run the vote whenever `score_version` or the presets change.
