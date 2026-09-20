"""§13 load verification: a batch must never delay a preview.

"A 500-file batch runs to completion without raising p95 latency on
`queue_preview`" is one of §13's definition-of-done items, and it is the
one that cannot be checked by any unit test: it is a claim about a broker,
three worker pools and a scheduler under contention. Everything else in
this repository runs the worker inline, which is exactly the configuration
in which this guarantee is vacuously true.

So this starts the real thing — a Redis broker, a Postgres database, an
API process and two worker pools on separate queues — measures preview
latency with the system idle, then measures it again while a batch of N
files grinds through `queue_batch`, and compares.

    python benchmarks/load/load_test.py --files 500

Prerequisites (see the module docstring in `harness.py`): Redis and
Postgres reachable, and `VEC_DATABASE_URL` / `VEC_REDIS_URL` pointing at
them. `make load-test` sets both up locally.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Stack, tiny_png

# §4.2's promise is that batch work cannot starve the interactive lane. A
# little movement is scheduling noise; this much means the lanes are
# sharing something they should not.
MAX_P95_INFLATION = 1.5


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def summarise(name: str, samples: list[float]) -> dict[str, float]:
    out = {
        "n": len(samples),
        "p50": round(percentile(samples, 0.50), 3),
        "p95": round(percentile(samples, 0.95), 3),
        "max": round(max(samples), 3) if samples else 0.0,
        "mean": round(statistics.fmean(samples), 3) if samples else 0.0,
    }
    print(
        f"  {name:<22} n={out['n']:<4} p50={out['p50']:.3f}s "
        f"p95={out['p95']:.3f}s max={out['max']:.3f}s"
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=500)
    # The idle baseline has to be long enough to cross the same worker
    # child recycles the loaded phase does. Measuring 10 idle previews
    # against 200 loaded ones compares a run with no recycle against a run
    # with several, and reports the difference as if the batch caused it —
    # which is exactly the wrong conclusion this test drew first time.
    parser.add_argument("--baseline-previews", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument(
        "--share-cpus",
        action="store_true",
        help="run both pools on every core, the way a single machine would",
    )
    args = parser.parse_args()

    image = tiny_png()
    results: dict[str, object] = {"files": args.files}

    with Stack(pin_cpus=not args.share_cpus) as stack:
        shape = "shared cores" if args.share_cpus else "a core set each"
        print(f"API {stack.base_url}  pools: preview + batch, {shape}  files: {args.files}\n")
        token = stack.sign_in("load@example.test", plan="pro")

        # Discard the first: it pays for cold imports and a cold page
        # cache in the preview pool, and leaving it in flatters the
        # comparison — the idle p95 would carry a cost the loaded one does
        # not, and the whole test would pass for the wrong reason.
        stack.preview(image, token)

        print("idle:")
        idle = [stack.preview(image, token) for _ in range(args.baseline_previews)]
        results["idle"] = summarise("preview latency", idle)
        results["idle_health"] = summarise(
            "/health latency", [stack.health() for _ in range(args.baseline_previews)]
        )

        print(f"\nsubmitting {args.files} files…")
        started = time.perf_counter()
        batch_id = stack.submit_batch(image, args.files, token)
        submit_s = time.perf_counter() - started
        print(f"  uploaded and started in {submit_s:.1f}s")

        print("\nunder load:")
        loaded: list[float] = []
        # A control: /health touches the API and nothing else. If its tail
        # moves with the preview tail, the contention is in the API, the
        # database or the disk — not in the queue lanes, which is a
        # different problem with a different fix.
        health: list[float] = []
        progress: list[tuple[float, int]] = []
        deadline = time.perf_counter() + args.timeout
        while time.perf_counter() < deadline:
            state = stack.batch_state(batch_id, token)
            progress.append((round(time.perf_counter() - started, 1), state["completed"]))
            if state["status"] == "complete":
                break
            health.append(stack.health())
            loaded.append(stack.preview(image, token))
        batch_s = time.perf_counter() - started

        final = stack.batch_state(batch_id, token)
        results["under_load"] = summarise("preview latency", loaded)
        results["under_load_health"] = summarise("/health latency", health)
        results["batch"] = {
            "status": final["status"],
            "completed": final["completed"],
            "failed": final["failed"],
            "seconds": round(batch_s, 1),
            "files_per_second": round(final["completed"] / max(batch_s, 0.001), 2),
        }
        results["worker_rss_mb"] = stack.worker_rss()
        results["progress"] = progress[-5:]

    idle_p95 = float(results["idle"]["p95"])  # type: ignore[index]
    load_p95 = float(results["under_load"]["p95"])  # type: ignore[index]
    inflation = load_p95 / idle_p95 if idle_p95 else 0.0
    batch = results["batch"]  # type: ignore[assignment]

    print(
        f"\nbatch: {batch['completed']}/{args.files} complete, {batch['failed']} failed, "  # type: ignore[index]
        f"{batch['seconds']}s ({batch['files_per_second']}/s)"  # type: ignore[index]
    )
    print(f"worker RSS (MB): {results['worker_rss_mb']}")
    print(f"preview p95 under load / idle: {inflation:.2f}x (limit {MAX_P95_INFLATION}x)")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n")

    failures = []
    if batch["status"] != "complete":  # type: ignore[index]
        failures.append(f"batch did not finish inside {args.timeout}s")
    if batch["failed"]:  # type: ignore[index]
        failures.append(f"{batch['failed']} files failed")  # type: ignore[index]
    if inflation > MAX_P95_INFLATION:
        failures.append(
            f"batch work raised preview p95 by {inflation:.2f}x — the lanes are sharing"
        )

    if failures:
        print("\nFAIL: " + "; ".join(failures))
        return 1
    print("\nPASS: the batch ran to completion and the preview lane held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
