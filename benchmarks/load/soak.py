"""§13: worker RSS must stay flat across a long run.

The failure this guards against is the one §4.1 already calls a scar:
OpenCV, NumPy and Pillow fragment the heap, so a worker that never
recycles its children climbs until the box OOMs at 3am. `celery`'s
`worker_max_tasks_per_child` is the guard; this is the check that the
guard works.

    python benchmarks/load/soak.py --jobs 1500 --chunk 250

§13 asks for 10,000 jobs. That is about 45 minutes here, so the default is
a shorter run: enough to cross many child recycles, which is what the
measurement is actually about. Run the full 10,000 before launch, on the
hardware you are launching on.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Stack, tiny_png

# A worker whose resident set grows by more than this across a soak is
# leaking, not just warming up.
MAX_GROWTH = 1.25


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=1500)
    parser.add_argument("--chunk", type=int, default=250)
    parser.add_argument("--timeout", type=float, default=460.0)
    parser.add_argument("--sample-every", type=float, default=4.0)
    args = parser.parse_args()

    image = tiny_png()
    samples: list[dict[str, float]] = []
    done = 0
    started = time.perf_counter()

    with Stack() as stack:
        token = stack.sign_in("soak@example.test", plan="pro")
        print(f"soaking {args.jobs} jobs in chunks of {args.chunk}\n")
        print(f"{'jobs':>6}{'elapsed':>9}{'preview RSS':>13}{'batch RSS':>11}")

        while done < args.jobs and time.perf_counter() - started < args.timeout:
            size = min(args.chunk, args.jobs - done)
            batch_id = stack.submit_batch(image, size, token)
            while time.perf_counter() - started < args.timeout:
                # Sampled on a timer, not at chunk boundaries. Prefork
                # workers recycle children, so RSS is a sawtooth: read it
                # only at the same point in each chunk and you measure the
                # phase of the saw rather than the trend of it.
                samples.append(stack.worker_rss())
                if stack.batch_state(batch_id, token)["status"] == "complete":
                    break
                time.sleep(args.sample_every)
            done += size
            latest = samples[-1] if samples else {}
            print(
                f"{done:>6}{time.perf_counter() - started:>8.0f}s"
                f"{latest.get('worker-preview', 0):>12.1f}M{latest.get('worker-batch', 0):>10.1f}M"
            )

    if len(samples) < 12:
        print("\nnot enough samples — raise --timeout or lower --sample-every")
        return 1

    third = len(samples) // 3
    print(f"\n{len(samples)} samples, {done} jobs")
    failures = []
    for worker in ("worker-preview", "worker-batch"):
        series = [sample.get(worker, 0.0) for sample in samples]
        # The p90 of a window, not its last value: high enough to see the
        # top of the sawtooth, robust to where in the cycle we sampled.
        early = percentile(series[:third], 0.9)
        late = percentile(series[-third:], 0.9)
        growth = late / early if early else 0.0
        print(
            f"  {worker}: p90 {early:.0f}M → {late:.0f}M "
            f"(peak {max(series):.0f}M) {growth:.2f}x"
        )
        if growth > MAX_GROWTH:
            failures.append(f"{worker} grew {growth:.2f}x")

    if failures:
        print("\nFAIL: " + "; ".join(failures))
        return 1
    print("\nPASS: resident memory settled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
