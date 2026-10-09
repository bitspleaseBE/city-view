"""Pack the 50 generated façades into one atlas (needs Pillow).

``python -m cityview.facade_textures``

Reads  assets/generated/facades/facade_NN.jpg  (image-generated straight elevations)
and    assets/generated/walls/wall_*.jpg       (generated seamless wall textures)
and writes assets/textures/facade_atlas.jpg + wall_*.jpg. The outputs are committed,
so CI (which only has Blender) never needs Pillow.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cityview import facade_kit as kit
from cityview.paths import ASSETS

FACADES_DIR = ASSETS / kit.FACADE_SRC_DIR
WALLS_DIR = ASSETS / kit.WALL_SRC_DIR
TEXTURES_DIR = ASSETS / kit.TEXTURES_DIRNAME
WALL_SIZE = 512


def _need_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - dev tool message
        raise SystemExit("Pillow is required: pip install pillow (or `pip install -e .[textures]`)") from exc


def _paste_cell(atlas, img, rect):
    """Paste a façade and extend its edge pixels into the PAD gutter."""
    from PIL import Image

    x0, y0, x1, y1 = rect
    pad = kit.PAD
    atlas.paste(img, (x0, y0))
    w, h = img.size
    atlas.paste(img.crop((0, 0, 1, h)).resize((pad, h), Image.NEAREST), (x0 - pad, y0))
    atlas.paste(img.crop((w - 1, 0, w, h)).resize((pad, h), Image.NEAREST), (x1, y0))
    top = atlas.crop((x0 - pad, y0, x1 + pad, y0 + 1)).resize((w + 2 * pad, pad), Image.NEAREST)
    atlas.paste(top, (x0 - pad, y0 - pad))
    bottom = atlas.crop((x0 - pad, y1 - 1, x1 + pad, y1)).resize((w + 2 * pad, pad), Image.NEAREST)
    atlas.paste(bottom, (x0 - pad, y1))


def _seeded_rng(fid: str):
    import numpy as np

    return np.random.default_rng(kit._stable(f"weather:{fid}"))


def _blur(arr, sigma: float):
    """Separable gaussian blur of a float32 2-D/3-D array (axes 0 and 1)."""
    import numpy as np

    radius = max(1, int(sigma * 3))
    xs = np.arange(-radius, radius + 1, dtype="float32")
    k = np.exp(-(xs**2) / (2 * sigma * sigma))
    k /= k.sum()
    out = np.apply_along_axis(lambda m: np.convolve(np.pad(m, radius, mode="edge"), k, mode="valid"), 0, arr)
    return np.apply_along_axis(lambda m: np.convolve(np.pad(m, radius, mode="edge"), k, mode="valid"), 1, out)


def clean_sky(img, fid: str):  # noqa: D401 - see docstring
    """Replace pale sky wedges beside stepped / curved gables with a slate backdrop.

    The façade quad is a rectangle up to the eaves, so any light sky pixel in the
    source would render as a white patch. Flood-fill (from the top edge) every
    low-saturation light pixel in the upper fifth and repaint it as a soft slate
    gradient, so the gable reads against a neighbouring roof instead of a hole.
    """
    import numpy as np
    from collections import deque

    if fid not in kit.SKY_FACADES:
        return img, 0.0  # pale flat-roofed / white-render walls must keep their top rows
    arr = np.asarray(img).astype("float32")
    h, w, _ = arr.shape
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    sky = (mx > 170) & (sat < 0.10)
    limit = int(h * 0.22)
    seen = np.zeros((h, w), dtype=bool)
    dq = deque((0, x) for x in range(w) if sky[0, x])
    for _, x in dq:
        seen[0, x] = True
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < limit and 0 <= nx < w and sky[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                dq.append((ny, nx))
    if seen.sum() < 0.004 * h * w:
        return img, 0.0
    # Grow one pixel so the anti-aliased gable edge does not keep a pale halo.
    grown = seen.copy()
    grown[1:, :] |= seen[:-1, :]
    grown[:-1, :] |= seen[1:, :]
    grown[:, 1:] |= seen[:, :-1]
    grown[:, :-1] |= seen[:, 1:]
    grown &= (mx > 120) & (sat < 0.2)
    top = np.array([104.0, 108.0, 116.0], dtype="float32")
    low = np.array([78.0, 80.0, 88.0], dtype="float32")
    t = np.clip(np.arange(h, dtype="float32") / max(1, limit), 0, 1)[:, None, None]
    backdrop = top * (1 - t) + low * t
    soft = _blur(grown.astype("float32"), 0.8)[..., None]
    out = arr * (1 - soft) + backdrop * soft
    from PIL import Image

    return Image.fromarray(np.clip(out, 0, 255).astype("uint8")), float(seen.mean())


def weather_facade(img, fid: str):
    """Bake a century of Antwerp grime into one elevation (seeded per façade).

    * damp / splash-back darkening and warm soot along the plinth,
    * soot under the cornice, blotchy low-frequency tonal variation,
    * rain streaks falling from sills and string courses.
    Everything is multiplicative and subtle: the photo-real elevation stays
    readable, it just stops looking freshly rendered.
    """
    import numpy as np
    from PIL import Image

    rng = _seeded_rng(fid)
    arr = np.asarray(img).astype("float32") / 255.0
    h, w, _ = arr.shape
    yy = np.linspace(0.0, 1.0, h, dtype="float32")[:, None]

    shade = np.ones((h, w), dtype="float32")
    # Ground grime: rising damp + splash-back fades out over the lowest ~16 %.
    grime_h = 0.16
    g = np.clip((yy - (1.0 - grime_h)) / grime_h, 0.0, 1.0)
    shade *= 1.0 - 0.34 * g * g
    # Wet line: a crisp tide mark where splash-back stops (varies along the wall).
    tide = (1.0 - 0.055 - 0.02 * _blur(rng.random((1, w)).astype("float32"), 6.0)[0] * 8.0)[None, :]
    shade *= 1.0 - 0.07 * np.exp(-(((yy - tide) / 0.006) ** 2))
    # Soot under the cornice.
    soot = np.clip((0.06 - yy) / 0.06, 0.0, 1.0)
    shade *= 1.0 - 0.14 * soot

    # Low-frequency blotches (two octaves) so repeated houses never look identical.
    blot = np.zeros((h, w), dtype="float32")
    for sigma, amp in ((26.0, 0.10), (9.0, 0.05)):
        n = _blur(rng.standard_normal((h, w)).astype("float32"), sigma)
        n /= max(float(np.abs(n).max()), 1e-6)
        blot += n * amp
    shade *= 1.0 + blot

    # Rain streaks: narrow, long, blurred, fading downward.
    streaks = np.zeros((h, w), dtype="float32")
    for _ in range(max(6, w // 14)):
        x = int(rng.integers(3, w - 3))
        y0 = int(rng.integers(int(h * 0.05), int(h * 0.75)))
        ln = int(rng.integers(int(h * 0.08), int(h * 0.30)))
        wd = int(rng.integers(1, 4))
        fade = np.linspace(1.0, 0.15, min(ln, h - y0), dtype="float32")
        streaks[y0 : y0 + len(fade), max(0, x - wd // 2) : x + wd // 2 + 1] += fade[:, None] * rng.uniform(0.05, 0.14)
    streaks = _blur(streaks, 1.1)
    shade *= 1.0 - np.clip(streaks, 0.0, 0.22)

    # Warm soot tint grows with the same grime field (browner near the ground).
    tint = np.stack([1.0 + 0.0 * g, 1.0 - 0.05 * g, 1.0 - 0.14 * g], axis=-1)
    out = arr * shade[..., None] * tint
    return Image.fromarray(np.clip(out * 255.0, 0, 255).astype("uint8"))


def build_atlas(src_dir: Path = FACADES_DIR, out_dir: Path = TEXTURES_DIR) -> Path:
    _need_pillow()
    from PIL import Image, ImageEnhance

    out_dir.mkdir(parents=True, exist_ok=True)
    aw, ah = kit.atlas_size()
    atlas = Image.new("RGB", (aw, ah), (128, 120, 110))
    for fid, facade in kit.FACADES.items():
        img = Image.open(src_dir / facade["file"]).convert("RGB")
        img = img.resize((kit.CELL_INNER_W, kit.CELL_INNER_H), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.05)
        img, _sky = clean_sky(img, fid)
        img = weather_facade(img, fid)
        _paste_cell(atlas, img, kit.cell_pixel_rect(fid))
    path = out_dir / kit.ATLAS_FILE
    atlas.save(path, quality=86, optimize=True, progressive=False)
    return path


NORMAL_FILE = kit.NORMAL_FILE
NORMAL_STRENGTH = 2.4  # slope scale: larger = deeper-looking reveals


def height_from_elevation(arr):
    """Relief height field (float32 0..1, y down) read off one weathered elevation.

    No geometry is known for the generated photos, so depth is inferred:
    * dark, low-saturation panes that are darker than their surround are
      *recessed* (window glass / door panels sit behind the masonry),
    * a thin high-pass of the luminance carries brick courses, mortar, stone
      joints, frames and sills as fine relief.
    """
    import numpy as np

    lum = arr @ np.array([0.299, 0.587, 0.114], dtype="float32")
    fine = lum - _blur(lum, 2.2)
    local = _blur(lum, 14.0)
    dark = np.clip((local - lum) / 0.20, 0.0, 1.0)  # 1 where much darker than the neighbourhood
    recess = _blur(dark, 1.6) * 0.8 + _blur(dark, 5.0) * 0.5  # soft chamfer around every opening
    return np.clip(0.5 + 0.9 * fine - recess * 0.55, 0.0, 1.0).astype("float32")


def normals_from_height(height, strength: float = NORMAL_STRENGTH):
    """Tangent-space normal map (glTF/OpenGL +Y up) from a y-down height field."""
    import numpy as np

    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5
    gy_down = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5
    nx = -gx * strength * 6.0
    ny = gy_down * strength * 6.0  # image-down height gain => +Y(up) slope sign flips
    nz = np.ones_like(nx)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx * inv, ny * inv, nz * inv], axis=-1)


def build_normal_atlas(atlas_path: Path | None = None, out_dir: Path = TEXTURES_DIR) -> Path:
    """facade_normal.jpg: normal map aligned 1:1 with facade_atlas.jpg (same UVs)."""
    _need_pillow()
    import numpy as np
    from PIL import Image

    atlas_path = atlas_path or (out_dir / kit.ATLAS_FILE)
    atlas = np.asarray(Image.open(atlas_path).convert("RGB")).astype("float32") / 255.0
    normal = np.zeros_like(atlas)
    normal[..., 2] = 1.0
    for fid in kit.FACADES:
        x0, y0, x1, y1 = kit.cell_pixel_rect(fid)
        pad = kit.PAD
        cell = atlas[y0 - pad : y1 + pad, x0 - pad : x1 + pad]
        n = normals_from_height(height_from_elevation(cell))
        # The gutter repeats the edge pixels, so the relief fades out there by itself.
        normal[y0 - pad : y1 + pad, x0 - pad : x1 + pad] = n
    rgb = np.clip((normal * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype("uint8")
    path = out_dir / NORMAL_FILE
    Image.fromarray(rgb).save(path, quality=76, optimize=True)
    return path


def build_wall_tiles(src_dir: Path = WALLS_DIR, out_dir: Path = TEXTURES_DIR) -> list[Path]:
    _need_pillow()
    import numpy as np
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for tid, tile in kit.WALL_TILES.items():
        img = Image.open(src_dir / tile["src"]).convert("RGB").resize((WALL_SIZE, WALL_SIZE), Image.LANCZOS)
        gain = float(tile.get("gain", 1.0))
        if gain != 1.0:
            arr = np.asarray(img).astype("float32") * gain
            img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
        path = out_dir / kit.wall_tile_file(tid)
        img.save(path, quality=86, optimize=True)
        written.append(path)
    return written


BANDS_FILE = kit.BANDS_FILE
_BAND_ROWS = 8  # rows compared on each side of a seam
BAND_MAX_COST = 0.35  # worse seams than this are visible; those elevations are not stacked


def find_storey_band(cell, windows: list[list[float]], storeys: int):
    """Seamless repeatable storey strip of one elevation (``cell``: H x W x 3 float array).

    Stacked copies of a strip ``[lo, hi]`` (fractions of the height from the ground) join
    where row ``hi`` meets row ``lo``, so the strip repeats without a visible seam when
    those rows match, so we look for the (lo, hi) pair above the ground floor and below
    the top floor / cornice where they match best, with a strip about one storey tall,
    and seams that fall between window rows (never through glass). Returns
    ``(lo, hi, cost)``.
    """
    import numpy as np

    h = cell.shape[0]
    nat_h = storeys * kit.STOREY_M + kit.EXTRA_M
    nominal = kit.STOREY_M / nat_h  # one storey as a fraction of the elevation
    lum = cell @ np.array([0.299, 0.587, 0.114], dtype="float32")
    best = (1e9, nominal * 1.0 + 0.3, 0.3)
    lo_min = 3.1 / nat_h
    lo_max = 1.0 - 6.2 / nat_h
    for lo_px in range(int((1.0 - lo_max - nominal * 1.25) * h), int((1.0 - lo_min) * h)):
        # lo_px: row index (from the top) of the strip's lower edge.
        for strip_px in range(int(nominal * 0.85 * h), int(nominal * 1.2 * h) + 1, 2):
            top_px = lo_px - strip_px  # the strip's upper edge row index
            if top_px < int(0.10 * h) or lo_px + _BAND_ROWS >= h:
                continue
            lo_f = 1.0 - lo_px / h
            hi_f = 1.0 - top_px / h
            if not (lo_min <= lo_f <= lo_max + 1e-6):
                continue
            a = cell[top_px : top_px + _BAND_ROWS]
            b = cell[lo_px : lo_px + _BAND_ROWS]
            cost = float(np.abs(a - b).mean())
            # Vertical gradients across the join should agree too (no step in a line).
            cost += 0.5 * float(np.abs(lum[top_px] - lum[lo_px]).mean())
            cost += 0.04 * abs(strip_px / (nominal * h) - 1.0)
            for x0, x1, z0, z1 in windows:
                for seam in (lo_f, hi_f):
                    if z0 - 0.004 <= seam <= z1 + 0.004:
                        cost += 0.35  # a seam through glass would show
            if cost < best[0]:
                best = (cost, hi_f, lo_f)
    return best[2], best[1], best[0]


def build_bands(atlas_path: Path | None = None, out_dir: Path = TEXTURES_DIR) -> Path:
    """facade_bands.json: the repeatable storey strip of every elevation (see ``find_storey_band``)."""
    _need_pillow()
    import json
    import numpy as np
    from PIL import Image

    atlas_path = atlas_path or (out_dir / kit.ATLAS_FILE)
    atlas = np.asarray(Image.open(atlas_path).convert("RGB")).astype("float32") / 255.0
    try:
        windows = json.loads((out_dir / kit.WINDOWS_FILE).read_text())
    except (OSError, ValueError):
        windows = {}
    doc = {}
    for fid, facade in kit.FACADES.items():
        x0, y0, x1, y1 = kit.cell_pixel_rect(fid)
        cell = atlas[y0:y1, x0:x1]
        lo, hi, cost = find_storey_band(cell, (windows.get(fid) or {}).get("windows", []), facade["storeys"])
        if cost > BAND_MAX_COST:
            continue  # no clean repeat in this picture: it keeps the single-stretch mapping
        doc[fid] = {"lo": round(lo, 4), "hi": round(hi, 4), "cost": round(cost, 4)}
    path = out_dir / BANDS_FILE
    path.write_text(json.dumps(doc, indent=1) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facades", default=str(FACADES_DIR))
    parser.add_argument("--walls", default=str(WALLS_DIR))
    parser.add_argument("--out", default=str(TEXTURES_DIR))
    parser.add_argument("--normal-only", action="store_true", help="only rebuild facade_normal.jpg from the committed atlas")
    parser.add_argument("--bands", action="store_true", help="only rebuild facade_bands.json (repeatable storey strips) from the committed atlas")
    args = parser.parse_args(argv)
    if args.bands:
        path = build_bands(None, Path(args.out))
        print(f"Wrote {path}")
        return 0
    if args.normal_only:
        normal = build_normal_atlas(None, Path(args.out))
        print(f"Wrote {normal} ({normal.stat().st_size // 1024} KiB normal atlas)")
        return 0
    atlas = build_atlas(Path(args.facades), Path(args.out))
    tiles = build_wall_tiles(Path(args.walls), Path(args.out))
    normal = build_normal_atlas(atlas, Path(args.out))
    print(f"Wrote {normal} ({normal.stat().st_size // 1024} KiB normal atlas)")
    print(
        f"Wrote {atlas} ({atlas.stat().st_size // 1024} KiB, {kit.FACADE_COUNT} facades) "
        f"+ {len(tiles)} wall tiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
