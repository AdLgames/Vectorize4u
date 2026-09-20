# apps/ — not built yet

Phases 2–6 of `VECTORIZER_SPEC_V3.md`. Placeholders so the boundaries in §11
are unambiguous from the start:

- `api/` — **FastAPI. Owns all of `/v1`, the credit ledger, Stripe webhooks
  and Alembic migrations.** One writer for money and jobs; two backends
  writing one ledger is how drift happens.
- `worker/` — Celery tasks, three queue lanes (`queue_preview`,
  `queue_sync`, `queue_batch`) with separate pools so a 500-file batch can
  never starve an interactive preview. One task per file, never one per batch.
- `web/` — Next.js. **UI only: no business logic, no DB access.** Uploads go
  straight to R2 via presigned PUT and never pass through Vercel (≈4.5 MB
  body cap).

The engine in `/packages/engine` is already shaped for these: see
`docs/architecture.md`.
