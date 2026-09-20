# infra — not built yet

Dockerfiles and `fly.toml` for the API and worker (§11).

Two things the Dockerfile must get right when it is written:

- The tracer binaries (`vtracer`, `resvg`, `potrace`) are pinned by version.
  A tracer bump changes output geometry, which moves every benchmark score;
  an unpinned bump shows up as an unexplained regression. CI pins them too
  (`.github/workflows/engine.yml`).
- `potrace` is GPLv2 and is invoked as a subprocess, never linked. See
  `docs/licensing.md` before changing how it is packaged.
