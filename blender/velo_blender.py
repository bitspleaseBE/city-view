"""Velo Antwerpen dock rails + docked city bikes (runs inside Blender).

``layout["velo_stations"]`` (see ``cityview.velo``) lists docking terminals at their
surveyed positions. Mesh convention: rail length on local X, front (street) on local +Y,
``yaw`` is ``rotation_z``.

Baked bikes give stations a clean Velo look. The walk viewer only spawns the ride bike
(``viewer/velo.js``) so docks are not doubled at runtime.
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
from cityview.railclear import CLEAR_FURNITURE  # noqa: E402
from cityview import velo as veloplan  # noqa: E402

LIFT = 0.04
MAX_BAKED_BIKES = 8
# The bike below is modelled at 1:1.55; this brings it to a real Velo (wheel r ≈ 0.31 m,
# saddle ≈ 0.95 m). viewer/velo.js scales its ride bike by the same factor.
BIKE_SCALE = 1.55
SLOT_PAD = 0.76  # bike centre in front of the rail: front wheel sits in the dock guide


def _box(bm, base: Matrix, size, center) -> None:
    m = base @ Matrix.Translation(Vector(center)) @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


def _cyl(bm, base: Matrix, radius: float, height: float, center, segs: int = 10) -> None:
    m = base @ Matrix.Translation(Vector(center))
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segs,
        radius1=radius,
        radius2=radius,
        depth=height,
        matrix=m,
    )


def _tube(bm, base: Matrix, a, b, radius: float, segs: int = 8) -> None:
    """Cylinder from point a to point b in the bike/station local frame."""
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    mid = ((ax + bx) * 0.5, (ay + by) * 0.5, (az + bz) * 0.5)
    # Align +Z of cone (depth axis after create_cone is Z in older bmesh — actually depth is Z)
    # bmesh create_cone depth along local Z. Build rotation from (0,0,1) to dir.
    dir_v = Vector((dx, dy, dz)).normalized()
    z = Vector((0.0, 0.0, 1.0))
    if abs(dir_v.dot(z)) > 0.999:
        rot = Matrix.Identity(3) if dir_v.z > 0 else Matrix.Rotation(math.pi, 3, "X")
    else:
        rot = z.rotation_difference(dir_v).to_matrix()
    m = base @ Matrix.Translation(Vector(mid)) @ rot.to_4x4()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segs,
        radius1=radius,
        radius2=radius,
        depth=length,
        matrix=m,
    )


def _wheel(bm_tire, bm_rim, base: Matrix, center, radius: float = 0.2) -> None:
    """Tire + hub. Wheel in YZ plane (axle along X) for bike facing +X."""
    cx, cy, cz = center
    # Tire as thin torus approximation
    segs = 16
    for i in range(segs):
        a0 = (i / segs) * math.tau
        a1 = ((i + 1) / segs) * math.tau
        y0, z0 = radius * math.cos(a0), radius * math.sin(a0)
        y1, z1 = radius * math.cos(a1), radius * math.sin(a1)
        _tube(bm_tire, base, (cx, cy + y0, cz + z0), (cx, cy + y1, cz + z1), 0.02, segs=6)
    _cyl(bm_rim, base, 0.028, 0.04, (cx, cy, cz), segs=8)
    # Rotated hub: cone is Z-up; axle should be X — rotate
    # Simpler hub as thin box along X:
    _box(bm_rim, base, (0.045, 0.05, 0.05), (cx, cy, cz))


class Parts:
    def __init__(self) -> None:
        self.meshes: dict[str, bmesh.types.BMesh] = {}

    def bm(self, key: str):
        if key not in self.meshes:
            self.meshes[key] = bmesh.new()
        return self.meshes[key]


def _station_rail(p: Parts, base: Matrix, length: float, capacity: int) -> None:
    half = length * 0.5
    metal = p.bm("metal")
    red = p.bm("signal_red")
    _box(metal, base, (length + 0.15, 0.65, 0.06), (0.0, 0.02, LIFT + 0.03))
    _box(metal, base, (length, 0.09, 0.12), (0.0, -0.14, LIFT + 0.36))
    _box(metal, base, (length, 0.035, 0.22), (0.0, -0.26, LIFT + 0.3))
    for sx in (-1.0, 1.0):
        _box(metal, base, (0.09, 0.5, 0.5), (sx * (half - 0.05), -0.06, LIFT + 0.28))
    n_mid = max(0, int(length // 2.6) - 1)
    for i in range(n_mid):
        t = (i + 1) / (n_mid + 1)
        cx = -half + t * length
        _box(metal, base, (0.055, 0.36, 0.42), (cx, -0.1, LIFT + 0.26))
    slots = max(4, int(capacity))
    spacing = length / max(1, slots)
    screen = p.bm("tire")
    panel = p.bm("mudguard")
    for i in range(slots):
        cx = -half + (i + 0.5) * spacing
        # Dock post with a lock head and status LED, plus a short wheel guide in front.
        _box(metal, base, (0.08, 0.08, 0.6), (cx, 0.1, LIFT + 0.3))
        _box(metal, base, (0.12, 0.2, 0.13), (cx, 0.14, LIFT + 0.66))
        _box(red, base, (0.05, 0.02, 0.03), (cx, 0.25, LIFT + 0.68))
        for gx in (-0.05, 0.05):
            _box(metal, base, (0.025, 0.42, 0.025), (cx + gx, 0.42, LIFT + 0.1))
    # Terminal pillar at the rail head: red column, dark screen + white map panel.
    tx = -half - 0.45
    _box(metal, base, (0.5, 0.36, 0.08), (tx, 0.0, LIFT + 0.04))
    _box(red, base, (0.42, 0.28, 1.9), (tx, 0.0, LIFT + 1.03))
    _box(red, base, (0.48, 0.34, 0.08), (tx, 0.0, LIFT + 2.0))
    _box(screen, base, (0.26, 0.02, 0.2), (tx, 0.145, LIFT + 1.42))
    _box(panel, base, (0.3, 0.02, 0.5), (tx, 0.145, LIFT + 0.85))
    _box(panel, base, (0.34, 0.02, 0.9), (tx, -0.145, LIFT + 1.1))
    _box(panel, base, (0.36, 0.3, 0.14), (tx, 0.0, LIFT + 1.82))


def _velo_bike(p: Parts, base: Matrix) -> None:
    """Cleaner step-through Velo: tube frame, small wheels, front rack, white mudguard.

    Bike faces local +X; docked with a π/2 yaw so the front wheel sits in the street-side fork.
    """
    tire = p.bm("tire")
    rim = p.bm("metal")
    frame = p.bm("frame")
    mud = p.bm("mudguard")
    red = p.bm("signal_red")

    wr = 0.2
    _wheel(tire, rim, base, (0.33, 0.0, wr), wr)   # front
    _wheel(tire, rim, base, (-0.33, 0.0, wr), wr)  # rear

    # Step-through tube polyline (side view in XZ, Y=0)
    pts = [
        (0.3, 0.0, 0.14),   # near front hub up
        (0.22, 0.0, 0.36),  # head cluster
        (0.05, 0.0, 0.26),  # low mid (step-through)
        (-0.05, 0.0, 0.22), # BB
        (-0.22, 0.0, 0.36), # seat cluster
        (-0.3, 0.0, 0.2),   # toward rear hub
    ]
    for a, b in zip(pts, pts[1:]):
        _tube(frame, base, a, b, 0.016, segs=7)
    # Seat stay
    _tube(frame, base, (-0.22, 0.0, 0.36), (-0.33, 0.0, wr), 0.012, segs=6)
    # Fork blades
    _tube(rim, base, (0.24, -0.03, 0.4), (0.33, -0.03, wr), 0.01, segs=5)
    _tube(rim, base, (0.24, 0.03, 0.4), (0.33, 0.03, wr), 0.01, segs=5)
    # Seat post + saddle
    _tube(rim, base, (-0.22, 0.0, 0.36), (-0.22, 0.0, 0.58), 0.011, segs=6)
    _box(tire, base, (0.18, 0.1, 0.035), (-0.22, 0.0, 0.62))
    # Stem + bars
    _tube(rim, base, (0.22, 0.0, 0.4), (0.22, 0.0, 0.6), 0.011, segs=6)
    _tube(rim, base, (0.22, -0.22, 0.62), (0.22, 0.22, 0.62), 0.01, segs=6)
    # Front rack
    _box(rim, base, (0.16, 0.28, 0.012), (0.4, 0.0, 0.48))
    _tube(rim, base, (0.36, -0.1, 0.48), (0.36, -0.1, 0.34), 0.008, segs=5)
    _tube(rim, base, (0.36, 0.1, 0.48), (0.36, 0.1, 0.34), 0.008, segs=5)
    # Thin white rear mudguard
    _box(mud, base, (0.2, 0.08, 0.09), (-0.4, 0.0, 0.3))
    _box(red, base, (0.04, 0.04, 0.04), (-0.48, 0.0, 0.3))
    # Crank hint
    _box(rim, base, (0.04, 0.05, 0.05), (-0.02, 0.0, 0.2))


def add_velo_stations(layout: dict, rails, mats: dict) -> dict:
    origin = tuple(layout.get("origin") or (0.0, 0.0))
    if "velo_stations" not in layout:
        plan = veloplan.plan_velo(layout, None, origin)
        layout["velo_stations"] = plan["stations"]
        layout["velo_stats"] = plan["stats"]

    p = Parts()
    counts = {"stations": 0, "bikes": 0, "skipped_rail": 0}
    for st in layout.get("velo_stations") or []:
        x, y = float(st["x"]), float(st["y"])
        if rails.within(x, y, CLEAR_FURNITURE):
            counts["skipped_rail"] += 1
            continue
        length = float(st.get("railLength") or 8.0)
        capacity = int(st.get("capacity") or 20)
        yaw = float(st["yaw"])
        base = Matrix.Translation(Vector((x, y, 0.0))) @ Matrix.Rotation(yaw, 4, "Z")
        _station_rail(p, base, length, capacity)
        counts["stations"] += 1

        bikes_n = min(MAX_BAKED_BIKES, int(st.get("bikesAvailable") or 0), capacity)
        spacing = length / max(1, capacity)
        half = length * 0.5
        for i in range(bikes_n):
            slot = int(round(i * (capacity - 1) / max(1, bikes_n - 1))) if bikes_n > 1 else capacity // 2
            cx = -half + (slot + 0.5) * spacing
            # Front wheel nosed into the dock (bike +X → station −Y), at real size.
            bike_base = (
                base
                @ Matrix.Translation(Vector((cx, SLOT_PAD, 0.0)))
                @ Matrix.Rotation(-math.pi / 2.0, 4, "Z")
                @ Matrix.Diagonal(Vector((BIKE_SCALE, BIKE_SCALE, BIKE_SCALE, 1.0)))
            )
            _velo_bike(p, bike_base)
            counts["bikes"] += 1

    name_map = {
        "metal": "velo_dock_metal",
        "frame": "velo_frame_red",
        "mudguard": "velo_mudguard",
        "tire": "velo_tire",
        "signal_red": "velo_accent_red",
    }
    for key, obj_name in name_map.items():
        bm = p.meshes.get(key)
        if not bm or not bm.verts:
            if bm:
                bm.free()
            continue
        mesh = bpy.data.meshes.new(obj_name)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(obj_name, mesh)
        mat = mats.get(key)
        if mat is not None:
            mesh.materials.append(mat)
        bpy.context.collection.objects.link(obj)
    return counts
