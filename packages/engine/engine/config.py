"""Engine-wide limits and tunables.

Every value here is a policy decision the spec names explicitly. They are
env-overridable so the service can tighten them per plan without a code
change, but the defaults are the documented ones.
"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


# §3.1 ingest limits
MAX_BYTES = _int("ENGINE_MAX_BYTES", 25 * 1024 * 1024)
MAX_DIMENSION = _int("ENGINE_MAX_DIMENSION", 8000)
# Decompression-bomb guard (§8). Pillow's own default is 89 MP; 8000² is 64 MP.
MAX_PIXELS = _int("ENGINE_MAX_PIXELS", 80_000_000)

# §3.5 sandboxing
CANDIDATE_TIMEOUT_S = _float("ENGINE_CANDIDATE_TIMEOUT_S", 15.0)
JOB_TIMEOUT_S = _float("ENGINE_JOB_TIMEOUT_S", 60.0)
SUBPROCESS_MEMORY_MB = _int("ENGINE_SUBPROCESS_MEMORY_MB", 2048)
SUBPROCESS_CPU_S = _int("ENGINE_SUBPROCESS_CPU_S", 20)
SANDBOX_NETWORK = os.environ.get("ENGINE_SANDBOX_NETWORK", "1") != "0"

# §3.6 scoring
SCORE_MAX_SIDE = _int("ENGINE_SCORE_MAX_SIDE", 1024)
# The simplification loop re-scores up to five times. It only ever compares
# its own scores against each other, so it runs at a lower resolution than
# the score reported to the user.
SCORE_SIMPLIFY_MAX_SIDE = _int("ENGINE_SCORE_SIMPLIFY_MAX_SIDE", 512)

# §3.3 preprocessing
UPSCALE_THRESHOLD_PX = _int("ENGINE_UPSCALE_THRESHOLD_PX", 600)
PREPROCESS_SSIM_FLOOR = _float("ENGINE_PREPROCESS_SSIM_FLOOR", 0.85)

# Smoothing (`Options.smoothing`, 0-10) as a filter window along the
# contour, as a fraction of the image diagonal so a 500 px logo and a
# 4000 px one round off by the same visible amount. 3% at full strength:
# measured on a 545 px aliased logo, below about 1.5% the staircase
# survives and the corner count wanders with the setting.
SMOOTH_MAX_WINDOW_FRACTION = _float("ENGINE_SMOOTH_MAX_WINDOW_FRACTION", 0.03)
# Refit tolerance for the smoothed contour, as a fraction of the diagonal.
SMOOTH_FIT_TOLERANCE = _float("ENGINE_SMOOTH_FIT_TOLERANCE", 0.0008)
# Above this many paths, smoothing is refused rather than applied.
# A banded gradient is hundreds of stacked shapes that share their
# boundaries; smoothing each contour on its own moves those boundaries
# independently and they tear apart. Measured on a 460-path gradient
# logo, the result was a visibly ragged, spiky edge — worse than the
# banding it was asked to fix. Flat artwork, which is what smoothing is
# for, is a handful of paths.
SMOOTH_MAX_PATHS = _int("ENGINE_SMOOTH_MAX_PATHS", 32)
# Below this much excess turning the outline is not stepped, and
# smoothing it would only round off artwork. Clean logos measure
# 0.90-1.03 and the noisiest legitimate artwork 1.81; the aliased
# files start at 17.4, so the gap is wide and the threshold sits in
# the middle of it rather than against either edge.
SMOOTH_AUTO_MIN_TURNS = _float("ENGINE_SMOOTH_AUTO_MIN_TURNS", 6.0)

# §3.7 post-processing
SLIVER_AREA_FRACTION = _float("ENGINE_SLIVER_AREA_FRACTION", 0.0002)
# The same check one level down, for subpaths inside a path that is
# itself large. Two orders of magnitude tighter, because the target is
# different: a degenerate contour, not a small one. Measured on the
# benchmark sketch, whose 51 subpaths include 3 of exactly zero area
# and 17 legitimate strokes between 6.5 and 98 — at the path-level
# threshold all 20 went and the category lost 0.0557 of its score.
SLIVER_SUBPATH_AREA_FRACTION = _float("ENGINE_SLIVER_SUBPATH_AREA_FRACTION", 0.000002)
SIMPLIFY_MAX_STEPS = _int("ENGINE_SIMPLIFY_MAX_STEPS", 5)
# Above this node count, simplification is skipped entirely. Refitting Bézier
# runs is superlinear in segment count, and a 170,000-node photo trace is
# never going on a cutting machine anyway — the node penalty in the score has
# already said what needs saying about it.
SIMPLIFY_MAX_NODES = _int("ENGINE_SIMPLIFY_MAX_NODES", 40_000)
SIMPLIFY_FIDELITY_DROP = _float("ENGINE_SIMPLIFY_FIDELITY_DROP", 0.02)
COLOR_MERGE_DELTA_E = _float("ENGINE_COLOR_MERGE_DELTA_E", 2.0)
COORD_DECIMALS = _int("ENGINE_COORD_DECIMALS", 2)

# §3.8 physical size
ASSUMED_DPI = _float("ENGINE_ASSUMED_DPI", 96.0)
MM_PER_INCH = 25.4
# DPI values writers stamp on files that never measured anything.
UNTRUSTED_DPI = (72.0, 96.0, 0.0, 1.0)

# Determinism: every stochastic step (k-means, sampling) uses this seed so
# `make bench` is reproducible (§3.9).
SEED = _int("ENGINE_SEED", 1729)
