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

## The blind A/B (`make ab`) — not yet run

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

## Known gaps

- **The corpus is synthetic.** §3.9 wants 60–100 hand-labelled real images.
  Drop them in `benchmarks/corpus/real/` with a `labels.json` and they are
  picked up automatically. Until then, `engine/calibration.json`'s `k_class`
  values are provisional bootstrap numbers, not calibration, and the category
  means are indicative only.
- **The A/B vote has not been run.** See above. This is the gate on all
  further work.
- **Latency was measured on a 4-core container**, not on the worker hardware
  §2 assumes: median ~5.2 s, p95 ~6.0 s on the synthetic corpus at
  `standard`. The photo fixture takes ~27 s and is the known outlier — a
  photograph traces to ~87,000 nodes, and the node penalty in the score
  already says what needs saying about that. Re-measure the §2 budget on
  real worker hardware before treating any of these numbers as the target.
- **`alpha_binary` scores lower than its siblings** (fidelity ~0.85). Worth
  a look before Phase 2: the alpha matting and the alpha IoU term interact.
