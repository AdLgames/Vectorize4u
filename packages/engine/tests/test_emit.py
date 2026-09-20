"""§3.8 — physical size is the thing the buyer actually checks."""

from __future__ import annotations

import pytest

from engine.emit import resolve_physical_size, to_dxf, to_eps
from engine.svgdoc import SvgDoc
from engine.types import ImageProfile, Options, Warning_

pytest.importorskip("ezdxf")


def _profile(**kw) -> ImageProfile:
    base = dict(
        source_format="PNG",
        width=400, height=200, unique_colors=4, edge_density=0.01, edge_pixel_count=500,
        has_alpha=False, alpha_is_binary=True, alpha_was_premultiplied=False,
        is_grayscale=False, is_bilevel=False, noise_estimate=10.0,
        jpeg_artifact_score=0.0, estimated_text_regions=0,
        dominant_palette=["#000000"], palette_size=2, flat_color_ratio=0.99,
        source_dpi=None, source_dpi_trusted=False,
        classification="LOGO_FLAT", classification_confidence=0.9,
    )
    base.update(kw)
    return ImageProfile(**base)  # type: ignore[arg-type]


def _doc() -> SvgDoc:
    from engine.svgdoc import Path, SubPath

    sp = SubPath(start=(0.0, 0.0), segments=[("L", ((400.0, 0.0),)), ("L", ((400.0, 200.0),))],
                 closed=True)
    return SvgDoc(width=400, height=200, paths=[Path(subpaths=[sp], fill="#123456")])


def test_user_size_wins():
    size, warnings = resolve_physical_size(
        _doc(), _profile(), Options(output_width=120, units="mm")
    )
    assert size.source == "user"
    assert size.width_mm == pytest.approx(120.0)
    assert size.height_mm == pytest.approx(60.0)
    assert warnings == []


def test_inches_are_converted():
    size, _ = resolve_physical_size(_doc(), _profile(), Options(output_width=4, units="in"))
    assert size.width_mm == pytest.approx(101.6)


def test_untrusted_metadata_dpi_is_ignored():
    """72 and 96 are writer defaults, not measurements."""
    size, warnings = resolve_physical_size(
        _doc(), _profile(source_dpi=72.0, source_dpi_trusted=False), Options()
    )
    assert size.source == "assumed"
    assert Warning_.PHYSICAL_SIZE_ASSUMED.value in warnings


def test_trusted_metadata_dpi_is_used():
    size, warnings = resolve_physical_size(
        _doc(), _profile(source_dpi=300.0, source_dpi_trusted=True), Options()
    )
    assert size.source == "metadata"
    assert size.width_mm == pytest.approx(400 / 300 * 25.4)
    assert warnings == []


def test_dxf_carries_absolute_units():
    import ezdxf

    from engine.emit import resolve_physical_size

    doc = _doc()
    size, _ = resolve_physical_size(doc, _profile(), Options(output_width=100, units="mm"))
    blob = to_dxf(doc, size, tolerance_mm=0.1, units="mm")
    drawing = ezdxf.read(__import__("io").StringIO(blob.decode()))
    assert drawing.header["$INSUNITS"] == 4  # millimetres

    extents_x = max(
        abs(p[0]) for e in drawing.modelspace() for p in e.get_points("xy")
    )
    assert extents_x == pytest.approx(100.0, rel=0.02)


def test_dxf_inches_use_insunits_one():
    import ezdxf

    doc = _doc()
    size, _ = resolve_physical_size(doc, _profile(), Options(output_width=4, units="in"))
    blob = to_dxf(doc, size, tolerance_mm=0.1, units="in")
    drawing = ezdxf.read(__import__("io").StringIO(blob.decode()))
    assert drawing.header["$INSUNITS"] == 1
    extents_x = max(abs(p[0]) for e in drawing.modelspace() for p in e.get_points("xy"))
    assert extents_x == pytest.approx(4.0, rel=0.02)


def test_eps_has_a_bounding_box():
    doc = _doc()
    size, _ = resolve_physical_size(doc, _profile(), Options(output_width=100, units="mm"))
    blob = to_eps(doc, size).decode()
    assert blob.startswith("%!PS-Adobe-3.0 EPSF-3.0")
    assert "%%BoundingBox:" in blob
