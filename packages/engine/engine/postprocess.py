"""§3.7 Post-processing, winner only.

The order below is the spec's order and it is load-bearing. Every stop rule
uses **fidelity**, never **total**: `total` rises as node count falls, so a
`total`-based stop rule would happily simplify the artwork into mush and
report an improvement.

  1. sliver removal
  2. simplification (per path type)
  3. minimum physical node spacing
  4. colour normalisation
  5. layer ordering + naming
  6. minification
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from engine import config
from engine.color import delta_e2000, from_hex, srgb_to_lab, to_hex
from engine.geom import Point, collinear_merge, fit_error, fit_polyline, rdp
from engine.raster import render_svg
from engine.score import Scorer
from engine.svgdoc import Path, SubPath, SvgDoc, serialize
from engine.types import ScoreVector, Warning_


@dataclass
class PostProcessResult:
    doc: SvgDoc
    svg: str
    score: ScoreVector
    steps: list[str]
    warnings: list[str]


def _subpath_points(sp: SubPath) -> list[Point]:
    return sp.points()


def remove_slivers(
    doc: SvgDoc, text_boxes: list[tuple[float, float, float, float]]
) -> tuple[SvgDoc, int]:
    """Drop paths below the area threshold unless they sit in a text region.

    Safe only because every candidate is traced in `stacked` mode: in cutout
    mode these shapes are holes, and deleting them punches through the art.
    """
    min_area = config.SLIVER_AREA_FRACTION * doc.width * doc.height
    kept: list[Path] = []
    dropped = 0
    for p in doc.paths:
        if p.area() >= min_area:
            kept.append(p)
            continue
        if _in_text_region(p.bbox(), text_boxes):
            kept.append(p)  # small glyph counters are the point, not noise
            continue
        dropped += 1
    doc.paths = kept
    return doc, dropped


def _in_text_region(
    bbox: tuple[float, float, float, float], boxes: list[tuple[float, float, float, float]]
) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in boxes)


def _sample_segment(
    start: Point, kind: str, args: tuple[Point, ...], per_curve: int = 8
) -> list[Point]:
    if kind == "L":
        return [args[0]]
    c1, c2, end = args
    step = 1.0 / per_curve
    pts = []
    for i in range(1, per_curve + 1):
        t = i * step
        mt = 1 - t
        a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
        pts.append(
            (
                a * start[0] + b * c1[0] + c * c2[0] + d * end[0],
                a * start[1] + b * c1[1] + c * c2[1] + d * end[1],
            )
        )
    return pts


def _merge_bezier_runs(sp: SubPath, tolerance: float) -> SubPath:
    """Refit runs of adjacent cubic segments with Schneider (§3.7 step 2).

    RDP does not apply to Béziers — running it on control points deforms the
    curve in ways that read as a rendering bug. Instead, greedily extend a
    run of segments for as long as a single cubic fits all of its sampled
    points within `tolerance`, so the error is bounded by construction and a
    tiny tolerance is a near no-op rather than a resample-and-hope.
    """
    if len(sp.segments) < 2:
        return sp

    starts: list[Point] = [sp.start]
    for _, args in sp.segments[:-1]:
        starts.append(args[-1])

    out: list[tuple[str, tuple[Point, ...]]] = []
    i = 0
    n = len(sp.segments)
    while i < n:
        best_end = i
        best_curve: tuple[Point, Point, Point, Point] | None = None
        samples: list[Point] = [starts[i]]
        for j in range(i, n):
            kind, args = sp.segments[j]
            samples.extend(_sample_segment(starts[j], kind, args))
            if j == i:
                continue  # a single segment is already its own best fit
            curves = fit_polyline(samples, tolerance)
            if len(curves) != 1:
                break
            if fit_error(samples, curves[0]) > tolerance:
                break
            best_end, best_curve = j, curves[0]
        if best_curve is None:
            out.append(sp.segments[i])
            i += 1
        else:
            _, c1, c2, end = best_curve
            out.append(("C", (c1, c2, end)))
            i = best_end + 1

    return SubPath(start=sp.start, segments=out, closed=sp.closed)


def _simplify_subpath(sp: SubPath, epsilon: float, tolerance: float) -> SubPath:
    """Polyline runs get RDP + Schneider; Bézier runs get merged in place."""
    if not sp.segments:
        return sp
    if all(kind == "L" for kind, _ in sp.segments):
        pts = collinear_merge(rdp(_subpath_points(sp), epsilon), epsilon * 0.5)
        if len(pts) < 2:
            return sp
        segments: list[tuple[str, tuple[Point, ...]]] = [
            ("C", (c1, c2, p3)) for _, c1, c2, p3 in fit_polyline(pts, tolerance)
        ]
        return SubPath(start=pts[0], segments=segments, closed=sp.closed)
    return _merge_bezier_runs(sp, tolerance)


def simplify(
    doc: SvgDoc,
    scorer: Scorer,
    baseline_fidelity: float,
    *,
    max_steps: int = config.SIMPLIFY_MAX_STEPS,
) -> tuple[SvgDoc, ScoreVector | None, int, bool]:
    """Geometric schedule on the image diagonal, re-scoring after each step.

    Stops as soon as `fidelity` drops more than 2% below its value before
    simplification started.
    """
    diag = math.hypot(doc.width, doc.height)
    # The stop rule compares like with like: the floor is re-measured on the
    # same reduced-resolution scorer the trial steps use, because fidelity is
    # not identical across resolutions.
    fast = scorer.reduced(config.SCORE_SIMPLIFY_MAX_SIDE)
    del baseline_fidelity
    try:
        pre_score = fast.score_raster(
            render_svg(serialize(doc), width=fast.size[0]),
            nodes=doc.node_count(),
            paths=doc.path_count(),
        )
    except Exception:
        return doc, None, 0, True
    floor = pre_score.fidelity * (1.0 - config.SIMPLIFY_FIDELITY_DROP)

    best_doc = doc
    best_score: ScoreVector | None = None
    applied = 0
    stopped_early = False

    for step in range(1, max_steps + 1):
        epsilon = diag * 0.0004 * (1.6 ** (step - 1))
        tolerance = epsilon * 1.5
        trial = SvgDoc(
            width=doc.width,
            height=doc.height,
            phys_width=doc.phys_width,
            phys_height=doc.phys_height,
            paths=[
                Path(
                    subpaths=[_simplify_subpath(sp, epsilon, tolerance) for sp in p.subpaths],
                    fill=p.fill,
                    fill_opacity=p.fill_opacity,
                    fill_rule=p.fill_rule,
                )
                for p in best_doc.paths
            ],
        )
        try:
            raster = render_svg(serialize(trial), width=fast.size[0])
        except Exception:
            stopped_early = True
            break
        score = fast.score_raster(raster, nodes=trial.node_count(), paths=trial.path_count())
        if score.fidelity < floor:
            stopped_early = True
            break
        best_doc, best_score, applied = trial, score, step

    return best_doc, best_score, applied, stopped_early


def enforce_node_spacing(doc: SvgDoc, min_spacing_px: float) -> tuple[SvgDoc, int]:
    """§3.7 step 3 — absolute minimum distance between adjacent nodes.

    Dense node clusters make vinyl blades tear material and confuse laser
    controllers. This is measured in real millimetres converted to user
    units, never in pixels-as-such.
    """
    if min_spacing_px <= 0:
        return doc, 0
    removed = 0
    for p in doc.paths:
        for sp in p.subpaths:
            if len(sp.segments) < 3:
                continue
            kept: list[tuple[str, tuple[Point, ...]]] = []
            cursor = sp.start
            for kind, args in sp.segments:
                end = args[-1]
                if math.dist(cursor, end) < min_spacing_px and kept:
                    # Collapse into the previous segment by retargeting it.
                    prev_kind, prev_args = kept[-1]
                    if prev_kind == "C":
                        kept[-1] = ("C", (prev_args[0], prev_args[1], end))
                    else:
                        kept[-1] = ("L", (end,))
                    cursor = end
                    removed += 1
                    continue
                kept.append((kind, args))
                cursor = end
            if len(kept) >= 2:
                sp.segments = kept
    return doc, removed


def normalise_colors(doc: SvgDoc) -> tuple[SvgDoc, int]:
    """Snap fills within ΔE2000 < 2.0 to one hex value.

    Vectorised over the palette on purpose: a photo trace can carry a few
    thousand distinct fills, and the obvious scalar double loop spends
    minutes computing ΔE2000 one pair at a time.

    No geometric union of adjacent shapes in v1: path booleans are a large
    dependency and a bug farm, and the merging that matters already happened
    in quantization (§3.3).
    """
    fills = list(dict.fromkeys(p.fill for p in doc.paths if p.fill.startswith("#")))
    if len(fills) < 2:
        return doc, 0

    lab = srgb_to_lab(np.array([from_hex(f) for f in fills], dtype=np.float32))
    canonical: dict[str, str] = {}
    rep_indices: list[int] = []

    for i, fill in enumerate(fills):
        if rep_indices:
            reps = lab[rep_indices]
            d = delta_e2000(np.broadcast_to(lab[i], reps.shape), reps)
            nearest = int(np.argmin(d))
            if float(d[nearest]) < config.COLOR_MERGE_DELTA_E:
                canonical[fill] = fills[rep_indices[nearest]]
                continue
        rep_indices.append(i)
        canonical[fill] = fill

    merged = 0
    for p in doc.paths:
        target = canonical.get(p.fill)
        if target and target != p.fill:
            p.fill = target
            merged += 1
    return doc, merged


def order_layers(doc: SvgDoc) -> int:
    """Count the colour groups that serialization will produce.

    Deliberately does **not** reorder. Tracer output is stacked: moving every
    path of one colour together changes which shape covers which, which turns
    a correct trace into corrupted artwork. The named `color-#RRGGBB` groups
    of §3.7 step 5 are produced at serialization time from consecutive runs.
    """
    groups = 0
    last: str | None = None
    for p in doc.paths:
        if p.fill != last:
            groups += 1
            last = p.fill
    return groups


def postprocess(
    doc: SvgDoc,
    scorer: Scorer,
    baseline_score: ScoreVector,
    *,
    text_boxes: list[tuple[float, float, float, float]] | None = None,
    min_spacing_px: float = 0.0,
    simplify_enabled: bool = True,
) -> PostProcessResult:
    steps: list[str] = []
    warnings: list[str] = []

    doc, dropped = remove_slivers(doc, text_boxes or [])
    if dropped:
        steps.append(f"slivers_removed:{dropped}")

    score = baseline_score
    if simplify_enabled and doc.node_count() > config.SIMPLIFY_MAX_NODES:
        simplify_enabled = False
        warnings.append(Warning_.SIMPLIFY_SKIPPED_LARGE.value)
    if simplify_enabled:
        doc, simplified_score, applied, stopped_early = simplify(
            doc, scorer, baseline_score.fidelity
        )
        if applied:
            steps.append(f"simplify:{applied}")
        if simplified_score is not None:
            score = simplified_score
        if stopped_early and applied < config.SIMPLIFY_MAX_STEPS:
            warnings.append(Warning_.SIMPLIFY_STOPPED_EARLY.value)

    doc, collapsed = enforce_node_spacing(doc, min_spacing_px)
    if collapsed:
        steps.append(f"node_spacing:{collapsed}")
        warnings.append(Warning_.NODE_SPACING_ENFORCED.value)

    doc, merged = normalise_colors(doc)
    if merged:
        steps.append(f"colors_merged:{merged}")

    steps.append(f"layers_named:{order_layers(doc)}")

    svg = serialize(doc, decimals=config.COORD_DECIMALS)
    steps.append("minified")

    # Re-score the artifact we actually ship. The steps after simplification
    # are small, but reporting a score for a document we then edited would be
    # exactly the kind of circularity §3.6 warns about.
    try:
        raster = render_svg(svg, width=scorer.size[0])
        score = scorer.score_raster(raster, nodes=doc.node_count(), paths=doc.path_count())
    except Exception:  # pragma: no cover - renderer failure mid-pipeline
        pass

    return PostProcessResult(doc=doc, svg=svg, score=score, steps=steps, warnings=warnings)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return from_hex(value)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return to_hex(rgb)
