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
    return STYLES.get(name, STYLES.get("eclectic") or next(iter(STYLES.values())))


def _as_rgba(value, fallback=(0.5, 0.5, 0.5, 1.0)):
    if not value:
        return fallback
    vals = list(value)
    while len(vals) < 4:
        vals.append(1.0)
    return (float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))


def merge_building_types(types_doc: dict | None) -> None:
    """Overlay photo-remixed building types onto STYLES (base + __vN variants)."""
    if not types_doc:
        return
    for type_id, entry in (types_doc.get("types") or {}).items():
        pal = entry.get("palette") or {}
        window = entry.get("window") or "rect"
        base = {
            "wall": _as_rgba(pal.get("wall"), STYLES.get(type_id, {}).get("wall", (0.6, 0.55, 0.45, 1.0))),
            "roof": _as_rgba(pal.get("roof"), STYLES.get(type_id, {}).get("roof", (0.18, 0.17, 0.16, 1.0))),
            "frame": _as_rgba(pal.get("frame"), STYLES.get(type_id, {}).get("frame", (0.15, 0.12, 0.1, 1.0))),
            "glass": _as_rgba(pal.get("glass"), STYLES.get(type_id, {}).get("glass", (0.25, 0.3, 0.32, 1.0))),
            "plinth": _as_rgba(pal.get("plinth"), STYLES.get(type_id, {}).get("plinth", (0.35, 0.32, 0.28, 1.0))),
            "trim": _as_rgba(pal.get("trim"), STYLES.get(type_id, {}).get("trim", (0.75, 0.7, 0.6, 1.0))),
            "window": window,
        }
        STYLES[type_id] = base
        for vi, variant in enumerate(entry.get("variants") or []):
            STYLES[f"{type_id}__v{vi}"] = {
                "wall": _as_rgba(variant.get("wall"), base["wall"]),
                "roof": _as_rgba(variant.get("roof"), base["roof"]),
                "frame": _as_rgba(variant.get("frame"), base["frame"]),
                "glass": _as_rgba(variant.get("glass"), base["glass"]),
                "plinth": _as_rgba(variant.get("plinth"), base["plinth"]),
                "trim": _as_rgba(variant.get("trim"), base["trim"]),
                "window": window,
            }


def style_key_for(bldg: dict) -> str:
    """Prefer typed variant key so streets share materials but vary within a type."""
    type_id = bldg.get("building_type") or bldg.get("style") or "eclectic"
    if bldg.get("palette") and "window" in (bldg.get("palette") or {}):
        # Window rhythm always comes from the building type.
        pass
    variant = bldg.get("type_variant")
    if variant is None:
        return type_id if type_id in STYLES else "eclectic"
    keyed = f"{type_id}__v{int(variant)}"
    if keyed in STYLES:
        return keyed
    return type_id if type_id in STYLES else "eclectic"


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


def _ring_signed_area(ring: list[list[float]]) -> float:
    n = len(ring)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def inset_ring(ring: list[list[float]], inset: float) -> list[list[float]]:
    """Offset polygon inward along edge normals; never expand past the wall ring."""
    if len(ring) < 3 or inset <= 0:
        return [list(p) for p in ring]
    area = _ring_signed_area(ring)
    pts = [list(p) for p in ring]
    if area < 0:
        pts.reverse()
        area = -area
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    char = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    inset = min(inset, char * 0.22)
    n = len(pts)
    out: list[list[float]] = []
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        e0x, e0y = p1[0] - p0[0], p1[1] - p0[1]
        e1x, e1y = p2[0] - p1[0], p2[1] - p1[1]
        l0 = math.hypot(e0x, e0y) or 1.0
        l1 = math.hypot(e1x, e1y) or 1.0
        n0x, n0y = -e0y / l0, e0x / l0  # inward for CCW
        n1x, n1y = -e1y / l1, e1x / l1
        bx, by = n0x + n1x, n0y + n1y
        bl = math.hypot(bx, by)
        if bl < 1e-9:
            bx, by = n0x, n0y
            bl = 1.0
        bx, by = bx / bl, by / bl
        cos_half = max(0.2, min(1.0, n0x * bx + n0y * by))
        d = inset / cos_half
        out.append([p1[0] + bx * d, p1[1] + by * d])
    new_area = abs(_ring_signed_area(out))
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    if new_area < area * 0.12 or new_area > area * 0.99:
        scale = max(0.55, 1.0 - inset / max(char * 0.5, 1.0))
        return [[cx + (p[0] - cx) * scale, cy + (p[1] - cy) * scale] for p in pts]
    fixed: list[list[float]] = []
    for x, y in out:
        if _point_in_ring(x, y, pts):
            fixed.append([x, y])
            continue
        fx, fy = x, y
        for _ in range(8):
            fx = cx + (fx - cx) * 0.7
            fy = cy + (fy - cy) * 0.7
            if _point_in_ring(fx, fy, pts):
                break
        fixed.append([fx, fy])
    return fixed


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


def _prism_roof_ok(ring: list[list[float]], min_fill: float = 0.82) -> bool:
    """Gable OBB prism only when the footprint nearly fills its OBB (no L-corners)."""
    if len(ring) < 3:
        return False
    cx, cy, ux, uy, vx, vy, hu, hv = _obb(ring)
    ring_area = abs(_ring_signed_area(ring))
    obb_area = 4.0 * hu * hv
    if obb_area < 1e-3 or ring_area / obb_area < min_fill:
        return False
    for su, sv in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
        ix = cx + su * hu * 0.92 * ux + sv * hv * 0.92 * vx
        iy = cy + su * hu * 0.92 * uy + sv * hv * 0.92 * vy
        if not _point_in_ring(ix, iy, ring):
            return False
    return True


def add_gable_roof(name: str, ring: list[list[float]], z0: float, roof_h: float, mat) -> None:
    cx, cy, ux, uy, vx, vy, hu, hv = _obb(ring)
    # Clamp half-extents so eave corners stay inside the wall ring.
    hu = max(0.45, hu - 0.08)
    hv = max(0.45, hv - 0.08)
    for _ in range(28):
        ok = True
        for su, sv in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
            ix = cx + su * hu * 0.98 * ux + sv * hv * 0.98 * vx
            iy = cy + su * hu * 0.98 * uy + sv * hv * 0.98 * vy
            if not _point_in_ring(ix, iy, ring):
                ok = False
                break
        if ok:
            break
        hu *= 0.9
        hv *= 0.9
        if hu < 0.45 or hv < 0.45:
            add_mansard_roof(name, ring, z0, roof_h, mat)
            return
    h = max(1.0, roof_h)
    # Four eave corners + ridge line along long axis — base exactly at eaves_z (z0).
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
    # Use a slight inset so hip faces sit on the wall plate, not past it.
    base_ring = inset_ring(ring, 0.05)
    if len(base_ring) < 3:
        base_ring = ring
    cx = sum(p[0] for p in base_ring) / len(base_ring)
    cy = sum(p[1] for p in base_ring) / len(base_ring)
    peak = (cx, cy, z0 + max(1.0, roof_h))
    base = [(p[0], p[1], z0) for p in base_ring]
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


def add_mansard_roof(name: str, ring: list[list[float]], z0: float, roof_h: float, mat) -> None:
    """Two inset extruded plates — stays inside footprint for irregular rings."""
    h = max(0.35, roof_h)
    lower = inset_ring(ring, 0.55)
    add_ring(f"{name}_a", lower, h * 0.55, z0, mat)
    upper = inset_ring(ring, 1.25)
    add_ring(f"{name}_b", upper, h * 0.45, z0 + h * 0.55, mat)


