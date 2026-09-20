# Raster → Vector SaaS — Build Specification

**Audience:** Claude Code (or any engineer) implementing this from scratch.
**Status:** Greenfield. Nothing exists yet.
**Read this whole file before writing code. Build in the phase order given at the end.**

---

## 0. Product thesis (read first — it constrains every technical decision)

This is not "an SVG converter." A converter is a commodity: `vtracer` is free, and
Illustrator has Image Trace built in. Nobody pays for a wrapper around a free binary.

The product sells **output quality** and **batch workflow** to people who vectorize
repeatedly for money:

- Print-on-demand / Etsy sellers (bulk, needs consistency)
- Cricut / laser / vinyl / embroidery users (paths must be cuttable, not just pretty)
- Small print shops (customer sends a 400px JPEG logo, needs print-ready art today)

Two engineering consequences that must not be negotiated away:

1. **Quality is produced by a scored parameter search, not a single trace call.**
   See §3. This is the core IP. A single `vtracer` invocation is the thing we are
   explicitly not shipping.
2. **Batch is a first-class feature, not a loop over the single-file endpoint.**
   Uploading 200 designs and getting a zip back is the thing casual free tools
   don't do.

Non-goals for v1: a full vector editor, AI image generation, photo vectorization
(photographs trace badly and always will — detect and warn instead).

---

## 1. Answering the "feed it back into itself" question

**Do not recursively re-vectorize.** Tracing is lossy and irreversible. Rasterizing
an SVG and tracing it again compounds quantization error, rounds corners further on
every pass, and inflates node count. Quality degrades monotonically. There is no
iteration count at which it improves.

**What actually works is closed-loop parameter search:**

```
original raster
      │
      ├─► trace(params_1) ─► svg_1 ─► rasterize ─┐
      ├─► trace(params_2) ─► svg_2 ─► rasterize ─┤
      ├─► trace(params_3) ─► svg_3 ─► rasterize ─┼─► score vs original ─► pick best
      └─► trace(params_n) ─► svg_n ─► rasterize ─┘
```

The loop is **outside** the tracer and always compares against the **original**
pixels, never against a previous trace. This is the entire design of §3.

A second legitimate loop is **localised refinement**: if scoring shows error
concentrated in one region (e.g. small text), re-trace only that region at higher
detail and composite. Implement only after Phase 3 — it is an optimisation, not a
foundation.

---

## 2. Stack

| Layer | Choice | Reason |
|---|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind | SSR needed for SEO landing pages |
| API | Next.js route handlers for CRUD/auth; **separate Python worker** for processing | Image work belongs in Python |
| Worker | Python 3.12, FastAPI, Celery (or RQ) + Redis | Long jobs must not block HTTP |
| Tracing | `vtracer` (Rust, color) + `potrace` (bilevel) | Both are fast, proven, permissively licensed |
| Raster ops | Pillow, NumPy, OpenCV, `cairosvg` or `resvg` for rasterizing SVG | scoring needs SVG→PNG |
| DB | Postgres (Supabase or Neon) | |
| Storage | S3-compatible (R2 preferred — zero egress fees) | Egress will otherwise dominate cost |
| Auth | Clerk or Supabase Auth | Don't hand-roll |
| Payments | Stripe (subscriptions + one-off credit packs) | |
| Queue/cache | Redis (Upstash) | |
| Hosting | Vercel (web) + Fly.io or Railway (worker, needs CPU + binaries) | Vercel functions can't host the tracer reliably |

**Licence check before coding:** `vtracer` is MIT. `potrace` is **GPLv2** — invoking
it as a separate process is generally accepted, but linking it into your code is not.
Shell out to the binary only, and record the decision in `/docs/licensing.md`. If
GPL is unacceptable to you, ship colour-only via vtracer in v1.

Target: **p95 < 6s** for a 2000×2000px image on the standard quality tier.

---

## 3. The vectorization engine (core IP — build this first and well)

