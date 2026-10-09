"""Generated façade kit: 50 straight front elevations mapped onto street façades.

The Blender builder (``blender/build_city.py``) skins street façades with these
images as real glTF textures. This module is pure Python (no bpy/PIL) so the layout
maths is unit-testable; ``cityview/facade_textures.py`` (Pillow) packs the images
into one atlas.

Flow: assets/generated/facades/facade_NN.jpg   (50 image-generated elevations)
      -> facade_textures.py  (pack into assets/textures/facade_atlas.jpg)
      -> build_city.py ImageTexture material + UVs
      -> glTF (atlas embedded in the GLB) -> viewer.

Each source is an orthographic, upright, symmetric-perspective-free elevation of
ONE townhouse. They are mapped **unmirrored**: a long edge becomes a terrace of
different houses side by side, never a mirrored/kaleidoscope repeat, and the image
is stretched vertically just enough to meet the building's eaves.

Buildings much taller (or shorter) than one source elevation are not stretched into
a kaleidoscope: ``assets/textures/facade_bands.json`` (``python -m
cityview.facade_textures --bands``) records a seamless "typical storey" strip per
elevation, found where the picture repeats itself vertically. Tall houses stack that
strip (ground floor below, cornice above), low ones drop it, so the windows keep
their real proportions from 2 up to 20 levels.
"""

from __future__ import annotations

import math
import zlib
from typing import Any

# --- atlas geometry (pixels) -------------------------------------------------
CELL_INNER_W = 288  # every façade is resampled into a 288 x 480 cell
CELL_INNER_H = 480
PAD = 6  # edge-extended gutter so mipmaps never bleed between cells
CELL_W = CELL_INNER_W + 2 * PAD
CELL_H = CELL_INNER_H + 2 * PAD
ATLAS_COLS = 8

ATLAS_FILE = "facade_atlas.jpg"
NORMAL_FILE = "facade_normal.jpg"  # tangent-space relief aligned 1:1 with the atlas
EMISSIVE_FILE = "facade_emissive.jpg"  # night glow of lit windows, aligned 1:1 with the atlas
WINDOWS_FILE = "facade_windows.json"  # detected glass / shop glazing per elevation
BANDS_FILE = "facade_bands.json"  # seamless repeatable storey strip per elevation
TEXTURES_DIRNAME = "textures"
FACADE_SRC_DIR = "generated/facades"
WALL_SRC_DIR = "generated/walls"

# Real-world size model: one storey ~3.2 m plus ~0.6 m of plinth + cornice.
STOREY_M = 3.2
EXTRA_M = 0.6
ASPECTS = {"tall": (9, 16), "wide": (3, 4)}  # source image width:height

