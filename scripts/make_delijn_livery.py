#!/usr/bin/env python3
"""Turn the generated De Lijn elevation drawings into viewer livery textures.

Inputs  : assets/references/delijn-liveries/*.jpg   (AI-generated flat elevations,
          prompted from public De Lijn photos / brand guide; see README "Livery").
Outputs : viewer/livery/*.jpg (+ *_glow.jpg emissive maps for night windows).

Each elevation is auto-cropped to the vehicle silhouette, the baked-in LED
destination displays are blanked (viewer/transit.js draws live ones on top), and
the result is resized to a power-of-two texture that maps 1:1 onto a BoxGeometry
face.  Run:  python3 scripts/make_delijn_livery.py   (needs Pillow + numpy)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "references" / "delijn-liveries"
OUT = ROOT / "viewer" / "livery"

LED_BLANK = (22, 20, 16)

# name -> (source file, output size, LED boxes (x0, y0, x1, y1),
#          glow rows as fractions of the cropped height (None = no night glow), optional x-crop (x0, x1)).
# All pixel coordinates are in a 1024-px-wide frame of the source (scaled to the
# real source width in main()).
JOBS = {
    "tram_side_l": ("tram_side_front_left.jpg", (1024, 256), [], (0.20, 0.72), None),
    "tram_side_r": ("tram_side_front_right.jpg", (1024, 256), [], (0.20, 0.72), None),
    "tram_front": ("tram_front.jpg", (512, 512), [(368, 117, 656, 174)], None, (282, 742)),
    "bus_side_l": (
        "bus_side_front_left.jpg",
        (1024, 256),
        [(184, 185, 311, 209)],
        (0.04, 0.58),
        (33, 1024),  # trim the mirror stalk off the body silhouette
    ),
    "bus_side_r": (
        "bus_side_front_right_doors.jpg",
        (1024, 256),
        [(722, 186, 840, 209)],
        (0.04, 0.58),
        (0, 986),
    ),
    "bus_front": ("bus_front.jpg", (512, 512), [(314, 135, 714, 195)], None, (246, 782)),
    "bus_rear": ("bus_rear.jpg", (512, 512), [(629, 127, 730, 187)], None, (244, 784)),
}


def autocrop(img: Image.Image, xcrop) -> Image.Image:
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    mask = a.min(axis=2) < 232
    if xcrop:
        keep = np.zeros_like(mask)
        keep[:, xcrop[0] : xcrop[1]] = True
        mask &= keep
    ys, xs = np.where(mask)
    return img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (fn, size, leds, glow_rows, xcrop) in JOBS.items():
        img = Image.open(SRC / fn).convert("RGB")
        k = img.width / 1024.0
        px = img.load()
        for x0, y0, x1, y1 in leds:
            for y in range(int(y0 * k), int(y1 * k)):
                for x in range(int(x0 * k), int(x1 * k)):
                    px[x, y] = LED_BLANK
        if xcrop:
            xcrop = (int(xcrop[0] * k), int(xcrop[1] * k))
        # Crop offsets matter for the glow rows, so crop first.
        crop = autocrop(img, xcrop).resize(size, Image.LANCZOS)
        crop.save(OUT / f"{name}.jpg", quality=88, optimize=True)

        if glow_rows is None:
            print(f"{name}: {size[0]}x{size[1]}")
            continue
        a = np.asarray(crop).astype(np.float32)
        luma = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        h = luma.shape[0]
        rows = np.zeros_like(luma, dtype=bool)
        rows[int(glow_rows[0] * h) : int(glow_rows[1] * h), :] = True
        # Grey glass panes only: the near-black frame/pillars and the yellow logos stay dark.
        lit = rows & (luma >= 78) & (luma < 165) & (np.abs(a[:, :, 0] - a[:, :, 2]) < 25)
        glow = np.zeros(a.shape, dtype=np.uint8)
        glow[lit] = (255, 206, 130)
        Image.fromarray(glow).save(OUT / f"{name}_glow.jpg", quality=80, optimize=True)
        print(f"{name}: {size[0]}x{size[1]} lit={lit.mean():.2f}")


if __name__ == "__main__":
    main()
