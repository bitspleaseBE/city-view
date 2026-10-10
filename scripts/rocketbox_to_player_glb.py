"""Build player character GLBs from Rocketbox avatars + walk clips.

Produces ``viewer/characters/players/{id}_Walking.glb`` (mesh + walk) and
``{id}_Riding.glb`` / ``{id}_Scooter.glb`` for Pieter, Mo and Jacob.

Pieter / Mo are baked from Rocketbox avatar FBXs (same import + world-space walk
bake as ``build_rocketbox_characters.py`` — ``automatic_bone_orientation`` bends
the head backward). Jacob is the Hasidic_Father pedestrian mesh (coat, hat, beard).

Usage:
  blender --background --python scripts/rocketbox_to_player_glb.py
  blender --background --python scripts/rocketbox_to_player_glb.py -- mo jacob
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
AVATAR_DIR = ROOT / "assets" / "rocketbox" / "avatars"
ANIM_DIR = ROOT / "assets" / "rocketbox" / "animations"
PEOPLE_DIR = ROOT / "viewer" / "characters" / "people"
OUT_DIR = ROOT / "viewer" / "characters" / "players"

# Street meshes: Rocketbox males chosen to match menu portraits (hair + clothes),
# then recolored via scripts/style_player_textures.py. Never used as pedestrians.
PLAYERS = (
    # id, avatar folder, fbx name, walk anim
    ("pieter", "Male_Adult_07", "Male_Adult_07.fbx", "m_walk_neutral_01.max.fbx"),
    ("mo", "Male_Adult_04", "Male_Adult_04.fbx", "m_walk_stroll_01.max.fbx"),
)
# Pedestrian already built with coat/hat/beard (scripts/build_rocketbox_characters.py).
JACOB_PEOPLE_ID = "Hasidic_Father"
STYLED_DIR = OUT_DIR / "_styled"

BODY_BONE = (
    "Pelvis", "Spine", "Neck", "Head", "Clavicle", "UpperArm", "Forearm", "Hand", "Finger",
    "Thigh", "Calf", "Foot", "Toe",
)


def _is_body_bone(name: str) -> bool:
    leaf = name.removeprefix("Bip01 ").removeprefix("L ").removeprefix("R ")
    return leaf.startswith(BODY_BONE)


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _shrink_textures(max_side: int = 512) -> None:
    for img in bpy.data.images:
        if not img.size[0]:
            continue
        w, h = img.size[0], img.size[1]
        if w > max_side or h > max_side:
            scale = max_side / max(w, h)
            try:
                img.scale(max(1, int(w * scale)), max(1, int(h * scale)))
            except Exception:
                pass


def _armature() -> bpy.types.Object:
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError("no armature")
    return arms[0]


def _import_fbx(path: Path, *, anim: bool) -> set[str]:
    """Match ``build_rocketbox_characters.import_fbx`` — do not remapping bone axes.

    ``automatic_bone_orientation=True`` (old player bake) left Head/Neck aiming at the
    sky after the world-space walk retarget.
    """
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.fbx(
        filepath=str(path),
        use_anim=anim,
        ignore_leaf_bones=False,
    )
    return {o.name for o in bpy.data.objects} - before


def _export_glb(path: Path, *, animations: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        filepath=str(path),
        export_format="GLB",
        export_animations=animations,
        export_skins=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_image_format="JPEG",
        export_jpeg_quality=72,
        export_apply=False,
    )
    # ACTIONS without re-sampling — we already keyed quaternions per frame.
    # force_sampling + mixed rotation modes previously collapsed clips to 2 keys.
    try:
        bpy.ops.export_scene.gltf(
            **kwargs,
            export_animation_mode="ACTIONS",
            export_force_sampling=False,
            export_anim_single_armature=True,
        )
    except TypeError:
        bpy.ops.export_scene.gltf(**kwargs)
    print(f"OK {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def _bone(arm: bpy.types.Object, *names: str) -> str | None:
    for n in names:
        if arm.pose.bones.get(n):
            return n
    return None


def _ensure_xyz(arm: bpy.types.Object, bone: str | None) -> None:
    if not bone:
        return
    pb = arm.pose.bones.get(bone)
    if pb:
        pb.rotation_mode = "XYZ"


def _set_quat_from_xyz(
    arm: bpy.types.Object, bone: str | None, eul: tuple[float, float, float]
) -> None:
    """Set a bone's quaternion from XYZ euler without flipping rotation_mode mid-clip.

    Switching XYZ↔QUATERNION while keyframing makes the glTF exporter emit
    \"Multiple rotation mode\" and collapse the clip to two identical keys.
    """
    if not bone:
        return
    from mathutils import Euler

    pb = arm.pose.bones[bone]
    pb.rotation_mode = "QUATERNION"
    pb.rotation_quaternion = Euler(eul, "XYZ").to_quaternion()


def bake_ride_pose(arm: bpy.types.Object, kind: str) -> bpy.types.Action:
    """Bike pedal loop or scooter stance on a Rocketbox (Bip01) skeleton.

    Pose bones are set in Euler each frame then visually baked to quaternions.
    Writing euler fcurves alone does not survive glTF export (clips looked identical
    and never pedalled). Rocketbox axes (probed on Male_Adult_04): Thigh/Calf +Z
    flex the leg; Spine +Z leans forward.
    """
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data_clear()
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)

    spine = _bone(arm, "Bip01 Spine", "Bip01_Spine")
    spine1 = _bone(arm, "Bip01 Spine1", "Bip01_Spine1")
    l_thigh = _bone(arm, "Bip01 L Thigh", "Bip01_L_Thigh")
    r_thigh = _bone(arm, "Bip01 R Thigh", "Bip01_R_Thigh")
    l_calf = _bone(arm, "Bip01 L Calf", "Bip01_L_Calf")
    r_calf = _bone(arm, "Bip01 R Calf", "Bip01_R_Calf")
    l_foot = _bone(arm, "Bip01 L Foot", "Bip01_L_Foot")
    r_foot = _bone(arm, "Bip01 R Foot", "Bip01_R_Foot")
    l_arm = _bone(arm, "Bip01 L UpperArm", "Bip01_L_UpperArm")
    r_arm = _bone(arm, "Bip01 R UpperArm", "Bip01_R_UpperArm")
    l_fore = _bone(arm, "Bip01 L Forearm", "Bip01_L_Forearm")
    r_fore = _bone(arm, "Bip01 R Forearm", "Bip01_R_Forearm")

    driven = [
        b
        for b in (
            spine, spine1, l_thigh, r_thigh, l_calf, r_calf, l_foot, r_foot,
            l_arm, r_arm, l_fore, r_fore,
        )
        if b
    ]
    for b in driven:
        pb = arm.pose.bones[b]
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)

    # Scooter: short loop (mostly static). Riding: full pedal revolution.
    n = 32 if kind == "Riding" else 16
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = n
    scene.render.fps = 30

    act = bpy.data.actions.new(name=kind)
    slot = act.slots.new(id_type="OBJECT", name=arm.name)
    layer = act.layers.new("Base")
    strip = layer.strips.new(type="KEYFRAME")
    strip.channelbags.new(slot)
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = act
    arm.animation_data.action_slot = slot

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")

    for f in range(1, n + 1):
        t = ((f - 1) / n) * math.tau
        scene.frame_set(f)
        if kind == "Riding":
            # Opposite cranks: +1 = foot high, −1 = foot low.
            left = math.cos(t)
            right = math.cos(t + math.pi)
            _set_quat_from_xyz(arm, spine, (0.05, 0.0, 0.28))
            _set_quat_from_xyz(arm, spine1, (0.0, 0.0, 0.18))
            _set_quat_from_xyz(arm, l_thigh, (0.12, 0.0, 0.62 + 0.38 * left))
            _set_quat_from_xyz(arm, r_thigh, (-0.12, 0.0, 0.62 + 0.38 * right))
            _set_quat_from_xyz(arm, l_calf, (0.0, 0.0, 0.75 - 0.45 * left))
            _set_quat_from_xyz(arm, r_calf, (0.0, 0.0, 0.75 - 0.45 * right))
            _set_quat_from_xyz(arm, l_foot, (0.0, 0.0, -0.15 + 0.1 * left))
            _set_quat_from_xyz(arm, r_foot, (0.0, 0.0, -0.15 + 0.1 * right))
            _set_quat_from_xyz(arm, l_arm, (0.35, 0.25, 0.85))
            _set_quat_from_xyz(arm, r_arm, (0.35, -0.25, -0.85))
            _set_quat_from_xyz(arm, l_fore, (0.0, 0.0, 0.55))
            _set_quat_from_xyz(arm, r_fore, (0.0, 0.0, -0.55))
        else:
            # Standing on the share-scooter deck (top ≈ 0.16 m). Rest soles sit at
            # ~0.12 m — a light crouch lifts both feet onto the board; rear foot a
            # little further back for the kick-ready stance.
            sway = 0.03 * math.sin(t)
            _set_quat_from_xyz(arm, spine, (0.0, 0.0, 0.12))
            _set_quat_from_xyz(arm, spine1, (0.0, 0.0, 0.06))
            _set_quat_from_xyz(arm, l_thigh, (0.06, 0.0, 0.28 + sway))
            _set_quat_from_xyz(arm, r_thigh, (-0.06, 0.0, 0.34 - sway))
            _set_quat_from_xyz(arm, l_calf, (0.0, 0.0, 0.42))
            _set_quat_from_xyz(arm, r_calf, (0.0, 0.0, 0.55))
            _set_quat_from_xyz(arm, l_foot, (0.0, 0.0, -0.12))
            _set_quat_from_xyz(arm, r_foot, (0.0, 0.0, -0.18))
            _set_quat_from_xyz(arm, l_arm, (0.4, 0.2, 1.05))
            _set_quat_from_xyz(arm, r_arm, (0.4, -0.2, -1.05))
            _set_quat_from_xyz(arm, l_fore, (0.0, 0.0, 0.45))
            _set_quat_from_xyz(arm, r_fore, (0.0, 0.0, -0.45))

        bpy.context.view_layer.update()
        for b in driven:
            arm.pose.bones[b].keyframe_insert(data_path="rotation_quaternion", frame=f)

    bpy.ops.object.mode_set(mode="OBJECT")

    baked = arm.animation_data.action if arm.animation_data else None
    if not baked:
        raise RuntimeError(f"{kind} bake produced no action")
    baked.name = kind
    baked.use_frame_range = True
    baked.use_cyclic = True
    baked.frame_start = 1
    baked.frame_end = n
    scene.frame_start = 1
    scene.frame_end = n

    cb = _channelbag(baked)
    nkeys = 0
    if cb is not None:
        for fc in list(cb.fcurves):
            if not (
                fc.data_path.startswith("pose.bones")
                and fc.data_path.endswith("rotation_quaternion")
            ):
                cb.fcurves.remove(fc)
                continue
            nkeys = max(nkeys, len(fc.keyframe_points))
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"

    print(f"  {kind}: frames 1-{n}, bones {len(driven)}, keys/curve {nkeys}")
    return baked


def _strip_extra_actions(keep: bpy.types.Action) -> None:
    for other in list(bpy.data.actions):
        if other != keep:
            bpy.data.actions.remove(other)


def _repair_leg_weights(mesh_obj: bpy.types.Object) -> int:
    """Rocketbox hipoly skins thighs mostly to Pelvis, so walk looks calf-only.

    Reassign mid-thigh mesh verts (mesh-local Z, hands excluded) to L/R Thigh.
    """
    if mesh_obj.type != "MESH" or not mesh_obj.vertex_groups:
        return 0
    needed = ("Bip01 L Thigh", "Bip01 R Thigh", "Bip01 L Calf", "Bip01 R Calf")
    if any(mesh_obj.vertex_groups.get(n) is None for n in needed):
        return 0

    zs = [v.co.z for v in mesh_obj.data.vertices]
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min
    if height < 1e-3:
        return 0
    # Feet~bottom, head~top. Thigh sits roughly 28–52% of mesh height.
    thigh_lo = z_min + height * 0.28
    thigh_hi = z_min + height * 0.52

    changed = 0
    for v in mesh_obj.data.vertices:
        z = v.co.z
        if z < thigh_lo or z > thigh_hi:
            continue
        wmap = {mesh_obj.vertex_groups[g.group].name: g.weight for g in v.groups}
        # Hands hang through this band in A-pose — leave them alone.
        if any(
            wmap.get(n, 0) > 0.35
            for n in wmap
            if any(s in n for s in ("Hand", "Finger", "Forearm", "UpperArm", "Head"))
        ):
            continue
        t = (z - thigh_lo) / (thigh_hi - thigh_lo)  # 0 near knee, 1 near hip
        strength = max(0.0, min(1.0, 1.0 - abs(t - 0.55) * 1.4))
        if strength < 0.2:
            continue
        side = "L" if v.co.x >= 0.0 else "R"
        target = f"Bip01 {side} Thigh"
        calf = f"Bip01 {side} Calf"
        want = 0.5 + 0.45 * strength
        cur = wmap.get(target, 0.0)
        if want <= cur + 0.02:
            continue
        for d in list(wmap):
            if d == target:
                continue
            if any(s in d for s in ("Pelvis", "Spine", "Calf")):
                mesh_obj.vertex_groups[d].add([v.index], 0.0, "REPLACE")
        mesh_obj.vertex_groups[target].add([v.index], want, "REPLACE")
        if t < 0.35:
            mesh_obj.vertex_groups[calf].add([v.index], max(0.0, 1.0 - want) * 0.65, "REPLACE")
        changed += 1
    return changed


def _tuck_arms_in_action(arm: bpy.types.Object, act: bpy.types.Action) -> None:
    """Pull UpperArm / Forearm closer to the torso for a natural walk rest."""
    from mathutils import Euler

    bones = {
        "Bip01 L UpperArm": Euler((0.55, 0.15, 0.35), "XYZ"),
        "Bip01 R UpperArm": Euler((0.55, -0.15, -0.35), "XYZ"),
        "Bip01 L Forearm": Euler((0.25, 0.0, 0.1), "XYZ"),
        "Bip01 R Forearm": Euler((0.25, 0.0, -0.1), "XYZ"),
    }
    # Blender 5 slotted actions: find channelbag.
    cb = None
    if hasattr(act, "layers") and act.layers:
        layer = act.layers[0]
        if layer.strips:
            strip = layer.strips[0]
            slot = None
            if arm.animation_data and getattr(arm.animation_data, "action_slot", None):
                slot = arm.animation_data.action_slot
            if slot is None and hasattr(act, "slots") and act.slots:
                slot = act.slots[0]
            if slot is not None:
                cb = strip.channelbag(slot, ensure=False)
    if cb is None:
        # Legacy / fallback: fcurves on action
        fcurves = getattr(act, "fcurves", None)
        if not fcurves:
            print("  warn: could not tuck arms (no channelbag/fcurves)")
            return
        for bone, delta in bones.items():
            path = f'pose.bones["{bone}"].rotation_euler'
            for axis, add in enumerate(delta):
                fc = act.fcurves.find(path, index=axis)
                if not fc:
                    continue
                for kp in fc.keyframe_points:
                    kp.co.y += float(add)
                fc.update()
        print("  tucked arms via action.fcurves")
        return

    for bone, delta in bones.items():
        path = f'pose.bones["{bone}"].rotation_euler'
        for axis, add in enumerate(delta):
            fc = cb.fcurves.find(path, index=axis)
            if not fc:
                # Quaternion tracks — skip euler tuck; runtime handles it.
                continue
            for kp in fc.keyframe_points:
                kp.co.y += float(add)
            fc.update()
    print("  tucked arms in walk action")


def _normalize_bip01_names(arm: bpy.types.Object) -> None:
    """Rocketbox children sometimes ship as Bip02 — rename like the people builder."""
    if not arm.data.bones:
        return
    prefix = arm.data.bones[0].name.split(" ")[0]
    if prefix == "Bip01":
        return
    for b in arm.data.bones:
        b.name = b.name.replace(prefix, "Bip01", 1)
    arm.name = "Bip01"


def _channelbag(action: bpy.types.Action):
    if hasattr(action, "layers") and action.layers and action.layers[0].strips:
        bags = getattr(action.layers[0].strips[0], "channelbags", None)
        if bags:
            return bags[0]
    return None


def _bake_walk_onto_body(body: bpy.types.Object, anim_arm: bpy.types.Object) -> bpy.types.Action:
    """Retarget walk like ``build_rocketbox_characters.bake_walk`` (body bones only)."""
    scene = bpy.context.scene
    src_act = anim_arm.animation_data.action
    fr = src_act.frame_range
    start, end = int(fr[0]), int(fr[1])
    scene.frame_start = start
    scene.frame_end = end

    for pb in body.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        if not _is_body_bone(pb.name) or pb.name not in anim_arm.pose.bones:
            continue
        cr = pb.constraints.new("COPY_ROTATION")
        cr.target = anim_arm
        cr.subtarget = pb.name

    # Keep hip bob from the clip's root Z; drop forward travel (viewer moves the root).
    action = bpy.data.actions.new("Walking")
    slot = action.slots.new(id_type="OBJECT", name=body.name)
    layer = action.layers.new("Base")
    strip = layer.strips.new(type="KEYFRAME")
    dst = strip.channelbags.new(slot)
    src_cb = _channelbag(src_act)
    if src_cb is not None:
        loc = {fc.array_index: fc for fc in src_cb.fcurves if fc.data_path == "location"}
        hip_ratio = 1.0
        if 2 in loc and loc[2].keyframe_points:
            peak = max(k.co[1] for k in loc[2].keyframe_points)
            if peak > 1e-6:
                hip_ratio = body.location.z / peak if abs(body.location.z) > 1e-6 else 1.0
        for fc in src_cb.fcurves:
            if fc.data_path == "rotation_euler" or (
                fc.data_path == "location" and fc.array_index == 2
            ):
                k = hip_ratio if fc.data_path == "location" else 1.0
                nf = dst.fcurves.new(fc.data_path, index=fc.array_index)
                for kp in fc.keyframe_points:
                    nf.keyframe_points.insert(kp.co[0], kp.co[1] * k)

    body.rotation_mode = anim_arm.rotation_mode
    if not body.animation_data:
        body.animation_data_create()
    body.animation_data.action = action
    body.animation_data.action_slot = slot

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(
        frame_start=start,
        frame_end=end,
        only_selected=False,
        visual_keying=True,
        clear_constraints=True,
        use_current_action=True,
        bake_types={"POSE"},
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    baked = body.animation_data.action if body.animation_data else None
    if not baked:
        raise RuntimeError("walk bake produced no action")
    baked.name = "Walking"
    baked.use_frame_range = True
    baked.use_cyclic = True
    baked.frame_start = start
    baked.frame_end = end

    # Drop non-quaternion / non-body pose curves (people builder does the same).
    cb = _channelbag(baked)
    if cb is not None:
        for fc in list(cb.fcurves):
            if not fc.data_path.startswith("pose.bones"):
                continue
            if not fc.data_path.endswith("rotation_quaternion"):
                cb.fcurves.remove(fc)
                continue
            bone = fc.data_path.split('"')[1]
            if not _is_body_bone(bone):
                cb.fcurves.remove(fc)

    print(f"  baked walk frames {start}-{end} onto {body.name}")
    return baked


def _apply_styled_textures(player_id: str) -> None:
    """Swap imported color maps for portrait-matched recolors."""
    tex_dir = STYLED_DIR / player_id
    if not tex_dir.is_dir():
        print(f"warn: no styled textures at {tex_dir}")
        return
    by_stem = {p.stem.lower(): p for p in tex_dir.glob("*.png")}
    for img in bpy.data.images:
        # FBX keeps original path on filepath even when image.name is "Map #0".
        src = (img.filepath_raw or img.filepath or img.name or "").replace("\\", "/")
        stem = Path(src).stem.lower()
        path = by_stem.get(stem)
        if not path:
            # Prefer color maps only for remap; normals already copied unstyled.
            for key, candidate in by_stem.items():
                if key in stem or stem in key:
                    path = candidate
                    break
        if not path:
            continue
        try:
            img.filepath = str(path)
            img.source = "FILE"
            img.reload()
            print(f"  texture {stem!r} → {path.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"warn: texture swap failed for {img.name}: {exc}")


def _drop_helpers(body: bpy.types.Object) -> bpy.types.Object:
    body_name = body.name
    for obj in list(bpy.data.objects):
        if obj.type == "EMPTY":
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
        if obj.type != "MESH":
            continue
        parented = obj.parent is not None and obj.parent.type == "ARMATURE"
        has_arm = any(m.type == "ARMATURE" for m in obj.modifiers)
        skinned = parented or has_arm or "hipoly" in obj.name.lower()
        if not skinned or obj.name.lower().startswith("ico") or "sphere" in obj.name.lower():
            print(f"  drop helper mesh {obj.name!r}")
            bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.data.objects.get(body_name) or _armature()


def build_walking(player_id: str, folder: str, fbx_name: str, walk_anim: str) -> Path:
    avatar = AVATAR_DIR / folder / fbx_name
    anim = ANIM_DIR / walk_anim
    if not avatar.exists():
        raise FileNotFoundError(avatar)
    if not anim.exists():
        raise FileNotFoundError(anim)

    _clear()
    _import_fbx(avatar, anim=False)
    body = _armature()
    _normalize_bip01_names(body)
    # Clear any bind-pose action the avatar FBX may have brought in.
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    if body.animation_data:
        body.animation_data_clear()

    before = {o.name for o in bpy.data.objects}
    _import_fbx(anim, anim=True)

    # Animation FBX brings a second armature that owns the walk action.
    anim_arm = None
    for obj in bpy.data.objects:
        if obj.name not in before and obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action:
            anim_arm = obj
            break
    if not anim_arm:
        raise RuntimeError(f"no animated armature in {walk_anim}")
    _normalize_bip01_names(anim_arm)

    walk_act = _bake_walk_onto_body(body, anim_arm)

    # Drop animation-only empties / armatures / helper meshes (incl. anim armature).
    for obj in list(bpy.data.objects):
        if obj.name in before:
            continue
        if obj.type in {"MESH", "ARMATURE", "EMPTY"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    body = _drop_helpers(body)

    # Thigh verts are weighted to Pelvis on stock Rocketbox — fix before export.
    for obj in bpy.data.objects:
        if obj.type == "MESH" and ("hipoly" in obj.name.lower() or obj.parent == body):
            n = _repair_leg_weights(obj)
            if n:
                print(f"  repaired thigh weights on {n} verts ({obj.name})")

    _tuck_arms_in_action(body, walk_act)

    for act in list(bpy.data.actions):
        if act != walk_act:
            bpy.data.actions.remove(act)

    # People pipeline leaves armature ~0.01 after glTF round-trip. Apply the same
    # so the viewer does not fight a cm-scale bind pose.
    if body.scale.x > 0.5:
        body.scale = (0.01, 0.01, 0.01)

    _apply_styled_textures(player_id)
    _shrink_textures(512)
    out = OUT_DIR / f"{player_id}_Walking.glb"
    _export_glb(out, animations=True)
    return out


def build_jacob_from_people() -> Path:
    """Use the Hasidic_Father pedestrian (coat, hat, beard) as Jacob's street mesh."""
    src = PEOPLE_DIR / f"{JACOB_PEOPLE_ID}.glb"
    if not src.exists():
        raise FileNotFoundError(
            f"{src} — build with: blender --background --python scripts/build_rocketbox_characters.py -- {JACOB_PEOPLE_ID}"
        )
    _clear()
    bpy.ops.import_scene.gltf(filepath=str(src))
    body = _armature()
    _normalize_bip01_names(body)
    body = _drop_helpers(body)

    # Prefer a single Walking action name for the player loader.
    act = body.animation_data.action if body.animation_data else None
    if act is None and bpy.data.actions:
        act = bpy.data.actions[0]
        if not body.animation_data:
            body.animation_data_create()
        body.animation_data.action = act
    if act:
        act.name = "Walking"
        act.use_cyclic = True
        for other in list(bpy.data.actions):
            if other != act:
                bpy.data.actions.remove(other)

    for obj in bpy.data.objects:
        if obj.type == "MESH":
            obj.name = "Jacob"

    _shrink_textures(512)
    out = OUT_DIR / "jacob_Walking.glb"
    _export_glb(out, animations=True)
    return out


