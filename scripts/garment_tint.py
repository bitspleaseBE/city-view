"""Recolour garments on a texture while keeping the cloth's shading (numpy only, so it runs
both inside Blender and in plain Python for previews)."""
from __future__ import annotations

import numpy as np


def _hsv(rgb: np.ndarray):
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    d = mx - mn
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, ((g - b) / dd) % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) * 60.0
    return np.where(d > 1e-6, h, 0.0), s, mx


def tint_mask(rgb: np.ndarray, t: dict) -> np.ndarray:
    h, s, v = _hsv(rgb)
    lo, hi = t["hue"]
    hm = (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
    m = hm & (s >= t["sat"][0]) & (s <= t["sat"][1]) & (v >= t["val"][0]) & (v <= t["val"][1])
    H, W = rgb.shape[:2]

    def box(r):
        u0, v0, u1, v1 = r
        b = np.zeros((H, W), bool)
        b[int(v0 * H) : int(v1 * H), int(u0 * W) : int(u1 * W)] = True
        return b

    if t.get("uv"):
        m &= box(t["uv"])
    for r in t.get("avoid") or ():
        m &= ~box(r)
    return m


def apply_tints(rgb: np.ndarray, tints: list[dict]) -> np.ndarray:
    """rgb: HxWx3 float in 0..1, row 0 = image top. Returns a recoloured copy."""
    out = rgb.copy()
    for t in tints:
        m = tint_mask(out, t)
        if not m.any():
            continue
        lum = out[m] @ np.array([0.299, 0.587, 0.114])
        rel = np.clip(lum / max(float(np.median(lum)), 1e-3), 0.3, 1.3)
        rel = 1 + (rel - 1) * t.get("detail", 1.0)
        to = np.asarray(t["to"], float) / 255.0
        new = np.clip(to[None, :] * rel[:, None], 0, 1)
        k = t.get("keep", 0.0)
        out[m] = new * (1 - k) + out[m] * k
    return out
