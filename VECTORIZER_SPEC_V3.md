# Raster → Vector SaaS — Build Specification v3

**Audience:** Claude Code (or any engineer) implementing this from scratch.
**Status:** Greenfield. Nothing exists yet.
**Read this whole file before writing code. Build in the phase order in §12.**

> **v3 changelog** (review fixes applied to v2):
> - **Strategy:** kill switch replaced with a blind human A/B (the v2 test could not
>   fail); Vectorizer.AI named as the real competitor; SEO clock starts in Phase 3;
>   new weekend-sized Phase 0.
> - **Engine:** scoring compares against a *cleaned reference*, not the raw source;
>   all score terms normalised and the node-penalty bug fixed; `fidelity` split from
>   `total`; physical size comes from the user, not `source_dpi`; premultiplied-alpha
>   detection rewritten; EXIF orientation and ICC/CMYK handling added; post-process
>   order made implementable.
> - **Service:** the SVG never reaches the browser before unlock (raster tile
>   preview); presigned direct-to-R2 uploads; SSRF rules for `{url}`;
>   `Idempotency-Key`; single owner for `/v1` and the ledger; Celery poison-pill cap;
>   both tracers run as subprocesses; fixed-price Redis.
> - **Money/data:** credit *grants* with expiry and consumption order; more Stripe
>   events; `profile`, `engine_version`, `score_version` and behaviour events
>   persisted so the dataset survives file deletion.
> - **Housekeeping:** cross-references fixed, DXF gating contradiction removed,
>   preview limits stated once, embroidery claim scoped, gradient strategy stated.
>
> **Carried from v2 — deliberately not adopted:** CDN edge-auth caching of user
> outputs, query-string-insensitive cache keys, immutable year-long cache headers
> (all §8), ClickHouse (§5), and unqualified spot instances (§4.2). Reasons are
> recorded inline at those sections so nobody re-adds them from memory.

---

## 0. Product thesis (read first — it constrains every technical decision)

This is not "an SVG converter." A converter is a commodity: `vtracer` is free, and
Illustrator has Image Trace built in. Nobody pays for a wrapper around a free binary.

**The real competitor is Vectorizer.AI**, not vtracer: an ML-based tracer selling
unlimited web downloads for about $9.99/month, with SVG/PDF/EPS/DXF export and an
API. Assume its raw trace quality on clean logos is at least as good as ours. We
therefore do not win on "quality" alone. We win on:

- **Batch workflow** — hundreds of files, server-persisted, per-file retry.
- **Cut-correctness** — physical scale, node spacing, cutter-safe DXF. Output that
  *works on the machine*, not just output that looks right on screen.
- **Transparency** — an exposed quality score and honest warnings.
- **Quality that is visibly better than free tools** (the entry ticket, not the moat).

Buyers — people who vectorize repeatedly for money:

- Print-on-demand / Etsy sellers (bulk, needs consistency)
- Cricut / laser / vinyl users (paths must be cuttable, not just pretty)
- Small print shops (customer sends a 400px JPEG logo, needs print-ready art today)
- Embroidery shops **only as "clean art for your digitizing software"** — we do not
  generate stitch files (see non-goals).

Two engineering consequences that must not be negotiated away:

1. **Quality is produced by a scored parameter search, not a single trace call.**
   See §3. This is the core IP.
2. **Batch is a first-class feature**, and it must never degrade interactive
   latency. See §4.2.

Non-goals for v1:

- A full vector editor; AI image generation.
- Photo vectorization (photographs trace badly and always will — detect and warn).
- **Stitch-file generation (DST/PES).** Digitizing is a different problem.
- **True SVG gradients.** vtracer bands gradients into steps; we detect, warn, and
  do the best banded trace (§3.2).
- **Centerline (single-stroke) tracing** for engravers/plotters. Both tracers produce
  outlines only; the obvious centerline tool (autotrace) is GPL. Revisit in Phase 8+.

**The real bottleneck is distribution, not code.** §9 is not optional garnish; it is
half the product. The first landing pages ship with the web app in Phase 3 because
indexing takes months and that clock must start early.

---

## 1. Answering the "feed it back into itself" question

**Do not recursively re-vectorize.** Tracing is lossy and irreversible. Rasterizing
an SVG and tracing it again compounds quantization error, rounds corners further on
every pass, and inflates node count. Quality degrades monotonically. There is no
iteration count at which it improves.

**What actually works is closed-loop parameter search:**

```
reference raster (cleaned original, §3.3)
      │
      ├─► trace(params_1) ─► svg_1 ─► rasterize ─┐
      ├─► trace(params_2) ─► svg_2 ─► rasterize ─┤
      ├─► trace(params_3) ─► svg_3 ─► rasterize ─┼─► score vs reference ─► pick best
      └─► trace(params_n) ─► svg_n ─► rasterize ─┘
```

The loop is **outside** the tracer and always compares against the **reference**
pixels derived from the original, never against a previous trace.

A second legitimate loop is **localised refinement**: if scoring shows error
concentrated in one region (e.g. small text), re-trace only that region at higher
detail and composite. Phase 8 only — an optimisation, not a foundation.

---

## 2. Stack

