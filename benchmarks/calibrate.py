"""`make calibrate` — recompute `k_class` from evidence (§3.6, Phase 8).

`node_baseline = k_class x edge_pixel_count / 1000` decides what counts as
"too many points". The numbers in `engine/calibration.json` are Phase 1
bootstrap values: someone's estimate, not a measurement. They matter,
because if the baseline sits far below what a good trace actually needs,
every candidate is penalised equally and `node_term` stops discriminating
between them — the penalty becomes a constant, and selection silently
degenerates into pure fidelity.

This reads what good traces actually cost, per class, from either source:

    python benchmarks/calibrate.py                    # the corpus
    python benchmarks/calibrate.py --from db          # real jobs (§5)
    python benchmarks/calibrate.py --write            # update the file

**Writing the file changes every score.** `score_version` must be bumped in
the same change and `make bench-baseline` re-run, or new scores get
compared against old ones — which §3.6 is explicit is meaningless.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO / "packages" / "engine"))

CALIBRATION = REPO / "packages" / "engine" / "engine" / "calibration.json"

# Below this many samples a class's number is noise; the existing value is
# kept and the report says so rather than quietly moving it.
MIN_SAMPLES = 5
# And a class whose samples disagree with each other this much has not been
# measured either — the spread is the signal. On the synthetic corpus
# LOGO_FLAT spans 4.7 to 261 nodes per thousand edge pixels, so its median
# says nothing about what a logo "should" cost, and writing it would make
# the penalty *worse* for the clean logos at the bottom of that range.
MAX_RELATIVE_SPREAD = 0.75


def from_corpus() -> dict[str, list[float]]:
    """Run the corpus and record what the *selected* trace cost per class."""
    import fixtures
    from engine.pipeline import run
    from engine.types import Options

    samples: dict[str, list[float]] = defaultdict(list)
    for fixture in fixtures.all_fixtures():
        result = run(fixture.data, Options())
        edges = result.profile.edge_pixel_count
        if edges <= 0:
            continue
        samples[result.profile.classification].append(result.score.nodes * 1000.0 / edges)
    return samples


def from_db() -> dict[str, list[float]]:
    """The same statistic from real jobs.

    This is the point of persisting `job_candidates` and `jobs.profile`
    (§5): the dataset survives the files being deleted, so calibration can
    be redone from months of real work without keeping a single pixel.
    """
    sys.path.insert(0, str(REPO / "apps" / "api"))
    from app.db import session_scope
    from app.models import Job, JobCandidate
    from sqlalchemy import select

    samples: dict[str, list[float]] = defaultdict(list)
    with session_scope() as session:
        rows = session.execute(
            select(Job, JobCandidate)
            .join(JobCandidate, JobCandidate.job_id == Job.id)
            .where(JobCandidate.selected.is_(True), Job.status == "complete")
        ).all()
        for job, candidate in rows:
            profile = job.profile or {}
            edges = profile.get("edge_pixel_count") or 0
            nodes = candidate.node_count or 0
            classification = job.classification
            if not classification or edges <= 0 or nodes <= 0:
                continue
            samples[classification].append(nodes * 1000.0 / edges)
    return samples


def report(samples: dict[str, list[float]], *, write: bool) -> int:
    current = json.loads(CALIBRATION.read_text())
    k_class: dict[str, float] = dict(current["k_class"])

    print(f"{'class':<16}{'n':>4}{'current':>9}{'measured':>10}{'spread':>9}  verdict")
    changed = False
    for name in sorted(set(k_class) | set(samples)):
        values = samples.get(name, [])
        now = k_class.get(name, current["default_k"])
        if len(values) < MIN_SAMPLES:
            print(f"{name:<16}{len(values):>4}{now:>9.2f}{'—':>10}{'—':>9}  too few samples, kept")
            continue
        # The median, not the mean: one pathological image with ten times
        # the nodes should not move a whole class's baseline.
        measured = round(statistics.median(values), 2)
        spread = round(statistics.pstdev(values), 2)
        verdict = "unchanged"
        if spread / max(measured, 0.01) > MAX_RELATIVE_SPREAD:
            print(
                f"{name:<16}{len(values):>4}{now:>9.2f}{measured:>10.2f}{spread:>9.2f}"
                f"  too noisy to trust, kept"
            )
            continue
        if abs(measured - now) / max(now, 0.01) > 0.15:
            verdict = f"move {now:.2f} → {measured:.2f}"
            k_class[name] = measured
            changed = True
        print(f"{name:<16}{len(values):>4}{now:>9.2f}{measured:>10.2f}{spread:>9.2f}  {verdict}")

    if not write:
        print("\n(dry run — pass --write to update calibration.json)")
        return 0
    if not changed:
        print("\nnothing moved by more than 15%; file untouched")
        return 0

    current["k_class"] = k_class
    current["calibrated_at"] = "measured"
    CALIBRATION.write_text(json.dumps(current, indent=2) + "\n")
    print(f"\nwrote {CALIBRATION}")
    print("!! bump SCORE_VERSION and re-run `make bench-baseline` in this same change:")
    print("   scores from two calibrations are not comparable (§3.6).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", choices=("corpus", "db"), default="corpus")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    samples = from_db() if args.source == "db" else from_corpus()
    total = sum(len(v) for v in samples.values())
    if not total:
        print(f"no samples from {args.source}")
        return 1
    print(f"{total} samples from {args.source}\n")
    return report(samples, write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
