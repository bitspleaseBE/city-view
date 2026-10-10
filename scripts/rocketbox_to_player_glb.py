"""Build player character GLBs from Rocketbox avatars + walk clips.

Produces ``viewer/characters/players/{id}_Walking.glb`` (mesh + walk) and
animation-only ``{id}_Riding.glb`` / ``{id}_Scooter.glb`` for Pieter and Mo'.
Jacob is the Mixamo James pedestrian (copied into players/) — not Rocketbox.

Usage:
  blender --background --python scripts/rocketbox_to_player_glb.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
AVATAR_DIR = ROOT / "assets" / "rocketbox" / "avatars"
ANIM_DIR = ROOT / "assets" / "rocketbox" / "animations"
OUT_DIR = ROOT / "viewer" / "characters" / "players"

# Street meshes: Rocketbox males chosen to match menu portraits (hair + clothes),
# then recolored via scripts/style_player_textures.py. Never used as pedestrians.
PLAYERS = (
    # id, avatar folder, fbx name, walk anim
    ("pieter", "Male_Adult_07", "Male_Adult_07.fbx", "m_walk_neutral_01.max.fbx"),
    ("mo", "Male_Adult_04", "Male_Adult_04.fbx", "m_walk_stroll_01.max.fbx"),
)
STYLED_DIR = OUT_DIR / "_styled"


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


def _import_fbx(path: Path, *, anim: bool) -> None:
    bpy.ops.import_scene.fbx(
        filepath=str(path),
        automatic_bone_orientation=True,
        use_anim=anim,
        ignore_leaf_bones=True,
        global_scale=0.01,
    )


def _export_glb(path: Path, *, animations: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
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
    print(f"OK {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def _setup_action(arm: bpy.types.Object, name: str):
    act = bpy.data.actions.new(name=name)
    layer = act.layers.new("layer0")
    strip = layer.strips.new(type="KEYFRAME")
    slot = act.slots.new(id_type="OBJECT", name=arm.name)
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = act
    arm.animation_data.action_slot = slot
    cb = strip.channelbag(slot, ensure=True)
    act.use_frame_range = True
    act.use_cyclic = True
    return act, cb


def _bone(arm: bpy.types.Object, *names: str) -> str | None:
    for n in names:
        if arm.pose.bones.get(n):
            return n
    return None


def _set_rot(cb, bone: str, frames: list[tuple[int, tuple[float, float, float]]]) -> None:
    path = f'pose.bones["{bone}"].rotation_euler'
    for i in (0, 1, 2):
        existing = cb.fcurves.find(path, index=i)
        if existing:
            cb.fcurves.remove(existing)
    for axis in (0, 1, 2):
        fc = cb.fcurves.new(path, index=axis)
        fc.keyframe_points.add(len(frames))
        for ki, (frame, eul) in enumerate(frames):
            kp = fc.keyframe_points[ki]
            kp.co = (float(frame), float(eul[axis]))
            kp.interpolation = "LINEAR"
        fc.update()


def _ensure_xyz(arm: bpy.types.Object, bone: str) -> None:
    pb = arm.pose.bones.get(bone)
    if pb:
        pb.rotation_mode = "XYZ"


def bake_ride_pose(arm: bpy.types.Object, kind: str) -> bpy.types.Action:
    """Simple seated / standing ride poses on a Rocketbox (Bip01) skeleton."""
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data_clear()
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)

    act, cb = _setup_action(arm, kind)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")

    # Common Rocketbox names
    spine = _bone(arm, "Bip01 Spine", "Bip01_Spine", "Spine")
    spine1 = _bone(arm, "Bip01 Spine1", "Bip01_Spine1", "Spine1")
    l_thigh = _bone(arm, "Bip01 L Thigh", "Bip01_L_Thigh", "LeftUpLeg")
    r_thigh = _bone(arm, "Bip01 R Thigh", "Bip01_R_Thigh", "RightUpLeg")
    l_calf = _bone(arm, "Bip01 L Calf", "Bip01_L_Calf", "LeftLeg")
    r_calf = _bone(arm, "Bip01 R Calf", "Bip01_R_Calf", "RightLeg")
    l_arm = _bone(arm, "Bip01 L UpperArm", "Bip01_L_UpperArm", "LeftArm")
    r_arm = _bone(arm, "Bip01 R UpperArm", "Bip01_R_UpperArm", "RightArm")
    l_fore = _bone(arm, "Bip01 L Forearm", "Bip01_L_Forearm", "LeftForeArm")
    r_fore = _bone(arm, "Bip01 R Forearm", "Bip01_R_Forearm", "RightForeArm")

    bones = [b for b in (spine, spine1, l_thigh, r_thigh, l_calf, r_calf, l_arm, r_arm, l_fore, r_fore) if b]
    for b in bones:
        _ensure_xyz(arm, b)

    n = 24 if kind == "Riding" else 28
    series: dict[str, list[tuple[int, tuple[float, float, float]]]] = {b: [] for b in bones}

    for f in range(n + 1):
        t = (f / n) * math.tau
        frame = f + 1
        if kind == "Riding":
            left = math.cos(t)
            right = math.cos(t + math.pi)
            if spine:
                series[spine].append((frame, (0.25, 0.0, 0.0)))
            if spine1:
                series[spine1].append((frame, (0.15, 0.0, 0.0)))
            if l_thigh:
                series[l_thigh].append((frame, (0.5 + 0.4 * left, 0.0, 0.1)))
            if r_thigh:
                series[r_thigh].append((frame, (0.5 + 0.4 * right, 0.0, -0.1)))
            if l_calf:
                series[l_calf].append((frame, (0.8 - 0.5 * left, 0.0, 0.0)))
            if r_calf:
                series[r_calf].append((frame, (0.8 - 0.5 * right, 0.0, 0.0)))
            if l_arm:
                series[l_arm].append((frame, (0.9, 0.2, 0.4)))
            if r_arm:
                series[r_arm].append((frame, (0.9, -0.2, -0.4)))
            if l_fore:
                series[l_fore].append((frame, (0.3, 0.0, 0.0)))
            if r_fore:
                series[r_fore].append((frame, (0.3, 0.0, 0.0)))
        else:
            push = max(0.0, math.sin(t))
            if spine:
                series[spine].append((frame, (0.1, 0.0, 0.0)))
            if l_thigh:
                series[l_thigh].append((frame, (0.1, 0.0, 0.1)))
            if r_thigh:
                series[r_thigh].append((frame, (0.3 + 0.5 * push, 0.0, -0.1)))
            if r_calf:
                series[r_calf].append((frame, (0.4 + 0.6 * push, 0.0, 0.0)))
            if l_arm:
                series[l_arm].append((frame, (1.1, 0.2, 0.3)))
            if r_arm:
                series[r_arm].append((frame, (1.1, -0.2, -0.3)))

    for bone, frames in series.items():
        if frames:
            _set_rot(cb, bone, frames)

    act.frame_start = 1
    act.frame_end = n
    bpy.ops.object.mode_set(mode="OBJECT")
    return act


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


def _bake_walk_onto_body(body: bpy.types.Object, anim_arm: bpy.types.Object) -> bpy.types.Action:
    """Copy world-space pose from the anim armature onto the avatar, then bake."""
    scene = bpy.context.scene
    src_act = anim_arm.animation_data.action
    fr = src_act.frame_range
    start, end = int(fr[0]), int(fr[1])
    scene.frame_start = start
    scene.frame_end = end

    # World-space copy so differing bone rolls still transfer limb aim.
    for pb in body.pose.bones:
        if pb.name not in anim_arm.pose.bones:
            continue
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        cr = pb.constraints.new("COPY_ROTATION")
        cr.target = anim_arm
        cr.subtarget = pb.name
        cr.target_space = "WORLD"
        cr.owner_space = "WORLD"
        if pb.name in {"Bip01", "Bip01 Pelvis"} or pb.parent is None:
            cl = pb.constraints.new("COPY_LOCATION")
            cl.target = anim_arm
            cl.subtarget = pb.name
            cl.target_space = "WORLD"
            cl.owner_space = "WORLD"

    bpy.context.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(
        frame_start=start,
        frame_end=end,
        step=1,
        only_selected=True,
        visual_keying=True,
        clear_constraints=True,
        clear_parents=False,
        use_current_action=False,
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
    before = {o.name for o in bpy.data.objects}
    _import_fbx(anim, anim=True)

    # Animation FBX brings a second armature (Bip01.001) that owns the walk action.
    anim_arm = None
    for obj in bpy.data.objects:
        if obj.name not in before and obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action:
            anim_arm = obj
            break
    if not anim_arm:
        raise RuntimeError(f"no animated armature in {walk_anim}")

    # World-space bake so avatar bone rolls match the walk clip's limb aim.
    walk_act = _bake_walk_onto_body(body, anim_arm)

    # Drop animation-only empties / armatures / helper meshes (incl. anim armature).
    for obj in list(bpy.data.objects):
        if obj.name in before:
            continue
        if obj.type in {"MESH", "ARMATURE", "EMPTY"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    # Rocketbox FBX also ships a stray Icosphere (and similar) that is not skinned —
    # it blows out bounds and blanks Blender/Three previews.
    body_name = body.name
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        parented = obj.parent is not None and obj.parent.type == "ARMATURE"
        has_arm = any(m.type == "ARMATURE" for m in obj.modifiers)
        skinned = parented or has_arm or "hipoly" in obj.name.lower()
        if not skinned or obj.name.lower().startswith("ico"):
            print(f"  drop helper mesh {obj.name!r}")
            bpy.data.objects.remove(obj, do_unlink=True)
    if body.name != body_name:
        body = _armature()

    # Thigh verts are weighted to Pelvis on stock Rocketbox — fix before export.
    for obj in bpy.data.objects:
        if obj.type == "MESH" and "hipoly" in obj.name.lower():
            n = _repair_leg_weights(obj)
            print(f"  repaired thigh weights on {n} verts")

    _tuck_arms_in_action(body, walk_act)

    # Drop leftover helper actions that are not the walk.
    for act in list(bpy.data.actions):
        if act != walk_act:
            bpy.data.actions.remove(act)

    # Leave armature object scale as imported (often 0.0001). The viewer normalizes
    # Bip01 to 0.01 each frame; baking scale here breaks bone lengths vs walk clips.

    _apply_styled_textures(player_id)
    _shrink_textures(512)
    out = OUT_DIR / f"{player_id}_Walking.glb"
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
    # Portrait-matched recolors (Pillow) before Blender import remaps them.
    import subprocess
    import sys

    style = ROOT / "scripts" / "style_player_textures.py"
    py = sys.executable
    # Prefer project venv with pillow if present.
    venv_py = ROOT / ".venv-img" / "bin" / "python"
    if venv_py.exists():
        py = str(venv_py)
    print("styling textures…")
    subprocess.check_call([py, str(style)])

    for player_id, folder, fbx_name, walk_anim in PLAYERS:
        try:
            print(f"== {player_id} ==")
            build_walking(player_id, folder, fbx_name, walk_anim)
            build_ride_clips(player_id)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {player_id}: {exc}")
            import traceback

            traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
