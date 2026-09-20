"""`make kit` — build and self-verify the cut-correctness acceptance kit.

§13's manual acceptance test is "SVG and DXF open at the user-specified
physical size in Cricut Design Space and LightBurn", and it is the one that
matters most to the buyer. It needs a human with that software.

What it does not need is a human discovering that our own emitter was wrong
all along. So this script measures every file it produces *before* anyone
opens it: the SVG's declared physical size, the DXF's `$INSUNITS` and real
extents, and whether the geometry came out mirrored. Only files that pass
are worth your time in Design Space.

Tracing is run with simplification and speckle removal off. These are
measurement targets, not artwork — the cleanup that makes a customer's logo
better would quietly move the very edges being measured.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np
from engine.emit import MM_PER_INCH
from engine.pipeline import run
from engine.types import Options
from PIL import Image
from targets import Target, all_targets

OUT = HERE / "out"
TOLERANCE = 0.002  # 0.2%: tighter than any cutting app's own rounding


@dataclass
class Measured:
    target: Target
    svg_width: str
    svg_height: str
    svg_width_mm: float
    svg_height_mm: float
    dxf_insunits: int
    dxf_width: float
    dxf_height: float
    mirrored_x: bool
    flipped_y: bool
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems


def _expected_mm(target: Target) -> tuple[float, float]:
    width_mm = target.width if target.units == "mm" else target.width * MM_PER_INCH
    return width_mm, width_mm * target.aspect


def _parse_length_mm(value: str) -> float:
    """Parse an SVG length that is expected to be in millimetres.

    Anything else raises rather than being silently read as mm — a unitless
    SVG is the exact defect this kit exists to catch, and a parser that
    quietly accepts one would hide it.
    """
    text = value.strip()
    if not text.endswith("mm"):
        raise ValueError(f"expected a length in mm, got {value!r}")
    return float(text[:-2])


def _ink_signature(gray: np.ndarray) -> tuple[float, float]:
    """Where the ink sits, as fractions of the bounding box.

    Returns (mean x, mean y) in 0..1 with y measured downward, the same way
    the source image is indexed. Comparing this signature before and after
    export is what catches a mirror: an "F" has its mass up and to the left,
    and a flip moves it somewhere else.
    """
    ink = gray < 128
    if not ink.any():
        return 0.5, 0.5
    ys, xs = np.nonzero(ink)
    h, w = gray.shape
    return float(xs.mean() / w), float(ys.mean() / h)


def _dxf_signature(path: Path) -> tuple[float, float, float, float, int]:
    """(min_x, min_y, width, height, insunits) plus the ink signature."""
    import ezdxf

    drawing = ezdxf.readfile(path)
    insunits = int(drawing.header.get("$INSUNITS", 0))
    xs: list[float] = []
    ys: list[float] = []
    for entity in drawing.modelspace():
        for point in entity.get_points("xy"):
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs:
        return 0.0, 0.0, 0.0, 0.0, insunits
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), insunits


def _dxf_ink_signature(path: Path) -> tuple[float, float]:
    """Mean vertex position in the DXF, as fractions, with y measured DOWN.

    DXF's Y axis grows upward and an image's grows downward, so the emitter
    flips it. Reporting the signature in image coordinates means it can be
    compared directly against the source: they should match.
    """
    import ezdxf

    drawing = ezdxf.readfile(path)
    xs: list[float] = []
    ys: list[float] = []
    for entity in drawing.modelspace():
        for point in entity.get_points("xy"):
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if not xs:
        return 0.5, 0.5
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    mean_x = (sum(xs) / len(xs) - min_x) / span_x
    mean_y = (sum(ys) / len(ys) - min_y) / span_y
    return mean_x, 1.0 - mean_y  # flip back to image orientation


def build(target: Target) -> Measured:
    folder = OUT / target.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.png").write_bytes(target.data)

    result = run(
        target.data,
        Options(
            quality_tier="standard",
            output_width=target.width,
            units=target.units,  # type: ignore[arg-type]
            formats=("svg", "dxf", "pdf"),
            # Measurement targets: cleanup would move the edges being measured.
            simplify=False,
            despeckle=0,
            min_node_spacing_mm=0.0,
        ),
    )
    for fmt, blob in result.outputs.items():
        (folder / f"{target.name}.{fmt}").write_bytes(blob)

    # The detail target gets a second pair at *production* defaults. The
    # measurement pair above answers "is the scale right"; this one answers
    # the question that actually decides the blade-safety claims: what does
    # our own cleanup remove at this physical size?
    if target.name.startswith("fine-detail"):
        production = run(
            target.data,
            Options(
                quality_tier="standard",
                output_width=target.width,
                units=target.units,  # type: ignore[arg-type]
                formats=("svg", "dxf"),
            ),
        )
        for fmt, blob in production.outputs.items():
            (folder / f"{target.name}-defaults.{fmt}").write_bytes(blob)

    problems: list[str] = []
    expected_w_mm, expected_h_mm = _expected_mm(target)

    svg = result.outputs["svg"].decode("utf-8")
    svg_width = svg.split('width="', 1)[1].split('"', 1)[0]
    svg_height = svg.split('height="', 1)[1].split('"', 1)[0]
    try:
        svg_w_mm = _parse_length_mm(svg_width)
        svg_h_mm = _parse_length_mm(svg_height)
    except ValueError as exc:
        # A cutting app given a unitless SVG guesses, and the guesses differ
        # between apps. That is the whole failure this kit is here to catch.
        problems.append(f"{exc} — cutting apps will guess")
        svg_w_mm = svg_h_mm = 0.0

    if svg_w_mm and abs(svg_w_mm - expected_w_mm) > expected_w_mm * TOLERANCE:
        problems.append(f"SVG width {svg_w_mm:.3f} mm, expected {expected_w_mm:.3f} mm")
    if svg_h_mm and abs(svg_h_mm - expected_h_mm) > expected_h_mm * TOLERANCE:
        problems.append(f"SVG height {svg_h_mm:.3f} mm, expected {expected_h_mm:.3f} mm")
    if "viewBox" not in svg:
        problems.append("SVG has no viewBox")

    dxf_path = folder / f"{target.name}.dxf"
    _, _, dxf_w, dxf_h, insunits = _dxf_signature(dxf_path)
    want_units = 4 if target.units == "mm" else 1
    if insunits != want_units:
        problems.append(f"DXF $INSUNITS is {insunits}, expected {want_units} ({target.units})")
    expected_dxf_w = target.width
    expected_dxf_h = target.width * target.aspect
    if abs(dxf_w - expected_dxf_w) > expected_dxf_w * TOLERANCE:
        problems.append(f"DXF width {dxf_w:.3f} {target.units}, expected {expected_dxf_w:.3f}")
    if abs(dxf_h - expected_dxf_h) > expected_dxf_h * TOLERANCE:
        problems.append(f"DXF height {dxf_h:.3f} {target.units}, expected {expected_dxf_h:.3f}")

    with Image.open(folder / "source.png") as img:
        gray = np.asarray(img.convert("L"))
    src_x, src_y = _ink_signature(gray)
    dxf_x, dxf_y = _dxf_ink_signature(dxf_path)
    mirrored_x = abs(dxf_x - src_x) > 0.12 and abs((1 - dxf_x) - src_x) < 0.12
    flipped_y = abs(dxf_y - src_y) > 0.12 and abs((1 - dxf_y) - src_y) < 0.12
    if mirrored_x:
        problems.append("DXF geometry is mirrored left-to-right")
    if flipped_y:
        problems.append("DXF geometry is upside down")

    return Measured(
        target=target,
        svg_width=svg_width,
        svg_height=svg_height,
        svg_width_mm=svg_w_mm,
        svg_height_mm=svg_h_mm,
        dxf_insunits=insunits,
        dxf_width=dxf_w,
        dxf_height=dxf_h,
        mirrored_x=mirrored_x,
        flipped_y=flipped_y,
        problems=problems,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make kit")
    parser.add_argument("--only", help="build a single target by name")
    args = parser.parse_args(argv)

    targets = [t for t in all_targets() if not args.only or t.name == args.only]
    if not targets:
        print(f"no target named {args.only!r}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    results = [build(target) for target in targets]

    print(f"\n{'target':22s} {'SVG':>18s} {'DXF':>20s}  units  self-check")
    for m in results:
        units = "mm" if m.dxf_insunits == 4 else "in" if m.dxf_insunits == 1 else f"?{m.dxf_insunits}"
        print(
            f"{m.target.name:22s} "
            f"{m.svg_width + ' x ' + m.svg_height:>18s} "
            f"{f'{m.dxf_width:.3f} x {m.dxf_height:.3f}':>20s}"
            f"  {units:5s}  {'ok' if m.ok else 'FAIL'}"
        )
        for problem in m.problems:
            print(f"{'':22s} └─ {problem}")

    manifest = {
        "tolerance": TOLERANCE,
        "targets": [
            {
                "name": m.target.name,
                "expect": m.target.expect,
                "catches": m.target.what_it_catches,
                "svg": {"width": m.svg_width, "height": m.svg_height},
                "dxf": {
                    "insunits": m.dxf_insunits,
                    "width": round(m.dxf_width, 4),
                    "height": round(m.dxf_height, 4),
                    "units": m.target.units,
                },
                "self_check": "ok" if m.ok else m.problems,
            }
            for m in results
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    failures = [m for m in results if not m.ok]
    print(f"\nwrote {OUT}")
    if failures:
        print(
            f"\n{len(failures)} target(s) failed the self-check. "
            "Fix the emitter before opening anything in a cutting app.",
            file=sys.stderr,
        )
        return 1
    print("\nAll targets measure correctly on our side.")
    print("Next: docs/acceptance-cut-correctness.md — open them in Design Space and LightBurn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
