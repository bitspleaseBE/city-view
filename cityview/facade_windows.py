"""Find the glass in each generated façade elevation (needs Pillow + numpy + scipy).

``python -m cityview.facade_windows``

Reads  assets/generated/facades/facade_NN.jpg
and writes (both committed, so CI only needs Blender)

* ``assets/textures/facade_windows.json`` — per façade, rectangles ``[x0, x1, z0, z1]``
  as fractions of the elevation (x from the left, z from the ground) for
  ``windows`` (confident glass boxes: the builder hangs 3D sills + window heads on them)
  and ``shops`` (wide ground-floor glazing: the builder hangs awnings over them);
* ``assets/textures/facade_emissive.jpg`` — an atlas-aligned night-time glow map: a seeded
  subset of windows lit warm (a few cold TV-blue), with simple painted room interiors
  (curtains, plants, table lamps, blinds) so the glow reads as inhabited space rather than
  the photo's mullions and reflections.

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

# Night interiors painted into each lit pane (weights sum to 1).
INTERIOR_KINDS: tuple[tuple[str, float], ...] = (
    ("curtains", 0.28),
    ("plant", 0.18),
    ("table_lamp", 0.18),
    ("blinds", 0.14),
    ("shelf", 0.12),
    ("empty", 0.10),
)


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


def glass_mask_in_box(
    lum,
    box: Box,
    *,
    dark_rel: float = 0.90,
    dark_abs: float = 0.52,
    min_frac: float = 0.22,
    local=None,
):
    """Boolean mask of glass-like pixels inside ``box`` (full image shape).

    Night glow used to paint the whole window rectangle — frames, stone surrounds and
    even plain wall when the detector was slightly off — so lights appeared on the
    masonry. Only keep pixels that are darker than their surroundings (or the darker
    share of the box). Returns an empty mask when the box is mostly wall.
    """
    import numpy as np
    from scipy import ndimage as ndi

    h, w = lum.shape
    x0, y0, x1, y1 = box
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    out = np.zeros((h, w), dtype=bool)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return out
    if local is None:
        local = ndi.gaussian_filter(lum, 18.0)
    patch = lum[y0:y1, x0:x1]
    loc = local[y0:y1, x0:x1]
    # Relative darkness catches recessed glass; percentile catches pale reflections in the pane.
    thr = float(np.percentile(patch, 42))
    glass = ((patch < dark_rel * loc) & (patch < dark_abs)) | ((patch <= thr) & (patch < 0.56))
    # Drop single-pixel speckles on mortar / ornament; keep the pane body.
    glass = ndi.binary_opening(glass, structure=np.ones((2, 2)))
    if float(glass.mean()) < min_frac:
        return out
    # Slight inward erode so glow stays off the sash / stone frame.
    glass = ndi.binary_erosion(glass, iterations=1)
    if not glass.any():
        return out
    out[y0:y1, x0:x1] = glass
    return out


def accept_window_box(lum, box: Box, local=None) -> bool:
    """True when ``box`` contains enough glass-like pixels to light (not a wall false positive)."""
    return bool(glass_mask_in_box(lum, box, local=local, min_frac=0.22).any())


def pick_interior_kind(rng) -> str:
    """Deterministic pick from ``INTERIOR_KINDS`` using ``rng.random()``."""
    r = float(rng.random())
    acc = 0.0
    for kind, weight in INTERIOR_KINDS:
        acc += weight
        if r < acc:
            return kind
    return INTERIOR_KINDS[-1][0]


def paint_room_interior(h: int, w: int, kind: str, rng) -> "object":
    """HxW float32 in ``[0, 1]``: bright = lit room, dark = silhouette (curtain / plant / …).

    Pure drawing (no photo sampling): mullions and reflections from the elevation used to
    punch weird holes in the glow; these shapes read as furniture instead.
    """
    import numpy as np

    h, w = max(4, int(h)), max(4, int(w))
    yy, xx = np.mgrid[0:h, 0:w]
    u = (xx + 0.5) / w
    v = (yy + 0.5) / h  # 0 at the top of the pane, 1 at the sill
    # Soft room wash: a little brighter near the ceiling light.
    room = np.full((h, w), 0.88, dtype="float32")
    room *= (0.72 + 0.38 * (1.0 - v)).astype("float32")

    def darken(mask, amount: float):
        nonlocal room
        room = room * (1.0 - amount * mask.astype("float32"))

    if kind == "curtains":
        # Side drapes meeting a bright central gap; soft vertical folds.
        left = np.clip(1.0 - u / 0.26, 0.0, 1.0) ** 1.35
        right = np.clip(1.0 - (1.0 - u) / 0.26, 0.0, 1.0) ** 1.35
        drape = np.maximum(left, right)
        folds = 0.55 + 0.45 * np.sin(v * 22.0 + u * 4.0 + float(rng.random()) * 6.0)
        darken(drape * folds, 0.82)
        # Tie-back bulge mid-height.
        mid = np.exp(-((v - 0.45) ** 2) / 0.04) * drape
        darken(mid, 0.15)
    elif kind == "plant":
        cx = 0.32 + 0.36 * float(rng.random())
        # Pot on the sill.
        pot = ((u - cx) ** 2) / 0.018 + ((v - 0.90) ** 2) / 0.012 < 1.0
        darken(pot, 0.78)
        # Leafy canopy above the pot.
        for i in range(5):
            lx = cx + 0.10 * (float(rng.random()) - 0.5)
            ly = 0.62 + 0.08 * float(rng.random())
            leaf = ((u - lx) ** 2) / (0.012 + 0.01 * i) + ((v - ly) ** 2) / (0.020 + 0.008 * i) < 1.0
            darken(leaf, 0.55 + 0.08 * i)
    elif kind == "table_lamp":
        # Table / desk along the sill.
        table = (v > 0.72) & (u > 0.18) & (u < 0.82)
        darken(table, 0.55)
        # Lamp base + warm shade (shade stays brighter — a local light).
        lx = 0.40 + 0.20 * float(rng.random())
        base = ((u - lx) ** 2) / 0.004 + ((v - 0.68) ** 2) / 0.010 < 1.0
        darken(base, 0.7)
        shade = ((u - lx) ** 2) / 0.028 + ((v - 0.42) ** 2) / 0.022 < 1.0
        room = np.where(shade, np.clip(room * 1.25, 0.0, 1.0), room)
        # Chair back hint.
        chair = ((u - (lx + 0.22)) ** 2) / 0.010 + ((v - 0.78) ** 2) / 0.035 < 1.0
        darken(chair, 0.45)
    elif kind == "blinds":
        # Horizontal slats with a slight pull-cord gap.
        slat = (np.sin(v * h * 0.85 + 0.4) > 0.15).astype("float32")
        gap = (np.abs(u - 0.5) < 0.06).astype("float32")
        darken(slat * (1.0 - 0.7 * gap), 0.62)
    elif kind == "shelf":
        # Bookshelf / picture: a few dark rectangles on one side.
        side = 0.18 if rng.random() < 0.5 else 0.62
        for i in range(3):
            top = 0.18 + 0.22 * i
            shelf = (u > side) & (u < side + 0.28) & (v > top) & (v < top + 0.06)
            books = (u > side + 0.02) & (u < side + 0.26) & (v > top + 0.06) & (v < top + 0.18)
            darken(shelf, 0.7)
            darken(books, 0.45 + 0.1 * float(rng.random()))
        # Small plant pot in the opposite corner.
        cx = 0.78 if side < 0.5 else 0.22
        pot = ((u - cx) ** 2) / 0.012 + ((v - 0.88) ** 2) / 0.010 < 1.0
        darken(pot, 0.65)
    else:  # empty — soft ceiling falloff only, maybe a picture frame
        if rng.random() < 0.55:
            fx, fy = 0.35 + 0.3 * float(rng.random()), 0.22 + 0.1 * float(rng.random())
            frame = (
                (np.abs(u - fx) < 0.16)
                & (np.abs(v - fy) < 0.14)
                & ~((np.abs(u - fx) < 0.12) & (np.abs(v - fy) < 0.10))
            )
            darken(frame, 0.55)

    # Soft vignette so the pane edge never looks cut out of a photo blob.
    edge = np.minimum(np.minimum(u, 1.0 - u) / 0.08, np.minimum(v, 1.0 - v) / 0.08)
    room *= np.clip(edge, 0.0, 1.0).astype("float32")
    return np.clip(room, 0.0, 1.0).astype("float32")


def window_glow_patch(h: int, w: int, rng) -> tuple["object", tuple[float, float, float]]:
    """Interior brightness patch + RGB tint for one lit window."""
    kind = pick_interior_kind(rng)
    tint = COOL if rng.random() < COOL_FRACTION else WARM
    return paint_room_interior(h, w, kind, rng), tint


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
        raw, _lab = _detect(img)
        door = kit.DOORS.get(fid)
        windows, shops = classify_boxes([r[:5] for r in raw], door, (f["width_m"], f["height_m"]))
        windows = [w for w in windows if w[3] <= 0.93]
        cx0, cy0, _cx1, _cy1 = kit.cell_pixel_rect(fid)
        rng = np.random.default_rng(kit._stable(f"emissive:{fid}"))
        # Layers 2 + 3 need luminance early so blob glow can stay on the glass too.
        lum = np.asarray(img, dtype="float32") @ np.array([0.299, 0.587, 0.114], dtype="float32") / 255.0
        ph, pw = lum.shape
        local_lum = ndi.gaussian_filter(lum, 18.0)

        def glow_window(box: Box, rng=rng, cx0=cx0, cy0=cy0, lum=lum, local_lum=local_lum) -> bool:
            """Paint a lit room into ``box``; keep glow inside the pane (no wall bleed)."""
            x0, y0, x1, y1 = box
            # Inset ~10% so stone frames / sashes stay dark and glow can't spill onto brick.
            ix, iy = max(1, int(0.10 * (x1 - x0))), max(1, int(0.10 * (y1 - y0)))
            x0, y0, x1, y1 = x0 + ix, y0 + iy, x1 - ix, y1 - iy
            if x1 - x0 < 4 or y1 - y0 < 4:
                return False
            patch, tint_t = window_glow_patch(y1 - y0, x1 - x0, rng)
            # Kill any paint that still lands on bright masonry inside the box.
            wall = (lum[y0:y1, x0:x1] > 0.60) & (local_lum[y0:y1, x0:x1] > 0.52)
            patch = patch.copy()
            patch[wall] = 0.0
            if float(patch.max()) < 0.05:
                return False
            soft = ndi.gaussian_filter(patch, 0.45)
            soft = np.clip(soft * 1.2, 0.0, 1.0)
            tint = np.array(tint_t, dtype="float32")
            # Ceiling a touch brighter than the sill.
            yy = np.linspace(1.08, 0.78, y1 - y0, dtype="float32")[:, None]
            lit = soft * yy * float(0.80 + 0.20 * rng.random())
            glow = np.zeros((kit.CELL_INNER_H, kit.CELL_INNER_W, 3), dtype="float32")
            glow[y0:y1, x0:x1] = lit[..., None] * tint[None, None, :]
            region = emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W]
            emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W] = np.maximum(region, glow)
            return True

        def to_px(w):
            return (round(w[0] * pw), round((1 - w[3]) * ph), round(w[1] * pw), round((1 - w[2]) * ph))

        for x0, x1, z0, z1 in list(windows):
            n_win += 1
            if rng.random() >= LIT_FRACTION:
                continue
            box = to_px([x0, x1, z0, z1])
            if glow_window(box):
                n_lit += 1

        # Layers 2 + 3: framed windows (edge density) and siblings by template matching.
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
            box = (gx0, gy0, gx1, gy1)
            # Reject wall / ornament false positives: no glass-like core → no window, no glow.
            if not accept_window_box(lum, box, local=local_lum):
                continue
            w = [gx0 / pw, gx1 / pw, 1 - gy1 / ph, 1 - gy0 / ph]
            if w[2] < 0.035 or w[3] > 0.93:
                continue
            windows.append(w)
            n_win += 1
            n_extra += 1
            if rng.random() < LIT_FRACTION and glow_window(box):
                n_lit += 1
        windows = [[round(v, 4) for v in w] for w in windows]
        n_shop += len(shops)
        doc[fid] = {"windows": windows, "shops": shops}

        # Final safety: never leave warm glow on bright masonry of this cell.
        cell = emissive[cy0 : cy0 + kit.CELL_INNER_H, cx0 : cx0 + kit.CELL_INNER_W]
        wall = (lum > 0.55) & (local_lum > 0.48)
        cell[wall] = 0.0
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
