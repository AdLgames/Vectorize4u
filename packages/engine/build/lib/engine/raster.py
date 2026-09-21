"""SVG → PNG via `resvg`, as a subprocess.

Scoring needs a fast, correct rasterizer, and it needs the *same* one the
service uses to render preview tiles — otherwise the score describes an
image nobody ever sees.
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
from PIL import Image

from engine import config
from engine.errors import TracerCrash
from engine.obs import span
from engine.sandbox import resolve_binary, run


def resvg_path() -> str:
    return resolve_binary("resvg", "ENGINE_RESVG_BIN")


def render_svg(
    svg: str,
    *,
    width: int | None = None,
    height: int | None = None,
    zoom: float | None = None,
    background: str | None = None,
    timeout: float | None = None,
) -> np.ndarray:
    """Render to an RGBA uint8 array."""
    binary = resvg_path()
    with tempfile.TemporaryDirectory(prefix="resvg-") as scratch:
        src = os.path.join(scratch, "in.svg")
        dst = os.path.join(scratch, "out.png")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(svg)
        argv = [binary, src, dst]
        if width:
            argv += ["--width", str(int(width))]
        if height:
            argv += ["--height", str(int(height))]
        if zoom:
            argv += ["--zoom", f"{zoom:.6f}"]
        if background:
            argv += ["--background", background]
        with span("engine.rasterize", "resvg", argv=argv):
            run(argv, timeout=timeout or config.CANDIDATE_TIMEOUT_S, scratch_dir=scratch)
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise TracerCrash("resvg produced no output")
        with Image.open(dst) as img:
            return np.asarray(img.convert("RGBA"), dtype=np.uint8).copy()


def render_tile(
    svg: str, x: int, y: int, w: int, h: int, scale: float, canvas: tuple[int, int]
) -> np.ndarray:
    """Render one preview tile (§7.4).

    The service never sends the SVG to the browser before unlock; it sends
    watermarked raster tiles rendered here. An SVG in the DOM *is* the
    download, watermark or not.
    """
    scale = float(min(max(scale, 0.05), 8.0))
    full = render_svg(svg, width=int(round(canvas[0] * scale)))
    x0, y0 = max(0, int(x * scale)), max(0, int(y * scale))
    return full[y0 : y0 + int(h * scale), x0 : x0 + int(w * scale)]
