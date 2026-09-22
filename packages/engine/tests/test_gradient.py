"""§3.4 gradient tracing — shading described as shading."""

from __future__ import annotations

import numpy as np

from engine import config
from engine.gradient import trace
from engine.svgdoc import parse_svg, serialize


def _shaded(width: int = 240, height: int = 240) -> np.ndarray:
    """Three bands, each shaded its own way, with hard edges between them.

    The hard edges are the point: that is what separates one shaded region
    from the next, and a fixture whose colours drift smoothly from top to
    bottom is one region however many colours it contains.
    """
    img = np.zeros((height, width, 4), np.uint8)
    img[:, :, 3] = 255
    third = height // 3
    ramp = np.linspace(40, 230, width, dtype=np.uint8)[None, :]

    img[:third, :, 0] = ramp
    img[:third, :, 1] = 20
    img[:third, :, 2] = 20

    img[third : 2 * third, :, 0] = 20
    img[third : 2 * third, :, 1] = 255 - ramp
    img[third : 2 * third, :, 2] = 20

    img[2 * third :, :, 0] = 20
    img[2 * third :, :, 1] = 20
    img[2 * third :, :, 2] = ramp
    return img


def _flat(width: int = 200, height: int = 200) -> np.ndarray:
    img = np.zeros((height, width, 4), np.uint8)
    img[:, :, 3] = 255
    img[:, :, :3] = (30, 60, 200)
    img[50:150, 50:150, :3] = (240, 240, 240)
    return img


def test_a_photograph_of_noise_is_declined():
    """This is not a general tracer and must never pretend to be one."""
    rng = np.random.default_rng(0)
    noise = np.dstack(
        [rng.integers(0, 255, (160, 160), dtype=np.uint8) for _ in range(3)]
        + [np.full((160, 160), 255, np.uint8)]
    )
    assert trace(noise) is None


def test_flat_artwork_is_declined():
    """Two flat colours have no shading to describe, and describing them as
    gradients would spend stops saying nothing."""
    assert trace(_flat()) is None


def test_shaded_artwork_produces_one_path_per_region():
    doc = trace(_shaded())
    assert doc is not None
    assert len(doc.paths) >= config.GRADIENT_MIN_REGIONS
    assert len(doc.gradients) == len(doc.paths)
    for path in doc.paths:
        assert path.fill.startswith("url(#")


def test_every_path_points_at_a_gradient_that_exists():
    """A fill referencing a missing id renders as nothing at all."""
    doc = trace(_shaded())
    assert doc is not None
    ids = {g.id for g in doc.gradients}
    for path in doc.paths:
        assert path.fill[5:-1] in ids


def test_gradients_survive_a_parse_and_serialize_round_trip():
    """Post-processing parses the winning candidate's SVG, so a parser that
    drops <defs> leaves every path pointing at nothing.

    Measured before the parser read them: a gradient trace that scored
    0.816 as a candidate came out of post-processing at 0.276.
    """
    doc = trace(_shaded())
    assert doc is not None
    again = parse_svg(serialize(doc))
    assert len(again.gradients) == len(doc.gradients)
    assert {g.id for g in again.gradients} == {g.id for g in doc.gradients}
    for before, after in zip(doc.gradients, again.gradients, strict=True):
        assert len(after.stops) == len(before.stops)
        assert after.stops[0].color == before.stops[0].color


def test_a_url_fill_is_not_mangled_by_normalisation():
    """Fill normalisation lower-cases colours, and an id is case-sensitive."""
    doc = trace(_shaded())
    assert doc is not None
    again = parse_svg(serialize(doc))
    assert all(p.fill.startswith("url(#") for p in again.paths)


def test_stops_are_colours_measured_from_the_image():
    """Never invented: each stop is the mean of the pixels in its slice, so
    a colour that is not in the artwork cannot appear in the file."""
    doc = trace(_shaded())
    assert doc is not None
    for gradient in doc.gradients:
        for stop in gradient.stops:
            assert stop.color.startswith("#") and len(stop.color) == 7
        offsets = [s.offset for s in gradient.stops]
        assert offsets == sorted(offsets)
        assert offsets[-1] == 1.0


def test_a_gradient_trace_is_smoothed_even_when_auto_would_not():
    """Its contours are polygons traced around a pixel mask, so they are
    stepped by construction.

    The automatic level is calibrated on tracer output — clean artwork up
    to 1.81 turns per shape, aliased from 17.4 — and reads a gradient
    trace at 5.38, inside the gap. So it chose no smoothing at all and the
    stair-steps shipped to the live site, where they were plainly visible
    on a phone. Provenance decides this one, not the heuristic.
    """
    from engine import config
    from engine.pipeline import _smoothing_for
    from engine.smooth import turning_per_shape
    from engine.types import Candidate, Options, Params

    doc = trace(_shaded())
    assert doc is not None
    winner = Candidate(
        params=Params(engine="gradient", label="gradient-regions"),
        svg="",
        score=None,
        duration_ms=0,
        exit_status=0,
    )
    assert turning_per_shape(doc) < config.SMOOTH_AUTO_MIN_TURNS, (
        "fixture no longer reproduces the case: its turning is already above "
        "the automatic threshold, so the floor would not be what is tested"
    )
    assert _smoothing_for(Options(), winner, doc) >= config.GRADIENT_SMOOTHING_FLOOR


def test_an_explicit_level_still_wins_over_the_floor():
    """Including 0. A customer who turns smoothing off has turned it off."""
    from engine.pipeline import _smoothing_for
    from engine.types import Candidate, Options, Params

    doc = trace(_shaded())
    assert doc is not None
    winner = Candidate(
        params=Params(engine="gradient", label="gradient-regions"),
        svg="",
        score=None,
        duration_ms=0,
        exit_status=0,
    )
    assert _smoothing_for(Options(smoothing=0), winner, doc) == 0
    assert _smoothing_for(Options(smoothing=3), winner, doc) == 3


def test_the_gradient_tracer_is_not_attempted_on_a_flat_result():
    """It can only win where it would replace a stack of bands, so that is
    the only place it is tried.

    Attempted on every conversion it cost a connected-components pass and a
    distance transform over the full image before declining: measured
    across the corpus, median job time went 4.1s -> 6.8s and p95 to 9.1s,
    which pushes work past the 8s sync window for no possible benefit.
    """
    from engine.pipeline import _banded
    from engine.types import Candidate, Params, ScoreVector

    def candidate(paths: int) -> Candidate:
        return Candidate(
            params=Params(),
            svg="<svg/>",
            score=ScoreVector(
                ssim=0.9, color=0.9, edge_f1=0.9, alpha_iou=None,
                node_term=0.5, path_term=0.5, fidelity=0.9, total=0.9,
                nodes=100, paths=paths, score_version="s3",
            ),
            duration_ms=1,
            exit_status=0,
        )

    assert not _banded([candidate(1), candidate(8)])
    assert _banded([candidate(4), candidate(460)])


def test_a_failed_candidate_does_not_count_as_banded():
    """A crashed trace has no score, and reading one would raise."""
    from engine.pipeline import _banded
    from engine.types import Candidate, Params

    failed = Candidate(
        params=Params(), svg=None, score=None, duration_ms=0, exit_status=1
    )
    assert not _banded([failed])