| Layer | Choice | Reason |
|---|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | SSR needed for SEO landing pages. **UI only** — no business logic, no DB writes |
| API | **FastAPI service owns all of `/v1`, the credit ledger, Stripe webhooks and DB migrations** | One writer for money and jobs. Two backends writing one ledger is how drift happens |
| Worker | Python 3.12, Celery + Redis | Long jobs must not block HTTP |
| Tracing | `vtracer` CLI (Rust, colour) + `potrace` CLI (bilevel), **both as subprocesses** | Uniform sandboxing, timeouts and crash isolation (§3.5) |
| Raster ops | Pillow (+ `pillow-heif`), NumPy, OpenCV; **`resvg`** for SVG→PNG | Scoring needs a fast, correct rasterizer |
| DB | Postgres (Neon or Supabase), Alembic migrations in `/apps/api` | Single store. See §5 on why not ClickHouse |
| Storage | Cloudflare R2 | Zero egress fees |
| Auth | Clerk or Supabase Auth; FastAPI verifies the JWT | Don't hand-roll |
| Payments | Stripe (subscriptions + one-off credit packs) | |
| Queue/cache | **Fixed-price Redis on the worker's private network** (Fly Redis / self-hosted) | Celery polls constantly; per-command-priced Redis (e.g. Upstash pay-as-you-go) turns idle polling into a bill |
| Errors/tracing | Sentry | Needed for subprocess failures, §3.5 |
| Hosting | Vercel (web) + Fly.io or Railway (API + worker) | Vercel functions can't host the tracer, and cap request bodies at ~4.5 MB — uploads never pass through Vercel (§4.3) |

**Licence check before coding.** Record every decision in `/docs/licensing.md`:

- `vtracer` — MIT.
- `potrace` — **GPLv2**. Invoke the binary as a subprocess only, never link it. If
  GPL is unacceptable, ship colour-only via vtracer in v1.
- `resvg`, `ezdxf`, `pillow-heif`/libheif — verify current licences and record them.
- **EPS toolchain** — pick one and record it. Do not pull in Ghostscript (AGPL)
  without an explicit decision.

**Latency targets**

| Path | Target |
|---|---|
| Preview stage A (single candidate, §7) | p95 < 2 s |
| Full `standard` job, 2000×2000 px, processing time only | **p95 < 6 s** |
| Sync HTTP hold window (upload + queue wait + processing) | 8 s, then `202` (§6) |

Indicative budget for the 6 s (measure in Phase 1, then adjust the *budget*, not the
target): ingest + analyse 0.6 · preprocess 0.5 · 4 parallel traces 1.5 ·
rasterize + score 1.0 · post-process 1.5 · emit 0.4. This only works if scoring runs
at reduced resolution (§3.6).

---

## 3. The vectorization engine (core IP — build this first and well)

Location: `/packages/engine`. Must be usable as a pure library with no web
dependencies, so it can be tested and benchmarked offline.

Pipeline: `ingest → analyse → preprocess → candidates → trace → score → select → post-process → emit`

Every run records `engine_version` (git SHA or semver) and `score_version` (§3.6).

### 3.1 Ingest

- Accept PNG, JPEG, WEBP, BMP, GIF (first frame), TIFF, HEIC.
- Verify **magic bytes**; never trust the extension or `Content-Type`.
- Reject > 25 MB or > 8000px on either side (configurable).
- **Apply EXIF orientation, then strip EXIF** (`ImageOps.exif_transpose`). Stripping
  first rotates every phone photo.
- **Colour-manage to sRGB.** If an ICC profile is embedded, convert with
  `ImageCms`; convert CMYK → sRGB; reduce 16-bit to 8-bit. Print shops send CMYK
  JPEGs and TIFFs, and untagged conversion shifts brand colours.
- Convert to RGBA internally.
- **Detect and un-premultiply alpha.** Premultiplied alpha is common in AI-generated
  and exported PNGs; tracing it produces dark halos on every soft edge. The naive
  test ("no channel exceeds alpha") is necessary but **not sufficient** — a dark logo
  with straight alpha passes it too, and dividing that image creates *bright* halos.
  Procedure:
  1. Consider only semi-transparent pixels (`0 < a < 255`). If fewer than ~500,
     skip: there is nothing to fix.
  2. If any of them has `max(r,g,b) > a`, the image is straight. Done.
  3. Otherwise test both hypotheses: for each sampled edge pixel, find the nearest
     fully opaque pixel and measure colour distance (a) as-is and (b) after
     dividing by alpha. Premultiplied images agree with their neighbours *after*
     division; straight images agree *before*. Choose the hypothesis with the lower
     mean distance; require a clear margin, else treat as straight.
  4. Expose `alpha_mode` = `auto | straight | premultiplied` as an override.

  Fixtures required: a premultiplied PNG (must be fixed) **and** a dark straight-alpha
  logo (must be left alone).

### 3.2 Analyse

Compute and **persist** as `ImageProfile` (`jobs.profile`, §5 — it contains
statistics only, no pixels, so it survives file deletion):

- `unique_colors` after 8-bit quantization
- `edge_density` (Canny edge pixel ratio)
- `has_alpha`, `alpha_is_binary`, `alpha_was_premultiplied`
- `is_grayscale`, `is_bilevel`
- `noise_estimate` (variance of Laplacian)
- `jpeg_artifact_score` (8×8 DCT-grid blockiness)
- `estimated_text_regions` (MSER / text-aspect connected components)
- `dominant_palette` (k-means, k = 2..32, elbow selection, **fixed seed**)
- `source_dpi` and `source_dpi_trusted` — metadata DPI is **untrusted by default**.
  72 and 96 are writer defaults, not facts. See §3.8 for how physical size is
  actually resolved.
- `classification`, `classification_confidence`

Classify into: `LOGO_FLAT` | `LOGO_GRADIENT` | `LINE_ART` | `SKETCH` |
`ILLUSTRATION` | `PHOTO` | `SCREENSHOT`. Rule thresholds live in
`engine/classify.py` with a unit test per class from the corpus.

