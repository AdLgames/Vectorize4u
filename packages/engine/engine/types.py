"""Shared value types for the engine.

Everything here is pure data: no web, no DB, no filesystem. `ImageProfile`
and `ScoreVector` are persisted verbatim by the service (§5), so they carry
statistics only — never pixels.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

Classification = Literal[
    "LOGO_FLAT",
    "LOGO_GRADIENT",
    "LINE_ART",
    "SKETCH",
    "ILLUSTRATION",
    "PHOTO",
    "SCREENSHOT",
]

CLASSIFICATIONS: tuple[Classification, ...] = (
    "LOGO_FLAT",
    "LOGO_GRADIENT",
    "LINE_ART",
    "SKETCH",
    "ILLUSTRATION",
    "PHOTO",
    "SCREENSHOT",
)

AlphaMode = Literal["auto", "straight", "premultiplied"]
QualityTier = Literal["fast", "standard", "max"]
Units = Literal["mm", "in"]
Detail = Literal["low", "balanced", "high"]
PhysicalSizeSource = Literal["user", "metadata", "assumed"]

TIER_CANDIDATES: dict[str, int] = {"fast": 1, "standard": 4, "max": 8}


class Warning_(StrEnum):
    """Stable warning codes. Surfaced by the API and the UI verbatim."""

    PHOTO_INPUT = "photo_input"
    GRADIENTS_BANDED = "gradients_banded"
    SOURCE_RESOLUTION_LOW = "source_resolution_low"
    PHYSICAL_SIZE_ASSUMED = "physical_size_assumed"
    PREPROCESS_BACKED_OFF = "preprocess_backed_off"
    ALPHA_PREMULTIPLIED_FIXED = "alpha_premultiplied_fixed"
    CMYK_CONVERTED = "cmyk_converted"
    EXIF_ROTATED = "exif_rotated"
    LOW_CONFIDENCE_CLASSIFICATION = "low_confidence_classification"
    TRACER_UNAVAILABLE = "tracer_unavailable"
    SIMPLIFY_STOPPED_EARLY = "simplify_stopped_early"
    SIMPLIFY_SKIPPED_LARGE = "simplify_skipped_large"
    NODE_SPACING_ENFORCED = "node_spacing_enforced"


@dataclass(frozen=True)
class ImageProfile:
    """Statistics computed in §3.2. Persisted as `jobs.profile`."""

    source_format: str
    width: int
    height: int
    unique_colors: int
    edge_density: float
    edge_pixel_count: int
    has_alpha: bool
    alpha_is_binary: bool
    alpha_was_premultiplied: bool
    is_grayscale: bool
    is_bilevel: bool
    noise_estimate: float
    jpeg_artifact_score: float
    estimated_text_regions: int
    dominant_palette: list[str]
    palette_size: int
    # Fraction of pixels within ΔE2000 < 4 of their nearest palette colour.
    # `unique_colors` is unreliable on re-compressed JPEGs — a 4-colour logo
    # can report 9000 colours — so this is what separates flat artwork from
    # genuinely continuous-tone artwork.
    flat_color_ratio: float
    source_dpi: float | None
    source_dpi_trusted: bool
    classification: Classification
    classification_confidence: float
    class_scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Params:
    """One point in tracer parameter space.

    `engine` selects the binary. vtracer knobs are ignored by potrace and
    vice versa, which keeps the candidate list a flat, serialisable thing
    that can be stored in `job_candidates.params` and replayed later.
    """

    engine: Literal["vtracer", "potrace"] = "vtracer"
    label: str = ""
    # vtracer
    color_precision: int = 6
    filter_speckle: int = 4
    corner_threshold: int = 60
    segment_length: float = 4.0
    splice_threshold: int = 45
    mode: Literal["spline", "polygon", "pixel"] = "spline"
    gradient_step: int = 16
    # `stacked` always: cutout mode makes sliver removal punch holes (§3.4).
    hierarchical: Literal["stacked", "cutout"] = "stacked"
    # potrace
    threshold: int = 128
    turdsize: int = 2
    alphamax: float = 1.0
    opttolerance: float = 0.2

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def key(self) -> str:
        if self.engine == "potrace":
            return (
                f"potrace:t{self.threshold}:turd{self.turdsize}:"
                f"a{self.alphamax}:o{self.opttolerance}"
            )
        return (
            f"vtracer:cp{self.color_precision}:fs{self.filter_speckle}:"
            f"ct{self.corner_threshold}:sl{self.segment_length}:"
            f"st{self.splice_threshold}:{self.mode}:gs{self.gradient_step}"
        )


@dataclass(frozen=True)
class ScoreVector:
    """Per-candidate score (§3.6). Persisted in `job_candidates.score`."""

    ssim: float
    color: float
    edge_f1: float
    alpha_iou: float | None
    node_term: float
    path_term: float
    fidelity: float
    total: float
    nodes: int
    paths: int
    score_version: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Candidate:
    params: Params
    svg: str | None
    score: ScoreVector | None
    duration_ms: int
    exit_status: int
    error: str | None = None
    selected: bool = False

    def as_row(self) -> dict[str, Any]:
        """Shape of a `job_candidates` row (§5)."""
        return {
            "params": self.params.as_dict(),
            "score": self.score.as_dict() if self.score else None,
            "fidelity": self.score.fidelity if self.score else None,
            "total": self.score.total if self.score else None,
            "selected": self.selected,
            "node_count": self.score.nodes if self.score else None,
            "path_count": self.score.paths if self.score else None,
            "exit_status": self.exit_status,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class PhysicalSize:
    width_mm: float
    height_mm: float
    source: PhysicalSizeSource


@dataclass
class Options:
    """Caller-facing options (§6). Defaults are the `standard` web path."""

    mode: Literal["auto", "flat", "lineart", "sketch", "photo"] = "auto"
    quality_tier: QualityTier = "standard"
    detail: Detail = "balanced"
    max_colors: int | None = None
    simplify: bool = True
    keep_background: bool = True
    # Overrides each candidate's `filter_speckle`. The UI exposes this
    # because a phone photo of a sign and a clean export need very
    # different amounts of speckle removal, and the difference is visible.
    despeckle: int | None = None
    alpha_mode: AlphaMode = "auto"
    output_width: float | None = None
    output_height: float | None = None
    units: Units = "mm"
    dxf_tolerance: float = 0.1
    min_node_spacing_mm: float = 0.1
    formats: tuple[str, ...] = ("svg",)
    # Escape hatch for the advanced panel (§7.6): a single forced candidate.
    forced_params: Params | None = None
    # Localised refinement (§1, Phase 8). Off by default, and deliberately
    # not exposed in the public API yet: on the current corpus it earns
    # about +0.001 fidelity for ~10% more nodes, which is not enough to
    # spend a customer's seconds on. `benchmarks/refine_report.py` is what
    # would change that verdict on a real corpus.
    refine: bool = False


@dataclass
class EngineResult:
    svg: str
    profile: ImageProfile
    chosen_params: Params
    score: ScoreVector
    candidates: list[Candidate]
    warnings: list[str]
    physical_size: PhysicalSize
    engine_version: str
    score_version: str
    timings_ms: dict[str, int]
    outputs: dict[str, bytes] = field(default_factory=dict)
    # How many regions localised refinement re-traced and kept (§1). Zero on
    # every tier but `max`, and zero there too unless a re-trace scored
    # better than what it replaced.
    refinements: int = 0