# (storeys, aspect, building-type tags). Order == atlas order == facade_NN.jpg.
_FACADE_TABLE: list[tuple[int, str, tuple[str, ...]]] = [
    (4, "tall", ("art-nouveau",)),                           # 01
    (3, "wide", ("red-brick", "neo-flemish")),               # 02
    (4, "tall", ("neoclassical", "cream-tile", "school")),   # 03
    (5, "tall", ("yellow-brick", "art-nouveau")),            # 04
    (3, "wide", ("neo-flemish", "brown-tile")),              # 05
    (4, "tall", ("neo-flemish", "red-brick")),               # 06
    (4, "tall", ("art-nouveau",)),                           # 07
    (3, "wide", ("neoclassical", "antwerp-70s")),            # 08
    (5, "tall", ("eclectic",)),                              # 09
    (4, "tall", ("neo-flemish", "eclectic")),                # 10
    (3, "wide", ("prefab-70s", "brown-tile")),               # 11
    (4, "tall", ("art-deco",)),                              # 12
    (3, "wide", ("cream-tile", "neoclassical", "restaurant")),  # 13
    (4, "tall", ("red-brick",)),                             # 14
    (5, "tall", ("eclectic", "cream-tile")),                 # 15
    (4, "tall", ("art-nouveau",)),                           # 16
    (3, "wide", ("red-brick",)),                             # 17
    (4, "tall", ("neoclassical",)),                          # 18
    (3, "wide", ("eclectic", "white-modern")),               # 19
    (4, "tall", ("neo-gothic", "neo-flemish", "church")),    # 20
    (5, "tall", ("neoclassical", "eclectic")),               # 21
    (4, "tall", ("prefab-70s", "antwerp-70s")),              # 22
    (3, "wide", ("neoclassical", "cream-tile")),             # 23
    (4, "tall", ("art-nouveau",)),                           # 24
    (4, "tall", ("red-brick", "neo-flemish")),               # 25
    (3, "wide", ("neoclassical", "eclectic")),               # 26
    (5, "tall", ("art-nouveau",)),                           # 27
    (3, "wide", ("brown-tile", "red-brick")),                # 28
    (4, "tall", ("neoclassical",)),                          # 29
    (4, "tall", ("yellow-brick", "neo-flemish")),            # 30
    (3, "wide", ("modern-infill", "white-modern", "supermarket", "hospital")),  # 31
    (4, "tall", ("yellow-brick", "art-nouveau")),            # 32
    (3, "wide", ("brown-tile", "neo-flemish")),              # 33
    (5, "tall", ("eclectic", "international", "hospital")),  # 34
    (4, "tall", ("neo-flemish",)),                           # 35
    (3, "wide", ("art-deco", "white-modern")),               # 36
    (4, "tall", ("eclectic", "neoclassical")),               # 37
    (3, "wide", ("red-brick", "antwerp-70s")),               # 38
    (5, "tall", ("neoclassical", "eclectic")),               # 39
    (4, "tall", ("brown-tile", "art-nouveau")),              # 40
    (3, "wide", ("yellow-brick",)),                          # 41
    (4, "tall", ("art-nouveau",)),                           # 42
    (3, "wide", ("cream-tile", "restaurant", "school")),     # 43
    (5, "tall", ("red-brick", "antwerp-70s")),               # 44
    (4, "tall", ("neoclassical", "cream-tile")),             # 45
    (3, "wide", ("antwerp-70s", "prefab-70s")),              # 46
    (4, "tall", ("yellow-brick", "eclectic")),               # 47
    (4, "tall", ("eclectic", "modern-infill", "international")),  # 48
    (5, "tall", ("eclectic", "neoclassical")),               # 49
    (3, "wide", ("neo-flemish", "red-brick")),               # 50
]


def _build_facades() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, (storeys, aspect, tags) in enumerate(_FACADE_TABLE, start=1):
        aw, ah = ASPECTS[aspect]
        height_m = storeys * STOREY_M + EXTRA_M
        out[f"facade_{i:02d}"] = {
            "file": f"facade_{i:02d}.jpg",
            "storeys": storeys,
            "aspect": (aw, ah),
            "height_m": height_m,
            "width_m": round(height_m * aw / ah, 2),
            "types": list(tags),
        }
    return out


FACADES: dict[str, dict[str, Any]] = _build_facades()
FACADE_COUNT = len(FACADES)

# Generated seamless wall textures (side walls, LOD blocks, backing skin).
# tile_m = metres per texture repeat.
WALL_TILES: dict[str, dict[str, Any]] = {
    "brick_red": {"src": "wall_brick_red.jpg", "tile_m": 1.6},
    "brick_brown": {"src": "wall_brick_brown.jpg", "tile_m": 1.6, "gain": 1.9},  # generated tile is very dark
    "stone_buff": {"src": "wall_stone_buff.jpg", "tile_m": 2.4},
    "stucco_cream": {"src": "wall_stucco_cream.jpg", "tile_m": 3.0},
    "brick_yellow": {"src": "wall_brick_yellow.jpg", "tile_m": 1.6},
    "plaster_white": {"src": "wall_plaster_white.jpg", "tile_m": 3.0},
}

TYPE_WALL_TILE: dict[str, str] = {
    "neo-flemish": "brick_brown",
    "red-brick": "brick_red",
    "neoclassical": "stucco_cream",
    "cream-tile": "stucco_cream",
    "eclectic": "stone_buff",
    "yellow-brick": "brick_yellow",
    "art-nouveau": "stone_buff",
    "art-deco": "plaster_white",
    "international": "plaster_white",
    "modern-infill": "plaster_white",
    "neo-gothic": "brick_brown",
    "white-modern": "plaster_white",
    "prefab-70s": "plaster_white",
    "brown-tile": "brick_brown",
    "antwerp-70s": "stucco_cream",
    "school": "stucco_cream",
    "restaurant": "stucco_cream",
    "supermarket": "plaster_white",
    "church": "brick_red",
    "hospital": "plaster_white",
}
DEFAULT_TYPE = "eclectic"

