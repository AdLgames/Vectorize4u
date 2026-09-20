"""§3.1 Ingest: bytes in, a trustworthy sRGB RGBA array out.

Order matters and is not negotiable:
  magic bytes → size guards → EXIF transpose → strip EXIF → ICC/CMYK → sRGB
  → RGBA → un-premultiply.

Stripping EXIF before transposing rotates every phone photo. Tracing a
premultiplied image produces dark halos on every soft edge.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageCms, ImageOps

from engine import config
from engine.errors import ImageTooLarge, UnsupportedFormat
from engine.types import AlphaMode, Warning_

Image.MAX_IMAGE_PIXELS = config.MAX_PIXELS

try:  # optional: HEIC comes from iPhones, which POD sellers use constantly
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - depends on libheif being present
    HEIF_AVAILABLE = False


# Magic bytes. Never trust the extension or the Content-Type header: both are
# attacker-controlled, and a mislabelled file is the cheapest way to reach a
# decoder you did not mean to expose.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
)

SUPPORTED = {"PNG", "JPEG", "GIF", "BMP", "TIFF", "WEBP", "HEIC"}


def sniff_format(data: bytes) -> str:
    """Return a format name from the leading bytes, or raise UnsupportedFormat."""
    for magic, name in _MAGIC:
        if data.startswith(magic):
            return name
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return "HEIC"
        if brand in (b"avif", b"avis"):
            return "AVIF"
    raise UnsupportedFormat(f"unrecognised image header: {data[:12]!r}")


@dataclass
class IngestResult:
    """RGBA uint8 array in sRGB, plus what we learned on the way in."""

    rgba: np.ndarray
    source_format: str
    source_dpi: float | None
    source_dpi_trusted: bool
    alpha_was_premultiplied: bool
    warnings: list[str]


def _dpi_from(img: Image.Image) -> tuple[float | None, bool]:
    """Metadata DPI is untrusted by default: 72 and 96 are writer defaults.

    A 400 px logo has no meaningful DPI. Deriving real-world scale from it
    produces confidently wrong sizes (§3.8).
    """
    raw = img.info.get("dpi")
    if not raw:
        return None, False
    try:
        dpi = float(raw[0])
    except (TypeError, ValueError, IndexError):
        return None, False
    if dpi <= 0:
        return None, False
    trusted = dpi not in config.UNTRUSTED_DPI
    return dpi, trusted


def _to_srgb(img: Image.Image, warnings: list[str]) -> Image.Image:
    """Colour-manage to sRGB. Print shops send CMYK; untagged conversion shifts brand colours."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            target = "RGBA" if (img.mode in ("RGBA", "LA") or "transparency" in img.info) else "RGB"
            if img.mode in ("CMYK", "RGB", "RGBA", "LA", "L"):
                img = ImageCms.profileToProfile(img, src, dst, outputMode=target) or img
                if img.mode == "CMYK":  # pragma: no cover - defensive
                    img = img.convert("RGB")
                return img
        except Exception:
            # A broken embedded profile must not fail the job; fall through to
            # the naive conversion and say so.
            warnings.append(Warning_.CMYK_CONVERTED.value)
    if img.mode == "CMYK":
        warnings.append(Warning_.CMYK_CONVERTED.value)
        return img.convert("RGB")
    return img


