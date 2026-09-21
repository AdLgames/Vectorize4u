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


def test_despeckle_overrides_every_candidate():
    """The UI's "Clean up specks" is an instruction, not another search axis.

    Searching around a value the user explicitly chose would mean showing
    them a result their own setting says they did not want.
    """
    picked = candidates_for(
        _profile("LINE_ART"), Options(quality_tier="max", despeckle=11), _image()
    )
    assert picked
    assert all(p.filter_speckle == 11 for p in picked if p.engine == "vtracer")
    assert all(p.turdsize == 11 for p in picked if p.engine == "potrace")


def test_despeckle_is_clamped_to_the_tracer_range():
    picked = candidates_for(
        _profile(), Options(quality_tier="fast", despeckle=999), _image()
    )
    assert picked[0].filter_speckle == 16


def test_no_despeckle_leaves_the_presets_alone():
    tuned = candidates_for(_profile(), Options(quality_tier="max"), _image())
    assert {p.filter_speckle for p in tuned} != {4}


# -- two-tone logos reach the bilevel tracer (§3.4) -------------------------


def _two_tone(size=(120, 200), *, aliased=True) -> np.ndarray:
    """A black shape on white, with the hard edges of a low-res export."""
    h, w = size
    rgba = np.full((h, w, 4), 255, dtype=np.uint8)
    rgba[:, :, 3] = 255
    yy, xx = np.mgrid[0:h, 0:w]
    inside = ((yy - h / 2) / (h / 2.5)) ** 2 + ((xx - w / 2) / (w / 2.5)) ** 2 <= 1.0
    rgba[inside, :3] = 0
    if not aliased:
        rgba[:, :, :3] = np.clip(rgba[:, :, :3].astype(int) + 40, 0, 255).astype(np.uint8)
    return rgba


def _coloured() -> np.ndarray:
    rgba = _two_tone()
    # Same shape, but the ink is red: potrace would discard the colour.
    dark = rgba[:, :, 0] == 0
    rgba[dark] = (200, 30, 30, 255)
    return rgba


def test_a_two_tone_logo_is_offered_the_bilevel_tracer():
    """LOGO_FLAT never reached potrace, whatever the image looked like.

    A black-and-white logo classified LOGO_FLAT was traced only by the
    colour tracer, which follows every pixel step of an aliased edge. On a
    real one that cost 1279 nodes against potrace's 494, and scored lower
    on the engine's own metric — a better result the search was never
    allowed to see.
    """
    picked = candidates_for(_profile(), Options(), _two_tone())
    engines = {p.engine for p in picked}
    assert "potrace" in engines, "a two-tone logo must be offered the bilevel tracer"
    assert "vtracer" in engines, "and still the colour tracer, which may yet win"


def test_a_coloured_logo_is_not():
    """potrace flattens to one ink colour, so offering it here spends a
    candidate slot on a result that cannot win."""
    picked = candidates_for(_profile(), Options(), _coloured())
    assert {p.engine for p in picked} == {"vtracer"}


def test_the_class_first_choice_survives_the_reordering():
    """Inserting potrace early must not push the class preset out of the
    budget: the point is to try both engines, not to swap one for another."""
    picked = candidates_for(_profile(), Options(), _two_tone())
    assert picked[0].engine == "vtracer"
    assert picked[0].label == "flat-balanced"


def test_a_photograph_is_never_called_two_tone():
    rng = np.random.default_rng(0)
    noisy = np.dstack(
        [rng.integers(0, 255, (80, 80), dtype=np.uint8) for _ in range(3)]
        + [np.full((80, 80), 255, dtype=np.uint8)]
    )
    picked = candidates_for(_profile("PHOTO", 0.9), Options(), noisy)
    assert {p.engine for p in picked} == {"vtracer"}
