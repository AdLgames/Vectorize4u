"""Trace shaded artwork as gradients instead of as a stack of bands.

§0 called banding a stated non-goal: vtracer steps a gradient into flat
colours and the pipeline's job was to detect it and say so. The measured
result of that policy, on a real gradient logo: 460 stacked shapes, 4891
nodes, 178 KB, and 619 machine defects — 456 of them contours that cross
themselves. Nothing downstream rescues it. Smoothing tears the shared
boundaries apart, and a cutter is handed hundreds of overlapping bands
where the artwork has three shapes.

The first attempt folded the *bands* into one gradient: take the
bottom-most band as the outline, fit a gradient to where the others sit.
Rendered, it destroyed the logo — filled the whole silhouette with one
smooth ramp and lost every internal shape. The premise was wrong. Shaded
artwork is built from the stack, not from one outline, and the stack's
structure is spatial, not chromatic: clustering the band colours made it
worse, because the two ramps in that logo overlap in colour space and are
separated only by where they are.

So the regions are found in the raster, where the structure is. Inside a
shaded region colour changes gently and at its edge it jumps, which the
magnitude of the Lab gradient separates directly. Each region becomes one
path filled with one gradient fitted to its own pixels.

The contours come off a pixel mask, so they arrive stair-stepped — and
are handed to §3.7 exactly like any other trace, where smoothing and
sliver removal clean them up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from engine import config
from engine.geom import Point
from engine.svgdoc import Gradient, GradientStop, Path, SubPath, SvgDoc


@dataclass(frozen=True)
class Region:
    label: int
    area: int


def _region_labels(rgba: np.ndarray) -> tuple[np.ndarray, list[Region]]:
    """Split the opaque artwork into areas of gently varying colour.

    Seeds are the pixels where the Lab gradient is small — the inside of a
    shaded area. The boundaries between regions are left unassigned and
    handed to the nearest seed afterwards, so the regions tile the artwork
    with no gaps for the background to show through.
    """
    rgb = rgba[:, :, :3]
    opaque = rgba[:, :, 3] > 128 if rgba.shape[2] == 4 else np.ones(rgb.shape[:2], bool)
    if not opaque.any():
        return np.zeros(rgb.shape[:2], np.int32), []

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.sqrt((gx**2).sum(axis=2) + (gy**2).sum(axis=2))

    seeds = ((magnitude < config.GRADIENT_EDGE_THRESHOLD) & opaque).astype(np.uint8)
    count, labels = cv2.connectedComponents(seeds, connectivity=4)
    if count <= 1:
        return np.zeros(rgb.shape[:2], np.int32), []

    sizes = np.bincount(labels.ravel())
    floor = config.GRADIENT_MIN_REGION_FRACTION * int(opaque.sum())
    kept = [i for i in range(1, count) if sizes[i] >= floor]
    if not kept:
        return np.zeros(rgb.shape[:2], np.int32), []

    markers = np.zeros(labels.shape, np.int32)
    for new, old in enumerate(kept, start=1):
        markers[labels == old] = new

    # Hand every unassigned opaque pixel to the nearest seeded one.
    _, nearest = cv2.distanceTransformWithLabels(
        (markers == 0).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL
    )
    flat = markers.ravel()
    seeded = np.nonzero(flat)[0]
    lut = np.zeros(int(nearest.max()) + 1, np.int32)
    lut[nearest.ravel()[seeded]] = flat[seeded]
    filled = np.where(markers > 0, markers, lut[nearest])
    filled[~opaque] = 0

    final = np.bincount(filled.ravel(), minlength=len(kept) + 1)
    return filled, [Region(i, int(final[i])) for i in range(1, len(kept) + 1) if final[i] > 0]


def _subpaths(mask: np.ndarray, min_area: float) -> list[SubPath]:
    """Contours of a region, as polylines. §3.7 turns them into curves."""
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out: list[SubPath] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        points = cv2.approxPolyDP(contour, 1.0, True).reshape(-1, 2)
        if len(points) < 3:
            continue
        anchors: list[Point] = [(float(x), float(y)) for x, y in points]
        out.append(
            SubPath(
                start=anchors[0],
                segments=[("L", (p,)) for p in anchors[1:]],
                closed=True,
            )
        )
    return out


def _stops_along(
    rgb: np.ndarray, ys: np.ndarray, xs: np.ndarray, projection: np.ndarray
) -> list[GradientStop]:
    """Mean colour of each slice along the axis — measured, never invented."""
    lo, hi = float(projection.min()), float(projection.max())
    if hi - lo <= 1e-6:
        return []
    slices = config.GRADIENT_STOPS
    stops: list[GradientStop] = []
    for i in range(slices):
        a0 = lo + (hi - lo) * i / slices
        a1 = lo + (hi - lo) * (i + 1) / slices
        selected = (projection >= a0) & (projection <= a1)
        if int(selected.sum()) < 5:
            continue
        mean = rgb[ys[selected], xs[selected]].mean(axis=0)
        r, g, b = (int(round(float(c))) for c in mean)
        stops.append(GradientStop(offset=i / (slices - 1), color=f"#{r:02x}{g:02x}{b:02x}"))
    if len(stops) < 2:
        return []
    stops[-1] = GradientStop(offset=1.0, color=stops[-1].color)
    return stops


def _colour_position(lab: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray | None:
    """Where each pixel sits along the region's own colour ramp, 0..1."""
    pixels = lab[ys, xs]
    centred = pixels - pixels.mean(axis=0)
    covariance = np.cov(centred, rowvar=False)
    if not np.isfinite(covariance).all():
        return None
    values, vectors = np.linalg.eigh(covariance)
    t = centred @ vectors[:, int(np.argmax(values))]
    span = float(t.max() - t.min())
    if span <= 1e-6:
        return None
    return (t - t.min()) / span


