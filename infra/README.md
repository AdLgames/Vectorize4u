# infra — not built yet

Dockerfiles and `fly.toml` for the API and worker (§11).

What the deployment must get right, none of which is expressible in the
application code:

- **Three worker pools, not one.** `make worker` consumes all three lanes for
  convenience locally. In production run a pool per queue, with
  `queue_batch` capped, or §4.2's guarantee is not a guarantee.
- **Pin the tracer binaries** (`vtracer`, `resvg`, `potrace`) by version. A
  tracer bump changes output geometry, which moves every benchmark score; an
  unpinned bump shows up later as an unexplained regression. CI pins them too.
- **`potrace` is GPLv2**, invoked as a subprocess and never linked. Read
  `docs/licensing.md` before changing how it is packaged.
- **R2 lifecycle rules on the `free/` and `paid/` prefixes** (2 days and 31
  days). These are the backstop for the retention promise: a dead sweeper
  must not be able to break it.
- **Fixed-price Redis on the worker's private network.** Celery polls
  constantly, so per-command pricing turns idle polling into a bill.
- **Verify the sandbox on the host.** `engine.sandbox.sandbox_mode()` reports
  what isolation actually applied; log it at worker startup. Do not assume
  cgroup control inside a Fly/Firecracker VM.
- **Rotate `VEC_IP_HASH_SECRET` daily.** A plain hash of an IPv4 address is
  reversible by brute force in seconds.
