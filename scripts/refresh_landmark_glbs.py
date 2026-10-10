"""Replace the seven rebuilt landmarks in the city blend and write their GLBs.

The viewer streams viewer/landmarks/{osm id}.glb in world coordinates (Y-up),
the same way peel_streamed_landmarks exports them. Run:

    blender -b output/antwerp_harmonie.blend --python scripts/refresh_landmark_glbs.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cityview import landmark_models as LM  # noqa: E402

WANT = {
    "harmonie_koetshuis",
    "benoit_34",
    "benoit_38",
    "benoit_40",
    "bonifacius",
    "heilig_hart",
    "heilig_hart_klooster",
}

# Logical kit name -> (material already in the blend, UV tile metres).
MATS = {
    "brick": ("lm_brick_red", 1.6),
    "brick_dark": ("lm_brick_dark", 1.6),
    "brick_brown": ("lm_brick_brown", 1.6),
    "brick_cream": ("lm_brick_cream", 1.6),
    "brick_yellow": ("lm_brick_yellow", 1.6),
    "stone_white": ("lm_stone_white", 2.4),
    "stone_grey": ("lm_stone_grey", 2.4),
    "bluestone": ("lm_bluestone", 1.6),
    "slate": ("lm_slate", 2.4),
    "glass": ("lm_glass", 2.0),
    "glass_roof": ("lm_glass_roof", 2.0),
    "glass_amber": ("lm_glass_amber", 2.0),
    "glass_green": ("lm_glass_green", 2.0),
    "glass_blue": ("lm_glass_blue", 2.0),
    "glass_dark": ("lm_glass_dark", 2.0),
    "frame_white": ("lm_frame_white", 2.0),
    "frame_dark": ("lm_frame_dark", 2.0),
    "iron": ("lm_iron", 2.0),
    "gold": ("lm_gold", 2.0),
    "door": ("lm_door", 2.0),
}

FALLBACK = {
    "brick": (0.45, 0.18, 0.12, 1),
    "brick_dark": (0.28, 0.1, 0.08, 1),
    "brick_cream": (0.78, 0.76, 0.7, 1),
    "brick_yellow": (0.86, 0.7, 0.38, 1),
    "stone_white": (0.86, 0.84, 0.79, 1),
    "stone_grey": (0.62, 0.62, 0.6, 1),
    "bluestone": (0.3, 0.31, 0.33, 1),
    "slate": (0.14, 0.14, 0.15, 1),
    "glass": (0.04, 0.05, 0.06, 1),
    "glass_amber": (0.86, 0.52, 0.1, 1),
    "glass_green": (0.12, 0.48, 0.28, 1),
    "glass_blue": (0.1, 0.24, 0.62, 1),
    "glass_dark": (0.015, 0.016, 0.018, 1),
    "frame_dark": (0.09, 0.09, 0.09, 1),
    "iron": (0.06, 0.07, 0.065, 1),
    "gold": (0.78, 0.6, 0.22, 1),
    "door": (0.13, 0.07, 0.04, 1),
}


def _material(logical: str):
    name, tile = MATS.get(logical, (f"lm_{logical}", 2.0))
    mat = bpy.data.materials.get(name)
    if mat is None:
        # Church slate lives on the shared church material, not lm_slate.
        if logical == "slate":
            mat = bpy.data.materials.get("church_slate") or bpy.data.materials.get("roof_slate")
        if mat is None:
            mat = bpy.data.materials.new(name)
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = FALLBACK.get(logical, (0.5, 0.5, 0.5, 1))
                bsdf.inputs["Roughness"].default_value = 0.8
            print(f"fallback material {name}")
    return mat, tile


def _uvs(faces, uv_layer, tile_m: float) -> None:
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


def _add(name: str, kit, collection) -> bpy.types.Object:
    names = sorted(kit.materials_used())
    slot = {n: i for i, n in enumerate(names)}
    mats = {n: _material(n) for n in names}
    bm = bmesh.new()
    verts = [bm.verts.new(v) for v in kit.verts]
    for face, mname in zip(kit.faces, kit.mats):
        try:
            bf = bm.faces.new([verts[i] for i in face])
        except ValueError:
            continue
        bf.material_index = slot[mname]
    bm.normal_update()
    uv = bm.loops.layers.uv.verify()
    for mname, idx in slot.items():
        _uvs([bf for bf in bm.faces if bf.material_index == idx], uv, mats[mname][1])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    for mname in names:
        obj.data.materials.append(mats[mname][0])
    return obj


def _export(obj: bpy.types.Object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_image_format="JPEG",
        export_jpeg_quality=85,
        export_yup=True,
        export_cameras=False,
    )
    print(f"Wrote {path} ({path.stat().st_size / 1e6:.2f} MB)")


def main() -> None:
    layout = json.loads((ROOT / "output" / "antwerp_harmonie_layout.json").read_text())
    viewer = ROOT / "viewer" / "landmarks"
    staged = ROOT / "output" / "landmarks"
    done = []
    for bldg in layout.get("buildings") or []:
        lm = bldg.get("landmark") or {}
        kind = lm.get("custom")
        if kind not in WANT:
            continue
        kit = LM.build_landmark(bldg)
        if kit is None:
            print(f"skip {kind}: builder returned nothing")
            continue
        name = f"bldg_{bldg['id']}_landmark"
        old = bpy.data.objects.get(name)
        coll = old.users_collection[0] if old and old.users_collection else bpy.context.scene.collection
        if old:
            data = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if data and data.users == 0:
                bpy.data.meshes.remove(data)
        obj = _add(name, kit, coll)
        _export(obj, viewer / f"{bldg['id']}.glb")
        _export(obj, staged / f"{bldg['id']}.glb")
        done.append(kind)
    missing = WANT - set(done)
    if missing:
        raise SystemExit(f"landmarks not in the layout: {sorted(missing)}")
    bpy.ops.wm.save_mainfile()
    print("saved", bpy.data.filepath)
    print("refreshed", ", ".join(sorted(done)))


if __name__ == "__main__":
    main()
