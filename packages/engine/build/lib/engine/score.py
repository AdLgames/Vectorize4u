"""§3.6 Scoring.

Every candidate is rasterized with the same renderer the service uses and
compared against the **cleaned reference**, never the raw source — scoring
against the raw source rewards traces that faithfully reproduce JPEG blocks
and halos.

Scoring runs at reduced resolution (longest side 1024). Full-resolution
SSIM + ΔE2000 over 4 MP × N candidates blows the whole latency budget on its
own.

Two outputs:
  fidelity — the first four terms, renormalised. "How close is it?"
  total    — all six, including the node/path penalties. Used for selection.

The penalty terms stop the scorer from always picking the highest-detail
trace. A 50,000-node SVG scores best on pure SSIM and is useless on a
cutting machine. DO NOT "FIX" THIS.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path as FsPath

import cv2
import numpy as np

from engine import config
from engine.analyse import canny
from engine.color import srgb_to_lab
from engine.types import ScoreVector

# Any change to a term, a weight, a radius or a baseline bumps this, and the
# same PR regenerates benchmarks/baseline.json. Scores from different
# versions are never compared.
SCORE_VERSION = "s3"

WEIGHTS: dict[str, float] = {
    "ssim": 0.35,
    "color": 0.20,
    "edge_f1": 0.20,
    "alpha_iou": 0.10,
    "node_term": 0.10,
    "path_term": 0.05,
}
FIDELITY_TERMS = ("ssim", "color", "edge_f1", "alpha_iou")

_CALIBRATION = json.loads((FsPath(__file__).parent / "calibration.json").read_text())


def k_class(classification: str) -> float:
    return float(_CALIBRATION["k_class"].get(classification, _CALIBRATION["default_k"]))


def downscale(rgba: np.ndarray, max_side: int = config.SCORE_MAX_SIDE) -> np.ndarray:
    h, w = rgba.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return rgba
    f = max_side / longest
    out: np.ndarray = cv2.resize(
        rgba,
        (max(1, int(round(w * f))), max(1, int(round(h * f)))),
        interpolation=cv2.INTER_AREA,
    )
    return out


def composite(rgba: np.ndarray) -> np.ndarray:
    """Flatten onto white. Both sides get exactly the same treatment."""
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    flat: np.ndarray = (rgba[:, :, :3].astype(np.float32) * a + 255.0 * (1 - a)).astype(np.uint8)
    return flat


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    from skimage.metrics import structural_similarity

    ga = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    smallest = min(ga.shape)
    win = min(7, smallest if smallest % 2 == 1 else smallest - 1)
    if win < 3:
        return 1.0
    value = float(structural_similarity(ga, gb, win_size=win, data_range=255))  # type: ignore[no-untyped-call]
    return float(np.clip(value, 0.0, 1.0))


def _color_term(ref: np.ndarray, cand: np.ndarray, opaque: np.ndarray) -> float:
    from engine.color import delta_e2000

    if not opaque.any():
        return 1.0
    lab_r = srgb_to_lab(ref[opaque])
    lab_c = srgb_to_lab(cand[opaque])
    mean_de = float(np.mean(delta_e2000(lab_r, lab_c)))
    return float(1.0 - min(mean_de, 20.0) / 20.0)


def _edge_f1(ref: np.ndarray, cand: np.ndarray) -> float:
    """Dilated-edge F1.

    Plain IoU collapses on a 1 px shift, which is exactly the error a good
    trace makes. The dilation radius scales with the image diagonal so the
    tolerance means the same thing at any size.
    """
    er = canny(cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)) > 0
    ec = canny(cv2.cvtColor(cand, cv2.COLOR_RGB2GRAY)) > 0
    if not er.any() and not ec.any():
        return 1.0
    if not er.any() or not ec.any():
        return 0.0
    diag = math.hypot(*ref.shape[:2])
    r = max(1, int(round(0.002 * diag)))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    dr = cv2.dilate(er.astype(np.uint8), k) > 0
    dc = cv2.dilate(ec.astype(np.uint8), k) > 0
    precision = float(np.count_nonzero(ec & dr)) / float(np.count_nonzero(ec))
    recall = float(np.count_nonzero(er & dc)) / float(np.count_nonzero(er))
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _alpha_iou(ref: np.ndarray, cand: np.ndarray) -> float:
    a = ref[:, :, 3] >= 128
    b = cand[:, :, 3] >= 128
    union = np.count_nonzero(a | b)
    if union == 0:
        return 1.0
    return float(np.count_nonzero(a & b)) / float(union)


def _penalty(count: int, baseline: float) -> float:
    """1 / (1 + ln(max(1, count / baseline))).

    The max(1, …) is load-bearing: without it the formula divides by zero at
    count = baseline / e and goes negative below it, handing a free bonus to
    degenerate traces with almost no geometry.
    """
    baseline = max(baseline, 1.0)
    return 1.0 / (1.0 + math.log(max(1.0, count / baseline)))


def path_baseline(reference: np.ndarray, quantized: np.ndarray | None = None) -> float:
    """Connected colour regions in the *quantized* reference, above sliver size.

    The quantization is not optional: counting regions over a photograph's
    quarter-million distinct colours means a connected-components pass per
    colour, which costs minutes. Small side length for the same reason — the
    count is a baseline, not a measurement.
    """
    src = quantized if quantized is not None else reference
    rgb = composite(downscale(src, 384))
    h, w = rgb.shape[:2]
    flat = rgb.reshape(-1, 3)
    if np.unique(flat, axis=0).shape[0] > 64:
        cv2.setRNGSeed(config.SEED)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, centers = cv2.kmeans(  # type: ignore[call-overload]
            flat.astype(np.float32), 32, None, criteria, 2, cv2.KMEANS_PP_CENTERS
        )
        rgb = centers[labels.ravel()].reshape(h, w, 3).astype(np.uint8)

    packed = (
        rgb[:, :, 0].astype(np.int32) * 65536
        + rgb[:, :, 1].astype(np.int32) * 256
        + rgb[:, :, 2].astype(np.int32)
    )
    min_area = max(4.0, config.SLIVER_AREA_FRACTION * h * w)
    total = 0
    for value in np.unique(packed):
        mask = (packed == value).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        total += int(np.count_nonzero(stats[1:, cv2.CC_STAT_AREA] >= min_area))
    return float(max(1, total))


def node_baseline(edge_pixel_count: int, classification: str) -> float:
    return max(1.0, k_class(classification) * edge_pixel_count / 1000.0)


class Scorer:
    """Holds everything that is constant across candidates for one job.

    Rebuilding the reference pyramid and the baselines per candidate is a
    measurable share of the latency budget at 8 candidates.
    """

    def __init__(
        self,
        reference: np.ndarray,
        *,
        classification: str,
        edge_pixel_count: int,
        quantized: np.ndarray | None = None,
    ) -> None:
        self.reference_small = downscale(reference)
        self.ref_rgb = composite(self.reference_small)
        self.has_alpha = bool((reference[:, :, 3] < 255).any())
        self.opaque = self.reference_small[:, :, 3] >= 128
        if not self.opaque.any():
            self.opaque = np.ones(self.reference_small.shape[:2], dtype=bool)
        self.node_baseline = node_baseline(edge_pixel_count, classification)
        self.path_baseline = path_baseline(reference, quantized)
        self.size = (self.reference_small.shape[1], self.reference_small.shape[0])

    def reduced(self, max_side: int) -> Scorer:
        """A cheaper view of the same job for the simplification loop.

        The node and path baselines are resolution-independent, so they are
        carried over rather than recomputed. Scores from this scorer are only
        ever compared against each other (§3.7's stop rule), never against a
        score reported to a user.
        """
        clone = object.__new__(Scorer)
        clone.reference_small = downscale(self.reference_small, max_side)
        clone.ref_rgb = composite(clone.reference_small)
        clone.has_alpha = self.has_alpha
        clone.opaque = clone.reference_small[:, :, 3] >= 128
        if not clone.opaque.any():
            clone.opaque = np.ones(clone.reference_small.shape[:2], dtype=bool)
        clone.node_baseline = self.node_baseline
        clone.path_baseline = self.path_baseline
        clone.size = (clone.reference_small.shape[1], clone.reference_small.shape[0])
        return clone

    def score_raster(self, candidate: np.ndarray, *, nodes: int, paths: int) -> ScoreVector:
        cand = candidate
        if cand.shape[:2] != self.reference_small.shape[:2]:
            cand = cv2.resize(cand, self.size, interpolation=cv2.INTER_AREA)
        cand_rgb = composite(cand)

        terms: dict[str, float] = {
            "ssim": _ssim(self.ref_rgb, cand_rgb),
            "color": _color_term(self.ref_rgb, cand_rgb, self.opaque),
            "edge_f1": _edge_f1(self.ref_rgb, cand_rgb),
            "node_term": _penalty(nodes, self.node_baseline),
            "path_term": _penalty(paths, self.path_baseline),
        }
        alpha_iou: float | None = None
        if self.has_alpha:
            alpha_iou = _alpha_iou(self.reference_small, cand)
            terms["alpha_iou"] = alpha_iou

        total = _weighted(terms, WEIGHTS.keys())
        fidelity = _weighted(terms, FIDELITY_TERMS)
        return ScoreVector(
            ssim=round(terms["ssim"], 5),
            color=round(terms["color"], 5),
            edge_f1=round(terms["edge_f1"], 5),
            alpha_iou=round(alpha_iou, 5) if alpha_iou is not None else None,
            node_term=round(terms["node_term"], 5),
            path_term=round(terms["path_term"], 5),
            fidelity=round(fidelity, 5),
            total=round(total, 5),
            nodes=nodes,
            paths=paths,
            score_version=SCORE_VERSION,
        )


def _weighted(terms: dict[str, float], keys: Iterable[str]) -> float:
    """Sum of present terms, renormalised over the weights that applied.

    Dropping a term (no alpha in the source) must not silently lower the
    score: the remaining weights are renormalised, exactly as §3.6 says.
    """
    num = 0.0
    den = 0.0
    for k in keys:
        if k in terms:
            num += WEIGHTS[k] * terms[k]
            den += WEIGHTS[k]
    return num / den if den else 0.0