Warnings surfaced in the API and UI:

- `PHOTO` → "Photographs don't vectorize cleanly. Here's the best we can do."
- `LOGO_GRADIENT` → `gradients_banded`: "Gradients are converted to colour steps."
  Strategy: stacked mode, high `color_precision`, small `gradient_step`.

Being honest here prevents refund requests.

### 3.3 Preprocess (conditional on profile)

Preprocessing produces **two** images:

- **`reference`** — the original after *cleaning* only (artifact removal, deskew,
  alpha matting, despeckle). This is what candidates are scored against. Scoring
  against the raw source would reward traces that faithfully reproduce JPEG blocks
  and halos — the opposite of what the customer is paying for.
- **`trace_input`** — `reference` plus the steps that exist purely to help the
  tracer (upscale, palette quantization).

Guard against over-cleaning: compute SSIM(`reference`, original). If it falls below
0.85, back the filters off one step and log `preprocess_backed_off`.

Each step is off by default, enabled only by classification:

- **JPEG artifact removal** — bilateral or guided filter when `jpeg_artifact_score`
  is high. POD sellers overwhelmingly upload re-compressed JPEGs.
- **Upscale** *(trace_input only)* — Lanczos ×2 when the shorter side < 600px. Small
  input is the #1 cause of ugly output. Real-ESRGAN later, behind a flag.
- **Palette quantization** *(trace_input only)* — k-means to the elbow value for
  `LOGO_FLAT`, *before* tracing. Collapses anti-aliased halos that otherwise become
  dozens of sliver paths. **Near-duplicate colours (ΔE2000 < 2.0) are merged here**,
  not after tracing (§3.7).
- **Alpha matting** — when `has_alpha` and not `alpha_is_binary`, threshold with a
  small feather so semi-transparent edge pixels don't become stray shapes.
- **Despeckle** — morphological open/close for `SKETCH` / `SCREENSHOT`.
- **Deskew** — Hough-transform angle estimate for scanned line art.

### 3.4 Candidate generation

Do **not** brute-force a grid. Use a classification-conditioned set of 3–6 parameter
vectors in `engine/presets.py`.

- Every set includes one **universal fallback** candidate, so a misclassification
  degrades gracefully.
- When `classification_confidence` is low, take the union of the top two classes'
  presets, capped at the tier's candidate count.
- All vtracer candidates use `hierarchical=stacked`. Cutout mode makes sliver removal
  (§3.7) punch holes in the artwork.

vtracer knobs that matter: `color_precision` (1–8), `filter_speckle` (0–16),
`corner_threshold` (0–180), `segment_length` (3.5–10), `splice_threshold` (0–180),
`mode` (spline|polygon|pixel), `gradient_step`.

Example for `LOGO_FLAT`:
```python
[
  Params(color_precision=6, filter_speckle=4, corner_threshold=60, mode="spline"),
  Params(color_precision=8, filter_speckle=2, corner_threshold=45, mode="spline"),
  Params(color_precision=4, filter_speckle=8, corner_threshold=80, mode="spline"),
  Params(color_precision=6, filter_speckle=4, corner_threshold=30, mode="polygon"),
]
```
For `LINE_ART` / `SKETCH`, add potrace candidates at 2–3 binarization thresholds
(Otsu, Otsu±15) varying `turdsize` and `alphamax`.

Run candidates **in parallel**: a `ThreadPoolExecutor` bounded by CPU count, each
thread launching one tracer **subprocess**. Do not use `multiprocessing.Pool` —
Celery prefork workers are daemonic and cannot have children of that kind. This is
why the worker needs real CPUs, not a serverless function.

### 3.5 Subprocess handling and observability

Tracer binaries fail in two completely different ways and conflating them wastes
days:

- Wrap every subprocess call with a Sentry span capturing argv, exit code, and full
  `stderr`.
- Map non-zero exits with parseable stderr → `400` class (`error_code: bad_image`).
- Map signals (SIGSEGV/SIGABRT), empty output, or timeout → `500` class
  (`error_code: tracer_crash`), alert, and retry once on a clean worker. The retry
  is bounded by the delivery cap in §4.1.
- Sandbox: no network, read-only FS except a scratch dir, memory ceiling, hard
  timeout 15s per candidate / 60s per job. Minimum implementation is `prlimit`
  (`RLIMIT_AS`, `RLIMIT_CPU`) plus `unshare -n`; use `bubblewrap`/`nsjail` where the
  host allows it. Do not assume cgroup control inside a Fly/Firecracker VM — verify.

### 3.6 Scoring

Rasterize each candidate SVG with `resvg` and compare against `reference`,
composited identically. **Score at a reduced resolution** — longest side capped at
1024 px for both images. Full-resolution SSIM + ΔE2000 over 4 MP × N candidates
blows the latency budget on its own.

Every term is normalised to [0, 1], higher is better:

| Term | Definition | Weight |
|---|---|---|
| `ssim` | SSIM (or MS-SSIM), clamped to [0,1] | 0.35 |
| `color` | `1 − min(mean ΔE2000 over opaque px, 20) / 20` | 0.20 |
| `edge_f1` | Canny on both; dilate each map by `r = max(1, round(0.002 × diagonal))`; precision/recall → F1. Plain IoU collapses on a 1 px shift | 0.20 |
| `alpha_iou` | IoU of alpha masks. If the source has no alpha, drop the term and renormalise the other weights | 0.10 |
| `node_term` | `1 / (1 + ln(max(1, nodes / node_baseline)))` | 0.10 |
| `path_term` | `1 / (1 + ln(max(1, paths / path_baseline)))` | 0.05 |

