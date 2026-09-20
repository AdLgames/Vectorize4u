"""§3.4/§3.5 Tracing: one subprocess per candidate, run in parallel.

Both tracers are invoked as binaries, never linked. For `potrace` that is
also a licensing requirement (GPLv2 — see docs/licensing.md); for `vtracer`
it buys uniform sandboxing, timeouts and crash isolation.

Parallelism is a ThreadPoolExecutor, not `multiprocessing.Pool`: Celery
prefork workers are daemonic and cannot have children of that kind. Each
thread only waits on a subprocess, so the GIL is irrelevant.
"""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from engine import config
from engine.errors import EngineError, TracerCrash
from engine.obs import span
from engine.sandbox import resolve_binary, run
from engine.types import Params


@dataclass
class TraceResult:
    params: Params
    svg: str | None
    duration_ms: int
    exit_status: int
    error: str | None = None


def vtracer_path() -> str:
    return resolve_binary("vtracer", "ENGINE_VTRACER_BIN")


def potrace_path() -> str:
    return resolve_binary("potrace", "ENGINE_POTRACE_BIN")


def _write_png(rgba: np.ndarray, path: str) -> None:
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=False)


def _write_pbm(rgba: np.ndarray, threshold: int, path: str) -> None:
    """Flatten to bilevel for potrace. Alpha composites onto white first."""
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    rgb = rgba[:, :, :3].astype(np.float32) * a + 255.0 * (1 - a)
    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    # potrace treats 1 as black; ink is darker than the threshold.
    bits = (gray < threshold).astype(np.uint8)
    Image.fromarray((1 - bits) * 255).convert("1").save(path, format="PPM")


def _trace_vtracer(rgba: np.ndarray, params: Params, scratch: str) -> str:
    src = os.path.join(scratch, "in.png")
    dst = os.path.join(scratch, "out.svg")
    _write_png(rgba, src)
    argv = [
        vtracer_path(),
        "--input", src,
        "--output", dst,
        "--colormode", "color",
        "--hierarchical", params.hierarchical,
        "--mode", params.mode,
        "--color_precision", str(int(np.clip(params.color_precision, 1, 8))),
        "--filter_speckle", str(int(np.clip(params.filter_speckle, 0, 16))),
        "--corner_threshold", str(int(np.clip(params.corner_threshold, 0, 180))),
        "--segment_length", f"{float(np.clip(params.segment_length, 3.5, 10.0)):.2f}",
        "--splice_threshold", str(int(np.clip(params.splice_threshold, 0, 180))),
        "--gradient_step", str(int(max(0, params.gradient_step))),
        "--path_precision", "3",
    ]
    with span("engine.trace", "vtracer", params=params.key(), argv=argv):
        run(argv, timeout=config.CANDIDATE_TIMEOUT_S, scratch_dir=scratch)
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise TracerCrash("vtracer produced no output")
    with open(dst, encoding="utf-8") as fh:
        return fh.read()


def _trace_potrace(rgba: np.ndarray, params: Params, scratch: str) -> str:
    src = os.path.join(scratch, "in.pbm")
    dst = os.path.join(scratch, "out.svg")
    _write_pbm(rgba, params.threshold, src)
    argv = [
        potrace_path(),
        src,
        "-b", "svg",
        "-o", dst,
        "--turdsize", str(int(max(0, params.turdsize))),
        "--alphamax", f"{float(np.clip(params.alphamax, 0.0, 1.334)):.3f}",
        "--opttolerance", f"{float(max(0.0, params.opttolerance)):.3f}",
        "--flat",
    ]
    with span("engine.trace", "potrace", params=params.key(), argv=argv):
        run(argv, timeout=config.CANDIDATE_TIMEOUT_S, scratch_dir=scratch)
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise TracerCrash("potrace produced no output")
    with open(dst, encoding="utf-8") as fh:
        return fh.read()


def trace_one(rgba: np.ndarray, params: Params) -> TraceResult:
    import time

    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="trace-") as scratch:
            if params.engine == "potrace":
                svg = _trace_potrace(rgba, params, scratch)
            else:
                svg = _trace_vtracer(rgba, params, scratch)
        return TraceResult(
            params=params,
            svg=svg,
            duration_ms=int((time.perf_counter() - started) * 1000),
            exit_status=0,
        )
    except EngineError as exc:
        # One candidate failing is survivable: the others still produce a
        # result. A job only fails when every candidate does (see pipeline).
        return TraceResult(
            params=params,
            svg=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            exit_status=getattr(exc, "http_class", 500),
            error=f"{exc.error_code}: {exc}",
        )


def trace_all(rgba: np.ndarray, candidates: list[Params], *, max_workers: int | None = None) -> (
    list[TraceResult]
):
    workers = max_workers or min(len(candidates), os.cpu_count() or 2)
    if workers <= 1 or len(candidates) == 1:
        return [trace_one(rgba, p) for p in candidates]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trace") as pool:
        return list(pool.map(lambda p: trace_one(rgba, p), candidates))