Location: `worker/engine/`. It must be usable as a pure library with no web
dependencies, so it can be tested and benchmarked offline.

### 3.1 Pipeline

```
ingest → analyse → preprocess → candidate generation → trace → score → select → post-process → emit
```

### 3.2 Ingest
- Accept PNG, JPEG, WEBP, BMP, GIF (first frame), TIFF, HEIC.
- Strip EXIF. Reject > 25 MB or > 8000px on either side (configurable).
- Verify magic bytes; never trust the extension or `Content-Type`.
- Convert to RGBA internally. Preserve alpha — transparency handling is where most
  cheap converters fail, and POD sellers care about it more than anything.

### 3.3 Analyse (classification drives everything downstream)

Compute and store as `ImageProfile`:

- `unique_colors` after 8-bit quantization
- `edge_density` (Canny edge pixel ratio)
- `has_alpha`, `alpha_is_binary` (alpha is only 0 or 255)
- `is_grayscale`, `is_bilevel`
- `noise_estimate` (variance of Laplacian)
- `jpeg_artifact_score` (blockiness at 8×8 boundaries via DCT-grid energy)
- `estimated_text_regions` (MSER or connected components with text-like aspect ratios)
- `dominant_palette` (k-means, k = 2..32, elbow selection)

Classify into: `LOGO_FLAT` | `LOGO_GRADIENT` | `LINE_ART` | `SKETCH` |
`ILLUSTRATION` | `PHOTO` | `SCREENSHOT`.

`PHOTO` returns a warning in the API response and is billed at the same rate but
flagged in the UI: "Photographs don't vectorize cleanly. Here's the best we can do."
Being honest here prevents refund requests.

### 3.4 Preprocess (conditional on profile)

Each step is off by default and enabled only by classification:

- **JPEG artifact removal** — bilateral filter or guided filter, when
  `jpeg_artifact_score` high. Critical: POD sellers overwhelmingly upload
  re-compressed JPEGs.
- **Upscale** — Lanczos ×2 when the shorter side < 600px. Small input is the #1
  cause of ugly output. Optionally swap in Real-ESRGAN later, behind a flag; it is
  a large dependency and a GPU cost.
- **Palette quantization** — k-means to the elbow value for `LOGO_FLAT`. Do this
  *before* tracing; it collapses anti-aliased halos that otherwise become dozens of
  sliver paths.
- **Alpha matting** — when `has_alpha` and not `alpha_is_binary`, threshold with a
  small feather so semi-transparent edge pixels don't become stray shapes.
- **Despeckle** — morphological open/close for `SKETCH`/`SCREENSHOT`.
- **Deskew** — Hough-transform angle estimate for scanned line art.

### 3.5 Candidate generation (the search space)

Do **not** brute-force a large grid; it wastes CPU. Use a classification-conditioned
candidate set of 3–6 parameter vectors, defined in `engine/presets.py`.

vtracer knobs that matter:
`color_precision` (1–8), `filter_speckle` (0–16), `corner_threshold` (0–180),
`segment_length` (3.5–10), `splice_threshold` (0–180), `mode` (spline|polygon|pixel),
`hierarchical` (stacked|cutout), `gradient_step`.

Example for `LOGO_FLAT`:
```python
[
  Params(color_precision=6, filter_speckle=4,  corner_threshold=60, mode="spline"),
  Params(color_precision=8, filter_speckle=2,  corner_threshold=45, mode="spline"),
  Params(color_precision=4, filter_speckle=8,  corner_threshold=80, mode="spline"),
  Params(color_precision=6, filter_speckle=4,  corner_threshold=30, mode="polygon"),
]
```
For `LINE_ART`/`SKETCH`, add potrace candidates at 2–3 binarization thresholds
(Otsu, Otsu±15) with `turdsize` and `alphamax` variation.

Run candidates **in parallel** (process pool, bounded by CPU count). This is the
main reason the worker needs real CPUs rather than a serverless function.

### 3.6 Scoring (how "best" is decided)