- `max(1, …)` matters: without it the v2 formula divides by zero at
  `nodes = baseline / e` and goes negative below that.
- `path_baseline` = number of connected colour regions in the quantized reference
  above the sliver area threshold.
- `node_baseline` = `k_class × edge_pixel_count(reference) / 1000`, with `k_class`
  calibrated per category from the corpus in Phase 1 and stored in
  `engine/calibration.json`.

Two outputs:

- **`fidelity`** — the first four terms, renormalised. "How close is it?"
- **`total`** — all six. Used for **selection**.

The penalty terms stop the scorer from always picking the highest-detail trace. A
50,000-node SVG scores best on pure SSIM and is useless on a cutting machine.
**Do not "fix" this** — leave this comment in the code.

`score_version` is a string constant in `score.py`. Any change to a term, weight,
radius or baseline bumps it, and the same PR regenerates `benchmarks/baseline.json`.
Scores from different versions are never compared.

Persist every candidate's score vector (§5).

**What this score is and is not.** It is an internal selector. It is *not* evidence
the product is good — selecting by a metric and then reporting that metric is
circular. Evidence comes from blind human comparison (§3.9) and user behaviour (§5).

### 3.7 Post-process (winner only)

Run in this order. All stop rules use **`fidelity`**, not `total` — `total` rises as
nodes fall, which would hide the damage.

1. **Sliver removal** — drop paths with area < 0.0002 × canvas area, unless inside a
   detected text region. Safe only because candidates are stacked (§3.4).
2. **Simplification**, by path type:
   - *Polygon-mode paths:* RDP, epsilon from a geometric schedule based on the image
     diagonal, then fit cubic Béziers (Schneider) to polyline runs within a strict
     tolerance; merge collinear segments.
   - *Spline-mode paths:* RDP does not apply to Béziers. Refit runs of adjacent cubic
     segments with Schneider at increasing tolerance instead.
   - At most 5 steps. Re-score after each (reduced resolution) and stop when
     `fidelity` falls more than 2% below the pre-simplification value.
3. **Minimum physical node spacing** — enforce an absolute minimum distance between
   adjacent nodes, computed from the **resolved physical size** (§3.8), not from
   `source_dpi`. Dense node clusters make vinyl blades tear material and confuse
   laser controllers. `min_node_spacing_mm`, default 0.1 mm. If the size is only
   assumed, still apply it and carry the `physical_size_assumed` warning.
4. **Colour normalisation** — fills within ΔE2000 < 2.0 are snapped to one hex value
   and grouped together. **No geometric union of adjacent shapes in v1** — path
   booleans are a large dependency and a bug farm; the merging that matters already
   happened in quantization (§3.3).
5. **Layer ordering + naming** — group by colour, name groups `color-#RRGGBB`.
   Cheap, visible quality signal to Illustrator/Inkscape users.
6. **Minification** — strip metadata, round coordinates to 2dp, svgo-equivalent.

### 3.8 Emit

Formats: **SVG** (always), **PDF**, **EPS**, **DXF**, AI-compatible PDF, high-res PNG.

`cairosvg`/`resvg` for PDF/PNG, `ezdxf` for DXF, EPS per the toolchain decision in §2.

**Physical size resolution** (used by SVG, DXF, PDF and §3.7 step 3), in order:

1. User-supplied `output_width` / `output_height` + `units`. The UI asks "How wide
   should this be?" on every cut-intent page and before any DXF download.
2. Metadata DPI, only if `source_dpi_trusted` (present and not a 72/96 default).
3. Fallback: assume 96 dpi and return warning `physical_size_assumed`.

A 400 px logo has no meaningful DPI. v2 derived real-world scale from it, which
produces confidently wrong sizes.

- **SVG carries explicit physical `width`/`height` with units plus a `viewBox`.**
  Most Cricut users import SVG, not DXF, and cutting apps disagree about unitless
  SVGs.
- **DXF must carry explicit absolute units.** Set `$INSUNITS` and scale geometry into
  real millimetres or inches. Flatten Béziers to polylines at a user-supplied
  tolerance (`dxf_tolerance`) — most cutters can't read curves.

### 3.9 Testing the engine

Build `benchmarks/corpus/` — 60–100 images with hand-labelled category, from
public-domain/CC0 sets plus your own. Required fixtures: premultiplied alpha, **dark
logo with straight alpha**, sub-600px input, heavy JPEG artifacts, binary alpha,
**CMYK JPEG**, **EXIF-rotated photo**, **gradient logo**, and a photo (expected to
score poorly).

**`make bench`** — prints mean `total` and `fidelity` per category plus per-image
regression against `benchmarks/baseline.json`. Seeds are fixed and thread counts
pinned so runs are reproducible. **CI fails any PR that lowers a category mean by
more than 0.005** unless the PR body justifies it. Without this gate, quality drifts
invisibly.

**`make ab`** — generates a static page of blind, randomised A/B pairs (ours vs a
comparator) and records votes to JSON. Comparators: a single default `vtracer` call,
and Vectorizer.AI output obtained through a normal paid account for internal
comparison only (check their terms first). This, not `make bench`, is the evidence
used by the kill switch (§12) and the definition of done (§13).

---

## 4. Service architecture

### 4.1 Worker hygiene

- `worker_max_tasks_per_child = 25`. OpenCV/NumPy/Pillow fragment memory; without
  recycling, RSS climbs until the box OOMs at 3am.
