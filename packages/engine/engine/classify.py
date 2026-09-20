"""§3.2 classification.

Rule thresholds live here on purpose, with a unit test per class from the
corpus. A learned classifier would be a second model to version, retrain and
explain; these rules are auditable and a misclassification degrades
gracefully because every preset set carries a universal fallback (§3.4).

Scores are unnormalised "evidence" per class; the winner's share of the
total is reported as `classification_confidence`, and a low confidence makes
the candidate generator take the union of the top two classes (§3.4).
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np

from engine.types import CLASSIFICATIONS, Classification

MODE_OVERRIDES: dict[str, Classification] = {
    "flat": "LOGO_FLAT",
    "lineart": "LINE_ART",
    "sketch": "SKETCH",
    "photo": "PHOTO",
}


def _gradient_evidence(rgba: np.ndarray) -> float:
    """Fraction of pixels in smooth, low-edge colour ramps.

    Distinguishes LOGO_GRADIENT from LOGO_FLAT: a flat logo has large regions
    of exactly one colour, a gradient logo has large regions of slowly
    varying colour with no edges in them.
    """
    import cv2

    rgb = rgba[:, :, :3].astype(np.float32)
    small = cv2.resize(rgb, (128, 128), interpolation=cv2.INTER_AREA)
    gx = np.abs(np.diff(small, axis=1)).mean(axis=2)
    gy = np.abs(np.diff(small, axis=0)).mean(axis=2)
    gx = gx[:-1, :]
    gy = gy[:, :-1]
    mag = gx + gy
    # Ramp = non-zero but small local change. Flat = zero. Edge = large.
    ramp = float(np.mean((mag > 0.4) & (mag < 6.0)))
    return ramp


def classify(
    rgba: np.ndarray,
    p: dict[str, Any],
    mode_override: str = "auto",
) -> tuple[Classification, float, dict[str, float]]:
    if mode_override in MODE_OVERRIDES:
        cls = MODE_OVERRIDES[mode_override]
        return cls, 1.0, {c: (1.0 if c == cls else 0.0) for c in CLASSIFICATIONS}

    uniq = p["unique_colors"]
    edge = p["edge_density"]
    noise = p["noise_estimate"]
    jpeg = p["jpeg_artifact_score"]
    gray = p["is_grayscale"]
    bilevel = p["is_bilevel"]
    palette = p["palette_size"]
    flat = p["flat_color_ratio"]
    text = p["estimated_text_regions"]
    ramp = _gradient_evidence(rgba)

    s: dict[str, float] = dict.fromkeys(CLASSIFICATIONS, 0.0)

    # LOGO_FLAT: the image sits on its own small palette, with crisp edges.
    # Driven by flat_color_ratio, not unique_colors: a re-compressed JPEG of
    # a 4-colour logo reports thousands of colours and is still a flat logo.
    s["LOGO_FLAT"] += 3.0 if (flat >= 0.93 and palette <= 8) else 0.0
    s["LOGO_FLAT"] += 1.5 if flat >= 0.90 else 0.0
    s["LOGO_FLAT"] += 1.0 if edge < 0.12 else 0.0
    s["LOGO_FLAT"] += 1.0 if noise < 800 else 0.0
    s["LOGO_FLAT"] -= 2.0 * float(gray)
    s["LOGO_FLAT"] -= 2.0 if ramp > 0.30 else 0.0
    # Dozens of glyph-sized components is the screenshot signature, not a
    # logo's. A wordmark lands well under this threshold.
    s["LOGO_FLAT"] -= 2.0 if text > 40 else 0.0

    # LOGO_GRADIENT: logo structure with measurable colour ramps. Grayscale
    # and noisy images are excluded outright — a pencil sketch has ramps
    # everywhere and is not a gradient logo.
    s["LOGO_GRADIENT"] += 4.0 * min(ramp / 0.25, 1.0)
    s["LOGO_GRADIENT"] += 1.5 if 0.5 <= flat < 0.93 else 0.0
    s["LOGO_GRADIENT"] += 1.0 if edge < 0.10 else 0.0
    s["LOGO_GRADIENT"] -= 4.0 * float(gray)
    s["LOGO_GRADIENT"] -= 3.0 if noise > 1500 else 0.0
    s["LOGO_GRADIENT"] -= 2.0 if flat >= 0.95 else 0.0

    # LINE_ART: bilevel or near-bilevel, thin strokes, no tone.
    s["LINE_ART"] += 3.0 if bilevel else 0.0
    s["LINE_ART"] += 2.0 if (gray and uniq < 32) else 0.0
    s["LINE_ART"] += 1.0 if 0.02 < edge < 0.35 else 0.0

    # SKETCH: grayscale with continuous tone and speckle.
    s["SKETCH"] += 2.5 if (gray and uniq >= 32) else 0.0
    s["SKETCH"] += 1.5 if noise > 1200 else 0.0
    s["SKETCH"] += 1.0 if edge > 0.03 else 0.0

    # PHOTO: the image does not sit on any small palette.
    s["PHOTO"] += 3.0 if flat < 0.50 else 0.0
    s["PHOTO"] += 2.0 if (uniq > 20000 and flat < 0.70) else 0.0
    s["PHOTO"] += 1.5 if edge > 0.15 else 0.0
    s["PHOTO"] += 1.5 if noise > 2000 else 0.0
    s["PHOTO"] += 1.0 if jpeg > 0.5 else 0.0
    s["PHOTO"] -= 2.0 if (palette <= 8 and flat >= 0.9) else 0.0

    # SCREENSHOT: flat UI fills plus a lot of text-like components.
    s["SCREENSHOT"] += 3.0 if text > 40 else 0.0
    s["SCREENSHOT"] += 1.5 if (palette <= 16 and edge > 0.02 and flat >= 0.80) else 0.0
    s["SCREENSHOT"] -= 2.0 if flat < 0.60 else 0.0

    # ILLUSTRATION: the middle ground — neither flat nor continuous-tone.
    s["ILLUSTRATION"] += 2.0 if 0.50 <= flat < 0.93 else 0.0
    s["ILLUSTRATION"] += 1.0 if noise < 2000 else 0.0
    s["ILLUSTRATION"] += 1.0 if edge < 0.18 else 0.0
    s["ILLUSTRATION"] -= 2.0 if text > 40 else 0.0
    s["ILLUSTRATION"] += 0.5

    positive = {k: max(0.0, v) for k, v in s.items()}
    total = sum(positive.values())
    best = cast(Classification, max(positive, key=lambda k: positive[k]))
    confidence = (positive[best] / total) if total > 0 else 0.0
    return best, round(confidence, 4), {k: round(v, 3) for k, v in s.items()}


def ranked(scores: dict[str, float]) -> list[Classification]:
    return [
        c  # type: ignore[misc]
        for c, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]
