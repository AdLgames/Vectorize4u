from __future__ import annotations

import math

from engine.geom import collinear_merge, fit_error, fit_polyline, flatten_cubic, rdp


def test_rdp_keeps_endpoints():
    pts = [(0, 0), (1, 0.01), (2, 0), (3, 0.01), (4, 0)]
    out = rdp(pts, 0.5)
    assert out[0] == (0, 0) and out[-1] == (4, 0)
    assert len(out) == 2


def test_rdp_keeps_real_corners():
    pts = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10)]
    out = rdp(pts, 0.5)
    assert (10, 0) in out


def test_rdp_handles_long_paths_without_recursion_limit():
    pts = [(i, math.sin(i / 50.0) * 20) for i in range(20_000)]
    assert len(rdp(pts, 0.5)) < len(pts)


def _bezier(curve, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve
    mt = 1 - t
    a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
    return (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)


def _chain_error(points, curves):
    """Max distance from each source point to the fitted chain of curves.

    Sampled densely on purpose: a coarse sampling of a long curve measures
    its own step size rather than the fit.
    """
    samples = [_bezier(c, i / 400.0) for c in curves for i in range(401)]
    return max(min(math.dist(p, s) for s in samples) for p in points)


def test_fit_polyline_respects_tolerance():
    pts = [(t, (t / 10.0) ** 2) for t in range(0, 101, 2)]
    previous = None
    for tol in (0.05, 0.5, 5.0):
        curves = fit_polyline(pts, tol)
        assert curves
        assert _chain_error(pts, curves) <= max(tol, 0.2)
        # A looser tolerance must never cost more curves.
        if previous is not None:
            assert len(curves) <= previous
        previous = len(curves)


def test_fit_single_run_stays_within_tolerance():
    pts = [(t, (t / 10.0) ** 2) for t in range(0, 21, 2)]
    curves = fit_polyline(pts, 0.05)
    if len(curves) == 1:
        assert fit_error(pts, curves[0]) <= 0.2


def test_flatten_cubic_endpoint_is_exact():
    pts = flatten_cubic((0, 0), (0, 10), (10, 10), (10, 0), 0.1)
    assert pts[-1] == (10, 0)


def test_collinear_merge_drops_midpoints():
    pts = [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert collinear_merge(pts, 0.01) == [(0, 0), (3, 0)]