- `task_acks_late = True` + `task_reject_on_worker_lost = True` so a killed worker
  requeues rather than silently dropping a paid job.
- **Delivery cap (poison-pill guard).** Late acks + requeue-on-loss means an image
  that kills its worker is redelivered forever. Increment `attempts:{job_id}` in
  Redis at task start; on the third delivery, mark the job `failed`
  (`tracer_crash`), do not requeue, and alert.
- `worker_prefetch_multiplier = 1`, and
  `broker_transport_options = {"visibility_timeout": 600}` — comfortably above the
  60 s job timeout, so Redis never redelivers a task that is still running.
- **One Celery task per file, never one per batch.** A 500-file batch is 500 tasks.
- Run workers with `--without-gossip --without-mingle` to cut broker chatter.
- Idempotent task bodies keyed on `job_id` — a requeue must not double-charge or
  double-write outputs.

### 4.2 Queue lanes (a 500-file batch must never block a preview)

| Lane | Priority | Worker pool | Purpose |
|---|---|---|---|
| `queue_preview` | Highest | Dedicated, always-warm | Interactive preview. This is the sales pitch; stage A p95 < 2 s |
| `queue_sync` | Standard | Its own general pool | Single-file web/API conversions, 8 s hold window |
| `queue_batch` | Background | Separate, capped pool | Large batches |

Three pools, no sharing. Batch work runs on its own capped pool so it cannot starve
the other lanes. **If you later move `queue_batch` to spot/preemptible instances for
cost**, it must first satisfy §4.1 (late acks, requeue on worker loss, delivery cap,
per-file tasks), so preemption loses at most one file. Do not adopt spot before that.

### 4.3 Uploads and remote fetch

**Uploads never pass through Vercel** (≈4.5 MB body cap) and batches never travel as
one multipart request (500 × 25 MB is 12.5 GB).

1. `POST /v1/uploads` → `{upload_id, put_url}` — a presigned R2 `PUT` with
   `Content-Length` and `Content-Type` signed in, valid 10 minutes.
2. Client `PUT`s the bytes straight to R2.
3. `POST /v1/vectorize {upload_id, …}` — the API `HEAD`s the object, enforces the
   size limit (delete on violation), then ingest re-checks magic bytes and dimensions.

Small API clients may still send multipart directly to the FastAPI host for
convenience; the web app always uses the presigned flow.

**`{url}` input is an SSRF vector.** Rules:

- `https` only. Resolve DNS first; reject loopback, private, link-local, CGNAT and
  cloud-metadata ranges (v4 and v6). **Connect to the resolved IP** so a second DNS
  answer can't rebind.
- No redirects, or re-validate every hop (max 3).
- Stream with a 25 MB cap and a 10 s total timeout.
- Fetch from a process with no route to internal services.

---

## 5. Data model

```sql
users(id, email, stripe_customer_id, credits_cached, created_at)

subscriptions(id, user_id, stripe_subscription_id UNIQUE, plan, status,
              current_period_end, cancel_at_period_end, updated_at)

api_keys(id, user_id, key_hash, key_prefix, label, last_used_at, revoked_at)

jobs(id, user_id NULL, batch_id NULL, root_job_id, parent_job_id NULL,
     kind,                         -- preview | sync | batch | api
     status, options JSONB,        -- what the caller asked for
     idempotency_key NULL,
     source_key, source_bytes, source_w, source_h,
     profile JSONB,                -- ImageProfile, statistics only
     classification, classification_confidence,
     engine_version, score_version,
     chosen_params JSONB, score JSONB, warnings JSONB,
     physical_w_mm, physical_size_source,  -- user | metadata | assumed
     output_keys JSONB, error_code, attempts,
     credits_charged, unlocked_at NULL,
     created_at, started_at, finished_at, expires_at, ip_hash,
     UNIQUE (user_id, idempotency_key))

job_candidates(id, job_id, params JSONB, score JSONB, fidelity, total, selected,
               node_count, path_count, exit_status, duration_ms)

job_events(id, job_id, user_id NULL, type, payload JSONB, created_at)
  -- preview_viewed | param_tweaked | rerun | unlocked | downloaded | deleted |
  -- refund_requested

batches(id, user_id, status, total, completed, failed, zip_key, webhook_url,
        created_at)

credit_grants(id, user_id, source,  -- free_monthly | plan_monthly | api_monthly |
                                    -- pack | promo
              amount, remaining, expires_at NULL,
              stripe_event_id UNIQUE NULL, created_at)

credit_ledger(id, user_id, grant_id, delta, reason, stripe_event_id NULL,
              root_job_id NULL, created_at,
              UNIQUE (root_job_id, reason), UNIQUE (stripe_event_id, reason))

usage_daily(user_id, date, jobs, credits, bytes_in, bytes_out)
```

`status`: `queued | processing | complete | failed | expired`.

**Credits are ledger-derived, never a mutable counter.** `credits_cached` and
`credit_grants.remaining` are projections rebuildable from `credit_ledger`. Getting
this wrong means either giving away free work or charging twice; both are fatal at
this scale.

**Why grants.** A single summed ledger cannot express "100 downloads that expire at
period end" alongside "50 that never expire" alongside "API credits that roll over up
to 3×". Rules:

- Every purchase, renewal or monthly allowance creates a **grant**. `plan_monthly`
  and `free_monthly` expire at period/month end; `pack` never expires; `api_monthly`
  does not expire while the subscription is active.
- **Consumption order:** soonest-expiring first, never-expiring last. Debit inside
  one transaction with `SELECT … FOR UPDATE` on the user's open grants.
