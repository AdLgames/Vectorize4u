"""A minimal SVG document model.

Only what post-processing needs: paths made of `M`/`L`/`C`/`Z` with a fill,
a canvas, and a serializer. A full SVG DOM library would be a large
dependency for a file format we also produce ourselves — both tracers emit
exactly this subset.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

Point = tuple[float, float]

_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_CMD = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])")


@dataclass
class SubPath:
    """One closed or open run. `segments` are cubic Béziers or lines.

    Representation: a start point plus a list of segments, each either
    ("L", end) or ("C", c1, c2, end). Everything a tracer emits maps onto
    this; anything exotic is flattened on parse.
    """

    start: Point
    segments: list[tuple[str, tuple[Point, ...]]] = field(default_factory=list)
    closed: bool = False

    def points(self) -> list[Point]:
        pts = [self.start]
        for _, args in self.segments:
            pts.append(args[-1])
        return pts

    def node_count(self) -> int:
        return 1 + len(self.segments)

    def area(self) -> float:
        """Shoelace area over the anchor polygon. Good enough for slivers."""
        pts = self.points()
        if len(pts) < 3:
            return 0.0
        acc = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            acc += x1 * y2 - x2 * y1
        return abs(acc) / 2.0

    def to_d(self, decimals: int = 2) -> str:
        def f(v: float) -> str:
            s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
            return s if s not in ("", "-0") else "0"

        out = [f"M{f(self.start[0])} {f(self.start[1])}"]
        for kind, args in self.segments:
            if kind == "L":
                out.append(f"L{f(args[0][0])} {f(args[0][1])}")
            else:
                c1, c2, end = args
                out.append(
                    f"C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(end[0])} {f(end[1])}"
                )
        if self.closed:
            out.append("Z")
        return "".join(out)


@dataclass
class Path:
    subpaths: list[SubPath]
    fill: str = "#000000"
    fill_opacity: float | None = None
    fill_rule: str | None = None

    def node_count(self) -> int:
        return sum(sp.node_count() for sp in self.subpaths)

    def area(self) -> float:
        return sum(sp.area() for sp in self.subpaths)

    def bbox(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for sp in self.subpaths:
            for x, y in sp.points():
                xs.append(x)
                ys.append(y)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def to_d(self, decimals: int = 2) -> str:
        return "".join(sp.to_d(decimals) for sp in self.subpaths)


@dataclass
class SvgDoc:
    width: float
    height: float
    paths: list[Path] = field(default_factory=list)
    # Physical size, set at emit time (§3.8). None → unitless, which cutting
    # apps disagree about, so emit() always fills it in.
    phys_width: str | None = None
    phys_height: str | None = None

    def node_count(self) -> int:
        return sum(p.node_count() for p in self.paths)

    def path_count(self) -> int:
        return len(self.paths)


def _tokenize(d: str) -> list[tuple[str, list[float]]]:
    parts = _CMD.split(d)
    out: list[tuple[str, list[float]]] = []
    i = 1
    while i < len(parts):
        cmd = parts[i]
        nums = [float(m.group()) for m in _NUM.finditer(parts[i + 1] if i + 1 < len(parts) else "")]
        out.append((cmd, nums))
        i += 2
    return out


def _flatten_arc(start: Point, end: Point) -> tuple[str, tuple[Point, ...]]:
    # Arcs do not appear in tracer output. If one ever does, a straight line
    # is a visible-but-safe degradation rather than a crash.
    del start
    return ("L", (end,))


def parse_path_d(d: str) -> list[SubPath]:
    subpaths: list[SubPath] = []
    cur: SubPath | None = None
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    prev_c2: Point | None = None

    for cmd, nums in _tokenize(d):
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            for k in range(0, len(nums) - 1, 2):
                x, y = nums[k], nums[k + 1]
                p = (pos[0] + x, pos[1] + y) if rel else (x, y)
                if k == 0:
                    if cur is not None and cur.segments:
                        subpaths.append(cur)
                    cur = SubPath(start=p)
                    start = p
                elif cur is not None:
                    cur.segments.append(("L", (p,)))
                pos = p
            prev_c2 = None
        elif c == "Z":
            if cur is not None:
                cur.closed = True
                subpaths.append(cur)
                cur = None
            pos = start
            prev_c2 = None
        elif cur is None:
            continue
        elif c in ("L", "H", "V"):
            if c == "L":
                pairs = [(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            elif c == "H":
                pairs = [(v, 0.0 if rel else pos[1]) for v in nums]
            else:
                pairs = [(0.0 if rel else pos[0], v) for v in nums]
            for x, y in pairs:
                p = (pos[0] + x, pos[1] + y) if rel else (x, y)
                cur.segments.append(("L", (p,)))
                pos = p
            prev_c2 = None
        elif c == "C":
            for k in range(0, len(nums) - 5, 6):
                pts = []
                for j in range(3):
                    x, y = nums[k + 2 * j], nums[k + 2 * j + 1]
                    pts.append((pos[0] + x, pos[1] + y) if rel else (x, y))
                cur.segments.append(("C", (pts[0], pts[1], pts[2])))
                prev_c2 = pts[1]
                pos = pts[2]
        elif c == "S":
            for k in range(0, len(nums) - 3, 4):
                pts = []
                for j in range(2):
                    x, y = nums[k + 2 * j], nums[k + 2 * j + 1]
                    pts.append((pos[0] + x, pos[1] + y) if rel else (x, y))
                c1 = (2 * pos[0] - prev_c2[0], 2 * pos[1] - prev_c2[1]) if prev_c2 else pos
                cur.segments.append(("C", (c1, pts[0], pts[1])))
                prev_c2 = pts[0]
                pos = pts[1]
        elif c in ("Q", "T"):
            step = 4 if c == "Q" else 2
            for k in range(0, len(nums) - (step - 1), step):
                if c == "Q":
                    qx, qy = nums[k], nums[k + 1]
                    ex, ey = nums[k + 2], nums[k + 3]
                    q = (pos[0] + qx, pos[1] + qy) if rel else (qx, qy)
                    end = (pos[0] + ex, pos[1] + ey) if rel else (ex, ey)
                else:
                    ex, ey = nums[k], nums[k + 1]
                    end = (pos[0] + ex, pos[1] + ey) if rel else (ex, ey)
                    q = pos
                c1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
                c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
                cur.segments.append(("C", (c1, c2, end)))
                pos = end
            prev_c2 = None
        elif c == "A":
            for k in range(0, len(nums) - 6, 7):
                ex, ey = nums[k + 5], nums[k + 6]
                end = (pos[0] + ex, pos[1] + ey) if rel else (ex, ey)
                cur.segments.append(_flatten_arc(pos, end))
                pos = end
            prev_c2 = None

    if cur is not None and cur.segments:
        subpaths.append(cur)
    return subpaths


def _length_unit(value: str | None) -> float | None:
    if not value:
        return None
    m = _NUM.match(value.strip())
    return float(m.group()) if m else None


def parse_svg(svg: str) -> SvgDoc:
    root = ET.fromstring(svg)
    vb = root.get("viewBox")
    if vb:
        nums = [float(v) for v in _NUM.findall(vb)]
        width, height = (nums[2], nums[3]) if len(nums) >= 4 else (0.0, 0.0)
    else:
        width = _length_unit(root.get("width")) or 0.0
        height = _length_unit(root.get("height")) or 0.0

    doc = SvgDoc(width=width, height=height)
    _walk(root, IDENTITY, doc, {})

    if not doc.width or not doc.height:
        boxes = [p.bbox() for p in doc.paths]
        doc.width = max((b[2] for b in boxes), default=1.0)
        doc.height = max((b[3] for b in boxes), default=1.0)
    return doc


Transform = tuple[float, float, float, float]  # sx, sy, tx, ty
IDENTITY: Transform = (1.0, 1.0, 0.0, 0.0)


def _walk(
    el: ET.Element, parent: Transform, doc: SvgDoc, inherited: dict[str, str]
) -> None:
    """Depth-first, accumulating transforms.

    vtracer puts a `translate(...)` on *every* path and potrace puts one
    `translate(...) scale(...)` on a wrapping group. Applying one element's
    transform to every path (or ignoring them) silently mangles the geometry
    — the trace still renders, just in the wrong place, which is a very
    expensive bug to notice late.
    """
    here = _compose(parent, _parse_transform(el.get("transform")))
    style = el.get("style") or ""
    # Presentation attributes inherit. Our own serializer puts `fill` on the
    # colour group, so a parser that ignores inheritance cannot read back
    # what it just wrote.
    attrs = dict(inherited)
    for key in ("fill", "fill-opacity", "fill-rule"):
        value = el.get(key) or _from_style(style, key)
        if value:
            attrs[key] = value

    tag = el.tag.rsplit("}", 1)[-1]
    if tag == "path":
        d = el.get("d")
        if d:
            fill = attrs.get("fill", "#000000")
            if fill != "none":
                subs = parse_path_d(d)
                if here != IDENTITY:
                    subs = [_apply(sp, here) for sp in subs]
                opacity = attrs.get("fill-opacity")
                doc.paths.append(
                    Path(
                        subpaths=subs,
                        fill=_normalise_fill(fill),
                        fill_opacity=float(opacity) if opacity else None,
                        fill_rule=attrs.get("fill-rule"),
                    )
                )
    for child in el:
        _walk(child, here, doc, attrs)


def _parse_transform(value: str | None) -> Transform:
    if not value:
        return IDENTITY
    sx = sy = 1.0
    tx = ty = 0.0
    mt = re.search(r"translate\(([^)]*)\)", value)
    if mt:
        nums = [float(v) for v in _NUM.findall(mt.group(1))]
        tx = nums[0] if nums else 0.0
        ty = nums[1] if len(nums) > 1 else 0.0
    ms = re.search(r"scale\(([^)]*)\)", value)
    if ms:
        nums = [float(v) for v in _NUM.findall(ms.group(1))]
        sx = nums[0] if nums else 1.0
        sy = nums[1] if len(nums) > 1 else sx
    if re.search(r"matrix|rotate|skew", value):
        # Neither tracer emits these. Failing loudly beats emitting geometry
        # that is quietly in the wrong place.
        raise ValueError(f"unsupported SVG transform: {value!r}")
    return (sx, sy, tx, ty)


def _compose(parent: Transform, child: Transform) -> Transform:
    psx, psy, ptx, pty = parent
    csx, csy, ctx, cty = child
    return (psx * csx, psy * csy, ctx * psx + ptx, cty * psy + pty)


def _apply(sp: SubPath, tf: tuple[float, float, float, float]) -> SubPath:
    sx, sy, tx, ty = tf

    def m(p: Point) -> Point:
        return (p[0] * sx + tx, p[1] * sy + ty)

    return SubPath(
        start=m(sp.start),
        segments=[(k, tuple(m(p) for p in args)) for k, args in sp.segments],
        closed=sp.closed,
    )


def _from_style(style: str, key: str) -> str | None:
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() == key:
                return v.strip()
    return None


def _normalise_fill(fill: str) -> str:
    f = fill.strip()
    if f.startswith("rgb"):
        nums = [int(round(float(v))) for v in _NUM.findall(f)[:3]]
        if len(nums) == 3:
            return "#{:02x}{:02x}{:02x}".format(*nums)
    if f.startswith("#") and len(f) == 4:
        return "#" + "".join(c * 2 for c in f[1:])
    return f.lower()


def serialize(doc: SvgDoc, *, decimals: int = 2, group_by_color: bool = True) -> str:
    """Emit SVG. Physical width/height plus a viewBox, never unitless (§3.8).

    Colour grouping never reorders paths. Tracer output is `stacked`: later
    paths cover earlier ones, so collecting every path of one colour into a
    single group changes what covers what and silently corrupts the artwork.
    Consecutive runs of the same fill are grouped instead, which gives
    Illustrator/Inkscape users the named layers of §3.7 step 5 without
    touching the stacking order.
    """
    w = doc.phys_width or f"{doc.width:g}"
    h = doc.phys_height or f"{doc.height:g}"
    head = (
        f'<svg xmlns="{SVG_NS}" version="1.1" width="{w}" height="{h}" '
        f'viewBox="0 0 {doc.width:g} {doc.height:g}">'
    )
    if not group_by_color:
        return head + "".join(_path_el(p, decimals) for p in doc.paths) + "</svg>"

    body: list[str] = []
    seen: dict[str, int] = {}
    i = 0
    while i < len(doc.paths):
        fill = doc.paths[i].fill
        j = i
        while j < len(doc.paths) and doc.paths[j].fill == fill:
            j += 1
        slug = fill.lstrip("#")
        seen[slug] = seen.get(slug, 0) + 1
        suffix = "" if seen[slug] == 1 else f"-{seen[slug]}"
        body.append(f'<g id="color-{slug}{suffix}" fill="{fill}">')
        body.extend(_path_el(p, decimals, omit_fill=True) for p in doc.paths[i:j])
        body.append("</g>")
        i = j
    return head + "".join(body) + "</svg>"


def _path_el(p: Path, decimals: int, omit_fill: bool = False) -> str:
    attrs = [f'd="{p.to_d(decimals)}"']
    if not omit_fill:
        attrs.append(f'fill="{p.fill}"')
    if p.fill_opacity is not None and not math.isclose(p.fill_opacity, 1.0):
        attrs.append(f'fill-opacity="{p.fill_opacity:g}"')
    if p.fill_rule:
        attrs.append(f'fill-rule="{p.fill_rule}"')
    return "<path " + " ".join(attrs) + "/>"
