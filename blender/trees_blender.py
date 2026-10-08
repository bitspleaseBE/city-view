"""Batched low-poly trees and shrubs for the city tile (runs inside Blender).

Positions come from ``layout["trees"]`` / ``layout["bushes"]`` (see
``cityview.trees``): real municipal + OSM survey points, with a Poisson-disc
fill only in sparse parks. Everything is merged into one mesh per material so
~1k trees cost a handful of draw calls in the browser viewer.
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
from cityview import trees as treeplan  # noqa: E402

# Genus → canopy palette slot (indices into canopy_mats); others use per-tree tone.
GENUS_CANOPY = {
    "Platanus": 3,
    "Tilia": 3,
    "Prunus": 3,
    "Malus": 3,
    "Pyrus": 3,
    "Fagus": 2,
    "Quercus": 2,
    "Carpinus": 4,
    "Acer": 0,
    "Aesculus": 1,
    "Fraxinus": 1,
}


class _Batch:
    """Accumulates primitives into one bmesh per material."""

    def __init__(self) -> None:
        self.meshes: dict[str, tuple[object, bmesh.types.BMesh]] = {}

    def bm(self, mat) -> bmesh.types.BMesh:
        key = mat.name
        if key not in self.meshes:
            self.meshes[key] = (mat, bmesh.new())
        return self.meshes[key][1]

    def blob(self, mat, center, radii, yaw: float = 0.0, subdiv: int = 1) -> None:
        m = Matrix.Translation(Vector(center)) @ Matrix.Rotation(yaw, 4, "Z")
        m = m @ Matrix.Diagonal(Vector((radii[0], radii[1], radii[2], 1.0)))
        bmesh.ops.create_icosphere(self.bm(mat), subdivisions=subdiv, radius=1.0, matrix=m)

    def cone(self, mat, base, r_bottom: float, r_top: float, depth: float, segments: int = 7) -> None:
        m = Matrix.Translation(Vector((base[0], base[1], base[2] + depth * 0.5)))
        bmesh.ops.create_cone(
            self.bm(mat),
            cap_ends=True,
            cap_tris=False,
            segments=segments,
            radius1=r_bottom,
            radius2=r_top,
            depth=depth,
            matrix=m,
        )

    def flush(self, prefix: str) -> int:
        count = 0
        for mat, bm in self.meshes.values():
            if not bm.verts:
                bm.free()
                continue
            mesh = bpy.data.meshes.new(f"{prefix}_{mat.name}")
            bm.to_mesh(mesh)
            bm.free()
            mesh.materials.append(mat)
            obj = bpy.data.objects.new(f"{prefix}_{mat.name}", mesh)
            bpy.context.collection.objects.link(obj)
            count += 1
        self.meshes.clear()
        return count


def _canopy_mat(tree: dict, canopy_mats: list):
    slot = GENUS_CANOPY.get(tree.get("genus") or "")
    tone = float(tree.get("tone") or 0.0)
    if slot is None:
        slot = int(tone * len(canopy_mats)) % len(canopy_mats)
    elif tone > 0.78:  # a few individuals drift to the neighbouring shade
        slot = (slot + 1) % len(canopy_mats)
    return canopy_mats[slot % len(canopy_mats)]


def add_vegetation(
    layout: dict,
    rails,
    trunk_mat,
    canopy_mats: list,
    conifer_mat,
    bush_mats: list,
) -> dict:
    """Create batched tree + bush meshes. Returns per-source counts."""
    origin = tuple(layout.get("origin") or (0.0, 0.0))
    if "trees" not in layout:  # layout predates tree planning: park fill only
        plan = treeplan.plan_trees(layout, None, origin)
        layout["trees"], layout["bushes"], layout["tree_stats"] = (
            plan["trees"],
            plan["bushes"],
            plan["stats"],
        )

    wood = _Batch()
    leaves = _Batch()
    counts = {"antwerp": 0, "osm": 0, "osm_row": 0, "fill": 0, "skipped_rail": 0, "bushes": 0}

    for tree in layout.get("trees") or []:
        x, y = float(tree["x"]), float(tree["y"])
        source = tree.get("source") or "fill"
        clearance = treeplan.CLEAR_TREE if source == "fill" else treeplan.CLEAR_REAL_TRUNK
        if rails.within(x, y, clearance):
            counts["skipped_rail"] += 1  # safety net: nothing grows on a tram bed
            continue
        h = float(tree.get("height") or 8.0)
        r = float(tree.get("radius") or 2.5)
        tone = float(tree.get("tone") or 0.5)
        yaw = tone * math.tau
        shape = tree.get("shape") or "broadleaf"
        trunk_r = max(0.09, min(0.38, 0.07 + 0.017 * h))
        if shape == "conifer":
            wood.cone(trunk_mat, (x, y, 0.0), trunk_r, trunk_r * 0.7, h * 0.25, 6)
            leaves.cone(conifer_mat, (x, y, h * 0.16), r, 0.05, h * 0.84, 7)
        elif shape == "columnar":
            wood.cone(trunk_mat, (x, y, 0.0), trunk_r, trunk_r * 0.6, h * 0.4, 6)
            leaves.blob(
                _canopy_mat(tree, canopy_mats),
                (x, y, h * 0.62),
                (r, r, h * 0.38),
                yaw,
                subdiv=2,
            )
        else:
            leaf = _canopy_mat(tree, canopy_mats)
            # Round-ish crown: height follows the radius, trunk runs up into it.
            vert = max(1.1, min(r * 1.3, h * 0.42))
            cz = h - vert
            wood.cone(trunk_mat, (x, y, 0.0), trunk_r, trunk_r * 0.6, max(1.6, cz * 0.95), 6)
            leaves.blob(leaf, (x, y, cz), (r, r, vert), yaw, subdiv=2)
            # Two smaller lobes break the silhouette so no two crowns match.
            for k, sign in enumerate((1.0, -1.0)):
                ang = yaw + k * 2.4
                ox = math.cos(ang) * r * 0.55 * sign
                oy = math.sin(ang) * r * 0.55 * sign
                leaves.blob(
                    leaf,
                    (x + ox, y + oy, cz - vert * (0.25 + 0.2 * k)),
                    (r * 0.68, r * 0.68, vert * 0.7),
                    ang,
                    subdiv=1,
                )
        counts[source if source in counts else "fill"] += 1

    shrubs = _Batch()
    for bush in layout.get("bushes") or []:
        x, y = float(bush["x"]), float(bush["y"])
        if rails.within(x, y, treeplan.CLEAR_FURNITURE):
            continue
        w = float(bush.get("w") or 1.4)
        hh = float(bush.get("h") or 1.0)
        tone = float(bush.get("tone") or 0.0)
        mat = bush_mats[int(tone * len(bush_mats)) % len(bush_mats)]
        shrubs.blob(mat, (x, y, hh * 0.4), (w * 0.6, w * 0.6, hh * 0.55), tone * math.tau)
        counts["bushes"] += 1

    counts["objects"] = wood.flush("tree_trunks") + leaves.flush("tree_crowns") + shrubs.flush("shrubs")
    return counts
