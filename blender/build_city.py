"""Build an Antwerp city tile in Blender: LOD2 roofs + street-edge facades."""

from __future__ import annotations

import argparse
import json
import math
import sys
import zlib
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

# Pure-Python rail clearance helpers live in the cityview package (no bpy).
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from cityview import facade_kit, surface_kit  # noqa: E402
from cityview import climbers, kerbs, railclear, rooftop  # noqa: E402
from cityview import parking as parking_plan  # noqa: E402
from cityview.landmarks import LANDMARKS_DIR, resolve_landmark_photo  # noqa: E402
from cityview.railclear import RailIndex  # noqa: E402
from cityview.shop_brands import fascia_for_brand  # noqa: E402
from cityview.signals import face_dir, pedestrian_signal_yaw, vehicle_signal_yaw  # noqa: E402

_BLENDER_DIR = str(Path(__file__).resolve().parent)
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)
import benches_blender  # noqa: E402
import barriers_blender  # noqa: E402
import clutter_blender  # noqa: E402
import courtyards_blender  # noqa: E402
import roadware_blender  # noqa: E402
import trees_blender  # noqa: E402
try:
    import velo_blender  # noqa: E402
except ImportError:  # optional — Velo docks ship separately
    velo_blender = None
try:
    import cars_blender  # noqa: E402
except ImportError:  # optional — Kenney car GLBs; box bodies otherwise
    cars_blender = None

# Surface rail corridors for the current build (set in build()).
RAILS: RailIndex = RailIndex([])

# (building id, street_edges index) -> climbing-plant spec (set in build()).
CLIMBERS: dict[tuple[int, int], dict] = {}
CLIMBER_STATS = {"plants": 0, "leaves": 0}

# Photo-derived facade imagery (committed by cityview.facade_textures).
TEXTURES_DIR = Path(_REPO_ROOT) / "assets" / facade_kit.TEXTURES_DIRNAME
TYPES_DOC: dict | None = None
FACADE_PHOTO_MAT = None  # shared atlas material, set in build()
# Block interiors (yards, gardens, shade) and parks seen from above are dark olive-grey in the
# orthophoto (yard median ~RGB 78/94/103 -> de-blued ~86/97/92; park median ~88/105/106), far
# darker than the old pale gravel / lime grass. Linear Base-Color multipliers measured with
# scripts/topdown_probe.html + scripts/compare_roofs.py so the top-down render lands on those.
GROUND_TINT = (0.061, 0.079, 0.074)
PARK_TINT = (0.42, 0.36, 0.46)
ROOF_AERIAL = surface_kit.load_roof_aerial()  # per-building roof family + tint measured from the orthophoto
SURFACES_DIR = Path(_REPO_ROOT) / "assets" / surface_kit.TEXTURES_DIRNAME  # procedural roofs / paving / grass
PHOTO_MAT_SLOT = 7  # material slot of the atlas on façade meshes
DOORSTEP_MAT = None  # shared granite doorstep material, set in build()
DOORSTEP_MAT_SLOT = 8  # right after the atlas slot
ROOFTOP_STATS = {"chimneys": 0, "plant": 0}
STATS = {"photo_quads": 0, "photo_edges": 0, "door_steps": 0, "awnings": 0, "reveals": 0, "downpipes": 0}


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
    "school": {
        "wall": (0.76, 0.72, 0.64, 1.0),
        "roof": (0.22, 0.20, 0.18, 1.0),
        "frame": (0.18, 0.14, 0.10, 1.0),
        "glass": (0.24, 0.30, 0.34, 1.0),
        "plinth": (0.42, 0.40, 0.36, 1.0),
        "trim": (0.82, 0.78, 0.70, 1.0),
        "window": "rect",
    },
    "restaurant": {
        "wall": (0.80, 0.72, 0.58, 1.0),
        "roof": (0.20, 0.18, 0.16, 1.0),
        "frame": (0.22, 0.14, 0.10, 1.0),
        "glass": (0.22, 0.28, 0.30, 1.0),
        "plinth": (0.70, 0.62, 0.48, 1.0),
        "trim": (0.88, 0.82, 0.70, 1.0),
        "window": "rect",
    },
    "supermarket": {
        "wall": (0.78, 0.78, 0.74, 1.0),
        "roof": (0.18, 0.18, 0.19, 1.0),
        "frame": (0.08, 0.08, 0.09, 1.0),
        "glass": (0.30, 0.36, 0.40, 1.0),
        "plinth": (0.50, 0.50, 0.48, 1.0),
        "trim": (0.85, 0.85, 0.82, 1.0),
        "window": "ribbon",
    },
    "church": {
        "wall": (0.52, 0.28, 0.22, 1.0),
        "roof": (0.14, 0.14, 0.15, 1.0),
        "frame": (0.42, 0.40, 0.36, 1.0),
        "glass": (0.14, 0.20, 0.24, 1.0),
        "plinth": (0.38, 0.36, 0.34, 1.0),
        "trim": (0.62, 0.58, 0.52, 1.0),
        "window": "arch",
        "roof_kind": "hip",
    },
    "hospital": {
        "wall": (0.84, 0.82, 0.76, 1.0),
        "roof": (0.20, 0.20, 0.21, 1.0),
        "frame": (0.08, 0.08, 0.09, 1.0),
        "glass": (0.32, 0.38, 0.42, 1.0),
        "plinth": (0.55, 0.54, 0.50, 1.0),
        "trim": (0.90, 0.88, 0.84, 1.0),
        "window": "ribbon",
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


def load_texture(path: Path):
    """Load a committed texture; None when missing so CI still builds flat colours."""
    if not Path(path).exists():
        print(f"WARNING: texture missing, using flat colour: {path}")
        return None
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "sRGB"
    return img


def image_average(img) -> tuple[float, float, float]:
    """Mean sRGB colour of an image (used to tint a shared photo tile per building)."""
    try:
        import numpy as np

        w, h = img.size
        px = np.empty(w * h * 4, dtype="float32")
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)[:, :3]
        lin = px.mean(axis=0)
        # pixels are linear for sRGB images; convert the mean back to sRGB-ish for ratios.
        srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
        return float(srgb[0]), float(srgb[1]), float(srgb[2])
    except Exception:  # pragma: no cover - fall back to neutral tint
        return (0.5, 0.5, 0.5)


def textured(
    name: str,
    img,
    fallback_color,
    rough: float = 0.88,
    tint=None,
    extend: str = "REPEAT",
):
    """Principled material whose Base Color is an ImageTexture (x optional tint).

    The glTF exporter turns this into baseColorTexture (+ baseColorFactor for
    the tint), so the photo survives into the GLB.
    """
    if img is None:
        return principled(name, fallback_color, rough)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    tex.extension = extend
    bsdf.inputs["Roughness"].default_value = rough
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    if tint is not None:
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        mix.inputs[7].default_value = (float(tint[0]), float(tint[1]), float(tint[2]), 1.0)
        links.new(tex.outputs["Color"], mix.inputs[6])
        links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    else:
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


NORMAL_MAP_STRENGTH = 1.0  # glTF normalTexture.scale (1 = as baked)


def add_normal_map(mat, path: Path, strength: float = 1.0) -> bool:
    """Plug a tangent-space normal map (same UVs as Base Color) into a Principled material.

    Exports as glTF ``normalTexture``; gives the photo façades window reveals, brick
    courses and sills that catch the sun without any extra geometry.
    """
    img = load_texture(path)
    if img is None or mat is None or not mat.use_nodes:
        return False
    try:
        img.colorspace_settings.name = "Non-Color"
    except Exception:  # pragma: no cover - older Blender colour-space names
        pass
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    base_tex = next((n for n in nodes if n.type == "TEX_IMAGE"), None)
    if bsdf is None:
        return False
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    tex.extension = "EXTEND"
    nmap = nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = float(strength)
    links.new(tex.outputs["Color"], nmap.inputs["Color"])
    links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if base_tex is not None and base_tex.inputs["Vector"].is_linked:
        links.new(base_tex.inputs["Vector"].links[0].from_socket, tex.inputs["Vector"])
    return True


def add_emissive_map(mat, path: Path, strength: float = 1.0) -> bool:
    """Plug the lit-window glow atlas into a Principled material's Emission.

    Same UVs as Base Color. Exports as glTF ``emissiveTexture`` (+ ``emissiveFactor``);
    the viewer scales ``emissiveIntensity`` with the time of day, so by day it is 0 and
    the windows are just photo, at night the lit rooms glow.
    """
    img = load_texture(path)
    if img is None or mat is None or not mat.use_nodes:
        return False
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    base_tex = next((n for n in nodes if n.type == "TEX_IMAGE"), None)
    if bsdf is None or "Emission Color" not in bsdf.inputs:
        return False
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    tex.extension = "EXTEND"
    links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = float(strength)
    if base_tex is not None and base_tex.inputs["Vector"].is_linked:
        links.new(base_tex.inputs["Vector"].links[0].from_socket, tex.inputs["Vector"])
    return True


def glowing(name: str, color, rough: float, emission, strength: float = 1.0):
    """Principled material with a constant emission colour (street lamps at night)."""
    mat = principled(name, color, rough)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Emission Color"].default_value = emission
    bsdf.inputs["Emission Strength"].default_value = float(strength)
    return mat


def wall_tint(wall_rgba, avg_rgb) -> tuple[float, float, float]:
    """Darken-only tint (glTF factors are <= 1) pulling a photo tile toward the type palette."""
    out = []
    for i in range(3):
        ratio = min(1.0, float(wall_rgba[i]) / max(avg_rgb[i], 1e-3))
        out.append(max(0.55, 1.0 - 0.7 * (1.0 - ratio)))
    return tuple(out)


def apply_planar_uvs(faces, uv_layer, tile_m: float) -> None:
    """World-planar UVs (metres / tile_m): side faces use (along-wall, z), others (x, y)."""
    inv = 1.0 / max(tile_m, 0.1)
    for face in faces:
        n = face.normal
        horiz = math.hypot(n.x, n.y)
        if abs(n.z) < 0.7 and horiz > 1e-6:
            tx, ty = n.y / horiz, -n.x / horiz
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = ((co.x * tx + co.y * ty) * inv, co.z * inv)
        else:
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x * inv, co.y * inv)


