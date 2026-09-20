"""§3.7 — the post-processing invariants that protect cut files."""

from __future__ import annotations

import math

from engine.postprocess import (
    enforce_node_spacing,
    normalise_colors,
    order_layers,
    remove_slivers,
)
from engine.svgdoc import Path, SubPath, SvgDoc


def _square(x: float, y: float, size: float) -> SubPath:
    return SubPath(
        start=(x, y),
        segments=[
            ("L", ((x + size, y),)),
            ("L", ((x + size, y + size),)),
            ("L", ((x, y + size),)),
            ("L", ((x, y),)),
        ],
        closed=True,
    )


def test_sliver_removal_drops_tiny_paths():
    doc = SvgDoc(width=1000, height=1000, paths=[
        Path(subpaths=[_square(0, 0, 500)], fill="#000000"),
        Path(subpaths=[_square(10, 10, 2)], fill="#ff0000"),
    ])
    doc, dropped = remove_slivers(doc, [])
    assert dropped == 1
    assert len(doc.paths) == 1


def test_sliver_removal_spares_text_regions():
    """Glyph counters are small by nature. Deleting them is the bug."""
    doc = SvgDoc(width=1000, height=1000, paths=[
        Path(subpaths=[_square(10, 10, 2)], fill="#ff0000"),
    ])
    doc, dropped = remove_slivers(doc, [(0.0, 0.0, 50.0, 50.0)])
    assert dropped == 0
    assert len(doc.paths) == 1


def test_node_spacing_collapses_dense_clusters():
    """Dense nodes make vinyl blades tear material."""
    segments = [("L", ((i * 0.05, 0.0),)) for i in range(1, 40)]
    segments.append(("L", ((50.0, 50.0),)))
    doc = SvgDoc(width=100, height=100, paths=[
        Path(subpaths=[SubPath(start=(0.0, 0.0), segments=segments, closed=True)],
             fill="#000000")
    ])
    before = doc.node_count()
    doc, removed = enforce_node_spacing(doc, min_spacing_px=1.0)
    assert removed > 0
    assert doc.node_count() < before

    sp = doc.paths[0].subpaths[0]
    pts = sp.points()
    gaps = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    assert all(g >= 1.0 or g == 0 for g in gaps[:-1])


def test_node_spacing_never_destroys_a_path():
    doc = SvgDoc(width=10, height=10, paths=[
        Path(subpaths=[_square(0, 0, 0.01)], fill="#000000")
    ])
    doc, _ = enforce_node_spacing(doc, min_spacing_px=5.0)
    assert doc.paths[0].subpaths[0].segments


def test_colour_normalisation_merges_indistinguishable_fills():
    doc = SvgDoc(width=10, height=10, paths=[
        Path(subpaths=[_square(0, 0, 5)], fill="#ff0000"),
        Path(subpaths=[_square(0, 0, 5)], fill="#fe0101"),
        Path(subpaths=[_square(0, 0, 5)], fill="#0000ff"),
    ])
    doc, merged = normalise_colors(doc)
    assert merged == 1
    assert doc.paths[0].fill == doc.paths[1].fill
    assert doc.paths[2].fill == "#0000ff"


def test_colour_normalisation_keeps_distinct_colours_apart():
    doc = SvgDoc(width=10, height=10, paths=[
        Path(subpaths=[_square(0, 0, 5)], fill="#ff0000"),
        Path(subpaths=[_square(0, 0, 5)], fill="#dd0000"),
    ])
    doc, merged = normalise_colors(doc)
    assert merged == 0


def test_order_layers_does_not_reorder():
    fills = ["#ff0000", "#00ff00", "#ff0000"]
    doc = SvgDoc(width=10, height=10, paths=[
        Path(subpaths=[_square(0, 0, 5)], fill=f) for f in fills
    ])
    groups = order_layers(doc)
    assert [p.fill for p in doc.paths] == fills
    assert groups == 3
