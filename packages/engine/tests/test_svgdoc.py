"""The SVG model. Transform handling here has already caused one silent
geometry corruption; these tests exist so it cannot happen again."""

from __future__ import annotations

import pytest

from engine.svgdoc import SvgDoc, parse_path_d, parse_svg, serialize

VTRACER_LIKE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<path d="M0 0 L10 0 L10 10 Z" fill="#FF0000" transform="translate(5,7)"/>'
    '<path d="M0 0 L20 0 L20 20 Z" fill="#00FF00" transform="translate(30,40)"/>'
    "</svg>"
)

POTRACE_LIKE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<g transform="translate(0,100) scale(0.1,-0.1)" fill="#000000">'
    '<path d="M0 0 L100 0 L100 100 Z"/>'
    "</g></svg>"
)


def test_each_path_gets_its_own_transform():
    """vtracer stamps a translate on every path.

    Applying the first path's transform to all of them renders fine and is
    completely wrong — exactly the kind of bug that survives to production.
    """
    doc = parse_svg(VTRACER_LIKE)
    assert len(doc.paths) == 2
    assert doc.paths[0].subpaths[0].start == (5.0, 7.0)
    assert doc.paths[1].subpaths[0].start == (30.0, 40.0)


def test_group_transform_is_composed():
    doc = parse_svg(POTRACE_LIKE)
    start = doc.paths[0].subpaths[0].start
    assert start == (0.0, 100.0)
    assert doc.paths[0].subpaths[0].points()[1] == (10.0, 100.0)


def test_unsupported_transform_raises_rather_than_silently_misplacing():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<path d="M0 0 L1 1" transform="rotate(45)" fill="#000"/></svg>'
    )
    with pytest.raises(ValueError):
        parse_svg(svg)


def test_quadratic_is_converted_to_cubic():
    subs = parse_path_d("M0 0 Q10 10 20 0")
    assert len(subs) == 1
    kind, args = subs[0].segments[0]
    assert kind == "C"
    assert args[-1] == (20.0, 0.0)


def test_relative_commands():
    subs = parse_path_d("m10 10 l5 0 l0 5 z")
    assert subs[0].start == (10.0, 10.0)
    assert subs[0].points()[1] == (15.0, 10.0)
    assert subs[0].closed


def test_serialize_never_reorders_paths():
    """Grouping by colour must not restack the artwork.

    In stacked output later paths cover earlier ones. Collecting all paths
    of one colour into a single group silently corrupts the image.
    """
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<path d="M0 0 L1 0 L1 1 Z" fill="#ff0000"/>'
        '<path d="M0 0 L2 0 L2 2 Z" fill="#00ff00"/>'
        '<path d="M0 0 L3 0 L3 3 Z" fill="#ff0000"/>'
        "</svg>"
    )
    out = serialize(parse_svg(svg))
    assert out.index("#ff0000") < out.index("#00ff00") < out.rindex("#ff0000")
    assert out.count("<g ") == 3


def test_serialize_names_colour_groups():
    doc = parse_svg(VTRACER_LIKE)
    out = serialize(doc)
    assert 'id="color-ff0000"' in out
    assert 'id="color-00ff00"' in out


def test_serialize_always_carries_units_and_viewbox():
    doc = SvgDoc(width=100, height=50)
    doc.phys_width, doc.phys_height = "120mm", "60mm"
    out = serialize(doc)
    assert 'width="120mm"' in out and 'height="60mm"' in out
    assert 'viewBox="0 0 100 50"' in out


def test_roundtrip_is_stable():
    doc = parse_svg(VTRACER_LIKE)
    again = parse_svg(serialize(doc))
    assert again.node_count() == doc.node_count()
    assert [p.fill for p in again.paths] == [p.fill for p in doc.paths]