# Elevations whose source image shows pale sky beside a stepped / curved gable
# (the quad is rectangular, so the atlas repaints that sky as a slate backdrop).
SKY_FACADES = frozenset({"facade_06", "facade_16", "facade_50"})

# Front doors read off the 50 elevations: (centre, width) as fractions of the
# image width, left to right. Elevations without a street-level entrance (upper
# storeys only, roller-shutter garages, shop fronts) are simply absent. The
# builder puts stone doorsteps in front of these so entrances stand proud of the
# pavement instead of being a flat picture.
DOORS: dict[str, tuple[float, float]] = {
    "facade_01": (0.11, 0.12), "facade_02": (0.30, 0.13), "facade_03": (0.50, 0.14),
    "facade_04": (0.20, 0.10), "facade_05": (0.41, 0.14), "facade_06": (0.28, 0.14),
    "facade_07": (0.52, 0.13), "facade_08": (0.38, 0.12), "facade_09": (0.50, 0.14),
    "facade_10": (0.28, 0.15), "facade_11": (0.44, 0.13), "facade_12": (0.55, 0.14),
    "facade_13": (0.80, 0.13), "facade_14": (0.30, 0.12), "facade_15": (0.62, 0.13),
    "facade_16": (0.28, 0.14), "facade_17": (0.62, 0.15), "facade_18": (0.48, 0.12),
    "facade_19": (0.78, 0.15), "facade_20": (0.62, 0.15), "facade_21": (0.10, 0.12),
    "facade_22": (0.52, 0.10), "facade_23": (0.38, 0.13), "facade_24": (0.23, 0.15),
    "facade_25": (0.64, 0.16), "facade_26": (0.27, 0.30), "facade_27": (0.65, 0.12),
    "facade_28": (0.47, 0.10), "facade_29": (0.50, 0.14), "facade_30": (0.63, 0.12),
    "facade_31": (0.77, 0.10), "facade_32": (0.50, 0.14), "facade_33": (0.30, 0.14),
    "facade_34": (0.62, 0.15), "facade_35": (0.70, 0.15), "facade_36": (0.78, 0.12),
    "facade_37": (0.50, 0.15), "facade_38": (0.28, 0.14), "facade_39": (0.56, 0.14),
    "facade_40": (0.55, 0.13), "facade_41": (0.63, 0.10), "facade_42": (0.20, 0.14),
    "facade_43": (0.55, 0.12), "facade_44": (0.58, 0.14), "facade_45": (0.78, 0.15),
    "facade_46": (0.78, 0.12), "facade_47": (0.45, 0.14), "facade_48": (0.20, 0.12),
    "facade_49": (0.50, 0.14), "facade_50": (0.92, 0.12),
}

# Shop windows read off the elevations: (x0, x1, top) with x as fractions of the image
# width and ``top`` the lintel height as a fraction of the elevation height. The builder
# hangs a shop awning over each so ground-floor shopfronts shade the pavement.
SHOPS: dict[str, tuple[float, float, float]] = {
    "facade_01": (0.40, 0.90, 0.32),
    "facade_13": (0.08, 0.52, 0.40),
}

# Terrace width target: a long edge is cut into houses about this wide.
TARGET_HOUSE_M = 6.4
# Towers (>= TOWER_LEVELS storeys) are wider, so cut them into fewer, wider elevations
# instead of a row of 6 m "townhouses" side by side.
TOWER_LEVELS = 7
TOWER_HOUSE_M = 9.0
MIN_CROP_FRAC = 0.5


def _door_spans(fid: str) -> list[tuple[float, float]]:
    door = DOORS.get(fid)
    if not door:
        return []
    centre, width = door
    lo, hi = centre - width * 0.5, centre + width * 0.5
    return [(max(0.0, lo), min(1.0, hi))] if hi > lo else []


def _window_spans(fid: str) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for x0, x1, _z0, _z1 in (window_layout().get(fid) or {}).get("windows", []):
        lo, hi = float(x0), float(x1)
        if hi > lo:
            spans.append((max(0.0, lo), min(1.0, hi)))
    return spans