def add_lod2_roof(name: str, ring, eaves_z: float, roof_h: float, shape: str, mat) -> None:
    h = max(0.35, roof_h)
    # Irregular / L-shaped footprints: OBB gables spill past walls — use mansard.
    if shape in {"gable", "hip"} and not _prism_roof_ok(ring):
        shape = "mansard"
    if shape == "flat":
        # Slight inset so flat caps don't Z-fight or overhang sidewalks.
        add_ring(name, inset_ring(ring, 0.04), min(0.55, h), eaves_z, mat)
    elif shape == "hip":
        add_hip_roof(name, ring, eaves_z, h, mat)
    elif shape == "gable":
        add_gable_roof(name, ring, eaves_z, h, mat)
    else:  # mansard
        add_mansard_roof(name, ring, eaves_z, h, mat)


def add_chimneys(name: str, ring: list[list[float]], eaves_z: float, roof_h: float, mat, seed: int) -> int:
    """Brick chimney stubs — GTA3 skyline grit, only a few per roof."""
    if len(ring) < 3:
        return 0
    safe = inset_ring(ring, 1.15)
    if len(safe) < 3:
        safe = inset_ring(ring, 0.6)
    if len(safe) < 3:
        return 0
    cx = sum(p[0] for p in safe) / len(safe)
    cy = sum(p[1] for p in safe) / len(safe)
    if not _point_in_ring(cx, cy, safe):
        return 0
    n = 1 + (seed % 3)
    placed = 0
    for i in range(n):
        u = ((seed * 1103515245 + i * 9973) & 0x7FFFFFFF) / 0x7FFFFFFF
        v = ((seed * 1664525 + i * 4243) & 0x7FFFFFFF) / 0x7FFFFFFF
        x = cx + (u - 0.5) * 2.4
        y = cy + (v - 0.5) * 2.4
        if not _point_in_ring(x, y, safe):
            x, y = cx, cy
        if not _point_in_ring(x, y, safe):
            continue
        z = eaves_z + roof_h * 0.85 + 0.7
        stack = add_box(f"{name}_chim{i}", (0.55, 0.45, 1.4), (x, y, z), u * 0.2)
        assign(stack, mat)
        cap = add_box(f"{name}_chimcap{i}", (0.7, 0.58, 0.12), (x, y, z + 0.75), 0.0)
        assign(cap, mat)
        placed += 1
    return placed


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
    window_kind: str | None = None,
    near_spawn: bool = False,
) -> None:
    """One batched mesh per street edge (skin, plinth, cornice, windows)."""
    style = style_of(style_name)
    mat_key = style_name if style_name in mats["wall"] else (
        style_name.split("__v")[0] if "__v" in style_name else "eclectic"
    )
    if mat_key not in mats["wall"]:
        mat_key = "eclectic" if "eclectic" in mats["wall"] else next(iter(mats["wall"]))
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
    # 0 wall, 1 plinth, 2 trim, 3 frame, 4 glass, 5 ivy, 6 shutter/awning fabric
    for key in ("wall", "plinth", "trim", "frame", "glass"):
        mesh.materials.append(mats[key].get(style_name) or mats[key][mat_key])
    ivy_mats = mats.get("ivy") or []
    shutter_mats = mats.get("shutter") or []
    accent_seed = sum(ord(c) for c in name) if name else 0
    mesh.materials.append(
        ivy_mats[accent_seed % len(ivy_mats)] if ivy_mats else mats["plinth"][mat_key]
    )
    mesh.materials.append(
        shutter_mats[accent_seed % len(shutter_mats)] if shutter_mats else mats["frame"][mat_key]
    )

    bm = bmesh.new()
    plinth_h = min(1.25, max(0.9, eaves_z * 0.11))
    # Skin slightly proud of the LOD1 block so façades cast readable depth.
    _append_box(bm, ox, oy, eaves_z * 0.5, length * 0.98, 0.1, eaves_z, yaw, 0)
    # Plinth: thicker base + grit bands (soot ledge + scuffed skirting).
    _append_box(bm, ox + nx * 0.05, oy + ny * 0.05, plinth_h * 0.5, length * 0.98, 0.18, plinth_h, yaw, 1)
    _append_box(
        bm,
        ox + nx * 0.09,
        oy + ny * 0.09,
        0.12,
        length * 0.99,
        0.1,
        0.14,
        yaw,
        1,
    )
    if detail == "full":
        _append_box(
            bm,
            ox + nx * 0.08,
            oy + ny * 0.08,
            plinth_h - 0.08,
            length * 0.96,
            0.08,
            0.1,
            yaw,
            1,
        )
    # Cornice: deep main ledge + thinner crown for century silhouette.
    _append_box(bm, ox + nx * 0.12, oy + ny * 0.12, eaves_z + 0.1, length * 1.02, 0.34, 0.38, yaw, 2)
    _append_box(bm, ox + nx * 0.18, oy + ny * 0.18, eaves_z + 0.28, length * 1.0, 0.2, 0.12, yaw, 2)
    # Vertical soot / rain-stain streaks — century façades aren't pristine.
    if detail == "full" and length > 5.0:
        for si in range(1 + int(length // 7.0)):
            along = -length * 0.35 + si * 2.8
            sx = ox + math.cos(yaw) * along + nx * 0.11
            sy = oy + math.sin(yaw) * along + ny * 0.11
            _append_box(bm, sx, sy, eaves_z * 0.42, 0.32, 0.06, eaves_z * 0.75, yaw, 1)

    kind = window_kind or style.get("window", "rect")
    floors = max(1, min(8, int(floors)))
    if detail == "simple":
        floors = min(floors, 3)
    floor_h = eaves_z / max(1, floors)
    bay_pitch = 4.2 if kind == "ribbon" else (2.8 if detail == "simple" else 2.35)
    bays = max(1, int(length / bay_pitch))
    bay_w = length / bays
    win_w = max(0.55, bay_w * (0.85 if kind == "ribbon" else 0.64))
    door_bay = bays // 2

    # Speklagen / string courses between floors — biggest cheap depth read vs flat boxes.
    if detail == "full":
        for fi in range(1, floors):
            z_band = fi * floor_h
            _append_box(
                bm,
                ox + nx * 0.12,
                oy + ny * 0.12,
                z_band,
                length * 0.98,
                0.14,
                0.16,
                yaw,
                2,
            )

    # Spawn-local ivy cascade near façade corners (batched, shared ivy slot).
    if near_spawn and detail == "full" and length > 4.0:
        for corner_along, ivy_h in ((-length * 0.42, min(4.2, eaves_z * 0.55)), (length * 0.38, min(3.2, eaves_z * 0.4))):
            ix = ox + math.cos(yaw) * corner_along + nx * 0.16
            iy = oy + math.sin(yaw) * corner_along + ny * 0.16
            _append_box(bm, ix, iy, ivy_h * 0.45, 0.55, 0.22, ivy_h, yaw, 5)
            _append_box(
                bm,
                ix + nx * 0.12,
                iy + ny * 0.12,
                ivy_h * 0.28,
                0.85,
                0.35,
                ivy_h * 0.35,
                yaw,
                5,
            )

    for fi in range(floors):
        z_base = fi * floor_h
        for bi in range(bays):
            along = -length * 0.5 + (bi + 0.5) * bay_w
            px = ox + math.cos(yaw) * along + nx * 0.14
            py = oy + math.sin(yaw) * along + ny * 0.14
            if fi == 0 and bi == door_bay:
                dh = min(2.35, floor_h * 0.75)
                door_w = min(1.15, win_w * 0.9)
                # Recessed door plane — stoop starts at the reveal and steps out.
                _append_box(
                    bm,
                    px - nx * 0.06,
                    py - ny * 0.06,
                    plinth_h + dh * 0.5,
                    door_w,
                    0.12,
                    dh,
                    yaw,
                    3,
                )
                if detail == "full":
                    # Continuous stoop: top tread at door sill, lower tread toward sidewalk.
                    _append_box(
                        bm,
                        px + nx * 0.02,
                        py + ny * 0.02,
                        0.22,
                        door_w * 1.05,
                        0.2,
                        0.22,
                        yaw,
                        1,
                    )
                    _append_box(
                        bm,
                        px + nx * 0.16,
                        py + ny * 0.16,
                        0.14,
                        door_w * 1.12,
                        0.24,
                        0.14,
                        yaw,
                        1,
                    )
                continue
            # Shop awnings on ground-floor bays — lived-in street rhythm.
            if detail == "full" and fi == 0 and bi % 3 == 1 and kind != "ribbon":
                aw_z = plinth_h + floor_h * 0.55
                _append_box(
                    bm,
                    px + nx * 0.45,
                    py + ny * 0.45,
                    aw_z,
                    win_w * 1.1,
                    0.55,
                    0.08,
                    yaw,
                    6,
                )
                # Ground-level shop sign board hanging under the awning.
                _append_box(
                    bm,
                    px + nx * 0.38,
                    py + ny * 0.38,
                    aw_z - 0.28,
                    win_w * 0.85,
                    0.06,
                    0.32,
                    yaw,
                    6,
                )
            if kind == "ribbon":
                wh, ww = floor_h * 0.52, bay_w * 0.88
            elif kind == "tall":
                wh, ww = floor_h * 0.62, win_w * 0.75
            elif kind == "arch":
                wh, ww = floor_h * 0.58, win_w * 0.9
            else:
                wh, ww = floor_h * (0.42 if fi == 0 else 0.5), win_w
            sill = (plinth_h + 0.35) if fi == 0 else (z_base + floor_h * 0.22)
            # Deep reveal: thick frame, glass inset, sill + lintel — windows as holes.
            _append_box(bm, px, py, sill + wh * 0.5, ww + 0.14, 0.14, wh + 0.14, yaw, 3)
            _append_box(
                bm,
                px + nx * 0.05,
                py + ny * 0.05,
                sill + wh * 0.5,
                ww * 0.92,
                0.05,
                wh * 0.92,
                yaw,
                4,
            )
            if detail == "full":
                # Mullion + sill shelf + lintel for century grit.
                _append_box(
                    bm,
                    px + nx * 0.06,
                    py + ny * 0.06,
                    sill + wh * 0.5,
                    0.08,
                    0.04,
                    wh * 0.9,
                    yaw,
                    3,
                )
                _append_box(
                    bm,
                    px + nx * 0.08,
                    py + ny * 0.08,
                    sill - 0.04,
                    ww + 0.2,
                    0.16,
                    0.08,
                    yaw,
                    2,
                )
                _append_box(
                    bm,
                    px + nx * 0.07,
                    py + ny * 0.07,
                    sill + wh + 0.06,
                    ww + 0.2,
                    0.16,
                    0.1,
                    yaw,
                    2,
                )
                if fi >= 1 and bi % 2 == 0 and kind != "ribbon":
                    _append_box(
                        bm,
                        px + nx * 0.22,
                        py + ny * 0.22,
                        sill - 0.05,
                        ww * 0.95,
                        0.1,
                        0.5,
                        yaw,
                        3,
                    )
                # Paired window shutters — spawn-local only to keep GLB lean.
                if (
                    near_spawn
                    and fi >= 1
                    and kind not in {"ribbon", "tall"}
                    and bi % 2 == 1
                ):
                    shut_w = max(0.18, ww * 0.28)
                    shut_d = 0.05
                    for side in (-1.0, 1.0):
                        sx = px + math.cos(yaw) * side * (ww * 0.5 + shut_w * 0.45) + nx * 0.1
                        sy = py + math.sin(yaw) * side * (ww * 0.5 + shut_w * 0.45) + ny * 0.1
                        _append_box(
                            bm,
                            sx,
                            sy,
                            sill + wh * 0.5,
                            shut_w,
                            shut_d,
                            wh * 0.92,
                            yaw,
                            6,
                        )

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))