Rasterize each candidate SVG back to PNG at the original dimensions (`resvg` is
faster and more standards-correct than `cairosvg`; prefer it), composited on a
neutral background identical to the original's handling. Then compute a weighted
score:

| Metric | What it catches | Weight (tune later) |
|---|---|---|
| **SSIM** (or MS-SSIM) vs original | overall structural fidelity | 0.35 |
| **ΔE2000** mean colour error over opaque pixels | wrong/merged colours | 0.20 |
| **Edge IoU** (Canny of original vs Canny of render) | lost or smeared detail | 0.20 |
| **Alpha IoU** | broken transparency | 0.10 |
| **Node-count penalty** `1/(1+log(nodes/baseline))` | bloated unusable files | 0.10 |
| **Path-count penalty** | thousands of slivers | 0.05 |

The two penalty terms are what stop the scorer from always selecting the
highest-detail trace. A 50,000-node SVG scores highest on pure SSIM and is useless
to a Cricut user. State this explicitly in code comments or someone will "fix" it.

Store every candidate's score vector in `job_candidates` even though only the winner
is returned. This dataset is how you tune weights later, and it is the only real
moat you will accumulate.

### 3.7 Post-process (applies to the winner only)

- **Path simplification** — Ramer–Douglas–Peucker with an epsilon derived from image
  diagonal, but only while the score stays within 2% of the pre-simplification score.
  Simplify greedily, re-score, stop when the budget is spent.
- **Curve fitting** — merge collinear segments; convert polyline runs to cubic Béziers.
- **Sliver removal** — drop paths with area < 0.0002 × canvas area, unless they are
  inside a text region.
- **Colour merging** — merge adjacent fills with ΔE2000 < 2.0 (imperceptible).
- **Layer ordering + naming** — group by colour, name groups `color-#RRGGBB`.
  Illustrator/Inkscape users will thank you; this is a cheap, visible quality signal.
- **SVG minification** — strip metadata, round coordinates to 2dp, `svgo`-equivalent.

### 3.8 Emit

Formats: **SVG** (always), **PDF**, **EPS**, **DXF** (cutting machines — required by
the target market), **AI-compatible PDF**, high-res **PNG**.

Use `cairosvg`/`resvg` for PDF/PNG, `ezdxf` for DXF. DXF conversion must flatten
Béziers to polylines at a user-chosen tolerance — most cutters can't read curves.

### 3.9 Testing the engine

Build `benchmarks/corpus/` — 60–100 images with hand-labelled category, sourced from
public-domain/CC0 sets plus your own. Add `make bench`, which prints mean score per
category and per-image regression vs the last committed run
(`benchmarks/baseline.json`). **Any PR that lowers mean score on any category must
be justified in the PR body.** Without this, quality drifts invisibly and you lose
the only thing you're selling.

---

## 4. Data model

```sql
users(id, email, stripe_customer_id, plan, credits_remaining, created_at)
api_keys(id, user_id, key_hash, key_prefix, label, last_used_at, revoked_at)
jobs(id, user_id NULL, batch_id NULL, status, source_key, source_bytes,
     source_w, source_h, classification, chosen_params JSONB, score JSONB,
     output_keys JSONB, error_code, credits_charged,
     created_at, started_at, finished_at, ip_hash)
job_candidates(id, job_id, params JSONB, score JSONB, node_count, duration_ms)
batches(id, user_id, status, total, completed, failed, zip_key, created_at)
credit_ledger(id, user_id, delta, reason, stripe_event_id, job_id, created_at)
usage_daily(user_id, date, jobs, credits, bytes_in, bytes_out)
```

`status`: `queued | processing | complete | failed | expired`.

**Credits are ledger-derived, never a mutable counter.** `credits_remaining` is a
cached projection, rebuildable from `credit_ledger`. Every write carries
`stripe_event_id` or `job_id` for idempotency. Getting this wrong means either
giving away free work or charging people twice; both are fatal at this scale.

---

## 5. API

