"""§3.2 — a unit test per class, from the corpus."""

from __future__ import annotations

import pytest

from engine.analyse import analyse
from engine.ingest import ingest

CASES = [
    ("logo_flat", "LOGO_FLAT"),
    ("logo_flat_jpeg_artifacts", "LOGO_FLAT"),
    ("logo_gradient", "LOGO_GRADIENT"),
    ("line_art", "LINE_ART"),
    ("sketch", "SKETCH"),
    ("screenshot", "SCREENSHOT"),
    ("photo", "PHOTO"),
]


@pytest.mark.parametrize(("name", "expected"), CASES)
def test_classification(fx, name, expected):
    profile = analyse(ingest(fx.by_name(name).data))
    assert profile.classification == expected


def test_mode_override_wins(fx):
    profile = analyse(ingest(fx.by_name("photo").data), mode_override="flat")
    assert profile.classification == "LOGO_FLAT"
    assert profile.classification_confidence == 1.0


def test_flat_ratio_separates_flat_from_photo(fx):
    """unique_colors alone cannot do this: the JPEG'd logo reports thousands."""
    flat = analyse(ingest(fx.by_name("logo_flat_jpeg_artifacts").data))
    photo = analyse(ingest(fx.by_name("photo").data))
    assert flat.unique_colors > 1000
    assert flat.flat_color_ratio > 0.9
    assert photo.flat_color_ratio < 0.5


def test_profile_contains_no_pixels(fx):
    """jobs.profile is persisted after files are deleted (§5)."""
    profile = analyse(ingest(fx.by_name("logo_flat").data))
    blob = profile.as_dict()
    assert set(blob) and all(
        not hasattr(v, "shape") for v in blob.values()
    ), "ImageProfile must be statistics only"
