"""§3.3 Preprocess.

Produces two images, and the distinction is the whole point:

  reference   — the original after *cleaning* only. Candidates are scored
                against this. Scoring against the raw source would reward
                traces that faithfully reproduce JPEG blocks and halos, i.e.
                exactly what the customer is paying to remove.
  trace_input — reference plus steps that exist only to help the tracer
                (upscale, palette quantization).

Every step is off by default and enabled by classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from engine import config
from engine.color import rgb_delta_e
from engine.types import ImageProfile, Options, Warning_

# Formats that can carry DCT block artifacts in the first place.
LOSSY_FORMATS = frozenset({"JPEG", "WEBP", "HEIC", "AVIF"})


@dataclass
class Preprocessed:
    reference: np.ndarray  # RGBA, cleaned original
    trace_input: np.ndarray  # RGBA, tracer-friendly
    scale: float  # trace_input px per reference px
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quantized_colors: int = 0


def _ssim_rgb(a: np.ndarray, b: np.ndarray) -> float:
    from skimage.metrics import structural_similarity

    ga = cv2.cvtColor(a[:, :, :3], cv2.COLOR_RGB2GRAY)
    gb = cv2.cvtColor(b[:, :, :3], cv2.COLOR_RGB2GRAY)
    win = min(7, min(ga.shape) - (1 - min(ga.shape) % 2))
    if win < 3:
        return 1.0
    return float(structural_similarity(ga, gb, win_size=win, data_range=255))


def _deartifact(rgba: np.ndarray, strength: float) -> np.ndarray:
    """Bilateral filter: kills DCT blocking without rounding the logo edges."""
    out = rgba.copy()
    d = 5 if strength < 1.0 else 7
    sigma = float(np.clip(20 + 30 * strength, 20, 80))
    out[:, :, :3] = cv2.bilateralFilter(rgba[:, :, :3], d, sigma, sigma)
    return out


def _despeckle(rgba: np.ndarray) -> np.ndarray:
    out = rgba.copy()
    kernel = np.ones((2, 2), np.uint8)
    opened = cv2.morphologyEx(rgba[:, :, :3], cv2.MORPH_OPEN, kernel)
    out[:, :, :3] = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
    return out


def _deskew(rgba: np.ndarray) -> tuple[np.ndarray, float]:
    """Hough-transform angle estimate for scanned line art."""
    gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 360, threshold=max(80, min(gray.shape) // 4))
    if lines is None:
        return rgba, 0.0
    angles = []
    for rho_theta in lines[:120]:
        theta = float(rho_theta[0][1])
        deg = np.degrees(theta) % 180.0
        # Only near-axis lines say anything about skew.
        for anchor in (0.0, 90.0, 180.0):
            if abs(deg - anchor) < 12.0:
                angles.append(deg - anchor)
    if len(angles) < 8:
        return rgba, 0.0
    angle = float(np.median(angles))
    if abs(angle) < 0.35:
        return rgba, 0.0
    h, w = rgba.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        rgba, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def _alpha_matte(rgba: np.ndarray) -> np.ndarray:
    """Threshold soft alpha with a small feather.

    Semi-transparent edge pixels otherwise become their own stray shapes:
    dozens of near-invisible slivers the customer has to delete by hand.
    """
    out = rgba.copy()
    a = rgba[:, :, 3]
    hard = np.where(a >= 128, 255, 0).astype(np.uint8)
    feathered = cv2.GaussianBlur(hard, (3, 3), 0)
    out[:, :, 3] = np.where(feathered >= 128, 255, 0).astype(np.uint8)
    return out


def quantize(rgba: np.ndarray, k: int) -> tuple[np.ndarray, int]:
    """k-means palette quantization with ΔE2000 < 2.0 merging.

    Collapsing anti-aliased halos *before* tracing is what stops them
    becoming dozens of sliver paths. Near-duplicate colours are merged here
    rather than after tracing, where merging means geometry surgery (§3.7).
    """
    rgb = rgba[:, :, :3]
    h, w = rgb.shape[:2]
    flat = rgb.reshape(-1, 3).astype(np.float32)
    k = int(max(2, min(k, 64, np.unique(flat, axis=0).shape[0])))

    cv2.setRNGSeed(config.SEED)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.3)
    _, labels, centers = cv2.kmeans(flat, k, None, criteria, 4, cv2.KMEANS_PP_CENTERS)
    centers = np.clip(centers, 0, 255)

    # Merge centres that no human can tell apart.
    merged = list(range(k))
    for i in range(k):
        for j in range(i):
            if merged[j] != j:
                continue
            if float(rgb_delta_e(centers[i], centers[j])) < config.COLOR_MERGE_DELTA_E:
                merged[i] = j
                break
    remap = np.array(merged, dtype=np.int32)
    final_labels = remap[labels.ravel()]
    out_rgb = centers[final_labels].reshape(h, w, 3).astype(np.uint8)

    out = rgba.copy()
    out[:, :, :3] = out_rgb
    return out, int(np.unique(final_labels).size)


def preprocess(rgba: np.ndarray, profile: ImageProfile, options: Options) -> Preprocessed:
    cls = profile.classification
    original = rgba
    reference = rgba.copy()
    steps: list[str] = []
    warnings: list[str] = []

    # Two conditions, both required. The blockiness score alone produces
    # false positives on hard-edged synthetic art, and a PNG that was never
    # JPEG-encoded has no DCT artifacts to remove — filtering it just softens
    # the customer's logo.
    if (
        profile.jpeg_artifact_score > 0.15
        and profile.source_format in LOSSY_FORMATS
        and cls != "PHOTO"
    ):
        reference = _deartifact(reference, profile.jpeg_artifact_score)
        steps.append("jpeg_artifact_removal")

    if cls in ("LINE_ART", "SKETCH") and profile.width >= 200 and profile.height >= 200:
        reference, angle = _deskew(reference)
        if angle:
            steps.append(f"deskew:{angle:.2f}")

    if cls in ("SKETCH", "SCREENSHOT"):
        reference = _despeckle(reference)
        steps.append("despeckle")

    if profile.has_alpha and not profile.alpha_is_binary:
        reference = _alpha_matte(reference)
        steps.append("alpha_matte")

    # Guard against over-cleaning. If we have destroyed the artwork, back the
    # filters off one step rather than shipping a scrubbed result.
    if steps and _ssim_rgb(reference, original) < config.PREPROCESS_SSIM_FLOOR:
        warnings.append(Warning_.PREPROCESS_BACKED_OFF.value)
        reference = original.copy()
        if profile.has_alpha and not profile.alpha_is_binary:
            reference = _alpha_matte(reference)
            steps = ["alpha_matte", "backed_off"]
        else:
            steps = ["backed_off"]

    trace_input = reference
    scale = 1.0

    # Upscale is trace_input-only: the reference must keep the original
    # geometry or every score becomes a comparison against a resampled image.
    # Photographs are excluded: upscaling one quadruples an already enormous
    # trace and improves nothing — small *logos* are what this step is for.
    if (
        min(profile.width, profile.height) < config.UPSCALE_THRESHOLD_PX
        and cls != "PHOTO"
    ):
        h, w = trace_input.shape[:2]
        trace_input = cv2.resize(trace_input, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)
        scale = 2.0
        steps.append("upscale:2x")
        warnings.append(Warning_.SOURCE_RESOLUTION_LOW.value)

    quantized_colors = 0
    if cls in ("LOGO_FLAT", "SCREENSHOT", "LINE_ART") or options.max_colors:
        k = options.max_colors or profile.palette_size
        trace_input, quantized_colors = quantize(trace_input, k)
        steps.append(f"quantize:{quantized_colors}")

    return Preprocessed(
        reference=reference,
        trace_input=trace_input,
        scale=scale,
        steps=steps,
        warnings=warnings,
        quantized_colors=quantized_colors,
    )