Auth: `Authorization: Bearer sk_live_...`. Store SHA-256 hashes; show the key once.

```
POST   /v1/vectorize          multipart or {url} → job (sync if <8s, else 202 + job id)
GET    /v1/jobs/{id}          status + score summary + signed download URLs
POST   /v1/batch              up to 500 files → batch id
GET    /v1/batch/{id}         progress + zip URL when done
GET    /v1/account            plan, credits, usage
POST   /v1/preview            free, watermarked, no credit charge, rate-limited by IP
DELETE /v1/jobs/{id}          purge source + outputs now
```

Request options: `format`, `mode` (`auto|flat|lineart|sketch|photo`), `max_colors`,
`detail` (`low|balanced|high`), `simplify`, `keep_background` (bool),
`dxf_tolerance`, `quality_tier` (`fast|standard|max` → 1, 4, 8 candidates).

Response always includes:
```json
{
  "id": "job_...", "status": "complete", "classification": "LOGO_FLAT",
  "quality": { "score": 0.94, "ssim": 0.96, "edge_iou": 0.91, "nodes": 412 },
  "warnings": ["source_resolution_low"],
  "outputs": { "svg": "https://...", "dxf": "https://..." },
  "credits_charged": 1
}
```

Exposing the quality score is a differentiator and a support-cost reducer — it moves
the conversation from "this looks bad" to a number both sides can see.

Errors: RFC 9457 problem+json, stable `error_code` strings. 429 with `Retry-After`.
Version in the path; never break `/v1`.

---

## 6. Web app

**Conversion flow** (mirrors what works commercially — free preview, paid download):
1. Drag-drop → immediate client-side thumbnail, no round-trip.
2. Server runs `/v1/preview` → **interactive side-by-side slider** (original vs
   vector), zoomable to 800%. The zoom is the sales pitch: it shows the raster
   pixelating and the vector staying sharp.
3. Preview is free and unlimited but **watermarked and download-locked**.
4. Download requires sign-in + credits or subscription.
5. Advanced panel: colour count, detail, despeckle, background removal — each
   re-runs a single trace (not the full search) for instant feedback.

**Batch flow:** multi-drop up to 500 → progress grid → per-file retry → zip download.
Persist batch state server-side so closing the tab doesn't lose work.

**Must-haves:** keyboard accessible, works on mobile (POD sellers work from phones),
dark mode, no layout shift on upload.

---

## 7. Pricing & billing

| Tier | Price | Contents |
|---|---|---|
| Free | $0 | Unlimited watermarked previews, 3 downloads/month |
| Starter | $12/mo | 100 downloads, all formats, batch ≤ 25 |
| Pro | $29/mo | 1,000 downloads, batch ≤ 500, DXF, priority queue |
| API | $29/mo + usage | 500 credits, overage $0.04, credits roll over 3× |
| Credit pack | $9 one-off | 50 downloads, never expires |

The one-off pack matters: most traffic is a person with a single logo who will never
subscribe. Without it you monetize 0% of them.

Implementation notes:
- Webhooks: `checkout.session.completed`, `invoice.paid`,
  `customer.subscription.deleted`, `charge.refunded`. **Verify signatures. Handle
  duplicates via `stripe_event_id` uniqueness.**
- Charge credits on **successful completion only**. A failed job is never billed.
- Stripe Tax on, multi-currency presentment on.
- Hard-cap API overage at 3× plan value unless the user opts out, so nobody gets a
  surprise $4,000 invoice from a runaway loop.

---

## 8. Abuse, security, cost control

- Per-IP rate limits on preview (e.g. 20/hour), sliding window in Redis.
- Turnstile/hCaptcha on anonymous preview after 5 requests.
- Bounded decode: reject decompression bombs (`Image.MAX_IMAGE_PIXELS`), enforce
  hard timeouts per candidate (15s) and per job (60s).
- Run tracer binaries in a locked-down subprocess: no network, read-only FS except a
  temp dir, memory ceiling via cgroups.
