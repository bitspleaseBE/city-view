"""Procedural surface textures (roofs, paving, grass, asphalt): names + real-world scale.

Pure Python (no bpy / Pillow / numpy) so the Blender builder and the unit tests can
share the table; ``cityview/surface_textures.py`` renders the actual images into
``assets/surfaces/`` (committed, so CI only needs Blender).
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

ROOF_AERIAL_PATH = Path(__file__).resolve().parent.parent / "assets" / "styles" / "roof_aerial.json"

TEXTURES_DIRNAME = "surfaces"  # assets/surfaces/ (kept apart from the photo façade kit in assets/textures/)

# tile_m = metres covered by one texture repeat (UVs are world-metres / tile_m).
SURFACES: dict[str, dict] = {
    # Roofs — Antwerp skyline is mostly slate mansards + red/brown Flemish pantiles.
    "roof_slate": {"file": "roof_slate.jpg", "tile_m": 2.4},
    "roof_clay": {"file": "roof_clay.jpg", "tile_m": 2.4},
    "roof_zinc": {"file": "roof_zinc.jpg", "tile_m": 2.4},
    "roof_flat": {"file": "roof_flat.jpg", "tile_m": 3.0},
    # Ground
    "sidewalk": {"file": "sidewalk_slabs.jpg", "tile_m": 2.4},
    "asphalt": {"file": "asphalt.jpg", "tile_m": 4.0},
    "grass": {"file": "park_grass.jpg", "tile_m": 8.0},
    "curb": {"file": "curb_granite.jpg", "tile_m": 1.6},
    "gravel": {"file": "courtyard_gravel.jpg", "tile_m": 3.0},
}

# Roof family mix per roof shape (cumulative weights out of 100). Measured from the
# Digitaal Vlaanderen winter-2025 orthophoto (cityview/aerial.py -> roof_aerial.json
# ``mix_by_shape``): Harmonie is overwhelmingly grey (slate / zinc / fibre-cement / bitumen)
# with red clay pantiles on only ~7 % of the pitched roofs. This table is only the
# fallback for buildings the aerial sampling did not cover; sampled buildings use
# their own measured family + tint (see ``roof_choice``).
ROOF_MIX: dict[str, list[tuple[str, int]]] = {
    "mansard": [("roof_slate", 35), ("roof_zinc", 58), ("roof_clay", 7)],
    "gable": [("roof_slate", 37), ("roof_zinc", 54), ("roof_clay", 9)],
    "hip": [("roof_slate", 37), ("roof_zinc", 54), ("roof_clay", 9)],
    "flat": [("roof_flat", 100)],
}


def load_roof_aerial(path: Path | None = None) -> dict | None:
    """Per-building roof families + tint clusters sampled from the aerial (None if absent)."""
    p = path or ROOF_AERIAL_PATH
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def roof_choice(doc: dict | None, building_id, shape: str) -> tuple[str, int] | None:
    """(surface key, tint cluster index) measured from the aerial for one OSM building.

    ``None`` when the building was not sampled, or when the sampled family cannot
    apply to the current roof shape (a flat membrane on a pitched roof and vice versa).
    """
    if not doc:
        return None
    entry = (doc.get("buildings") or {}).get(str(building_id))
    if not entry:
        return None
    classes = list(doc.get("classes") or [])
    try:
        key = classes[entry[0]]
    except IndexError:
        return None
    if (key == "roof_flat") != (shape == "flat"):
        return None
    clusters = ((doc.get("families") or {}).get(key) or {}).get("clusters") or []
    if not 0 <= entry[1] < len(clusters):
        return None
    return key, int(entry[1])


def pick_roof_cluster(doc: dict | None, key: str, seed: int) -> int:
    """Tint cluster for an unsampled building: weighted by how common each cluster is."""
    clusters = (((doc or {}).get("families") or {}).get(key) or {}).get("clusters") or []
    total = sum(int(c.get("count", 1)) for c in clusters)
    if not total:
        return 0
    roll = zlib.crc32(f"rc:{seed}".encode()) % total
    acc = 0
    for i, c in enumerate(clusters):
        acc += int(c.get("count", 1))
        if roll < acc:
            return i
    return len(clusters) - 1


def surface_file(key: str) -> str:
    return SURFACES[key]["file"]


def surface_tile_m(key: str) -> float:
    return float(SURFACES[key]["tile_m"])


def pick_roof_surface(shape: str, seed: int) -> str:
    """Deterministic roof material for a building (same seed -> same roof everywhere)."""
    mix = ROOF_MIX.get(shape) or ROOF_MIX["mansard"]
    roll = zlib.crc32(f"roof:{seed}".encode()) % 100
    acc = 0
    for key, weight in mix:
        acc += weight
        if roll < acc:
            return key
    return mix[-1][0]