def apply_roof_uvs(mesh, tile_m: float) -> None:
    """Per-face slope-aligned UVs: u runs along the eave, v up the slope (courses stay level)."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()
    uv_layer = bm.loops.layers.uv.verify()
    inv = 1.0 / max(tile_m, 0.1)
    for face in bm.faces:
        n = face.normal
        if n.z < 0.0:  # winding of from_pydata roofs is not guaranteed outward
            n = -n
        horiz = math.hypot(n.x, n.y)
        if horiz < 1e-4:  # flat cap
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x * inv, co.y * inv)
            continue
        tx, ty = n.y / horiz, -n.x / horiz
        ux, uy, uz = -n.x * n.z / horiz, -n.y * n.z / horiz, horiz
        for loop in face.loops:
            co = loop.vert.co
            loop[uv_layer].uv = ((co.x * tx + co.y * ty) * inv, (co.x * ux + co.y * uy + co.z * uz) * inv)
    bm.to_mesh(mesh)
    bm.free()


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


def ring_mesh(
    name: str,
    ring: list[list[float]],
    height: float,
    z: float = 0.0,
    uv_tile_m: float | None = None,
) -> bpy.types.Mesh | None:
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
    if uv_tile_m:
        apply_planar_uvs(bm.faces, bm.loops.layers.uv.verify(), uv_tile_m)
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


def add_ring(
    name: str,
    ring: list[list[float]],
    height: float,
    z: float,
    mat: bpy.types.Material,
    uv_tile_m: float | None = None,
) -> bpy.types.Object | None:
    mesh = ring_mesh(name, ring, height, z, uv_tile_m=uv_tile_m)
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


def add_gable_roof(
    name: str, ring: list[list[float]], z0: float, roof_h: float, mat, uv_tile_m: float | None = None
) -> None:
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
            add_mansard_roof(name, ring, z0, roof_h, mat, uv_tile_m)
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
    if uv_tile_m:
        apply_roof_uvs(mesh, uv_tile_m)
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)


def add_hip_roof(
    name: str, ring: list[list[float]], z0: float, roof_h: float, mat, uv_tile_m: float | None = None
) -> None:
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
    if uv_tile_m:
        apply_roof_uvs(mesh, uv_tile_m)
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)


def add_mansard_roof(
    name: str, ring: list[list[float]], z0: float, roof_h: float, mat, uv_tile_m: float | None = None
) -> None:
    """Two inset extruded plates — stays inside footprint for irregular rings."""
    h = max(0.35, roof_h)
    lower = inset_ring(ring, 0.55)
    add_ring(f"{name}_a", lower, h * 0.55, z0, mat, uv_tile_m=uv_tile_m)
    upper = inset_ring(ring, 1.25)
    add_ring(f"{name}_b", upper, h * 0.45, z0 + h * 0.55, mat, uv_tile_m=uv_tile_m)


def add_lod2_roof(
    name: str, ring, eaves_z: float, roof_h: float, shape: str, mat, uv_tile_m: float | None = None
) -> None:
    h = max(0.35, roof_h)
    # Irregular / L-shaped footprints: OBB gables spill past walls — use mansard.
    if shape in {"gable", "hip"} and not _prism_roof_ok(ring):
        shape = "mansard"
    if shape == "flat":
        # Slight inset so flat caps don't Z-fight or overhang sidewalks.
        add_ring(name, inset_ring(ring, 0.04), min(0.55, h), eaves_z, mat, uv_tile_m=uv_tile_m)
    elif shape == "hip":
        add_hip_roof(name, ring, eaves_z, h, mat, uv_tile_m)
    elif shape == "gable":
        add_gable_roof(name, ring, eaves_z, h, mat, uv_tile_m)
    else:  # mansard
        add_mansard_roof(name, ring, eaves_z, h, mat, uv_tile_m)


# Chimneys and roof plant are merged into one mesh per material for the whole tile
# (hundreds of tiny boxes as separate glTF nodes would bloat the GLB).
ROOFTOP_BM: dict[str, tuple] = {}


def _rooftop_box(mat, size, center, yaw: float) -> None:
    key = mat.name
    if key not in ROOFTOP_BM:
        ROOFTOP_BM[key] = (bmesh.new(), mat)
    m = (
        Matrix.Translation(Vector(center))
        @ Matrix.Rotation(yaw, 4, "Z")
        @ Matrix.Diagonal(Vector((size[0], size[1], size[2], 1.0)))
    )
    bmesh.ops.create_cube(ROOFTOP_BM[key][0], size=1.0, matrix=m)


def flush_rooftop() -> int:
    """Turn the collected chimney / roof-plant boxes into merged mesh objects."""
    made = 0
    for key, (bm, mat) in ROOFTOP_BM.items():
        if bm.verts:
            mesh = bpy.data.meshes.new(f"rooftop_{key}")
            bm.to_mesh(mesh)
            mesh.materials.append(mat)
            link(bpy.data.objects.new(f"rooftop_{key}", mesh))
            made += 1
        bm.free()
    ROOFTOP_BM.clear()
    return made


def add_chimneys(
    ring: list[list[float]], eaves_z: float, roof_h: float, shape: str, mats: dict, seed: int, pots: bool
) -> int:
    """Brick stacks on the ridge / party walls (``cityview.rooftop``): shaft, stone cap and,
    near the spawn, a corbelled course plus terracotta pots (a handful of boxes per stack)."""
    brick = mats.get("chimney") or mats["roof"]
    cap_mat = mats.get("chimney_cap") or brick
    pot_mat = mats.get("chimney_pot") or brick
    placed = 0
    for c in rooftop.plan_chimneys(ring, eaves_z, roof_h, shape, seed):
        x, y, yaw = c["x"], c["y"], c["yaw"]
        h = c["h"]
        _rooftop_box(brick, (c["w"], c["d"], h), (x, y, c["z"] + h * 0.5), yaw)
        top = c["z"] + h
        if pots:  # LOD: the corbel is a near-spawn detail; far stacks are shaft + cap only
            _rooftop_box(brick, (c["w"] + 0.1, c["d"] + 0.1, 0.1), (x, y, top - 0.22), yaw)
        _rooftop_box(cap_mat, (c["w"] + 0.2, c["d"] + 0.2, 0.1), (x, y, top + 0.05), yaw)
        if pots:
            n = int(c["pots"])
            for k in range(n):
                off = (k - (n - 1) * 0.5) * (c["w"] * 0.62 / max(1, n - 1)) if n > 1 else 0.0
                _rooftop_box(pot_mat, (0.17, 0.17, 0.36), (x + math.cos(yaw) * off, y + math.sin(yaw) * off, top + 0.28), yaw)
        placed += 1
    return placed


def add_roof_plant(ring: list[list[float]], top_z: float, mats: dict, seed: int, detail: bool) -> int:
    """Flat-roof stair head, plant units, vent stack and aerials (``cityview.rooftop``)."""
    box_mat = mats.get("roof_box") or mats["roof"]
    metal = mats.get("roof_metal") or box_mat
    placed = 0
    for it in rooftop.plan_roof_plant(ring, top_z, seed):
        kind = it["kind"]
        if kind in {"vent", "aerial"} and not detail:
            continue
        sz = it["sz"]
        _rooftop_box(box_mat if kind == "stair" else metal, (it["sx"], it["sy"], sz), (it["x"], it["y"], it["z"] + sz * 0.5), it["yaw"])
        if kind == "stair":
            _rooftop_box(metal, (it["sx"] + 0.15, it["sy"] + 0.15, 0.12), (it["x"], it["y"], it["z"] + sz + 0.04), it["yaw"])
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


def _append_photo_quad(bm, uv_layer, pts, uvs, mat_index: int) -> None:
    """One textured quad; ``pts`` are 4 (x, y, z) corners, ``uvs`` 4 matching (u, v)."""
    verts = [bm.verts.new(p) for p in pts]
    face = bm.faces.new(verts)
    face.material_index = mat_index
    for loop, uv in zip(face.loops, uvs):
        loop[uv_layer].uv = uv


def _climber_mat_base(mesh, mats: dict, climber: dict | None) -> int | None:
    """Append the climbing-plant palette to ``mesh``; return the first slot (or None)."""
    palette = mats.get("climber") or []
    if not climber or not palette:
        return None
    base = len(mesh.materials)
    for m in palette:
        mesh.materials.append(m)
    return base


def _append_climber(
    bm,
    spec: dict,
    mat_base: int,
    ox: float,
    oy: float,
    ux: float,
    uy: float,
    nx: float,
    ny: float,
    length: float,
    eaves_z: float,
    plinth_h: float,
    openings: list[tuple[float, float, float, float]],
) -> int:
    """Grow one ivy / creeper on a façade: thin stem ribbons + faceted leaf clusters.

    Everything hugs the wall (leaves 19-30 cm proud, apex a few cm more) instead of
    stacked boxes; see ``cityview.climbers`` for the growth model. Returns leaf count.
    """
    plant = climbers.generate_climber(spec, length, eaves_z, plinth_h, openings)

    def pt(a: float, z: float, d: float) -> tuple[float, float, float]:
        return (ox + ux * a + nx * d, oy + uy * a + ny * d, z)

    def face(pts, mat: int, centre=None) -> None:
        verts = [bm.verts.new(p) for p in pts]
        try:
            f = bm.faces.new(verts)
        except ValueError:
            return
        f.normal_update()
        n = f.normal
        if centre is None:
            outward_dot = n.x * nx + n.y * ny
        else:
            fc = f.calc_center_median()
            outward_dot = n.x * (fc.x - centre[0]) + n.y * (fc.y - centre[1]) + n.z * (fc.z - centre[2])
        if outward_dot < 0.0:
            f.normal_flip()
        f.material_index = mat

    for a0, z0, a1, z1, w in plant["stems"]:
        hw = w * 0.5
        face([pt(a0 - hw, z0, 0.185), pt(a0 + hw, z0, 0.185), pt(a1 + hw, z1, 0.185), pt(a1 - hw, z1, 0.185)], mat_base + climbers.STEM)

    for i, (a, z, w, h, roll, depth, mat) in enumerate(plant["leaves"]):
        # Leaf = kite folded along its midrib: tip + base ride proud, side points
        # sink toward the wall, so each leaf catches light like a real one (2 tris).
        d0 = 0.19 + (i % 8) * 0.011  # stagger layers so overlapping leaves never z-fight
        cr, sr = math.cos(roll), math.sin(roll)

        def at(u: float, v: float, d: float):
            return pt(a + u * cr - v * sr, z + u * sr + v * cr, d)

        tip, base = at(0.0, h * 0.5, d0 + depth), at(0.0, -h * 0.5, d0 + depth * 0.4)
        left, right = at(-w * 0.5, 0.0, d0), at(w * 0.5, 0.0, d0)
        face([base, right, tip], mat_base + mat)
        face([base, tip, left], mat_base + mat)
    return len(plant["leaves"])


def _append_doorstep(bm, ox, oy, ux, uy, nx, ny, a, door_w, off, variant: int) -> int:
    """Stone doorstep in front of a photo-façade door (slot DOORSTEP_MAT_SLOT = granite).

    ``a`` is the door centre along the edge (metres from the edge midpoint),
    ``off`` the distance of the photo plane from the skin centre line.
    variant 0: two treads (wide lower step + narrower upper step);
    variant 1: one deep block step with a worn threshold slab on top.
    """
    yaw = math.atan2(uy, ux)
    cx, cy = ox + ux * a, oy + uy * a
    w = max(0.8, min(2.0, door_w))
    if variant == 0:
        _append_box(bm, cx + nx * (off + 0.30), cy + ny * (off + 0.30), 0.13, w * 1.45, 0.52, 0.26, yaw, DOORSTEP_MAT_SLOT)
        _append_box(bm, cx + nx * (off + 0.15), cy + ny * (off + 0.15), 0.19, w * 1.22, 0.28, 0.38, yaw, DOORSTEP_MAT_SLOT)
    else:
        _append_box(bm, cx + nx * (off + 0.28), cy + ny * (off + 0.28), 0.15, w * 1.35, 0.5, 0.30, yaw, DOORSTEP_MAT_SLOT)
        _append_box(bm, cx + nx * (off + 0.12), cy + ny * (off + 0.12), 0.315, w * 1.1, 0.24, 0.03, yaw, DOORSTEP_MAT_SLOT)
    return 1


def _append_shop_awning(bm, ox, oy, ux, uy, nx, ny, a, w, z_top, off, variant: int) -> int:
    """Fabric awning (slot 6) over a shop window: sloped slab built from two steps + valance.

    ``z_top`` is the lintel height; the awning rail sits just above it. A trim rail
    (slot 2) carries it, so it reads as hardware, not a floating box.
    """
    yaw = math.atan2(uy, ux)
    cx, cy = ox + ux * a, oy + uy * a
    w = max(1.2, min(6.0, w * 1.08))
    z = z_top + 0.35
    proj = 0.95 if variant == 0 else 0.75
    # Wall rail + upper canopy (near the wall, higher) + lower canopy (outer, lower) + valance.
    _append_box(bm, cx + nx * (off + 0.05), cy + ny * (off + 0.05), z + 0.1, w * 1.02, 0.10, 0.12, yaw, 2)
    _append_box(bm, cx + nx * (off + proj * 0.30), cy + ny * (off + proj * 0.30), z + 0.04, w, proj * 0.62, 0.05, yaw, 6)
    _append_box(bm, cx + nx * (off + proj * 0.72), cy + ny * (off + proj * 0.72), z - 0.10, w, proj * 0.50, 0.05, yaw, 6)
    _append_box(bm, cx + nx * (off + proj), cy + ny * (off + proj), z - 0.24, w, 0.05, 0.26, yaw, 6)
    return 1


def _append_downpipe(bm, ox, oy, ux, uy, nx, ny, a, z_top, off) -> int:
    """Cast-iron rainwater pipe on a party-wall joint (frame material, slot 3).

    Shaft + wall brackets every ~1.6 m, a hopper head under the cornice and a bent
    shoe at the foot, so the façade reads as plumbed rather than a flat print.
    """
    yaw = math.atan2(uy, ux)
    cx, cy = ox + ux * a, oy + uy * a
    z_bot = 0.2
    h = z_top - z_bot
    if h < 2.0:
        return 0
    d = off + 0.05
    _append_box(bm, cx + nx * d, cy + ny * d, z_bot + h * 0.5, 0.09, 0.09, h, yaw, 3)
    z = z_bot + 0.9
    while z < z_top - 0.5:
        _append_box(bm, cx + nx * (d - 0.01), cy + ny * (d - 0.01), z, 0.14, 0.12, 0.05, yaw, 3)
        z += 1.6
    _append_box(bm, cx + nx * (d + 0.01), cy + ny * (d + 0.01), z_top - 0.1, 0.24, 0.16, 0.26, yaw, 3)  # hopper head
    _append_box(bm, cx + nx * (d + 0.08), cy + ny * (d + 0.08), z_bot + 0.05, 0.09, 0.2, 0.12, yaw, 3)  # shoe
    return 1


def _stable_variant(name: str, a: float) -> int:
    return zlib.adler32(f"{name}:{a:.2f}".encode("utf-8")) % 2


def _append_window_reveal(bm, ox, oy, ux, uy, nx, ny, a, w, z0, z1, off, variant: int) -> int:
    """Stone sill + projecting head over one detected window (3D relief on the photo).

    ``a`` is the glass centre along the edge, ``w`` its width, ``z0``/``z1`` sill and
    head heights. Everything is granite (slot DOORSTEP_MAT_SLOT): the sill has a drip lip, the head
    is a stone hood. Jamb returns are two slim trim fins so the glass
    reads as set back from the wall plane rather than printed on it.
    """
    yaw = math.atan2(uy, ux)
    cx, cy = ox + ux * a, oy + uy * a
    sw = w + 0.16
    # Sill: slab proud of the wall with a thinner drip lip underneath.
    _append_box(bm, cx + nx * (off + 0.07), cy + ny * (off + 0.07), z0 - 0.025, sw, 0.14, 0.05, yaw, DOORSTEP_MAT_SLOT)
    _append_box(bm, cx + nx * (off + 0.04), cy + ny * (off + 0.04), z0 - 0.07, sw * 0.92, 0.08, 0.04, yaw, DOORSTEP_MAT_SLOT)
    # Head: lintel hood (variant 1 adds a thin cornice course on top).
    _append_box(bm, cx + nx * (off + 0.05), cy + ny * (off + 0.05), z1 + 0.04, w + 0.12, 0.10, 0.08, yaw, DOORSTEP_MAT_SLOT)
    if variant == 1:
        _append_box(bm, cx + nx * (off + 0.07), cy + ny * (off + 0.07), z1 + 0.10, w + 0.22, 0.14, 0.04, yaw, DOORSTEP_MAT_SLOT)
    # Jamb fins: slim reveals either side of the glass.
    for sgn in (-1, 1):
        jx = cx + ux * sgn * (w * 0.5 + 0.02)
        jy = cy + uy * sgn * (w * 0.5 + 0.02)
        _append_box(bm, jx + nx * (off + 0.025), jy + ny * (off + 0.025), (z0 + z1) * 0.5, 0.045, 0.05, z1 - z0, yaw, DOORSTEP_MAT_SLOT)
    return 1


def add_photo_facade(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    eaves_z: float,
    floors: int,
    style_name: str,
    mats: dict,
    mat_key: str,
    detail: str,
    near_spawn: bool,
    climber: dict | None = None,
) -> bool:
    """Street façade skinned with generated straight elevations (atlas).

    Each house is ONE full elevation (ground to eaves), never mirrored; a long
    edge becomes a terrace of different houses. Cornice, kerb skirt and
    spawn-local ivy stay 3D so the silhouette keeps depth.
    """
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    nx, ny = outward
    yaw = math.atan2(y1 - y0, x1 - x0)
    ux, uy = math.cos(yaw), math.sin(yaw)
    mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    ox, oy = mx + nx * 0.06, my + ny * 0.06
    base_type = style_name.split("__v")[0]
    seed = zlib.adler32(name.encode("utf-8"))
    quads = facade_kit.plan_facade_quads(length * 0.98, eaves_z, floors, base_type, seed)
    tile_id = facade_kit.wall_tile_for_type(base_type, TYPES_DOC)
    tile_m = float(facade_kit.WALL_TILES[tile_id]["tile_m"])

    mesh = bpy.data.meshes.new(name)
    for key in ("wall", "plinth", "trim", "frame", "glass"):
        mesh.materials.append(mats[key].get(style_name) or mats[key][mat_key])
    ivy_mats = mats.get("ivy") or []
    shutter_mats = mats.get("shutter") or []
    accent_seed = sum(ord(c) for c in name) if name else 0
    mesh.materials.append(ivy_mats[accent_seed % len(ivy_mats)] if ivy_mats else mats["plinth"][mat_key])
    mesh.materials.append(shutter_mats[accent_seed % len(shutter_mats)] if shutter_mats else mats["frame"][mat_key])
    mesh.materials.append(FACADE_PHOTO_MAT)  # slot PHOTO_MAT_SLOT
    mesh.materials.append(DOORSTEP_MAT or mats["plinth"][mat_key])  # slot DOORSTEP_MAT_SLOT
    climber_base = _climber_mat_base(mesh, mats, climber)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.verify()
    # Backing skin (textured wall tile) + thin kerb skirt + deep cornice.
    skin_start = len(bm.faces)
    _append_box(bm, ox, oy, eaves_z * 0.5, length * 0.98, 0.1, eaves_z, yaw, 0)
    _append_box(bm, ox + nx * 0.06, oy + ny * 0.06, 0.09, length * 0.985, 0.16, 0.18, yaw, 1)
    _append_box(bm, ox + nx * 0.12, oy + ny * 0.12, eaves_z + 0.1, length * 1.02, 0.34, 0.38, yaw, 2)
    _append_box(bm, ox + nx * 0.18, oy + ny * 0.18, eaves_z + 0.28, length * 1.0, 0.2, 0.12, yaw, 2)
    bm.normal_update()
    apply_planar_uvs([f for f in bm.faces if f.material_index == 0], uv_layer, tile_m)

    # Photo quads sit 10 cm proud of the skin centre line (>= 4 cm clear of its front face).
    off = 0.16
    # Which way does increasing "a" run as seen from the street? n == u x z  -> rightwards.
    rightwards = (uy * nx - ux * ny) > 0
    half = length * 0.98 * 0.5
    for q in quads:
        a0, a1, z0, z1 = q["a0"] - half, q["a1"] - half, q["z0"], q["z1"]
        u0, v0, u1, v1 = q["uv"]
        ul, ur = u0, u1  # never mirrored: u0 < u1 for every house
        if not rightwards:
            ul, ur = ur, ul
        def corner(a, z):
            return (ox + ux * a + nx * off, oy + uy * a + ny * off, z)
        pts = [corner(a0, z0), corner(a1, z0), corner(a1, z1), corner(a0, z1)]
        uvs = [(ul, v0), (ur, v0), (ur, v1), (ul, v1)]
        if not rightwards:
            # keep outward-facing winding
            pts = [pts[1], pts[0], pts[3], pts[2]]
            uvs = [uvs[1], uvs[0], uvs[3], uvs[2]]
        _append_photo_quad(bm, uv_layer, pts, uvs, PHOTO_MAT_SLOT)
        STATS["photo_quads"] += 1

    # Doorsteps: stone treads in front of every front door in the elevations, so
    # entrances stand proud of the pavement (pavement top is Z_SIDEWALK ~ 12 cm).
    first_step_face = len(bm.faces)
    # LOD: distant ("simple") edges keep only the photo + cornice; stoops are spawn-district detail.
    for door in facade_kit.door_steps(quads, rightwards=rightwards) if detail == "full" else ():
        STATS["door_steps"] += _append_doorstep(
            bm, ox, oy, ux, uy, nx, ny, door["a"] - half, door["w"], off, int(door["side"])
        )
    if len(bm.faces) > first_step_face:
        bm.normal_update()
        apply_planar_uvs(list(bm.faces)[first_step_face:], uv_layer, surface_kit.surface_tile_m("curb"))

    # Shopfront awnings (ground-floor shop windows read off the elevations): a fabric
    # canopy projecting over the pavement with a valance, on a trim bracket rail.
    if detail == "full":
        for shop in facade_kit.shop_awnings(quads, rightwards=rightwards):
            STATS["awnings"] += _append_shop_awning(
                bm, ox, oy, ux, uy, nx, ny, shop["a"] - half, shop["w"], shop["z"], off, int(shop["side"])
            )

    # Rainwater downpipes on party-wall joints, clear of doors and shop glazing.
    if detail == "full":
        clear = [(d["a"], d["w"] * 1.4) for d in facade_kit.door_steps(quads, rightwards=rightwards)]
        clear += [(sh["a"], sh["w"]) for sh in facade_kit.shop_awnings(quads, rightwards=rightwards)]
        for pipe in facade_kit.downpipes(quads, eaves_z, clear):
            STATS["downpipes"] += _append_downpipe(bm, ox, oy, ux, uy, nx, ny, pipe["a"] - half, pipe["z1"], off)

    # Window reveals: sills, heads and jamb fins on the glass found in the elevations,
    # so near-spawn windows have relief instead of being printed flat.
    if detail == "full":
        first_reveal_face = len(bm.faces)
        for win in facade_kit.window_reveals(quads, rightwards=rightwards):
            STATS["reveals"] += _append_window_reveal(
                bm, ox, oy, ux, uy, nx, ny, win["a"] - half, win["w"], win["z0"], win["z1"], off,
                _stable_variant(name, win["a"]),
            )
        if len(bm.faces) > first_reveal_face:
            bm.normal_update()
            apply_planar_uvs(
                [f for f in list(bm.faces)[first_reveal_face:] if f.material_index == DOORSTEP_MAT_SLOT],
                uv_layer,
                surface_kit.surface_tile_m("curb"),
            )

    # Rare climbing plant (planned per street in build(); most façades have none).
    if climber_base is not None and climber is not None and detail == "full":
        CLIMBER_STATS["leaves"] += _append_climber(
            bm, climber, climber_base, ox, oy, ux, uy, nx, ny, length, eaves_z, 0.9, []
        )

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))
    STATS["photo_edges"] += 1
    return True


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
    climber: dict | None = None,
    prefer_procedural: bool = False,
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
    # Churches skip the townhouse photo atlas — arched procedural elevations instead.
    if (
        FACADE_PHOTO_MAT is not None
        and not prefer_procedural
        and add_photo_facade(
            name, p0, p1, outward, eaves_z, floors, style_name, mats, mat_key, detail, near_spawn, climber
        )
    ):
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
    # Climbing-plant palette goes after every fixed slot (only on façades that have one).
    climber_base = _climber_mat_base(mesh, mats, climber)
    # Window / door rectangles (along, half_w, z0, z1) so climbing plants skirt openings.
    openings: list[tuple[float, float, float, float]] = []

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
    floors = max(1, min(20, int(floors)))  # 20 = hard level cap (cityview.building_heights)
    if detail == "simple":
        floors = min(floors, 6)
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

    for fi in range(floors):
        z_base = fi * floor_h
        for bi in range(bays):
            along = -length * 0.5 + (bi + 0.5) * bay_w
            px = ox + math.cos(yaw) * along + nx * 0.14
            py = oy + math.sin(yaw) * along + ny * 0.14
            if fi == 0 and bi == door_bay:
                dh = min(2.35, floor_h * 0.75)
                door_w = min(1.15, win_w * 0.9)
                openings.append((along, door_w * 0.5 + 0.1, plinth_h, plinth_h + dh))
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
            openings.append((along, ww * 0.5 + 0.1, sill - 0.05, sill + wh + 0.15))
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

    # Rare climbing plant (planned per street in build(); most façades have none).
    if climber_base is not None and climber is not None and detail == "full":
        CLIMBER_STATS["leaves"] += _append_climber(
            bm,
            climber,
            climber_base,
            ox,
            oy,
            math.cos(yaw),
            math.sin(yaw),
            nx,
            ny,
            length,
            eaves_z,
            plinth_h,
            openings,
        )

    # Tile brick/stone/plaster — without UVs textured walls read as flat muddy colour.
    bm.normal_update()
    uv_layer = bm.loops.layers.uv.verify()
    _base = style_name.split("__v")[0]
    tile_m = float(facade_kit.WALL_TILES[facade_kit.wall_tile_for_type(_base, TYPES_DOC)]["tile_m"])
    apply_planar_uvs(list(bm.faces), uv_layer, tile_m)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))


DORMER_STATS = {"dormers": 0}
ROOF_STATS: dict[str, int] = {"measured": 0, "fallback": 0}


def add_dormers(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    eaves_z: float,
    roof_h: float,
    roof_mat,
    frame_mat,
    glass_mat,
    trim_mat,
    seed: int,
) -> int:
    """Pitched-roof dormer windows on a mansard's street slope (one batched mesh per edge).

    Sits on the lower mansard plate (inset 0.55 m): masonry cheeks, a glazed front with
    frame, and a small capped roof — the classic Antwerp attic-storey silhouette.
    """
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 5.0:
        return 0
    nx, ny = outward
    nl = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nl, ny / nl
    yaw = math.atan2(y1 - y0, x1 - x0)
    ux, uy = math.cos(yaw), math.sin(yaw)
    bays = max(1, int(length / 2.35))
    bay_w = length / bays
    # Real dormers stand proud of the lower slope and poke through the upper one.
    body_h = min(1.5, max(0.35, roof_h) * 0.78)
    if body_h < 0.9:
        return 0
    inset = 0.55
    depth = 0.8
    mid_x, mid_y = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    mesh = bpy.data.meshes.new(name)
    for m in (roof_mat, trim_mat, frame_mat, glass_mat):
        mesh.materials.append(m)
    bm = bmesh.new()
    placed = 0
    for bi in range(bays):
        # Every other bay, phase set per building so adjacent houses do not mirror each other.
        if (bi + seed) % 2:
            continue
        if bi == 0 or bi == bays - 1:
            continue
        along = (bi + 0.5) * bay_w - length * 0.5
        w = min(1.35, bay_w * 0.58)
        # Front sits 6 cm proud of the lower slope wall; body runs back into the upper plate.
        fd = inset - 0.06
        cxm = mid_x + ux * along - nx * (fd + depth * 0.5)
        cym = mid_y + uy * along - ny * (fd + depth * 0.5)
        z0 = eaves_z + 0.05
        _append_box(bm, cxm, cym, z0 + body_h * 0.5, w, depth, body_h, yaw, 0)
        # Trim surround + glass + frame on the front face.
        fx = mid_x + ux * along - nx * (fd - 0.015)
        fy = mid_y + uy * along - ny * (fd - 0.015)
        _append_box(bm, fx, fy, z0 + body_h * 0.5, w * 0.82, 0.05, body_h * 0.78, yaw, 1)
        _append_box(bm, fx + nx * 0.03, fy + ny * 0.03, z0 + body_h * 0.5, w * 0.62, 0.05, body_h * 0.62, yaw, 3)
        _append_box(bm, fx + nx * 0.06, fy + ny * 0.06, z0 + body_h * 0.5, w * 0.06, 0.04, body_h * 0.62, yaw, 2)
        _append_box(bm, fx + nx * 0.06, fy + ny * 0.06, z0 + body_h * 0.62, w * 0.62, 0.04, 0.05, yaw, 2)
        # Cap: wide slab (zinc/slate cornice) + narrower ridge slab reads as a little pitched roof.
        cap_x, cap_y = cxm - nx * 0.02, cym - ny * 0.02
        _append_box(bm, cap_x, cap_y, z0 + body_h + 0.07, w + 0.30, depth + 0.30, 0.14, yaw, 0)
        _append_box(bm, cap_x, cap_y, z0 + body_h + 0.22, w * 0.55, depth + 0.1, 0.18, yaw, 0)
        placed += 1
    if not placed:
        bm.free()
        bpy.data.meshes.remove(mesh)
        return 0
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))
    return placed


def photo_material_cropped(name: str, image_path: Path, crop: list[float], rough: float = 0.86):
    """Image material with UV crop (same idea as street-mode photo heroes)."""
    img = load_texture(image_path)
    if img is None:
        return principled(name, (0.45, 0.42, 0.38, 1.0), rough)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    mapping = nodes.new("ShaderNodeMapping")
    uv = nodes.new("ShaderNodeTexCoord")
    tex.image = img
    tex.extension = "CLIP"
    u0, v0, u1, v1 = [float(c) for c in (crop or [0.0, 0.0, 1.0, 1.0])]
    mapping.inputs["Location"].default_value = (u0, v0, 0.0)
    mapping.inputs["Scale"].default_value = (max(u1 - u0, 0.001), max(v1 - v0, 0.001), 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    links.new(uv.outputs["UV"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _landmark_crop_aspect(crop: list[float] | None) -> float:
    """Crop width/height in UV space (used to size photo quads to the real elevation)."""
    u0, v0, u1, v1 = [float(c) for c in (crop or [0.0, 0.0, 1.0, 1.0])]
    return max(0.18, (u1 - u0) / max(1e-6, v1 - v0))


def add_landmark_photo_quad(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    eaves_z: float,
    photo_path: Path,
    crop: list[float],
    proud: float = 0.35,
) -> None:
    """Thin photo plane on one street wall (hospitals only — churches never use photos)."""
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 2.0 or eaves_z < 4.0:
        return
    nx, ny = outward
    nl = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nl, ny / nl
    yaw = math.atan2(y1 - y0, x1 - x0)
    ux, uy = math.cos(yaw), math.sin(yaw)
    mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    ox, oy = mx + nx * proud, my + ny * proud
    mat = photo_material_cropped(f"{name}_photo", photo_path, crop)
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(mat)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.verify()
    half = length * 0.99 * 0.5
    rightwards = (uy * nx - ux * ny) > 0

    def corner(a, z):
        return (ox + ux * a, oy + uy * a, z)

    pts = [corner(-half, 0.05), corner(half, 0.05), corner(half, eaves_z), corner(-half, eaves_z)]
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if not rightwards:
        pts = [pts[1], pts[0], pts[3], pts[2]]
        uvs = [(1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    _append_photo_quad(bm, uv_layer, pts, uvs, 0)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))


def add_church_west_front(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    facade_h: float,
    church_mats: dict,
    thickness: float = 1.15,
) -> None:
    """Mesh-only street elevation (Heilige Geest west front) — brick/stone/glass, no photo."""
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 2.0 or facade_h < 4.0:
        return
    nx, ny = outward
    nl = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nl, ny / nl
    yaw = math.atan2(y1 - y0, x1 - x0)
    ux, uy = math.cos(yaw), math.sin(yaw)
    mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    cx = mx + nx * (thickness * 0.5 + 0.06)
    cy = my + ny * (thickness * 0.5 + 0.06)
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(church_mats["brick"])   # 0
    mesh.materials.append(church_mats["stone"])   # 1
    mesh.materials.append(church_mats["glass"])   # 2
    mesh.materials.append(church_mats["portal"])  # 3
    bm = bmesh.new()
    # Main brick wall mass (proud of the extruded ring).
    _append_box(bm, cx, cy, facade_h * 0.5, length * 0.985, thickness, facade_h, yaw, 0)
    # Stone plinth
    _append_box(
        bm,
        mx + nx * (thickness * 0.55 + 0.06),
        my + ny * (thickness * 0.55 + 0.06),
        0.7,
        length * 0.99,
        thickness * 0.75,
        1.4,
        yaw,
        1,
    )
    # Horizontal stone string courses
    for zf in (0.32, 0.58, 0.82):
        _append_box(
            bm,
            mx + nx * (thickness * 0.55 + 0.08),
            my + ny * (thickness * 0.55 + 0.08),
            facade_h * zf,
            length * 0.98,
            0.22,
            0.2,
            yaw,
            1,
        )
    # Shoulder gable over the central bay
    gable_w = min(length * 0.52, max(5.5, length * 0.4))
    gable_h = min(5.8, max(3.4, facade_h * 0.26))
    gx = mx + nx * (thickness * 0.48 + 0.05)
    gy = my + ny * (thickness * 0.48 + 0.05)
    _append_box(bm, gx, gy, facade_h + gable_h * 0.42, gable_w, thickness * 0.9, gable_h, yaw, 0)
    # Stone coping + peak cross stub
    _append_box(
        bm,
        mx + nx * (thickness * 0.55 + 0.08),
        my + ny * (thickness * 0.55 + 0.08),
        facade_h + gable_h + 0.12,
        gable_w * 1.06,
        0.32,
        0.26,
        yaw,
        1,
    )
    _append_box(
        bm,
        mx + nx * (thickness * 0.5),
        my + ny * (thickness * 0.5),
        facade_h + gable_h + 0.85,
        0.22,
        0.22,
        1.1,
        yaw,
        1,
    )
    # Corbel-table frieze under the gable (row of small stone arches)
    fringe_z = facade_h - 0.35
    n_corbels = max(5, int(gable_w / 0.85))
    for i in range(n_corbels):
        t = (i + 0.5) / n_corbels - 0.5
        _append_box(
            bm,
            mx + ux * t * gable_w + nx * (thickness * 0.62),
            my + uy * t * gable_w + ny * (thickness * 0.62),
            fringe_z,
            0.55,
            0.28,
            0.45,
            yaw,
            1,
        )
    # Triple arched window bank (central taller) — neo-Romanesque west front
    win_z = facade_h * 0.55
    for side, scale in ((-1.0, 0.85), (0.0, 1.0), (1.0, 0.85)):
        ww = length * 0.09 * scale
        wh = facade_h * 0.28 * scale
        wx = mx + ux * side * length * 0.14 + nx * (thickness * 0.55 + 0.12)
        wy = my + uy * side * length * 0.14 + ny * (thickness * 0.55 + 0.12)
        # Stone surround
        _append_box(bm, wx - nx * 0.08, wy - ny * 0.08, win_z, ww * 1.35, 0.35, wh * 1.2, yaw, 1)
        # Glass recess
        _append_box(bm, wx + nx * 0.05, wy + ny * 0.05, win_z, ww, 0.22, wh, yaw, 2)
        # Mullion
        _append_box(bm, wx + nx * 0.08, wy + ny * 0.08, win_z, 0.1, 0.12, wh * 0.92, yaw, 3)
    # Small oculi in the gable
    for side in (-1.0, 1.0):
        ox = mx + ux * side * gable_w * 0.22 + nx * (thickness * 0.55)
        oy = my + uy * side * gable_w * 0.22 + ny * (thickness * 0.55)
        _append_box(bm, ox, oy, facade_h + gable_h * 0.45, 0.7, 0.25, 0.7, yaw, 2)
    bm.to_mesh(mesh)
    bm.free()
    _uv_mesh_faces(mesh, float(church_mats["brick_tile_m"]))
    link(bpy.data.objects.new(name, mesh))


def _primary_street_edge(
    bldg: dict,
    ring: list[list[float]],
    spawn_xy: tuple[float, float] | None = None,
) -> dict | None:
    """Longest street edge; prefer the one facing the spawn when available."""
    edges = bldg.get("street_edges") or []
    if not edges:
        return None
    best = None
    best_score = -1e18
    for edge in edges:
        i0, i1 = int(edge["i0"]), int(edge["i1"])
        if i0 >= len(ring) or i1 >= len(ring):
            continue
        p0, p1 = ring[i0], ring[i1]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        score = length
        if spawn_xy is not None:
            mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
            nx, ny = edge.get("outward") or [0.0, 1.0]
            dx, dy = spawn_xy[0] - mx, spawn_xy[1] - my
            dist = math.hypot(dx, dy) or 1.0
            facing = (nx * dx + ny * dy) / dist
            score = length * (1.0 + max(0.0, facing) * 2.5)
        if score > best_score:
            best_score = score
            best = edge
    return best


def _uv_mesh_faces(mesh, tile_m: float = 1.6) -> None:
    """Planar UVs so brick/stone/slate tiles read on extruded church volumes."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.normal_update()
    uv_layer = bm.loops.layers.uv.verify()
    apply_planar_uvs(list(bm.faces), uv_layer, tile_m)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def make_church_materials(surface_mat_fn) -> dict:
    """Dedicated textured mats for nave / tower / spire / portal (not one muddy colour)."""
    brick_img = load_texture(TEXTURES_DIR / facade_kit.wall_tile_file("brick_red"))
    stone_img = load_texture(TEXTURES_DIR / facade_kit.wall_tile_file("stone_buff"))
    return {
        "brick": textured(
            "church_brick_red",
            brick_img,
            (0.52, 0.28, 0.22, 1.0),
            rough=0.88,
        ),
        "stone": textured(
            "church_stone_buff",
            stone_img,
            (0.62, 0.58, 0.52, 1.0),
            rough=0.78,
        ),
        "slate": surface_mat_fn(
            "roof_slate",
            "church_slate",
            (0.16, 0.16, 0.17, 1.0),
            0.72,
            tint=(0.55, 0.55, 0.56),
        ),
        "portal": surface_mat_fn(
            "curb",
            "church_portal_stone",
            (0.42, 0.40, 0.36, 1.0),
            0.82,
            tint=(0.92, 0.88, 0.78),
        ),
        "plinth": surface_mat_fn(
            "curb",
            "church_plinth",
            (0.36, 0.34, 0.32, 1.0),
            0.9,
            tint=(0.75, 0.74, 0.70),
        ),
        "glass": principled("church_glass", (0.10, 0.16, 0.20, 1.0), 0.16, metallic=0.35),
        "door": principled("church_door", (0.20, 0.11, 0.07, 1.0), 0.78),
        "brick_tile_m": float(facade_kit.WALL_TILES["brick_red"]["tile_m"]),
        "stone_tile_m": float(facade_kit.WALL_TILES["stone_buff"]["tile_m"]),
        "slate_tile_m": float(surface_kit.surface_tile_m("roof_slate")),
    }


