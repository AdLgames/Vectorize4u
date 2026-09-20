"""§3.2 Analyse: statistics only, no pixels.

The result is persisted as `jobs.profile`, which is what lets the dataset
survive file deletion (§5). Nothing here may leak image content.
"""

from __future__ import annotations

import cv2
import numpy as np

from engine import config
from engine.classify import classify
from engine.color import to_hex
from engine.ingest import IngestResult
from engine.types import ImageProfile


def _flatten_on_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    rgb = rgba[:, :, :3].astype(np.float32)
    return (rgb * a + 255.0 * (1 - a)).astype(np.uint8)


def to_gray(rgba: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(_flatten_on_white(rgba), cv2.COLOR_RGB2GRAY)


def canny(gray: np.ndarray) -> np.ndarray:
    """Otsu-anchored Canny.

    Fixed 100/200 thresholds behave completely differently on a flat logo and
    a photo, which would make `edge_density` incomparable across the corpus.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    high, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    high = float(np.clip(high, 30, 200))
    return cv2.Canny(blurred, high * 0.5, high)


def _unique_colors(rgba: np.ndarray, sample: int = 400_000) -> int:
    rgb = _flatten_on_white(rgba).reshape(-1, 3)
    if rgb.shape[0] > sample:
        rng = np.random.default_rng(config.SEED)
        rgb = rgb[rng.choice(rgb.shape[0], sample, replace=False)]
    packed = (rgb[:, 0].astype(np.uint32) << 16) | (rgb[:, 1].astype(np.uint32) << 8) | rgb[:, 2]
    return int(np.unique(packed).size)


def _jpeg_artifact_score(gray: np.ndarray) -> float:
    """Blockiness on the 8×8 DCT grid.

    Mean absolute gradient on grid-aligned columns/rows against the mean on
    the others, over *active* lines only. It is a real signal on photographic
    content and a noisy one on hard-edged synthetic art, where a couple of
    shape edges can land on the grid by luck — which is why preprocessing
    also requires a lossy source format before it de-artifacts anything
    (see `preprocess`). Reported honestly rather than massaged: the service
    persists it, and a number that quietly means something else is worse
    than a noisy one.
    """
    g = gray.astype(np.float32)
    if g.shape[0] < 24 or g.shape[1] < 24:
        return 0.0
    dx = np.abs(np.diff(g, axis=1))
    dy = np.abs(np.diff(g, axis=0))
    ratios: list[float] = []
    for profile in (dx.mean(axis=0), dy.mean(axis=1)):
        on_grid = (np.arange(profile.size) + 1) % 8 == 0
        active = profile > 0.15
        aligned = profile[on_grid & active]
        rest = profile[(~on_grid) & active]
        if aligned.size < 8 or rest.size < 32:
            continue
        ratios.append(float(aligned.mean()) / max(float(rest.mean()), 0.15) - 1.0)
    if not ratios:
        return 0.0
    return float(np.clip(sum(ratios) / len(ratios), 0.0, 5.0))


def text_like_boxes(gray: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Glyph-sized connected components, both polarities.

    §3.2 allows MSER or text-aspect connected components. Connected
    components win here: MSER merges whole words at small point sizes, which
    made a page of UI text read as three regions. Two consumers depend on
    this — the SCREENSHOT rule, and sliver removal, which must not delete
    the counters inside small glyphs (§3.7 step 1).
    """
    h, w = gray.shape
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    boxes: list[tuple[float, float, float, float]] = []
    for polarity in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        _, bw = cv2.threshold(blurred, 0, 255, polarity + cv2.THRESH_OTSU)
        n, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
        if n > 6000:  # a texture, not text; bail rather than burn the budget
            continue
        for i in range(1, n):
            x, y, cw, ch, area = (int(v) for v in stats[i])
            if ch < 4 or cw < 2:
                continue
            if ch > h * 0.25 or cw > w * 0.25:
                continue
            aspect = cw / ch
            if not 0.08 <= aspect <= 3.0:
                continue
            density = area / float(cw * ch)
            if not 0.12 <= density <= 0.95:
                continue
            boxes.append((float(x), float(y), float(x + cw), float(y + ch)))
    return boxes


def _text_regions(gray: np.ndarray) -> int:
    return len(text_like_boxes(gray))


def dominant_palette(
    rgb: np.ndarray, k_min: int = 2, k_max: int = 32
) -> tuple[list[tuple[int, int, int]], int]:
    """k-means with elbow selection and a fixed seed.

    Determinism matters here: the palette feeds quantization, which feeds the
    tracer, which feeds the score. A wandering seed makes `make bench`
    meaningless.
    """
    flat = rgb.reshape(-1, 3).astype(np.float32)
    rng = np.random.default_rng(config.SEED)
    if flat.shape[0] > 60_000:
        flat = flat[rng.choice(flat.shape[0], 60_000, replace=False)]

    distinct = np.unique(flat, axis=0)
    if distinct.shape[0] <= k_min:
        colors = [tuple(int(v) for v in c) for c in distinct]
        return colors, max(1, len(colors))

    k_max = int(min(k_max, distinct.shape[0]))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    inertias: dict[int, float] = {}
    centers: dict[int, np.ndarray] = {}
    ks = [k for k in (2, 3, 4, 6, 8, 12, 16, 24, 32) if k_min <= k <= k_max]
    if not ks:
        ks = [k_max]
    for k in ks:
        cv2.setRNGSeed(config.SEED)
        compactness, _, cen = cv2.kmeans(
            flat, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
        inertias[k] = float(compactness) / flat.shape[0]
        centers[k] = cen

    # Elbow: first k whose marginal improvement drops below 15% of the first
    # improvement seen. Cheap, stable, and good enough to pick a palette.
    best_k = ks[-1]
    if len(ks) > 2:
        drops = [inertias[ks[i]] - inertias[ks[i + 1]] for i in range(len(ks) - 1)]
        first = max(drops[0], 1e-9)
        for i, d in enumerate(drops):
            if d < 0.15 * first:
                best_k = ks[i]
                break
        else:
            best_k = ks[-1]

    cen = centers[best_k]
    order = np.argsort(cen.sum(axis=1))
    return [tuple(int(round(v)) for v in cen[i]) for i in order], best_k


def flat_color_ratio(rgb: np.ndarray, palette: list[tuple[int, int, int]]) -> float:
    """How much of the image sits on its own palette.

    JPEG recompression explodes `unique_colors` without changing the
    artwork's nature; this stays near 1.0 for flat logos and drops for
    photographs and painted illustration.
    """
    from engine.color import delta_e2000, srgb_to_lab

    if not palette:
        return 0.0
    small = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    lab_px = srgb_to_lab(small)
    lab_pal = srgb_to_lab(np.array(palette, dtype=np.float32))
    best = np.full(lab_px.shape[0], np.inf)
    for centre in lab_pal:
        d = delta_e2000(lab_px, np.broadcast_to(centre, lab_px.shape))
        best = np.minimum(best, d)
    return float(np.mean(best < 4.0))


def analyse(ing: IngestResult, *, mode_override: str = "auto") -> ImageProfile:
    rgba = ing.rgba
    h, w = rgba.shape[:2]
    rgb = _flatten_on_white(rgba)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    edges = canny(gray)
    edge_pixels = int(np.count_nonzero(edges))
    edge_density = edge_pixels / float(h * w)

    alpha = rgba[:, :, 3]
    has_alpha = bool((alpha < 255).any())
    alpha_is_binary = bool(np.isin(alpha, (0, 255)).all())

    channels_equal = bool(
        np.array_equal(rgba[:, :, 0], rgba[:, :, 1])
        and np.array_equal(rgba[:, :, 1], rgba[:, :, 2])
    )
    is_bilevel = channels_equal and bool(np.isin(rgba[:, :, 0], (0, 255)).all())

    noise = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    palette, palette_size = dominant_palette(rgb)

    profile_kwargs = {
        "source_format": ing.source_format,
        "width": w,
        "height": h,
        "unique_colors": _unique_colors(rgba),
        "edge_density": edge_density,
        "edge_pixel_count": edge_pixels,
        "has_alpha": has_alpha,
        "alpha_is_binary": alpha_is_binary,
        "alpha_was_premultiplied": ing.alpha_was_premultiplied,
        "is_grayscale": channels_equal,
        "is_bilevel": is_bilevel,
        "noise_estimate": noise,
        "jpeg_artifact_score": _jpeg_artifact_score(gray),
        "estimated_text_regions": _text_regions(gray),
        "dominant_palette": [to_hex(c) for c in palette],
        "palette_size": palette_size,
        "flat_color_ratio": flat_color_ratio(rgb, palette),
        "source_dpi": ing.source_dpi,
        "source_dpi_trusted": ing.source_dpi_trusted,
    }

    classification, confidence, scores = classify(rgba, profile_kwargs, mode_override)
    return ImageProfile(
        classification=classification,
        classification_confidence=confidence,
        class_scores=scores,
        **profile_kwargs,  # type: ignore[arg-type]
    )