def build_ride_clips(player_id: str) -> None:
    src = OUT_DIR / f"{player_id}_Walking.glb"
    _clear()
    bpy.ops.import_scene.gltf(filepath=str(src))
    arm = _armature()
    act = bake_ride_pose(arm, "Riding")
    _strip_extra_actions(act)
    _export_glb(OUT_DIR / f"{player_id}_Riding.glb", animations=True)

    _clear()
    bpy.ops.import_scene.gltf(filepath=str(src))
    arm = _armature()
    act = bake_ride_pose(arm, "Scooter")
    _strip_extra_actions(act)
    _export_glb(OUT_DIR / f"{player_id}_Scooter.glb", animations=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    rides_only = "rides" in {a.lower() for a in argv}
    want = {a.lower() for a in argv if a.lower() != "rides"} or None

    import subprocess

    style = ROOT / "scripts" / "style_player_textures.py"
    py = sys.executable
    venv_py = ROOT / ".venv-img" / "bin" / "python"
    if venv_py.exists():
        py = str(venv_py)

    ids = [p[0] for p in PLAYERS] + ["jacob"]
    if want is not None:
        ids = [i for i in ids if i in want]

    if rides_only:
        for player_id in ids:
            try:
                print(f"== {player_id} rides ==")
                build_ride_clips(player_id)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {player_id}: {exc}")
                import traceback

                traceback.print_exc()
                return 1
        return 0

    if want is None or want & {"pieter", "mo"}:
        print("styling textures…")
        subprocess.check_call([py, str(style)])

    for player_id, folder, fbx_name, walk_anim in PLAYERS:
        if want is not None and player_id not in want:
            continue
        try:
            print(f"== {player_id} ==")
            build_walking(player_id, folder, fbx_name, walk_anim)
            build_ride_clips(player_id)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {player_id}: {exc}")
            import traceback

            traceback.print_exc()
            return 1

    if want is None or "jacob" in want:
        try:
            print("== jacob ==")
            build_jacob_from_people()
            build_ride_clips("jacob")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL jacob: {exc}")
            import traceback

            traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
