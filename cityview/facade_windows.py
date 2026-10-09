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

Detection is layered. (1) Glass is a compact, darker-than-its-surroundings blob of window
proportions (conservative, tight on the glass). (2) *Framed* windows that are not darker than
the wall (white sashes in brick, stone surrounds) are found as dense rectangles of edges,
picked from a threshold hierarchy so merged rows fall apart into single windows. (3) Every
confident window is then used as a template: elevations repeat the same sash on every floor,
so normalised cross-correlation of the edge image recovers the siblings the first two passes
missed. A window that is still missed simply stays dark at night.
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


# --- layered detection helpers (pure box maths first, numpy below) -------------------------

Box = tuple[int, int, int, int]  # pixel (x0, y0, x1, y1), y down
MATCH_THRESHOLD = 0.5  # normalised cross-correlation needed to accept a sibling window
MAX_NEW_PER_FACADE = 12
FRAME_PAD = (0.11, 0.07)  # frame / glass: how far a sash extends past the glass, (w, h) fractions
GLASS_INSET = (0.09, 0.06)  # inverse for density boxes that include the frame


def box_overlap(a: Box, b: Box) -> float:
    """Intersection area as a fraction of the smaller box (0 when disjoint)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy / max(1, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def inset_box(b: Box, fx: float, fy: float) -> Box:
    w, h = b[2] - b[0], b[3] - b[1]
    return (round(b[0] + w * fx), round(b[1] + h * fy), round(b[2] - w * fx), round(b[3] - h * fy))


def grow_box(b: Box, fx: float, fy: float) -> Box:
    w, h = b[2] - b[0], b[3] - b[1]
    return (round(b[0] - w * fx), round(b[1] - h * fy), round(b[2] + w * fx), round(b[3] + h * fy))


def _contains(a: Box, b: Box, slack: int = 2) -> bool:
    return a[0] <= b[0] + slack and a[2] >= b[2] - slack and a[1] <= b[1] + slack and a[3] >= b[3] - slack


def pick_nested(cands: list[tuple[float, Box]]) -> list[Box]:
    """Choose window-sized boxes out of a threshold hierarchy ``[(level, box), ...]``.

    A *low* level gives the biggest component. The largest candidate wins unless it
    swallows two or more disjoint candidates of a higher level (a merged row or
    sill-joined pair): then those children are preferred. Overlapping picks are dropped.
    """
    ordered = sorted(cands, key=lambda c: c[0])
    picked: list[Box] = []
    for lvl, box in ordered:
        kids: list[Box] = []
        for lvl2, kid in sorted(ordered, key=lambda c: -(c[1][2] - c[1][0]) * (c[1][3] - c[1][1])):
            if lvl2 > lvl and kid != box and _contains(box, kid) and all(box_overlap(kid, k) == 0 for k in kids):
                kids.append(kid)
        if len(kids) >= 2:
            continue
        if any(box_overlap(box, p) > 0 for p in picked):
            continue
        picked.append(box)
    return picked


def merge_new(existing: list[Box], extra: list[Box], max_overlap: float = 0.25, limit: int = 99) -> list[Box]:
    """Append boxes of ``extra`` that do not collide with ``existing`` or with each other."""
    out: list[Box] = []
    for b in extra:
        if len(out) >= limit:
            break
        if any(box_overlap(b, c) > max_overlap for c in existing + out):
            continue
        out.append(b)
    return out


def _dense_windows(lum) -> list[Box]:
    """Framed windows as dense blobs of edges, picked through a threshold hierarchy."""
    import numpy as np
    from scipy import ndimage as ndi

    h, w = lum.shape
    g = ndi.gaussian_gradient_magnitude(lum, 1.5)
    dens = ndi.uniform_filter((g > 0.03).astype("float32"), (13, 9))
    lo, hi = np.percentile(dens, 20), np.percentile(dens, 97)
    cands: list[tuple[float, Box]] = []
    for t in np.linspace(0.85, 0.2, 14):
        m = ndi.binary_opening(dens > lo + t * (hi - lo), structure=np.ones((7, 5)))
        lab, _n = ndi.label(m)
        for i, sl in enumerate(ndi.find_objects(lab), start=1):
            ys, xs = sl
            bh, bw = ys.stop - ys.start, xs.stop - xs.start
            fill = float((lab[sl] == i).sum()) / (bh * bw)
            tall = bh * w / (bw * h)  # height:width relative to the cell, ~1.7x on the wall
            if 0.07 * w <= bw <= 0.30 * w and 0.07 * h <= bh <= 0.28 * h and fill > 0.72 and 0.9 <= tall * 2.2 <= 4.5:
                cands.append((float(t), (xs.start, ys.start, xs.stop, ys.stop)))
    return pick_nested(cands)


def _ncc(img, tpl):
    import numpy as np
    from scipy import signal

    t = tpl - tpl.mean()
    tn = float(np.sqrt((t**2).sum())) + 1e-6
    ones = np.ones_like(tpl)
    num = signal.fftconvolve(img, t[::-1, ::-1], mode="valid")
    s1 = signal.fftconvolve(img, ones[::-1, ::-1], mode="valid")
    s2 = signal.fftconvolve(img**2, ones[::-1, ::-1], mode="valid")
    var = np.maximum(s2 - s1**2 / tpl.size, 1e-6)
    return num / (tn * np.sqrt(var))


def _siblings(lum, seeds: list[tuple[Box, Box]]) -> list[Box]:
    """Glass boxes of windows that look like a seed. ``seeds`` = ``[(frame_box, glass_box)]``."""
    import numpy as np
    from scipy import ndimage as ndi

    h, _w = lum.shape
    g = ndi.gaussian_gradient_magnitude(lum, 1.2)
    found: list[tuple[float, Box]] = []
    for frame, glass in seeds[:5]:
        x0, y0, x1, y1 = frame
        tpl = g[max(0, y0) : y1, max(0, x0) : x1]
        if tpl.shape[0] < 8 or tpl.shape[1] < 8 or float(tpl.std()) < 1e-4:
            continue
        m = _ncc(g, tpl)
        peaks = (m == ndi.maximum_filter(m, size=(tpl.shape[0] // 2 | 1, tpl.shape[1] // 2 | 1))) & (m > MATCH_THRESHOLD)
        for y, x in zip(*np.nonzero(peaks)):
            dx, dy = int(x) - x0, int(y) - y0
            found.append((float(m[y, x]), (glass[0] + dx, glass[1] + dy, glass[2] + dx, glass[3] + dy)))
    found.sort(key=lambda f: -f[0])
    return [b for _s, b in found if b[3] < h * 0.965]


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
    n_win = n_lit = n_shop = n_extra = 0
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

        def glow_for(mask, rng=rng, cx0=cx0, cy0=cy0):
            soft = ndi.gaussian_filter(mask.astype("float32"), 0.8)
            tint = np.array(COOL if rng.random() < COOL_FRACTION else WARM, dtype="float32")
            # Warm rooms glow brighter near the ceiling light, with a little per-room variance.
            yy = np.linspace(1.05, 0.7, kit.CELL_INNER_H, dtype="float32")[:, None, None]
            glow = soft[..., None] * tint[None, None, :] * yy * float(0.78 + 0.22 * rng.random())
            region = emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W]
            emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W] = np.maximum(region, glow)

        for x0, x1, z0, z1 in windows:
            n_win += 1
            if rng.random() >= LIT_FRACTION:
                continue
            glow_for(ndi.binary_erosion(lab == blob_of[(x0, z0)], iterations=1))
            n_lit += 1

        # Layers 2 + 3: framed windows (edge density) and siblings by template matching.
        lum = np.asarray(img, dtype="float32") @ np.array([0.299, 0.587, 0.114], dtype="float32") / 255.0
        ph, pw = lum.shape

        def to_px(w):
            return (round(w[0] * pw), round((1 - w[3]) * ph), round(w[1] * pw), round((1 - w[2]) * ph))

        have = [to_px(w) for w in windows]
        blocked = [to_px(s) for s in shops]
        if door is not None:
            dc, dw = door
            blocked.append((round((dc - dw * 0.75) * pw), round(0.40 * ph), round((dc + dw * 0.75) * pw), ph))
        seeds: list[tuple[Box, Box]] = []
        for b in have:
            seeds.append((grow_box(b, *FRAME_PAD), b))
        for fb in _dense_windows(lum):
            seeds.append((fb, inset_box(fb, *GLASS_INSET)))
        seeds.sort(key=lambda sd: -(sd[1][2] - sd[1][0]) * (sd[1][3] - sd[1][1]))
        cand = [gl for _fr, gl in seeds] + _siblings(lum, seeds)
        extra = merge_new(have + blocked, cand, limit=MAX_NEW_PER_FACADE)
        for gx0, gy0, gx1, gy1 in extra:
            gx0, gy0, gx1, gy1 = max(0, gx0), max(0, gy0), min(pw, gx1), min(ph, gy1)
            if gx1 - gx0 < 6 or gy1 - gy0 < 10:
                continue
            w = [gx0 / pw, gx1 / pw, 1 - gy1 / ph, 1 - gy0 / ph]
            if w[2] < 0.035 or w[3] > 0.93:
                continue
            windows.append(w)
            n_win += 1
            n_extra += 1
            if rng.random() < LIT_FRACTION:
                m = np.zeros((ph, pw), dtype=bool)
                m[gy0 + 1 : gy1 - 1, gx0 + 1 : gx1 - 1] = True
                glow_for(m)
                n_lit += 1
        windows = [[round(v, 4) for v in w] for w in windows]
        n_shop += len(shops)
        doc[fid] = {"windows": windows, "shops": shops}
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / kit.EMISSIVE_FILE
    Image.fromarray(np.clip(emissive, 0, 255).astype("uint8")).save(tex_path, quality=88)
    json_path = out_dir / kit.WINDOWS_FILE
    json_path.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True))
    print(f"windows: {n_win} ({n_extra} from frame/template passes, lit {n_lit}), shop glazing: {n_shop} -> {tex_path.name}, {json_path.name}")
    return tex_path, json_path


def main() -> None:
    build()


if __name__ == "__main__":
    main()
