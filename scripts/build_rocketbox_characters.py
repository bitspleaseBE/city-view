"""Bake Rocketbox avatars into walking pedestrian GLBs for the viewer.

  python3 scripts/fetch_rocketbox.py
  blender --background --python scripts/build_rocketbox_characters.py [-- Id1 Id2 ...]

Writes viewer/characters/people/<id>.glb plus manifest.json (heights, natural walk speed,
grouping tags). The walk clip's forward travel is removed so the viewer moves the root; the
vertical bob is kept and scaled to the avatar's own hip height (children).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from garment_tint import apply_tints  # noqa: E402
from rocketbox_props import add_extras  # noqa: E402
from rocketbox_roster import ROSTER  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "assets" / "rocketbox"
OUT = ROOT / "viewer" / "characters" / "people"
COLOR_RES = 1024
DETAIL_RES = 512  # normal + hair/eyelash cards
FPS = 30


def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FPS


def import_fbx(path: Path) -> set:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path), use_anim=True, ignore_leaf_bones=False)
    return set(bpy.data.objects) - before


def load_image(path: Path, res: int):
    img = bpy.data.images.load(str(path))
    if img.size[0] > res:
        img.scale(res, res)
    img.pack()
    return img


def pixels(img) -> np.ndarray:
    w, h = img.size
    buf = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)[::-1].copy()  # row 0 = image top


def set_pixels(img, arr: np.ndarray) -> None:
    img.pixels.foreach_set(np.ascontiguousarray(arr[::-1]).ravel())
    img.update()
    img.pack()


def build_material(mat, folder: Path, part: str, recolor) -> None:
    color = next(folder.glob(f"*_{part}_color*.tga"), None)
    normal = next(folder.glob(f"*_{part}_normal*.tga"), None)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = {"head": 0.55, "opacity": 0.6}.get(part, 0.78)
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    if color:
        img = load_image(color, DETAIL_RES if part == "opacity" else COLOR_RES)
        if recolor and part == "body":
            px = pixels(img)
            px[..., :3] = apply_tints(px[..., :3], recolor)
            set_pixels(img, px)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if part == "opacity":
            # Round = alpha clip at 0.5 in glTF (MASK): hair cards need no sorting.
            clip = nt.nodes.new("ShaderNodeMath")
            clip.operation = "ROUND"
            nt.links.new(tex.outputs["Alpha"], clip.inputs[0])
            nt.links.new(clip.outputs[0], bsdf.inputs["Alpha"])
    if normal and part != "opacity":
        img = load_image(normal, DETAIL_RES)
        img.colorspace_settings.name = "Non-Color"
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 0.8
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


def channelbag(action):
    return action.layers[0].strips[0].channelbags[0]


BODY_BONE = (
    "Pelvis", "Spine", "Neck", "Head", "Clavicle", "UpperArm", "Forearm", "Hand", "Finger",
    "Thigh", "Calf", "Foot", "Toe",
)


def is_body_bone(name: str) -> bool:
    leaf = name.removeprefix("Bip01 ").removeprefix("L ").removeprefix("R ")
    return leaf.startswith(BODY_BONE)


def bake_walk(arm, clip: str) -> float:
    """Retarget the walk onto `arm` in place; returns its natural speed in m/s.

    The clip's skeleton has its own rest pose, so bone rotations are matched in world space
    (all Rocketbox rigs share Biped bone axes) and baked, rather than copied channel by channel.
    Facial bones keep their rest pose.
    """
    objs = import_fbx(CACHE / "animations" / f"{clip}.max.fbx")
    src = next(o for o in objs if o.type == "ARMATURE")
    src_action = src.animation_data.action
    f0, f1 = (int(f) for f in src_action.frame_range)

    # Root node: drop the forward travel, scale the hip bob to this avatar's hip height.
    cb = channelbag(src_action)
    loc = {fc.array_index: fc for fc in cb.fcurves if fc.data_path == "location"}
    ys = [k.co[1] for k in loc[1].keyframe_points]
    travel = abs(ys[-1] - ys[0])
    hip_ratio = arm.location.z / max(k.co[1] for k in loc[2].keyframe_points)
    action = bpy.data.actions.new("Walk")
    slot = action.slots.new(id_type="OBJECT", name=arm.name)
    layer = action.layers.new("Base")
    strip = layer.strips.new(type="KEYFRAME")
    dst = strip.channelbags.new(slot)
    for fc in cb.fcurves:
        if fc.data_path == "rotation_euler" or (fc.data_path == "location" and fc.array_index == 2):
            k = hip_ratio if fc.data_path == "location" else 1.0
            nf = dst.fcurves.new(fc.data_path, index=fc.array_index)
            for kp in fc.keyframe_points:
                nf.keyframe_points.insert(kp.co[0], kp.co[1] * k)
    arm.rotation_mode = src.rotation_mode
    arm.animation_data_create()
    arm.animation_data.action = action
    arm.animation_data.action_slot = slot

    for pb in arm.pose.bones:
        if is_body_bone(pb.name) and pb.name in src.pose.bones:
            c = pb.constraints.new("COPY_ROTATION")
            c.target = src
            c.subtarget = pb.name
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = f0, f1
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(
        frame_start=f0,
        frame_end=f1,
        only_selected=False,
        visual_keying=True,
        clear_constraints=True,
        use_current_action=True,
        bake_types={"POSE"},
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        if a != action:
            bpy.data.actions.remove(a)
    for fc in list(channelbag(action).fcurves):
        if fc.data_path.startswith("pose.bones") and not fc.data_path.endswith("rotation_quaternion"):
            channelbag(action).fcurves.remove(fc)
        elif fc.data_path.startswith("pose.bones") and not is_body_bone(fc.data_path.split('"')[1]):
            channelbag(action).fcurves.remove(fc)
    return travel * hip_ratio / ((f1 - f0) / FPS)


def build(entry: dict) -> dict:
    reset()
    folder = CACHE / "avatars" / entry["src"]
    objs = import_fbx(folder / f"{entry['src']}.fbx")
    arm = next(o for o in objs if o.type == "ARMATURE")
    mesh = next(o for o in objs if o.type == "MESH")
    for o in objs:
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    if arm.animation_data:
        arm.animation_data_clear()
    prefix = arm.data.bones[0].name.split(" ")[0]
    for b in arm.data.bones:  # children are rigged as Bip02
        b.name = b.name.replace(prefix, "Bip01", 1)
    arm.name = "Bip01"
    mesh.name = entry["id"]

    for mat in mesh.data.materials:
        part = mat.name.rsplit("_", 1)[-1].lower()
        build_material(mat, folder, part, entry.get("recolor"))

    bpy.context.view_layer.update()
    zs = [(mesh.matrix_world @ v.co).z for v in mesh.data.vertices]
    height = max(zs) - min(zs)
    add_extras(entry, arm, mesh)

    speed = bake_walk(arm, entry["walk"])
    OUT.mkdir(parents=True, exist_ok=True)
    glb = OUT / f"{entry['id']}.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        export_image_format="WEBP",
        export_image_quality=82,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_frame_step=1,
        export_skins=True,
        export_morph=False,
        export_apply=False,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
    )
    print(f"OK {entry['id']}: {height:.2f} m, walk {speed:.2f} m/s, {glb.stat().st_size // 1024} KB")
    return {
        "id": entry["id"],
        "file": glb.name,
        "age": entry["age"],
        "sex": entry["sex"],
        "look": entry["look"],
        "height": round(height, 3),
        "walkSpeed": round(speed, 3),
    }


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    entries = [e for e in ROSTER if not argv or e["id"] in argv]
    manifest_path = OUT / "manifest.json"
    manifest = {}
    if argv and manifest_path.exists():
        manifest = {m["id"]: m for m in json.loads(manifest_path.read_text())["people"]}
    for e in entries:
        manifest[e["id"]] = build(e)
    order = [e["id"] for e in ROSTER if e["id"] in manifest]
    manifest_path.write_text(
        json.dumps(
            {
                "source": "Microsoft Rocketbox avatars (MIT), built by scripts/build_rocketbox_characters.py",
                "people": [manifest[i] for i in order],
            },
            indent=1,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
