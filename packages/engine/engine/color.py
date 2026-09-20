"""Colour helpers: sRGB ↔ Lab and ΔE2000.

ΔE2000 is used in three places with one meaning throughout: "are these two
colours the same to a human?" The 2.0 threshold is the usual
just-noticeable-difference boundary for flat fills.
"""

from __future__ import annotations

import numpy as np

_M_RGB2XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_WHITE = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: (..., 3) uint8 or float in [0,255] → Lab float64 (..., 3)."""
    arr = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M_RGB2XYZ.T / _WHITE
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 over broadcastable (..., 3) Lab arrays."""
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_bar**7 / (c_bar**7 + 25.0**7 + 1e-12)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dlp = l2 - l1
    dcp = c2p - c1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, np.where(dhp < -180, dhp + 360, dhp))
    dhp = np.where(c1p * c2p == 0, 0.0, dhp)
    dHp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp / 2.0))

    lp_bar = (l1 + l2) / 2.0
    cp_bar = (c1p + c2p) / 2.0
    hsum = h1p + h2p
    hdiff = np.abs(h1p - h2p)
    hp_bar = np.where(
        c1p * c2p == 0,
        hsum,
        np.where(
            hdiff <= 180,
            hsum / 2.0,
            np.where(hsum < 360, (hsum + 360) / 2.0, (hsum - 360) / 2.0),
        ),
    )

    t = (
        1
        - 0.17 * np.cos(np.radians(hp_bar - 30))
        + 0.24 * np.cos(np.radians(2 * hp_bar))
        + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
        - 0.20 * np.cos(np.radians(4 * hp_bar - 63))
    )
    sl = 1 + (0.015 * (lp_bar - 50) ** 2) / np.sqrt(20 + (lp_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    dtheta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))
    rc = 2 * np.sqrt(cp_bar**7 / (cp_bar**7 + 25.0**7 + 1e-12))
    rt = -rc * np.sin(np.radians(2 * dtheta))

    result: np.ndarray = np.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dHp / sh) ** 2
        + rt * (dcp / sc) * (dHp / sh)
    )
    return result


def rgb_delta_e(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return delta_e2000(srgb_to_lab(a), srgb_to_lab(b))


def to_hex(rgb: tuple[int, int, int] | np.ndarray) -> str:
    r, g, b = (int(round(float(v))) for v in rgb[:3])
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def from_hex(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
