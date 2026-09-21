"""The pipeline: ingest → analyse → preprocess → candidates → trace → score →
select → post-process → emit.

This is the closed-loop parameter search from §1. The loop lives *outside*
the tracer and every candidate is compared against the reference pixels
derived from the original — never against a previous trace. Re-vectorizing a
trace is lossy and monotonically worse; there is no iteration count at which
it improves.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

import cv2
import numpy as np

from engine.analyse import analyse
from engine.emit import emit
from engine.errors import EngineError, TracerCrash
from engine.ingest import ingest
from engine.obs import span
from engine.postprocess import postprocess
from engine.presets import candidates_for
from engine.raster import render_svg
from engine.score import SCORE_VERSION, Scorer
from engine.svgdoc import SvgDoc, parse_svg
from engine.trace import trace_all
from engine.types import (
    Candidate,
    EngineResult,
    ImageProfile,
    Options,
    Params,
    Warning_,
)
from engine.version import ENGINE_VERSION


class _Timer:
    def __init__(self) -> None:
        self.marks: dict[str, int] = {}

    @contextmanager
    def __call__(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.marks[name] = self.marks.get(name, 0) + int(
                (time.perf_counter() - started) * 1000
            )


def _text_boxes(rgba: np.ndarray, profile: ImageProfile) -> list[tuple[float, float, float, float]]:
    """Glyph boxes, used only to protect small text shapes from sliver removal."""
    if profile.estimated_text_regions == 0:
        return []
    from engine.analyse import text_like_boxes

    gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
    return text_like_boxes(gray)


def _profile_warnings(profile: ImageProfile) -> list[str]:
    out: list[str] = []
    if profile.classification == "PHOTO":
        out.append(Warning_.PHOTO_INPUT.value)
    if profile.classification == "LOGO_GRADIENT":
        out.append(Warning_.GRADIENTS_BANDED.value)
    if profile.classification_confidence < 0.35:
        out.append(Warning_.LOW_CONFIDENCE_CLASSIFICATION.value)
    return out


def run(data: bytes, options: Options | None = None) -> EngineResult:
    """Vectorize `data`. Raises only when *every* candidate fails."""
    options = options or Options()
    timer = _Timer()
    warnings: list[str] = []

    with timer("ingest"):
        ing = ingest(data, alpha_mode=options.alpha_mode)
    warnings += ing.warnings

    with timer("analyse"):
        profile = analyse(ing, mode_override=options.mode)
    warnings += _profile_warnings(profile)

    with timer("preprocess"):
        from engine.preprocess import preprocess

        pre = preprocess(ing.rgba, profile, options)
    warnings += pre.warnings

    with timer("candidates"):
        candidates = candidates_for(profile, options, pre.trace_input)

    with timer("trace"), span("engine.trace_all", candidates=len(candidates)):
        traces = trace_all(pre.trace_input, candidates)

    # Timed explicitly: the baselines here are the one part of scoring whose
    # cost scales with the *source*, not with the candidate count.
    with timer("baselines"):
        scorer = Scorer(
            pre.reference,
            classification=profile.classification,
            edge_pixel_count=profile.edge_pixel_count,
            quantized=pre.trace_input if pre.quantized_colors else None,
        )

    scored: list[Candidate] = []
    with timer("score"):
        for tr in traces:
            if tr.svg is None:
                scored.append(
                    Candidate(
                        params=tr.params,
                        svg=None,
                        score=None,
                        duration_ms=tr.duration_ms,
                        exit_status=tr.exit_status,
                        error=tr.error,
                    )
                )
                continue
            try:
                doc = parse_svg(tr.svg)
                raster = render_svg(tr.svg, width=scorer.size[0])
                score = scorer.score_raster(
                    raster, nodes=doc.node_count(), paths=doc.path_count()
                )
            except EngineError as exc:
                scored.append(
                    Candidate(
                        params=tr.params,
                        svg=None,
                        score=None,
                        duration_ms=tr.duration_ms,
                        exit_status=500,
                        error=f"{exc.error_code}: {exc}",
                    )
                )
                continue
            scored.append(
                Candidate(
                    params=tr.params,
                    svg=tr.svg,
                    score=score,
                    duration_ms=tr.duration_ms,
                    exit_status=0,
                )
            )

    usable = [c for c in scored if c.score is not None and c.svg is not None]
    if not usable:
        errors = "; ".join(c.error or "?" for c in scored)[:500]
        raise TracerCrash(f"every candidate failed: {errors}")

    # Selection is by `total`, which includes the node/path penalties.
    winner = max(usable, key=lambda c: c.score.total)  # type: ignore[union-attr]
    winner.selected = True

    doc = parse_svg(winner.svg)  # type: ignore[arg-type]
    # trace_input may have been upscaled; bring geometry back to the
    # reference's coordinate system so physical size stays honest.
    if pre.scale != 1.0:
        doc = _rescale(doc, 1.0 / pre.scale)

    score = winner.score  # type: ignore[assignment]
    refinements = 0
    if _should_refine(options):
        with timer("refine"):
            from engine.refine import refine as refine_regions

            refined = refine_regions(
                doc,
                scorer=scorer,
                trace_input=pre.trace_input,
                input_scale=pre.scale,
                params=winner.params,
                base_score=score,  # type: ignore[arg-type]
            )
            doc, score, refinements = refined.doc, refined.score, refined.regions_kept

    with timer("postprocess"):

        min_spacing_px = _min_spacing_px(doc, profile, options)
        post = postprocess(
            doc,
            scorer,
            score,  # type: ignore[arg-type]
            text_boxes=_text_boxes(pre.reference, profile),
            min_spacing_px=min_spacing_px,
            simplify_enabled=options.simplify,
        )
    warnings += post.warnings

    with timer("emit"):
        emitted = emit(post.doc, profile, options)
    warnings += emitted.warnings

    return EngineResult(
        svg=emitted.svg,
        profile=profile,
        chosen_params=winner.params,
        score=post.score,
        candidates=scored,
        warnings=list(dict.fromkeys(warnings)),
        physical_size=emitted.physical_size,
        engine_version=ENGINE_VERSION,
        score_version=SCORE_VERSION,
        timings_ms=timer.marks,
        outputs=emitted.outputs,
        refinements=refinements,
    )


def _should_refine(options: Options) -> bool:
    """Opt-in only (§1: "an optimisation, not a foundation").

    Refinement costs another trace and two more renders per region — about
    1.5 s on the `max` tier — and on the current corpus it earns roughly
    +0.001 fidelity. That is not a trade worth making on a customer's
    behalf, so it is off until a real corpus says otherwise.

    `forced_params` is the advanced panel asking for one specific trace
    (§7.6); refining it would mean returning something the user did not
    ask for.
    """
    return options.refine and options.forced_params is None


def _min_spacing_px(doc: SvgDoc, profile: ImageProfile, options: Options) -> float:
    """Convert min_node_spacing_mm into user units.

    Applied even when the physical size is only assumed — a cut file with
    knowingly assumed scale still benefits, and the job carries the
    `physical_size_assumed` warning either way (§3.7 step 3).
    """
    from engine.emit import resolve_physical_size

    size, _ = resolve_physical_size(doc, profile, options)
    if size.width_mm <= 0 or doc.width <= 0:
        return 0.0
    px_per_mm = doc.width / size.width_mm
    return float(options.min_node_spacing_mm * px_per_mm)


def _rescale(doc: SvgDoc, factor: float) -> SvgDoc:
    for p in doc.paths:
        for sp in p.subpaths:
            sp.start = (sp.start[0] * factor, sp.start[1] * factor)
            sp.segments = [
                (kind, tuple((x * factor, y * factor) for x, y in args))
                for kind, args in sp.segments
            ]
    doc.width *= factor
    doc.height *= factor
    return doc


def run_single(data: bytes, params: Params, options: Options | None = None) -> EngineResult:
    """One trace, no search — the advanced panel's instant-feedback path (§7.6)."""
    opts = options or Options()
    opts.forced_params = params
    opts.quality_tier = "fast"
    return run(data, opts)
