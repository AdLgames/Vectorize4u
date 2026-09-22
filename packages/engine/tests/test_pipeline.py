"""End-to-end behaviour. These are the promises §13 makes to the buyer."""

from __future__ import annotations

import pytest

from engine.pipeline import run, run_single
from engine.svgdoc import parse_svg
from engine.types import Options, Params, Warning_
from tests.conftest import needs_resvg, needs_vtracer

pytestmark = [needs_vtracer, needs_resvg]


@pytest.fixture(scope="module")
def flat_result(fx):
    return run(fx.by_name("logo_flat").data, Options(output_width=120, units="mm"))


def test_produces_svg_with_physical_size(flat_result):
    assert flat_result.svg.startswith("<svg")
    assert 'width="120.0000mm"' in flat_result.svg
    assert "viewBox=" in flat_result.svg
    assert flat_result.physical_size.source == "user"


def test_records_versions(flat_result):
    assert flat_result.engine_version
    assert flat_result.score_version == flat_result.score.score_version


def test_every_candidate_is_scored_and_persistable(flat_result):
    assert len(flat_result.candidates) >= 2
    assert sum(c.selected for c in flat_result.candidates) == 1
    for candidate in flat_result.candidates:
        row = candidate.as_row()
        assert set(row) >= {"params", "score", "selected", "duration_ms", "exit_status"}


def test_winner_is_the_highest_total(flat_result):
    scored = [c for c in flat_result.candidates if c.score]
    best = max(scored, key=lambda c: c.score.total)
    assert best.selected


def test_quality_is_high_on_a_flat_logo(flat_result):
    assert flat_result.score.fidelity > 0.9
    assert flat_result.score.nodes < 2000


def test_photo_is_warned_about(fx):
    result = run(fx.by_name("photo").data, Options(quality_tier="fast"))
    assert result.profile.classification == "PHOTO"
    assert Warning_.PHOTO_INPUT.value in result.warnings


def test_gradient_is_warned_about(fx):
    result = run(fx.by_name("logo_gradient").data, Options(quality_tier="fast"))
    assert Warning_.GRADIENTS_BANDED.value in result.warnings


def test_small_input_is_warned_about(fx):
    result = run(fx.by_name("logo_flat_small").data, Options(quality_tier="fast"))
    assert Warning_.SOURCE_RESOLUTION_LOW.value in result.warnings


def test_assumed_size_is_warned_about(fx):
    result = run(fx.by_name("logo_flat").data, Options(quality_tier="fast"))
    assert Warning_.PHYSICAL_SIZE_ASSUMED.value in result.warnings
    assert result.physical_size.source == "assumed"


def test_transparency_survives(fx):
    result = run(fx.by_name("alpha_binary").data, Options(quality_tier="fast"))
    assert result.profile.has_alpha
    assert result.profile.alpha_is_binary


def test_tier_controls_candidate_count(fx):
    data = fx.by_name("logo_flat").data
    fast = run(data, Options(quality_tier="fast"))
    standard = run(data, Options(quality_tier="standard"))
    assert len(fast.candidates) == 1
    assert len(standard.candidates) == 4


def test_forced_params_run_a_single_trace(fx):
    """The advanced panel re-runs one trace, not the whole search (§7.6)."""
    result = run_single(fx.by_name("logo_flat").data, Params(color_precision=4))
    assert len(result.candidates) == 1
    assert result.chosen_params.color_precision == 4


def test_simplification_reduces_nodes_without_losing_fidelity(fx):
    data = fx.by_name("logo_flat").data
    simplified = run(data, Options(simplify=True))
    raw = run(data, Options(simplify=False))
    assert simplified.score.nodes <= raw.score.nodes
    assert simplified.score.fidelity > raw.score.fidelity * 0.98 - 1e-9


def test_output_is_parseable_and_grouped(flat_result):
    doc = parse_svg(flat_result.svg)
    assert doc.path_count() > 0
    assert 'id="color-' in flat_result.svg


def test_timings_cover_every_stage(flat_result):
    assert set(flat_result.timings_ms) >= {
        "ingest", "analyse", "preprocess", "trace", "score", "postprocess", "emit"
    }


# -- banding is warned about on the evidence, not on the label -------------


def test_banding_is_warned_about_whatever_the_class_was_called():
    """§0 promises we detect, warn, and do the best banded trace.

    The warning used to fire only when the classifier said LOGO_GRADIENT.
    A gradient logo it called LOGO_FLAT — which is what happens at the 0.46
    confidence both real-world images landed on — came back as hundreds of
    flat colour bands with nothing said about it. What the trace produced
    is not in doubt the way the label is.
    """
    from engine.pipeline import banding_warnings

    assert banding_warnings("LOGO_FLAT", 460) == ["gradients_banded"]
    assert banding_warnings("LOGO_GRADIENT", 460) == ["gradients_banded"]


def test_a_flat_logo_is_not_accused_of_banding():
    """Single figures are what a clean logo traces to, so the threshold has
    to sit well above them or every good result carries a scary notice."""
    from engine.pipeline import banding_warnings

    assert banding_warnings("LOGO_FLAT", 8) == []
    assert banding_warnings("LOGO_FLAT", 11) == []


def test_a_screenshot_is_not_banded_just_because_it_has_many_paths():
    """A screenshot genuinely is hundreds of rectangles."""
    from engine.pipeline import banding_warnings

    assert banding_warnings("SCREENSHOT", 3444) == []
    assert banding_warnings("PHOTO", 90000) == []


def test_simplification_never_collapses_a_contour(fx):
    """RDP and the refit both move nodes, and on a contour a couple of
    units across they can flatten it onto its own axis.

    Measured on the real Batman trace, seven subpaths went into §3.7 with
    areas of 0.86 to 2.23 and came out at exactly 0.0 — contours enclosing
    nothing, which render as nothing while a cutter still drives the blade
    around them. Simplification keeps the original in that case.
    """
    from engine.svgdoc import parse_svg

    for name in ("logo_flat", "logo_flat_small", "sketch", "line_art"):
        doc = parse_svg(run(fx.by_name(name).data, Options(simplify=True)).svg)
        flat = [
            f"{pi}.{si}"
            for pi, p in enumerate(doc.paths)
            for si, sp in enumerate(p.subpaths)
            if abs(sp.area()) <= 1e-6
        ]
        assert not flat, f"{name} shipped contours enclosing no area: {flat}"
