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
        _paste_cell(atlas, img, kit.cell_pixel_rect(fid))
    path = out_dir / kit.ATLAS_FILE
    atlas.save(path, quality=86, optimize=True, progressive=False)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facades", default=str(FACADES_DIR))
    parser.add_argument("--walls", default=str(WALLS_DIR))
    parser.add_argument("--out", default=str(TEXTURES_DIR))
    args = parser.parse_args(argv)
    atlas = build_atlas(Path(args.facades), Path(args.out))
    tiles = build_wall_tiles(Path(args.walls), Path(args.out))
    print(
        f"Wrote {atlas} ({atlas.stat().st_size // 1024} KiB, {kit.FACADE_COUNT} facades) "
        f"+ {len(tiles)} wall tiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