def _feature_spans(fid: str) -> list[tuple[float, float]]:
    """Horizontal spans that should stay whole under a crop (doors + window bays)."""
    return _door_spans(fid) + _window_spans(fid)


def _edge_cuts(edge: float, lo: float, hi: float, margin: float = 0.025) -> bool:
    """True when ``edge`` splits the span by more than ``margin`` (ignore hairline clips)."""
    return lo + margin < edge < hi - margin


def choose_crop_span(fid: str, frac: float, seed_key: str) -> tuple[float, float]:
    """Pick a ``frac``-wide slice of the elevation that keeps doors/windows intact.

    Narrow street edges used to take a random left- or right-aligned crop; when that
    cut through a front door or a window bay you got a half-door / half top floor on
    the party wall. Prefer a window that either fully includes or fully excludes each
    feature; never bisect a door when any alternative exists.
    """
    frac = max(0.05, min(1.0, frac))
    if frac >= 0.999:
        return 0.0, 1.0
    doors = _door_spans(fid)
    windows = _window_spans(fid)
    features = doors + windows
    candidates = {0.0, 1.0 - frac}
    for lo, hi in features:
        # Align crop edges to feature edges (include whole feature or sit just outside).
        for start in (lo, hi - frac, hi, lo - frac):
            if 0.0 <= start <= 1.0 - frac + 1e-9:
                candidates.add(max(0.0, min(1.0 - frac, start)))

    prefer_left = _unit(f"{seed_key}:side") < 0.5

    def score(f0: float) -> float:
        f1 = f0 + frac
        s = 0.0
        for lo, hi in doors:
            if _edge_cuts(f0, lo, hi) or _edge_cuts(f1, lo, hi):
                s -= 50.0  # half doors read as broken geometry
            elif f0 <= lo + 1e-4 and hi <= f1 + 1e-4:
                s += 8.0
            elif hi <= f0 + 1e-4 or lo >= f1 - 1e-4:
                s += 2.0
        for lo, hi in windows:
            if _edge_cuts(f0, lo, hi) or _edge_cuts(f1, lo, hi):
                s -= 8.0
            elif f0 <= lo + 1e-4 and hi <= f1 + 1e-4:
                s += 2.0
            elif hi <= f0 + 1e-4 or lo >= f1 - 1e-4:
                s += 0.5
        if prefer_left and f0 <= 1e-6:
            s += 0.15
        if not prefer_left and f0 >= 1.0 - frac - 1e-6:
            s += 0.15
        return s

    best = max(candidates, key=lambda f0: (score(f0), -f0 if prefer_left else f0))
    return best, best + frac


def cell_ids() -> list[str]:
    return list(FACADES.keys())


# Back-compat name used by older callers/tests.
facade_ids = cell_ids


def wall_tile_file(tile_id: str) -> str:
    return f"wall_{tile_id}.jpg"


def atlas_size() -> tuple[int, int]:
    rows = (FACADE_COUNT + ATLAS_COLS - 1) // ATLAS_COLS
    return ATLAS_COLS * CELL_W, rows * CELL_H


