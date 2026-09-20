"""Is localised refinement (§1, Phase 8) worth its nodes?

Runs each corpus fixture twice — refinement off, then on — and prints what
each region's re-trace proposed and whether the score gate kept it.

    python benchmarks/refine_report.py                # whole corpus
    python benchmarks/refine_report.py screenshot.png # one fixture

This exists because the answer is currently **no**, and a negative result
that nobody can reproduce gets quietly re-litigated every few months. The
numbers as of the synthetic corpus: proposals gain about +0.001 fidelity
for ~10% more nodes, so `total` rejects them and nothing is kept. The
corpus is small and synthetic; a real one full of customer logos with
small type is where this could earn its place, and this script is how you
would find out.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from engine import pipeline
from engine import refine as refine_mod
from engine.types import Options

CORPUS = ROOT / "benchmarks" / "corpus"


def run_one(name: str) -> None:
    data = (CORPUS / name).read_bytes()

    started = time.perf_counter()
    off = pipeline.run(data, Options(quality_tier="max", formats=("svg",)))
    off_ms = int((time.perf_counter() - started) * 1000)

    proposals: list[tuple[float, float, int]] = []
    original = refine_mod._score_doc

    def watched(doc, scorer):  # type: ignore[no-untyped-def]
        score, raster = original(doc, scorer)
        proposals.append((score.total, score.fidelity, score.nodes))
        return score, raster

    refine_mod._score_doc = watched
    try:
        started = time.perf_counter()
        on = pipeline.run(data, Options(quality_tier="max", formats=("svg",), refine=True))
        on_ms = int((time.perf_counter() - started) * 1000)
    finally:
        refine_mod._score_doc = original

    print(f"\n{name}")
    print(
        f"  off  total={off.score.total:.4f} fidelity={off.score.fidelity:.4f} "
        f"nodes={off.score.nodes:6d}  {off_ms:6d} ms"
    )
    if proposals:
        base = proposals[0]
        for total, fidelity, nodes in proposals[1:]:
            print(
                f"    proposal  total {total - base[0]:+.4f}  "
                f"fidelity {fidelity - base[1]:+.4f}  nodes x{nodes / max(1, base[2]):.2f}"
            )
    print(
        f"  on   total={on.score.total:.4f} fidelity={on.score.fidelity:.4f} "
        f"nodes={on.score.nodes:6d}  {on_ms:6d} ms  kept={on.refinements} "
        f"(refine {on.timings_ms.get('refine', 0)} ms)"
    )


def main() -> int:
    names = sys.argv[1:] or sorted(
        p.name for p in CORPUS.iterdir() if p.suffix in (".png", ".jpg")
    )
    for name in names:
        run_one(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
