"""Does this file survive a machine? (§13)

`fidelity` answers "does it look like the source". It says nothing about
whether a cutter, a press or a laser will accept the geometry, and those
reject for reasons that have no bearing on appearance at all: a contour
that crosses itself, a path left open, two nodes closer together than the
machine resolves, a sliver narrower than the blade.

Every defect here is one a person hits *after* paying — on the cutting
mat, not on the screen — which is exactly the kind this pipeline should
catch first. They are reported in millimetres, because that is the unit
the machine works in and a defect measured in SVG units means nothing on
a mat.

Advisory by design: this reports, it does not edit. Silently "repairing"
a self-intersection moves artwork the customer drew.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from engine.geom import Point
from engine.smooth import _dense
from engine.svgdoc import SubPath, SvgDoc

# Vinyl blades and laser kerfs sit around 0.2-0.5 mm, and a cutter that is
# fed two nodes 0.01 mm apart either stutters or rounds them together.
# These are the defaults a plotter-shaped machine wants; a caller with a
# real machine profile should pass its own.
MIN_NODE_SPACING_MM = 0.05
MIN_FEATURE_MM = 0.3
# Below this angle a blade cannot turn without overcutting, and the spike
# is nearly always a trace artifact rather than artwork.
MIN_ANGLE_DEGREES = 8.0


class Defect(StrEnum):
    OPEN_CONTOUR = "open_contour"
    SELF_INTERSECTION = "self_intersection"
    NODE_TOO_CLOSE = "node_too_close"
    FEATURE_TOO_SMALL = "feature_too_small"
    DEGENERATE_SEGMENT = "degenerate_segment"
    SPIKE = "spike"


@dataclass(frozen=True)
class Finding:
    defect: Defect
    path: int
    subpath: int
    detail: str
    where: Point | None = None

    def __str__(self) -> str:
        at = f" at ({self.where[0]:.1f}, {self.where[1]:.1f})" if self.where else ""
        return f"{self.defect.value}: path {self.path}.{self.subpath}{at} — {self.detail}"


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Proper crossing only: touching at a shared endpoint is not a defect."""

    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = orient(c, d, a), orient(c, d, b)
    d3, d4 = orient(a, b, c), orient(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _self_intersects(pts: list[Point], closed: bool) -> Point | None:
    """Grid-bucketed pairwise test.

    A traced contour runs to thousands of points, and every pair is 25
    million comparisons on a single logo — slow enough that nobody would
    leave the check switched on. Segments are bucketed by the cells their
    bounding box covers, so only plausible neighbours are compared.
    """
    # A closed contour is usually flattened with its start point repeated
    # at the end. Left in place it makes a zero-length final segment, and
    # then the ring's genuinely adjacent first and last real segments are
    # `n - 2` apart rather than `n - 1`, so the adjacency test misses them
    # and reports a crossing where two segments merely meet. That fired on
    # every clean benchmark logo — one phantom crossing each, always at
    # the contour's own start point.
    pts = list(pts)
    while closed and len(pts) > 2 and pts[0] == pts[-1]:
        pts.pop()

    n = len(pts)
    if n < 4:
        return None
    count = n if closed else n - 1
    spans = [(pts[i], pts[(i + 1) % n]) for i in range(count)]

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    extent = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    cell = extent / 64.0
    grid: dict[tuple[int, int], list[int]] = {}

    def cells(a: Point, b: Point) -> list[tuple[int, int]]:
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        return [
            (cx, cy)
            for cx in range(int(x0 // cell), int(x1 // cell) + 1)
            for cy in range(int(y0 // cell), int(y1 // cell) + 1)
        ]

    for i, (a, b) in enumerate(spans):
        for key in cells(a, b):
            for j in grid.get(key, ()):
                # Neighbouring segments share an endpoint by construction.
                if abs(i - j) <= 1 or (closed and abs(i - j) == count - 1):
                    continue
                if _segments_cross(a, b, spans[j][0], spans[j][1]):
                    return a
            grid.setdefault(key, []).append(i)
    return None


def _angle_at(before: Point, here: Point, after: Point) -> float:
    ax, ay = before[0] - here[0], before[1] - here[1]
    bx, by = after[0] - here[0], after[1] - here[1]
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na == 0 or nb == 0:
        return 180.0
    cos = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos))


def _min_width(pts: list[Point]) -> float:
    """Shortest side of the bounding box — a cheap stand-in for cut width."""
    if len(pts) < 2:
        return 0.0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(max(xs) - min(xs), max(ys) - min(ys))


def inspect_subpath(
    sp: SubPath,
    *,
    px_per_mm: float,
    min_node_mm: float,
    min_feature_mm: float,
    path_index: int,
    subpath_index: int,
) -> list[Finding]:
    findings: list[Finding] = []

    def add(defect: Defect, detail: str, where: Point | None = None) -> None:
        findings.append(Finding(defect, path_index, subpath_index, detail, where))

    pts = sp.points()
    if not sp.closed:
        add(Defect.OPEN_CONTOUR, "a filled shape whose outline does not close", sp.start)

    min_node_px = min_node_mm * px_per_mm
    for i in range(len(pts) - 1):
        gap = math.dist(pts[i], pts[i + 1])
        if gap == 0.0:
            add(Defect.DEGENERATE_SEGMENT, "two nodes in the same place", pts[i])
        elif gap < min_node_px:
            add(
                Defect.NODE_TOO_CLOSE,
                f"nodes {gap / px_per_mm:.3f} mm apart, below {min_node_mm} mm",
                pts[i],
            )

    width_mm = _min_width(pts) / px_per_mm
    if width_mm < min_feature_mm:
        add(
            Defect.FEATURE_TOO_SMALL,
            f"{width_mm:.3f} mm across, below {min_feature_mm} mm",
            pts[0],
        )

    count = len(pts)
    if count >= 3:
        for i in range(count):
            if not sp.closed and (i == 0 or i == count - 1):
                continue
            angle = _angle_at(pts[(i - 1) % count], pts[i], pts[(i + 1) % count])
            if angle < MIN_ANGLE_DEGREES:
                add(Defect.SPIKE, f"{angle:.1f}° spike, too sharp to cut", pts[i])

    # On the flattened outline, not the anchor polygon. The anchors of a
    # perfectly ordinary curved shape can cross while its curves do not:
    # checked against the anchors, the clean 29-node benchmark logo
    # reported five crossings and a 9-node one reported one. A check that
    # cries wolf on clean artwork is worse than no check.
    outline = _dense(sp, max(0.25, _min_width(pts) / 200.0))
    crossing = _self_intersects(outline, sp.closed)
    if crossing is not None:
        add(Defect.SELF_INTERSECTION, "the outline crosses itself", crossing)

    return findings


def inspect(
    doc: SvgDoc,
    *,
    width_mm: float,
    min_node_mm: float = MIN_NODE_SPACING_MM,
    min_feature_mm: float = MIN_FEATURE_MM,
) -> list[Finding]:
    """Inspect a document at the physical size it will be cut at.

    `width_mm` is what makes this mean anything: the same artwork is fine
    on a 300 mm banner and unmakeable on a 20 mm badge, and the geometry
    is identical in both. Scale is the whole question.
    """
    if width_mm <= 0 or doc.width <= 0:
        return []
    px_per_mm = doc.width / width_mm

    findings: list[Finding] = []
    for pi, path in enumerate(doc.paths):
        for si, sp in enumerate(path.subpaths):
            findings.extend(
                inspect_subpath(
                    sp,
                    px_per_mm=px_per_mm,
                    min_node_mm=min_node_mm,
                    min_feature_mm=min_feature_mm,
                    path_index=pi,
                    subpath_index=si,
                )
            )
    return findings


def summarise(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.defect.value] = counts.get(f.defect.value, 0) + 1
    return counts


__all__ = ["Defect", "Finding", "inspect", "inspect_subpath", "summarise"]
