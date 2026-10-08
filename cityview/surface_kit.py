"""Procedural surface textures (roofs, paving, grass, asphalt): names + real-world scale.

Pure Python (no bpy / Pillow / numpy) so the Blender builder and the unit tests can
share the table; ``cityview/surface_textures.py`` renders the actual images into
``assets/surfaces/`` (committed, so CI only needs Blender).
"""

from __future__ import annotations

import zlib

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

# Pantile / slate mix per roof family (cumulative weights out of 100).
# Mansards are slate or zinc; gables/hips lean towards red clay pantiles.
ROOF_MIX: dict[str, list[tuple[str, int]]] = {
    "mansard": [("roof_slate", 62), ("roof_zinc", 28), ("roof_clay", 10)],
    "gable": [("roof_clay", 52), ("roof_slate", 40), ("roof_zinc", 8)],
    "hip": [("roof_clay", 50), ("roof_slate", 42), ("roof_zinc", 8)],
    "flat": [("roof_flat", 100)],
}


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
