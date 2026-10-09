"""Merged courtyard ground surfaces from OSM areas (runs inside Blender).

``layout["courtyards"]`` (see ``cityview.courtyards``) lists flat counter-clockwise rings tagged
with a drawn surface and a layer. Every surface becomes one mesh (a handful of draw calls for the
whole tile). Layers are millimetres apart and all sit below the road carriageway, so a car park
that spills onto a street is simply overdrawn by the street.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bmesh
import bpy

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from cityview import courtyards  # noqa: E402,F401

# Above the park plane (0.00) and below the road (0.04) / pavement / tram bed.
LAYER_Z = {"earth": 0.008, "grass": 0.014, "paving": 0.020, "sport": 0.026, "water": 0.032}


def _fill(bm, ring: list[list[float]], z: float, tile_m: float | None) -> int:
    """Triangle-fill one ring at height ``z``; returns the number of faces added."""
    verts = [bm.verts.new((p[0], p[1], z)) for p in ring]
    edges = []
    for i, v in enumerate(verts):
        try:
            edges.append(bm.edges.new((v, verts[(i + 1) % len(verts)])))
        except ValueError:
            pass
    filled = bmesh.ops.triangle_fill(bm, use_beauty=True, edges=edges)
    faces = [g for g in filled.get("geom", []) if isinstance(g, bmesh.types.BMFace)]
    uv = bm.loops.layers.uv.verify()
    for f in faces:
        if f.normal.z < 0:
            f.normal_flip()
        for loop in f.loops:
            x, y = loop.vert.co.x, loop.vert.co.y
            loop[uv].uv = (x / tile_m, y / tile_m) if tile_m else (0.0, 0.0)
    return len(faces)


def add_courtyards(layout: dict, mats: dict, tiles: dict) -> dict:
    """Create one merged mesh per surface. ``mats`` / ``tiles`` map surface keys to material / tile metres."""
    parts: dict[str, bmesh.types.BMesh] = {}
    counts: dict[str, int] = {"faces": 0, "areas": 0}
    for area in layout.get("courtyards") or []:
        surface = area["surface"]
        if surface not in mats:
            continue
        z = LAYER_Z.get(area.get("layer", "paving"), LAYER_Z["paving"])
        bm = parts.setdefault(surface, bmesh.new())
        n = _fill(bm, area["ring"], z, tiles.get(surface))
        if n:
            counts["faces"] += n
            counts["areas"] += 1
            counts[surface] = counts.get(surface, 0) + 1
    for key, bm in parts.items():
        if not bm.faces:
            bm.free()
            continue
        mesh = bpy.data.meshes.new(f"courtyard_{key}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mats[key])
        bpy.context.collection.objects.link(bpy.data.objects.new(f"courtyard_{key}", mesh))
    return counts
