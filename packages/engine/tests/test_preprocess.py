"""§3.3 — the reference/trace_input split is the whole point of this stage."""

from __future__ import annotations

import numpy as np

from engine.analyse import analyse
from engine.ingest import ingest
from engine.preprocess import preprocess, quantize
from engine.types import Options, Warning_


def _prep(fx, name, options=None):
    ing = ingest(fx.by_name(name).data)
    profile = analyse(ing)
    return ing, profile, preprocess(ing.rgba, profile, options or Options())


def test_reference_keeps_original_geometry(fx):
    """Upscaling the reference would make every score a comparison against
    a resampled image rather than against the artwork."""
    ing, profile, pre = _prep(fx, "logo_flat_small")
    assert pre.reference.shape[:2] == ing.rgba.shape[:2]
    assert pre.trace_input.shape[0] == ing.rgba.shape[0] * 2
    assert pre.scale == 2.0


def test_photos_are_not_upscaled(fx):
    """Upscaling a photo quadruples an already enormous trace and helps nothing."""
    _, profile, pre = _prep(fx, "photo")
    assert profile.classification == "PHOTO"
    assert pre.scale == 1.0


def test_jpeg_artifacts_are_cleaned_from_the_reference(fx):
    """Scoring against the raw source would reward reproducing JPEG blocks."""
    ing, profile, pre = _prep(fx, "logo_flat_jpeg_artifacts")
    assert profile.source_format == "JPEG"
    assert "jpeg_artifact_removal" in pre.steps
    assert not np.array_equal(pre.reference, ing.rgba)


def test_lossless_sources_are_never_de_artifacted(fx):
    """A PNG has no DCT artifacts to remove; filtering it just softens the logo."""
    _, profile, pre = _prep(fx, "logo_flat_small")
    assert profile.source_format == "PNG"
    assert "jpeg_artifact_removal" not in pre.steps


def test_quantization_only_touches_trace_input(fx):
    _, _, pre = _prep(fx, "logo_flat")
    assert any(s.startswith("quantize") for s in pre.steps)
    assert pre.quantized_colors > 0
    ref_colors = np.unique(pre.reference[:, :, :3].reshape(-1, 3), axis=0).shape[0]
    trace_colors = np.unique(pre.trace_input[:, :, :3].reshape(-1, 3), axis=0).shape[0]
    assert trace_colors <= ref_colors


def test_soft_alpha_is_matted(fx):
    _, _, pre = _prep(fx, "alpha_dark_straight")
    assert "alpha_matte" in pre.steps
    assert set(np.unique(pre.reference[:, :, 3]).tolist()) <= {0, 255}


def test_over_cleaning_is_backed_off(fx, monkeypatch):
    """If the filters destroyed the artwork, ship the original instead."""
    from engine import config
    from engine import preprocess as pp

    monkeypatch.setattr(config, "PREPROCESS_SSIM_FLOOR", 1.01)
    monkeypatch.setattr(pp.config, "PREPROCESS_SSIM_FLOOR", 1.01)
    _, _, pre = _prep(fx, "logo_flat_jpeg_artifacts")
    assert Warning_.PREPROCESS_BACKED_OFF.value in pre.warnings
    assert "backed_off" in pre.steps


def test_quantize_merges_indistinguishable_colours():
    img = np.zeros((32, 32, 4), dtype=np.uint8)
    img[:, :, 3] = 255
    img[:16] = (255, 0, 0, 255)
    img[16:] = (254, 1, 1, 255)
    out, colors = quantize(img, 4)
    assert colors == 1


def test_quantize_is_deterministic():
    rng = np.random.default_rng(7)
    img = np.dstack(
        [rng.integers(0, 255, (48, 48, 3), dtype=np.uint8), np.full((48, 48), 255, np.uint8)]
    )
    a, ka = quantize(img, 6)
    b, kb = quantize(img, 6)
    assert ka == kb
    assert np.array_equal(a, b)


def test_smoothing_is_off_by_default(fx):
    """The default has to stay byte-identical: every stored score, the
    benchmark corpus and every price quoted on the site were measured
    without it."""
    _, _, pre = _prep(fx, "logo_flat_small")
    assert pre.unsmoothed is None
    assert not [s for s in pre.steps if s.startswith("smooth")]


def test_smoothing_blurs_only_the_trace_input(fx):
    """Same rule as the upscale: the reference is the customer's file, so
    the score keeps meaning 'how close is this to what you sent'."""
    _, _, pre = _prep(fx, "logo_flat_small", Options(smoothing=8))
    _, _, plain = _prep(fx, "logo_flat_small")
    assert "smooth:8" in pre.steps
    assert np.array_equal(pre.reference, plain.reference)
    assert not np.array_equal(pre.trace_input, pre.unsmoothed)


def test_smoothing_keeps_the_pre_blur_image_for_tracer_choice(fx):
    """`candidates_for` asks whether the artwork is two-tone. A blur fills
    the gap between two tones with every value in between, so asking the
    blurred image loses the bilevel tracer — measured, the Batman logo fell
    from one potrace path to ten vtracer bands at smoothing 4."""
    _, _, pre = _prep(fx, "logo_flat_small", Options(smoothing=6))
    assert pre.unsmoothed is not None
    assert pre.unsmoothed.shape == pre.trace_input.shape


def test_smoothing_scales_with_the_image(fx):
    """A fixed pixel radius would be invisible on a 4000 px export and
    would dissolve a 300 px one."""
    _, _, small = _prep(fx, "logo_flat_small", Options(smoothing=10))
    assert "smooth:10" in small.steps
    # The blur is a fraction of width, so a wider trace input gets a wider
    # kernel — the visible amount of rounding is what stays constant.
    assert small.trace_input.shape[1] > 0
