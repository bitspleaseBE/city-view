"""Merged manhole covers and gully grates on the carriageway (runs inside Blender).

Plan comes from ``cityview.roadware``. Two materials -> two meshes: a dark cast-iron
plate and a lighter worn-edge ring / grate bars, so the covers read from eye height
without any texture.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from cityview import roadware  # noqa: E402
from cityview.railclear import CLEAR_MARKING  # noqa: E402

ROAD_TOP = 0.05  # asphalt surface (+ a hair, no z-fighting)


def _cyl(bm, base: Matrix, r: float, h: float, z: float, segs: int = 16) -> None:
    bmesh.ops.create_cone(
        bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r, radius2=r, depth=h,
        matrix=base @ Matrix.Translation(Vector((0, 0, z))),
    )


def _box(bm, base: Matrix, size, center) -> None:
    m = base @ Matrix.Translation(Vector(center)) @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


def _manhole(iron, edge, b: Matrix) -> None:
    _cyl(edge, b, roadware.MANHOLE_R + 0.05, 0.014, 0.007)  # worn frame ring
    _cyl(iron, b, roadware.MANHOLE_R, 0.022, 0.011)  # cover
    for dx in (-0.16, 0.0, 0.16):  # raised pattern bars
        _box(edge, b, (0.04, 0.46, 0.008), (dx, 0, 0.024))


def _gully(iron, edge, b: Matrix) -> None:
    _box(edge, b, (roadware.GULLY_L + 0.08, roadware.GULLY_W + 0.08, 0.014), (0, 0, 0.007))  # frame
    _box(iron, b, (roadware.GULLY_L, roadware.GULLY_W, 0.022), (0, 0, 0.011))  # slotted plate
    for i in range(5):  # slots read as bars across the grate
        _box(edge, b, (0.03, roadware.GULLY_W - 0.06, 0.008), ((i - 2) * 0.09, 0, 0.024))


def add_roadware(layout: dict, spawn_xy, rails, iron_mat, edge_mat) -> dict:
    plan = roadware.plan_roadware(layout.get("roads") or [], spawn_xy)
    iron, edge = bmesh.new(), bmesh.new()
    counts = {"skipped_rail": 0}
    for it in plan:
        if rails.within(it["x"], it["y"], CLEAR_MARKING):
            counts["skipped_rail"] += 1
            continue
        b = Matrix.Translation(Vector((it["x"], it["y"], ROAD_TOP))) @ Matrix.Rotation(it["yaw"], 4, "Z")
        (_manhole if it["kind"] == "manhole" else _gully)(iron, edge, b)
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    for name, bm, mat in (("roadware_iron", iron, iron_mat), ("roadware_edge", edge, edge_mat)):
        if bm.verts:
            mesh = bpy.data.meshes.new(name)
            bm.to_mesh(mesh)
            mesh.materials.append(mat)
            bpy.context.collection.objects.link(bpy.data.objects.new(name, mesh))
        bm.free()
    counts["total"] = sum(v for k, v in counts.items() if k != "skipped_rail")
    return counts
