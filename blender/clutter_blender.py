"""Merged street clutter from OSM-surveyed points (runs inside Blender).

``layout["clutter"]`` (see ``cityview.clutter``) lists bins, bike hoops, bollards, hydrants,
post boxes, recycling bring-sites, street cabinets, ticket machines, flagpoles and lamps at
their mapped positions. Object convention: front on local +Y, ``yaw`` is ``rotation_z``.
Everything is merged into one mesh per material (a handful of draw calls for the lot).
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
from cityview.clutter import HOOP_SPACING_M  # noqa: E402
from cityview.railclear import CLEAR_FURNITURE  # noqa: E402

LIFT = 0.06  # pavement / asphalt top: objects stand on it instead of sinking into it


class Parts:
    """One bmesh per material name."""

    def __init__(self) -> None:
        self.meshes: dict[str, bmesh.types.BMesh] = {}

    def bm(self, key: str):
        if key not in self.meshes:
            self.meshes[key] = bmesh.new()
        return self.meshes[key]

    def box(self, key: str, base: Matrix, size, center) -> None:
        m = base @ Matrix.Translation(Vector(center)) @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
        bmesh.ops.create_cube(self.bm(key), size=1.0, matrix=m)

    def cyl(self, key: str, base: Matrix, radius: float, height: float, center, r_top: float | None = None, segs: int = 10) -> None:
        m = base @ Matrix.Translation(Vector(center))
        bmesh.ops.create_cone(
            self.bm(key),
            cap_ends=True,
            cap_tris=False,
            segments=segs,
            radius1=radius,
            radius2=radius if r_top is None else r_top,
            depth=height,
            matrix=m,
        )


def _bin(p: Parts, b: Matrix) -> None:
    p.cyl("bin", b, 0.2, 0.8, (0, 0, 0.4), r_top=0.22)
    p.cyl("metal", b, 0.23, 0.05, (0, 0, 0.82))  # lid ring


def _bike_rack(p: Parts, b: Matrix, hoops: int) -> None:
    for i in range(hoops):
        cx = (i - (hoops - 1) * 0.5) * HOOP_SPACING_M
        for sx in (-0.3, 0.3):
            p.box("metal", b, (0.04, 0.04, 0.78), (cx + sx, 0, 0.39))
        p.box("metal", b, (0.64, 0.04, 0.04), (cx, 0, 0.78))  # inverted-U crown


def _bollard(p: Parts, b: Matrix) -> None:
    p.cyl("metal", b, 0.07, 0.85, (0, 0, 0.425), segs=8)
    p.cyl("signal_white", b, 0.072, 0.07, (0, 0, 0.7), segs=8)  # reflective band


def _hydrant(p: Parts, b: Matrix) -> None:
    p.cyl("signal_red", b, 0.1, 0.62, (0, 0, 0.31), r_top=0.085, segs=8)
    p.cyl("signal_red", b, 0.12, 0.08, (0, 0, 0.66), segs=8)
    p.box("signal_red", b, (0.34, 0.1, 0.1), (0, 0, 0.45))  # side nozzles
    p.box("metal", b, (0.1, 0.1, 0.06), (0, 0, 0.72))  # operating nut


def _post_box(p: Parts, b: Matrix) -> None:
    p.box("signal_red", b, (0.46, 0.34, 1.0), (0, 0, 0.55))
    p.cyl("signal_red", b, 0.17, 0.46, (0, 0, 1.05), segs=10)
    p.box("metal", b, (0.28, 0.02, 0.05), (0, 0.17, 0.95))  # letter slot


def _recycling(p: Parts, b: Matrix, bins: int) -> None:
    for i in range(bins):
        cx = (i - (bins - 1) * 0.5) * 1.3
        key = ("container_green", "container_blue", "container_white")[i % 3]
        p.box(key, b, (1.15, 1.15, 1.5), (cx, 0, 0.75 + 0.1))
        p.box("metal", b, (0.3, 0.3, 0.1), (cx, 0.0, 1.62))  # drop-in hood


def _cabinet(p: Parts, b: Matrix) -> None:
    p.box("cabinet", b, (0.9, 0.38, 1.25), (0, 0, 0.7))
    p.box("metal", b, (0.94, 0.42, 0.05), (0, 0, 1.35))  # roof lip
    p.box("metal", b, (0.9, 0.38, 0.12), (0, 0, 0.06))  # plinth


def _meter(p: Parts, b: Matrix) -> None:
    p.cyl("metal", b, 0.04, 1.4, (0, 0, 0.7), segs=6)
    p.box("meter_blue", b, (0.32, 0.22, 0.45), (0, 0, 1.45))
    p.box("signal_white", b, (0.22, 0.01, 0.1), (0, 0.115, 1.58))  # P-sign / screen


def _flagpole(p: Parts, b: Matrix) -> None:
    p.cyl("metal", b, 0.05, 7.0, (0, 0, 3.5), r_top=0.03, segs=6)
    p.cyl("metal", b, 0.06, 0.12, (0, 0, 7.05), segs=6)


def _lamp(p: Parts, b: Matrix) -> None:
    p.cyl("metal", b, 0.06, 5.0, (0, 0, 2.5), r_top=0.045, segs=8)
    p.box("metal", b, (0.06, 1.0, 0.06), (0, 0.5, 4.95))  # arm over the carriageway
    p.box("lamp_head", b, (0.34, 0.6, 0.14), (0, 1.0, 4.88))


def add_clutter(layout: dict, rails, mats: dict) -> dict:
    """Create merged clutter meshes. ``mats`` maps part keys to materials."""
    parts = Parts()
    counts: dict[str, int] = {"skipped_rail": 0}
    for rec in layout.get("clutter") or []:
        x, y = float(rec["x"]), float(rec["y"])
        if rails.within(x, y, CLEAR_FURNITURE) and rec["kind"] not in {"flagpole"}:
            counts["skipped_rail"] += 1
            continue
        b = Matrix.Translation(Vector((x, y, LIFT))) @ Matrix.Rotation(float(rec["yaw"]), 4, "Z")
        kind = rec["kind"]
        if kind == "bin":
            _bin(parts, b)
        elif kind == "bike_rack":
            _bike_rack(parts, b, int(rec.get("hoops") or 2))
        elif kind == "bollard":
            _bollard(parts, b)
        elif kind == "hydrant":
            _hydrant(parts, b)
        elif kind == "post_box":
            _post_box(parts, b)
        elif kind == "recycling":
            _recycling(parts, b, int(rec.get("bins") or 3))
        elif kind == "cabinet":
            _cabinet(parts, b)
        elif kind == "meter":
            _meter(parts, b)
        elif kind == "flagpole":
            _flagpole(parts, b)
        elif kind == "lamp":
            _lamp(parts, b)
        else:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    for key, bm in parts.meshes.items():
        if not bm.verts or key not in mats:
            bm.free()
            continue
        mesh = bpy.data.meshes.new(f"clutter_{key}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mats[key])
        obj = bpy.data.objects.new(f"clutter_{key}", mesh)
        bpy.context.collection.objects.link(obj)
    counts["total"] = sum(v for k, v in counts.items() if k != "skipped_rail")
    return counts
