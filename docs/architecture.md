# Architecture

What exists today, and how the pieces that do not yet exist attach to it.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Weekend kill test: flat logos, scored search, `make ab` | **Built.** The kill switch has not been *run* — that needs 2–3 humans (see below). |
| 1 | Full engine: all classes, potrace, post-processing, physical size, corpus, `make bench` gate | **Built**, against a synthetic corpus. Calibration is provisional until real images land. |
| 2 | Service: `/v1`, three queue lanes, presigned uploads, SSRF rules, retention | **Built.** Runs on SQLite + local storage for dev and tests; Postgres + R2 + Redis in production. |
| 3 | Web app + SEO foundation | **Built.** Converter, tile preview, slider, advanced panel, batch grid, `/png-to-svg`, `/convert-for-cricut`, sitemap, JSON-LD, Lighthouse budget. Auth is stubbed — see below. |
| 4 | Money | **Partly built.** Grants, ledger, unlock and the Stripe event → grant mapping are done and tested. The §10 pricing decision is still open, and there is no checkout UI. |
| 5–8 | Batch polish, API product, SEO expansion, refinement | Batch and webhooks are built; the rest not started. |

## The engine (`/packages/engine`)

A pure library. No web framework, no database, no cloud SDK — it must stay
testable and benchmarkable offline, and it is the only part of the product
that is not a commodity.

```
ingest → analyse → preprocess → candidates → trace → score → select
       → post-process → emit
```

The loop is **outside** the tracer. Candidates are always scored against
the reference pixels derived from the original, never against a previous
trace: re-vectorizing a trace compounds quantization error and rounds
corners further on every pass. There is no iteration count at which it
improves.

| Module | Responsibility |
|---|---|
| `ingest.py` | Magic bytes, size guards, EXIF transpose **then** strip, ICC/CMYK → sRGB, un-premultiply |
| `analyse.py` | `ImageProfile` — statistics only, no pixels, so it survives file deletion |
| `classify.py` | Rule thresholds, one unit test per class |
| `preprocess.py` | The `reference` / `trace_input` split |
| `presets.py` | Classification-conditioned candidate sets, always incl. a universal fallback |
| `trace.py` | vtracer + potrace as subprocesses, in parallel |
| `sandbox.py` | rlimits, network isolation, timeouts, and the 400/500 error split |
| `raster.py` | `resvg` — the same renderer the service will use for preview tiles |
| `score.py` | Six normalised terms; `fidelity` vs `total`; `score_version` |
| `postprocess.py` | Slivers, simplification, node spacing, colour snapping, grouping |
| `emit.py` | Physical size resolution; SVG/DXF/PDF/EPS/PNG |
| `pipeline.py` | Orchestration, timings, job deadline |

### Decisions worth knowing before changing anything

**`total` selects, `fidelity` stops.** The node and path penalties exist to
stop the scorer always picking the highest-detail trace: a 50,000-node SVG
scores best on pure SSIM and is useless on a cutting machine. Every
post-processing stop rule therefore uses `fidelity`, because `total` *rises*
as nodes fall and would hide the damage.

**Colour grouping never reorders paths.** Tracer output is stacked: later
paths cover earlier ones. Collecting every path of one colour into one group
changes what covers what. Groups are built from consecutive runs instead.
This already caused one silent corruption; `test_serialize_never_reorders_paths`
exists to stop it recurring.

**`flat_color_ratio`, not `unique_colors`.** A re-compressed JPEG of a
four-colour logo reports nine thousand colours. The fraction of pixels
sitting within ΔE2000 < 4 of the image's own palette does not care.

**De-artifacting needs two signals.** DCT blockiness alone fires on
hard-edged synthetic art, so the filter also requires a lossy source format.
A PNG that was never JPEG-encoded has no artifacts to remove; filtering it
just softens the customer's logo.

**Physical size comes from the user.** Metadata DPI is untrusted unless it
is present *and* not a 72/96 writer default. A 400 px logo has no meaningful
DPI, and a confidently wrong size is the one failure a cutter user cannot
recover from.

## The service (`/apps/api`, `/apps/worker`)