- **API rollover cap:** on renewal, add the new grant, then if total remaining
  `api_monthly` credits exceed 3× the monthly amount, expire the oldest excess with a
  ledger entry `reason = rollover_cap`.
- **Refunds** reverse the unspent part of that purchase's grant. If it was already
  spent, flag the account for review rather than driving a balance negative.
- **One charge per source image.** Tweaked re-runs from the advanced panel are child
  jobs sharing a `root_job_id`; the unique `(root_job_id, reason)` constraint makes
  one unlock cover every revision for the retention window.

**The dataset that survives deletion.** Sources and outputs are hard-deleted on
schedule (§8), so the accumulating asset is *not* images. It is, per job:
`profile` + every candidate's params and scores + `engine_version`/`score_version`
+ `job_events`. That is enough to learn profile → best-params priors. Behaviour
(`unlocked`, `param_tweaked`, `rerun`, `refund_requested`) is the only signal in the
system that isn't self-referential — treat it as the ground truth for weight tuning
in Phase 8. None of it contains pixels; say so on the privacy page. An explicit
opt-in ("help improve results") may retain sources for the corpus.

`DELETE /v1/jobs/{id}` purges files immediately and nulls `user_id` on the retained
statistical rows.

`job_candidates` stays in Postgres. At realistic v1 volume this is a few thousand
rows a month — Postgres handles it for years. Revisit a columnar store only when the
table passes ~100M rows; a second database is a second thing to operate, back up and
debug, for no benefit today.

`ip_hash` = HMAC-SHA256 with a **daily-rotating secret**. A plain hash of an IPv4
address is reversible by brute force in seconds.

---

## 6. API

Served entirely by FastAPI. Auth: `Authorization: Bearer sk_live_...` for keys, or
the auth provider's JWT from the web app. Store SHA-256 hashes; show the key once.

```
POST   /v1/uploads              → {upload_id, put_url}                    (§4.3)
POST   /v1/vectorize            {upload_id | url} or multipart
GET    /v1/jobs/{id}            status + score summary + download URLs
POST   /v1/jobs/{id}/unlock     web flow: spend a credit, enable downloads
GET    /v1/jobs/{id}/preview    watermarked raster tile: ?x&y&w&h&scale   (§7)
DELETE /v1/jobs/{id}            purge source + outputs now
POST   /v1/batch                {count ≤ 500, options} → batch id + put_urls
POST   /v1/batch/{id}/start     after uploads complete
GET    /v1/batch/{id}           progress + zip URL when done
POST   /v1/preview              free, no charge, rate-limited (§8)
GET    /v1/account              plan, credits by grant, usage
```

- **Sync/async.** `/v1/vectorize` holds the connection up to 8 s. Finished → `200`
  with the result; not finished → `202` with the job id. `Prefer: respond-async`
  returns `202` immediately. The server never has to guess duration in advance.
- **`Idempotency-Key` header** on every `POST`. A retried request with the same key
  returns the original job and never charges twice.
- **Webhooks.** Optional `webhook_url` on jobs and batches; payloads signed with
  HMAC-SHA256 and a timestamp; retried with backoff.
- **Charging.** API jobs are debited on successful completion. Web jobs are debited
  at `unlock`. Failed jobs are never billed. Out of credits → `402`.

Options: `format`, `mode` (`auto|flat|lineart|sketch|photo`), `max_colors`,
`detail` (`low|balanced|high`), `simplify`, `keep_background`, `alpha_mode`,
`output_width`, `output_height`, `units` (`mm|in`), `dxf_tolerance`,
`min_node_spacing_mm`, `quality_tier` (`fast|standard|max` → 1, 4, 8 candidates).

Response:
```json
{
  "id": "job_...", "status": "complete", "classification": "LOGO_FLAT",
  "quality": { "total": 0.94, "fidelity": 0.95, "ssim": 0.96, "edge_f1": 0.91,
               "nodes": 412, "score_version": "s3" },
  "physical_size": { "width_mm": 120.0, "source": "user" },
  "warnings": ["source_resolution_low"],
  "outputs": { "svg": "https://...", "dxf": "https://..." },
  "credits_charged": 1
}
```

Exposing the quality score is a differentiator and a support-cost reducer: it turns
"this looks bad" into a number both sides can see. Always return `score_version`
with it so numbers are never compared across versions.

Errors: RFC 9457 `problem+json`, stable `error_code` strings, clear separation of
`400` (bad image) from `500` (worker crash) per §3.5. 429 with `Retry-After`.
Version in the path; never break `/v1`.

---

## 7. Web app

**Conversion flow** — free preview, paid download:

1. Drag-drop → immediate client-side thumbnail → presigned upload straight to R2.
2. `/v1/preview` on `queue_preview`, **progressive**:
   - *Stage A* — one candidate, shown in < 2 s.
   - *Stage B* — the full `standard` search finishes and replaces it in place
     ("refining…"). The job the user sees at the end **is** the job they buy. No
     separate "real" run after payment.
3. **Interactive side-by-side slider**, zoomable to 800%. The zoom is the sales
   pitch: raster pixelates, vector stays sharp.
4. **The SVG never reaches the browser before unlock.** The preview is served as
   watermarked raster tiles rendered on demand by `resvg`
   (`/v1/jobs/{id}/preview?x&y&w&h&scale`, max scale 8×, short-lived cache). An SVG
   in the DOM *is* the download, watermark or not — anyone can copy it from DevTools.