def add_building(bldg: dict, mats: dict, spawn_xy: tuple[float, float] | None = None) -> None:
    style_name = style_key_for(bldg)
    type_id = bldg.get("building_type") or bldg.get("style") or "eclectic"
    window_kind = None
    pal = bldg.get("palette") or {}
    if pal.get("window"):
        window_kind = str(pal["window"])
    elif type_id in STYLES:
        window_kind = STYLES[type_id].get("window")
    ring = bldg.get("ring") or []
    if len(ring) < 3:
        return
    bid = bldg.get("id", 0)
    name = f"bldg_{bid}"
    eaves = float(bldg.get("height", 12.0))
    roof_h = float(bldg.get("roof_height") or max(1.2, eaves * 0.15))
    floors = int(bldg.get("floors") or max(1, round(eaves / 3.15)))
    type_roof = (bldg.get("palette") or {}).get("roof_kind") or STYLES.get(type_id, {}).get("roof_kind")
    shape = bldg.get("roof_shape") or type_roof or "mansard"
    wall = mats["wall"].get(style_name) or mats["wall"].get(type_id) or mats["wall"]["eclectic"]
    roof = mats["roof"].get(style_name) or mats["roof"].get(type_id) or mats["roof"]["eclectic"]

    add_ring(name, ring, max(2.5, eaves), 0.0, wall)
    add_lod2_roof(f"{name}_roof", ring, max(2.5, eaves), roof_h, shape, roof)

    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    detail = "full"
    dist = 0.0
    near_spawn = False
    if spawn_xy is not None:
        dist = math.hypot(cx - spawn_xy[0], cy - spawn_xy[1])
        near_spawn = dist <= 95.0
        if dist > 140.0:
            detail = "simple"
        if dist > 360.0:
            # Far LOD1 colour blocks only — still keep roofs.
            return

    if detail == "full" and shape != "flat" and int(bid) % 2 == 0:
        chimney_mat = mats.get("chimney") or roof
        add_chimneys(name, ring, max(2.5, eaves), roof_h, chimney_mat, int(bid) if bid else 1)

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
            window_kind=window_kind,
            near_spawn=near_spawn,
        )


# Vertical layer stack — enough separation to avoid WebGL Z-fighting at street scale.
Z_GROUND = -0.15
Z_ROAD = 0.03
Z_DASH = 0.055
Z_ZEBRA = 0.068
Z_SIDEWALK = 0.09
Z_CURB = 0.13
Z_PARK_PATH = 0.045
Z_TRAM = 0.045


def polyline_mesh(name: str, points: list[list[float]], width: float, z: float = Z_ROAD) -> bpy.types.Mesh | None:
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


def add_road(
    name: str,
    points: list[list[float]],
    width: float,
    mat: bpy.types.Material,
    z: float = Z_ROAD,
) -> bpy.types.Object | None:
    mesh = polyline_mesh(name, points, width, z=z)
    if mesh is None:
        return None
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def offset_polyline(points: list[list[float]], offset: float) -> list[list[float]]:
    """Offset a polyline to the left of travel direction by `offset` metres."""
    if len(points) < 2:
        return []
    out: list[list[float]] = []
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == len(points) - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        out.append([x + nx * offset, y + ny * offset])
    return out


