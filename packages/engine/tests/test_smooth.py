"""§3.7 smoothing — the part that has to tell a pixel step from a corner."""

from __future__ import annotations

import math

from engine import config
from engine.smooth import (
    SAMPLES_PER_WINDOW,
    _corners,
    _dense,
    _rdp_indices,
    smooth_doc,
    smooth_subpath,
)
from engine.svgdoc import Path, SubPath, SvgDoc


def _staircase(steps: int = 40, rise: float = 4.0) -> SubPath:
    """A 45° diagonal drawn the way a low-resolution raster draws one."""
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    x = y = 0.0
    for _ in range(steps):
        x += rise
        pts.append((x, y))
        y += rise
        pts.append((x, y))
    # Close it back along a straight edge, so the shape is a real region.
    pts.append((0.0, y))
    segments = [("L", (p,)) for p in pts[1:]]
    return SubPath(start=pts[0], segments=segments, closed=True)


def _square(size: float = 100.0) -> SubPath:
    pts = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    return SubPath(start=pts[0], segments=[("L", (p,)) for p in pts[1:]], closed=True)


def _doc(sp: SubPath, w: float = 200.0, h: float = 200.0) -> SvgDoc:
    return SvgDoc(width=w, height=h, paths=[Path(subpaths=[sp])])


def test_a_staircase_is_not_a_run_of_corners():
    """Measured between neighbouring samples every step is a 90° corner, and
    32-38% of the real logo's contour was flagged that way — which pins the
    contour in place and smooths nothing."""
    sp = _staircase()
    pts = _dense(sp, 20.0 / SAMPLES_PER_WINDOW)
    corners = _corners(pts, sp.closed, window=20.0)
    assert sum(corners) <= 6, f"a staircase reported {sum(corners)} corners"


def test_a_real_corner_survives():
    """The other half: a square is four corners and must stay four corners,
    or smoothing rounds off artwork the customer drew on purpose."""
    sp = _square()
    pts = _dense(sp, 12.0 / SAMPLES_PER_WINDOW)
    corners = _corners(pts, sp.closed, window=12.0)
    assert 3 <= sum(corners) <= 8


def test_a_square_keeps_its_corners_through_smoothing():
    """End to end, on geometry whose right answer is known exactly: the
    corner points must still be present in the output."""
    doc = _doc(_square())
    doc, touched = smooth_doc(doc, 8, tolerance=0.2)
    assert touched == 1
    pts = doc.paths[0].subpaths[0].points()
    for corner in ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)):
        assert min(math.dist(corner, p) for p in pts) < 4.0, f"lost the corner at {corner}"


def _roughness(pts: list[tuple[float, float]]) -> float:
    """Total turning along the diagonal run, in degrees.

    Not distance from the ideal diagonal: smoothing a closed shape also
    pulls it very slightly inward, so a distance metric scores shrinkage
    and jaggedness together and cannot tell which it is looking at. Total
    turning is zero for any straight line, wherever it sits.
    """
    run = [p for p in pts if 1.0 < p[0] < 155.0 and p[1] > 1.0]
    total = 0.0
    for i in range(1, len(run) - 1):
        ax, ay = run[i][0] - run[i - 1][0], run[i][1] - run[i - 1][1]
        bx, by = run[i + 1][0] - run[i][0], run[i + 1][1] - run[i][1]
        na, nb = math.hypot(ax, ay), math.hypot(bx, by)
        if na == 0 or nb == 0:
            continue
        cos = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
        total += math.degrees(math.acos(cos))
    return total


def test_smoothing_flattens_the_staircase():
    """A 45° staircase is the customer's complaint in its purest form: it
    should come back as the straight line it is drawing."""
    sp = _staircase()
    step = 20.0 / SAMPLES_PER_WINDOW
    before = _roughness(_dense(sp, step))
    after = _roughness(_dense(smooth_subpath(sp, window=20.0, tolerance=0.2), step))
    assert after < before * 0.2, f"turning went {before:.0f}° -> {after:.0f}°"


def test_level_zero_changes_nothing():
    doc = _doc(_staircase())
    before = doc.paths[0].subpaths[0].points()
    doc, touched = smooth_doc(doc, 0, tolerance=0.2)
    assert touched == 0
    assert doc.paths[0].subpaths[0].points() == before


def test_stronger_levels_smooth_more():
    """The slider has to mean something across its range, and the window
    has to stay wider than the steps it is removing — at a window below the
    step size the filter chased the staircase and made it rougher."""
    sp = _staircase()

    def rough(level: int) -> float:
        window = level / 10 * config.SMOOTH_MAX_WINDOW_FRACTION * math.hypot(200.0, 200.0)
        return _roughness(
            _dense(smooth_subpath(sp, window=window, tolerance=0.2), window / SAMPLES_PER_WINDOW)
        )

    assert rough(9) <= rough(4)


def test_rdp_indices_match_the_points_they_name():
    """The corner test reads points back through these indices, so an
    off-by-one here would silently move every corner."""
    pts = _dense(_square(), 4.0)
    idx = _rdp_indices(pts, 1.0)
    assert idx[0] == 0 and idx[-1] == len(pts) - 1
    assert idx == sorted(set(idx))
