"""Render the procedural surface kit (needs Pillow + numpy): ``python -m cityview.surface_textures``.

Writes seamless 256 px tiles (roof slate / clay pantiles / zinc / flat bitumen,
pavement slabs, asphalt, park grass, granite kerb, courtyard gravel) to
assets/surfaces/. Outputs are committed; CI (Blender only) never re-renders them.
All patterns are periodic, so they tile without seams.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cityview import surface_kit as kit
from cityview.paths import ASSETS

TEXTURES_DIR = ASSETS / kit.TEXTURES_DIRNAME
SIZE = 256


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - dev tool message
        raise SystemExit("numpy + Pillow are required: pip install -e .[textures]") from exc
    return np


def noise(seed: int, cells: int, size: int = SIZE):
    """Periodic value noise in [0, 1]: random lattice, cosine-interpolated, wraps at the edges."""
    np = _np()
    rng = np.random.default_rng(seed)
    grid = rng.random((cells, cells))
    t = np.arange(size) * cells / size
    i0 = np.floor(t).astype(int) % cells
    i1 = (i0 + 1) % cells
    f = t - np.floor(t)
    f = (1 - np.cos(f * np.pi)) * 0.5
    rows = grid[i0][:, :] * (1 - f)[:, None] + grid[i1][:, :] * f[:, None]  # (size, cells)
    out = rows[:, i0] * (1 - f)[None, :] + rows[:, i1] * f[None, :]
    return out


def fbm(seed: int, base_cells: int = 4, octaves: int = 4, size: int = SIZE):
    np = _np()
    total = np.zeros((size, size))
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        total += amp * noise(seed + o * 101, base_cells * (2**o), size)
        norm += amp
        amp *= 0.5
    return total / norm


def speckle(seed: int, density: float, size: int = SIZE):
    """Sparse random 1-px specks in [0, 1] (periodic by construction)."""
    np = _np()
    rng = np.random.default_rng(seed)
    return (rng.random((size, size)) < density) * rng.random((size, size))


def grain(seed: int, size: int = SIZE):
    np = _np()
    return np.random.default_rng(seed).random((size, size))


def _rgb(base, field=None):
    np = _np()
    arr = np.ones((SIZE, SIZE, 3)) * np.array(base)[None, None, :]
    if field is not None:
        arr = arr * field[..., None]
    return arr


def _tint(arr, color, mask, amount=1.0):
    np = _np()
    c = np.array(color)[None, None, :]
    m = (mask * amount)[..., None]
    return arr * (1 - m) + c * m


def roof_slate():
    np = _np()
    rows, cols = 16, 8  # 16 courses per tile, 8 slates across
    rh, cw = SIZE // rows, SIZE // cols
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    row = y // rh
    xo = (x + (row % 2) * (cw // 2)) % SIZE
    col = xo // cw
    rng = np.random.default_rng(11)
    tone = rng.uniform(0.82, 1.18, (rows, cols))[row, col]
    hue = rng.uniform(-0.03, 0.03, (rows, cols))[row, col]
    # Each course: shadow where the course above overlaps, bright lit lower lip.
    fy = (y % rh) / rh
    lip = 0.78 + 0.34 * np.sin(np.clip(fy, 0, 1) * np.pi * 0.5) - 0.28 * (fy > 0.88)
    fx = (xo % cw) / cw
    joint = 1.0 - 0.45 * ((fx < 0.045) | (fx > 0.955))
    field = tone * lip * joint * (0.88 + 0.24 * fbm(3, 3, 3))
    arr = _rgb((0.285, 0.30, 0.34), field)
    arr[..., 0] += hue * 0.5
    arr[..., 2] += hue
    arr = _tint(arr, (0.30, 0.38, 0.22), np.clip(fbm(21, 5, 3) - 0.62, 0, 1) * 2.2, 0.55)  # moss
    return arr


def roof_clay():
    np = _np()
    pitch, course = 32, 32  # pantile width / course height
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    row = y // course
    xo = (x + (row % 2) * (pitch // 2)) % SIZE
    col = xo // pitch
    rng = np.random.default_rng(23)
    tone = rng.uniform(0.80, 1.20, (SIZE // course, SIZE // pitch))[row, col]
    shift = rng.uniform(0.0, 1.0, (SIZE // course, SIZE // pitch))[row, col]
    fx = (xo % pitch) / pitch
    fy = (y % course) / course
    wave = 0.82 + 0.18 * np.cos((fx - 0.5) * 2 * np.pi)  # S-curve of the pan
    lip = 1.0 - 0.38 * np.clip((fy - 0.72) / 0.28, 0, 1) ** 1.5  # shadow under the overlap
    lip *= 0.85 + 0.15 * fy
    field = tone * wave * lip * (0.9 + 0.2 * fbm(5, 3, 3))
    base = np.array((0.58, 0.29, 0.20))
    brown = np.array((0.42, 0.22, 0.16))
    mix = shift[..., None] * 0.55
    arr = (base[None, None, :] * (1 - mix) + brown[None, None, :] * mix) * field[..., None]
    arr = _tint(arr, (0.28, 0.34, 0.20), np.clip(fbm(31, 5, 3) - 0.66, 0, 1) * 2.4, 0.5)
    return arr


def roof_zinc():
    np = _np()
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    seam_pitch = 64
    fx = (x % seam_pitch) / seam_pitch
    seam = 1.0 + 0.22 * np.exp(-((fx - 0.0) ** 2) / 0.0006) - 0.28 * np.exp(-((fx - 0.035) ** 2) / 0.0004)
    seam += 0.22 * np.exp(-((1.0 - fx) ** 2) / 0.0006)
    strip = np.random.default_rng(37).uniform(0.9, 1.1, SIZE // seam_pitch)[x // seam_pitch]
    streak = 0.9 + 0.2 * fbm(43, 2, 3)
    field = seam * strip * streak
    arr = _rgb((0.40, 0.43, 0.46), field)
    # Rain streaks (vertical) and a few oxidised patches.
    arr = _tint(arr, (0.52, 0.55, 0.56), np.clip(noise(47, 40) - 0.7, 0, 1) * 1.6, 0.35)
    return arr


def roof_flat():
    np = _np()
    base = 0.88 + 0.22 * fbm(51, 6, 4)
    chips = speckle(53, 0.07) * 0.6
    arr = _rgb((0.23, 0.23, 0.24), base)
    arr = arr + chips[..., None] * 0.35
    # Puddled / lighter bitumen seams every 64 px.
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    seam = (x % 64 < 2) * 0.05
    arr = arr + seam[..., None]
    return arr


def sidewalk_slabs():
    np = _np()
    n = 8  # 8x8 slabs -> 30 cm slabs at tile_m 2.4
    cell = SIZE // n
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    rng = np.random.default_rng(61)
    tone = rng.uniform(0.90, 1.08, (n, n))[y // cell, x // cell]
    warm = rng.uniform(-0.02, 0.02, (n, n))[y // cell, x // cell]
    fx, fy = x % cell, y % cell
    joint = ((fx < 2) | (fy < 2)).astype(float)
    bevel = ((fx == 2) | (fy == 2)) * 0.06
    field = tone * (0.92 + 0.16 * fbm(63, 4, 4)) * (1 - 0.42 * joint) + bevel
    arr = _rgb((0.55, 0.54, 0.51), field)
    arr[..., 0] += warm
    arr[..., 2] -= warm
    arr = arr + (grain(65) - 0.5)[..., None] * 0.045
    arr = _tint(arr, (0.30, 0.28, 0.25), np.clip(fbm(67, 4, 4) - 0.64, 0, 1) * 2.0, 0.3)  # stains
    arr = _tint(arr, (0.35, 0.37, 0.30), joint * np.clip(fbm(69, 6, 3) - 0.55, 0, 1) * 2.0, 0.4)  # weeds in joints
    return arr


def asphalt():
    np = _np()
    field = 0.9 + 0.2 * fbm(71, 5, 5)
    arr = _rgb((0.105, 0.105, 0.115), field)
    stones = speckle(73, 0.10)
    arr = arr + stones[..., None] * 0.14
    arr = arr + (grain(75) - 0.5)[..., None] * 0.03
    # Patched repairs: slightly different tone blotches with sharp edges.
    patch = (fbm(77, 3, 2) > 0.62).astype(float)
    arr = _tint(arr, (0.085, 0.085, 0.095), patch, 0.45)
    # Hairline cracks.
    crack = (np.abs(fbm(79, 6, 3) - 0.5) < 0.006).astype(float)
    arr = _tint(arr, (0.03, 0.03, 0.03), crack, 0.8)
    return arr


def park_grass():
    np = _np()
    field = 0.82 + 0.38 * fbm(81, 4, 5)
    arr = _rgb((0.26, 0.45, 0.20), field)
    blades = speckle(83, 0.22)
    arr = arr + blades[..., None] * np.array((0.04, 0.10, 0.02))[None, None, :]
    arr = arr - speckle(85, 0.12)[..., None] * 0.07
    arr = _tint(arr, (0.42, 0.50, 0.20), np.clip(fbm(87, 3, 3) - 0.6, 0, 1) * 2.0, 0.5)  # dry/sunny patches
    arr = _tint(arr, (0.40, 0.33, 0.20), np.clip(fbm(89, 5, 3) - 0.74, 0, 1) * 3.0, 0.45)  # bare earth
    return arr


def curb_granite():
    np = _np()
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    blocks = 2  # 2 stones per 1.6 m repeat -> 80 cm kerb stones
    bw = SIZE // blocks
    rng = np.random.default_rng(91)
    tone = rng.uniform(0.9, 1.1, blocks)[x // bw]
    joint = ((x % bw) < 3).astype(float)
    field = tone * (0.9 + 0.2 * fbm(93, 4, 4)) * (1 - 0.5 * joint)
    arr = _rgb((0.46, 0.46, 0.45), field)
    arr = arr + (speckle(95, 0.18)[..., None] * 0.18) - (speckle(97, 0.10)[..., None] * 0.12)
    return arr


def courtyard_gravel():
    np = _np()
    field = 0.85 + 0.3 * fbm(101, 6, 5)
    arr = _rgb((0.66, 0.63, 0.57), field)
    arr = arr + (speckle(103, 0.20)[..., None] * 0.16) - (speckle(105, 0.18)[..., None] * 0.16)
    arr = _tint(arr, (0.42, 0.40, 0.36), np.clip(fbm(107, 3, 3) - 0.6, 0, 1) * 2.0, 0.4)
    return arr


GENERATORS = {
    "roof_slate": roof_slate,
    "roof_clay": roof_clay,
    "roof_zinc": roof_zinc,
    "roof_flat": roof_flat,
    "sidewalk": sidewalk_slabs,
    "asphalt": asphalt,
    "grass": park_grass,
    "curb": curb_granite,
    "gravel": courtyard_gravel,
}


def render_all(out_dir: Path = TEXTURES_DIR) -> list[Path]:
    np = _np()
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dev tool message
        raise SystemExit("Pillow is required: pip install -e .[textures]") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for key, fn in GENERATORS.items():
        arr = np.clip(fn(), 0.0, 1.0)
        img = Image.fromarray((arr * 255.0 + 0.5).astype("uint8"), "RGB")
        path = out_dir / kit.surface_file(key)
        img.save(path, quality=88, optimize=True)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(TEXTURES_DIR))
    args = parser.parse_args(argv)
    written = render_all(Path(args.out))
    print(f"Wrote {len(written)} surface textures to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
