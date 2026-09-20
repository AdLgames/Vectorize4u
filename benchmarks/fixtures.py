"""Deterministic synthetic corpus.

These cover every fixture §3.9 names as *required*, so the behaviours that
must not regress (premultiplied alpha fixed, dark straight alpha left alone,
EXIF upright, CMYK colour-correct) are testable in CI on any machine.

They are **not** a substitute for the real corpus. §3.9 calls for 60–100
hand-labelled real images; drop them into `benchmarks/corpus/real/` with a
`labels.json` and `run.py` picks them up. The `k_class` values in
`engine/calibration.json` stay provisional until that exists — see
docs/runbook.md.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SEED = 1729
CORPUS = Path(__file__).parent / "corpus"


@dataclass(frozen=True)
class Fixture:
    name: str
    data: bytes
    label: str
    note: str = ""


def _png(img: Image.Image, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", **kw)
    return buf.getvalue()


def _jpeg(img: Image.Image, quality: int = 30, **kw) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, **kw)
    return buf.getvalue()


def _flat_logo(size: tuple[int, int] = (800, 600), bg=(255, 255, 255, 255)) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, bg)
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.07, h * 0.1, w * 0.5, h * 0.67], fill=(220, 40, 40, 255))
    d.rectangle([w * 0.37, h * 0.33, w * 0.87, h * 0.53], fill=(30, 60, 200, 255))
    d.polygon(
        [(w * 0.62, h * 0.7), (w * 0.87, h * 0.93), (w * 0.47, h * 0.93)],
        fill=(20, 150, 90, 255),
    )
    d.ellipse([w * 0.2, h * 0.28, w * 0.3, h * 0.4], fill=(255, 255, 255, 255))
    return img


def _line_art(size: tuple[int, int] = (700, 700)) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(6):
        inset = 30 + i * 45
        d.ellipse([inset, inset, w - inset, h - inset], outline=(0, 0, 0, 255), width=5)
    d.line([40, h // 2, w - 40, h // 2], fill=(0, 0, 0, 255), width=5)
    d.line([w // 2, 40, w // 2, h - 40], fill=(0, 0, 0, 255), width=5)
    return img


def _gradient_logo(size: tuple[int, int] = (700, 500)) -> Image.Image:
    w, h = size
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    xs = np.linspace(0, 1, w)[None, :]
    ys = np.linspace(0, 1, h)[:, None]
    ramp = (xs * 0.7 + ys * 0.3)
    arr[:, :, 0] = (40 + ramp * 200).astype(np.uint8)
    arr[:, :, 1] = (90 + (1 - ramp) * 120).astype(np.uint8)
    arr[:, :, 2] = (200 - ramp * 150).astype(np.uint8)
    arr[:, :, 3] = 255
    img = Image.fromarray(arr, "RGBA")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([w * 0.1, h * 0.1, w * 0.9, h * 0.9], fill=255)
    out = Image.new("RGBA", size, (255, 255, 255, 255))
    out.paste(img, (0, 0), mask)
    return out


def _photo_like(size: tuple[int, int] = (640, 480)) -> Image.Image:
    rng = np.random.default_rng(SEED)
    h, w = size[1], size[0]
    base = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8)
    img = Image.fromarray(base, "RGB").resize(size, Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    arr = np.asarray(img).astype(np.int16)
    arr += rng.integers(-22, 22, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def _screenshot(size: tuple[int, int] = (900, 600)) -> Image.Image:
    """A UI screenshot: flat fills plus a lot of real glyphs.

    Drawn at half size with Pillow's bundled bitmap font and scaled up with
    NEAREST, so the glyphs are large enough for MSER without depending on a
    system font — a fixture that renders differently on the CI box would
    silently invalidate every benchmark baseline.
    """
    w, h = size
    small = Image.new("RGBA", (w // 2, h // 2), (245, 246, 248, 255))
    d = ImageDraw.Draw(small)
    d.rectangle([0, 0, w // 2, 24], fill=(32, 38, 52, 255))
    words = ["Dashboard", "Projects", "Settings", "Invoices", "Customers", "Reports"]
    for row in range(14):
        y = 35 + row * 18
        d.text((12, y), f"{words[row % len(words)]} {row:02d} item", fill=(60, 66, 80, 255))
        d.text((260, y), f"{row * 37 + 11} units", fill=(120, 126, 140, 255))
    d.rectangle([12, h // 2 - 30, 110, h // 2 - 10], fill=(30, 110, 220, 255))
    return small.resize(size, Image.NEAREST)


def _dark_straight_alpha(size: tuple[int, int] = (600, 600)) -> Image.Image:
    """A dark logo with *straight* alpha and a soft edge.

    This is the fixture the naive premultiplied test gets wrong: every
    semi-transparent pixel satisfies `max(r,g,b) <= a`, so a naive detector
    divides it by alpha and produces bright halos. It must come out
    untouched.
    """
    w, h = size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([w * 0.15, h * 0.15, w * 0.85, h * 0.85], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    rgb = Image.new("RGB", size, (10, 12, 16))
    out = Image.merge("RGBA", (*rgb.split(), mask))
    return out


def _premultiplied(size: tuple[int, int] = (600, 600)) -> Image.Image:
    """A bright logo stored premultiplied. Must be detected and divided."""
    w, h = size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse([w * 0.15, h * 0.15, w * 0.85, h * 0.85], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    a = np.asarray(mask, dtype=np.float32) / 255.0
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    rgb[:, :, 0] = 240.0
    rgb[:, :, 1] = 200.0
    rgb[:, :, 2] = 60.0
    premul = (rgb * a[:, :, None]).astype(np.uint8)
    out = np.dstack([premul, (a * 255).astype(np.uint8)])
    return Image.fromarray(out, "RGBA")


def _binary_alpha(size: tuple[int, int] = (600, 400)) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 360, 360], fill=(200, 30, 90, 255))
    d.rectangle([300, 120, 560, 260], fill=(20, 40, 160, 255))
    return img


def _exif_rotated() -> bytes:
    """A portrait image stored landscape with orientation=6 (rotate 90° CW).

    Must come out upright. Stripping EXIF before transposing — the easy
    mistake — leaves every phone photo on its side.
    """
    img = _flat_logo((600, 400))
    exif = Image.Exif()
    exif[274] = 6
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92, exif=exif)
    return buf.getvalue()


def _cmyk_jpeg() -> bytes:
    """Print shops send CMYK JPEGs; untagged conversion shifts brand colours."""
    img = _flat_logo((640, 480)).convert("RGB").convert("CMYK")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _sketch(size: tuple[int, int] = (700, 700)) -> Image.Image:
    rng = np.random.default_rng(SEED + 1)
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)
    for i in range(140):
        x0 = rng.integers(40, size[0] - 40)
        y0 = rng.integers(40, size[1] - 40)
        ang = rng.uniform(0, math.pi)
        length = rng.integers(20, 90)
        d.line(
            [x0, y0, x0 + length * math.cos(ang), y0 + length * math.sin(ang)],
            fill=int(rng.integers(20, 120)),
            width=int(rng.integers(1, 4)),
        )
    arr = np.asarray(img).astype(np.int16) + rng.integers(-18, 18, (size[1], size[0]))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L").convert("RGBA")


def all_fixtures() -> list[Fixture]:
    return [
        Fixture("logo_flat", _png(_flat_logo()), "LOGO_FLAT"),
        Fixture("logo_flat_small", _png(_flat_logo((320, 240))), "LOGO_FLAT",
                "sub-600px: must be upscaled for tracing, not for scoring"),
        Fixture("logo_flat_jpeg_artifacts", _jpeg(_flat_logo(), quality=18), "LOGO_FLAT",
                "heavy JPEG artifacts: the reference must be cleaned before scoring"),
        Fixture("logo_gradient", _png(_gradient_logo()), "LOGO_GRADIENT",
                "must warn gradients_banded"),
        Fixture("line_art", _png(_line_art()), "LINE_ART"),
        Fixture("sketch", _png(_sketch()), "SKETCH"),
        Fixture("screenshot", _png(_screenshot()), "SCREENSHOT"),
        Fixture("photo", _jpeg(_photo_like(), quality=80), "PHOTO",
                "expected to score poorly; must warn photo_input"),
        Fixture("alpha_binary", _png(_binary_alpha()), "LOGO_FLAT",
                "transparency must survive"),
        Fixture("alpha_premultiplied", _png(_premultiplied()), "LOGO_FLAT",
                "must be detected and divided: no dark halos"),
        Fixture("alpha_dark_straight", _png(_dark_straight_alpha()), "LOGO_FLAT",
                "must be LEFT ALONE: dividing it creates bright halos"),
        Fixture("cmyk_jpeg", _cmyk_jpeg(), "LOGO_FLAT", "must come out colour-correct"),
        Fixture("exif_rotated", _exif_rotated(), "LOGO_FLAT", "must come out upright"),
    ]


def by_name(name: str) -> Fixture:
    for f in all_fixtures():
        if f.name == name:
            return f
    raise KeyError(name)


def generate(target: Path = CORPUS) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    labels: dict[str, dict[str, str]] = {}
    written = []
    for fx in all_fixtures():
        ext = "jpg" if fx.data[:3] == b"\xff\xd8\xff" else "png"
        path = target / f"{fx.name}.{ext}"
        path.write_bytes(fx.data)
        labels[path.name] = {"label": fx.label, "note": fx.note, "source": "synthetic"}
        written.append(path)
    (target / "labels.json").write_text(json.dumps(labels, indent=2, sort_keys=True) + "\n")
    return written


if __name__ == "__main__":
    for p in generate():
        print(p)