def _append_pyramid(
    bm,
    cx: float,
    cy: float,
    z0: float,
    base: float,
    height: float,
    yaw: float,
    mat_i: int,
) -> None:
    """True four-sided pyramid (smooth silhouette, not Minecraft stair-steps)."""
    c, s = math.cos(yaw), math.sin(yaw)
    hx = base * 0.5

    def rot(x: float, y: float) -> tuple[float, float]:
        return cx + x * c - y * s, cy + x * s + y * c

    corners = [(-hx, -hx), (hx, -hx), (hx, hx), (-hx, hx)]
    base_vs = [bm.verts.new((*rot(x, y), z0)) for x, y in corners]
    apex = bm.verts.new((cx, cy, z0 + height))
    bm.verts.ensure_lookup_table()
    for i in range(4):
        face = bm.faces.new([base_vs[i], base_vs[(i + 1) % 4], apex])
        face.material_index = mat_i


def _append_prism_n(
    bm,
    cx: float,
    cy: float,
    z0: float,
    height: float,
    radius: float,
    yaw: float,
    mat_i: int,
    sides: int = 8,
) -> None:
    """Regular n-gon prism (round stair turret approximation)."""
    c, s = math.cos(yaw), math.sin(yaw)
    bot, top = [], []
    for i in range(sides):
        ang = (i / sides) * math.tau
        lx, ly = math.cos(ang) * radius, math.sin(ang) * radius
        wx, wy = cx + lx * c - ly * s, cy + lx * s + ly * c
        bot.append(bm.verts.new((wx, wy, z0)))
        top.append(bm.verts.new((wx, wy, z0 + height)))
    bm.verts.ensure_lookup_table()
    for i in range(sides):
        j = (i + 1) % sides
        face = bm.faces.new([bot[i], bot[j], top[j], top[i]])
        face.material_index = mat_i
    try:
        bm.faces.new(bot[::-1]).material_index = mat_i
        bm.faces.new(top).material_index = mat_i
    except ValueError:
        pass