def add_sidewalks_and_curbs(
    roads: list,
    sidewalk_mat,
    curb_mat,
    spawn_xy: tuple[float, float] | None,
) -> int:
    """Sidewalk ribbons + low curbs. Prefer roads near the human spawn for FPS."""
    count = 0
    sidewalk_w = 2.0
    for i, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind in {"footway", "path", "cycleway", "steps"}:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        if spawn_xy is not None:
            mid = pts[len(pts) // 2]
            if math.hypot(mid[0] - spawn_xy[0], mid[1] - spawn_xy[1]) > 320.0:
                continue
        half = float(road.get("width") or 6.0) * 0.5
        for side, sign in (("L", 1.0), ("R", -1.0)):
            walk = offset_polyline(pts, sign * (half + sidewalk_w * 0.5))
            curb = offset_polyline(pts, sign * (half + 0.12))
            if add_road(f"sidewalk_{i}_{side}", walk, sidewalk_w, sidewalk_mat, z=Z_SIDEWALK):
                count += 1
            if add_road(f"curb_{i}_{side}", curb, 0.28, curb_mat, z=Z_CURB):
                count += 1
    return count


def add_parked_cars(
    roads: list,
    spawn_xy: tuple[float, float],
    body_mats: list,
    glass_mat,
    tire_mat,
    max_cars: int = 48,
) -> int:
    """GTA3-simple parked cars along both kerbs near spawn."""
    placed = 0
    for ri, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind not in {"residential", "living_street", "tertiary", "unclassified", "secondary"}:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        half = float(road.get("width") or 6.0) * 0.5
        for side, sign in (("R", -1.0), ("L", 1.0)):
            kerb = offset_polyline(pts, sign * (half - 1.15))
            for i in range(len(kerb) - 1):
                x0, y0 = kerb[i]
                x1, y1 = kerb[i + 1]
                seg = math.hypot(x1 - x0, y1 - y0)
                yaw = math.atan2(y1 - y0, x1 - x0)
                t = 4.0 if side == "L" else 0.0
                while t < seg:
                    if placed >= max_cars:
                        return placed
                    x = x0 + (x1 - x0) * (t / seg if seg else 0)
                    y = y0 + (y1 - y0) * (t / seg if seg else 0)
                    if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > 150.0:
                        t += 18.0
                        continue
                    slot = placed + ri + (0 if side == "R" else 7)
                    if slot % 4 == 0:
                        t += 8.0
                        continue
                    body = add_box(f"car_{placed}", (4.2, 1.75, 1.35), (x, y, 0.75), yaw)
                    assign(body, body_mats[placed % len(body_mats)])
                    cabin = add_box(
                        f"car_g_{placed}",
                        (2.0, 1.55, 0.65),
                        (x + math.cos(yaw) * 0.15, y + math.sin(yaw) * 0.15, 1.45),
                        yaw,
                    )
                    assign(cabin, glass_mat)
                    # Four stub wheels — reads as a car from street POV.
                    for wx, wy in ((1.35, 0.85), (1.35, -0.85), (-1.35, 0.85), (-1.35, -0.85)):
                        lx = x + math.cos(yaw) * wx - math.sin(yaw) * wy
                        ly = y + math.sin(yaw) * wx + math.cos(yaw) * wy
                        wheel = add_box(f"car_w_{placed}_{wx}_{wy}", (0.55, 0.22, 0.55), (lx, ly, 0.28), yaw)
                        assign(wheel, tire_mat)
                    placed += 1
                    t += 13.0 + (slot % 5) * 0.9
    return placed


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
    for line in layout.get("transit_lines") or []:
        for x, y in line.get("points") or []:
            xs.append(x)
            ys.append(y)
    for stop in layout.get("transit_stops") or []:
        if stop.get("x") is not None and stop.get("y") is not None:
            xs.append(float(stop["x"]))
            ys.append(float(stop["y"]))
    if not xs:
        return (-200, -200, 200, 200)
    pad = 40.0
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def add_transit_stop(
    name: str,
    x: float,
    y: float,
    mode: str,
    lines: list,
    pole_mat,
    shelter_mat,
    sign_mat,
) -> None:
    """Simple pole + shelter plate; line numbers baked into object names."""
    line_tag = "-".join(str(v) for v in (lines or [])[:4]) or "na"
    pole = add_box(f"{name}_pole_{line_tag}", (0.1, 0.1, 2.6), (x, y, 1.3), 0.0)
    assign(pole, pole_mat)
    # Colour cue: tram yellow-ish sign, bus cream.
    roof = add_box(f"{name}_roof", (1.4, 0.7, 0.06), (x, y + 0.15, 2.55), 0.0)
    assign(roof, shelter_mat)
    panel = add_box(f"{name}_sign_{mode}_{line_tag}", (0.55, 0.05, 0.4), (x, y + 0.28, 2.15), 0.0)
    assign(panel, sign_mat)


def add_transit_layer(layout: dict, spawn_xy: tuple[float, float] | None) -> tuple[int, int]:
    """Draw tram/premetro ribbons and stop shelters. Returns (tracks, stops)."""
    track_mat = principled("tram_track", (0.12, 0.12, 0.13, 1.0), 0.55, metallic=0.35)
    bed_mat = principled("tram_bed", (0.22, 0.22, 0.2, 1.0), 0.9)
    pole_mat = principled("transit_pole", (0.2, 0.2, 0.22, 1.0), 0.45, metallic=0.4)
    shelter_mat = principled("transit_shelter", (0.55, 0.55, 0.52, 1.0), 0.55, metallic=0.25)
    tram_sign = principled("tram_sign", (0.85, 0.55, 0.12, 1.0), 0.4)
    bus_sign = principled("bus_sign", (0.15, 0.45, 0.7, 1.0), 0.4)
    tracks = 0
    for i, line in enumerate(layout.get("transit_lines") or []):
        mode = line.get("mode") or "bus"
        if mode not in {"tram", "subway"}:
            continue
        if line.get("source") == "gtfs":
            # Prefer OSM track geometry for static rails.
            continue
        pts = line.get("points") or []
        if len(pts) < 2:
            continue
        wid = 2.4 if mode == "tram" else 2.8
        if add_road(f"tram_{line.get('id', i)}", pts, wid, bed_mat, z=Z_TRAM):
            tracks += 1
        # Twin rails as thinner overlays.
        left = offset_polyline(pts, 0.55)
        right = offset_polyline(pts, -0.55)
        add_road(f"rail_l_{line.get('id', i)}", left, 0.18, track_mat, z=Z_TRAM + 0.01)
        add_road(f"rail_r_{line.get('id', i)}", right, 0.18, track_mat, z=Z_TRAM + 0.01)

    stops_n = 0
    for i, stop in enumerate(layout.get("transit_stops") or []):
        x = float(stop.get("x") or 0.0)
        y = float(stop.get("y") or 0.0)
        if spawn_xy is not None and math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > 320.0:
            continue
        mode = stop.get("mode") or "bus"
        lines = stop.get("lines") or stop.get("refs") or []
        sign_mat = tram_sign if mode in {"tram", "subway"} else bus_sign
        add_transit_stop(
            f"stop_{stop.get('id', i)}",
            x,
            y,
            mode,
            lines,
            pole_mat,
            shelter_mat,
            sign_mat,
        )
        stops_n += 1
    return tracks, stops_n


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


def add_park_vegetation(parks: list, trunk_mat, canopy_mats: list, bush_mats: list) -> int:
    """Simple trees + bushes inside park polygons. Capped for browser FPS."""
    placed = 0
    max_trees = 260
    max_bushes = 200
    for park in parks:
        ring = park.get("ring") or []
        if len(ring) < 3:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        area = abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))) * 0.5
        n_trees = max(3, min(36, int(area / 650)))
        n_bushes = max(4, min(48, int(area / 380)))
        seed = int(park.get("id") or 1)
        trees_here = 0
        attempts = 0
        while trees_here < n_trees and placed < max_trees and attempts < n_trees * 8:
            attempts += 1
            i = attempts
            u = ((seed * 1103515245 + i * 12345) & 0x7FFFFFFF) / 0x7FFFFFFF
            v = ((seed * 1664525 + i * 1013904223) & 0x7FFFFFFF) / 0x7FFFFFFF
            x = minx + u * (maxx - minx)
            y = miny + v * (maxy - miny)
            if not _point_in_ring(x, y, ring):
                continue
            h = 5.5 + (u * 4.5)
            leaf = canopy_mats[trees_here % len(canopy_mats)]
            trunk = add_box(f"tree_t_{park.get('id')}_{i}", (0.28, 0.28, h * 0.45), (x, y, h * 0.22), 0.0)
            assign(trunk, trunk_mat)
            canopy = add_box(
                f"tree_c_{park.get('id')}_{i}",
                (2.8 + v, 2.7 + u, 3.0 + v * 0.5),
                (x, y, h * 0.58),
                u * 0.4,
            )
            assign(canopy, leaf)
            canopy2 = add_box(
                f"tree_c2_{park.get('id')}_{i}",
                (2.0 + u, 2.2 + v, 2.1),
                (x + (u - 0.5) * 0.9, y + (v - 0.5) * 0.9, h * 0.74),
                v * 0.6,
            )
            assign(canopy2, leaf)
            if trees_here % 3 == 0:
                canopy3 = add_box(
                    f"tree_c3_{park.get('id')}_{i}",
                    (1.5 + v * 0.4, 1.6, 1.5),
                    (x - (u - 0.5) * 0.6, y - (v - 0.5) * 0.5, h * 0.66),
                    u,
                )
                assign(canopy3, leaf)
            placed += 1
            trees_here += 1
        bushes_here = 0
        attempts = 0
        while bushes_here < n_bushes and placed < max_trees + max_bushes and attempts < n_bushes * 8:
            attempts += 1
            i = attempts
            u = ((seed * 214013 + i * 2531011) & 0x7FFFFFFF) / 0x7FFFFFFF
            v = ((seed * 1103515245 + i * 99991) & 0x7FFFFFFF) / 0x7FFFFFFF
            x = minx + u * (maxx - minx)
            y = miny + v * (maxy - miny)
            if not _point_in_ring(x, y, ring):
                continue
            bush = add_box(
                f"bush_{park.get('id')}_{i}",
                (1.2 + u * 0.7, 1.2 + v * 0.7, 0.95 + u * 0.55),
                (x, y, 0.5),
                0.0,
            )
            assign(bush, bush_mats[bushes_here % len(bush_mats)])
            placed += 1
            bushes_here += 1
    return placed


