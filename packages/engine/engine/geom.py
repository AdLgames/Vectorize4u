"""Geometry primitives for post-processing: RDP, Schneider Bézier fitting,
and curve flattening.

These are small, well-understood algorithms with exact behaviour we depend
on; pulling a CAD library in for them would be a much larger dependency than
the problem deserves.
"""

from __future__ import annotations

import math

Point = tuple[float, float]


def rdp(points: list[Point], epsilon: float) -> list[Point]:
    """Ramer–Douglas–Peucker, iterative (recursion blows up on 50k-point paths)."""
    if len(points) < 3 or epsilon <= 0:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        max_d = -1.0
        index = lo
        ax, ay = points[lo]
        bx, by = points[hi]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        for i in range(lo + 1, hi):
            px, py = points[i]
            if norm == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > max_d:
                max_d, index = d, i
        if max_d > epsilon:
            keep[index] = True
            stack.append((lo, index))
            stack.append((index, hi))
    return [p for p, k in zip(points, keep, strict=True) if k]


def _bezier_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1 - t
    a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def flatten_cubic(p0: Point, p1: Point, p2: Point, p3: Point, tolerance: float) -> list[Point]:
    """Adaptive-ish flattening: segment count from the control polygon length.

    Used for DXF, where most cutters cannot read curves at all (§3.8).
    """
    poly = (
        math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    )
    n = max(2, min(64, int(math.ceil(math.sqrt(poly / max(tolerance, 1e-6)) * 2))))
    return [_bezier_point(p0, p1, p2, p3, i / n) for i in range(1, n + 1)]


def _chord_parameterise(points: list[Point]) -> list[float]:
    u = [0.0]
    for i in range(1, len(points)):
        u.append(u[-1] + math.dist(points[i], points[i - 1]))
    total = u[-1]
    if total == 0:
        return [i / max(1, len(points) - 1) for i in range(len(points))]
    return [v / total for v in u]


def _normalise(v: Point) -> Point:
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n else (0.0, 0.0)


def fit_cubic(points: list[Point], t1: Point, t2: Point) -> tuple[Point, Point, Point, Point]:
    """Least-squares cubic fit with fixed end tangents (Schneider's method)."""
    p0, p3 = points[0], points[-1]
    u = _chord_parameterise(points)
    c00 = c01 = c11 = x0 = x1 = 0.0
    for pt, ui in zip(points, u, strict=True):
        b0 = (1 - ui) ** 3
        b1 = 3 * ui * (1 - ui) ** 2
        b2 = 3 * ui * ui * (1 - ui)
        b3 = ui**3
        a1 = (t1[0] * b1, t1[1] * b1)
        a2 = (t2[0] * b2, t2[1] * b2)
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        tmp = (
            pt[0] - (b0 * p0[0] + b1 * p0[0] + b2 * p3[0] + b3 * p3[0]),
            pt[1] - (b0 * p0[1] + b1 * p0[1] + b2 * p3[1] + b3 * p3[1]),
        )
        x0 += a1[0] * tmp[0] + a1[1] * tmp[1]
        x1 += a2[0] * tmp[0] + a2[1] * tmp[1]

    det = c00 * c11 - c01 * c01
    seg_len = math.dist(p0, p3)
    if abs(det) < 1e-12:
        alpha1 = alpha2 = seg_len / 3.0
    else:
        alpha1 = (x0 * c11 - x1 * c01) / det
        alpha2 = (c00 * x1 - c01 * x0) / det
        if alpha1 < 1e-6 or alpha2 < 1e-6:
            alpha1 = alpha2 = seg_len / 3.0

    # A least-squares solve on nearly-degenerate input can return enormous
    # tangent lengths, which produce a loop that passes nowhere near the
    # points it was fitted to. Clamp, then keep whichever of the two
    # candidates actually fits better.
    limit = max(seg_len * 3.0, 1e-6)
    alpha1 = min(max(alpha1, 1e-6), limit)
    alpha2 = min(max(alpha2, 1e-6), limit)
    solved = (
        p0,
        (p0[0] + t1[0] * alpha1, p0[1] + t1[1] * alpha1),
        (p3[0] + t2[0] * alpha2, p3[1] + t2[1] * alpha2),
        p3,
    )
    third = seg_len / 3.0
    heuristic = (
        p0,
        (p0[0] + t1[0] * third, p0[1] + t1[1] * third),
        (p3[0] + t2[0] * third, p3[1] + t2[1] * third),
        p3,
    )
    return solved if fit_error(points, solved) <= fit_error(points, heuristic) else heuristic


def fit_error(points: list[Point], curve: tuple[Point, Point, Point, Point]) -> float:
    """Max distance from the sampled points to the fitted curve."""
    u = _chord_parameterise(points)
    worst = 0.0
    for pt, ui in zip(points, u, strict=True):
        q = _bezier_point(*curve, ui)
        worst = max(worst, math.dist(pt, q))
    return worst


def fit_polyline(points: list[Point], tolerance: float) -> list[tuple[Point, Point, Point, Point]]:
    """Fit a run of points with as few cubics as the tolerance allows."""
    if len(points) < 2:
        return []
    if len(points) == 2:
        p0, p3 = points
        c1 = (p0[0] + (p3[0] - p0[0]) / 3, p0[1] + (p3[1] - p0[1]) / 3)
        c2 = (p0[0] + 2 * (p3[0] - p0[0]) / 3, p0[1] + 2 * (p3[1] - p0[1]) / 3)
        return [(p0, c1, c2, p3)]

    t1 = _normalise((points[1][0] - points[0][0], points[1][1] - points[0][1]))
    t2 = _normalise((points[-2][0] - points[-1][0], points[-2][1] - points[-1][1]))
    curve = fit_cubic(points, t1, t2)
    if fit_error(points, curve) <= tolerance or len(points) <= 4:
        return [curve]
    mid = len(points) // 2
    return fit_polyline(points[: mid + 1], tolerance) + fit_polyline(points[mid:], tolerance)


def collinear_merge(points: list[Point], tolerance: float) -> list[Point]:
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    for i in range(1, len(points) - 1):
        ax, ay = out[-1]
        bx, by = points[i]
        cx, cy = points[i + 1]
        cross = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
        base = math.hypot(cx - ax, cy - ay)
        if base == 0 or cross / base > tolerance:
            out.append(points[i])
    out.append(points[-1])
    return out
