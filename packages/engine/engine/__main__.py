"""`python -m engine in.png out.svg` — the offline entry point.

The engine must be usable and benchmarkable with no service running (§3).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.errors import EngineError
from engine.pipeline import run
from engine.types import Options


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m engine", description="Raster → vector")
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="output .svg (default: alongside input)")
    p.add_argument("--mode", default="auto",
                   choices=["auto", "flat", "lineart", "sketch", "photo"])
    p.add_argument("--tier", dest="quality_tier", default="standard",
                   choices=["fast", "standard", "max"])
    p.add_argument("--detail", default="balanced", choices=["low", "balanced", "high"])
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument("--no-simplify", dest="simplify", action="store_false")
    p.add_argument("--smoothing", type=int, default=0, choices=range(0, 11),
                   metavar="0-10",
                   help="blur the pixel staircase before tracing (0 = off)")
    p.add_argument("--alpha-mode", default="auto",
                   choices=["auto", "straight", "premultiplied"])
    p.add_argument("--width", dest="output_width", type=float, default=None,
                   help="physical output width (see --units)")
    p.add_argument("--height", dest="output_height", type=float, default=None)
    p.add_argument("--units", default="mm", choices=["mm", "in"])
    p.add_argument("--dxf-tolerance", type=float, default=0.1)
    p.add_argument("--min-node-spacing-mm", type=float, default=0.1)
    p.add_argument("--format", dest="formats", action="append", default=None,
                   choices=["svg", "dxf", "pdf", "eps", "png"])
    p.add_argument("--json", action="store_true", help="print the result summary as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formats = tuple(dict.fromkeys(["svg", *(args.formats or [])]))
    options = Options(
        mode=args.mode,
        quality_tier=args.quality_tier,
        detail=args.detail,
        max_colors=args.max_colors,
        simplify=args.simplify,
        smoothing=args.smoothing,
        alpha_mode=args.alpha_mode,
        output_width=args.output_width,
        output_height=args.output_height,
        units=args.units,
        dxf_tolerance=args.dxf_tolerance,
        min_node_spacing_mm=args.min_node_spacing_mm,
        formats=formats,
    )

    try:
        result = run(args.input.read_bytes(), options)
    except EngineError as exc:
        print(f"error [{exc.error_code}]: {exc}", file=sys.stderr)
        return 1 if exc.http_class == 400 else 2

    out = args.output or args.input.with_suffix(".svg")
    out.write_bytes(result.outputs["svg"])
    for fmt, blob in result.outputs.items():
        if fmt != "svg":
            out.with_suffix(f".{fmt}").write_bytes(blob)

    summary = {
        "output": str(out),
        "classification": result.profile.classification,
        "classification_confidence": result.profile.classification_confidence,
        "chosen_params": result.chosen_params.as_dict(),
        "quality": result.score.as_dict(),
        "physical_size": {
            "width_mm": round(result.physical_size.width_mm, 3),
            "height_mm": round(result.physical_size.height_mm, 3),
            "source": result.physical_size.source,
        },
        "warnings": result.warnings,
        "engine_version": result.engine_version,
        "timings_ms": result.timings_ms,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{out}  {result.profile.classification} "
              f"total={result.score.total:.4f} fidelity={result.score.fidelity:.4f} "
              f"nodes={result.score.nodes} paths={result.score.paths}")
        if result.warnings:
            print("warnings: " + ", ".join(result.warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
