"""Batched park / street benches from surveyed positions (runs inside Blender).

Positions, facing and backrest flags come from ``layout["benches"]`` (see
``cityview.benches``): OSM ``amenity=bench`` + the Stad Antwerpen park-furniture
inventory, each with a surveyed or rule-derived facing. Bench mesh convention: length
on local X, backrest on local +Y, seat looking toward local -Y, so ``yaw`` is exactly
``rotation_z`` as produced by ``cityview.benches.facing_to_yaw``.

Everything is merged into one mesh per material (a few draw calls for ~100+ benches).
"""

from __future__ import annotations

import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from cityview import benches as benchplan  # noqa: E402
from cityview.railclear import CLEAR_FURNITURE  # noqa: E402

SEAT_Z = 0.43
SEAT_DEPTH = 0.46
SEAT_THICK = 0.07
LEG_W = 0.07
BACK_THICK = 0.05
BACK_H = 0.42


def _box(bm, base: Matrix, size, center) -> None:
    """Axis-aligned box in the bench's local frame, then moved into the world."""
    m = base @ Matrix.Translation(Vector(center)) @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


def add_benches(layout: dict, rails, wood_mat, metal_mat) -> dict:
    """Create merged bench meshes. Returns per-source / per-rule counts."""
    origin = tuple(layout.get("origin") or (0.0, 0.0))
    if "benches" not in layout:  # layout predates bench planning: OSM + fallback only
        plan = benchplan.plan_benches(layout, benchplan.osm_benches(None), None, origin)
        layout["benches"], layout["bench_stats"] = plan["benches"], plan["stats"]

    wood = bmesh.new()
    metal = bmesh.new()
    counts = {"osm": 0, "antwerp": 0, "stop": 0, "fallback": 0, "skipped_rail": 0}
    for bench in layout.get("benches") or []:
        x, y = float(bench["x"]), float(bench["y"])
        if rails.within(x, y, CLEAR_FURNITURE):
            counts["skipped_rail"] += 1  # safety net: nothing sits on a tram bed
            continue
        length = float(bench.get("length") or 1.7)
        base = Matrix.Translation(Vector((x, y, 0.0))) @ Matrix.Rotation(float(bench["yaw"]), 4, "Z")
        _box(wood, base, (length, SEAT_DEPTH, SEAT_THICK), (0.0, 0.0, SEAT_Z))
        if bench.get("backrest", True):
            # Backrest on the +Y edge, leaning back slightly via a raised, thin board.
            _box(
                wood,
                base,
                (length, BACK_THICK, BACK_H),
                (0.0, SEAT_DEPTH * 0.5 - BACK_THICK * 0.5, SEAT_Z + SEAT_THICK * 0.5 + BACK_H * 0.5 + 0.04),
            )
        for sx in (-1.0, 1.0):
            _box(
                metal,
                base,
                (LEG_W, SEAT_DEPTH * 0.9, SEAT_Z - SEAT_THICK * 0.5),
                (sx * (length * 0.5 - 0.14), 0.0, (SEAT_Z - SEAT_THICK * 0.5) * 0.5),
            )
        counts[bench.get("source") or "osm"] = counts.get(bench.get("source") or "osm", 0) + 1

    for name, mat, bm in (("benches_wood", wood_mat, wood), ("benches_metal", metal_mat, metal)):
        if not bm.verts:
            bm.free()
            continue
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
    counts["total"] = sum(counts[k] for k in ("osm", "antwerp", "stop", "fallback"))
    return counts
