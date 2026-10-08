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
    (4, "tall", ("neoclassical", "cream-tile")),             # 03
    (5, "tall", ("yellow-brick", "art-nouveau")),            # 04
    (3, "wide", ("neo-flemish", "brown-tile")),              # 05
    (4, "tall", ("neo-flemish", "red-brick")),               # 06
    (4, "tall", ("art-nouveau",)),                           # 07
    (3, "wide", ("neoclassical", "antwerp-70s")),            # 08
    (5, "tall", ("eclectic",)),                              # 09
    (4, "tall", ("neo-flemish", "eclectic")),                # 10
    (3, "wide", ("prefab-70s", "brown-tile")),               # 11
    (4, "tall", ("art-deco",)),                              # 12
    (3, "wide", ("cream-tile", "neoclassical")),             # 13
    (4, "tall", ("red-brick",)),                             # 14
    (5, "tall", ("eclectic", "cream-tile")),                 # 15
    (4, "tall", ("art-nouveau",)),                           # 16
    (3, "wide", ("red-brick",)),                             # 17
    (4, "tall", ("neoclassical",)),                          # 18
    (3, "wide", ("eclectic", "white-modern")),               # 19
    (4, "tall", ("neo-gothic", "neo-flemish")),              # 20
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
    (3, "wide", ("modern-infill", "white-modern")),          # 31
    (4, "tall", ("yellow-brick", "art-nouveau")),            # 32
    (3, "wide", ("brown-tile", "neo-flemish")),              # 33
    (5, "tall", ("eclectic", "international")),              # 34
    (4, "tall", ("neo-flemish",)),                           # 35
    (3, "wide", ("art-deco", "white-modern")),               # 36
    (4, "tall", ("eclectic", "neoclassical")),               # 37
    (3, "wide", ("red-brick", "antwerp-70s")),               # 38
    (5, "tall", ("neoclassical", "eclectic")),               # 39
    (4, "tall", ("brown-tile", "art-nouveau")),              # 40
    (3, "wide", ("yellow-brick",)),                          # 41
    (4, "tall", ("art-nouveau",)),                           # 42
    (3, "wide", ("cream-tile",)),                            # 43
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
    "facade_10": (0.28, 0.15), "facade_13": (0.80, 0.13), "facade_17": (0.62, 0.15),
    "facade_19": (0.78, 0.15), "facade_20": (0.62, 0.15), "facade_21": (0.10, 0.12),
    "facade_22": (0.52, 0.10), "facade_23": (0.38, 0.13), "facade_24": (0.23, 0.15),
    "facade_25": (0.64, 0.16), "facade_26": (0.27, 0.17), "facade_27": (0.65, 0.12),
    "facade_28": (0.47, 0.10), "facade_30": (0.63, 0.12), "facade_31": (0.77, 0.10),
    "facade_32": (0.50, 0.14), "facade_33": (0.30, 0.14), "facade_34": (0.62, 0.15),
    "facade_35": (0.70, 0.15), "facade_36": (0.78, 0.12), "facade_37": (0.50, 0.15),
    "facade_39": (0.56, 0.14), "facade_40": (0.55, 0.13), "facade_41": (0.63, 0.10),
    "facade_42": (0.20, 0.14), "facade_43": (0.55, 0.12), "facade_44": (0.58, 0.14),
    "facade_45": (0.78, 0.15), "facade_46": (0.78, 0.12), "facade_47": (0.45, 0.14),
    "facade_48": (0.20, 0.12), "facade_49": (0.50, 0.14), "facade_50": (0.92, 0.12),
}

# Terrace width target: a long edge is cut into houses about this wide.
TARGET_HOUSE_M = 6.4
MIN_CROP_FRAC = 0.5


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
    storey_pen = 0.55 * abs(f["storeys"] - max(2, min(5, floors)))
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


def plan_facade_quads(
    length: float,
    eaves_z: float,
    floors: int,
    type_id: str,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Cut one street edge into houses; each house = one straight, unmirrored quad.

    Quad keys: ``a0, a1`` (metres along the edge from its start), ``z0, z1``
    (metres above ground), ``uv`` = (u0, v0, u1, v1) in atlas UV space (u0 < u1
    always: **no mirroring**), ``cell`` = façade id. The whole elevation spans
    ground to eaves in one piece, so windows stay level with each other.
    """
    reps = max(1, int(round(length / TARGET_HOUSE_M)))
    rep_len = length / reps
    quads: list[dict[str, Any]] = []
    used: list[str] = []
    for ri in range(reps):
        fid = pick_facade(
            type_id, floors, rep_len, f"{seed}:{type_id}:{ri}", avoid=tuple(used[-2:])
        )
        used.append(fid)
        u0, v0, u1, v1 = cell_uv_rect(fid)
        width_m = FACADES[fid]["width_m"]
        # Narrow edge: show a slice of the house instead of squeezing it.
        if reps == 1 and rep_len < width_m * 0.75:
            frac = max(MIN_CROP_FRAC, rep_len / width_m)
            span = (u1 - u0) * frac
            if _unit(f"{seed}:{fid}:side") < 0.5:
                u1 = u0 + span
            else:
                u0 = u1 - span
        quads.append(
            {
                "a0": ri * rep_len,
                "a1": (ri + 1) * rep_len,
                "z0": 0.0,
                "z1": eaves_z,
                "uv": (u0, v0, u1, v1),
                "cell": fid,
                "flip": False,
            }
        )
    return quads


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
    for q in quads:
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
