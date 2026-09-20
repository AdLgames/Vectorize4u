"""`make ab-report` — read votes.json and apply the §12 kill switch.

vs a single default `vtracer` call: ours must be preferred on ≥ 70% of
pairs. If not, the search adds nothing a free binary doesn't, and the honest
move is to stop. Finding that out in one weekend is the most valuable thing
in the spec.

vs Vectorizer.AI: recorded, never gated. Losing on raw quality is survivable
only because §0 positions on batch and cut-correctness — but then that
positioning is mandatory, not optional.

Ties count against us: a tie means the search bought nothing visible.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KILL_SWITCH_THRESHOLD = 0.70
DEFINITION_OF_DONE_THRESHOLD = 0.80


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0]) if argv else HERE / "votes.json"
    if not path.exists():
        print(f"no votes at {path} — run `make ab` first", file=sys.stderr)
        return 1

    blob = json.loads(path.read_text())
    votes = blob["votes"]
    comparator = blob.get("comparator", "unknown")
    tally = Counter(v["choice"] for v in votes)
    total = len(votes)
    if total == 0:
        print("no votes recorded", file=sys.stderr)
        return 1

    preferred = tally["ours"] / total
    print(f"comparator: {comparator}")
    print(f"pairs voted: {total}")
    print(f"  ours:       {tally['ours']:4d}  ({preferred:.1%})")
    print(f"  comparator: {tally['comparator']:4d}")
    print(f"  tie:        {tally['tie']:4d}   (counted against us)")

    if comparator != "vtracer-default":
        print("\nRecorded, not gated. §12: losing to a paid competitor on raw quality is")
        print("survivable only if the product leads on batch and cut-correctness.")
        return 0

    print(f"\nkill switch (§12): ≥ {KILL_SWITCH_THRESHOLD:.0%} required")
    if preferred >= DEFINITION_OF_DONE_THRESHOLD:
        print(f"PASS — and clears the §13 definition of done "
              f"({DEFINITION_OF_DONE_THRESHOLD:.0%}).")
        return 0
    if preferred >= KILL_SWITCH_THRESHOLD:
        print(f"PASS — but below the §13 definition of done "
              f"({DEFINITION_OF_DONE_THRESHOLD:.0%}).")
        return 0
    print("FAIL — the scored search is not beating a single free binary call.")
    print("That is a legitimate and cheap outcome. Read §12 before writing more code.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
