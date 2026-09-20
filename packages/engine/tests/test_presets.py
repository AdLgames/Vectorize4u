"""§3.4 — candidate generation."""

from __future__ import annotations

import numpy as np

from engine.presets import UNIVERSAL_FALLBACK, candidates_for, potrace_presets
from engine.types import ImageProfile, Options, Params


def _profile(classification="LOGO_FLAT", confidence=0.9, scores=None) -> ImageProfile:
    return ImageProfile(
        source_format="PNG",
        width=800, height=600, unique_colors=8, edge_density=0.01, edge_pixel_count=900,
        has_alpha=False, alpha_is_binary=True, alpha_was_premultiplied=False,
        is_grayscale=False, is_bilevel=False, noise_estimate=100.0,
        jpeg_artifact_score=0.0, estimated_text_regions=0,
        dominant_palette=["#000000"], palette_size=4, flat_color_ratio=0.99,
        source_dpi=None, source_dpi_trusted=False,
        classification=classification, classification_confidence=confidence,
        class_scores=scores or {classification: 5.0},
    )


def _image() -> np.ndarray:
    img = np.zeros((64, 64, 4), dtype=np.uint8)
    img[:, :, 3] = 255
    img[16:48, 16:48, :3] = 255
    return img


def test_every_set_contains_the_universal_fallback():
    """A misclassification must degrade, not fail."""
    for cls in ("LOGO_FLAT", "LOGO_GRADIENT", "ILLUSTRATION", "SCREENSHOT", "PHOTO"):
        picked = candidates_for(_profile(cls), Options(quality_tier="max"), _image())
        assert any(p.key() == UNIVERSAL_FALLBACK.key() for p in picked)


def test_tier_caps_candidate_count():
    for tier, expected in (("fast", 1), ("standard", 4), ("max", 8)):
        picked = candidates_for(_profile(), Options(quality_tier=tier), _image())
        assert len(picked) == expected


def test_fast_tier_picks_the_class_first_choice_not_the_fallback():
    picked = candidates_for(_profile("SCREENSHOT"), Options(quality_tier="fast"), _image())
    assert picked[0].label == "shot-poly"


def test_low_confidence_unions_the_top_two_classes():
    scores = {"LOGO_FLAT": 3.0, "SCREENSHOT": 2.9, "PHOTO": 0.1}
    picked = candidates_for(
        _profile("LOGO_FLAT", confidence=0.2, scores=scores),
        Options(quality_tier="max"),
        _image(),
    )
    labels = {p.label for p in picked}
    assert any(label.startswith("flat") for label in labels)
    assert any(label.startswith("shot") for label in labels)


def test_line_art_adds_potrace_candidates():
    picked = candidates_for(_profile("LINE_ART"), Options(quality_tier="max"), _image())
    assert any(p.engine == "potrace" for p in picked)


def test_potrace_candidates_bracket_otsu():
    presets = potrace_presets(_image())
    thresholds = sorted(p.threshold for p in presets)
    assert len(presets) == 3
    assert thresholds[0] < thresholds[1] < thresholds[2]


def test_forced_params_bypass_the_search():
    forced = Params(color_precision=3, label="forced")
    picked = candidates_for(_profile(), Options(forced_params=forced), _image())
    assert picked == [forced]


def test_all_vtracer_candidates_are_stacked():
    """Cutout mode makes sliver removal punch holes in the artwork."""
    for cls in ("LOGO_FLAT", "LOGO_GRADIENT", "ILLUSTRATION", "SCREENSHOT", "PHOTO"):
        for p in candidates_for(_profile(cls), Options(quality_tier="max"), _image()):
            if p.engine == "vtracer":
                assert p.hierarchical == "stacked"


def test_detail_option_adds_a_candidate():
    high = candidates_for(_profile(), Options(quality_tier="max", detail="high"), _image())
    assert any(p.label == "detail-high" for p in high)
