"""Localised refinement: re-trace where the error actually is (§1, Phase 8).

§1 is explicit that recursively re-vectorizing a trace is worthless — it
compounds quantization error and gets monotonically worse. The one loop it
allows is this one: when scoring shows the error concentrated in a small
part of the image (small text is the usual culprit), re-trace *that region*
from the original pixels at higher detail and composite the result.

Three rules make it safe rather than a slow way to make things worse:

1. **The region is re-traced from the reference, never from the trace.**
   Same rule as the outer loop.
2. **Every composite is re-scored, and kept only if it is better.** The
   score is the arbiter, so a refinement that introduces a seam or a
   duplicate shape is discarded rather than shipped.
3. **No clipping.** A clip path would look right in a browser and export
   as unclipped geometry into DXF — a wrong cut file. Compositing is done
   by replacing whole subpaths, so every format sees the same shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from engine.color import rgb_delta_e
from engine.raster import render_svg
from engine.score import Scorer, composite, downscale
from engine.svgdoc import Path, SubPath, SvgDoc, parse_svg, serialize
from engine.types import Params, ScoreVector

# A region has to be worth the trace: at least this fraction of the canvas,
# or the gain cannot outweigh the nodes it adds.
MIN_REGION_FRACTION = 0.0008
# And it has to be *localised*. Past this, the right answer is a different
# candidate, not a patch.
MAX_REGION_FRACTION = 0.25
# The error percentile that counts as "concentrated".
ERROR_PERCENTILE = 96.0
MAX_REGIONS = 2
# How much more resolution the re-trace gets than the original trace saw.
REGION_UPSCALE = 2.0
# `total` must improve by at least this much to keep the composite. Below
# this, the difference is noise and the extra nodes are not worth it.
MIN_GAIN = 0.002
PAD_FRACTION = 0.06


@dataclass
class RefineResult:
    doc: SvgDoc
    score: ScoreVector
    regions_tried: int = 0
    regions_kept: int = 0
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)


Box = tuple[int, int, int, int]


def error_regions(scorer: Scorer, candidate: np.ndarray) -> list[Box]:
    """Boxes, in the *reference's* pixel space, where the trace is worst.

    Colour distance and edge disagreement both count: a region can match
    colour perfectly and still have lost every letterform in it.
    """
    small = candidate
    if small.shape[:2] != scorer.reference_small.shape[:2]:
        small = cv2.resize(small, scorer.size, interpolation=cv2.INTER_AREA)
    cand_rgb = composite(small)

    colour: np.ndarray = rgb_delta_e(scorer.ref_rgb, cand_rgb).astype(np.float32)
    colour = colour / max(1.0, float(colour.max()))

    ref_edges = cv2.Canny(cv2.cvtColor(scorer.ref_rgb, cv2.COLOR_RGB2GRAY), 80, 160)
    cand_edges = cv2.Canny(cv2.cvtColor(cand_rgb, cv2.COLOR_RGB2GRAY), 80, 160)
    # Edges the reference has and the trace does not: lost detail, which is
    # what refinement can actually fix. Extra edges are usually noise the
    # despeckler should handle instead.
    missing = cv2.dilate((ref_edges > 0).astype(np.uint8), np.ones((3, 3), np.uint8))
    missing[cv2.dilate((cand_edges > 0).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0] = 0

    error = colour + missing.astype(np.float32)
    if not np.isfinite(error).any() or error.max() <= 0:
        return []

    cutoff = float(np.percentile(error, ERROR_PERCENTILE))
    if cutoff <= 0:
        return []
    # Close first: scattered pixels of error are not a region, a cluster is.
    mask: np.ndarray = cv2.morphologyEx(
        (error >= cutoff).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
    )

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    height, width = mask.shape[:2]
    canvas = float(height * width)

    ranked: list[tuple[float, Box]] = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index][:5])
        if area / canvas < MIN_REGION_FRACTION:
            continue
        if (w * h) / canvas > MAX_REGION_FRACTION:
            continue
        weight = float(error[labels == index].sum())
        ranked.append((weight, (x, y, w, h)))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [box for _, box in ranked[:MAX_REGIONS]]


def _scale_box(box: Box, factor: float, limit: tuple[int, int], pad: float) -> Box:
    x, y, w, h = box
    px, py = int(w * pad) + 1, int(h * pad) + 1
    x0 = max(0, int(x * factor) - px)
    y0 = max(0, int(y * factor) - py)
    x1 = min(limit[0], int((x + w) * factor) + px)
    y1 = min(limit[1], int((y + h) * factor) + py)
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


Rect = tuple[float, float, float, float]


def _inside(bbox: Rect, box: Rect) -> bool:
    return bbox[0] >= box[0] and bbox[1] >= box[1] and bbox[2] <= box[2] and bbox[3] <= box[3]


def _subpath_bbox(sp: SubPath) -> Rect:
    xs = [p[0] for p in sp.points()]
    ys = [p[1] for p in sp.points()]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _translate_scale(doc: SvgDoc, factor: float, dx: float, dy: float) -> list[Path]:
    out: list[Path] = []
    for path in doc.paths:
        subpaths: list[SubPath] = []
        for sp in path.subpaths:
            start = (sp.start[0] * factor + dx, sp.start[1] * factor + dy)
            segments = [
                (cmd, tuple((px * factor + dx, py * factor + dy) for px, py in args))
                for cmd, args in sp.segments
            ]
            subpaths.append(SubPath(start=start, segments=segments, closed=sp.closed))
        out.append(
            Path(
                subpaths=subpaths,
                fill=path.fill,
                fill_opacity=path.fill_opacity,
                fill_rule=path.fill_rule,
            )
        )
    return out


def _composite(doc: SvgDoc, replacement: list[Path], region: Rect) -> SvgDoc:
    """Swap the geometry inside `region` for `replacement`.

    Subpaths of the original that lie wholly inside the region are dropped;
    anything crossing the boundary is kept, because a shape that continues
    outside the region is not ours to cut in half. Replacement subpaths that
    touch the boundary are dropped for the mirror-image reason: they are
    where the crop truncated a shape, not where the artwork ends.
    """
    kept: list[Path] = []
    for path in doc.paths:
        survivors = [sp for sp in path.subpaths if not _inside(_subpath_bbox(sp), region)]
        if survivors:
            kept.append(
                Path(
                    subpaths=survivors,
                    fill=path.fill,
                    fill_opacity=path.fill_opacity,
                    fill_rule=path.fill_rule,
                )
            )

    inner = (region[0] + 1.0, region[1] + 1.0, region[2] - 1.0, region[3] - 1.0)
    added: list[Path] = []
    for path in replacement:
        survivors = [sp for sp in path.subpaths if _inside(_subpath_bbox(sp), inner)]
        if survivors:
            added.append(
                Path(
                    subpaths=survivors,
                    fill=path.fill,
                    fill_opacity=path.fill_opacity,
                    fill_rule=path.fill_rule,
                )
            )

    return SvgDoc(
        width=doc.width,
        height=doc.height,
        paths=kept + added,
        phys_width=doc.phys_width,
        phys_height=doc.phys_height,
    )


def _refined_params(params: Params) -> Params:
    """The winning candidate's own parameters, unchanged.

    The obvious thing — turn the detail knobs up, since detail is what was
    lost — is measurably wrong. On the corpus it buys +0.0007 fidelity for
    2x the nodes, which `total` correctly rejects. Re-tracing the same
    region at higher *resolution* with the same parameters gets the same
    fidelity gain for about 10% more nodes.

    So the resolution does the work and the parameters stay put. See
    `benchmarks/refine_report.py` for the numbers.
    """
    return params


def _score_doc(doc: SvgDoc, scorer: Scorer) -> tuple[ScoreVector, np.ndarray]:
    svg = serialize(doc)
    raster = render_svg(svg, width=scorer.size[0])
    score = scorer.score_raster(raster, nodes=doc.node_count(), paths=doc.path_count())
    return score, raster


def refine(
    doc: SvgDoc,
    *,
    scorer: Scorer,
    trace_input: np.ndarray,
    input_scale: float,
    params: Params,
    base_score: ScoreVector,
    base_raster: np.ndarray | None = None,
) -> RefineResult:
    """Re-trace the worst regions and keep the result only if it scores better.

    `trace_input` is what the tracer saw (possibly upscaled); `input_scale`
    is its scale relative to the document's coordinates, so a region found
    in score space can be mapped into both.
    """
    from engine.trace import trace_one

    result = RefineResult(doc=doc, score=base_score)

    raster = base_raster
    if raster is None:
        _, raster = _score_doc(doc, scorer)

    regions = error_regions(scorer, raster)
    if not regions:
        return result

    # Score space → document space, and document space → trace-input space.
    to_doc = doc.width / float(scorer.size[0]) if scorer.size[0] else 1.0
    input_h, input_w = trace_input.shape[:2]

    current = doc
    current_score = base_score
    for box in regions:
        result.regions_tried += 1

        doc_box = _scale_box(box, to_doc, (int(doc.width), int(doc.height)), PAD_FRACTION)
        dx, dy, dw, dh = doc_box
        crop_box = _scale_box(doc_box, input_scale, (input_w, input_h), 0.0)
        cx, cy, cw, ch = crop_box
        if cw < 8 or ch < 8:
            continue

        crop = trace_input[cy : cy + ch, cx : cx + cw]
        enlarged = cv2.resize(
            crop,
            (max(1, int(cw * REGION_UPSCALE)), max(1, int(ch * REGION_UPSCALE))),
            interpolation=cv2.INTER_CUBIC,
        )

        traced = trace_one(enlarged, _refined_params(params))
        if traced.svg is None:
            continue

        try:
            sub = parse_svg(traced.svg)
        except Exception:  # pragma: no cover - a tracer emitting unparseable SVG
            continue

        # Back from the enlarged crop into document coordinates.
        factor = (1.0 / REGION_UPSCALE) / input_scale
        replacement = _translate_scale(
            sub, factor, float(cx) / input_scale, float(cy) / input_scale
        )
        region = (float(dx), float(dy), float(dx + dw), float(dy + dh))
        candidate_doc = _composite(current, replacement, region)

        try:
            candidate_score, _ = _score_doc(candidate_doc, scorer)
        except Exception:  # pragma: no cover - render failures are not fatal here
            continue

        # The gate. Everything above this line is a proposal.
        if candidate_score.total > current_score.total + MIN_GAIN:
            current = candidate_doc
            current_score = candidate_score
            result.regions_kept += 1
            result.boxes.append(doc_box)

    result.doc = current
    result.score = current_score
    return result


__all__ = ["RefineResult", "error_regions", "refine", "downscale"]
