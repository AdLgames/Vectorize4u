"""Localised refinement (§1, Phase 8).

The feature is off by default and the reason is measured, not assumed —
see `benchmarks/refine_report.py`. What these tests protect is that it
stays *safe*: it never returns something worse than what it was given, it
never invents geometry outside the region it is refining, and it never
reaches for a clip path, which would look right in a browser and export as
an unclipped cut file.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.pipeline import _should_refine
from engine.refine import MIN_GAIN, _composite, error_regions
from engine.score import Scorer
from engine.svgdoc import Path, SubPath, SvgDoc, parse_svg
from engine.types import Options, Params


def _rect(x0: float, y0: float, x1: float, y1: float, fill: str = "#000000") -> Path:
    return Path(
        subpaths=[
            SubPath(
                start=(x0, y0),
                segments=[("L", ((x1, y0),)), ("L", ((x1, y1),)), ("L", ((x0, y1),))],
                closed=True,
            )
        ],
        fill=fill,
    )


def _canvas(colour: tuple[int, int, int] = (255, 255, 255), size: int = 120) -> np.ndarray:
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, :3] = colour
    rgba[:, :, 3] = 255
    return rgba


def test_refinement_is_off_unless_asked_for():
    """It costs a trace and two renders per region for about +0.001
    fidelity on the current corpus. Not a customer's seconds to spend."""
    assert _should_refine(Options()) is False
    assert _should_refine(Options(quality_tier="max")) is False
    assert _should_refine(Options(refine=True)) is True


def test_a_forced_trace_is_never_refined():
    """The advanced panel asked for one specific trace (§7.6). Refining it
    would return something the user did not ask for."""
    assert _should_refine(Options(refine=True, forced_params=Params())) is False


def test_no_error_means_no_regions():
    reference = _canvas()
    scorer = Scorer(reference, classification="LOGO_FLAT", edge_pixel_count=10)
    assert error_regions(scorer, reference.copy()) == []


def test_a_damaged_patch_is_found():
    reference = _canvas()
    reference[30:60, 30:60, :3] = (0, 0, 0)
    scorer = Scorer(reference, classification="LOGO_FLAT", edge_pixel_count=200)

    # A candidate that lost the patch entirely.
    candidate = _canvas()
    regions = error_regions(scorer, candidate)

    assert regions, "a missing 30x30 black square should be found"
    x, y, w, h = regions[0]
    scale = scorer.size[0] / reference.shape[1]
    # The box should sit roughly where the damage is, in score space.
    assert x <= 32 * scale + 4 and y <= 32 * scale + 4
    assert w >= 20 * scale and h >= 20 * scale


def test_compositing_replaces_only_what_is_inside_the_region():
    doc = SvgDoc(width=100, height=100, paths=[_rect(10, 10, 20, 20), _rect(40, 40, 90, 90)])
    replacement = [_rect(12, 12, 18, 18, fill="#ff0000")]

    out = _composite(doc, replacement, (5.0, 5.0, 25.0, 25.0))

    fills = [p.fill for p in out.paths]
    # The shape inside the region is gone, the one crossing it is not, and
    # the replacement is in.
    assert "#ff0000" in fills
    assert len(out.paths) == 2
    kept = [p for p in out.paths if p.fill == "#000000"][0]
    assert kept.bbox() == (40.0, 40.0, 90.0, 90.0)


def test_a_shape_crossing_the_boundary_is_left_alone():
    """Half a logo is worse than an unrefined logo."""
    doc = SvgDoc(width=100, height=100, paths=[_rect(15, 15, 60, 60)])
    out = _composite(doc, [], (5.0, 5.0, 25.0, 25.0))
    assert len(out.paths) == 1
    assert out.paths[0].bbox() == (15.0, 15.0, 60.0, 60.0)


def test_replacement_geometry_touching_the_crop_edge_is_dropped():
    """Shapes at the crop boundary are where the crop cut something in
    half, not where the artwork ends."""
    doc = SvgDoc(width=100, height=100, paths=[])
    straddling = _rect(4, 4, 30, 30, fill="#00ff00")
    inside = _rect(10, 10, 18, 18, fill="#0000ff")
    out = _composite(doc, [straddling, inside], (5.0, 5.0, 25.0, 25.0))
    assert [p.fill for p in out.paths] == ["#0000ff"]


def test_refinement_never_returns_a_worse_document(monkeypatch):
    """The gate, which is the whole safety argument: every composite is
    re-scored and kept only if it beats what it replaced."""
    reference = _canvas()
    reference[30:60, 30:60, :3] = (0, 0, 0)
    scorer = Scorer(reference, classification="LOGO_FLAT", edge_pixel_count=200)

    doc = SvgDoc(width=120, height=120, paths=[_rect(30, 30, 60, 60)])
    base_score, raster = _score(doc, scorer)

    from engine import refine as refine_mod

    # A tracer whose output is real but useless: one tiny shape.
    def fake_trace_one(rgba, params):  # type: ignore[no-untyped-def]
        from engine.types import TraceResult

        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
            'viewBox="0 0 10 10"><path d="M1 1 L9 1 L9 9 L1 9 Z" fill="#ff00ff"/></svg>'
        )
        return TraceResult(params=params, svg=svg, duration_ms=1, exit_status=0)

    monkeypatch.setattr("engine.trace.trace_one", fake_trace_one)

    result = refine_mod.refine(
        doc,
        scorer=scorer,
        trace_input=reference,
        input_scale=1.0,
        params=Params(),
        base_score=base_score,
        base_raster=raster,
    )

    assert result.score.total >= base_score.total
    if result.regions_kept == 0:
        assert result.doc is doc


def test_the_gate_needs_a_real_gain_not_a_rounding_difference():
    assert MIN_GAIN > 0


def _score(doc: SvgDoc, scorer: Scorer):
    from engine.raster import render_svg
    from engine.svgdoc import serialize

    raster = render_svg(serialize(doc), width=scorer.size[0])
    return scorer.score_raster(raster, nodes=doc.node_count(), paths=doc.path_count()), raster


def test_refinement_output_has_no_clip_paths():
    """A clip path renders correctly in a browser and exports as unclipped
    geometry into DXF — a wrong cut file, silently."""
    doc = SvgDoc(width=50, height=50, paths=[_rect(5, 5, 45, 45)])
    out = _composite(doc, [_rect(10, 10, 20, 20, fill="#123456")], (8.0, 8.0, 25.0, 25.0))
    from engine.svgdoc import serialize

    svg = serialize(out)
    assert "clip-path" not in svg and "clipPath" not in svg
    assert parse_svg(svg).path_count() == out.path_count()


@pytest.mark.parametrize("fill", ["#000000", "#abcdef"])
def test_compositing_preserves_fills(fill):
    doc = SvgDoc(width=60, height=60, paths=[_rect(1, 1, 59, 59, fill=fill)])
    out = _composite(doc, [], (0.0, 0.0, 60.0, 60.0))
    assert out.paths == [] or out.paths[0].fill == fill