_DRIVEABLE_SIGNAL_KINDS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
}


def _nearest_road_hit(
    px: float, py: float, roads: list
) -> tuple[float, float, float, float, float, float] | None:
    """Closest driveable centreline sample: cx, cy, tx, ty, width, dist."""
    best: tuple[float, float, float, float, float, float] | None = None
    for road in roads:
        kind = road.get("kind") or "residential"
        if kind not in _DRIVEABLE_SIGNAL_KINDS:
            continue
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 < 1e-6:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
            cx, cy = ax + t * dx, ay + t * dy
            dist = math.hypot(px - cx, py - cy)
            if best is None or dist < best[5]:
                length = math.sqrt(len2)
                best = (cx, cy, dx / length, dy / length, width, dist)
    return best


def _cluster_signal_nodes(
    nodes: list[tuple[float, float]],
    *,
    merge_m: float = 12.0,
) -> list[tuple[float, float]]:
    """Deduplicate OSM signal nodes; one cluster centroid per intersection."""
    clusters: list[list[tuple[float, float]]] = []
    for x, y in nodes:
        placed = False
        for cluster in clusters:
            cx = sum(p[0] for p in cluster) / len(cluster)
            cy = sum(p[1] for p in cluster) / len(cluster)
            if math.hypot(x - cx, y - cy) <= merge_m:
                cluster.append((x, y))
                placed = True
                break
        if not placed:
            clusters.append([(x, y)])
    out: list[tuple[float, float]] = []
    for cluster in clusters:
        out.append(
            (
                sum(p[0] for p in cluster) / len(cluster),
                sum(p[1] for p in cluster) / len(cluster),
            )
        )
    return out


def _approaches_at_junction(
    jx: float, jy: float, roads: list, *, search_r: float = 16.0
) -> list[dict]:
    """Unique inbound approaches (stop-line + curb) around a junction centre."""
    raw: list[dict] = []
    for road in roads:
        kind = road.get("kind") or "residential"
        if kind not in _DRIVEABLE_SIGNAL_KINDS:
            continue
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        if len(pts) < 2:
            continue
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
            for ex, ey, ox, oy in ((ax, ay, bx, by), (bx, by, ax, ay)):
                if math.hypot(ex - jx, ey - jy) > search_r:
                    continue
                dx, dy = ex - ox, ey - oy
                length = math.hypot(dx, dy) or 1.0
                # Inbound tangent: travel toward the junction endpoint.
                tx, ty = dx / length, dy / length
                # Stop-line ~3m before junction along the approach.
                sx = ex - tx * 3.2
                sy = ey - ty * 3.2
                raw.append({"tx": tx, "ty": ty, "sx": sx, "sy": sy, "width": width})
            # Mid-segment projection when the junction sits along a long way.
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 < 1.0:
                continue
            t = max(0.0, min(1.0, ((jx - ax) * dx + (jy - ay) * dy) / len2))
            if t <= 0.02 or t >= 0.98:
                continue
            cx, cy = ax + t * dx, ay + t * dy
            if math.hypot(cx - jx, cy - jy) > search_r * 0.6:
                continue
            length = math.sqrt(len2)
            tx, ty = dx / length, dy / length
            for sign in (1.0, -1.0):
                atx, aty = tx * sign, ty * sign
                sx = jx - atx * 3.2
                sy = jy - aty * 3.2
                raw.append({"tx": atx, "ty": aty, "sx": sx, "sy": sy, "width": width})

    # Angle-bin so we get at most one approach per compass arm.
    bins: dict[int, dict] = {}
    for ap in raw:
        ang = math.atan2(ap["ty"], ap["tx"])
        key = int(round(ang / (math.pi / 4.0))) % 8
        prev = bins.get(key)
        if prev is None:
            bins[key] = ap
            continue
        # Prefer stop-lines closer to a typical 3m offset from junction.
        d_new = abs(math.hypot(ap["sx"] - jx, ap["sy"] - jy) - 3.2)
        d_old = abs(math.hypot(prev["sx"] - jx, prev["sy"] - jy) - 3.2)
        if d_new < d_old:
            bins[key] = ap
    return list(bins.values())[:4]


def collect_signal_placements(
    layout: dict, spawn_xy: tuple[float, float] | None = None
) -> list[dict]:
    """OSM traffic_signals → curb poles + stop-line zebras per approach."""
    roads = layout.get("roads") or []
    raw: list[tuple[float, float]] = []
    for s in layout.get("signals") or []:
        x, y = float(s["x"]), float(s["y"])
        if spawn_xy is not None and math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > 220.0:
            continue
        raw.append((x, y))
    if not raw:
        return []

    if spawn_xy is not None:
        raw.sort(key=lambda p: math.hypot(p[0] - spawn_xy[0], p[1] - spawn_xy[1]))
    clusters = _cluster_signal_nodes(raw, merge_m=12.0)
    if spawn_xy is not None:
        clusters.sort(key=lambda p: math.hypot(p[0] - spawn_xy[0], p[1] - spawn_xy[1]))
    clusters = clusters[:14]

    placements: list[dict] = []
    used_stops: list[tuple[float, float]] = []
    for jx, jy in clusters:
        approaches = _approaches_at_junction(jx, jy, roads)
        if not approaches:
            hit = _nearest_road_hit(jx, jy, roads)
            if hit is None:
                continue
            cx, cy, tx, ty, width, _dist = hit
            approaches = [
                {
                    "tx": tx,
                    "ty": ty,
                    "sx": cx - tx * 3.0,
                    "sy": cy - ty * 3.0,
                    "width": width,
                }
            ]
        for ap in approaches:
            sx, sy = ap["sx"], ap["sy"]
            if any(math.hypot(sx - ux, sy - uy) < 5.5 for ux, uy in used_stops):
                continue
            used_stops.append((sx, sy))
            tx, ty = ap["tx"], ap["ty"]
            width = float(ap["width"])
            half = width * 0.5
            # Right-hand curb relative to inbound travel.
            rx, ry = ty, -tx
            pole_x = sx + rx * (half + 0.85)
            pole_y = sy + ry * (half + 0.85)
            # Face the head toward oncoming traffic (look back along approach).
            yaw = math.atan2(-ty, -tx)
            placements.append(
                {
                    "pole_x": pole_x,
                    "pole_y": pole_y,
                    "stop_x": sx,
                    "stop_y": sy,
                    "tx": tx,
                    "ty": ty,
                    "yaw": yaw,
                    "width": width,
                    "jx": jx,
                    "jy": jy,
                }
            )
    return placements


