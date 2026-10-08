"""Build an Antwerp city tile in Blender: LOD2 roofs + street-edge facades."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


# Century-old Harmonie palette: stylish but lived-in, not showroom clean.
STYLES = {
    "neoclassical": {
        "wall": (0.72, 0.68, 0.58, 1.0),
        "roof": (0.18, 0.17, 0.16, 1.0),
        "frame": (0.22, 0.18, 0.14, 1.0),
        "glass": (0.28, 0.34, 0.36, 1.0),
        "plinth": (0.38, 0.36, 0.32, 1.0),
        "trim": (0.78, 0.74, 0.64, 1.0),
        "window": "rect",
    },
    "eclectic": {
        "wall": (0.66, 0.58, 0.46, 1.0),
        "roof": (0.16, 0.15, 0.14, 1.0),
        "frame": (0.18, 0.12, 0.09, 1.0),
        "glass": (0.26, 0.30, 0.32, 1.0),
        "plinth": (0.34, 0.30, 0.26, 1.0),
        "trim": (0.74, 0.68, 0.56, 1.0),
        "window": "rect",
    },
    "neo-flemish": {
        "wall": (0.42, 0.18, 0.14, 1.0),
        "roof": (0.14, 0.12, 0.11, 1.0),
        "frame": (0.10, 0.07, 0.05, 1.0),
        "glass": (0.22, 0.28, 0.30, 1.0),
        "plinth": (0.30, 0.28, 0.26, 1.0),
        "trim": (0.70, 0.64, 0.54, 1.0),
        "window": "arch",
    },
    "neo-gothic": {
        "wall": (0.36, 0.32, 0.28, 1.0),
        "roof": (0.12, 0.11, 0.10, 1.0),
        "frame": (0.08, 0.07, 0.06, 1.0),
        "glass": (0.18, 0.22, 0.24, 1.0),
        "plinth": (0.26, 0.24, 0.22, 1.0),
        "trim": (0.58, 0.54, 0.48, 1.0),
        "window": "arch",
    },
    "art-nouveau": {
        "wall": (0.62, 0.52, 0.34, 1.0),
        "roof": (0.15, 0.14, 0.13, 1.0),
        "frame": (0.10, 0.18, 0.12, 1.0),
        "glass": (0.28, 0.32, 0.28, 1.0),
        "plinth": (0.32, 0.30, 0.28, 1.0),
        "trim": (0.68, 0.62, 0.48, 1.0),
        "window": "arch",
    },
    "art-deco": {
        "wall": (0.70, 0.66, 0.58, 1.0),
        "roof": (0.20, 0.20, 0.21, 1.0),
        "frame": (0.10, 0.10, 0.11, 1.0),
        "glass": (0.24, 0.28, 0.32, 1.0),
        "plinth": (0.42, 0.40, 0.36, 1.0),
        "trim": (0.76, 0.72, 0.64, 1.0),
        "window": "tall",
    },
    "international": {
        "wall": (0.58, 0.58, 0.56, 1.0),
        "roof": (0.22, 0.22, 0.23, 1.0),
        "frame": (0.08, 0.08, 0.09, 1.0),
        "glass": (0.34, 0.38, 0.40, 1.0),
        "plinth": (0.40, 0.40, 0.38, 1.0),
        "trim": (0.62, 0.62, 0.60, 1.0),
        "window": "ribbon",
    },
    "modern-infill": {
        "wall": (0.78, 0.78, 0.74, 1.0),
        "roof": (0.16, 0.16, 0.17, 1.0),
        "frame": (0.08, 0.08, 0.09, 1.0),
        "glass": (0.32, 0.36, 0.38, 1.0),
        "plinth": (0.52, 0.52, 0.50, 1.0),
        "trim": (0.82, 0.82, 0.78, 1.0),
        "window": "ribbon",
    },
    "yellow-brick": {
        "wall": (0.62, 0.48, 0.32, 1.0),
        "roof": (0.22, 0.22, 0.23, 1.0),
        "frame": (0.18, 0.12, 0.08, 1.0),
        "glass": (0.22, 0.28, 0.32, 1.0),
        "plinth": (0.45, 0.34, 0.22, 1.0),
        "trim": (0.82, 0.78, 0.70, 1.0),
        "window": "rect",
    },
    "cream-tile": {
        "wall": (0.78, 0.72, 0.60, 1.0),
        "roof": (0.28, 0.28, 0.27, 1.0),
        "frame": (0.22, 0.16, 0.12, 1.0),
        "glass": (0.22, 0.28, 0.32, 1.0),
        "plinth": (0.84, 0.78, 0.64, 1.0),
        "trim": (0.88, 0.84, 0.74, 1.0),
        "window": "rect",
    },
    "white-modern": {
        "wall": (0.90, 0.89, 0.86, 1.0),
        "roof": (0.16, 0.16, 0.17, 1.0),
        "frame": (0.05, 0.05, 0.055, 1.0),
        "glass": (0.28, 0.34, 0.38, 1.0),
        "plinth": (0.88, 0.87, 0.84, 1.0),
        "trim": (0.94, 0.93, 0.90, 1.0),
        "window": "ribbon",
    },
    "prefab-70s": {
        "wall": (0.58, 0.56, 0.50, 1.0),
        "roof": (0.20, 0.20, 0.20, 1.0),
        "frame": (0.10, 0.11, 0.12, 1.0),
        "glass": (0.25, 0.30, 0.34, 1.0),
        "plinth": (0.40, 0.38, 0.34, 1.0),
        "trim": (0.42, 0.40, 0.36, 1.0),
        "window": "ribbon",
    },
    "red-brick": {
        "wall": (0.42, 0.20, 0.16, 1.0),
        "roof": (0.18, 0.16, 0.15, 1.0),
        "frame": (0.14, 0.10, 0.08, 1.0),
        "glass": (0.20, 0.26, 0.30, 1.0),
        "plinth": (0.28, 0.16, 0.13, 1.0),
        "trim": (0.80, 0.76, 0.68, 1.0),
        "window": "rect",
    },
    "brown-tile": {
        "wall": (0.36, 0.24, 0.18, 1.0),
        "roof": (0.16, 0.14, 0.12, 1.0),
        "frame": (0.08, 0.07, 0.06, 1.0),
        "glass": (0.20, 0.26, 0.30, 1.0),
        "plinth": (0.22, 0.14, 0.10, 1.0),
        "trim": (0.72, 0.64, 0.50, 1.0),
        "window": "rect",
    },
    "antwerp-70s": {
        "wall": (0.70, 0.65, 0.55, 1.0),
        "roof": (0.24, 0.24, 0.23, 1.0),
        "frame": (0.12, 0.11, 0.10, 1.0),
        "glass": (0.22, 0.28, 0.32, 1.0),
        "plinth": (0.82, 0.76, 0.62, 1.0),
        "trim": (0.86, 0.80, 0.68, 1.0),
        "window": "rect",
    },
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(argv)


def reset_scene() -> None:
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for block in list(coll):
            coll.remove(block)
    bpy.context.scene.unit_settings.system = "METRIC"


def link(obj: bpy.types.Object) -> bpy.types.Object:
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)
    return obj


def principled(name: str, color, rough: float = 0.85, metallic: float = 0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = metallic
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def style_of(name: str) -> dict:
    return STYLES.get(name, STYLES["eclectic"])


def add_box(name: str, size, loc, rot_z: float = 0.0) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.scale = size
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, rot_z)
    return link(obj)


def ring_mesh(name: str, ring: list[list[float]], height: float, z: float = 0.0) -> bpy.types.Mesh | None:
    if len(ring) < 3:
        return None
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts = [bm.verts.new((p[0], p[1], z)) for p in ring]
    bm.verts.ensure_lookup_table()
    edges = [bm.edges.new((vert, verts[(i + 1) % len(verts)])) for i, vert in enumerate(verts)]
    filled = bmesh.ops.triangle_fill(bm, edges=edges)
    faces = [ele for ele in filled.get("geom", []) if isinstance(ele, bmesh.types.BMFace)]
    if not faces:
        faces = list(bm.faces)
    if not faces:
        bm.free()
        return None
    if height > 0.05:
        extruded = bmesh.ops.extrude_face_region(bm, geom=faces)
        moved = [ele for ele in extruded["geom"] if isinstance(ele, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=moved, vec=(0.0, 0.0, height))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def inset_ring(ring: list[list[float]], inset: float) -> list[list[float]]:
    if len(ring) < 3 or inset <= 0:
        return ring
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    out: list[list[float]] = []
    for x, y in ring:
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy) or 1.0
        scale = max(0.35, 1.0 - inset / dist)
        out.append([cx + dx * scale, cy + dy * scale])
    return out


def add_ring(name: str, ring: list[list[float]], height: float, z: float, mat: bpy.types.Material) -> bpy.types.Object | None:
    mesh = ring_mesh(name, ring, height, z)
    if mesh is None:
        return None
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def _obb(ring: list[list[float]]):
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    cov_xx = cov_xy = cov_yy = 0.0
    for x, y in ring:
        dx, dy = x - cx, y - cy
        cov_xx += dx * dx
        cov_xy += dx * dy
        cov_yy += dy * dy
    n = max(1, len(ring))
    cov_xx /= n
    cov_xy /= n
    cov_yy /= n
    trace = cov_xx + cov_yy
    det = cov_xx * cov_yy - cov_xy * cov_xy
    gap = math.sqrt(max(0.0, trace * trace * 0.25 - det))
    l1 = trace * 0.5 + gap
    if abs(cov_xy) > 1e-9:
        ux, uy = l1 - cov_yy, cov_xy
    else:
        ux, uy = (1.0, 0.0) if cov_xx >= cov_yy else (0.0, 1.0)
    ulen = math.hypot(ux, uy) or 1.0
    ux, uy = ux / ulen, uy / ulen
    vx, vy = -uy, ux
    hu = hv = 0.0
    for x, y in ring:
        dx, dy = x - cx, y - cy
        hu = max(hu, abs(dx * ux + dy * uy))
        hv = max(hv, abs(dx * vx + dy * vy))
    if hu < hv:
        ux, uy, vx, vy = vx, vy, ux, uy
        hu, hv = hv, hu
    return cx, cy, ux, uy, vx, vy, max(hu, 0.8), max(hv, 0.8)


def add_gable_roof(name: str, ring: list[list[float]], z0: float, roof_h: float, mat) -> None:
    cx, cy, ux, uy, vx, vy, hu, hv = _obb(ring)
    h = max(1.0, roof_h)
    # Four eave corners + ridge line along long axis.
    corners = [
        (cx - hu * ux - hv * vx, cy - hu * uy - hv * vy, z0),
        (cx + hu * ux - hv * vx, cy + hu * uy - hv * vy, z0),
        (cx + hu * ux + hv * vx, cy + hu * uy + hv * vy, z0),
        (cx - hu * ux + hv * vx, cy - hu * uy + hv * vy, z0),
        (cx - hu * ux, cy - hu * uy, z0 + h),
        (cx + hu * ux, cy + hu * uy, z0 + h),
    ]
    faces = [
        (0, 1, 5, 4),  # slope -v
        (3, 2, 5, 4),  # slope +v
        (0, 4, 3),  # gable
        (1, 2, 5),  # gable
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)


def add_hip_roof(name: str, ring: list[list[float]], z0: float, roof_h: float, mat) -> None:
    if len(ring) < 3:
        return
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    peak = (cx, cy, z0 + max(1.0, roof_h))
    base = [(p[0], p[1], z0) for p in ring]
    verts = base + [peak]
    apex = len(base)
    faces = []
    for i in range(len(base)):
        faces.append((i, (i + 1) % len(base), apex))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)


def add_lod2_roof(name: str, ring, eaves_z: float, roof_h: float, shape: str, mat) -> None:
    h = max(0.35, roof_h)
    if shape == "flat":
        add_ring(name, ring, min(0.55, h), eaves_z, mat)
    elif shape == "hip":
        add_hip_roof(name, ring, eaves_z, h, mat)
    elif shape == "gable":
        add_gable_roof(name, ring, eaves_z, h, mat)
    else:  # mansard
        lower = inset_ring(ring, 0.7)
        add_ring(f"{name}_a", lower, h * 0.55, eaves_z, mat)
        upper = inset_ring(ring, 1.5)
        add_ring(f"{name}_b", upper, h * 0.45, eaves_z + h * 0.55, mat)


def _box_verts(cx, cy, cz, sx, sy, sz, yaw: float):
    """Axis-aligned box in local edge frame, rotated by yaw around Z."""
    c, s = math.cos(yaw), math.sin(yaw)
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    local = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    out = []
    for x, y, z in local:
        out.append((cx + x * c - y * s, cy + x * s + y * c, cz + z))
    return out


def _append_box(bm, cx, cy, cz, sx, sy, sz, yaw: float, mat_index: int) -> None:
    verts = [bm.verts.new(v) for v in _box_verts(cx, cy, cz, sx, sy, sz, yaw)]
    bm.verts.ensure_lookup_table()
    faces_idx = (
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    for idxs in faces_idx:
        face = bm.faces.new([verts[i] for i in idxs])
        face.material_index = mat_index


def add_street_facade(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    eaves_z: float,
    floors: int,
    style_name: str,
    mats: dict,
    detail: str = "full",
) -> None:
    """One batched mesh per street edge (skin, plinth, cornice, windows)."""
    style = style_of(style_name)
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 2.6 or eaves_z < 4.0:
        return
    nx, ny = outward
    yaw = math.atan2(y1 - y0, x1 - x0)
    mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    ox, oy = mx + nx * 0.06, my + ny * 0.06

    mesh = bpy.data.meshes.new(name)
    # Slot order matches material_index below.
    for key in ("wall", "plinth", "trim", "frame", "glass"):
        mesh.materials.append(mats[key][style_name])

    bm = bmesh.new()
    plinth_h = min(1.15, eaves_z * 0.12)
    _append_box(bm, ox, oy, eaves_z * 0.5, length * 0.98, 0.08, eaves_z, yaw, 0)
    _append_box(bm, ox + nx * 0.04, oy + ny * 0.04, plinth_h * 0.5, length * 0.98, 0.12, plinth_h, yaw, 1)
    _append_box(bm, ox + nx * 0.08, oy + ny * 0.08, eaves_z + 0.05, length * 1.02, 0.22, 0.28, yaw, 2)

    kind = style.get("window", "rect")
    floors = max(1, min(8, int(floors)))
    if detail == "simple":
        floors = min(floors, 3)
    floor_h = eaves_z / max(1, floors)
    bay_pitch = 4.2 if kind == "ribbon" else (2.8 if detail == "simple" else 2.35)
    bays = max(1, int(length / bay_pitch))
    bay_w = length / bays
    win_w = max(0.55, bay_w * (0.85 if kind == "ribbon" else 0.64))
    door_bay = bays // 2

    for fi in range(floors):
        z_base = fi * floor_h
        for bi in range(bays):
            along = -length * 0.5 + (bi + 0.5) * bay_w
            px = ox + math.cos(yaw) * along + nx * 0.12
            py = oy + math.sin(yaw) * along + ny * 0.12
            if fi == 0 and bi == door_bay:
                dh = min(2.3, floor_h * 0.72)
                _append_box(bm, px, py, plinth_h + dh * 0.5, min(1.1, win_w * 0.85), 0.1, dh, yaw, 3)
                continue
            if kind == "ribbon":
                wh, ww = floor_h * 0.52, bay_w * 0.88
            elif kind == "tall":
                wh, ww = floor_h * 0.62, win_w * 0.75
            elif kind == "arch":
                wh, ww = floor_h * 0.58, win_w * 0.9
            else:
                wh, ww = floor_h * (0.42 if fi == 0 else 0.5), win_w
            sill = (plinth_h + 0.35) if fi == 0 else (z_base + floor_h * 0.22)
            _append_box(bm, px, py, sill + wh * 0.5, ww + 0.1, 0.1, wh + 0.1, yaw, 3)
            _append_box(
                bm,
                px + nx * 0.03,
                py + ny * 0.03,
                sill + wh * 0.5,
                ww,
                0.06,
                wh,
                yaw,
                4,
            )

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))


def add_building(bldg: dict, mats: dict, spawn_xy: tuple[float, float] | None = None) -> None:
    style_name = bldg.get("style", "eclectic")
    ring = bldg.get("ring") or []
    if len(ring) < 3:
        return
    bid = bldg.get("id", 0)
    name = f"bldg_{bid}"
    eaves = float(bldg.get("height", 12.0))
    roof_h = float(bldg.get("roof_height") or max(1.2, eaves * 0.15))
    floors = int(bldg.get("floors") or max(1, round(eaves / 3.15)))
    shape = bldg.get("roof_shape") or "mansard"
    wall = mats["wall"].get(style_name) or mats["wall"]["eclectic"]
    roof = mats["roof"].get(style_name) or mats["roof"]["eclectic"]

    add_ring(name, ring, max(2.5, eaves), 0.0, wall)
    add_lod2_roof(f"{name}_roof", ring, max(2.5, eaves), roof_h, shape, roof)

    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    detail = "full"
    if spawn_xy is not None:
        dist = math.hypot(cx - spawn_xy[0], cy - spawn_xy[1])
        if dist > 180.0:
            detail = "simple"
        if dist > 420.0:
            # Far LOD1 colour blocks only — still keep roofs.
            return

    for ei, edge in enumerate(bldg.get("street_edges") or []):
        i0 = int(edge["i0"])
        i1 = int(edge["i1"])
        if i0 >= len(ring) or i1 >= len(ring):
            continue
        add_street_facade(
            f"{name}_facade{ei}",
            ring[i0],
            ring[i1],
            edge.get("outward") or [0.0, 1.0],
            max(2.5, eaves),
            floors,
            style_name,
            mats,
            detail=detail,
        )


def polyline_mesh(name: str, points: list[list[float]], width: float, z: float = 0.04) -> bpy.types.Mesh | None:
    if len(points) < 2:
        return None
    half = width / 2.0
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == len(points) - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    verts = [(x, y, z) for x, y in left] + [(x, y, z) for x, y in reversed(right)]
    n = len(left)
    faces = [list(range(n)) + list(range(n, 2 * n))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def add_road(name: str, points: list[list[float]], width: float, mat: bpy.types.Material) -> bpy.types.Object | None:
    mesh = polyline_mesh(name, points, width)
    if mesh is None:
        return None
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def bounds(layout: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for group in ("buildings", "water", "parks"):
        for item in layout.get(group) or []:
            for x, y in item.get("ring") or []:
                xs.append(x)
                ys.append(y)
    for road in layout.get("roads") or []:
        for x, y in road.get("points") or []:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (-200, -200, 200, 200)
    pad = 40.0
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def setup_world() -> None:
    """Clear Belgian summer day — deep blue sky, hard sun."""
    world = bpy.data.worlds.new("SunnyDay")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.35, 0.58, 0.92, 1.0)
    bg.inputs["Strength"].default_value = 1.05
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = world

    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 4.2
    sun.angle = math.radians(0.55)
    sun.color = (1.0, 0.96, 0.88)
    obj = bpy.data.objects.new("Sun", sun)
    obj.rotation_euler = (math.radians(38), 0.0, math.radians(145))
    link(obj)

    # Visible sun disc in the sky for pedestrian POV / renders.
    sun_ball = add_box("SunDisc", (18.0, 18.0, 18.0), (420.0, -280.0, 520.0), 0.0)
    assign(sun_ball, principled("sun_glow", (1.0, 0.95, 0.75, 1.0), 0.15, metallic=0.0))


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1):
            inside = not inside
    return inside


def add_park_vegetation(parks: list, trunk_mat, canopy_mat, bush_mat) -> int:
    """Simple trees + bushes inside park polygons. Capped for browser FPS."""
    placed = 0
    max_trees = 220
    max_bushes = 160
    for park in parks:
        ring = park.get("ring") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        area = abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))) * 0.5
        n_trees = max(2, min(28, int(area / 900)))
        n_bushes = max(3, min(36, int(area / 550)))
        seed = int(park.get("id") or 1)
        for i in range(n_trees):
            if placed >= max_trees:
                break
            # Deterministic pseudo-random in bbox
            u = ((seed * 1103515245 + i * 12345) & 0x7FFFFFFF) / 0x7FFFFFFF
            v = ((seed * 1664525 + i * 1013904223) & 0x7FFFFFFF) / 0x7FFFFFFF
            x = minx + u * (maxx - minx)
            y = miny + v * (maxy - miny)
            if not _point_in_ring(x, y, ring):
                continue
            h = 5.5 + (u * 4.0)
            trunk = add_box(f"tree_t_{park.get('id')}_{i}", (0.28, 0.28, h * 0.45), (x, y, h * 0.22), 0.0)
            assign(trunk, trunk_mat)
            canopy = add_box(
                f"tree_c_{park.get('id')}_{i}",
                (2.2 + v, 2.2 + u, 2.4 + v),
                (x, y, h * 0.55),
                u * 0.4,
            )
            assign(canopy, canopy_mat)
            placed += 1
        for i in range(n_bushes):
            if placed >= max_trees + max_bushes:
                break
            u = ((seed * 214013 + i * 2531011) & 0x7FFFFFFF) / 0x7FFFFFFF
            v = ((seed * 1103515245 + i * 99991) & 0x7FFFFFFF) / 0x7FFFFFFF
            x = minx + u * (maxx - minx)
            y = miny + v * (maxy - miny)
            if not _point_in_ring(x, y, ring):
                continue
            bush = add_box(f"bush_{park.get('id')}_{i}", (1.1 + u * 0.6, 1.1 + v * 0.6, 0.9 + u * 0.5), (x, y, 0.5), 0.0)
            assign(bush, bush_mat)
            placed += 1
    return placed


def add_traffic_light(name: str, x: float, y: float, pole_mat, housing_mat, lamp_mats) -> None:
    pole = add_box(f"{name}_pole", (0.12, 0.12, 3.4), (x, y, 1.7), 0.0)
    assign(pole, pole_mat)
    head = add_box(f"{name}_head", (0.28, 0.22, 0.85), (x, y + 0.18, 3.55), 0.0)
    assign(head, housing_mat)
    for i, mat in enumerate(lamp_mats):
        lamp = add_box(f"{name}_l{i}", (0.16, 0.08, 0.16), (x, y + 0.32, 3.85 - i * 0.26), 0.0)
        assign(lamp, mat)


def collect_signal_points(layout: dict) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for s in layout.get("signals") or []:
        pts.append((float(s["x"]), float(s["y"])))
    if pts:
        return pts[:80]
    # Fallback: dense road vertices ≈ junctions.
    buckets: dict[tuple[int, int], int] = {}
    coords: dict[tuple[int, int], tuple[float, float]] = {}
    for road in layout.get("roads") or []:
        if road.get("kind") in {"footway", "path", "cycleway", "steps", "service"}:
            continue
        for x, y in road.get("points") or []:
            key = (int(round(x / 8.0)), int(round(y / 8.0)))
            buckets[key] = buckets.get(key, 0) + 1
            coords[key] = (x, y)
    for key, count in buckets.items():
        if count >= 3:
            pts.append(coords[key])
    return pts[:60]


def setup_cameras(layout: dict, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
    mid_x = (xmin + xmax) / 2.0
    mid_y = (ymin + ymax) / 2.0
    span = max(xmax - xmin, ymax - ymin)
    aerial = bpy.data.cameras.new("CityCam")
    aerial.lens = 35
    aerial.clip_start = 1.0
    aerial.clip_end = 12000
    aerial_obj = bpy.data.objects.new("CityCam", aerial)
    aerial_obj.location = (mid_x - span * 0.55, mid_y - span * 0.7, max(180.0, span * 0.55))
    direction = Vector((mid_x, mid_y, 0.0)) - aerial_obj.location
    aerial_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    link(aerial_obj)

    spawn = layout.get("spawn") or {}
    sx = float(spawn.get("x", mid_x))
    sy = float(spawn.get("y", mid_y))
    sz = float(spawn.get("z", 1.7))
    yaw = float(spawn.get("yaw", 0.0))

    empty = bpy.data.objects.new("HumanSpawn", None)
    empty.empty_display_type = "ARROWS"
    empty.empty_display_size = 1.2
    empty.location = (sx, sy, sz)
    empty.rotation_euler = (0.0, 0.0, yaw)
    link(empty)

    street = bpy.data.cameras.new("StreetCam")
    street.lens = 28
    street.clip_start = 0.2
    street.clip_end = 2500
    street_obj = bpy.data.objects.new("StreetCam", street)
    # Human eye: stand near the address, look along the street tangent.
    street_obj.location = (sx, sy, sz)
    ahead = Vector((sx + math.cos(yaw) * 10.0, sy + math.sin(yaw) * 10.0, sz))
    street_obj.rotation_euler = (ahead - street_obj.location).to_track_quat("-Z", "Y").to_euler()
    link(street_obj)
    bpy.context.scene.camera = street_obj


def build(layout: dict) -> None:
    reset_scene()
    xmin, ymin, xmax, ymax = bounds(layout)
    ground = bpy.data.meshes.new("ground")
    ground.from_pydata(
        [
            (xmin, ymin, -0.15),
            (xmax, ymin, -0.15),
            (xmax, ymax, -0.15),
            (xmin, ymax, -0.15),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    ground.update()
    assign(link(bpy.data.objects.new("ground", ground)), principled("ground", (0.74, 0.73, 0.68, 1.0), 0.95))

    water_mat = principled("water", (0.18, 0.32, 0.42, 1.0), 0.12)
    park_mat = principled("park", (0.28, 0.48, 0.26, 1.0), 0.92)
    road_mat = principled("asphalt", (0.08, 0.08, 0.09, 1.0), 0.96)
    trunk_mat = principled("trunk", (0.28, 0.18, 0.10, 1.0), 0.9)
    canopy_mat = principled("canopy", (0.22, 0.42, 0.18, 1.0), 0.85)
    bush_mat = principled("bush", (0.26, 0.40, 0.16, 1.0), 0.9)
    pole_mat = principled("pole", (0.18, 0.18, 0.18, 1.0), 0.5, metallic=0.4)
    housing_mat = principled("tl_housing", (0.08, 0.08, 0.08, 1.0), 0.45, metallic=0.35)
    lamp_mats = [
        principled("tl_red", (0.85, 0.12, 0.08, 1.0), 0.25),
        principled("tl_amber", (0.9, 0.55, 0.08, 1.0), 0.25),
        principled("tl_green", (0.12, 0.7, 0.22, 1.0), 0.25),
    ]

    mats = {
        "wall": {n: principled(f"wall_{n}", s["wall"], 0.92) for n, s in STYLES.items()},
        "roof": {n: principled(f"roof_{n}", s["roof"], 0.6, metallic=0.08) for n, s in STYLES.items()},
        "frame": {n: principled(f"frame_{n}", s["frame"], 0.55, metallic=0.15) for n, s in STYLES.items()},
        "glass": {n: principled(f"glass_{n}", s["glass"], 0.2, metallic=0.05) for n, s in STYLES.items()},
        "plinth": {n: principled(f"plinth_{n}", s["plinth"], 0.94) for n, s in STYLES.items()},
        "trim": {n: principled(f"trim_{n}", s["trim"], 0.78) for n, s in STYLES.items()},
    }

    for i, pond in enumerate(layout.get("water") or []):
        add_ring(f"water_{pond.get('id', i)}", pond["ring"], 0.0, -0.04, water_mat)
    for i, park in enumerate(layout.get("parks") or []):
        add_ring(f"park_{park.get('id', i)}", park["ring"], 0.0, 0.02, park_mat)
    for i, road in enumerate(layout.get("roads") or []):
        add_road(f"road_{road.get('id', i)}", road["points"], float(road["width"]), road_mat)

    veg = add_park_vegetation(layout.get("parks") or [], trunk_mat, canopy_mat, bush_mat)
    print(f"Park vegetation props: {veg}")

    signal_pts = collect_signal_points(layout)
    for i, (sx, sy) in enumerate(signal_pts):
        add_traffic_light(f"signal_{i}", sx, sy, pole_mat, housing_mat, lamp_mats)
    print(f"Traffic lights: {len(signal_pts)}")

    spawn = layout.get("spawn") or {}
    spawn_xy = (float(spawn["x"]), float(spawn["y"])) if spawn.get("x") is not None else None
    for bldg in layout.get("buildings") or []:
        add_building(bldg, mats, spawn_xy=spawn_xy)

    setup_world()
    setup_cameras(layout, xmin, ymin, xmax, ymax)


def export_outputs(output_dir: Path, name: str, do_render: bool) -> None:
    blend = output_dir / f"{name}.blend"
    glb = output_dir / f"{name}.glb"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_cameras=True,
        export_yup=True,
    )
    if do_render:
        scene = bpy.context.scene
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE"
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
        scene.render.image_settings.file_format = "JPEG"
        scene.render.image_settings.quality = 90
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = 32
        # Street-level hero preview from Gounodstraat spawn.
        if "StreetCam" in bpy.data.objects:
            scene.camera = bpy.data.objects["StreetCam"]
        preview = output_dir / f"{name}_preview.jpg"
        scene.render.filepath = str(preview)
        bpy.ops.render.render(write_still=True)
        print(f"Wrote {preview}")
        # Also keep an aerial overview.
        if "CityCam" in bpy.data.objects:
            scene.camera = bpy.data.objects["CityCam"]
            aerial = output_dir / f"{name}_aerial.jpg"
            scene.render.filepath = str(aerial)
            bpy.ops.render.render(write_still=True)
            print(f"Wrote {aerial}")
    print(f"Wrote {blend}")
    print(f"Wrote {glb}")


def main() -> None:
    args = parse_args()
    job = json.loads(Path(args.job).read_text())
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    layout = job.get("layout")
    if not layout:
        layout = json.loads(Path(job["layout_path"]).read_text())
    if job.get("spawn") and not layout.get("spawn"):
        layout["spawn"] = job["spawn"]
    build(layout)
    export_outputs(output_dir, job.get("scene_name", "antwerp_city"), job.get("render", True))


if __name__ == "__main__":
    main()
