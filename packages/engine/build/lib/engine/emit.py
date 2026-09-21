"""§3.8 Emit.

Physical size is resolved in this order, and only this order:

  1. user-supplied output_width/height + units
  2. metadata DPI, **only** if source_dpi_trusted
  3. assume 96 dpi and return warning `physical_size_assumed`

A 400 px logo has no meaningful DPI. Deriving real-world scale from it
produces confidently wrong sizes, and "confidently wrong" is the one failure
a cutter user cannot recover from.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from engine import config
from engine.geom import flatten_cubic
from engine.svgdoc import SvgDoc, serialize
from engine.types import ImageProfile, Options, PhysicalSize, Units, Warning_

MM_PER_INCH = config.MM_PER_INCH


@dataclass
class EmitResult:
    outputs: dict[str, bytes]
    svg: str
    physical_size: PhysicalSize
    warnings: list[str]


def resolve_physical_size(
    doc: SvgDoc, profile: ImageProfile, options: Options
) -> tuple[PhysicalSize, list[str]]:
    warnings: list[str] = []
    aspect = (doc.height / doc.width) if doc.width else 1.0

    def mm(value: float, units: Units) -> float:
        return value if units == "mm" else value * MM_PER_INCH

    if options.output_width or options.output_height:
        if options.output_width and options.output_height:
            w = mm(options.output_width, options.units)
            h = mm(options.output_height, options.units)
        elif options.output_width:
            w = mm(options.output_width, options.units)
            h = w * aspect
        else:
            h = mm(options.output_height or 0.0, options.units)
            w = h / aspect if aspect else h
        return PhysicalSize(width_mm=w, height_mm=h, source="user"), warnings

    if profile.source_dpi_trusted and profile.source_dpi:
        w = doc.width / profile.source_dpi * MM_PER_INCH
        return PhysicalSize(w, w * aspect, "metadata"), warnings

    warnings.append(Warning_.PHYSICAL_SIZE_ASSUMED.value)
    w = doc.width / config.ASSUMED_DPI * MM_PER_INCH
    return PhysicalSize(w, w * aspect, "assumed"), warnings


def apply_physical_size(doc: SvgDoc, size: PhysicalSize) -> SvgDoc:
    """SVG carries explicit physical width/height *and* a viewBox.

    Most Cricut users import SVG, not DXF, and cutting apps disagree about
    what a unitless SVG means. Being explicit is the difference between
    "opens at the right size" and a support ticket.
    """
    doc.phys_width = f"{size.width_mm:.4f}mm"
    doc.phys_height = f"{size.height_mm:.4f}mm"
    return doc


def _polylines(doc: SvgDoc, tolerance_units: float) -> list[tuple[str, list[tuple[float, float]]]]:
    """Flatten every path to polylines. Most cutters cannot read curves."""
    out = []
    for p in doc.paths:
        for sp in p.subpaths:
            pts = [sp.start]
            cursor = sp.start
            for kind, args in sp.segments:
                if kind == "L":
                    pts.append(args[0])
                    cursor = args[0]
                else:
                    c1, c2, end = args
                    pts.extend(flatten_cubic(cursor, c1, c2, end, tolerance_units))
                    cursor = end
            if sp.closed and pts[0] != pts[-1]:
                pts.append(pts[0])
            if len(pts) >= 2:
                out.append((p.fill, pts))
    return out


def to_dxf(doc: SvgDoc, size: PhysicalSize, *, tolerance_mm: float, units: Units) -> bytes:
    """DXF with explicit absolute units.

    `$INSUNITS` is set and the geometry is scaled into real mm/inches. A DXF
    without units imports at whatever scale the receiving app guesses, which
    is the single most common "your file is wrong" complaint from LightBurn
    and Cricut users.
    """
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "DXF export requires ezdxf (pip install 'vectorize-engine[emit]')"
        ) from exc

    # 4 = millimetres, 1 = inches, per the DXF spec.
    insunits = 4 if units == "mm" else 1
    scale = (size.width_mm / doc.width) if doc.width else 1.0
    if units == "in":
        scale /= MM_PER_INCH

    tol_units = max(1e-4, tolerance_mm * (doc.width / size.width_mm if size.width_mm else 1.0))

    drawing = ezdxf.new(dxfversion="R2010", setup=True)  # type: ignore[attr-defined]
    drawing.header["$INSUNITS"] = insunits
    drawing.header["$MEASUREMENT"] = 1 if units == "mm" else 0
    msp = drawing.modelspace()

    for fill, pts in _polylines(doc, tol_units):
        layer = f"color-{fill.lstrip('#')}"
        if layer not in drawing.layers:
            drawing.layers.add(layer)
        # DXF y grows upward; SVG y grows downward. Flip, or every cut file
        # comes out mirrored.
        coords = [(x * scale, (doc.height - y) * scale) for x, y in pts]
        msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": layer})

    stream = io.StringIO()
    drawing.write(stream)
    return stream.getvalue().encode("utf-8")


def to_pdf(svg: str, size: PhysicalSize) -> bytes:
    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "PDF export requires cairosvg (pip install 'vectorize-engine[emit]')"
        ) from exc
    blob: bytes = cairosvg.svg2pdf(
        bytestring=svg.encode("utf-8"),
        output_width=size.width_mm * 72.0 / MM_PER_INCH,
        output_height=size.height_mm * 72.0 / MM_PER_INCH,
    )
    return blob


def to_png(svg: str, *, width: int) -> bytes:
    from PIL import Image

    from engine.raster import render_svg

    arr = render_svg(svg, width=width)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def to_eps(doc: SvgDoc, size: PhysicalSize) -> bytes:
    """Minimal EPS writer.

    Deliberately hand-written: the obvious alternative is Ghostscript, which
    is AGPL and must not be pulled in without an explicit licensing decision
    (§2, docs/licensing.md). Filled polygons are all the format needs here.
    """
    pt_w = size.width_mm * 72.0 / MM_PER_INCH
    pt_h = size.height_mm * 72.0 / MM_PER_INCH
    sx = pt_w / doc.width if doc.width else 1.0
    sy = pt_h / doc.height if doc.height else 1.0

    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {math.ceil(pt_w)} {math.ceil(pt_h)}",
        "%%Creator: vectorize-engine",
        "%%EndComments",
    ]
    for fill, pts in _polylines(doc, max(0.05, 1.0 / max(sx, 1e-6))):
        r, g, b = (int(fill.lstrip("#")[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        lines.append(f"{r:.4f} {g:.4f} {b:.4f} setrgbcolor")
        x0, y0 = pts[0]
        lines.append(f"newpath {x0 * sx:.3f} {(doc.height - y0) * sy:.3f} moveto")
        for x, y in pts[1:]:
            lines.append(f"{x * sx:.3f} {(doc.height - y) * sy:.3f} lineto")
        lines.append("closepath fill")
    lines.append("showpage")
    lines.append("%%EOF")
    return ("\n".join(lines)).encode("ascii", "replace")


def emit(
    doc: SvgDoc, profile: ImageProfile, options: Options
) -> EmitResult:
    size, warnings = resolve_physical_size(doc, profile, options)
    doc = apply_physical_size(doc, size)
    svg = serialize(doc, decimals=config.COORD_DECIMALS)

    outputs: dict[str, bytes] = {"svg": svg.encode("utf-8")}
    for fmt in options.formats:
        if fmt == "svg":
            continue
        if fmt == "dxf":
            outputs["dxf"] = to_dxf(
                doc, size, tolerance_mm=options.dxf_tolerance, units=options.units
            )
        elif fmt == "pdf":
            outputs["pdf"] = to_pdf(svg, size)
        elif fmt == "eps":
            outputs["eps"] = to_eps(doc, size)
        elif fmt == "png":
            outputs["png"] = to_png(svg, width=int(max(doc.width, 1024)))
        else:
            raise ValueError(f"unknown output format: {fmt}")

    return EmitResult(outputs=outputs, svg=svg, physical_size=size, warnings=warnings)
