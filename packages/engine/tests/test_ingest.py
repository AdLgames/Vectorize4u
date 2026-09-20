"""§3.1 ingest behaviours that the definition of done names explicitly."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from engine.errors import ImageTooLarge, UnsupportedFormat
from engine.ingest import ingest, sniff_format


def test_sniff_rejects_non_images():
    with pytest.raises(UnsupportedFormat):
        sniff_format(b"not an image at all")


def test_extension_is_not_trusted(fx):
    """A PNG's bytes decide what it is, not its name or Content-Type."""
    data = fx.by_name("logo_flat").data
    assert sniff_format(data) == "PNG"


def test_size_limit():
    with pytest.raises(ImageTooLarge):
        ingest(b"\x89PNG\r\n\x1a\n" + b"0" * 10, max_bytes=8)


def test_dimension_limit(fx):
    with pytest.raises(ImageTooLarge):
        ingest(fx.by_name("logo_flat").data, max_dimension=100)


def test_exif_rotation_applied_before_strip(fx):
    """Orientation 6 on a 600×400 source must come out 400×600, upright."""
    result = ingest(fx.by_name("exif_rotated").data)
    assert result.rgba.shape[0] > result.rgba.shape[1]
    assert "exif_rotated" in result.warnings


def test_cmyk_is_converted_and_colour_correct(fx):
    """A CMYK JPEG of the flat logo must keep its red and blue."""
    result = ingest(fx.by_name("cmyk_jpeg").data)
    assert result.rgba.shape[2] == 4
    rgb = result.rgba[:, :, :3].reshape(-1, 3).astype(int)
    reds = rgb[(rgb[:, 0] > 150) & (rgb[:, 1] < 110) & (rgb[:, 2] < 110)]
    blues = rgb[(rgb[:, 2] > 130) & (rgb[:, 0] < 110)]
    assert len(reds) > 1000, "lost the red mark in CMYK conversion"
    assert len(blues) > 1000, "lost the blue mark in CMYK conversion"


def test_premultiplied_is_detected_and_divided(fx):
    """The premultiplied fixture must be fixed: no dark halo on soft edges."""
    result = ingest(fx.by_name("alpha_premultiplied").data)
    assert result.alpha_was_premultiplied is True

    rgba = result.rgba
    alpha = rgba[:, :, 3]
    semi = (alpha > 40) & (alpha < 200)
    opaque = alpha >= 250
    # After un-premultiplying, edge pixels carry the same colour as the core.
    assert rgba[semi][:, :3].mean() > rgba[opaque][:, :3].mean() * 0.8


def test_dark_straight_alpha_is_left_alone(fx):
    """The fixture the naive test gets wrong.

    Every semi-transparent pixel satisfies max(r,g,b) <= a, so a naive
    detector divides it and creates bright halos. It must be untouched.
    """
    raw = fx.by_name("alpha_dark_straight").data
    result = ingest(raw)
    assert result.alpha_was_premultiplied is False

    with Image.open(io.BytesIO(raw)) as img:
        original = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    assert np.array_equal(result.rgba, original)


def test_alpha_mode_override_forces_division(fx):
    result = ingest(fx.by_name("alpha_dark_straight").data, alpha_mode="premultiplied")
    assert result.alpha_was_premultiplied is True


def test_binary_alpha_survives(fx):
    result = ingest(fx.by_name("alpha_binary").data)
    assert set(np.unique(result.rgba[:, :, 3]).tolist()) <= {0, 255}


def test_fewer_than_500_semi_transparent_pixels_is_skipped():
    """Nothing to fix, and the test is not reliable at that sample size."""
    img = Image.new("RGBA", (64, 64), (10, 10, 10, 255))
    img.putpixel((0, 0), (5, 5, 5, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert ingest(buf.getvalue()).alpha_was_premultiplied is False
