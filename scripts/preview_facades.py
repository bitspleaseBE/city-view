"""Street-front check of the hand models, without the rest of the city.

    blender -b --python scripts/preview_facades.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cityview.landmark_facades import _span, _wall_frame  # noqa: E402
from cityview import landmark_models as LM  # noqa: E402

COLORS = {
    "brick": (0.45, 0.18, 0.12, 1),
    "brick_dark": (0.28, 0.1, 0.08, 1),
    "brick_cream": (0.72, 0.68, 0.58, 1),
    "brick_yellow": (0.72, 0.55, 0.22, 1),
    "stone_white": (0.82, 0.8, 0.74, 1),
    "stone_grey": (0.45, 0.44, 0.42, 1),
    "bluestone": (0.35, 0.38, 0.4, 1),
    "slate": (0.22, 0.26, 0.3, 1),
    "glass": (0.55, 0.7, 0.78, 1),
    "glass_dark": (0.15, 0.2, 0.28, 1),
    "glass_amber": (0.85, 0.55, 0.15, 1),
    "glass_green": (0.15, 0.45, 0.28, 1),
    "glass_blue": (0.15, 0.28, 0.62, 1),
    "gold": (0.75, 0.58, 0.15, 1),
    "iron": (0.12, 0.12, 0.13, 1),
    "door": (0.08, 0.1, 0.16, 1),
    "frame_dark": (0.15, 0.14, 0.13, 1),
}

# (stand-off metres, look-at height, lens)
SHOT = {
    "harmonie_koetshuis": (18.0, 5.5, 28),
    "benoit_34": (14.0, 7.0, 32),
    "benoit_38": (14.0, 8.0, 32),
    "benoit_40": (14.0, 7.0, 32),
    "bonifacius": (26.0, 11.0, 22),
    "heilig_hart": (24.0, 12.0, 22),
    "heilig_hart_klooster": (22.0, 8.0, 28),
}


def _material(name: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = COLORS.get(name, (0.6, 0.6, 0.6, 1))
        bsdf.inputs["Roughness"].default_value = 0.8
    return mat


def _add(kit, name: str):
    import bmesh

    names = sorted(kit.materials_used())
    slot = {n: i for i, n in enumerate(names)}
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    verts = [bm.verts.new(v) for v in kit.verts]
    for face, mname in zip(kit.faces, kit.mats):
        try:
            bf = bm.faces.new([verts[i] for i in face])
        except ValueError:
            continue
        bf.material_index = slot[mname]
    bm.to_mesh(mesh)
    bm.free()
    for n in names:
        mesh.materials.append(_material(f"{name}_{n}"))
        # recolor: materials were created with the long name; set color now
    for i, n in enumerate(names):
        mat = mesh.materials[i]
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = COLORS.get(n, (0.6, 0.6, 0.6, 1))
    return obj


def main() -> None:
    fix = json.loads((ROOT / "cityview/testdata/landmark_footprints.json").read_text())
    out = ROOT / "output" / "landmark_renders"
    out.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 1400
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 90
    world = bpy.data.worlds.new("preview")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.75, 0.78, 0.82, 1)
    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = 3.5
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.8, 0.2, 0.4)
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    for b in fix["buildings"]:
        kind = b["landmark"]["custom"]
        if kind not in SHOT:
            continue
        for obj in list(bpy.data.objects):
            if obj.type == "MESH":
                bpy.data.objects.remove(obj, do_unlink=True)
        kit = LM.build_landmark(b)
        _add(kit, kind)
        _f, _outline, _width, _depth, edge = _span(b["ring"], b["landmark"])
        wf = _wall_frame(edge.frame(), edge)
        # Aim at the street wall. The nave runs back from it; framing every vertex
        # swings the camera onto the side wall.
        stand, look_z, lens = SHOT[kind]
        if kind == "bonifacius":
            locs = [wf.local(float(p[0]), float(p[1])) for p in b["ring"]]
            near = [a for a, d in locs if -1.2 <= d <= 2.5]
            if near:
                amid = (min(near) + max(near)) * 0.5
                stand = max(stand, (max(near) - min(near)) * 1.35)
            else:
                amid = edge.length * 0.5
        else:
            amid = edge.length * 0.5
            stand = max(stand, edge.length * 1.15)
        eye = Vector(wf.p(amid, stand, 1.7))
        tgt = Vector(wf.p(amid, -1.0, look_z))
        cam.location = eye
        cam.rotation_euler = (tgt - eye).to_track_quat("-Z", "Y").to_euler()
        cam_data.lens = lens
        path = out / f"{kind}_street_after.jpg"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print("Wrote", path)


if __name__ == "__main__":
    main()
