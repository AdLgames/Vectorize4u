"""The centerline experiment (§0 non-goals, Phase 8).

It is not wired into the pipeline and it is not a feature. These tests
exist because the evaluation in docs/architecture.md rests on its numbers,
and a broken prototype would make that write-up fiction.
"""

from __future__ import annotations

import numpy as np

from engine.centerline import ink_mask, node_count, stroke_width_fraction, strokes, to_svg


def _paper(size: int = 120) -> np.ndarray:
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = 255
    return rgba


def test_a_straight_line_is_one_stroke_of_its_own_width():
    rgba = _paper()
    rgba[58:63, 20:100, :3] = 0  # a 5px horizontal bar

    found = strokes(rgba)

    assert len(found) == 1
    assert 4.0 <= found[0].width <= 6.0, found[0].width
    assert found[0].length() > 60


def test_ink_is_ink_whichever_way_round_the_image_is():
    """White artwork on a black field is the same drawing."""
    light = _paper()
    light[58:63, 20:100, :3] = 0

    dark = np.zeros_like(light)
    dark[:, :, 3] = 255
    dark[58:63, 20:100, :3] = 255

    assert ink_mask(light).sum() == ink_mask(dark).sum()


def test_filled_artwork_and_drawn_lines_are_an_order_of_magnitude_apart():
    """How centerline knows it is the wrong tool for an image. Not stroke
    width (it does not travel between image sizes) and not how much ink the
    strokes explain (a filled letter's skeleton explains all of it) — how
    wide the ink is relative to the picture."""
    line = _paper(240)
    line[119:122, 40:200, :3] = 0

    filled = _paper(240)
    filled[80:160, 80:160, :3] = 0

    drawn = stroke_width_fraction(line, strokes(line))
    solid = stroke_width_fraction(filled, strokes(filled))

    assert drawn < 0.02, drawn
    assert solid > 0.1, solid


def test_transparent_pixels_are_not_ink():
    rgba = _paper()
    rgba[58:63, 20:100, :3] = 0
    rgba[:, :, 3] = 0

    assert ink_mask(rgba).sum() == 0
    assert strokes(rgba) == []


def test_the_svg_is_stroked_and_unfilled():
    """Open paths with a stroke width — what a plotter wants, and exactly
    what SvgDoc cannot represent, which is the real cost of the feature."""
    rgba = _paper()
    rgba[58:63, 20:100, :3] = 0

    svg = to_svg(strokes(rgba), 120, 120)

    assert 'fill="none"' in svg
    assert "stroke-width=" in svg
    assert svg.count("<path") == 1


def test_node_count_is_far_below_an_outline_of_the_same_line():
    """The whole point: one path down the middle instead of a loop around
    the outside."""
    rgba = _paper()
    rgba[58:63, 20:100, :3] = 0

    assert node_count(strokes(rgba)) <= 6


def test_blank_paper_produces_nothing():
    assert strokes(_paper()) == []