5. Download → sign-in → `POST /v1/jobs/{id}/unlock` → signed URLs. Re-downloads and
   other formats of an unlocked job are free for the retention window.
6. Advanced panel: colour count, detail, despeckle, background removal — each
   re-runs a *single* trace as a child job (same `root_job_id`), not the full search,
   for instant feedback. Every tweak is logged as a `param_tweaked` event (§5).
7. Cut-intent pages and any DXF download ask **"How wide should this be?"** (§3.8).

**Batch flow:** multi-drop up to 500 → presigned uploads → server-persisted progress
grid → per-file retry → zip download. Closing the tab must not lose work.

**Must-haves:** keyboard accessible, works on mobile (POD sellers work from phones),
dark mode, no layout shift on upload.

---

## 8. Storage, delivery, retention

- Outputs in R2, served via **short-lived signed URLs (1 hour)**. Never serve user
  files from your own origin path.
- **Do not put user outputs behind a long-lived CDN cache.** Every output is a unique
  file downloaded once or twice by one person, so the cache hit rate is inherently
  near zero and there is nothing to win — R2 egress is already free. More
  importantly, caching private artwork under a path-only cache key with
  `immutable, max-age=31536000` would serve deleted files for a year and break the
  retention promise below, which is the exact guarantee print shops under NDA are
  buying. If a future CDN layer is ever added, it must key on the full signed URL and
  purge on delete.
- **Retention:** sources and outputs hard-deleted after 24h (free) / 30 days (paid),
  driven by `expires_at` and a sweeper job. **Backstop:** R2 lifecycle rules on
  separate prefixes (`free/` 2 days, `paid/` 31 days) so a dead sweeper cannot break
  the promise. State the policy on the marketing page.
- Zip artifacts for batches follow the owner's retention, not a longer one.

**Abuse and cost guardrails:**

- **Preview limits, stated once:** previews are free and unmetered for normal human
  use, rate-limited per IP in Redis — 20/hour anonymous, 60/hour signed-in — with
  Turnstile after 5 anonymous previews. Tile requests are rate-limited separately.
  Marketing copy says "free previews", not "unlimited".
- Reject decompression bombs (`Image.MAX_IMAGE_PIXELS`), enforce §3.5 timeouts.
- SSRF rules for `{url}` input (§4.3).
- Hard-cap API overage at 3× plan value unless explicitly opted out, so nobody gets a
  surprise $4,000 invoice from a runaway loop.
- Alert to Slack/email when daily compute cost deviates >15% from the trailing 7-day
  moving average. An 8-candidate search's failure mode is a large CPU bill.
- Log `ip_hash` only (§5). Keep a takedown path; no moderation model in v1.

---

## 9. SEO & distribution (the actual bottleneck — not deferrable)

The code is the easy half. Nobody finding it is how this dies.

**Ships with the web app in Phase 3** (the indexing clock starts here):

- `/png-to-svg` and `/convert-for-cricut` as SSR pages, each a **working converter**.
- `sitemap.xml`, `robots.txt`, canonicals, OpenGraph images, JSON-LD
  `SoftwareApplication` + `FAQPage`.
- Core Web Vitals budget: LCP < 2.0s, CLS < 0.05, checked in CI with Lighthouse.

**Phase 7 expands it:**

- Remaining intent pages: `/jpg-to-svg`, `/logo-to-vector`, `/image-to-dxf`,
  `/vector-art-for-embroidery-digitizing`. Each needs genuinely different copy and
  examples — thin doorway pages get penalised. The embroidery page says plainly that
  we produce clean art for Ink/Stitch, Hatch and similar, **not stitch files**.
- Tutorial content aimed at buyers: "prepare a logo for DTF printing", "clean up a
  customer's low-res logo", "correct DXF scale in LightBurn".
- Public API docs — they rank, and they recruit the developer tier.
- Free tools as link bait: SVG minifier, SVG→PNG, palette extractor.
- A comparison page against Vectorizer.AI — **only** if the A/B results (§3.9)
  support an honest one.

---

## 10. Pricing & billing

| Tier | Price | Contents |
|---|---|---|
| Free | $0 | Free watermarked previews, 3 downloads/month |
| Starter | $12/mo | 100 downloads, **all formats incl. DXF**, batch ≤ 25 |
| Pro | $29/mo | 1,000 downloads, batch ≤ 500, priority queue, webhooks |
| API | $29/mo + usage | 500 credits, overage $0.04, credits roll over up to 3× |
| Credit pack | $9 one-off | 50 downloads, never expires |

Formats are never tier-gated on paid plans. DXF is the reason cutters show up;
gating it behind Pro contradicts §0. Tiers differ on volume, batch size, priority
and API access.

> **DECISION NEEDED (owner, before Phase 4).** The market anchor is unlimited web
> downloads at ~$9.99/month. A capped $12 Starter loses a side-by-side comparison on
> price unless batch and cut-correctness are visible on the pricing page itself.
> Options: (a) keep prices, lead with batch + "opens at the right size"; (b) Starter
> at $9 with a higher cap; (c) unlimited single-file downloads, metering only batch
> and API. Use the Phase 0 A/B result to choose. The credit-pack tier is the one
> clear gap in the competitor's line-up — keep it regardless.

The one-off pack matters: most traffic is a person with a single logo who will never
subscribe. Without it you monetize 0% of them.