def add_traffic_light(
    name: str,
    x: float,
    y: float,
    yaw: float,
    pole_mat,
    housing_mat,
    lamp_mats,
) -> None:
    """Pole on the curb; head faces oncoming traffic."""
    pole = add_box(f"{name}_pole", (0.12, 0.12, 3.4), (x, y, 1.7), yaw)
    assign(pole, pole_mat)
    # Local +Y is the face direction after rot_z=yaw (Blender).
    fx, fy = math.cos(yaw), math.sin(yaw)
    hx, hy = x + fx * 0.2, y + fy * 0.2
    head = add_box(f"{name}_head", (0.28, 0.22, 0.85), (hx, hy, 3.55), yaw)
    assign(head, housing_mat)
    for i, mat in enumerate(lamp_mats):
        lx = hx + fx * 0.14
        ly = hy + fy * 0.14
        lamp = add_box(f"{name}_l{i}", (0.16, 0.08, 0.16), (lx, ly, 3.85 - i * 0.26), yaw)
        assign(lamp, mat)


def add_crosswalks(placements: list[dict], stripe_mat, spawn_xy) -> int:
    """One zebra set per approach: stripes perpendicular to road tangent."""
    count = 0
    for i, pl in enumerate(placements):
        sx, sy = float(pl["stop_x"]), float(pl["stop_y"])
        if spawn_xy is not None and math.hypot(sx - spawn_xy[0], sy - spawn_xy[1]) > 220.0:
            continue
        tx, ty = float(pl["tx"]), float(pl["ty"])
        width = float(pl.get("width") or 6.0)
        # Travel yaw: stripe long axis is across the carriageway (local Y after rot).
        yaw = math.atan2(ty, tx)
        span = max(3.2, min(7.5, width * 0.92))
        n_stripes = 5
        for s in range(n_stripes):
            along = -1.6 + s * 0.8
            cx = sx + tx * along
            cy = sy + ty * along
            # Thin along travel (X), wide across road (Y).
            stripe = add_box(
                f"zebra_{i}_{s}",
                (0.42, span, 0.02),
                (cx, cy, Z_ZEBRA),
                yaw,
            )
            assign(stripe, stripe_mat)
            count += 1
    return count


def add_street_furniture(
    roads: list,
    spawn_xy: tuple[float, float],
    metal_mat,
    wood_mat,
    bin_mat,
    lamp_head_mat,
    trunk_mat,
    canopy_mats: list,
) -> dict:
    """Lamp posts, bollards, bins, benches, and sidewalk trees near the spawn."""
    stats = {"lamps": 0, "bollards": 0, "bins": 0, "benches": 0, "street_trees": 0, "bike_racks": 0}
    max_lamps, max_bollards, max_bins, max_benches, max_trees = 42, 70, 24, 16, 48
    for ri, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind in {"footway", "path", "cycleway", "steps"}:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        mid = pts[len(pts) // 2]
        if math.hypot(mid[0] - spawn_xy[0], mid[1] - spawn_xy[1]) > 170.0:
            continue
        half = float(road.get("width") or 6.0) * 0.5
        # Trees on left band, clutter on right — dedicated cadences so they don't starve.
        tree_band = offset_polyline(pts, half + 1.35)
        clutter_band = offset_polyline(pts, -(half + 1.05))
        for band, mode in ((tree_band, "trees"), (clutter_band, "clutter")):
            dist = 0.0
            step = 16.0 if mode == "trees" else 7.0
            for i in range(len(band) - 1):
                x0, y0 = band[i]
                x1, y1 = band[i + 1]
                seg = math.hypot(x1 - x0, y1 - y0)
                yaw = math.atan2(y1 - y0, x1 - x0)
                t = 3.0 + (ri % 5)
                while t < seg:
                    x = x0 + (x1 - x0) * (t / seg if seg else 0)
                    y = y0 + (y1 - y0) * (t / seg if seg else 0)
                    if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > 155.0:
                        t += step
                        continue
                    slot = int(dist + t + ri)
                    if mode == "trees" and kind in {
                        "residential",
                        "living_street",
                        "tertiary",
                        "unclassified",
                        "secondary",
                    }:
                        if stats["street_trees"] < max_trees and slot % 2 == 0:
                            h = 5.0 + (slot % 5) * 0.4
                            leaf = canopy_mats[stats["street_trees"] % len(canopy_mats)]
                            trunk = add_box(
                                f"stree_t_{stats['street_trees']}",
                                (0.22, 0.22, h * 0.4),
                                (x, y, h * 0.2),
                                0.0,
                            )
                            assign(trunk, trunk_mat)
                            canopy = add_box(
                                f"stree_c_{stats['street_trees']}",
                                (2.4, 2.3, 2.6),
                                (x, y, h * 0.55),
                                yaw * 0.2,
                            )
                            assign(canopy, leaf)
                            canopy2 = add_box(
                                f"stree_c2_{stats['street_trees']}",
                                (1.7, 1.8, 1.7),
                                (x + 0.4, y - 0.2, h * 0.7),
                                0.3,
                            )
                            assign(canopy2, leaf)
                            stats["street_trees"] += 1
                    else:
                        kind_slot = slot % 5
                        if kind_slot == 0 and stats["lamps"] < max_lamps:
                            pole = add_box(f"lamp_{stats['lamps']}", (0.1, 0.1, 4.6), (x, y, 2.3), 0.0)
                            assign(pole, metal_mat)
                            head = add_box(
                                f"lamp_h_{stats['lamps']}",
                                (0.55, 0.35, 0.2),
                                (x + math.cos(yaw) * 0.15, y + math.sin(yaw) * 0.15, 4.55),
                                yaw,
                            )
                            assign(head, lamp_head_mat)
                            stats["lamps"] += 1
                        elif kind_slot == 1 and stats["bollards"] < max_bollards:
                            boll = add_box(
                                f"bollard_{stats['bollards']}",
                                (0.18, 0.18, 0.75),
                                (x, y, 0.38),
                                0.0,
                            )
                            assign(boll, metal_mat)
                            stats["bollards"] += 1
                        elif kind_slot == 2 and stats["bins"] < max_bins:
                            bin_obj = add_box(
                                f"bin_{stats['bins']}",
                                (0.45, 0.45, 0.85),
                                (x, y, 0.42),
                                yaw,
                            )
                            assign(bin_obj, bin_mat)
                            stats["bins"] += 1
                        elif kind_slot == 3 and stats["benches"] < max_benches:
                            seat = add_box(
                                f"bench_{stats['benches']}",
                                (1.6, 0.42, 0.12),
                                (x, y, 0.42),
                                yaw,
                            )
                            assign(seat, wood_mat)
                            back = add_box(
                                f"bench_b_{stats['benches']}",
                                (1.6, 0.08, 0.55),
                                (x - math.sin(yaw) * 0.18, y + math.cos(yaw) * 0.18, 0.72),
                                yaw,
                            )
                            assign(back, wood_mat)
                            stats["benches"] += 1
                        elif kind_slot == 4 and stats.get("bike_racks", 0) < 20:
                            # Simple U-rack pair.
                            for k, off in enumerate((-0.35, 0.35)):
                                rack = add_box(
                                    f"bike_{stats.get('bike_racks', 0)}_{k}",
                                    (0.08, 0.55, 0.85),
                                    (x + math.cos(yaw) * off, y + math.sin(yaw) * off, 0.42),
                                    yaw,
                                )
                                assign(rack, metal_mat)
                            stats["bike_racks"] = stats.get("bike_racks", 0) + 1
                    t += step + (slot % 3) * 0.8
                dist += seg
    return stats


def add_park_amenities(
    parks: list,
    spawn_xy: tuple[float, float] | None,
    wood_mat,
    path_mat,
    hedge_mat,
    max_benches: int = 36,
) -> dict:
    """Park benches, gravel paths, and edge hedges so greens read usable from the street."""
    stats = {"benches": 0, "paths": 0, "hedges": 0}
    for park in parks:
        ring = park.get("ring") or []
        if len(ring) < 3:
            continue
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        if spawn_xy is not None and math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) > 220.0:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        seed = int(park.get("id") or 1)
        path_pts = [
            [cx - 8.0, cy - 2.0],
            [cx, cy],
            [cx + 8.0, cy + 1.5],
        ]
        if add_road(f"park_path_{park.get('id')}", path_pts, 1.6, path_mat, z=Z_PARK_PATH):
            stats["paths"] += 1
        # Hedge segments along every other park edge.
        for ei in range(0, len(ring), 2):
            if stats["hedges"] >= 80:
                break
            p0 = ring[ei]
            p1 = ring[(ei + 1) % len(ring)]
            length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if length < 3.0 or length > 28.0:
                continue
            mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
            yaw = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
            hedge = add_box(
                f"hedge_{park.get('id')}_{ei}",
                (min(length * 0.85, 12.0), 0.55, 1.15),
                (mx, my, 0.55),
                yaw,
            )
            assign(hedge, hedge_mat)
            stats["hedges"] += 1
        for i in range(3):
            if stats["benches"] >= max_benches:
                return stats
            u = ((seed * 1103515245 + i * 777) & 0x7FFFFFFF) / 0x7FFFFFFF
            v = ((seed * 1664525 + i * 333) & 0x7FFFFFFF) / 0x7FFFFFFF
            x = min(xs) + u * (max(xs) - min(xs))
            y = min(ys) + v * (max(ys) - min(ys))
            if not _point_in_ring(x, y, ring):
                x, y = cx + (u - 0.5) * 4.0, cy + (v - 0.5) * 4.0
            yaw = u * math.pi
            seat = add_box(f"park_bench_{stats['benches']}", (1.7, 0.42, 0.12), (x, y, 0.42), yaw)
            assign(seat, wood_mat)
            back = add_box(
                f"park_bench_b_{stats['benches']}",
                (1.7, 0.08, 0.55),
                (x - math.sin(yaw) * 0.18, y + math.cos(yaw) * 0.18, 0.72),
                yaw,
            )
            assign(back, wood_mat)
            stats["benches"] += 1
    return stats