def _append_cone(
    bm,
    cx: float,
    cy: float,
    z0: float,
    radius: float,
    height: float,
    yaw: float,
    mat_i: int,
    sides: int = 8,
) -> None:
    """Conical roof for a round turret."""
    c, s = math.cos(yaw), math.sin(yaw)
    ring = []
    for i in range(sides):
        ang = (i / sides) * math.tau
        lx, ly = math.cos(ang) * radius, math.sin(ang) * radius
        wx, wy = cx + lx * c - ly * s, cy + lx * s + ly * c
        ring.append(bm.verts.new((wx, wy, z0)))
    apex = bm.verts.new((cx, cy, z0 + height))
    bm.verts.ensure_lookup_table()
    for i in range(sides):
        face = bm.faces.new([ring[i], ring[(i + 1) % sides], apex])
        face.material_index = mat_i


def _place_church_tower_volume(
    name: str,
    tx: float,
    ty: float,
    tower_h: float,
    tw: float,
    spire_h: float,
    yaw: float,
    church_mats: dict,
    gothic: bool = False,
) -> None:
    """Square shaft + cornice + belfry arches + smooth pyramidal slate spire + finial."""
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(church_mats["brick"])   # 0
    mesh.materials.append(church_mats["slate"])   # 1
    mesh.materials.append(church_mats["stone"])   # 2
    mesh.materials.append(church_mats["glass"])   # 3
    bm = bmesh.new()
    # Main shaft
    _append_box(bm, tx, ty, tower_h * 0.5, tw, tw, tower_h, yaw, 0)
    # Stone plinth
    _append_box(bm, tx, ty, 0.7, tw * 1.08, tw * 1.08, 1.4, yaw, 2)
    # String-course bands (speklagen)
    for zf in (0.28, 0.52, 0.78):
        _append_box(bm, tx, ty, tower_h * zf, tw * 1.06, tw * 1.06, 0.22, yaw, 2)
    # Cornice under the belfry
    _append_box(bm, tx, ty, tower_h + 0.15, tw * 1.12, tw * 1.12, 0.45, yaw, 2)
    # Belfry stage
    bh = 2.4 if gothic else 2.0
    _append_box(bm, tx, ty, tower_h + 0.35 + bh * 0.5, tw * 0.9, tw * 0.9, bh, yaw, 0)
    # Recessed belfry openings on four faces (dark glass).
    for ang in (0.0, math.pi * 0.5, math.pi, math.pi * 1.5):
        ox = math.cos(yaw + ang) * (tw * 0.42)
        oy = math.sin(yaw + ang) * (tw * 0.42)
        _append_box(
            bm,
            tx + ox,
            ty + oy,
            tower_h + 0.35 + bh * 0.55,
            tw * 0.28,
            0.35,
            bh * 0.7,
            yaw + ang,
            3,
        )
    # Smooth pyramidal spire (Heilige Geest: steep four-sided slate needle)
    _append_pyramid(bm, tx, ty, tower_h + 0.35 + bh + 0.1, tw * 1.02, spire_h, yaw, 1)
    # Finial / cross stub
    _append_box(
        bm,
        tx,
        ty,
        tower_h + 0.35 + bh + spire_h + 0.55,
        0.18,
        0.18,
        1.1,
        yaw,
        2,
    )
    if gothic:
        # Corner pinnacles (Boniface-style)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            c, s = math.cos(yaw), math.sin(yaw)
            lx, ly = sx * tw * 0.42, sy * tw * 0.42
            px, py = tx + lx * c - ly * s, ty + lx * s + ly * c
            _append_box(bm, px, py, tower_h + bh + 1.2, 0.55, 0.55, 2.2, yaw, 2)
            _append_pyramid(bm, px, py, tower_h + bh + 2.3, 0.65, 1.4, yaw, 1)
    bm.to_mesh(mesh)
    bm.free()
    _uv_mesh_faces(mesh, float(church_mats["brick_tile_m"]))
    link(bpy.data.objects.new(name, mesh))


def _place_round_turret(
    name: str,
    tx: float,
    ty: float,
    height: float,
    radius: float,
    yaw: float,
    church_mats: dict,
) -> None:
    """Heilige Geest south-corner round stair turret + conical slate roof."""
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(church_mats["brick"])
    mesh.materials.append(church_mats["slate"])
    mesh.materials.append(church_mats["stone"])
    bm = bmesh.new()
    _append_prism_n(bm, tx, ty, 0.0, height, radius, yaw, 0, sides=10)
    _append_box(bm, tx, ty, 0.55, radius * 2.15, radius * 2.15, 1.1, yaw, 2)
    _append_cone(bm, tx, ty, height, radius * 1.08, radius * 1.85, yaw, 1, sides=10)
    bm.to_mesh(mesh)
    bm.free()
    _uv_mesh_faces(mesh, float(church_mats["brick_tile_m"]))
    link(bpy.data.objects.new(name, mesh))


