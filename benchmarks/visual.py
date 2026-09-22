"""Is the output fit to show a customer? (§13)

`make bench` scores fidelity, and the machine checks score geometry. A
gradient trace once passed both — 16 shapes, zero machine defects, 17 KB,
fidelity inside its margin — and shipped visibly stair-stepped, because
nothing measured the shape of the result itself. The customer found it in
about a minute on a phone.

Three layers, because "professional" is partly measurable and partly not:

  1. A roughness gate. A closed contour turns through 360° exactly once,
     so turns-per-shape is 1.0 for clean artwork and climbs with every
     stair-step. Every output this pipeline ships measures 0.90 to 2.24.
     The stepped one measured 5.38, so the gate at 3.0 sits in open space
     on both sides and would have caught it.

  2. A defect budget. Machine defects cannot be gated at zero: a sketch
     genuinely has sharp stroke ends and a screenshot genuinely has
     features below cut width. What can be gated is *growth* — the budget
     records what each file reports today, and a rise is a regression.

  3. A contact sheet. Everything above is a proxy. Whether artwork reads
     correctly — whether the inner swoosh of a logo is still there — needs
     an eye, so the sheet renders every output at a zoom where flaws are
     visible and tiles them into one image to look at in ten seconds.

    python benchmarks/visual.py              # gate + sheet
    python benchmarks/visual.py --write       # accept current as the budget
    python benchmarks/visual.py --extra DIR   # also include real customer files

Exits non-zero when the gate fails, so it can sit in front of a deploy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "engine"))

from engine.checks import inspect, summarise
from engine.pipeline import run
from engine.smooth import turning_per_shape
from engine.svgdoc import parse_svg
from engine.types import Options

BUDGET = ROOT / "benchmarks" / "visual_budget.json"
SHEET = ROOT / "benchmarks" / "visual_sheet.png"

# Measured across every output this pipeline ships: 0.90 (a clean flat
# logo) to 2.24. The stepped gradient that reached a customer measured
# 5.38. Three sits between them with room on both sides, which is what
# makes it a threshold rather than a line drawn under today's numbers.
MAX_ROUGHNESS = 3.0

# A defect count may not grow by more than this against the budget. Not
# zero, because a re-trace can legitimately shift a contour by a pixel and
# move one feature across the cut-width line.
DEFECT_SLACK = 2

# The zoom a flaw is visible at. 100% hid the stair-steps that a customer
# saw immediately on a phone, because a 500 px logo drawn at 500 px shows
# a two-pixel step as two pixels.
SHEET_ZOOM = 4


@dataclass
class Result:
    name: str
    classification: str
    roughness: float
    defects: int
    nodes: int
    paths: int
    detail: dict[str, int]
    svg: str
    width: float


def measure(path: Path) -> Result:
    engine_result = run(path.read_bytes(), Options())
    doc = parse_svg(engine_result.svg)
    findings = inspect(doc, width_mm=100.0)
    return Result(
        name=path.name,
        classification=engine_result.profile.classification,
        roughness=turning_per_shape(doc),
        defects=len(findings),
        nodes=engine_result.score.nodes,
        paths=engine_result.score.paths,
        detail=summarise(findings),
        svg=engine_result.svg,
        width=doc.width,
    )


def corpus(extra: Path | None) -> list[Path]:
    files = sorted(
        p
        for p in (ROOT / "benchmarks" / "corpus").iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    )
    if extra and extra.is_dir():
        # Real customer files, kept outside the repository: they are other
        # people's logos and redistributing them is not ours to do. Both
        # quality failures this pipeline has had came from files like
        # these and from no synthetic image, so the door stays open.
        files += sorted(
            p
            for p in extra.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        )
    return files


def contact_sheet(results: list[Result], out: Path) -> bool:
    """Render each output at a zoom where flaws show, and tile them."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    tiles: list[tuple[str, Image.Image]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for result in results:
            svg_path = Path(tmp) / f"{result.name}.svg"
            png_path = Path(tmp) / f"{result.name}.png"
            svg_path.write_text(result.svg)
            width = max(320, int(result.width * SHEET_ZOOM))
            rendered = subprocess.run(
                ["resvg", "--width", str(width), str(svg_path), str(png_path)],
                check=False,
                capture_output=True,
                timeout=60,
            )
            if rendered.returncode != 0 or not png_path.exists():
                # A tile that will not render is worth saying out loud: the
                # sheet is for looking at, and a silently missing panel is
                # a file nobody reviews.
                print(f"  ! {result.name}: resvg failed — {rendered.stderr[:120]!r}")
                continue
            image = Image.open(png_path).convert("RGBA")
            flat = Image.new("RGB", image.size, "white")
            flat.paste(image, (0, 0), image)
            tiles.append((result.name, flat))

    if not tiles:
        return False

    cell = 300
    columns = min(5, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (cell * columns, (cell + 26) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (name, image) in enumerate(tiles):
        thumb = image.copy()
        thumb.thumbnail((cell, cell), Image.LANCZOS)
        x = (index % columns) * cell
        y = (index // columns) * (cell + 26)
        sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + 26))
        draw.text((x + 6, y + 8), name[:38], fill="black")
    sheet.save(out)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="accept current as the budget")
    parser.add_argument("--extra", type=Path, default=None, help="a directory of real files")
    parser.add_argument("--no-sheet", action="store_true")
    args = parser.parse_args()

    files = corpus(args.extra)
    if not files:
        print("no images to measure", file=sys.stderr)
        return 1

    budget: dict[str, dict] = {}
    if BUDGET.exists() and not args.write:
        budget = json.loads(BUDGET.read_text())

    results = [measure(path) for path in files]

    print(f"{'file':<30}{'class':<15}{'rough':>7}{'defects':>9}{'nodes':>8}")
    failures: list[str] = []
    for result in results:
        recorded = budget.get(result.name)
        note = ""
        if result.roughness > MAX_ROUGHNESS:
            failures.append(
                f"{result.name}: roughness {result.roughness:.2f} is above {MAX_ROUGHNESS} "
                f"— the outline turns far more than its shape needs, which is what a "
                f"stair-stepped edge looks like as a number"
            )
            note = "  <-- ROUGH"
        if recorded and result.defects > recorded["defects"] + DEFECT_SLACK:
            failures.append(
                f"{result.name}: {result.defects} machine defects against "
                f"{recorded['defects']} in the budget ({result.detail})"
            )
            note = "  <-- DEFECTS"
        print(
            f"{result.name:<30}{result.classification:<15}{result.roughness:>7.2f}"
            f"{result.defects:>9}{result.nodes:>8}{note}"
        )

    if args.write:
        BUDGET.write_text(
            json.dumps(
                {
                    r.name: {"defects": r.defects, "roughness": round(r.roughness, 3)}
                    for r in results
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(f"\nwrote {BUDGET.relative_to(ROOT)}")

    if not args.no_sheet:
        if contact_sheet(results, SHEET):
            print(f"contact sheet: {SHEET.relative_to(ROOT)} (look at it)")
        else:
            print("contact sheet skipped (resvg or Pillow unavailable)")

    if failures:
        print("\nVISUAL REGRESSION", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\nevery output is within the visual budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