def _unpremultiply(rgba: np.ndarray) -> tuple[np.ndarray, bool]:
    """Detect and undo premultiplied alpha (§3.1).

    The naive test ("no channel exceeds alpha") is necessary but not
    sufficient: a dark logo with straight alpha passes it too, and dividing
    that image creates *bright* halos. So we test both hypotheses against the
    image's own opaque neighbourhood and require a clear margin.
    """
    alpha = rgba[:, :, 3].astype(np.int16)
    rgb = rgba[:, :, :3].astype(np.int16)
    semi = (alpha > 0) & (alpha < 255)
    n_semi = int(semi.sum())
    if n_semi < 500:
        return rgba, False  # nothing to fix

    if bool((rgb[semi].max(axis=1) > alpha[semi]).any()):
        return rgba, False  # some channel exceeds alpha → definitely straight

    opaque = alpha >= 255
    if not opaque.any():
        return rgba, False

    import cv2

    # Nearest fully-opaque pixel for every pixel, via a distance transform on
    # the complement: `labels` indexes the nearest zero (i.e. opaque) pixel.
    mask = (~opaque).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(
        mask, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL
    )
    oy, ox = np.nonzero(opaque)
    # OpenCV does not document the label numbering order, so build the
    # label → coordinate lookup from the opaque pixels themselves.
    lut_y = np.zeros(int(labels.max()) + 1, dtype=np.int64)
    lut_x = np.zeros_like(lut_y)
    op_labels = labels[oy, ox].astype(np.int64)
    lut_y[op_labels] = oy
    lut_x[op_labels] = ox

    rng = np.random.default_rng(config.SEED)
    ys, xs = np.nonzero(semi)
    if ys.size > 4000:
        pick = rng.choice(ys.size, 4000, replace=False)
        ys, xs = ys[pick], xs[pick]

    lab = np.clip(labels[ys, xs].astype(np.int64), 0, lut_y.size - 1)
    neighbour = rgba[lut_y[lab], lut_x[lab], :3].astype(np.float32)

    a = alpha[ys, xs].astype(np.float32)[:, None] / 255.0
    as_is = rgb[ys, xs].astype(np.float32)
    divided = np.clip(as_is / np.maximum(a, 1e-3), 0, 255)

    d_straight = float(np.mean(np.linalg.norm(as_is - neighbour, axis=1)))
    d_premul = float(np.mean(np.linalg.norm(divided - neighbour, axis=1)))

    # Require a clear margin: ties and near-ties are treated as straight,
    # because wrongly dividing a straight image is the more visible failure.
    if d_premul < d_straight * 0.8:
        out = rgba.copy()
        a_full = rgba[:, :, 3:4].astype(np.float32) / 255.0
        fixed = np.clip(rgba[:, :, :3].astype(np.float32) / np.maximum(a_full, 1e-3), 0, 255)
        sel = (rgba[:, :, 3] > 0) & (rgba[:, :, 3] < 255)
        out[:, :, :3][sel] = fixed[sel].astype(np.uint8)
        return out, True
    return rgba, False


def ingest(
    data: bytes,
    *,
    alpha_mode: AlphaMode = "auto",
    max_bytes: int | None = None,
    max_dimension: int | None = None,
) -> IngestResult:
    max_bytes = max_bytes or config.MAX_BYTES
    max_dimension = max_dimension or config.MAX_DIMENSION
    warnings: list[str] = []

    if len(data) > max_bytes:
        raise ImageTooLarge(f"{len(data)} bytes exceeds the {max_bytes} byte limit")

    fmt = sniff_format(data)
    if fmt not in SUPPORTED:
        raise UnsupportedFormat(f"{fmt} is not supported")
    if fmt == "HEIC" and not HEIF_AVAILABLE:
        raise UnsupportedFormat("HEIC support requires pillow-heif")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise ImageTooLarge(str(exc)) from exc
    except UnsupportedFormat:
        raise
    except Exception as exc:
        raise UnsupportedFormat(f"could not decode {fmt}: {exc}") from exc

    if max(img.size) > max_dimension:
        raise ImageTooLarge(f"{img.size} exceeds {max_dimension}px on a side")

    dpi, dpi_trusted = _dpi_from(img)

    # EXIF orientation first, then strip. The reverse rotates every phone photo.
    exif = img.getexif()
    orientation = exif.get(274) if exif else None
    img = ImageOps.exif_transpose(img) or img
    if orientation not in (None, 1):
        warnings.append(Warning_.EXIF_ROTATED.value)

    img = _to_srgb(img, warnings)

    if img.mode == "I;16" or img.mode == "I":
        img = img.point(lambda v: v * (1 / 256)).convert("L")
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if img.mode in ("LA", "PA") else "RGB")
    if img.mode == "RGB":
        img = img.convert("RGBA")

    rgba = np.asarray(img, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:  # pragma: no cover - defensive
        raise UnsupportedFormat("expected RGBA after conversion")
    rgba = np.ascontiguousarray(rgba)

    premultiplied = False
    if alpha_mode == "premultiplied":
        rgba, premultiplied = _force_unpremultiply(rgba), True
    elif alpha_mode == "auto":
        rgba, premultiplied = _unpremultiply(rgba)
    if premultiplied:
        warnings.append(Warning_.ALPHA_PREMULTIPLIED_FIXED.value)

    return IngestResult(
        rgba=rgba,
        source_format=fmt,
        source_dpi=dpi,
        source_dpi_trusted=dpi_trusted,
        alpha_was_premultiplied=premultiplied,
        warnings=warnings,
    )


def _force_unpremultiply(rgba: np.ndarray) -> np.ndarray:
    out = rgba.copy()
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    fixed = np.clip(rgba[:, :, :3].astype(np.float32) / np.maximum(a, 1e-3), 0, 255)
    sel = rgba[:, :, 3] > 0
    out[:, :, :3][sel] = fixed[sel].astype(np.uint8)
    return out
