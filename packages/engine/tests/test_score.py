"""§3.6 — the scorer's invariants, including the bug v2 shipped."""

from __future__ import annotations

import numpy as np
import pytest

from engine.score import (
    SCORE_VERSION,
    WEIGHTS,
    Scorer,
    _penalty,
    node_baseline,
    path_baseline,
)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_penalty_never_exceeds_one_or_goes_negative():
    """The v2 formula divided by zero at nodes = baseline/e and went negative.

    max(1, …) is the fix. A trace with almost no geometry must not collect a
    bonus for it.
    """
    for count in (0, 1, 10, 100, 10_000, 1_000_000):
        for baseline in (1.0, 50.0, 5000.0):
            value = _penalty(count, baseline)
            assert 0.0 < value <= 1.0


def test_penalty_is_monotonic():
    baseline = 100.0
    values = [_penalty(n, baseline) for n in (50, 100, 200, 400, 800)]
    assert values == sorted(values, reverse=True)


def test_penalty_is_one_below_baseline():
    assert _penalty(10, 100.0) == 1.0
    assert _penalty(100, 100.0) == 1.0


def test_node_baseline_uses_class_calibration():
    assert node_baseline(10_000, "PHOTO") > node_baseline(10_000, "LOGO_FLAT")


def test_identical_images_score_one():
    ref = np.zeros((64, 64, 4), dtype=np.uint8)
    ref[16:48, 16:48] = (200, 30, 30, 255)
    ref[:, :, 3] = 255
    scorer = Scorer(ref, classification="LOGO_FLAT", edge_pixel_count=200)
    score = scorer.score_raster(ref.copy(), nodes=1, paths=1)
    assert score.ssim > 0.99
    assert score.color > 0.99
    assert score.fidelity > 0.99
    assert score.score_version == SCORE_VERSION


def test_alpha_term_dropped_when_source_is_opaque():
    ref = np.full((32, 32, 4), 255, dtype=np.uint8)
    scorer = Scorer(ref, classification="LOGO_FLAT", edge_pixel_count=10)
    score = scorer.score_raster(ref.copy(), nodes=1, paths=1)
    assert score.alpha_iou is None
    # Renormalised, so dropping a term does not silently lower the score.
    assert score.fidelity == pytest.approx(1.0, abs=1e-3)


def test_fidelity_ignores_node_count_but_total_does_not():
    """Selection uses `total`; simplification stop rules use `fidelity`."""
    ref = np.zeros((64, 64, 4), dtype=np.uint8)
    ref[8:56, 8:56] = (10, 120, 200, 255)
    ref[:, :, 3] = 255
    scorer = Scorer(ref, classification="LOGO_FLAT", edge_pixel_count=200)
    lean = scorer.score_raster(ref.copy(), nodes=10, paths=1)
    fat = scorer.score_raster(ref.copy(), nodes=100_000, paths=1)
    assert lean.fidelity == fat.fidelity
    assert lean.total > fat.total


def test_path_baseline_counts_regions():
    ref = np.zeros((128, 128, 4), dtype=np.uint8)
    ref[:, :, 3] = 255
    ref[10:60, 10:60] = (255, 0, 0, 255)
    ref[70:120, 70:120] = (0, 255, 0, 255)
    assert path_baseline(ref) >= 3
