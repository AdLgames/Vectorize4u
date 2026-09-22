"""§13 machine checks — the defects a cutter finds that the eye does not."""

from __future__ import annotations

from engine.checks import Defect, inspect, inspect_subpath, summarise
from engine.svgdoc import Path, SubPath, SvgDoc


def _closed(pts: list[tuple[float, float]]) -> SubPath:
    return SubPath(start=pts[0], segments=[("L", (p,)) for p in pts[1:]], closed=True)


def _doc(sp: SubPath, w: float = 100.0, h: float = 100.0) -> SvgDoc:
    return SvgDoc(width=w, height=h, paths=[Path(subpaths=[sp])])


def _kinds(findings) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.defect.value for f in findings}


def test_a_clean_square_has_no_defects():
    """The floor: a shape a machine has no objection to must report none,
    or every real finding drowns in noise."""
    assert inspect(_doc(_closed([(10, 10), (90, 10), (90, 90), (10, 90)])), width_mm=100) == []


def test_a_bowtie_is_caught():
    """A contour crossing itself has no well-defined inside, so fill rule
    and cut direction both become guesses."""
    bowtie = _closed([(0, 0), (100, 100), (100, 0), (0, 100)])
    assert Defect.SELF_INTERSECTION.value in _kinds(inspect(_doc(bowtie), width_mm=100))


def test_touching_at_a_shared_endpoint_is_not_a_crossing():
    """Every pair of adjacent segments shares an endpoint. Counting that as
    an intersection would report one on every contour ever traced."""
    square = _closed([(10, 10), (90, 10), (90, 90), (10, 90)])
    assert Defect.SELF_INTERSECTION.value not in _kinds(inspect(_doc(square), width_mm=100))


def test_an_open_contour_is_caught():
    sp = SubPath(start=(10, 10), segments=[("L", ((90, 10),)), ("L", ((90, 90),))], closed=False)
    assert Defect.OPEN_CONTOUR.value in _kinds(inspect(_doc(sp), width_mm=100))


def test_a_speck_below_cut_width_is_caught():
    """0.1 mm of vinyl is not a shape, it is a hole the blade tears."""
    speck = _closed([(50.0, 50.0), (50.05, 50.0), (50.05, 50.05), (50.0, 50.05)])
    assert Defect.FEATURE_TOO_SMALL.value in _kinds(inspect(_doc(speck), width_mm=100))


def test_the_same_artwork_passes_large_and_fails_small():
    """Scale is the whole question: identical geometry is fine on a banner
    and unmakeable on a badge, so a defect list without a size is a
    statement about nothing."""
    small = _closed([(50.0, 50.0), (50.4, 50.0), (50.4, 50.4), (50.0, 50.4)])
    doc = _doc(small)
    at_badge = summarise(inspect(doc, width_mm=20))
    at_banner = summarise(inspect(_doc(small), width_mm=1000))
    assert at_badge.get(Defect.FEATURE_TOO_SMALL.value, 0) == 1
    assert at_banner.get(Defect.FEATURE_TOO_SMALL.value, 0) == 0


def test_a_zero_length_segment_is_caught():
    """Two nodes in one place: a degenerate contour some RIPs refuse."""
    sp = _closed([(10, 10), (90, 10), (90, 10), (90, 90), (10, 90)])
    assert Defect.DEGENERATE_SEGMENT.value in _kinds(inspect(_doc(sp), width_mm=100))


def test_a_spike_is_caught():
    """A near-zero angle is a blade overcut, and is nearly always a trace
    artifact rather than something the customer drew."""
    spike = _closed([(10, 50), (90, 50.2), (10, 50.4), (10, 80), (5, 80)])
    assert Defect.SPIKE.value in _kinds(inspect(_doc(spike), width_mm=100))


def test_findings_name_the_place_they_are():
    """A defect the customer cannot locate is a complaint, not a report."""
    bowtie = _closed([(0, 0), (100, 100), (100, 0), (0, 100)])
    found = inspect(_doc(bowtie), width_mm=100)
    assert found[0].where is not None
    assert "path 0.0" in str(found[0])


def test_inspect_subpath_reports_against_the_indices_it_is_given():
    sp = _closed([(0, 0), (100, 100), (100, 0), (0, 100)])
    found = inspect_subpath(
        sp,
        px_per_mm=1.0,
        min_node_mm=0.05,
        min_feature_mm=0.3,
        path_index=3,
        subpath_index=7,
    )
    assert all(f.path == 3 and f.subpath == 7 for f in found)
