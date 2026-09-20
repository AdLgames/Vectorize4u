# Runbook

## Setting up

```bash
make setup          # venv + engine in editable mode with dev/emit extras
cargo install vtracer resvg
apt-get install potrace        # or: skip it, see below
make fixtures       # regenerate the synthetic corpus
make check          # lint + typecheck + tests
make bench          # category means + regression gate
```

Binaries are found on `PATH` and can be overridden:
`ENGINE_VTRACER_BIN`, `ENGINE_POTRACE_BIN`, `ENGINE_RESVG_BIN`.

**Running without potrace.** Leave it uninstalled and the `LINE_ART` /
`SKETCH` potrace candidates simply drop out of the candidate set; those
classes fall back to vtracer presets. This is the escape hatch if GPLv2
ever becomes unacceptable (docs/licensing.md).

## Using the engine directly

```bash
python -m engine input.png output.svg --width 120 --units mm --format dxf --json
```

`--json` prints the classification, the chosen parameters, the full score
vector, the resolved physical size and per-stage timings. That summary is
exactly what the API will return, so it is the fastest way to reproduce a
support ticket.

## Sandboxing: verify it on every new host

`engine.sandbox.sandbox_mode()` reports what isolation actually applied:

- `bwrap` — bubblewrap, network unshared. Best case.
- `unshare` — `unshare -n`, network unshared.
- `rlimit-only` — **no network isolation.** Memory and CPU limits still
  apply. The host firewall is the only thing stopping a tracer from talking
  to the network.

Do not assume cgroup control inside a Fly/Firecracker VM — §3.5 says verify,
and this is how you verify. Log the value at worker startup.

## Timeouts and limits