def add_road_dashes(roads: list, spawn_xy: tuple[float, float], dash_mat, max_dashes: int = 120) -> int:
    """Center-line dashes near spawn — cheap GTA3 asphalt read."""
    placed = 0
    for ri, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind not in {"residential", "tertiary", "secondary", "unclassified", "primary"}:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        mid = pts[len(pts) // 2]
        if math.hypot(mid[0] - spawn_xy[0], mid[1] - spawn_xy[1]) > 180.0:
            continue
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            seg = math.hypot(x1 - x0, y1 - y0)
            yaw = math.atan2(y1 - y0, x1 - x0)
            t = 2.0 + (ri % 4)
            while t < seg - 1.0:
                if placed >= max_dashes:
                    return placed
                x = x0 + (x1 - x0) * (t / seg)
                y = y0 + (y1 - y0) * (t / seg)
                if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) <= 160.0:
                    dash = add_box(f"dash_{placed}", (1.6, 0.14, 0.02), (x, y, Z_DASH), yaw)
                    assign(dash, dash_mat)
                    placed += 1
                t += 7.5
    return placed


def add_asphalt_wear(
    roads: list,
    spawn_xy: tuple[float, float],
    wear_mats: list,
    max_patches: int = 64,
) -> int:
    """Subtle darker asphalt patches near spawn — worn carriageway without new textures."""
    placed = 0
    for ri, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind not in {"residential", "tertiary", "secondary", "unclassified", "primary", "living_street"}:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        mid = pts[len(pts) // 2]
        if math.hypot(mid[0] - spawn_xy[0], mid[1] - spawn_xy[1]) > 140.0:
            continue
        half = float(road.get("width") or 6.0) * 0.28
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            seg = math.hypot(x1 - x0, y1 - y0)
            yaw = math.atan2(y1 - y0, x1 - x0)
            t = 4.0 + (ri % 5) * 1.2
            while t < seg - 2.0:
                if placed >= max_patches:
                    return placed
                x = x0 + (x1 - x0) * (t / seg)
                y = y0 + (y1 - y0) * (t / seg)
                if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) <= 120.0:
                    # Alternate centre blotches and kerb-side tyre wear.
                    side = 1.0 if (placed % 3) else 0.0
                    ox = x + math.cos(yaw + math.pi * 0.5) * half * side * (1.0 if placed % 2 == 0 else -1.0)
                    oy = y + math.sin(yaw + math.pi * 0.5) * half * side * (1.0 if placed % 2 == 0 else -1.0)
                    patch = add_box(
                        f"asphalt_wear_{placed}",
                        (2.4 + (placed % 3) * 0.4, 0.9 + (placed % 2) * 0.35, 0.015),
                        (ox, oy, Z_ROAD + 0.008),
                        yaw,
                    )
                    assign(patch, wear_mats[placed % len(wear_mats)])
                    placed += 1
                t += 11.0 + (ri % 3)
    return placed


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


