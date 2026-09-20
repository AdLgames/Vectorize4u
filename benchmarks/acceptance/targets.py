"""Measurement targets for the §13 cut-correctness acceptance test.

These are not artwork. Every one is drawn so that a specific failure mode
is visible to the naked eye in a cutting app, and so that the expected
number is unambiguous:

- Each target is **full bleed**: the ink touches all four edges of the
  canvas. That matters because the emitted SVG's physical width is the
  width of the *canvas*, not of the artwork inside it. With a margin, "open
  at 100 mm" would mean the shape measures less than 100 mm and the test
  would fail for a reason that isn't a bug.
- Shapes are asymmetric on both axes where a flip would otherwise be
  invisible. A mirrored square looks fine; a mirrored "F" does not.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw

INK = (17, 17, 17, 255)
PAPER = (255, 255, 255, 255)


@dataclass(frozen=True)
class Target:
    name: str
    data: bytes
    width: float
    units: str
    aspect: float
    what_it_catches: str
    expect: str


def _png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def ruler(px_wide: int = 1200, px_high: int = 240) -> Image.Image:
    """A 10-division ruler. Catches scale error *and* non-uniform scaling.

    Total width is one number to check; the tick spacing is a second,
    independent one. A file that is uniformly 4% small fails both the same
    way; a file that is stretched on one axis fails them differently, which
    is what tells the two apart.
    """
    img = Image.new("RGBA", (px_wide, px_high), PAPER)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, px_high - 24, px_wide - 1, px_high - 1], fill=INK)
    for i in range(11):
        x = round(i * (px_wide - 1) / 10)
        tall = i % 5 == 0
        height = px_high - 24 if tall else (px_high - 24) // 2
        w = 10 if tall else 6
        draw.rectangle(
            [max(0, x - w // 2), px_high - 24 - height, min(px_wide - 1, x + w // 2), px_high - 24],
            fill=INK,
        )
    # Full bleed: the outermost ticks are clipped to the canvas edge on
    # purpose, so the ruler's length is exactly the canvas width.
    return img


def letter_f(px: int = 800) -> Image.Image:
    """A full-bleed "F". Catches a mirror or a 180° rotation.

    Asymmetric on both axes: the arms are at the top and extend right of
    the stem. Nothing else in the kit would reveal a flipped Y axis, and a
    flipped DXF cuts a mirrored part that looks perfectly reasonable until
    it is glued to something.
    """
    img = Image.new("RGBA", (px, px), PAPER)
    draw = ImageDraw.Draw(img)
    stem = px // 4
    draw.rectangle([0, 0, stem, px - 1], fill=INK)            # stem, full height
    draw.rectangle([0, 0, px - 1, stem], fill=INK)            # top arm, full width
    draw.rectangle([0, px // 2 - stem // 2, int(px * 0.72), px // 2 + stem // 2], fill=INK)
    return img


def square(px: int = 800) -> Image.Image:
    """A full-bleed square frame. Catches aspect-ratio error.

    Width and height are the same number, so a file that opens 100 × 94 mm
    is obvious without measuring carefully.
    """
    img = Image.new("RGBA", (px, px), PAPER)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, px - 1, px - 1], fill=INK)
    inset = px // 8
    draw.rectangle([inset, inset, px - 1 - inset, px - 1 - inset], fill=PAPER)
    # A notch in one corner so a 90° rotation is also visible.
    draw.rectangle([0, 0, inset * 2, inset // 2], fill=PAPER)
    return img


def fine_detail(px_wide: int = 900, px_high: int = 640) -> Image.Image:
    """Thin strokes and small holes. Catches over-eager cleanup.

    The engine drops slivers and enforces a minimum node spacing for the
    blade's sake (§3.7). Both are good defaults and both can go too far:
    this target says how far, in millimetres, on a real machine.

    The holes are punched through a solid band rather than through the
    strokes, so each one is a genuine enclosed counter — the thing sliver
    removal is most likely to swallow.
    """
    img = Image.new("RGBA", (px_wide, px_high), PAPER)
    draw = ImageDraw.Draw(img)

    # Full-bleed rules top and bottom, so the canvas equals the artwork.
    draw.rectangle([0, 0, px_wide - 1, 36], fill=INK)
    draw.rectangle([0, px_high - 37, px_wide - 1, px_high - 1], fill=INK)

    # Seven strokes, 1 px to 10 px. At 150 mm wide, 1 px is about 0.17 mm.
    for i, weight in enumerate((1, 2, 3, 4, 6, 8, 10)):
        x = 70 + i * 118
        draw.rectangle([x, 70, x + weight, 320], fill=INK)

    # Six holes punched through a solid band, 3 px to 24 px across.
    draw.rectangle([60, 370, px_wide - 61, px_high - 70], fill=INK)
    for i, radius in enumerate((3, 5, 8, 12, 18, 24)):
        cx = 140 + i * 130
        cy = (370 + px_high - 70) // 2
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=PAPER)
    return img


def all_targets() -> list[Target]:
    return [
        Target(
            name="ruler-100mm",
            data=_png(ruler()),
            width=100.0,
            units="mm",
            aspect=0.2,
            what_it_catches="scale error, and stretching on one axis",
            expect="100.0 mm wide, 20.0 mm tall. Ticks every 10.0 mm, tall ticks at 0, 50, 100.",
        ),
        Target(
            name="ruler-4in",
            data=_png(ruler()),
            width=4.0,
            units="in",
            aspect=0.2,
            what_it_catches="the imperial unit path, and mm/inch confusion",
            expect="4.000 in wide, 0.800 in tall. Ticks every 0.400 in.",
        ),
        Target(
            name="square-100mm",
            data=_png(square()),
            width=100.0,
            units="mm",
            aspect=1.0,
            what_it_catches="aspect-ratio error and 90° rotation",
            expect="100.0 x 100.0 mm. The missing notch sits in the TOP-LEFT corner.",
        ),
        Target(
            name="letter-f-80mm",
            data=_png(letter_f()),
            width=80.0,
            units="mm",
            aspect=1.0,
            what_it_catches="mirrored or upside-down import (DXF flips the Y axis)",
            expect="80.0 x 80.0 mm. Reads as a normal F: arms at the TOP, pointing RIGHT.",
        ),
        Target(
            name="fine-detail-150mm",
            data=_png(fine_detail()),
            width=150.0,
            units="mm",
            aspect=640 / 900,
            what_it_catches="strokes and holes lost to sliver removal or node spacing",
            expect=(
                "150.0 x 106.7 mm. Seven strokes (0.17 to 1.7 mm wide) and six round "
                "holes (0.5 to 4.0 mm across) should all be present."
            ),
        ),
    ]
