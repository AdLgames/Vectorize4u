"""Smoothing in contour space, where a corner and a pixel step differ.

Blurring the raster before tracing (§3.3) removes the staircase, but it
cannot tell the staircase from the artwork: the same kernel that rounds
off a two-pixel step rounds off the point of a bat wing. Measured on the
real 545 px logo at smoothing 6-8, the long arcs came back visibly wavy
*and* the sharp tips came back blunt — under-smoothed and over-smoothed
at once, which is the signature of using the wrong domain.

Along a contour the two are not alike at all. A pixel step is a short,
high-frequency wobble; a corner is a large turn sustained across it. So
this walks each subpath as a polyline, marks the genuine corners, and
low-pass filters only between them — the filter never averages across a
corner, so the corner survives exactly while the wobble either side of it
does not.

The order matters: this runs before simplification, so the refit works on
a clean contour rather than chasing every step it is about to remove.
"""

from __future__ import annotations

import math

from engine import config
from engine.geom import Point, fit_polyline
from engine.svgdoc import SubPath, SvgDoc

# A turn this sharp is artwork, not aliasing: well below the ~90° of a
# drawn corner, well above what the curvature of a smooth arc accumulates
# between two RDP vertices. Measured on the real logo, the count it gives
# is stable (17-19 corners) across a four-fold change of window, which is
# what you want from a threshold — the answer should be a property of the
# artwork, not of the setting.
CORNER_DEGREES = 50.0

# Samples per filter window. The filter can only see detail it has samples
# for, so the flattening density is tied to the window rather than to the
# segment count: a potrace trace of a staircase is *lines*, and sampling
# one line per endpoint gave the filter five points for a square — it
# collapsed to two anchors.
SAMPLES_PER_WINDOW = 8


def _dense(sp: SubPath, step: float) -> list[Point]:
    """Flatten a subpath to a polyline with roughly `step` between points."""
    step = max(step, 1e-3)
    pts: list[Point] = [sp.start]
    cursor = sp.start

    def line_to(end: Point) -> None:
        nonlocal cursor
        n = max(1, int(math.dist(cursor, end) / step))
        for i in range(1, n + 1):
            t = i / n
            pts.append((cursor[0] + (end[0] - cursor[0]) * t, cursor[1] + (end[1] - cursor[1]) * t))
        cursor = end

    for kind, args in sp.segments:
        if kind == "L":
            line_to(args[0])
            continue
        c1, c2, end = args
        # Control polygon length over-estimates the curve, which is the
        # safe direction: too many samples costs time, too few costs shape.
        rough = math.dist(cursor, c1) + math.dist(c1, c2) + math.dist(c2, end)
        n = max(2, int(rough / step))
        for i in range(1, n + 1):
            t = i / n
            mt = 1.0 - t
            a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
            pts.append(
                (
                    a * cursor[0] + b * c1[0] + c * c2[0] + d * end[0],
                    a * cursor[1] + b * c1[1] + c * c2[1] + d * end[1],
                )
            )
        cursor = end
    return pts


def _rdp_indices(pts: list[Point], epsilon: float) -> list[int]:
    """RDP, returning indices into `pts` rather than a new polyline."""
    n = len(pts)
    if n < 3 or epsilon <= 0:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = pts[lo]
        bx, by = pts[hi]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, index = -1.0, lo
        for i in range(lo + 1, hi):
            px, py = pts[i]
            if norm == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > best:
                best, index = d, i
        if best > epsilon:
            keep[index] = True
            stack.append((lo, index))
            stack.append((index, hi))
    return [i for i, k in enumerate(keep) if k]


def _corners(pts: list[Point], closed: bool, window: float) -> list[bool]:
    """Mark points where the contour genuinely turns.

    Measuring the angle between neighbouring samples calls every step of a
    staircase a 90° corner — measured, 32-38% of the points on the real
    logo's contour. Measuring it across a fixed window is no better: too
    small and the staircase still wins, too large and the curvature of a
    smooth arc accumulates past any threshold, so the arc reports corners
    all along itself.

    So the staircase is removed *before* the question is asked. RDP at an
    epsilon above the step amplitude collapses a run of steps into the
    straight line they approximate, while a real corner survives as a
    vertex — it is the one thing RDP cannot discard. The turn is then
    measured between the surviving vertices, where it means what it says.
    """
    n = len(pts)
    flags = [False] * n
    if n < 3:
        return flags

    # Half the smoothing window: comfortably above the one-to-two pixel
    # amplitude of a staircase, comfortably below any drawn feature.
    idx = _rdp_indices(pts, max(0.5, window * 0.5))
    if len(idx) < 3:
        return flags

    for k, i in enumerate(idx):
        if not closed and (k == 0 or k == len(idx) - 1):
            flags[i] = True  # an open end is a corner by definition
            continue
        before = pts[idx[k - 1]]
        after = pts[idx[(k + 1) % len(idx)]]
        ax, ay = pts[i][0] - before[0], pts[i][1] - before[1]
        bx, by = after[0] - pts[i][0], after[1] - pts[i][1]
        na, nb = math.hypot(ax, ay), math.hypot(bx, by)
        if na == 0 or nb == 0:
            continue
        cos = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
        if math.degrees(math.acos(cos)) >= CORNER_DEGREES:
            flags[i] = True
    return flags


