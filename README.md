# Raster → Vector

A scored parameter search around off-the-shelf tracers, built to the
specification in [`VECTORIZER_SPEC_V3.md`](VECTORIZER_SPEC_V3.md).

The product thesis is in §0 of that file and constrains everything here: the
competitor is Vectorizer.AI, not `vtracer`, and we do not win on raw trace
quality alone. We win on batch workflow, cut-correctness (physical scale,
node spacing, cutter-safe DXF) and an honest, exposed quality score.

## What is built

**The engine** (`/packages/engine`) — Phases 0 and 1. A pure library with no
web dependencies:

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

## What is not built

Phases 2–8: the FastAPI service, the worker and its queue lanes, the web app,
Stripe and the credit ledger, batch, the public API, and the SEO pages.
`/apps/*` are placeholders.

## The thing that decides whether any of this continues

`make bench` grades our own selector against our own metric. It detects
regressions; it is **not** evidence the product is good.

The evidence is the blind A/B in §12 — randomised pairs voted by people who
did not write the code. Ours must be preferred on **≥ 70%** of pairs against
a single default `vtracer` call. Below that, the search adds nothing a free
binary does not, and stopping is the right answer.

```bash
make ab          # builds the voting page
make ab-report   # applies the kill switch
```

**That vote has not been run yet.** It needs 2–3 humans and about an hour.