Per §2 the API owns **all** of `/v1`, the credit ledger, Stripe webhooks and
the Alembic migrations — one writer for money and jobs, because two backends
writing one ledger is how drift happens. The worker runs the engine on three
separate Celery queues so a 500-file batch cannot starve an interactive
preview. The web app is UI only.

### Decisions worth knowing before changing anything

**Credits are ledger-derived.** `credit_grants.remaining` and
`users.credits_cached` are projections. `credits.rebuild_projections`
recomputes both from `credit_ledger` alone, and every ledger test asserts the
rebuild matches what was stored. If they ever disagree, the ledger is right.

**Consumption order is soonest-expiring first.** Spending a never-expiring
pack while a plan grant is days from lapsing silently destroys credit the
customer paid for.

**One charge per source image.** A tweak from the advanced panel is a child
job sharing its parent's `root_job_id`, and the unique `(root_job_id, reason)`
constraint on the ledger makes the second unlock free rather than a second
charge.

**The unlock gate is server-side and absolute.** `jobs.visible_outputs`
filters every vector format out of the response until `unlocked_at` is set,
and the preview endpoint returns watermarked *raster tiles* rendered by
resvg. An `<svg>` in the DOM is the download, watermark or not.

**Storage prefixes are the retention backstop.** Free work is written under
`free/`, paid under `paid/`, chosen at write time. The R2 lifecycle rules key
on those prefixes, so a dead sweeper cannot break the retention promise —
which is the exact guarantee a print shop under NDA is buying.

**The delivery cap is not optional.** Late acks plus requeue-on-worker-loss
means an image that kills its worker is redelivered forever. The counter in
`worker.tasks._deliveries` bounds it at three, after which the job is failed
and rejected without requeue.

### Running it without any infrastructure

`VEC_STORAGE_BACKEND=local` plus a SQLite URL plus `VEC_INLINE_WORKER=1` runs
the entire request path — upload, trace, score, tile, unlock, download — in
one process with no Postgres, no Redis and no cloud credentials. That is how
the test suite runs, which is why the tests exercise the real engine rather
than a mock.

## The web app (`/apps/web`)

UI only: no business logic, no database access. Uploads go straight to
storage with a presigned PUT and never pass through the Next.js server —
Vercel caps request bodies around 4.5 MB and a 25 MB logo is an ordinary
input.

The preview is the product demo, so the slider zooms to 800% and both sides
are raster: the left is a server-rendered tile of the trace, the right is the
user's original. Zoom in and the original pixelates while the vector stays
sharp.

Two bugs the browser smoke test caught on its first run, both invisible to
unit tests and to the type checker:

- Tailwind's preflight sets `img { max-width: 100% }`, which squashed the
  preview tile to its container's width while leaving the height alone. The
  comparison was distorted and still looked plausible.
- On zoom, the browser stretched the previous low-resolution tile while the
  new one rendered, so the vector appeared to pixelate — the exact opposite
  of the point the slider exists to make. There is now a "Sharpening…" state.

`apps/web/e2e/smoke.mjs` is kept for that reason.

### Measured, not assumed

Lighthouse against the production build of `/png-to-svg`, on this container:
performance 99, accessibility 100, best practices 96, SEO 100; LCP 1.9 s,
CLS 0, TBT 90 ms. §9's budget is LCP < 2.0 s, CLS < 0.05 and every category
at 95 or better, and `lighthouserc.json` asserts exactly that in CI.

## Evidence

`make bench` grades our own selector, so it can only detect regressions — it
is not evidence the product is good. Selecting by a metric and then reporting
that metric is circular. The evidence is `make ab`: blind, randomised pairs
voted by people who did not write the code, gated at ≥70% vs a single default
`vtracer` call (§12) and ≥80% for the definition of done (§13).

**That vote has not been run.** It needs humans, and it is the cheapest way
to find out whether any of this should continue.

## What is stubbed

**Authentication.** The API verifies a JWT against the provider's JWKS and
accepts `sk_live_...` API keys; both paths are real and tested. The web app
holds `token` as a `useState(null)` placeholder, so signed-in flows (unlock,
batch, account) show their sign-in prompt rather than working end to end.
Wiring Clerk or Supabase Auth is a Phase 4 task and touches one value in
three components.

**Checkout.** Stripe events map to grants and are tested; there is no
checkout page, because §10's pricing decision is still open and the page
depends on the answer.
