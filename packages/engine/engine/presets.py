"""§3.4 Candidate generation.

Not a brute-force grid: a classification-conditioned set of 3–6 parameter
vectors, one of which is always a universal fallback so a misclassification
degrades instead of failing.
"""

from __future__ import annotations

import cv2
import numpy as np

from engine.classify import ranked
from engine.types import TIER_CANDIDATES, Classification, ImageProfile, Options, Params

# The candidate that has to be survivable on anything. Present in every set.
UNIVERSAL_FALLBACK = Params(
    label="universal", color_precision=6, filter_speckle=4, corner_threshold=60, mode="spline"
)

VTRACER_PRESETS: dict[str, list[Params]] = {
    "LOGO_FLAT": [
        Params(label="flat-balanced", color_precision=6, filter_speckle=4, corner_threshold=60),
        Params(label="flat-detail", color_precision=8, filter_speckle=2, corner_threshold=45),
        Params(label="flat-clean", color_precision=4, filter_speckle=8, corner_threshold=80),
        Params(label="flat-poly", color_precision=6, filter_speckle=4, corner_threshold=30,
               mode="polygon"),
    ],
    "LOGO_GRADIENT": [
        # Gradients are banded, not reproduced (§3.2). High colour precision
        # and a small gradient step make the banding as fine as vtracer can.
        Params(label="grad-fine", color_precision=8, filter_speckle=2, corner_threshold=60,
               gradient_step=8),
        Params(label="grad-finer", color_precision=8, filter_speckle=4, corner_threshold=45,
               gradient_step=4),
        Params(label="grad-coarse", color_precision=6, filter_speckle=6, corner_threshold=60,
               gradient_step=16),
    ],
    "ILLUSTRATION": [
        Params(label="illus-balanced", color_precision=6, filter_speckle=4, corner_threshold=60),
        Params(label="illus-detail", color_precision=7, filter_speckle=3, corner_threshold=40,
               segment_length=3.5),
        Params(label="illus-smooth", color_precision=5, filter_speckle=8, corner_threshold=75,
               segment_length=6.0),
    ],
    "SCREENSHOT": [
        # Screenshots are axis-aligned; polygon mode keeps corners square.
        Params(label="shot-poly", color_precision=8, filter_speckle=1, corner_threshold=20,
               mode="polygon"),
        Params(label="shot-poly-clean", color_precision=6, filter_speckle=3, corner_threshold=30,
               mode="polygon"),
        Params(label="shot-spline", color_precision=8, filter_speckle=2, corner_threshold=40),
    ],
    "PHOTO": [
        # Photos do not vectorize cleanly and never will. These exist so the
        # answer to "do your best" is a defensible trace, not a refusal.
        Params(label="photo-coarse", color_precision=5, filter_speckle=8, corner_threshold=80,
               segment_length=8.0, gradient_step=24),
        Params(label="photo-poster", color_precision=4, filter_speckle=12, corner_threshold=90,
               segment_length=10.0, gradient_step=32),
    ],
    "LINE_ART": [
        Params(label="line-bw", color_precision=2, filter_speckle=4, corner_threshold=60),
    ],
    "SKETCH": [
        Params(label="sketch-bw", color_precision=3, filter_speckle=6, corner_threshold=70),
    ],
}


def _otsu_threshold(rgba: np.ndarray) -> int:
    rgb = rgba[:, :, :3]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    value, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return int(value)


def potrace_presets(rgba: np.ndarray) -> list[Params]:
    """Bilevel candidates at Otsu and Otsu±15 (§3.4)."""
    base = int(np.clip(_otsu_threshold(rgba), 40, 215))
    out = []
    for i, t in enumerate((base, base - 15, base + 15)):
        out.append(
            Params(
                engine="potrace",
                label=f"potrace-t{t}",
                threshold=t,
                turdsize=(2, 4, 8)[i],
                alphamax=(1.0, 1.0, 0.8)[i],
            )
        )
    return out


def candidates_for(
    profile: ImageProfile,
    options: Options,
    trace_input: np.ndarray,
    *,
    potrace_available: bool = True,
) -> list[Params]:
    if options.forced_params is not None:
        return [options.forced_params]

    budget = TIER_CANDIDATES.get(options.quality_tier, 4)

    classes: list[Classification] = [profile.classification]
    # Low confidence → take the union of the top two classes, capped by tier.
    if profile.classification_confidence < 0.35 and profile.class_scores:
        for c in ranked(profile.class_scores):
            if c not in classes:
                classes.append(c)
                break

    picked: list[Params] = []
    seen: set[str] = set()

    def add(p: Params) -> None:
        if p.key() not in seen:
            seen.add(p.key())
            picked.append(p)

    for cls in classes:
        for p in VTRACER_PRESETS.get(cls, []):
            add(p)
        if cls in ("LINE_ART", "SKETCH") and potrace_available:
            for p in potrace_presets(trace_input):
                add(p)

    add(UNIVERSAL_FALLBACK)

    if options.detail == "high":
        add(Params(label="detail-high", color_precision=8, filter_speckle=1,
                   corner_threshold=30, segment_length=3.5))
    elif options.detail == "low":
        add(Params(label="detail-low", color_precision=4, filter_speckle=10,
                   corner_threshold=90, segment_length=8.0))

    if budget == 1:
        # `fast` tier: one candidate, and it must be the class's first choice
        # rather than the fallback, or the cheap tier looks broken.
        return picked[:1]

    if len(picked) < budget:
        extras = [
            Params(label="x-detail", color_precision=8, filter_speckle=2, corner_threshold=40),
            Params(label="x-smooth", color_precision=5, filter_speckle=8, corner_threshold=80,
                   segment_length=6.0),
            Params(label="x-poly", color_precision=6, filter_speckle=4, corner_threshold=45,
                   mode="polygon"),
            Params(label="x-fine-seg", color_precision=7, filter_speckle=3,
                   corner_threshold=55, segment_length=3.5),
        ]
        for p in extras:
            if len(picked) >= budget:
                break
            add(p)

    return picked[:budget]