- Stripe webhooks are received by **FastAPI** (the ledger's only writer):
  `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`,
  `customer.subscription.updated`, `customer.subscription.deleted`,
  `charge.refunded`, `charge.dispute.created`. Verify signatures; dedupe on
  `stripe_event_id` uniqueness. `past_due` suspends new unlocks; a dispute freezes
  the account pending review.
- Each event maps to grant operations per §5 — never to a direct balance edit.
- **Charge on success only** (API: completion; web: unlock). A failed job is never
  billed.
- Stripe Tax on, multi-currency presentment on.

---

## 11. Repo layout

```
/apps/web            Next.js: marketing, app UI, checkout redirect. No DB access
/apps/api            FastAPI: /v1, auth verification, ledger, Stripe webhooks
  /migrations        Alembic — the only place schema changes
/apps/worker         Celery app + task definitions
/packages/engine     Pure library. `python -m engine in.png out.svg`
    ingest.py  analyse.py  classify.py  preprocess.py  presets.py  trace.py
    score.py   postprocess.py  emit.py  pipeline.py  calibration.json
/packages/shared     TS types generated from the FastAPI OpenAPI schema
/benchmarks          corpus/, baseline.json, run.py, ab/
/infra               Dockerfiles, fly.toml
/docs                architecture.md, licensing.md, runbook.md
```

Gates: `ruff` + `mypy --strict`, `eslint` + `tsc --noEmit`, pytest ≥80% coverage on
`packages/engine`, `make bench` in CI.

---

## 12. Build order

**Phase 0 — Weekend kill test.** `LOGO_FLAT` only. 20–30 images. Ingest → k-means
quantize → 4 presets → `fidelity` score → select → SVG. Plus `make ab`. No
classifier, no potrace, no deskew, no MSER, no post-processing, no web.

> **Kill switch.** Have 2–3 people who didn't write the code vote on the blind pairs.
>
> - **vs a single default `vtracer` call:** ours must be preferred on **≥ 70%** of
>   pairs. If not, the search adds nothing a free binary doesn't, and you should
>   stop. That is a legitimate and cheap outcome, and finding it out in one weekend
>   is the most valuable thing in this document.
> - **vs Vectorizer.AI:** record the result honestly. Losing on raw quality is
>   survivable **only** because §0 positions on batch and cut-correctness — if you
>   lose here, that positioning is mandatory, not optional, and §10's decision should
>   lean toward (b) or (c).
>
> Do not use `make bench` for this. Best-of-N selected by a score always beats a
> single call *on that score*; the v2 kill switch could not fail.

**Phase 1 — Full engine, no web.** Everything in §3: all classes, reference/
trace_input split, potrace, post-processing, emit with physical size, the full
corpus, `calibration.json`, `make bench` with the CI gate. Measure the §2 latency
budget here.

**Phase 2 — Service.** FastAPI `/v1`, Redis, three queue lanes (§4.2), worker
hygiene incl. delivery cap (§4.1), presigned uploads + SSRF rules (§4.3), R2 storage
with lifecycle rules, job tables, sync/async hold, idempotency keys, signed URLs.

**Phase 3 — Web app + SEO foundation.** Upload, progressive preview, tile renderer,
slider, advanced panel, auth. **Ship `/png-to-svg` and `/convert-for-cricut`, the
sitemap, JSON-LD and the Lighthouse CI budget now** (§9).

**Phase 4 — Money.** Resolve the §10 decision. Stripe, grants + ledger, unlock flow,
plan gates, account page.

**Phase 5 — Batch + formats.** 500-file batches as per-file tasks, zip, webhooks,
DXF/EPS/PDF with correct units.

**Phase 6 — API product.** Keys, docs, rate limits, overage caps.

**Phase 7 — SEO expansion.** Remaining intent pages, tutorials, free tools.

**Phase 8 — Refinement loop.** Region-level re-tracing (§1); weight and preset tuning
from `job_candidates` + `job_events`; evaluate centerline tracing.

---

## 13. Definition of done for v1

**Engine**
- 2000×2000 logo → SVG, processing p95 under 6s, standard tier.
- Blind A/B: preferred over (or tied with) a naive single-call `vtracer` on ≥80% of
  the benchmark corpus. Human votes, not `make bench`.
- Premultiplied-alpha PNGs produce no edge halos; **the dark straight-alpha fixture
  is left untouched**.
- EXIF-rotated and CMYK fixtures come out upright and colour-correct.
- Transparency preserved correctly on binary-alpha PNGs.
- **SVG and DXF open at the user-specified physical size in Cricut Design Space and
  LightBurn** — manual acceptance test, and the one that matters most to the buyer.

**Service**
- A 25 MB upload succeeds from the web app; nothing routes through Vercel.
- A 500-file batch runs to completion without raising p95 latency on
  `queue_preview`.
- A deliberately crashing image fails cleanly after the delivery cap and does not
  loop.
- Worker RSS stays flat across a 10,000-job soak run.
- `{url}` input rejects loopback, private-range, metadata-IP and redirect-to-private
  test cases.
- **No route returns SVG or any vector output for a job that is not unlocked.**
- A retried `POST` with the same `Idempotency-Key` creates one job and one charge.

**Money**
- Stripe subscribe / renew / cancel / refund / dispute / credit-pack all reconcile
  against `credit_ledger` with zero drift; `remaining` rebuilds exactly from it.
- Expiring grants are consumed before non-expiring ones; API rollover caps at 3×.
- No job can bill a user on failure; re-runs under one `root_job_id` bill once.

**Retention & SEO**
- Deleted jobs are unreachable immediately; nothing survives past `expires_at`, and
  the R2 lifecycle backstop is configured.
- `/png-to-svg` and `/convert-for-cricut` are live and indexed; Lighthouse ≥ 95.
