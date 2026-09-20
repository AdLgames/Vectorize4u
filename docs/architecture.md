# Architecture

What exists today, and how the pieces that do not yet exist attach to it.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Weekend kill test: flat logos, scored search, `make ab` | **Built.** The kill switch has not been *run* — that needs 2–3 humans (see below). |
| 1 | Full engine: all classes, potrace, post-processing, physical size, corpus, `make bench` gate | **Built**, against a synthetic corpus. Calibration is provisional until real images land. |
| 2–8 | Service, web, money, batch, API, SEO, refinement | Not started. |

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

## What the service will own (not built)

Per §2 and §4, `/apps/api` (FastAPI) owns all of `/v1`, the credit ledger,
Stripe webhooks and migrations — one writer for money and jobs. `/apps/worker`
runs Celery with three queue lanes so a 500-file batch cannot starve an
interactive preview. `/apps/web` is UI only.

The engine is already shaped for that: `EngineResult` carries exactly the
fields `jobs` and `job_candidates` need (`profile`, `chosen_params`, per
-candidate `score`, `engine_version`, `score_version`, `warnings`,
`physical_size`), `run_single` is the advanced panel's single-trace path, and
`raster.render_tile` is the watermark-free half of the preview-tile endpoint.

## Evidence

`make bench` grades our own selector, so it can only detect regressions — it
is not evidence the product is good. Selecting by a metric and then reporting
that metric is circular. The evidence is `make ab`: blind, randomised pairs
voted by people who did not write the code, gated at ≥70% vs a single default
`vtracer` call (§12) and ≥80% for the definition of done (§13).

**That vote has not been run.** It needs humans, and it is the cheapest way
to find out whether any of this should continue.
