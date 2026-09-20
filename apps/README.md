# apps/

The boundaries in §11 of the spec, and why they are drawn there.

- **`api/` — FastAPI.** Owns all of `/v1`, the credit ledger, Stripe webhooks
  and the Alembic migrations. One writer for money and jobs: two backends
  writing one ledger is how drift happens.
- **`worker/` — Celery.** Three queue lanes (`queue_preview`, `queue_sync`,
  `queue_batch`) with separate pools, so a 500-file batch can never starve an
  interactive preview. One task per file, never one per batch.
- **`web/` — Next.js 15.** UI only: no business logic, no database access.
  Uploads go straight to storage with a presigned PUT and never pass through
  the Next.js server — Vercel caps request bodies around 4.5 MB, and a 25 MB
  logo is an ordinary input here.

Run the whole thing with no infrastructure:

```bash
make api    # FastAPI, SQLite, local object store, worker inline
make web    # Next.js against http://127.0.0.1:8000
```

See `docs/architecture.md` for the decisions that are load-bearing and
`docs/runbook.md` for environment variables and debugging.
