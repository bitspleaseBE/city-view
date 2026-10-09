"""Merged garden walls, hedges and fences from OSM ``barrier=*`` ways (runs inside Blender).

``layout["barriers"]`` (see ``cityview.barriers``) lists straight, already-visibility-trimmed
runs. Each surface becomes one mesh (a handful of draw calls for the whole tile): walls get a
slightly wider coping slab, hedges taper to a rounded-looking top, fences are posts + two rails.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from cityview import barriers  # noqa: E402

Z_BASE = -0.12  # just under the pavement / yard so the foot never floats
COPING_H = 0.05
COPING_OVER = 0.04  # coping overhang per side
POST_PITCH_M = 2.0
POST_W = 0.06
RAIL_W = 0.03
HEDGE_TOP_RATIO = 0.72
MAX_FENCE_POSTS = 600  # sanity cap per run list


def _prism(bm, a: Vector, b: Vector, z0: float, z1: float, w_bot: float, w_top: float | None = None) -> None:
    """Closed tapered box along a->b (XY), ``w_bot`` / ``w_top`` wide, from z0 to z1."""
    d = b - a
    d.z = 0.0
    if d.length < 1e-6:
        return
    d.normalize()
    n = Vector((-d.y, d.x, 0.0))
    wt = w_bot if w_top is None else w_top
    vs = []
    for z, w in ((z0, w_bot), (z1, wt)):
        for p in (a, b):
            for s in (-0.5, 0.5):
                vs.append(bm.verts.new((p.x + n.x * w * s, p.y + n.y * w * s, z)))
    # index = level*4 + end*2 + side
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    for f in faces:
        try:
            bm.faces.new([vs[i] for i in f])
        except ValueError:
            pass


def _wall(parts: dict, run: dict, a: Vector, b: Vector, kind: str) -> None:
    bm = parts.setdefault(run["surface"], bmesh.new())
    h = float(run["h"])
    t = barriers.THICKNESS[kind]
    _prism(bm, a, b, Z_BASE, Z_BASE + h + 0.12, t)
    cop = parts.setdefault("coping", bmesh.new())
    _prism(cop, a, b, Z_BASE + h + 0.12, Z_BASE + h + 0.12 + COPING_H, t + 2 * COPING_OVER)


def _hedge(parts: dict, run: dict, a: Vector, b: Vector) -> None:
    bm = parts.setdefault("hedge", bmesh.new())
    t = barriers.THICKNESS["hedge"]
    h = float(run["h"])
    _prism(bm, a, b, Z_BASE, Z_BASE + h * 0.82 + 0.12, t, t * 0.95)  # trunk-to-shoulder
    _prism(bm, a, b, Z_BASE + h * 0.82, Z_BASE + h + 0.12, t * 0.95, t * HEDGE_TOP_RATIO)  # clipped top


def _fence(parts: dict, run: dict, a: Vector, b: Vector, budget: list[int]) -> None:
    bm = parts.setdefault("metal", bmesh.new())
    h = float(run["h"])
    length = (b - a).length
    n = max(1, int(math.ceil(length / POST_PITCH_M)))
    for i in range(n + 1):
        if budget[0] <= 0:
            break
        p = a.lerp(b, i / n)
        _prism(bm, p - Vector((POST_W / 2, 0, 0)), p + Vector((POST_W / 2, 0, 0)), Z_BASE, Z_BASE + h, POST_W)
        budget[0] -= 1
    for frac in (0.3, 0.85):
        _prism(bm, a, b, Z_BASE + h * frac, Z_BASE + h * frac + RAIL_W, RAIL_W)


def add_barriers(layout: dict, rails, mats: dict) -> dict:
    """Create merged barrier meshes. ``mats`` maps surface keys to materials."""
    parts: dict[str, bmesh.types.BMesh] = {}
    counts: dict[str, int] = {"skipped_rail": 0}
    budget = [MAX_FENCE_POSTS]
    for run in layout.get("barriers") or []:
        a = Vector((float(run["x0"]), float(run["y0"]), 0.0))
        b = Vector((float(run["x1"]), float(run["y1"]), 0.0))
        mx, my = (a.x + b.x) * 0.5, (a.y + b.y) * 0.5
        if rails.within(mx, my, 0.5):
            counts["skipped_rail"] += 1
            continue
        kind = run["kind"]
        if kind in {"wall", "retaining"}:
            _wall(parts, run, a, b, kind)
        elif kind == "hedge":
            _hedge(parts, run, a, b)
        elif kind == "fence":
            _fence(parts, run, a, b, budget)
        else:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    for key, bm in parts.items():
        if not bm.verts or key not in mats:
            bm.free()
            continue
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        mesh = bpy.data.meshes.new(f"barrier_{key}")
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mats[key])
        bpy.context.collection.objects.link(bpy.data.objects.new(f"barrier_{key}", mesh))
    counts["total"] = sum(v for k, v in counts.items() if k != "skipped_rail")
    return counts
