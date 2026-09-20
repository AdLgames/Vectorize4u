"""Is centerline tracing worth building? (§0 non-goals, Phase 8)

Runs the experimental skeleton-based centerliner in `engine/centerline.py`
against the corpus and reports what it produces next to what the shipping
outline tracer produces for the same image.

    python benchmarks/centerline_report.py

The question is not "does a skeleton come out" — it does. It is whether a
plotter-usable result comes out cheaply enough to justify a second kind of
geometry flowing through post-processing, scoring and DXF export. The
findings are written up in docs/architecture.md.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO / "packages" / "engine"))

import fixtures
from engine import centerline
from engine.ingest import ingest
from engine.pipeline import run
from engine.types import Options

# Centerline only means anything for stroke-like artwork — but the filled
# classes are printed too, because the contrast is the finding.
INTERESTING = {"LINE_ART", "SKETCH", "LOGO_FLAT", "SCREENSHOT"}


def main() -> int:
    print(
        f"{'fixture':<26}{'class':<12}{'outline n':>10}{'center n':>10}"
        f"{'strokes':>9}{'width':>8}{'w/side':>8}{'ms':>7}"
    )
    for fixture in fixtures.all_fixtures():
        outline = run(fixture.data, Options())
        if outline.profile.classification not in INTERESTING:
            continue

        ing = ingest(fixture.data)
        started = time.perf_counter()
        found = centerline.strokes(ing.rgba)
        elapsed = int((time.perf_counter() - started) * 1000)
        nodes = centerline.node_count(found)
        widths = [s.width for s in found]
        median_width = sorted(widths)[len(widths) // 2] if widths else 0.0

        fraction = centerline.stroke_width_fraction(ing.rgba, found)
        print(
            f"{fixture.name:<26}{outline.profile.classification:<12}"
            f"{outline.score.nodes:>10}{nodes:>10}{len(found):>9}"
            f"{median_width:>8.1f}{fraction:>8.3f}{elapsed:>7}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
