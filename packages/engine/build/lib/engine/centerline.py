"""Centerline tracing — an experiment, not a feature (§0 non-goals, Phase 8).

Engravers, pen plotters and single-line CNC work want the *stroke*, not its
outline. Every tracer we ship produces outlines: a 1 px pen line comes back
as a closed loop around it, which a plotter then draws twice, once down
each side.

§0 defers this to "Phase 8+" and names the obstacle as licensing —
autotrace, the obvious tool, is GPL. That framing is worth questioning:
potrace is GPLv2 and we already ship it, as a subprocess that is never
linked (docs/licensing.md). The real obstacles are different, and this
module exists to find out what they are with a measurement instead of an
opinion.

**Nothing imports this from the pipeline.** It is reachable only from
`benchmarks/centerline_report.py`. See docs/architecture.md for what the
numbers came out as and what they imply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np

from engine.geom import Point, fit_polyline, rdp

# A skeleton branch shorter than this is a spur off a junction — a wart on
# the skeleton, not a stroke someone drew.
MIN_BRANCH_PX = 8
# Simplification before curve fitting. Skeletons are jagged at pixel scale.
RDP_EPSILON = 0.8
FIT_TOLERANCE = 1.2


@dataclass
class Stroke:
    points: list[Point]
    width: float

    def length(self) -> float:
        total = 0.0
        for (x0, y0), (x1, y1) in zip(self.points, self.points[1:], strict=False):
            total += float(np.hypot(x1 - x0, y1 - y0))
        return total


def ink_mask(rgba: np.ndarray, *, threshold: int = 128) -> np.ndarray:
    """Ink as 1, paper as 0, regardless of which is darker."""
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3] if rgba.shape[2] == 4 else None
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = (gray < threshold).astype(np.uint8)
    if alpha is not None:
        mask[alpha < 128] = 0
    # More ink than paper means the image is inverted for our purposes.
    if mask.mean() > 0.5:
        mask = 1 - mask
        if alpha is not None:
            mask[alpha < 128] = 0
    return mask


def _skeleton(mask: np.ndarray) -> np.ndarray:
    from skimage.morphology import skeletonize

    # scikit-image ships no annotations for this, and whether mypy sees it
    # as untyped depends on the version installed — which is how this
    # passed here and failed in CI. Going through `cast` states the
    # boundary once and holds for both.
    skeleton = cast(Any, skeletonize)(mask.astype(bool))
    return np.asarray(skeleton, dtype=np.uint8)


def _neighbour_count(skel: np.ndarray) -> np.ndarray:
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.uint8)
    counts = np.asarray(cv2.filter2D(skel, -1, kernel, borderType=cv2.BORDER_CONSTANT))
    return np.asarray(counts * skel)


def _walk(skel: np.ndarray) -> list[list[tuple[int, int]]]:
    """Split the skeleton into branches between endpoints and junctions."""
    counts = _neighbour_count(skel)
    marked = np.where((counts == 1) | (counts >= 3))
    nodes = {(int(y), int(x)) for y, x in zip(*marked, strict=False)}
    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    previous: tuple[int, int] | None
    branches: list[list[tuple[int, int]]] = []

    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def neighbours(p: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = p
        out = []
        for dy, dx in offsets:
            ny, nx = y + dy, x + dx
            if 0 <= ny < skel.shape[0] and 0 <= nx < skel.shape[1] and skel[ny, nx]:
                out.append((ny, nx))
        return out

    for node in sorted(nodes):
        for first in neighbours(node):
            if (node, first) in visited:
                continue
            branch = [node, first]
            visited.add((node, first))
            visited.add((first, node))
            current, previous = first, node
            while current not in nodes:
                nxt = [p for p in neighbours(current) if p != previous]
                if not nxt:
                    break
                previous, current = current, nxt[0]
                visited.add((previous, current))
                visited.add((current, previous))
                branch.append(current)
            branches.append(branch)

    if not branches and skel.any():
        # A closed loop with no endpoints and no junctions — a circle.
        ys, xs = np.where(skel)
        start = (int(ys[0]), int(xs[0]))
        branch = [start]
        previous = None
        current = start
        while True:
            nxt = [p for p in neighbours(current) if p != previous and p not in branch[-2:]]
            if not nxt:
                break
            previous, current = current, nxt[0]
            if current == start:
                break
            branch.append(current)
        branches.append(branch)

    return branches


def strokes(rgba: np.ndarray, *, threshold: int = 128) -> list[Stroke]:
    """Centerlines of the ink in `rgba`, with an estimated stroke width."""
    mask = ink_mask(rgba, threshold=threshold)
    if not mask.any():
        return []

    skel = _skeleton(mask)
    # The distance transform at a skeleton pixel is half the local stroke
    # width — which is the number a plotter actually needs.
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    out: list[Stroke] = []
    for branch in _walk(skel):
        if len(branch) < MIN_BRANCH_PX:
            continue
        points = [(float(x), float(y)) for y, x in branch]
        simplified = rdp(points, RDP_EPSILON)
        if len(simplified) < 2:
            continue
        widths = [float(distance[y, x]) * 2.0 for y, x in branch]
        out.append(Stroke(points=simplified, width=float(np.median(widths))))
    return out


def to_svg(strokes_: list[Stroke], width: int, height: int) -> str:
    """Strokes as an SVG of open paths — the shape a plotter wants.

    Note what this is *not*: `SvgDoc` models filled paths, because that is
    what both tracers emit and what every output format downstream assumes.
    Open stroked paths would need their own path through post-processing,
    scoring and DXF export, which is the real cost of this feature.
    """
    body = []
    for stroke in strokes_:
        curves = fit_polyline(stroke.points, FIT_TOLERANCE)
        if not curves:
            continue
        first = curves[0][0]
        d = [f"M{first[0]:.2f} {first[1]:.2f}"]
        for _, c1, c2, end in curves:
            d.append(f"C{c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {end[0]:.2f} {end[1]:.2f}")
        body.append(
            f'<path d="{"".join(d)}" fill="none" stroke="#000000" '
            f'stroke-width="{max(0.5, stroke.width):.2f}" stroke-linecap="round"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{"".join(body)}</svg>'
    )


def stroke_width_fraction(
    rgba: np.ndarray, strokes_: list[Stroke], *, threshold: int = 128
) -> float:
    """Mean stroke width as a fraction of the image's shorter side.

    This is the statistic that says whether centerline is the right tool
    for an image, and it took two wrong guesses to find. Stroke *width*
    alone does not travel between images of different sizes. Coverage —
    how much ink the strokes account for — does not separate the cases at
    all: a filled letter's skeleton is long and its estimated width is
    huge, so length x width still explains all of its ink.

    What separates them is how wide the ink is relative to the picture.
    Measured on the corpus:

        line art, sketches, screenshots   0.003 – 0.017
        filled logos                      0.10  – 0.36

    An order of magnitude, with nothing in between.
    """
    ink = float(ink_mask(rgba, threshold=threshold).sum())
    total = sum(stroke.length() for stroke in strokes_)
    side = float(min(rgba.shape[:2]))
    if ink <= 0 or side <= 0:
        return 0.0
    if total <= 0:
        # Ink with no skeleton left to explain it. A convex blob collapses
        # to a handful of pixels under skeletonization and its branches are
        # then dropped as too short — so "no strokes at all" is the most
        # filled case there is, not the least.
        return 1.0
    return (ink / total) / side


def node_count(strokes_: list[Stroke]) -> int:
    return sum(len(fit_polyline(s.points, FIT_TOLERANCE)) + 1 for s in strokes_)