def add_church_tower(
    name: str,
    ring: list[list[float]],
    nave_h: float,
    massing: str,
    church_mats: dict,
    street_edge: dict | None,
) -> None:
    """Parametric tower + spire matched to landmark massing (Heilige Geest / Boniface)."""
    tw = 5.4
    elen = 12.0
    yaw = 0.0
    nx, ny = 0.0, 1.0
    ux, uy = 1.0, 0.0
    p0 = p1 = None
    if street_edge is not None:
        i0, i1 = int(street_edge["i0"]), int(street_edge["i1"])
        p0, p1 = ring[i0], ring[i1]
        ux, uy = p1[0] - p0[0], p1[1] - p0[1]
        elen = math.hypot(ux, uy) or 1.0
        ux, uy = ux / elen, uy / elen
        nx, ny = street_edge.get("outward") or [0.0, 1.0]
        nl = math.hypot(nx, ny) or 1.0
        nx, ny = nx / nl, ny / nl
        yaw = math.atan2(uy, ux)
        tw = min(6.4, max(4.8, elen * 0.30))

    gothic = "gothic" in massing
    romanesque = "romanesque" in massing
    tower_left = "tower_left" in massing or romanesque or gothic
    if romanesque:
        tower_h = max(28.0, nave_h * 1.75)
        spire_h = 13.5
        tw = min(6.0, max(4.8, elen * 0.26))
    elif gothic:
        tower_h = max(32.0, nave_h * 1.9)
        spire_h = tower_h * 0.22
    else:
        tower_h = max(26.0, nave_h * 1.6)
        spire_h = tower_h * 0.38

    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    along = 0.14 if tower_left else 0.5
    if p0 is not None:
        # Sit the shaft just inside the extruded footprint / west-front mass.
        tx = p0[0] + ux * (elen * along) - nx * (tw * 0.42)
        ty = p0[1] + uy * (elen * along) - ny * (tw * 0.42)
    else:
        tx, ty = cx, cy

    _place_church_tower_volume(
        f"{name}_tower",
        tx,
        ty,
        tower_h,
        tw,
        spire_h,
        yaw,
        church_mats,
        gothic=gothic,
    )

    # Heilige Geest: round stair turret on street-right (not a second twin spire).
    if romanesque and p0 is not None:
        rw = tw * 0.34
        rtx = p0[0] + ux * (elen * 0.88) - nx * (rw * 0.9)
        rty = p0[1] + uy * (elen * 0.88) - ny * (rw * 0.9)
        _place_round_turret(
            f"{name}_turret",
            rtx,
            rty,
            nave_h * 1.08,
            rw,
            yaw,
            church_mats,
        )


def add_church_entrance(
    name: str,
    ring: list[list[float]],
    nave_h: float,
    church_mats: dict,
    street_edge: dict | None,
) -> None:
    """Deep arched portal, rose recess, buttress piers — textured stone/brick/glass."""
    if street_edge is None:
        return
    i0, i1 = int(street_edge["i0"]), int(street_edge["i1"])
    if i0 >= len(ring) or i1 >= len(ring):
        return
    p0, p1 = ring[i0], ring[i1]
    elen = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) or 1.0
    if elen < 4.0:
        return
    ux, uy = (p1[0] - p0[0]) / elen, (p1[1] - p0[1]) / elen
    nx, ny = street_edge.get("outward") or [0.0, 1.0]
    nl = math.hypot(nx, ny) or 1.0
    nx, ny = nx / nl, ny / nl
    yaw = math.atan2(uy, ux)
    mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
    portal_w = min(6.2, max(3.6, elen * 0.26))
    portal_h = min(9.0, max(5.6, nave_h * 0.52))
    mesh = bpy.data.meshes.new(f"{name}_portal")
    mesh.materials.append(church_mats["brick"])    # 0
    mesh.materials.append(church_mats["portal"])   # 1 stone portal
    mesh.materials.append(church_mats["glass"])    # 2
    mesh.materials.append(church_mats["door"])     # 3
    mesh.materials.append(church_mats["stone"])    # 4
    bm = bmesh.new()
    # Stepped arch recess (outer brick → stone → glass) so the portal has real depth.
    for dw, dh, depth, mat_i in (
        (1.0, 1.0, 0.55, 0),
        (0.78, 0.88, 0.95, 1),
        (0.52, 0.72, 1.35, 2),
    ):
        _append_box(
            bm,
            mx + nx * (0.55 + depth),
            my + ny * (0.55 + depth),
            portal_h * 0.48 * dh,
            portal_w * dw,
            0.55,
            portal_h * dh,
            yaw,
            mat_i,
        )
    # Door leaf plane
    _append_box(
        bm,
        mx + nx * 2.05,
        my + ny * 2.05,
        portal_h * 0.32,
        portal_w * 0.42,
        0.18,
        portal_h * 0.58,
        yaw,
        3,
    )
    # Triple lancet / round-arch window bank above the portal
    rose_z = min(nave_h * 0.68, portal_h + 2.8)
    for side in (-1.0, 0.0, 1.0):
        ww = portal_w * (0.22 if side == 0.0 else 0.16)
        wh = portal_w * (0.55 if side == 0.0 else 0.42)
        _append_box(
            bm,
            mx + ux * side * portal_w * 0.28 + nx * 0.55,
            my + uy * side * portal_w * 0.28 + ny * 0.55,
            rose_z,
            ww,
            0.45,
            wh,
            yaw,
            2,
        )
        # Stone surround
        _append_box(
            bm,
            mx + ux * side * portal_w * 0.28 + nx * 0.4,
            my + uy * side * portal_w * 0.28 + ny * 0.4,
            rose_z,
            ww * 1.25,
            0.28,
            wh * 1.15,
            yaw,
            4,
        )
    # Flanking buttress piers with stone setbacks
    for side in (-1.0, 1.0):
        bx = mx + ux * side * (portal_w * 0.68) + nx * 0.55
        by = my + uy * side * (portal_w * 0.68) + ny * 0.55
        _append_box(bm, bx, by, nave_h * 0.45, 1.05, 1.45, nave_h * 0.9, yaw, 0)
        _append_box(
            bm,
            bx + nx * 0.2,
            by + ny * 0.2,
            nave_h * 0.72,
            0.85,
            1.1,
            nave_h * 0.35,
            yaw,
            4,
        )
    bm.to_mesh(mesh)
    bm.free()
    _uv_mesh_faces(mesh, float(church_mats["brick_tile_m"]))
    link(bpy.data.objects.new(f"{name}_portal", mesh))


def add_hospital_extras(
    name: str,
    ring: list[list[float]],
    eaves: float,
    wall,
    trim,
    street_edge: dict | None,
) -> None:
    """Rooftop plant + street-edge entrance canopy for hospitals."""
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    mesh = bpy.data.meshes.new(f"{name}_hospital")
    mesh.materials.append(wall)
    mesh.materials.append(trim)
    bm = bmesh.new()
    _append_box(bm, cx, cy, eaves + 1.1, 6.5, 4.2, 2.2, 0.0, 0)
    if street_edge is not None:
        i0, i1 = int(street_edge["i0"]), int(street_edge["i1"])
        p0, p1 = ring[i0], ring[i1]
        mx, my = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5
        nx, ny = street_edge.get("outward") or [0.0, 1.0]
        yaw = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        canopy_w = min(12.0, max(4.0, length * 0.35))
        _append_box(
            bm,
            mx + nx * 1.4,
            my + ny * 1.4,
            3.2,
            canopy_w,
            2.4,
            0.28,
            yaw,
            1,
        )
        # Canopy posts
        for side in (-0.35, 0.35):
            ux, uy = math.cos(yaw), math.sin(yaw)
            _append_box(
                bm,
                mx + ux * canopy_w * side + nx * 2.2,
                my + uy * canopy_w * side + ny * 2.2,
                1.55,
                0.22,
                0.22,
                3.1,
                yaw,
                1,
            )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(f"{name}_hospital", mesh))


def add_supermarket_fascia(
    name: str,
    p0: list[float],
    p1: list[float],
    outward: list[float],
    brand_key: str | None,
) -> None:
    """Ground-floor brand fascia strip + accent (no trademark logos)."""
    spec = fascia_for_brand(brand_key)
    x0, y0 = p0
    x1, y1 = p1
    length = math.hypot(x1 - x0, y1 - y0)
    if length < 3.0:
        return
    nx, ny = outward
    yaw = math.atan2(y1 - y0, x1 - x0)
    mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
    fascia_mat = principled(f"{name}_fascia", tuple(spec["fascia"]), 0.55)
    accent_mat = principled(f"{name}_accent", tuple(spec["accent"]), 0.45)
    mesh = bpy.data.meshes.new(name)
    mesh.materials.append(fascia_mat)
    mesh.materials.append(accent_mat)
    bm = bmesh.new()
    ox, oy = mx + nx * 0.22, my + ny * 0.22
    _append_box(bm, ox, oy, 3.15, length * 0.92, 0.28, 1.15, yaw, 0)
    _append_box(bm, ox + nx * 0.04, oy + ny * 0.04, 2.45, length * 0.92, 0.16, 0.18, yaw, 1)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    link(bpy.data.objects.new(name, mesh))
    label = str(spec.get("label") or "")
    if label:
        curve = bpy.data.curves.new(name=f"{name}_txt", type="FONT")
        curve.body = label
        curve.size = min(1.05, max(0.55, length * 0.08))
        curve.align_x = "CENTER"
        curve.align_y = "CENTER"
        obj = bpy.data.objects.new(f"{name}_label", curve)
        obj.location = (ox + nx * 0.2, oy + ny * 0.2, 3.15)
        obj.rotation_euler = (math.pi / 2.0, 0.0, yaw)
        obj.data.materials.append(accent_mat)
        link(obj)


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
    landmark = bldg.get("landmark") or {}
    massing = str(landmark.get("massing") or f"{type_id}_default")
    photo_path = resolve_landmark_photo(landmark, LANDMARKS_DIR) if landmark.get("photo") else None
    # Churches: extruded OSM mass + pitched roof + tower/turret + mesh west front.
    # No facade photographs — recognition comes from geometry + tiling brick/stone/slate.
    body_h = max(2.5, eaves)
    church_mats = mats.get("church") or {}
    if type_id == "church":
        body_h = min(18.0, max(13.0, eaves * 0.65))
        shape = "hip"
        roof_h = max(3.2, roof_h if roof_h > 0.5 else 4.0)
        if church_mats.get("brick") is not None:
            wall = church_mats["brick"]
        if church_mats.get("slate") is not None:
            roof = church_mats["slate"]
        style_name = "church" if "church" in mats["wall"] else style_name

    base_type = "church" if type_id == "church" else style_name.split("__v")[0]
    wall_tile_m = float(facade_kit.WALL_TILES[facade_kit.wall_tile_for_type(base_type, TYPES_DOC)]["tile_m"])
    if type_id == "church" and church_mats.get("brick_tile_m"):
        wall_tile_m = float(church_mats["brick_tile_m"])
    add_ring(name, ring, body_h, 0.0, wall, uv_tile_m=wall_tile_m)
    roof_uv_tile = None
    roof_pool = mats.get("roof_tex") or {}
    # Irregular footprints fall back to a mansard stack inside add_lod2_roof.
    eff_shape = "mansard" if shape in {"gable", "hip"} and not _prism_roof_ok(ring) else shape
    if type_id == "church" and church_mats.get("slate") is not None:
        # Churches always wear slate — matches spire/turret and the real Harmonie roofs.
        roof = church_mats["slate"]
        roof_uv_tile = float(church_mats.get("slate_tile_m") or surface_kit.surface_tile_m("roof_slate"))
        ROOF_STATS["roof_slate"] = ROOF_STATS.get("roof_slate", 0) + 1
    elif roof_pool:
        bseed = int(bid) if str(bid).lstrip("-").isdigit() else 1
        measured = surface_kit.roof_choice(ROOF_AERIAL, bid, eff_shape)
        if measured and measured[0] in roof_pool:
            surf, cluster = measured  # the roof colour seen from above in the orthophoto
        else:
            surf = surface_kit.pick_roof_surface(eff_shape, bseed)
            cluster = surface_kit.pick_roof_cluster(ROOF_AERIAL, surf, bseed)
        variants = roof_pool.get(surf)
        if variants:
            roof = variants[cluster % len(variants)]
            roof_uv_tile = surface_kit.surface_tile_m(surf)
            ROOF_STATS[surf] = ROOF_STATS.get(surf, 0) + 1
            ROOF_STATS["measured" if measured else "fallback"] += 1
    add_lod2_roof(f"{name}_roof", ring, body_h, roof_h, shape, roof, uv_tile_m=roof_uv_tile)

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
    primary = _primary_street_edge(bldg, ring, spawn_xy)

    # Landmark churches/hospitals keep tower + street detail even when far — skyline
    # recognition matters more than LOD savings on a handful of sites.
    if type_id in {"church", "hospital"}:
        if detail not in {"full", "simple"}:
            detail = "simple"

    if spawn_xy is not None and dist > 360.0 and type_id not in {"church", "hospital"}:
        # Far LOD1 colour blocks only — still keep roofs.
        return

    if type_id in {"church", "hospital"} and detail in {"full", "simple"}:
        trim = mats["trim"].get(style_name) or mats["trim"].get(type_id) or mats["trim"]["eclectic"]
        skip_primary_facade = False
        if type_id == "church":
            cm = church_mats or {
                "brick": wall,
                "stone": trim,
                "slate": roof,
                "portal": trim,
                "plinth": trim,
                "glass": mats["glass"].get(style_name) or mats["glass"]["eclectic"],
                "door": trim,
                "brick_tile_m": wall_tile_m,
                "stone_tile_m": 2.4,
                "slate_tile_m": 1.8,
            }
            add_church_tower(name, ring, body_h, massing, cm, primary)
            # Portal + west front always — churches are landmarks, not LOD1 boxes.
            add_church_entrance(name, ring, body_h, cm, primary)
            # Mesh-only west front (brick / stone / glass) — NEVER a facade photograph.
            if primary is not None:
                i0, i1 = int(primary["i0"]), int(primary["i1"])
                p0, p1 = ring[i0], ring[i1]
                nx, ny = primary.get("outward") or [0.0, 1.0]
                add_church_west_front(
                    f"{name}_front",
                    p0,
                    p1,
                    [nx, ny],
                    body_h,
                    cm,
                    thickness=1.15,
                )
                skip_primary_facade = True
        else:
            add_hospital_extras(name, ring, body_h, wall, trim, primary)
            # Hospitals may still dress one street wall with a photo.
            if photo_path is not None and primary is not None and detail == "full":
                i0, i1 = int(primary["i0"]), int(primary["i1"])
                p0, p1 = ring[i0], ring[i1]
                edge_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                nx, ny = primary.get("outward") or [0.0, 1.0]
                crop = landmark.get("crop") or [0.0, 0.0, 1.0, 1.0]
                aspect = _landmark_crop_aspect(crop)
                facade_h = min(48.0, max(body_h, edge_len / max(aspect, 0.2)))
                add_landmark_photo_quad(
                    f"{name}_landmark",
                    p0,
                    p1,
                    [nx, ny],
                    facade_h,
                    photo_path,
                    crop,
                    proud=0.28,
                )
                skip_primary_facade = True
        for ei, edge in enumerate(bldg.get("street_edges") or []):
            if skip_primary_facade and edge is primary:
                continue
            i0 = int(edge["i0"])
            i1 = int(edge["i1"])
            if i0 >= len(ring) or i1 >= len(ring):
                continue
            # Churches force the textured church brick wall mat on procedural sides.
            side_style = "church" if type_id == "church" and "church" in mats["wall"] else style_name
            add_street_facade(
                f"{name}_facade{ei}",
                ring[i0],
                ring[i1],
                edge.get("outward") or [0.0, 1.0],
                body_h,
                max(3, min(5, floors)) if type_id == "church" else floors,
                side_style,
                mats,
                detail=detail,
                window_kind="arch" if type_id == "church" else window_kind,
                near_spawn=near_spawn,
                prefer_procedural=(type_id == "church"),
            )
        return
    seed_id = int(bid) if str(bid).lstrip("-").isdigit() else 1
    # LOD: chimneys and plant also crown the "simple" ring (skyline from the orbit view);
    # corbels, pots, vents and aerials are near-spawn only.
    if eff_shape != "flat" and seed_id % 2 == 0:
        ROOFTOP_STATS["chimneys"] += add_chimneys(
            ring, max(2.5, eaves), roof_h, eff_shape, {**mats, "roof": roof}, abs(seed_id) or 1, near_spawn
        )
    elif eff_shape == "flat":
        flat_top = max(2.5, eaves) + min(0.55, max(0.35, roof_h))
        ROOFTOP_STATS["plant"] += add_roof_plant(ring, flat_top, {**mats, "roof": roof}, abs(seed_id) or 1, near_spawn)

    for ei, edge in enumerate(bldg.get("street_edges") or []):
        i0 = int(edge["i0"])
        i1 = int(edge["i1"])
        if i0 >= len(ring) or i1 >= len(ring):
            continue
        if detail == "full" and eff_shape == "mansard" and roof_h >= 1.5:
            DORMER_STATS["dormers"] += add_dormers(
                f"{name}_dormers{ei}",
                ring[i0],
                ring[i1],
                edge.get("outward") or [0.0, 1.0],
                max(2.5, eaves),
                roof_h,
                roof,
                mats["frame"].get(style_name) or mats["frame"]["eclectic"],
                mats["glass"].get(style_name) or mats["glass"]["eclectic"],
                mats["trim"].get(style_name) or mats["trim"]["eclectic"],
                int(bid) if str(bid).lstrip("-").isdigit() else 1,
            )
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
            climber=CLIMBERS.get((int(bid), ei)) if detail == "full" else None,
        )
        if type_id == "supermarket" and detail == "full" and edge is primary:
            add_supermarket_fascia(
                f"{name}_fascia{ei}",
                ring[i0],
                ring[i1],
                edge.get("outward") or [0.0, 1.0],
                bldg.get("brand_key") or (bldg.get("use") or {}).get("brand_key"),
            )