All env-overridable (`engine/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `ENGINE_MAX_BYTES` | 25 MB | Rejected at ingest |
| `ENGINE_MAX_DIMENSION` | 8000 | Either side |
| `ENGINE_MAX_PIXELS` | 80 M | Decompression-bomb guard |
| `ENGINE_CANDIDATE_TIMEOUT_S` | 15 | Per tracer subprocess |
| `ENGINE_JOB_TIMEOUT_S` | 60 | Honoured in post-processing |
| `ENGINE_SCORE_MAX_SIDE` | 1024 | Scoring resolution |
| `ENGINE_SIMPLIFY_MAX_NODES` | 40000 | Above this, simplification is skipped |
| `ENGINE_SEED` | 1729 | Every stochastic step |

## Diagnosing a bad result

1. `python -m engine bad.png /tmp/out.svg --json` — read `classification`
   and `classification_confidence` first. Most "bad output" is a
   misclassification, and `--mode flat|lineart|sketch|photo` overrides it.
2. Check `warnings`. `physical_size_assumed`, `source_resolution_low` and
   `gradients_banded` explain most complaints on their own.
3. Compare candidates: every one's params, score and exit status is in
   `EngineResult.candidates`, shaped for the `job_candidates` table.
4. `simplify_stopped_early` means simplification hit the 2% fidelity floor —
   working as intended on tight line art, suspicious on a flat logo.

## `make bench` and the regression gate

CI fails any PR that lowers a category mean by more than 0.005. If a change
is a genuine improvement that moves a mean down, say so in the PR body and
regenerate the baseline in the **same** PR:

```bash
make bench-baseline
```

Changing a term, weight, radius or baseline in `score.py` **must** bump
`SCORE_VERSION` and regenerate `baseline.json` in the same PR. Scores from
different versions are never compared, and `make bench` refuses to compare
them.

## The blind A/B (`make ab`)

```bash
make ab              # writes benchmarks/ab/out/ab-vtracer-default.html
# open it; have 2–3 people who did not write the code vote
# save the downloaded votes.json to benchmarks/ab/votes.json
make ab-report
```

The kill switch: ours must be preferred on **≥ 70%** of pairs against a
single default `vtracer` call. Below that, the scored search adds nothing a
free binary does not, and stopping is the correct outcome.

Do not substitute `make bench` for this. Best-of-N selected by a score always
beats a single call *on that score*.

**Status:** the owner reports this vote was run and passed the §12 gate.
`benchmarks/ab/votes.json` is not in the repository, so the number is not on
the record — commit the votes file and the `make ab-report` output, and
re-run the vote whenever `score_version` or the preset sets change, since a
pass on one engine version says nothing about the next.

## Running the whole stack locally

No Postgres, no Redis, no cloud account:

```bash
make setup setup-service
make api      # terminal 1 — FastAPI with the worker running inline
make web      # terminal 2 — Next.js against http://127.0.0.1:8000
```

With real infrastructure, drop `VEC_INLINE_WORKER` and run `make worker`
alongside. The worker consumes all three lanes in that command; in
production run **three separate pools**, one per queue, so a 500-file batch
cannot starve an interactive preview (§4.2).

Service environment variables (all prefixed `VEC_`):

| Variable | Default | Meaning |
|---|---|---|
| `VEC_ENVIRONMENT` | `dev` | `prod`/`staging` turn on the startup safety checks |
| `VEC_DATABASE_URL` | SQLite file | Postgres in production |
| `VEC_REDIS_URL` | local Redis | Celery broker and rate-limit store |
| `VEC_STORAGE_BACKEND` | `local` | `r2` in production; `local` is refused there |
| `VEC_INLINE_WORKER` | unset | `1` runs jobs in the request thread; refused in production |
| `VEC_IP_HASH_SECRET` | dev default | **Rotate daily.** A plain hash of an IPv4 is brute-forced in seconds |
| `VEC_STRIPE_WEBHOOK_SECRET` | empty | Required in production; without it signatures are not verified |

`Settings.check()` runs at startup and refuses to boot a production process
that still holds a development default for any of the secrets, or that is
pointed at the local storage backend.

## Authentication (Supabase)

### Setting up a project

1. Create a Supabase project. Dashboard → **Settings → API** gives you the
   project URL and the **anon** key. Only those two go in the web app —
   the service-role key is never needed here, because every privileged
   action goes through `/v1`, which verifies the session token itself.
2. Dashboard → **Authentication → URL Configuration → Redirect URLs**: add
   `http://localhost:3000/auth/callback` and your production equivalent.
   A missing entry is the usual cause of a magic link that bounces.
3. Set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in
   `apps/web/.env.local`, and `VEC_SUPABASE_URL` in `apps/api/.env`.

The API verifies tokens itself rather than calling Supabase per request —
a network round trip inside every API call would put someone else's uptime
in our p95 — but the verification is real: signature, issuer, audience and
expiry, against the project's published keys.

**Legacy projects** that still sign with a shared secret set
`VEC_SUPABASE_JWT_SECRET` instead (Settings → API → JWT Secret). Which
branch runs is chosen by the token's own `alg` header, and each branch pins
its algorithm list, so a token cannot talk the server into the wrong one.
**Remove the secret once you migrate to asymmetric keys** — leaving it set
keeps a second way to mint tokens alive long after anyone remembers it.

### Sign-in without a Supabase project

```bash
make api   # sets VEC_DEV_AUTH_ENABLED=1
make web   # sets NEXT_PUBLIC_DEV_AUTH=1
```

Any address signs straight in. This is **an auth bypass**, and three things
stand between it and production: it is off by default, the router is not
mounted when the environment is staging or prod, and `Settings.check()`
refuses to boot production while it is set.

It exists so the signed-in flow can actually be tested — a magic link
cannot be clicked by a script, which is precisely why the path that takes
money would otherwise never run in CI or in a browser here.

### Identity rules worth knowing

- **`sub` is the account.** The Supabase user UUID is our user id; the
  email is a label that can change, and a change follows the account.
- **Linking by email requires a verified address.** Otherwise anyone could
  claim an existing account by signing up with its address through a
  provider that does not verify email. An unverified collision is refused
  with a clear message rather than opening a second account.
- **Anonymous Supabase sessions are rejected** for account actions. Our
  anonymous path has no account at all, and an anonymous user holding a
  credit balance would be a second identity model.

## Browser smoke test

```bash
make api    # terminal 1
make web    # terminal 2
make e2e    # terminal 3
```

Two scripts. `e2e/smoke.mjs` covers the anonymous path — preview, the
unlock gate, the zoom. `e2e/signed-in.mjs` covers the one that takes money:
sign in, convert, unlock, download the real file, and confirm a credit was
actually spent.

They are not decoration. Between them they have caught five bugs that unit
tests and the type checker could not see, including a preview image
silently squashed by a Tailwind default and a credit balance that stayed
stale after a purchase (see docs/architecture.md).

## Known gaps

- **The corpus is synthetic.** §3.9 wants 60–100 hand-labelled real images.
  Drop them in `benchmarks/corpus/real/` with a `labels.json` and they are
  picked up automatically. Until then, `engine/calibration.json`'s `k_class`
  values are provisional bootstrap numbers, not calibration, and the category
  means are indicative only.
- **The A/B vote's result is not in the repository.** The owner reports it
  passed; `benchmarks/ab/votes.json` should be committed so the number is
  auditable.
- **Latency was measured on a 4-core container**, not on the worker hardware
  §2 assumes: median ~5.2 s, p95 ~6.0 s on the synthetic corpus at
  `standard`. The photo fixture takes ~27 s and is the known outlier — a
  photograph traces to ~87,000 nodes, and the node penalty in the score
  already says what needs saying about that. Re-measure the §2 budget on
  real worker hardware before treating any of these numbers as the target.
- **`alpha_binary` scores lower than its siblings** (fidelity ~0.85). The
  alpha matting and the alpha IoU term interact; worth a look.
- **No checkout page.** Stripe events map to grants and reconcile, and the
  prices are decided, but the Stripe product/price objects and the checkout
  redirect are not wired, so "Buy 50 credits" is inert. Sign-in and unlock
  work; only the part that takes the money does not.
- **Rate limiting falls back to per-process memory** when Redis is absent.
  That is not a real limit across replicas, and it is refused in production.
- **Preview tiles are one tile, not a grid.** Panning re-renders the whole
  visible area. Fine at launch sizes; a tile grid is a Phase 8 optimisation.