- Never serve user files from your own origin path — signed URLs only, 1-hour expiry.
- **Retention:** sources and outputs deleted after 24h (free) / 30 days (paid).
  Say this on the page. Print shops handle client logos under NDA and will ask.
- NSFW/illegal content: log `ip_hash` only, keep a takedown path, don't build a
  moderation model in v1.
- Cost guard: alert if daily compute exceeds a set threshold; the failure mode of
  an 8-candidate search is a large CPU bill.

---

## 9. SEO & distribution (the actual bottleneck — do not defer this to "later")

The code is the easy half. Nobody finding it is how this dies. Ship from day one:

- SSR landing pages per intent: `/png-to-svg`, `/jpg-to-svg`, `/logo-to-vector`,
  `/image-to-dxf`, `/convert-for-cricut`, `/vectorize-for-embroidery`.
  Each is a **working converter**, not a doormat page, with genuinely different copy
  and examples. Thin doorway pages get penalised.
- `sitemap.xml`, `robots.txt`, canonical tags, OpenGraph images, JSON-LD
  `SoftwareApplication` + `FAQPage`.
- Core Web Vitals budget: LCP < 2.0s, CLS < 0.05. Check in CI with Lighthouse.
- Comparison and tutorial content: "prepare a logo for DTF printing",
  "clean up a customer's low-res logo". This is where the buying audience searches.
- Public API docs — they rank, and they attract the developer tier.
- Free tools as link bait: SVG minifier, SVG→PNG, colour palette extractor.

---

## 10. Repo layout

```
/apps/web            Next.js: marketing, app, checkout
/apps/worker         FastAPI + Celery
  /engine
    analyse.py  preprocess.py  presets.py  trace.py
    score.py    postprocess.py  emit.py    pipeline.py
  /tasks
/packages/shared     TS types generated from OpenAPI
/benchmarks          corpus/, baseline.json, run.py
/infra               Dockerfiles, fly.toml, migrations
/docs                architecture.md, licensing.md, runbook.md
```

Quality gates: `ruff` + `mypy --strict` (Python), `eslint` + `tsc --noEmit` (TS),
pytest with ≥80% coverage on `engine/`, `make bench` in CI.

---

## 11. Build order

**Phase 1 — Engine (no web).** CLI: `python -m engine path/in.png out.svg`.
Analyse → presets → parallel trace → score → select → emit SVG. Build the benchmark
corpus and `make bench` **in this phase**. Do not start Phase 2 until mean score on
`LOGO_FLAT` beats a single default `vtracer` call by a visible margin on the corpus.
If it doesn't, the product has no reason to exist and you should stop here — that is
a legitimate and cheap outcome.

**Phase 2 — Service.** FastAPI wrapper, Redis queue, S3 storage, job table, sync/async
split, signed URLs.

**Phase 3 — Web app.** Upload, preview slider, advanced panel, auth.

**Phase 4 — Money.** Stripe, credit ledger, plan gates, account page.

**Phase 5 — Batch + formats.** 500-file batches, zip, DXF/EPS/PDF.

**Phase 6 — API product.** Keys, docs, rate limits, overage.

**Phase 7 — SEO surface.** Intent landing pages, content, free tools.

**Phase 8 — Refinement loop.** Region-level re-tracing (§1) and weight tuning from
accumulated `job_candidates` data.

---

## 12. Definition of done for v1

- 2000×2000 logo → SVG, p95 under 6s, standard tier.
- Beats a naive single-call `vtracer` on ≥80% of the benchmark corpus.
- Transparency preserved correctly on binary-alpha PNGs.
- DXF opens cleanly in Cricut Design Space and LightBurn (test manually — this is
  the acceptance test that actually matters to the buyer).
- Stripe: subscribe, cancel, refund, and credit-pack purchase all reconcile against
  `credit_ledger` with zero drift.
- No job can bill a user on failure.
- Lighthouse ≥ 95 on `/png-to-svg`.
