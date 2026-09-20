"""`make bench` — per-category means plus per-image regression (§3.9).

CI fails any PR that lowers a category mean by more than 0.005 unless the
PR body justifies it. Without this gate, quality drifts invisibly: every
individual change looks harmless and the corpus mean walks downhill.

Seeds are fixed (engine.config.SEED) and tracer thread counts are pinned in
engine.sandbox, so runs are reproducible on the same corpus and binaries.
Scores from different `score_version`s are never compared — a version
mismatch against the baseline is a hard error, not a warning.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import fixtures
from engine.errors import EngineError
from engine.pipeline import run
from engine.score import SCORE_VERSION
from engine.types import Options
from engine.version import ENGINE_VERSION

BASELINE = ROOT / "baseline.json"
REGRESSION_TOLERANCE = 0.005


def corpus() -> list[tuple[str, bytes, str]]:
    """Synthetic fixtures plus any real images dropped into corpus/real/.

    §3.9 wants 60–100 hand-labelled real images. Until they exist the
    category means are indicative only — see docs/runbook.md.
    """
    items = [(f.name, f.data, f.label) for f in fixtures.all_fixtures()]
    real = ROOT / "corpus" / "real"
    labels_file = real / "labels.json"
    if labels_file.exists():
        labels = json.loads(labels_file.read_text())
        for path in sorted(real.iterdir()):
            if path.name == "labels.json" or not path.is_file():
                continue
            entry = labels.get(path.name)
            if not entry:
                print(f"warning: {path.name} has no label, skipping", file=sys.stderr)
                continue
            items.append((path.stem, path.read_bytes(), entry["label"]))
    return items


def measure(tier: str = "standard") -> dict:
    rows: dict[str, dict] = {}
    for name, data, label in corpus():
        started = time.perf_counter()
        try:
            result = run(data, Options(quality_tier=tier))
        except EngineError as exc:
            rows[name] = {"label": label, "error": f"{exc.error_code}: {exc}"}
            print(f"{name:28s} FAILED {exc.error_code}", flush=True)
            continue
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        rows[name] = {
            "label": label,
            "classification": result.profile.classification,
            "total": result.score.total,
            "fidelity": result.score.fidelity,
            "nodes": result.score.nodes,
            "paths": result.score.paths,
            "elapsed_ms": elapsed_ms,
            "warnings": result.warnings,
        }
        print(
            f"{name:28s} {result.profile.classification:14s} "
            f"total={result.score.total:.4f} fidelity={result.score.fidelity:.4f} "
            f"nodes={result.score.nodes:6d} {elapsed_ms:6d}ms",
            flush=True,
        )
    return {
        "score_version": SCORE_VERSION,
        "engine_version": ENGINE_VERSION,
        "tier": tier,
        "images": rows,
    }


def category_means(report: dict) -> dict[str, dict[str, float]]:
    by_class: dict[str, list[dict]] = defaultdict(list)
    for row in report["images"].values():
        if "error" not in row:
            by_class[row["label"]].append(row)
    return {
        label: {
            "total": statistics.fmean(r["total"] for r in rows),
            "fidelity": statistics.fmean(r["fidelity"] for r in rows),
            "n": len(rows),
        }
        for label, rows in sorted(by_class.items())
    }


def compare(report: dict, baseline: dict) -> list[str]:
    if baseline["score_version"] != report["score_version"]:
        message = (
            f"score_version changed ({baseline['score_version']} → "
            f"{report['score_version']}): regenerate baseline.json in the same PR. "
            "Scores from different versions are never compared."
        )
        return [message]

    failures: list[str] = []
    new_means = category_means(report)
    old_means = category_means(baseline)
    for label, old in old_means.items():
        new = new_means.get(label)
        if new is None:
            failures.append(f"{label}: category disappeared from the corpus")
            continue
        drop = old["total"] - new["total"]
        if drop > REGRESSION_TOLERANCE:
            failures.append(
                f"{label}: mean total fell {drop:.4f} "
                f"({old['total']:.4f} → {new['total']:.4f}), limit {REGRESSION_TOLERANCE}"
            )

    for name, old_row in baseline["images"].items():
        new_row = report["images"].get(name)
        if new_row is None:
            continue
        if "error" in new_row and "error" not in old_row:
            failures.append(f"{name}: now fails ({new_row['error']})")
    return failures


def print_summary(report: dict, baseline: dict | None) -> None:
    print("\ncategory means")
    print(f"  {'category':16s} {'n':>3s} {'total':>8s} {'fidelity':>9s} {'Δtotal':>8s}")
    old = category_means(baseline) if baseline else {}
    for label, stats in category_means(report).items():
        delta = ""
        if label in old:
            delta = f"{stats['total'] - old[label]['total']:+.4f}"
        print(
            f"  {label:16s} {stats['n']:3d} {stats['total']:8.4f} "
            f"{stats['fidelity']:9.4f} {delta:>8s}"
        )
    timings = [r["elapsed_ms"] for r in report["images"].values() if "elapsed_ms" in r]
    if timings:
        timings.sort()
        p95 = timings[max(0, int(len(timings) * 0.95) - 1)]
        print(f"\nprocessing time: median {statistics.median(timings):.0f}ms  p95 {p95}ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make bench")
    parser.add_argument("--tier", default="standard", choices=["fast", "standard", "max"])
    parser.add_argument("--write-baseline", action="store_true",
                        help="regenerate baseline.json (do this in the same PR as a "
                             "score_version bump)")
    parser.add_argument("--no-gate", action="store_true",
                        help="report regressions without failing")
    args = parser.parse_args(argv)

    report = measure(args.tier)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None

    if args.write_baseline:
        BASELINE.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"\nwrote {BASELINE}")
        print_summary(report, baseline)
        return 0

    print_summary(report, baseline)

    if baseline is None:
        print("\nno baseline.json — run `make bench-baseline` to create one", file=sys.stderr)
        return 0

    failures = compare(report, baseline)
    if failures:
        print("\nREGRESSION", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        if not args.no_gate:
            return 1
    else:
        print("\nno regression against baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