def cell_origin(cell_id: str) -> tuple[int, int]:
    """Top-left pixel of a cell (including its gutter) inside the atlas."""
    idx = cell_ids().index(cell_id)
    return (idx % ATLAS_COLS) * CELL_W, (idx // ATLAS_COLS) * CELL_H


def cell_pixel_rect(cell_id: str) -> tuple[int, int, int, int]:
    """Inner (gutter-free) pixel rect of a façade: x0, y0, x1, y1, y down."""
    ox, oy = cell_origin(cell_id)
    return ox + PAD, oy + PAD, ox + PAD + CELL_INNER_W, oy + PAD + CELL_INNER_H


def cell_uv_rect(cell_id: str) -> tuple[float, float, float, float]:
    """(u0, v0, u1, v1) in Blender UV space (origin bottom-left, v up)."""
    aw, ah = atlas_size()
    x0, y0, x1, y1 = cell_pixel_rect(cell_id)
    return x0 / aw, 1.0 - y1 / ah, x1 / aw, 1.0 - y0 / ah


def _stable(text: str) -> int:
    return zlib.adler32(text.encode("utf-8")) & 0xFFFFFFFF


def _unit(text: str) -> float:
    """Deterministic pseudo-random in [0, 1)."""
    return (_stable(text) % 10007) / 10007.0


def wall_tile_for_type(type_id: str, types_doc: dict | None = None) -> str:
    if types_doc:
        entry = (types_doc.get("types") or {}).get(type_id) or {}
        tile = entry.get("wall_tile")
        if tile in WALL_TILES:
            return tile
    base = type_id.split("__v")[0]
    return TYPE_WALL_TILE.get(base) or TYPE_WALL_TILE[DEFAULT_TYPE]


def facades_for_type(type_id: str) -> list[str]:
    """Façades tagged for a building type (informational; scoring also uses it)."""
    base = type_id.split("__v")[0]
    return [fid for fid, f in FACADES.items() if base in f["types"]]


def facade_score(
    fid: str, type_id: str, floors: int, rep_len: float, seed_key: str
) -> float:
    """Lower is better: storey mismatch + horizontal stretch - type bonus + jitter."""
    f = FACADES[fid]
    base = type_id.split("__v")[0]
    # With a repeatable storey strip the elevation can grow / shrink by whole storeys, so
    # its own storey count matters much less than its type and plan width.
    banded = fid in band_layout()
    storey_pen = (0.3 if banded else 0.55) * abs(f["storeys"] - max(2, min(5, floors)))
    if not banded:
        # Without a strip the picture is stretched to the eaves: punish big stretches.
        want_m = max(1, floors) * 3.15
        storey_pen += 2.5 * max(0.0, abs(math.log(want_m / f["height_m"])) - 0.25)
    stretch = abs(math.log(max(0.2, rep_len) / f["width_m"]))
    bonus = -0.7 if base in f["types"] else 0.0
    return storey_pen + 1.1 * stretch + bonus + 0.9 * _unit(f"{seed_key}:{fid}")


def pick_facade(
    type_id: str,
    floors: int,
    rep_len: float,
    seed_key: str,
    avoid: tuple[str, ...] = (),
) -> str:
    best = min(
        (fid for fid in FACADES if fid not in avoid) or FACADES,
        key=lambda fid: facade_score(fid, type_id, floors, rep_len, seed_key),
    )
    return best


# Back-compat helper: the façade a whole edge would start with.
def pick_cell(type_id: str, seed: int, types_doc: dict | None = None, floors: int = 4) -> str:
    return pick_facade(type_id, floors, TARGET_HOUSE_M, f"{seed}:{type_id}")


_BAND_DOC: dict[str, Any] | None = None


def band_layout() -> dict[str, Any]:
    """Repeatable storey strip per elevation (``assets/textures/facade_bands.json``), cached.

    ``{facade_id: {"lo": f, "hi": f}}`` where ``lo`` / ``hi`` are heights above the
    elevation's ground as fractions of its height. Rows ``lo`` and ``hi`` of the picture
    match, so the strip can be repeated (or dropped) without a visible seam. Empty when
    the file is missing: the builder then stretches one elevation as before.
    """
    global _BAND_DOC
    if _BAND_DOC is None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "assets" / TEXTURES_DIRNAME / BANDS_FILE
        try:
            _BAND_DOC = json.loads(path.read_text())
        except (OSError, ValueError):
            _BAND_DOC = {}
    return _BAND_DOC


def plan_house_bands(fid: str, eaves_z: float) -> list[dict[str, Any]]:
    """Vertical pieces of ONE house elevation, ground to ``eaves_z``.

    Each piece: ``z0, z1`` (metres), ``v0, v1`` (atlas UV, v up), ``vz`` = the slice of
    the elevation it shows as (from, to) fractions of its height, ``band`` in
    ``ground`` / ``mid`` / ``top``. A single full-height piece (``vz == (0, 1)``) is
    the classic stretch; otherwise ground floor + ``k`` copies of the storey strip +
    top floor and cornice, scaled uniformly so the stack meets the eaves exactly.
    """
    _u0, vb, _u1, vt = cell_uv_rect(fid)
    dv = vt - vb
    whole = {"z0": 0.0, "z1": eaves_z, "v0": vb, "v1": vt, "vz": (0.0, 1.0), "band": "ground"}
    band = band_layout().get(fid)
    if not band:
        return [whole]
    lo, hi = float(band["lo"]), float(band["hi"])
    nat_h = FACADES[fid]["height_m"]
    strip_m = (hi - lo) * nat_h
    if strip_m < 1.2 or not (0.05 < lo < hi < 0.97):
        return [whole]
    k = max(0, int(round((eaves_z - nat_h + strip_m) / strip_m)))
    if k == 1:
        return [whole]
    scale = eaves_z / (nat_h + (k - 1) * strip_m)

    def piece(z0: float, z1: float, f0: float, f1: float, name: str) -> dict[str, Any]:
        return {
            "z0": z0, "z1": z1, "v0": vb + f0 * dv, "v1": vb + f1 * dv, "vz": (f0, f1), "band": name,
        }

    out = [piece(0.0, lo * nat_h * scale, 0.0, lo, "ground")]
    z = out[0]["z1"]
    for _ in range(k):
        out.append(piece(z, z + strip_m * scale, lo, hi, "mid"))
        z += strip_m * scale
    out.append(piece(z, eaves_z, hi, 1.0, "top"))
    out[-1]["z0"] = z
    return out


def plan_facade_quads(
    length: float,
    eaves_z: float,
    floors: int,
    type_id: str,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Cut one street edge into houses; each house = one straight, unmirrored column.

    Quad keys: ``a0, a1`` (metres along the edge from its start), ``z0, z1``
    (metres above ground), ``uv`` = (u0, v0, u1, v1) in atlas UV space (u0 < u1
    always: **no mirroring**), ``cell`` = façade id, ``vz`` / ``band`` = which
    vertical slice of the elevation this quad shows (see ``plan_house_bands``).
    A house is one quad from ground to eaves, or (for storey counts far from the
    elevation's own) a ground piece + repeated storey strips + a top piece, so
    windows stay level with each other and keep their proportions.
    """
    target = TARGET_HOUSE_M if floors < TOWER_LEVELS else TOWER_HOUSE_M
    reps = max(1, int(round(length / target)))
    rep_len = length / reps
    quads: list[dict[str, Any]] = []
    used: list[str] = []
    for ri in range(reps):
        fid = pick_facade(
            type_id, floors, rep_len, f"{seed}:{type_id}:{ri}", avoid=tuple(used[-2:])
        )
        used.append(fid)
        u0, _v0, u1, _v1 = cell_uv_rect(fid)
        width_m = FACADES[fid]["width_m"]
        # Narrow edge: show a slice of the house instead of squeezing it.
        # Align the slice so doors / window bays stay whole (no half-door party walls).
        if reps == 1 and rep_len < width_m * 0.75:
            frac = max(MIN_CROP_FRAC, rep_len / width_m)
            f0, f1 = choose_crop_span(fid, frac, f"{seed}:{fid}")
            span_u = u1 - u0
            u0, u1 = u0 + f0 * span_u, u0 + f1 * span_u
        for piece in plan_house_bands(fid, eaves_z):
            quads.append(
                {
                    "a0": ri * rep_len,
                    "a1": (ri + 1) * rep_len,
                    "z0": piece["z0"],
                    "z1": piece["z1"],
                    "uv": (u0, piece["v0"], u1, piece["v1"]),
                    "cell": fid,
                    "flip": False,
                    "vz": piece["vz"],
                    "band": piece["band"],
                }
            )
    return quads


def ground_quads(quads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One quad per house, the one touching the pavement (doors, awnings, party walls)."""
    return [q for q in quads if q.get("band", "ground") == "ground"]


def door_steps(
    quads: list[dict[str, Any]], rightwards: bool = True, min_edge_frac: float = 0.06
) -> list[dict[str, float]]:
    """Doorstep placements for planned façade quads.

    Returns ``[{"a": metres along the edge from its start, "w": door width in
    metres, "side": 0/1 (which of two stoop styles)}]``. Positions follow the
    image mapping (never mirrored; ``rightwards`` says whether ``u`` grows with
    ``a`` for this edge's orientation), including the cropped slice shown on
    narrow edges.
    """
    out: list[dict[str, float]] = []
    for q in ground_quads(quads):
        door = DOORS.get(q["cell"])
        if not door:
            continue
        centre, width_frac = door
        cu0, _cv0, cu1, _cv1 = cell_uv_rect(q["cell"])
        u0, _v0, u1, _v1 = q["uv"]
        span = cu1 - cu0
        if span <= 0:
            continue
        f0, f1 = (u0 - cu0) / span, (u1 - cu0) / span  # visible slice of the elevation
        if not (f0 + min_edge_frac <= centre <= f1 - min_edge_frac):
            continue  # door is cropped out of view on this narrow edge
        t = (centre - f0) / max(1e-6, f1 - f0)
        # ``rightwards`` False: the quad is drawn with u falling as ``a`` grows.
        a = q["a0"] + (t if rightwards else 1.0 - t) * (q["a1"] - q["a0"])
        # metres per unit of image width on this quad (the slice may be a crop)
        width_m = width_frac * (q["a1"] - q["a0"]) / max(1e-6, f1 - f0)
        out.append({"a": a, "w": width_m, "side": float(_stable(f"{q['cell']}:{q['a0']:.2f}") % 2)})
    return out


_WINDOW_DOC: dict[str, Any] | None = None


def window_layout() -> dict[str, Any]:
    """Detected glass per elevation (``assets/textures/facade_windows.json``), cached.

    ``{facade_id: {"windows": [[x0, x1, z0, z1], ...], "shops": [...]}}`` with every
    coordinate a fraction of the elevation (x from the left, z from the ground). Empty
    when the file has not been generated, so the builder degrades to no extras.
    """
    global _WINDOW_DOC
    if _WINDOW_DOC is None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "assets" / TEXTURES_DIRNAME / WINDOWS_FILE
        try:
            _WINDOW_DOC = json.loads(path.read_text())
        except (OSError, ValueError):
            _WINDOW_DOC = {}
    return _WINDOW_DOC


def _span_on_quad(q: dict[str, Any], lo: float, hi: float, rightwards: bool):
    """Map an x-range of the elevation (fractions) onto a planned quad.

    Returns ``(a_centre, width_m)`` along the edge, honouring the cropped slice of a
    narrow edge and the edge orientation, or ``None`` when the range is cropped out.
    """
    cu0, _cv0, cu1, _cv1 = cell_uv_rect(q["cell"])
    u0, _v0, u1, _v1 = q["uv"]
    span = cu1 - cu0
    if span <= 0:
        return None
    f0, f1 = (u0 - cu0) / span, (u1 - cu0) / span
    lo, hi = max(lo, f0), min(hi, f1)
    if hi <= lo:
        return None
    m_per_f = (q["a1"] - q["a0"]) / max(1e-6, f1 - f0)
    t = ((lo + hi) * 0.5 - f0) / max(1e-6, f1 - f0)
    a = q["a0"] + (t if rightwards else 1.0 - t) * (q["a1"] - q["a0"])
    return a, (hi - lo) * m_per_f


def shop_awnings(
    quads: list[dict[str, Any]], rightwards: bool = True, min_width_m: float = 1.4
) -> list[dict[str, float]]:
    """Awning placements ``[{"a": centre, "w": width, "z": lintel height, "side": 0/1}]``.

    Mirrors ``door_steps``: ``a`` runs along the edge from its start, honouring the
    cropped slice of a narrow edge and the edge orientation. ``z`` is metres above ground.
    Hand-picked ``SHOPS`` plus the wide ground-floor glazing found by ``facade_windows``.
    """
    out: list[dict[str, float]] = []
    doc = window_layout()
    for q in ground_quads(quads):
        vf0, vf1 = q.get("vz", (0.0, 1.0))
        shops: list[tuple[float, float, float]] = []
        if q["cell"] in SHOPS:
            shops.append(SHOPS[q["cell"]])
        else:
            shops.extend((s[0], s[1], s[3]) for s in (doc.get(q["cell"]) or {}).get("shops", []))
        for sx0, sx1, top in shops:
            placed = _span_on_quad(q, sx0, sx1, rightwards)
            if placed is None or placed[1] < min_width_m:
                continue
            a, width_m = placed
            if top > vf1:
                continue  # lintel lies above the ground piece of a stacked tower
            out.append(
                {
                    "a": a,
                    "w": width_m,
                    "z": (top - vf0) / (vf1 - vf0) * (q["z1"] - q["z0"]) + q["z0"],
                    "side": float(_stable(f"{q['cell']}:awn:{q['a0']:.2f}:{sx0:.2f}") % 2),
                }
            )
    return out


def downpipes(
    quads: list[dict[str, Any]],
    eaves_z: float,
    keep_clear: list[tuple[float, float]] | None = None,
    min_gap_m: float = 5.0,
) -> list[dict[str, float]]:
    """Rainwater downpipe placements ``[{"a": along edge, "z1": top height}]`` (metres).

    Pipes sit on party-wall joints between neighbouring houses (never mid-elevation,
    where they would cut a window), skip any joint inside a ``keep_clear`` span
    (doors / shop glazing, ``(a_centre, width)``), and are thinned to one every
    ``min_gap_m`` so long terraces read as paired houses sharing a pipe.
    """
    clear = keep_clear or []
    out: list[dict[str, float]] = []
    last = -1e9
    ground = ground_quads(quads)
    for left, right in zip(ground, ground[1:]):
        a = 0.5 * (left["a1"] + right["a0"])
        if a - last < min_gap_m:
            continue
        if any(abs(a - c) < w * 0.5 + 0.25 for c, w in clear):
            continue
        out.append({"a": a, "z1": eaves_z - 0.15})
        last = a
    return out


def window_reveals(
    quads: list[dict[str, Any]], rightwards: bool = True, min_width_m: float = 0.5
) -> list[dict[str, float]]:
    """Window placements ``[{"a": centre, "w": glass width, "z0": sill, "z1": head}]`` (metres).

    Same mapping as ``door_steps`` / ``shop_awnings``; windows cropped by a narrow edge
    (only partly visible) are skipped so no sill ever dangles past the wall.
    """
    out: list[dict[str, float]] = []
    doc = window_layout()
    for q in quads:
        height = q["z1"] - q["z0"]
        vf0, vf1 = q.get("vz", (0.0, 1.0))
        cu0, _cv0, cu1, _cv1 = cell_uv_rect(q["cell"])
        u0, _v0, u1, _v1 = q["uv"]
        span = cu1 - cu0
        if span <= 0:
            continue
        f0, f1 = (u0 - cu0) / span, (u1 - cu0) / span
        for x0, x1, z0, z1 in (doc.get(q["cell"]) or {}).get("windows", []):
            if x0 < f0 + 0.005 or x1 > f1 - 0.005:
                continue  # cut by the crop
            placed = _span_on_quad(q, x0, x1, rightwards)
            if placed is None or placed[1] < min_width_m:
                continue
            if z0 < vf0 - 1e-6 or z1 > vf1 + 1e-6:
                continue  # glass belongs to another piece of the stack (or straddles a seam)
            span_z = max(1e-6, vf1 - vf0)
            out.append(
                {
                    "a": placed[0],
                    "w": placed[1],
                    "z0": q["z0"] + (z0 - vf0) / span_z * height,
                    "z1": q["z0"] + (z1 - vf0) / span_z * height,
                }
            )
    return out


def annotate_types_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Record the generated façade kit in building_types.json."""
    doc["facade_kit"] = {
        "atlas": f"{TEXTURES_DIRNAME}/{ATLAS_FILE}",
        "count": FACADE_COUNT,
        "mapping": "one straight unmirrored elevation per house; terrace along the edge",
        "facades": {
            fid: {
                "source": f"{FACADE_SRC_DIR}/{f['file']}",
                "storeys": f["storeys"],
                "width_m": f["width_m"],
                "types": f["types"],
            }
            for fid, f in FACADES.items()
        },
        "wall_tiles": {
            tid: {
                "source": f"{WALL_SRC_DIR}/{t['src']}",
                "file": f"{TEXTURES_DIRNAME}/{wall_tile_file(tid)}",
                "tile_m": t["tile_m"],
            }
            for tid, t in WALL_TILES.items()
        },
    }
    for type_id, entry in (doc.get("types") or {}).items():
        entry["facade_cells"] = facades_for_type(type_id)
        entry["wall_tile"] = wall_tile_for_type(type_id)
    return doc