def build(layout: dict, types_doc: dict | None = None) -> None:
    reset_scene()
    if types_doc is None:
        # Fallback: assets/styles/building_types.json next to the job root.
        for candidate in (
            layout.get("building_types_path"),
            str(Path(__file__).resolve().parents[1] / "assets" / "styles" / "building_types.json"),
        ):
            if candidate and Path(candidate).exists():
                types_doc = json.loads(Path(candidate).read_text())
                break
    merge_building_types(types_doc)
    if types_doc:
        print(f"Building types loaded: {len(types_doc.get('types') or {})}")
    xmin, ymin, xmax, ymax = bounds(layout)
    ground = bpy.data.meshes.new("ground")
    ground.from_pydata(
        [
            (xmin, ymin, Z_GROUND),
            (xmax, ymin, Z_GROUND),
            (xmax, ymax, Z_GROUND),
            (xmin, ymax, Z_GROUND),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    ground.update()
    assign(link(bpy.data.objects.new("ground", ground)), principled("ground", (0.74, 0.73, 0.68, 1.0), 0.95))

    water_mat = principled("water", (0.18, 0.32, 0.42, 1.0), 0.12)
    park_mat = principled("park", (0.28, 0.48, 0.26, 1.0), 0.92)
    road_mat = principled("asphalt", (0.08, 0.08, 0.09, 1.0), 0.96)
    sidewalk_mat = principled("sidewalk", (0.55, 0.54, 0.50, 1.0), 0.95)
    curb_mat = principled("curb", (0.42, 0.41, 0.38, 1.0), 0.9)
    trunk_mat = principled("trunk", (0.28, 0.18, 0.10, 1.0), 0.9)
    # Varied park canopy: deep shade, sun-lit lime, dusty summer olive.
    canopy_mats = [
        principled("canopy_a", (0.16, 0.40, 0.13, 1.0), 0.9),
        principled("canopy_b", (0.24, 0.44, 0.14, 1.0), 0.86),
        principled("canopy_c", (0.12, 0.32, 0.15, 1.0), 0.92),
        principled("canopy_d", (0.30, 0.42, 0.16, 1.0), 0.84),
        principled("canopy_e", (0.20, 0.36, 0.10, 1.0), 0.88),
    ]
    bush_mats = [
        principled("bush_a", (0.20, 0.34, 0.11, 1.0), 0.92),
        principled("bush_b", (0.26, 0.38, 0.14, 1.0), 0.9),
        principled("bush_c", (0.18, 0.30, 0.12, 1.0), 0.94),
    ]
    ivy_mats = [
        principled("ivy_a", (0.14, 0.30, 0.10, 1.0), 0.92),
        principled("ivy_b", (0.18, 0.34, 0.12, 1.0), 0.9),
    ]
    shutter_mats = [
        principled("shutter_green", (0.18, 0.28, 0.16, 1.0), 0.75),
        principled("shutter_cream", (0.72, 0.66, 0.48, 1.0), 0.78),
        principled("shutter_blue", (0.22, 0.28, 0.38, 1.0), 0.72),
    ]
    wear_mats = [
        principled("asphalt_wear_a", (0.05, 0.05, 0.055, 1.0), 0.98),
        principled("asphalt_wear_b", (0.10, 0.09, 0.08, 1.0), 0.97),
    ]
    dash_mat = principled("road_dash", (0.82, 0.78, 0.55, 1.0), 0.9)
    path_mat = principled("park_path", (0.48, 0.42, 0.32, 1.0), 0.95)
    chimney_mat = principled("chimney_brick", (0.32, 0.18, 0.14, 1.0), 0.9)
    pole_mat = principled("pole", (0.18, 0.18, 0.18, 1.0), 0.5, metallic=0.4)
    housing_mat = principled("tl_housing", (0.08, 0.08, 0.08, 1.0), 0.45, metallic=0.35)
    lamp_mats = [
        principled("tl_red", (0.85, 0.12, 0.08, 1.0), 0.25),
        principled("tl_amber", (0.9, 0.55, 0.08, 1.0), 0.25),
        principled("tl_green", (0.12, 0.7, 0.22, 1.0), 0.25),
    ]
    car_mats = [
        principled("car_black", (0.08, 0.08, 0.09, 1.0), 0.35, metallic=0.45),
        principled("car_silver", (0.55, 0.55, 0.56, 1.0), 0.3, metallic=0.55),
        principled("car_red", (0.45, 0.08, 0.06, 1.0), 0.35, metallic=0.35),
        principled("car_blue", (0.12, 0.18, 0.35, 1.0), 0.35, metallic=0.4),
        principled("car_cream", (0.72, 0.68, 0.55, 1.0), 0.4, metallic=0.25),
    ]
    car_glass = principled("car_glass", (0.35, 0.42, 0.48, 1.0), 0.12, metallic=0.1)
    tire_mat = principled("tire", (0.06, 0.06, 0.06, 1.0), 0.95)
    hedge_mat = principled("hedge", (0.16, 0.32, 0.12, 1.0), 0.9)
    stripe_mat = principled("zebra", (0.88, 0.86, 0.78, 1.0), 0.92)
    wood_mat = principled("bench_wood", (0.32, 0.22, 0.12, 1.0), 0.88)
    bin_mat = principled("bin_green", (0.14, 0.28, 0.16, 1.0), 0.65, metallic=0.2)
    lamp_head_mat = principled("lamp_head", (0.75, 0.72, 0.55, 1.0), 0.35)

    # Only bake materials for types/variants present in this tile — keeps GLB lean.
    used_keys = {"eclectic"}
    for bldg in layout.get("buildings") or []:
        used_keys.add(style_key_for(bldg))
        tid = bldg.get("building_type") or bldg.get("style")
        if tid:
            used_keys.add(str(tid))
    style_items = [(n, s) for n, s in STYLES.items() if n in used_keys]
    if not style_items:
        style_items = list(STYLES.items())
    mats = {
        "wall": {n: principled(f"wall_{n}", s["wall"], 0.88) for n, s in style_items},
        "roof": {n: principled(f"roof_{n}", s["roof"], 0.72, metallic=0.05) for n, s in style_items},
        "frame": {n: principled(f"frame_{n}", s["frame"], 0.62, metallic=0.12) for n, s in style_items},
        # Glazier glass — darker, slightly reflective so windows read as openings not stickers.
        "glass": {n: principled(f"glass_{n}", s["glass"], 0.12, metallic=0.35) for n, s in style_items},
        "plinth": {n: principled(f"plinth_{n}", s["plinth"], 0.92) for n, s in style_items},
        "trim": {n: principled(f"trim_{n}", s["trim"], 0.7) for n, s in style_items},
        "chimney": chimney_mat,
        "ivy": ivy_mats,
        "shutter": shutter_mats,
    }
    print(f"Facade material keys: {len(style_items)}")

    spawn = layout.get("spawn") or {}
    spawn_xy = (float(spawn["x"]), float(spawn["y"])) if spawn.get("x") is not None else None

    for i, pond in enumerate(layout.get("water") or []):
        add_ring(f"water_{pond.get('id', i)}", pond["ring"], 0.0, -0.04, water_mat)
    for i, park in enumerate(layout.get("parks") or []):
        add_ring(f"park_{park.get('id', i)}", park["ring"], 0.0, 0.02, park_mat)
    for i, road in enumerate(layout.get("roads") or []):
        add_road(f"road_{road.get('id', i)}", road["points"], float(road["width"]), road_mat, z=Z_ROAD)

    tram_n, stop_n = add_transit_layer(layout, spawn_xy)
    print(f"Transit: {tram_n} tram tracks, {stop_n} stops")

    walks = add_sidewalks_and_curbs(layout.get("roads") or [], sidewalk_mat, curb_mat, spawn_xy)
    print(f"Sidewalk/curb strips: {walks}")

    veg = add_park_vegetation(layout.get("parks") or [], trunk_mat, canopy_mats, bush_mats)
    print(f"Park vegetation props: {veg}")
    park_am = add_park_amenities(layout.get("parks") or [], spawn_xy, wood_mat, path_mat, hedge_mat)
    print(f"Park amenities: {park_am}")

    signal_placements = collect_signal_placements(layout, spawn_xy=spawn_xy)
    for i, pl in enumerate(signal_placements):
        add_traffic_light(
            f"signal_{i}",
            float(pl["pole_x"]),
            float(pl["pole_y"]),
            float(pl["yaw"]),
            pole_mat,
            housing_mat,
            lamp_mats,
        )
    print(f"Traffic lights: {len(signal_placements)}")
    zebras = add_crosswalks(signal_placements, stripe_mat, spawn_xy)
    print(f"Crosswalk stripes: {zebras}")

    if spawn_xy is not None:
        dashes = add_road_dashes(layout.get("roads") or [], spawn_xy, dash_mat)
        print(f"Road dashes near spawn: {dashes}")
        wear = add_asphalt_wear(layout.get("roads") or [], spawn_xy, wear_mats)
        print(f"Asphalt wear patches near spawn: {wear}")
        cars = add_parked_cars(
            layout.get("roads") or [], spawn_xy, car_mats, car_glass, tire_mat, max_cars=48
        )
        print(f"Parked cars near spawn: {cars}")
        furniture = add_street_furniture(
            layout.get("roads") or [],
            spawn_xy,
            pole_mat,
            wood_mat,
            bin_mat,
            lamp_head_mat,
            trunk_mat,
            canopy_mats,
        )
        print(f"Street furniture: {furniture}")

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
    types_doc = job.get("building_types")
    if not types_doc:
        types_path = job.get("building_types_path") or layout.get("building_types_path")
        if types_path and Path(types_path).exists():
            types_doc = json.loads(Path(types_path).read_text())
    build(layout, types_doc=types_doc)
    export_outputs(output_dir, job.get("scene_name", "antwerp_city"), job.get("render", True))


if __name__ == "__main__":
    main()
