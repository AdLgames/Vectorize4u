"""Preview tile rendering (§7.4).

The watermark is composited **server-side, onto raster**. Any scheme that
ships the vector and overlays a watermark in the browser is decorative: the
SVG is already on the client, and the "watermark" is one DevTools copy away.
"""

from __future__ import annotations

import io
from functools import lru_cache

from engine.raster import render_svg
from PIL import Image, ImageDraw


def render_tile_png(
    svg: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    scale: float,
    watermark: bool,
) -> bytes:
    canvas = _canvas_size(svg)
    full = render_svg(svg, width=max(1, int(round(canvas[0] * scale))))

    x0 = max(0, int(x * scale))
    y0 = max(0, int(y * scale))
    tile = full[y0 : y0 + int(h * scale), x0 : x0 + int(w * scale)]
    if tile.size == 0:
        tile = full[:1, :1]

    image = Image.fromarray(tile, mode="RGBA")
    if watermark:
        image = _watermark(image)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _watermark(image: Image.Image) -> Image.Image:
    """Diagonal repeating mark. Visible, but not so heavy the zoom is useless.

    The zoom *is* the sales pitch — raster pixelates, vector stays sharp —
    so an unreadable preview costs conversions.
    """
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = max(120, min(image.size) // 3)
    for offset in range(-image.size[1], image.size[0], step):
        draw.line(
            [(offset, image.size[1]), (offset + image.size[1], 0)],
            fill=(15, 23, 42, 38),
            width=2,
        )
    for ty in range(0, image.size[1], step):
        for tx in range(0, image.size[0], step):
            draw.text((tx + 8, ty + 8), "PREVIEW", fill=(15, 23, 42, 90))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


@lru_cache(maxsize=256)
def _canvas_size_cached(svg_head: str) -> tuple[float, float]:
    from engine.svgdoc import parse_svg

    doc = parse_svg(svg_head)
    return (doc.width or 1024.0, doc.height or 1024.0)


def _canvas_size(svg: str) -> tuple[float, float]:
    # Parsing the whole document for two numbers is wasteful on a 1.5 MB
    # trace, and tiles are requested in bursts as the user pans.
    head = svg[:400]
    close = head.find(">")
    probe = (head[: close + 1] + "</svg>") if close > 0 else svg
    try:
        return _canvas_size_cached(probe)
    except Exception:
        return _canvas_size_cached(svg)