# Vertical layer stack (metres). Strictly increasing, >= 2 cm between layers that
# can overlap, so no layer relies on polygonOffset alone (24-bit depth at 200 m+
# resolves ~2 cm). Rails are the highest flat layer: they can never sink under
# asphalt, sidewalks, kerbs or park/ground polygons.
Z_GROUND = -0.15
Z_WATER = -0.04
Z_PARK = 0.00
Z_ROAD = 0.04
Z_PARK_PATH = 0.05
Z_DASH = 0.07  # box centre; 2 cm thick
Z_ZEBRA = 0.07  # box centre; 2 cm thick
Z_SIDEWALK = kerbs.PAVEMENT_TOP  # raised pavement, a hair below the kerb top
Z_CURB = 0.12  # legacy flat-ribbon height (unused by the 3-D kerb)
Z_TRAM_BED = 0.14
Z_TRAM_RAIL = 0.18
Z_ZEBRA_ON_RAIL = 0.22  # zebra stripe pieces that cross a rail corridor
Z_TRAM = Z_TRAM_BED  # backwards-compatible alias


def polyline_mesh(
    name: str,
    points: list[list[float]],
    width: float,
    z: float = Z_ROAD,
    uv_tile_m: float | None = None,
) -> bpy.types.Mesh | None:
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
    if uv_tile_m:
        # u = distance along the polyline, v = across the strip (metres / tile).
        along = [0.0]
        for i in range(1, n):
            along.append(along[-1] + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
        inv = 1.0 / max(uv_tile_m, 0.1)
        uvs = [(a * inv, 0.0) for a in along] + [(a * inv, width * inv) for a in reversed(along)]
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for li, vi in zip(poly.loop_indices, poly.vertices):
                uv_layer.data[li].uv = uvs[vi]
    return mesh


def add_road(
    name: str,
    points: list[list[float]],
    width: float,
    mat: bpy.types.Material,
    z: float = Z_ROAD,
    uv_tile_m: float | None = None,
) -> bpy.types.Object | None:
    mesh = polyline_mesh(name, points, width, z=z, uv_tile_m=uv_tile_m)
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


def add_kerb_prism(
    name: str,
    run: list[list[float]],
    mat,
    road_edge_is_left: bool,
    uv_tile_m: float | None,
) -> bpy.types.Object | None:
    """A real stone kerb: top, road-facing riser, pavement face and end caps."""
    if len(run) < 2:
        return None
    verts, faces, uvs, _kinds = kerbs.kerb_profile(
        run,
        kerbs.KERB_WIDTH,
        kerbs.Z_ROAD_SURFACE - 0.005,
        kerbs.KERB_TOP,
        road_edge_is_left,
        uv_tile_m or 1.6,
    )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    li = 0
    for poly in mesh.polygons:
        for loop in poly.loop_indices:
            uv_layer.data[loop].uv = uvs[li]
            li += 1
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def add_sidewalks_and_curbs(
    roads: list,
    sidewalk_mat,
    curb_mat,
    spawn_xy: tuple[float, float] | None,
    sidewalk_tile_m: float | None = None,
    curb_tile_m: float | None = None,
) -> int:
    """Raised pavement ribbons + stone kerbs. Prefer roads near the human spawn for FPS.

    Kerbs and pavements are cut where another carriageway joins (a dropped-kerb
    mouth) so a side street is never walled off by the main road's kerb.
    """
    count = 0
    sidewalk_w = 2.0
    carriageways = kerbs.CarriagewayIndex(roads)
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
            # Never lay pavement/kerb over a tram bed (shared tram streets).
            for ri, rail_run in enumerate(railclear.clear_runs(walk, RAILS, railclear.CLEAR_SIDEWALK)):
                for ji, run in enumerate(kerbs.split_at_carriageways(rail_run, carriageways, i, 0.0)):
                    if add_road(
                        f"sidewalk_{i}_{side}_{ri}_{ji}",
                        run,
                        sidewalk_w,
                        sidewalk_mat,
                        z=Z_SIDEWALK,
                        uv_tile_m=sidewalk_tile_m,
                    ):
                        count += 1
            # Road lies to the right of a ribbon offset to the left (sign +1), and vice versa.
            for ri, rail_run in enumerate(railclear.clear_runs(curb, RAILS, railclear.CLEAR_CURB)):
                for ji, run in enumerate(kerbs.split_at_carriageways(rail_run, carriageways, i, -0.1)):
                    if add_kerb_prism(
                        f"curb_{i}_{side}_{ri}_{ji}", run, curb_mat, sign < 0, curb_tile_m
                    ):
                        count += 1
    return count


def add_parked_cars(
    layout: dict,
    spawn_xy: tuple[float, float],
    body_mats: list,
    glass_mat,
    tire_mat,
    max_cars: int = 64,
) -> dict:
    """Parked cars on OSM parallel kerbside parking — Kenney fleet GLBs when present.

    Placement (side, spacing, clearance from the runtime traffic lane, junctions, crossings,
    signals, stops, trees) is planned by ``cityview.parking``. Meshes come from
    ``viewer/cars/`` (Antwerp-weighted mix); box bodies are the fallback only.
    """

    def _box_fallback(plan: list) -> dict:
        for placed, car in enumerate(plan):
            x, y, yaw, lift = car["x"], car["y"], car["yaw"], car.get("lift", 0.0)
            body = add_box(f"car_{placed}", (4.2, 1.75, 1.35), (x, y, 0.75 + lift), yaw)
            assign(body, body_mats[placed % len(body_mats)])
            cabin = add_box(
                f"car_g_{placed}",
                (2.0, 1.55, 0.65),
                (x + math.cos(yaw) * 0.15, y + math.sin(yaw) * 0.15, 1.45 + lift),
                yaw,
            )
            assign(cabin, glass_mat)
            for wx, wy in ((1.35, 0.85), (1.35, -0.85), (-1.35, 0.85), (-1.35, -0.85)):
                lx = x + math.cos(yaw) * wx - math.sin(yaw) * wy
                ly = y + math.sin(yaw) * wx + math.cos(yaw) * wy
                wheel = add_box(f"car_w_{placed}_{wx}_{wy}", (0.55, 0.22, 0.55), (lx, ly, 0.28 + lift), yaw)
                assign(wheel, tire_mat)
        return {"cars": len(plan), "summary": parking_plan.summarize(plan)}

    if cars_blender is not None:
        return cars_blender.add_parked_cars(
            layout,
            spawn_xy,
            RAILS,
            railclear.CLEAR_PARKED_CAR,
            max_cars=max_cars,
            fallback=_box_fallback,
        )
    plan = parking_plan.plan_parked_cars(
        layout,
        spawn_xy,
        max_cars=max_cars,
        blocked=lambda x, y: RAILS.within(x, y, railclear.CLEAR_PARKED_CAR),
    )
    return _box_fallback(plan)


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
        if line.get("tunnel"):
            # Premetro / tunnel ways are below ground — never draw them at grade.
            continue
        pts = line.get("points") or []
        if len(pts) < 2:
            continue
        wid = 2.4 if mode == "tram" else 2.8
        if add_road(f"tram_{line.get('id', i)}", pts, wid, bed_mat, z=Z_TRAM_BED):
            tracks += 1
        # Twin rails as thinner overlays, strictly above every other flat layer.
        left = offset_polyline(pts, 0.55)
        right = offset_polyline(pts, -0.55)
        add_road(f"rail_l_{line.get('id', i)}", left, 0.18, track_mat, z=Z_TRAM_RAIL)
        add_road(f"rail_r_{line.get('id', i)}", right, 0.18, track_mat, z=Z_TRAM_RAIL)

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
            # Prefer right-hand curb; flip to left if that lands on a tram bed.
            rx, ry = ty, -tx
            pole_x = pole_y = None
            side = 1.0
            for sign in (1.0, -1.0):
                px = sx + rx * sign * (half + 0.85)
                py = sy + ry * sign * (half + 0.85)
                if RAILS and RAILS.within(px, py, railclear.CLEAR_SIGNAL_POLE):
                    continue
                pole_x, pole_y = px, py
                side = sign
                break
            if pole_x is None:
                continue
            # Local +Y = front: lenses look at the traffic this approach controls.
            yaw = vehicle_signal_yaw(tx, ty)
            ped_yaw = pedestrian_signal_yaw(rx, ry, side)
            placements.append(
                {
                    "pole_x": pole_x,
                    "pole_y": pole_y,
                    "stop_x": sx,
                    "stop_y": sy,
                    "tx": tx,
                    "ty": ty,
                    "yaw": yaw,
                    "ped_yaw": ped_yaw,
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
    *,
    ped_yaw: float | None = None,
    ped_mats: list | None = None,
) -> None:
    """Pole on the curb; vehicle head faces controlled traffic; optional ped head."""
    pole = add_box(f"{name}_pole", (0.12, 0.12, 3.4), (x, y, 1.7), yaw)
    assign(pole, pole_mat)
    # Local +Y is the face direction after rot_z=yaw (same convention as clutter).
    fx, fy = face_dir(yaw)
    hx, hy = x + fx * 0.2, y + fy * 0.2
    head = add_box(f"{name}_head", (0.28, 0.22, 0.85), (hx, hy, 3.55), yaw)
    assign(head, housing_mat)
    for i, mat in enumerate(lamp_mats):
        lx = hx + fx * 0.14
        ly = hy + fy * 0.14
        # Dark “off” lenses in the GLB; the viewer lights the active aspect.
        lamp = add_box(f"{name}_l{i}", (0.16, 0.08, 0.16), (lx, ly, 3.85 - i * 0.26), yaw)
        assign(lamp, mat)

    if ped_yaw is None or not ped_mats:
        return
    # Pedestrian signal: smaller two-aspect head facing people waiting to cross.
    pfx, pfy = face_dir(ped_yaw)
    phx, phy = x + pfx * 0.18, y + pfy * 0.18
    ped_head = add_box(f"{name}_ped_head", (0.22, 0.14, 0.55), (phx, phy, 2.35), ped_yaw)
    assign(ped_head, housing_mat)
    for i, mat in enumerate(ped_mats[:2]):
        plx = phx + pfx * 0.1
        ply = phy + pfy * 0.1
        lamp = add_box(
            f"{name}_ped_l{i}",
            (0.14, 0.06, 0.18),
            (plx, ply, 2.52 - i * 0.22),
            ped_yaw,
        )
        assign(lamp, mat)
        # Stick-figure silhouette on each aspect (standing red / walking green).
        _add_ped_figure(f"{name}_ped_fig{i}", plx, ply, 2.52 - i * 0.22, ped_yaw, mat, walking=i == 1)


def _add_ped_figure(
    name: str,
    x: float,
    y: float,
    z: float,
    yaw: float,
    mat,
    *,
    walking: bool,
) -> None:
    """Tiny standing / walking man silhouette in the pedestrian lens plane."""
    fx, fy = face_dir(yaw)
    # Sit the figure on the front of the lens.
    cx, cy = x + fx * 0.04, y + fy * 0.04
    head = add_box(f"{name}_h", (0.04, 0.03, 0.04), (cx, cy, z + 0.06), yaw)
    assign(head, mat)
    torso = add_box(f"{name}_t", (0.05, 0.03, 0.08), (cx, cy, z + 0.0), yaw)
    assign(torso, mat)
    if walking:
        # Stride: one leg forward, one back; one arm forward.
        leg_a = add_box(f"{name}_la", (0.025, 0.03, 0.07), (cx + fx * 0.02, cy + fy * 0.02, z - 0.07), yaw)
        leg_b = add_box(f"{name}_lb", (0.025, 0.03, 0.07), (cx - fx * 0.02, cy - fy * 0.02, z - 0.07), yaw)
        arm = add_box(f"{name}_a", (0.06, 0.025, 0.025), (cx + fx * 0.03, cy + fy * 0.03, z + 0.02), yaw)
        assign(leg_a, mat)
        assign(leg_b, mat)
        assign(arm, mat)
    else:
        legs = add_box(f"{name}_lg", (0.04, 0.03, 0.08), (cx, cy, z - 0.07), yaw)
        assign(legs, mat)


def _add_zebra_stripe(name: str, cx: float, cy: float, tx: float, ty: float, span: float, stripe_mat) -> int:
    """One stripe across a carriageway, split so rail-overlapping pieces ride on top.

    Pieces outside rail corridors sit on the asphalt layer; pieces over a tram bed
    sit above the rails (never z-fighting underneath them).
    """
    yaw = math.atan2(ty, tx)
    ux, uy = -ty, tx
    made = 0
    for k, (t0, t1, on_rail) in enumerate(railclear.span_intervals(cx, cy, ux, uy, span, RAILS)):
        length = t1 - t0
        if length < 0.05:
            continue
        mid = (t0 + t1) * 0.5
        piece = add_box(
            f"{'zebra_rail' if on_rail else 'zebra'}_{name}_{k}",
            (0.42, length, 0.02),
            (cx + ux * mid, cy + uy * mid, Z_ZEBRA_ON_RAIL if on_rail else Z_ZEBRA),
            yaw,
        )
        assign(piece, stripe_mat)
        made += 1
    return made


def add_crosswalks(
    placements: list[dict],
    stripe_mat,
    spawn_xy,
    crossings: list[dict] | None = None,
) -> int:
    """Zebra sets: one per signal approach, plus OSM crossings that sit on rails.

    * A signal-approach zebra that would overlap a tram corridor is a decorative
      guess, so it is skipped unless OSM maps a pedestrian crossing right there.
    * OSM crossings on rails are drawn over the rails (see ``_add_zebra_stripe``).
    """
    count = 0
    crossings = crossings or []
    covered: list[tuple[float, float]] = []
    for i, pl in enumerate(placements):
        sx, sy = float(pl["stop_x"]), float(pl["stop_y"])
        if spawn_xy is not None and math.hypot(sx - spawn_xy[0], sy - spawn_xy[1]) > 220.0:
            continue
        tx, ty = float(pl["tx"]), float(pl["ty"])
        width = float(pl.get("width") or 6.0)
        span = max(3.2, min(7.5, width * 0.92))
        if railclear.zebra_touches_rails(sx, sy, tx, ty, span, RAILS):
            backed = railclear.nearest_crossing_node(sx, sy, crossings, 9.0)
            if backed is None:
                continue
        covered.append((sx, sy))
        for s in range(5):
            along = -1.6 + s * 0.8
            count += _add_zebra_stripe(f"{i}_{s}", sx + tx * along, sy + ty * along, tx, ty, span, stripe_mat)

    # Real OSM crossings over/next to rails that no signal zebra already covers.
    placed_rail = 0
    for j, node in enumerate(crossings):
        if placed_rail >= 24:
            break
        x, y = float(node["x"]), float(node["y"])
        if spawn_xy is not None and math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > 220.0:
            continue
        if not RAILS.within(x, y, railclear.RAIL_CROSSING_SNAP):
            continue
        if any(math.hypot(x - cx, y - cy) < 9.0 for cx, cy in covered):
            continue
        tan = RAILS.nearest_tangent(x, y)
        if tan is None:
            continue
        tx, ty = tan
        span = 5.5
        covered.append((x, y))
        placed_rail += 1
        for s in range(5):
            along = -1.6 + s * 0.8
            count += _add_zebra_stripe(f"x{j}_{s}", x + tx * along, y + ty * along, tx, ty, span, stripe_mat)
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
    skip_lamps: bool = False,
) -> dict:
    """Lamp posts near the spawn (bins / bollards / bike racks: see ``clutter_blender``).

    Benches are *not* generated here: they come from surveyed positions with a surveyed
    or rule-derived facing (``cityview.benches`` / ``benches_blender``).
    """
    stats = {"lamps": 0, "street_trees": 0}
    # Street trees now come from surveyed positions (layout["trees"], see
    # trees_blender); the old evenly-spaced kerb rows read as a straight parade.
    max_lamps, max_trees = 42, 0
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
                    # Trees need the widest berth (canopy); furniture a tighter one.
                    if RAILS.within(
                        x, y, railclear.CLEAR_TREE if mode == "trees" else railclear.CLEAR_FURNITURE
                    ):
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
                        # Bins, bollards and bike racks are no longer invented here: they come
                        # from OSM-mapped points (``clutter_blender``). Only lamps stay
                        # procedural — OSM has no ``highway=street_lamp`` for this tile.
                        if slot % 5 == 0 and stats["lamps"] < max_lamps and not skip_lamps:
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
                    t += step + (slot % 3) * 0.8
                dist += seg
    return stats


def add_park_amenities(
    parks: list,
    spawn_xy: tuple[float, float] | None,
    path_mat,
    hedge_mat,
) -> dict:
    """Gravel paths and edge hedges so greens read usable (benches: see benches_blender)."""
    stats = {"paths": 0, "hedges": 0}
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
        if not any(RAILS.within(px, py, railclear.CLEAR_SIDEWALK) for px, py in path_pts) and add_road(
            f"park_path_{park.get('id')}", path_pts, 1.6, path_mat, z=Z_PARK_PATH
        ):
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
            if RAILS.within(mx, my, railclear.CLEAR_FURNITURE + length * 0.3):
                continue
            yaw = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
            hedge = add_box(
                f"hedge_{park.get('id')}_{ei}",
                (min(length * 0.85, 12.0), 0.55, 1.15),
                (mx, my, 0.55),
                yaw,
            )
            assign(hedge, hedge_mat)
            stats["hedges"] += 1
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
                if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) <= 160.0 and not RAILS.within(
                    x, y, railclear.CLEAR_MARKING
                ):
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
                if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) <= 120.0 and not RAILS.within(
                    x, y, railclear.CLEAR_PARKED_CAR
                ):
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
    global RAILS, TYPES_DOC, FACADE_PHOTO_MAT, DOORSTEP_MAT
    TYPES_DOC = types_doc
    STATS["photo_quads"] = 0
    STATS["door_steps"] = 0
    STATS["awnings"] = 0
    STATS["reveals"] = 0
    STATS["downpipes"] = 0
    STATS["photo_edges"] = 0
    atlas_img = load_texture(TEXTURES_DIR / facade_kit.ATLAS_FILE)
    FACADE_PHOTO_MAT = (
        textured("facade_photo_atlas", atlas_img, (0.6, 0.55, 0.45, 1.0), rough=0.9, extend="EXTEND")
        if atlas_img is not None
        else None
    )
    if FACADE_PHOTO_MAT is not None:
        add_normal_map(FACADE_PHOTO_MAT, TEXTURES_DIR / facade_kit.NORMAL_FILE, strength=NORMAL_MAP_STRENGTH)
        add_emissive_map(FACADE_PHOTO_MAT, TEXTURES_DIR / facade_kit.EMISSIVE_FILE)
    print(f"Facade photo atlas: {'loaded' if atlas_img is not None else 'MISSING'}")
    RAILS = RailIndex.from_layout(layout)
    print(f"Surface rail segments: {len(RAILS.segments)}")
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
    surf_imgs: dict[str, object] = {}

    def surface_img(key: str):
        if key not in surf_imgs:
            surf_imgs[key] = load_texture(SURFACES_DIR / surface_kit.surface_file(key))
        return surf_imgs[key]

    def surface_mat(key: str, name: str, fallback, rough: float, tint=None, extend: str = "REPEAT"):
        return textured(name, surface_img(key), fallback, rough=rough, tint=tint, extend=extend)

    gravel_tile = surface_kit.surface_tile_m("gravel")
    guv = ground.uv_layers.new(name="UVMap")
    for poly in ground.polygons:
        for li, vi in zip(poly.loop_indices, poly.vertices):
            vx, vy, _vz = ground.vertices[vi].co
            guv.data[li].uv = (vx / gravel_tile, vy / gravel_tile)
    assign(
        link(bpy.data.objects.new("ground", ground)),
        surface_mat("gravel", "ground", (0.74, 0.73, 0.68, 1.0), 0.95, tint=GROUND_TINT),
    )

    water_mat = principled("water", (0.18, 0.32, 0.42, 1.0), 0.12)
    park_mat = surface_mat("grass", "park", (0.28, 0.48, 0.26, 1.0), 0.92, tint=PARK_TINT)
    road_mat = surface_mat("asphalt", "asphalt", (0.08, 0.08, 0.09, 1.0), 0.96)
    sidewalk_mat = surface_mat("sidewalk", "sidewalk", (0.55, 0.54, 0.50, 1.0), 0.95)
    curb_mat = surface_mat("curb", "curb", (0.42, 0.41, 0.38, 1.0), 0.9)
    # Doorsteps: the same granite, a touch bluer and darker (arduin) so they read against the plinth.
    DOORSTEP_MAT = surface_mat("curb", "doorstep", (0.36, 0.36, 0.38, 1.0), 0.88, tint=(0.82, 0.84, 0.88))
    # Roof families: slate / clay pantiles / zinc / bitumen. Each family gets one material per
    # aerial-measured tint cluster (roof_aerial.json); fallback tints if the file is missing.
    roof_tex: dict[str, list] = {}
    fallback_tints = {
        "roof_slate": ((0.55, 0.55, 0.55), (0.40, 0.41, 0.43)),
        "roof_clay": ((0.62, 0.40, 0.33), (0.50, 0.33, 0.28)),
        "roof_zinc": ((0.60, 0.62, 0.65), (0.45, 0.47, 0.50)),
        "roof_flat": ((0.40, 0.40, 0.42), (0.30, 0.30, 0.32)),
    }
    for key in ("roof_slate", "roof_clay", "roof_zinc", "roof_flat"):
        if surface_img(key) is None:
            continue
        clusters = (((ROOF_AERIAL or {}).get("families") or {}).get(key) or {}).get("clusters") or []
        tints = [tuple(c["tint"]) for c in clusters] or list(fallback_tints[key])
        roof_tex[key] = [
            surface_mat(key, f"{key}_{ti}", (0.18, 0.17, 0.16, 1.0), 0.78, tint=t) for ti, t in enumerate(tints)
        ]
    trunk_mat = principled("trunk", (0.28, 0.18, 0.10, 1.0), 0.9)
    # Varied park canopy: deep shade, sun-lit lime, dusty summer olive.
    canopy_mats = [
        principled("canopy_a", (0.16, 0.40, 0.13, 1.0), 0.9),
        principled("canopy_b", (0.24, 0.44, 0.14, 1.0), 0.86),
        principled("canopy_c", (0.12, 0.32, 0.15, 1.0), 0.92),
        principled("canopy_d", (0.30, 0.42, 0.16, 1.0), 0.84),
        principled("canopy_e", (0.20, 0.36, 0.10, 1.0), 0.88),
    ]
    conifer_mat = principled("conifer", (0.07, 0.22, 0.11, 1.0), 0.92)
    bush_mats = [
        principled("bush_a", (0.20, 0.34, 0.11, 1.0), 0.92),
        principled("bush_b", (0.26, 0.38, 0.14, 1.0), 0.9),
        principled("bush_c", (0.18, 0.30, 0.12, 1.0), 0.94),
    ]
    ivy_mats = [
        principled("ivy_a", (0.14, 0.30, 0.10, 1.0), 0.92),
        principled("ivy_b", (0.18, 0.34, 0.12, 1.0), 0.9),
    ]
    # Climbing-plant palette; order matches cityview.climbers LEAF_* / STEM constants.
    climber_mats = [
        principled("climber_dark", (0.05, 0.13, 0.05, 1.0), 0.9),
        principled("climber_mid", (0.09, 0.20, 0.07, 1.0), 0.92),
        principled("climber_light", (0.15, 0.28, 0.09, 1.0), 0.92),
        principled("climber_olive", (0.21, 0.26, 0.08, 1.0), 0.94),
        principled("climber_red", (0.40, 0.10, 0.06, 1.0), 0.9),
        principled("climber_stem", (0.15, 0.10, 0.07, 1.0), 0.95),
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
    chimney_cap_mat = principled("chimney_cap", (0.50, 0.49, 0.46, 1.0), 0.85)
    chimney_pot_mat = principled("chimney_pot", (0.48, 0.23, 0.14, 1.0), 0.8)
    roof_box_mat = principled("roof_stairhead", (0.52, 0.50, 0.46, 1.0), 0.9)
    roof_metal_mat = principled("roof_plant", (0.60, 0.62, 0.63, 1.0), 0.5, metallic=0.4)
    pole_mat = principled("pole", (0.18, 0.18, 0.18, 1.0), 0.5, metallic=0.4)
    housing_mat = principled("tl_housing", (0.08, 0.08, 0.08, 1.0), 0.45, metallic=0.35)
    # Dim “off” lenses in the baked GLB — the walk viewer lights the active aspect.
    lamp_mats = [
        principled("tl_red", (0.22, 0.05, 0.04, 1.0), 0.55),
        principled("tl_amber", (0.22, 0.14, 0.04, 1.0), 0.55),
        principled("tl_green", (0.04, 0.18, 0.07, 1.0), 0.55),
    ]
    ped_mats = [
        principled("tl_ped_red", (0.2, 0.04, 0.04, 1.0), 0.55),
        principled("tl_ped_green", (0.04, 0.16, 0.06, 1.0), 0.55),
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
    lamp_head_mat = glowing("lamp_head", (0.75, 0.72, 0.55, 1.0), 0.35, (1.0, 0.78, 0.45, 1.0))
    clutter_mats = {
        "metal": pole_mat,
        "bin": bin_mat,
        "lamp_head": lamp_head_mat,
        "signal_red": principled("signal_red", (0.62, 0.06, 0.05, 1.0), 0.45, metallic=0.15),
        "signal_white": principled("signal_white", (0.82, 0.82, 0.78, 1.0), 0.5),
        "cabinet": principled("street_cabinet", (0.42, 0.45, 0.43, 1.0), 0.6, metallic=0.25),
        "meter_blue": principled("ticket_meter", (0.10, 0.20, 0.45, 1.0), 0.45, metallic=0.2),
        "container_green": principled("bring_glass_green", (0.10, 0.34, 0.18, 1.0), 0.55, metallic=0.1),
        "container_blue": principled("bring_pmd_blue", (0.12, 0.26, 0.58, 1.0), 0.55, metallic=0.1),
        "container_white": principled("bring_glass_white", (0.78, 0.78, 0.74, 1.0), 0.55, metallic=0.1),
    }

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
    tile_imgs: dict[str, object] = {}
    tile_avgs: dict[str, tuple[float, float, float]] = {}

    def wall_mat(n: str, st: dict):
        tid = facade_kit.wall_tile_for_type(n.split("__v")[0], types_doc)
        if tid not in tile_imgs:
            tile_imgs[tid] = load_texture(TEXTURES_DIR / facade_kit.wall_tile_file(tid))
            tile_avgs[tid] = image_average(tile_imgs[tid]) if tile_imgs[tid] is not None else (0.5, 0.5, 0.5)
        return textured(
            f"wall_{n}",
            tile_imgs[tid],
            st["wall"],
            rough=0.88,
            tint=wall_tint(st["wall"], tile_avgs[tid]),
        )

    church_mats = make_church_materials(surface_mat)
    mats = {
        "wall": {n: wall_mat(n, s) for n, s in style_items},
        "roof": {n: principled(f"roof_{n}", s["roof"], 0.72, metallic=0.05) for n, s in style_items},
        "roof_tex": roof_tex,
        "frame": {n: principled(f"frame_{n}", s["frame"], 0.62, metallic=0.12) for n, s in style_items},
        # Glazier glass — darker, slightly reflective so windows read as openings not stickers.
        "glass": {n: principled(f"glass_{n}", s["glass"], 0.12, metallic=0.35) for n, s in style_items},
        "plinth": {n: principled(f"plinth_{n}", s["plinth"], 0.92) for n, s in style_items},
        "trim": {n: principled(f"trim_{n}", s["trim"], 0.7) for n, s in style_items},
        "chimney": chimney_mat,
        "chimney_cap": chimney_cap_mat,
        "chimney_pot": chimney_pot_mat,
        "roof_box": roof_box_mat,
        "roof_metal": roof_metal_mat,
        "ivy": ivy_mats,
        "climber": climber_mats,
        "shutter": shutter_mats,
        "church": church_mats,
    }
    # Ensure the church style wall uses the same red-brick tile as the landmark volumes.
    if "church" in mats["wall"]:
        mats["wall"]["church"] = church_mats["brick"]
    print(f"Facade material keys: {len(style_items)}; church mats: brick/stone/slate/portal")

    spawn = layout.get("spawn") or {}
    spawn_xy = (float(spawn["x"]), float(spawn["y"])) if spawn.get("x") is not None else None

    for i, pond in enumerate(layout.get("water") or []):
        add_ring(f"water_{pond.get('id', i)}", pond["ring"], 0.0, Z_WATER, water_mat)
    for i, park in enumerate(layout.get("parks") or []):
        add_ring(
            f"park_{park.get('id', i)}",
            park["ring"],
            0.0,
            Z_PARK,
            park_mat,
            uv_tile_m=surface_kit.surface_tile_m("grass"),
        )
    courtyard_mats = {
        # Private lots wear differently from the street: same asphalt, a little paler and bluer.
        "asphalt": surface_mat("asphalt", "lot_asphalt", (0.14, 0.14, 0.15, 1.0), 0.94, tint=(0.80, 0.82, 0.86)),
        "paving": surface_mat("sidewalk", "yard_paving", (0.50, 0.49, 0.45, 1.0), 0.95, tint=(0.82, 0.80, 0.76)),
        "concrete": surface_mat("sidewalk", "yard_concrete", (0.48, 0.48, 0.47, 1.0), 0.96, tint=(0.62, 0.64, 0.66)),
        # Baked-colour yard textures (cityview/surface_textures.py): real setts, EPDM mats, turf rolls, earth, leaf litter.
        "sett": surface_mat("sett", "yard_sett", (0.40, 0.39, 0.36, 1.0), 0.90),
        "gravel": surface_mat("gravel", "yard_gravel", (0.60, 0.58, 0.52, 1.0), 0.96, tint=(0.30, 0.30, 0.28)),
        "grass": surface_mat("grass", "yard_grass", (0.28, 0.48, 0.26, 1.0), 0.92, tint=PARK_TINT),
        "woodland": surface_mat("forest", "woodland_floor", (0.14, 0.24, 0.12, 1.0), 0.96),
        "dirt": surface_mat("dirt", "site_dirt", (0.30, 0.24, 0.16, 1.0), 0.97),
        "rubber": surface_mat("rubber", "play_rubber", (0.46, 0.20, 0.14, 1.0), 0.92),
        "turf": surface_mat("turf", "pitch_turf", (0.10, 0.34, 0.12, 1.0), 0.93),
        "pool": principled("pool_water", (0.16, 0.42, 0.52, 1.0), 0.1),
    }
    courtyard_tiles = {
        "asphalt": surface_kit.surface_tile_m("asphalt"),
        "paving": surface_kit.surface_tile_m("sidewalk"),
        "concrete": surface_kit.surface_tile_m("sidewalk"),
        "sett": surface_kit.surface_tile_m("sett"),
        "gravel": surface_kit.surface_tile_m("gravel"),
        "grass": surface_kit.surface_tile_m("grass"),
        "woodland": surface_kit.surface_tile_m("forest"),
        "dirt": surface_kit.surface_tile_m("dirt"),
        "rubber": surface_kit.surface_tile_m("rubber"),
        "turf": surface_kit.surface_tile_m("turf"),
    }
    courtyard_stats = courtyards_blender.add_courtyards(layout, courtyard_mats, courtyard_tiles)
    print(f"Courtyard surfaces (OSM car parks, playgrounds, pitches, sites, pools, woods): {courtyard_stats}")
    for i, road in enumerate(layout.get("roads") or []):
        add_road(
            f"road_{road.get('id', i)}",
            road["points"],
            float(road["width"]),
            road_mat,
            z=Z_ROAD,
            uv_tile_m=surface_kit.surface_tile_m("asphalt"),
        )

    tram_n, stop_n = add_transit_layer(layout, spawn_xy)
    print(f"Transit: {tram_n} tram tracks, {stop_n} stops")

    walks = add_sidewalks_and_curbs(
        layout.get("roads") or [],
        sidewalk_mat,
        curb_mat,
        spawn_xy,
        sidewalk_tile_m=surface_kit.surface_tile_m("sidewalk"),
        curb_tile_m=surface_kit.surface_tile_m("curb"),
    )
    print(f"Sidewalk/curb strips: {walks}")

    veg = trees_blender.add_vegetation(layout, RAILS, trunk_mat, canopy_mats, conifer_mat, bush_mats)
    print(f"Trees and shrubs (surveyed + sparse-park fill): {veg}")
    park_am = add_park_amenities(layout.get("parks") or [], spawn_xy, path_mat, hedge_mat)
    print(f"Park amenities: {park_am}")
    bench_stats = benches_blender.add_benches(layout, RAILS, wood_mat, pole_mat)
    print(f"Benches (surveyed positions + facing): {bench_stats}")
    barrier_mats = {
        "render": principled("wall_render", (0.46, 0.42, 0.35, 1.0), 0.92),
        "brick": principled("wall_brick", (0.36, 0.17, 0.12, 1.0), 0.92),
        "concrete": principled("wall_concrete", (0.38, 0.38, 0.36, 1.0), 0.95),
        "stone": principled("wall_stone", (0.42, 0.39, 0.33, 1.0), 0.9),
        "coping": principled("wall_coping", (0.50, 0.49, 0.46, 1.0), 0.85),
        "hedge": hedge_mat,
        "metal": pole_mat,
    }
    barrier_stats = barriers_blender.add_barriers(layout, RAILS, barrier_mats)
    print(f"Courtyard barriers (OSM walls, hedges, fences): {barrier_stats}")
    clutter_stats = clutter_blender.add_clutter(layout, RAILS, clutter_mats)
    print(f"Street clutter (OSM-mapped bins, hoops, bollards, hydrants, ...): {clutter_stats}")
    if velo_blender is not None:
        velo_mats = {
            "metal": principled("velo_dock_metal", (0.08, 0.08, 0.09, 1.0), 0.45),
            "frame": principled("velo_frame_red", (0.72, 0.06, 0.12, 1.0), 0.55),
            "mudguard": principled("velo_mudguard", (0.94, 0.93, 0.90, 1.0), 0.7),
            "tire": principled("velo_tire", (0.08, 0.08, 0.08, 1.0), 0.95),
            "signal_red": principled("velo_accent_red", (0.78, 0.05, 0.1, 1.0), 0.5),
        }
        velo_stats = velo_blender.add_velo_stations(layout, RAILS, velo_mats)
        print(f"Velo docks (GBFS stations): {velo_stats}")

    signal_placements = collect_signal_placements(layout, spawn_xy=spawn_xy)
    lights_n = 0
    for i, pl in enumerate(signal_placements):
        add_traffic_light(
            f"signal_{i}",
            float(pl["pole_x"]),
            float(pl["pole_y"]),
            float(pl["yaw"]),
            pole_mat,
            housing_mat,
            lamp_mats,
            ped_yaw=float(pl["ped_yaw"]),
            ped_mats=ped_mats,
        )
        lights_n += 1
    print(f"Traffic lights: {lights_n} (from {len(signal_placements)} approaches)")
    zebras = add_crosswalks(signal_placements, stripe_mat, spawn_xy, layout.get("crossings") or [])
    print(f"Crosswalk stripes: {zebras}")

    if spawn_xy is not None:
        dashes = add_road_dashes(layout.get("roads") or [], spawn_xy, dash_mat)
        print(f"Road dashes near spawn: {dashes}")
        wear = add_asphalt_wear(layout.get("roads") or [], spawn_xy, wear_mats)
        print(f"Asphalt wear patches near spawn: {wear}")
        ironwork = roadware_blender.add_roadware(
            layout,
            spawn_xy,
            RAILS,
            principled("road_iron", (0.07, 0.07, 0.065, 1.0), 0.55, metallic=0.5),
            principled("road_iron_worn", (0.20, 0.19, 0.17, 1.0), 0.45, metallic=0.6),
        )
        print(f"Road ironwork (manholes, gully grates): {ironwork}")
        cars = add_parked_cars(layout, spawn_xy, car_mats, car_glass, tire_mat, max_cars=64)
        print(f"Parked cars near spawn (OSM parking:* only): {cars['summary']}")
        furniture = add_street_furniture(
            layout.get("roads") or [],
            spawn_xy,
            pole_mat,
            wood_mat,
            bin_mat,
            lamp_head_mat,
            trunk_mat,
            canopy_mats,
            skip_lamps=any(c.get("kind") == "lamp" for c in layout.get("clutter") or []),
        )
        print(f"Street furniture: {furniture}")

    # Climbing plants are rare: per street, most get none, some one house, hard cap two.
    CLIMBERS.clear()
    CLIMBERS.update(climbers.plan_climbers(layout, spawn_xy))
    CLIMBER_STATS["leaves"] = 0
    streets = {c["street"] for c in CLIMBERS.values()}
    print(f"Climbing plants: {len(CLIMBERS)} houses on {len(streets)} streets (max {climbers.MAX_PER_STREET}/street)")

    DORMER_STATS["dormers"] = 0
    ROOFTOP_STATS.update({"chimneys": 0, "plant": 0})
    ROOF_STATS.clear()
    ROOF_STATS.update({"measured": 0, "fallback": 0})
    for bldg in layout.get("buildings") or []:
        add_building(bldg, mats, spawn_xy=spawn_xy)
    print(f"Rooftop detail: {ROOFTOP_STATS}, merged into {flush_rooftop()} meshes")
    print(f"Mansard dormers: {DORMER_STATS['dormers']}; textured roof families: {sorted((mats.get('roof_tex') or {}))}")
    print(f"Climbing-plant leaf clusters: {CLIMBER_STATS['leaves']}")
    print(f"Aerial-matched roofs: {ROOF_STATS}")
    print(
        f"Photo facades: {STATS['photo_edges']} street edges, {STATS['photo_quads']} textured quads "
        f"(atlas {'on' if FACADE_PHOTO_MAT is not None else 'OFF'}); doorsteps: {STATS['door_steps']}; awnings: {STATS['awnings']}; window reveals: {STATS['reveals']}; downpipes: {STATS['downpipes']}"
    )

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
        export_image_format="JPEG",  # photo textures stay JPEG inside the GLB
        export_jpeg_quality=85,
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
