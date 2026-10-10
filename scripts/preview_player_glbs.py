"""Render quick front stills of player Walking GLBs for visual QA."""
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
PLAYERS = ROOT / "viewer" / "characters" / "players"
OUT = PLAYERS / "_preview"
OUT.mkdir(parents=True, exist_ok=True)


def render_one(glb: Path, dest: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    bip = bpy.data.objects.get("Bip01")
    if bip and bip.scale.x < 0.001:
        bip.scale = (0.01, 0.01, 0.01)
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and (
            obj.name.lower().startswith("ico") or "sphere" in obj.name.lower()
        ):
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()

    # Bake evaluated skinned meshes into plain objects so Workbench sees metre scale.
    baked = []
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            continue
        eo = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(eo)
        if not me.vertices:
            bpy.data.meshes.remove(me)
            continue
        # Bake includes bind-pose cm units; fold in the armature world matrix (0.01 scale).
        me.transform(eo.matrix_world)
        # Copy materials (force opaque)
        mats = []
        for slot in o.material_slots:
            mat = slot.material
            if mat:
                mat = mat.copy()
                mat.blend_method = "OPAQUE"
                if mat.use_nodes:
                    for n in mat.node_tree.nodes:
                        if n.type == "BSDF_PRINCIPLED" and "Alpha" in n.inputs:
                            n.inputs["Alpha"].default_value = 1.0
            mats.append(mat)
        bo = bpy.data.objects.new(o.name + "_bake", me)
        bpy.context.scene.collection.objects.link(bo)
        for mat in mats:
            bo.data.materials.append(mat)
        baked.append(bo)
        o.hide_render = True
        o.hide_viewport = True

    if not baked:
        print("FAIL no baked meshes", glb)
        return

    minv = Vector((1e9, 1e9, 1e9))
    maxv = Vector((-1e9, -1e9, -1e9))
    for o in baked:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            minv = Vector((min(minv.x, w.x), min(minv.y, w.y), min(minv.z, w.z)))
            maxv = Vector((max(maxv.x, w.x), max(maxv.y, w.y), max(maxv.z, w.z)))

    center = (minv + maxv) * 0.5
    height = max(maxv.z - minv.z, 0.5)
    size = max(height, (maxv - minv).length * 0.5, 1.0)

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = height * 1.15
    cam.location = (center.x, center.y - size * 2.2, center.z)
    cam.rotation_euler = (1.5708, 0.0, 0.0)  # look along +Y

    light_data = bpy.data.lights.new("sun", "SUN")
    light = bpy.data.objects.new("sun", light_data)
    bpy.context.scene.collection.objects.link(light)
    light.rotation_euler = (0.7, 0.2, 0.4)
    light_data.energy = 6.0

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.66, 0.72, 1.0)

    scene = bpy.context.scene
    scene.render.resolution_x = 480
    scene.render.resolution_y = 720
    scene.render.filepath = str(dest)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 92
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    bpy.ops.render.render(write_still=True)
    print(
        "wrote",
        dest,
        "height",
        round(height, 3),
        "baked",
        len(baked),
        "z",
        round(minv.z, 3),
        round(maxv.z, 3),
    )


# Jacob is Mixamo James (already hatted); still preview for QA.
for pid in ("pieter", "mo", "jacob"):
    render_one(PLAYERS / f"{pid}_Walking.glb", OUT / f"{pid}.jpg")