def _fit_linear(
    rgb: np.ndarray, ys: np.ndarray, xs: np.ndarray, t: np.ndarray, gid: str
) -> tuple[Gradient, float] | None:
    design = np.column_stack([xs, ys, np.ones(len(xs))]).astype(np.float64)
    solution, *_ = np.linalg.lstsq(design, t, rcond=None)
    a, b = float(solution[0]), float(solution[1])
    norm = math.hypot(a, b)
    if norm <= 1e-12:
        return None
    residual = float(np.sqrt(np.mean((t - design @ solution) ** 2)))

    direction = np.array([a / norm, b / norm])
    projection = np.column_stack([xs, ys]) @ direction
    stops = _stops_along(rgb, ys, xs, projection)
    if not stops:
        return None
    start = direction * float(projection.min())
    end = direction * float(projection.max())
    return (
        Gradient(
            id=gid,
            kind="linear",
            stops=stops,
            x1=float(start[0]),
            y1=float(start[1]),
            x2=float(end[0]),
            y2=float(end[1]),
        ),
        residual,
    )


def _fit(
    rgb: np.ndarray, lab: np.ndarray, ys: np.ndarray, xs: np.ndarray, gradient_id: str
) -> Gradient | None:
    """Fit the shading of one region.

    Linear only, which is a measured choice rather than a simplification.
    A radial model was implemented and tried — shading on anything curved
    really is radial — and it was selected for every region on the test
    logo and made the result *worse*: fidelity 0.751 against the linear
    fit's 0.816. Its four coefficients fit the colour positions more
    closely than the linear three, so it always won a comparison by
    residual, while rendering less like the artwork. Residual on the fit
    does not predict rendered quality, and picking a model by it selects
    for overfitting. Choosing by rendered fidelity instead would mean a
    render per region per model, which is not affordable here.
    """
    t = _colour_position(lab, ys, xs)
    if t is None:
        return None
    fitted = _fit_linear(rgb, ys, xs, t, gradient_id)
    return fitted[0] if fitted else None


def trace(rgba: np.ndarray) -> SvgDoc | None:
    """Trace shaded artwork as gradient-filled regions.

    Returns None when the image has no such structure to find, which is
    the honest answer for flat artwork and for a photograph — this is not
    a general tracer and must never pretend to be one.
    """
    height, width = rgba.shape[:2]
    labels, regions = _region_labels(rgba)
    if len(regions) < config.GRADIENT_MIN_REGIONS:
        return None

    rgb = rgba[:, :, :3]
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    min_area = config.SLIVER_AREA_FRACTION * width * height

    built: list[tuple[int, Path]] = []
    gradients: list[Gradient] = []
    for region in regions:
        mask = (labels == region.label).astype(np.uint8)
        subpaths = _subpaths(mask, min_area)
        if not subpaths:
            continue
        ys, xs = np.nonzero(mask)
        gradient = _fit(rgb, lab, ys, xs, f"grad-{region.label}")
        if gradient is None:
            continue
        gradients.append(gradient)
        built.append(
            (
                region.area,
                Path(subpaths=subpaths, fill=f"url(#{gradient.id})", fill_rule="evenodd"),
            )
        )

    if len(built) < config.GRADIENT_MIN_REGIONS:
        return None

    # Largest first: the regions tile the artwork, but a stray pixel of
    # overlap should be resolved in favour of the smaller, more specific
    # shape — which is the one drawn last.
    built.sort(key=lambda item: -item[0])
    return SvgDoc(
        width=float(width),
        height=float(height),
        paths=[path for _, path in built],
        gradients=gradients,
    )


__all__ = ["trace"]
