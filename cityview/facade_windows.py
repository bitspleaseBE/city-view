"""Find the glass in each generated façade elevation (needs Pillow + numpy + scipy).

``python -m cityview.facade_windows``

Reads  assets/generated/facades/facade_NN.jpg
and writes (both committed, so CI only needs Blender)

* ``assets/textures/facade_windows.json`` — per façade, rectangles ``[x0, x1, z0, z1]``
  as fractions of the elevation (x from the left, z from the ground) for
  ``windows`` (confident glass boxes: the builder hangs 3D sills + window heads on them)
  and ``shops`` (wide ground-floor glazing: the builder hangs awnings over them);
* ``assets/textures/facade_emissive.jpg`` — an atlas-aligned night-time glow map: the
  *actual glass pixels* of a seeded subset of windows lit warm (a few cold TV-blue).
  Because the glow follows the detected glass pixels, it lines up with the photo exactly.

Detection is deliberately conservative: glass is a compact, darker-than-its-surroundings
blob of window proportions. A window that is missed simply stays dark at night.
"""

from __future__ import annotations

import json
from pathlib import Path

from cityview import facade_kit as kit
from cityview.paths import ASSETS

FACADES_DIR = ASSETS / kit.FACADE_SRC_DIR
TEXTURES_DIR = ASSETS / kit.TEXTURES_DIRNAME

LIT_FRACTION = 0.8  # share of detected windows with the lights on
COOL_FRACTION = 0.16  # of the lit ones: television blue instead of tungsten
WARM = (255.0, 184.0, 104.0)
COOL = (150.0, 188.0, 255.0)


def _need_deps():
    try:
        import numpy  # noqa: F401
        import scipy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - dev tool message
        raise SystemExit("pip install pillow numpy scipy (or `pip install -e .[textures]`)") from exc


def classify_boxes(
    boxes: list[tuple[float, float, float, float, float]],
    door: tuple[float, float] | None,
    size_m: tuple[float, float] = (6.0, 13.0),
):
    """Split raw blob boxes ``(x0, x1, z0, z1, fill)`` (fractions of the elevation, ``size_m`` its real size) into ``windows`` and ``shops``.

    Pure function (unit-tested). Doors (known from ``kit.DOORS``) and blobs hugging the
    ground are dropped; wide low glazing becomes a shop; tall compact glass a window.
    """
    windows, shops = [], []
    for x0, x1, z0, z1, fill in boxes:
        w, h = x1 - x0, z1 - z0
        if w <= 0 or h <= 0:
            continue
        if door is not None and z1 < 0.55:
            c, dw = door
            if x1 > c - dw * 0.75 and x0 < c + dw * 0.75:
                continue  # that is the front door, not glass
        if z0 < 0.035:
            continue
        if w >= 0.26 and z1 <= 0.5 and fill >= 0.6:
            shops.append([round(x0, 4), round(x1, 4), round(z0, 4), round(z1, 4)])
            continue
        aspect = (h * size_m[1]) / (w * size_m[0])  # height : width on the real wall
        if fill >= 0.62 and 0.06 <= w <= 0.24 and 0.8 <= aspect <= 3.6:
            windows.append([round(x0, 4), round(x1, 4), round(z0, 4), round(z1, 4)])
    return windows, shops


def _detect(img):
    """Return raw blobs ``[(x0, x1, z0, z1, fill), ...]`` plus the label image."""
    import numpy as np
    from scipy import ndimage as ndi

    arr = np.asarray(img.convert("RGB"), dtype="float32") / 255.0
    lum = arr @ np.array([0.299, 0.587, 0.114], dtype="float32")
    smooth = ndi.gaussian_filter(lum, 1.2)
    local = ndi.gaussian_filter(lum, 22)
    mask = (smooth < 0.80 * local) & (smooth < 0.50)
    mask = ndi.binary_closing(mask, structure=np.ones((11, 5)))
    mask = ndi.binary_opening(mask, structure=np.ones((7, 5)))
    lab, _n = ndi.label(mask)
    h, w = lum.shape
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        ys, xs = sl
        bh, bw = ys.stop - ys.start, xs.stop - xs.start
        fill = float((lab[sl] == i).sum()) / (bh * bw)
        if bw < 0.05 * w or bw > 0.62 * w or bh < 0.06 * h or bh > 0.3 * h or fill < 0.55:
            continue
        out.append((xs.start / w, xs.stop / w, 1 - ys.stop / h, 1 - ys.start / h, fill, i))
    return out, lab


def build(src_dir: Path = FACADES_DIR, out_dir: Path = TEXTURES_DIR) -> tuple[Path, Path]:
    _need_deps()
    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi

    aw, ah = kit.atlas_size()
    emissive = np.zeros((ah, aw, 3), dtype="float32")
    doc: dict[str, dict] = {}
    n_win = n_lit = n_shop = 0
    for fid, f in kit.FACADES.items():
        img = Image.open(src_dir / f["file"]).convert("RGB")
        img = img.resize((kit.CELL_INNER_W, kit.CELL_INNER_H), Image.LANCZOS)
        raw, lab = _detect(img)
        door = kit.DOORS.get(fid)
        windows, shops = classify_boxes([r[:5] for r in raw], door, (f["width_m"], f["height_m"]))
        blob_of = {(round(r[0], 4), round(r[2], 4)): r[5] for r in raw}
        windows = [w for w in windows if w[3] <= 0.93]
        cx0, cy0, _cx1, _cy1 = kit.cell_pixel_rect(fid)
        rng = np.random.default_rng(kit._stable(f"emissive:{fid}"))
        for x0, x1, z0, z1 in windows:
            n_win += 1
            if rng.random() >= LIT_FRACTION:
                continue
            glass = ndi.binary_erosion(lab == blob_of[(x0, z0)], iterations=1)
            soft = ndi.gaussian_filter(glass.astype("float32"), 0.8)
            tint = np.array(COOL if rng.random() < COOL_FRACTION else WARM, dtype="float32")
            # Warm rooms glow brighter near the ceiling light, with a little per-room variance.
            yy = np.linspace(1.05, 0.7, kit.CELL_INNER_H, dtype="float32")[:, None, None]
            glow = soft[..., None] * tint[None, None, :] * yy * float(0.78 + 0.22 * rng.random())
            region = emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W]
            emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W] = np.maximum(region, glow)
            n_lit += 1
        windows = [[round(v, 4) for v in w] for w in windows]
        n_shop += len(shops)
        doc[fid] = {"windows": windows, "shops": shops}
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / kit.EMISSIVE_FILE
    Image.fromarray(np.clip(emissive, 0, 255).astype("uint8")).save(tex_path, quality=88)
    json_path = out_dir / kit.WINDOWS_FILE
    json_path.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True))
    print(f"windows: {n_win} (lit {n_lit}), shop glazing: {n_shop} -> {tex_path.name}, {json_path.name}")
    return tex_path, json_path


def main() -> None:
    build()


if __name__ == "__main__":
    main()