def _filter(pts: list[Point], closed: bool, corners: list[bool], window: float) -> list[Point]:
    """Gaussian low-pass along the contour, never averaging across a corner."""
    n = len(pts)
    if n < 3 or window <= 0:
        return pts
    sigma = window / 2.0
    # Three sigma of support, expressed in samples via the median spacing —
    # the contour is flattened evenly enough that this is a fair conversion.
    spacing = sorted(
        math.dist(pts[i], pts[(i + 1) % n]) for i in range(n if closed else n - 1)
    )[max(0, (n if closed else n - 1) // 2)] or 1e-6
    half = max(1, int(window * 1.5 / spacing))

    out: list[Point] = []
    for i in range(n):
        if corners[i]:
            out.append(pts[i])
            continue
        sx = sy = wsum = 0.0
        for offset in range(-half, half + 1):
            j = i + offset
            if closed:
                j %= n
            elif not 0 <= j < n:
                break
            # Stop at the first corner in each direction: past it the
            # contour belongs to the other side of the turn.
            if offset != 0:
                step = 1 if offset > 0 else -1
                k = i
                crossed = False
                for _ in range(abs(offset)):
                    k = (k + step) % n if closed else k + step
                    if not closed and not 0 <= k < n:
                        crossed = True
                        break
                    if corners[k] and k != j:
                        crossed = True
                        break
                if crossed:
                    continue
            d = offset * spacing
            w = math.exp(-(d * d) / (2 * sigma * sigma))
            sx += pts[j][0] * w
            sy += pts[j][1] * w
            wsum += w
        out.append((sx / wsum, sy / wsum) if wsum else pts[i])
    return out


def _dedupe(pts: list[Point], closed: bool, epsilon: float) -> list[Point]:
    """Drop points the filter has collapsed onto one another.

    Smoothing pulls neighbours together, hardest where a run is short and
    pinned at both ends by corners. Two points that land in the same place
    make a zero-length segment, which a cutter reports as a degenerate
    contour and some RIPs refuse outright — found by the machine checks,
    which counted 3-5 of them per logo where the unsmoothed trace had
    none.
    """
    out: list[Point] = []
    for p in pts:
        if not out or math.dist(out[-1], p) > epsilon:
            out.append(p)
    if closed and len(out) > 2 and math.dist(out[0], out[-1]) <= epsilon:
        out.pop()
    return out


def smooth_subpath(sp: SubPath, window: float, tolerance: float) -> SubPath:
    pts = _dense(sp, window / SAMPLES_PER_WINDOW)
    if len(pts) < 4:
        return sp
    corners = _corners(pts, sp.closed, window)
    moved = _dedupe(_filter(pts, sp.closed, corners, window), sp.closed, tolerance * 0.5)
    if len(moved) < 4:
        return sp
    curves = fit_polyline(moved, tolerance)
    if not curves:
        return sp
    segments: list[tuple[str, tuple[Point, ...]]] = [
        ("C", (c1, c2, p3)) for _, c1, c2, p3 in curves
    ]
    return SubPath(start=moved[0], segments=segments, closed=sp.closed)


def smooth_doc(doc: SvgDoc, level: int, *, tolerance: float) -> tuple[SvgDoc, int]:
    """Smooth every contour in the document. Returns the doc and a count.

    `level` is the caller's 0-10. The window is a fraction of the image
    diagonal so the visible amount of rounding is the same on a 500 px logo
    and a 4000 px one — a pixel count would be invisible on one and
    dissolve the other.
    """
    if level <= 0:
        return doc, 0
    diag = math.hypot(doc.width, doc.height)
    window = min(10, level) / 10 * config.SMOOTH_MAX_WINDOW_FRACTION * diag
    if window <= 0:
        return doc, 0

    touched = 0
    for path in doc.paths:
        new_subpaths: list[SubPath] = []
        for sp in path.subpaths:
            smoothed = smooth_subpath(sp, window, tolerance)
            if smoothed is not sp:
                touched += 1
            new_subpaths.append(smoothed)
        path.subpaths = new_subpaths
    return doc, touched


__all__ = ["smooth_doc", "smooth_subpath", "CORNER_DEGREES"]
