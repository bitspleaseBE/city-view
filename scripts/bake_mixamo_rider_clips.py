"""Bake looping Mixamo-rig riding clips onto existing Walking character GLBs.

Produces ``viewer/characters/{Name}_Riding.glb`` (seated bike pedal) and
``{Name}_Scooter.glb`` (standing kick-scooter with push-step cycle)
from each ``{Name}_Walking.glb``.

Uses Blender 5 slotted Action API (channelbags). Re-run after replacing
Walking assets:

  blender --background --python scripts/bake_mixamo_rider_clips.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
CHAR_DIR = ROOT / "viewer" / "characters"
CHARS = ("Remy", "Amy", "James", "Michelle", "Aj")


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_glb(path: Path) -> bpy.types.Object:
    bpy.ops.import_scene.gltf(filepath=str(path))
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise RuntimeError(f"no armature in {path}")
    return arms[0]


def _strip_all_animation() -> None:
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data_clear()
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)


def _setup_action(arm: bpy.types.Object, name: str) -> tuple[bpy.types.Action, bpy.types.ActionChannelbag]:
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


def _mixamo_prefix(arm: bpy.types.Object) -> str:
    """Mixamo exports use mixamorig: or mixamorigN: depending on the character."""
    for pb in arm.pose.bones:
        if pb.name.endswith(":Hips") and "mixamorig" in pb.name:
            return pb.name[: -len("Hips")]
        if pb.name == "mixamorig:Hips":
            return "mixamorig:"
    raise RuntimeError(f"no Mixamo Hips bone on {arm.name}")


def _bn(prefix: str, short: str) -> str:
    return f"{prefix}{short}"


def _ensure_xyz(arm: bpy.types.Object, bone: str) -> bpy.types.PoseBone | None:
    pb = arm.pose.bones.get(bone)
    if not pb:
        return None
    pb.rotation_mode = "XYZ"
    return pb


def _set_rot_keys(
    cb: bpy.types.ActionChannelbag,
    bone: str,
    frames: list[tuple[int, tuple[float, float, float]]],
) -> None:
    path = f'pose.bones["{bone}"].rotation_euler'
    # Remove existing curves for this bone if re-baking mid-run
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


def _set_loc_keys(
    cb: bpy.types.ActionChannelbag,
    bone: str,
    frames: list[tuple[int, tuple[float, float, float]]],
) -> None:
    path = f'pose.bones["{bone}"].location'
    for i in (0, 1, 2):
        existing = cb.fcurves.find(path, index=i)
        if existing:
            cb.fcurves.remove(existing)
    for axis in (0, 1, 2):
        fc = cb.fcurves.new(path, index=axis)
        fc.keyframe_points.add(len(frames))
        for ki, (frame, loc) in enumerate(frames):
            kp = fc.keyframe_points[ki]
            kp.co = (float(frame), float(loc[axis]))
            kp.interpolation = "LINEAR"
        fc.update()


def bake_riding(arm: bpy.types.Object) -> bpy.types.Action:
    _strip_all_animation()
    act, cb = _setup_action(arm, "Riding")
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")

    p = _mixamo_prefix(arm)
    shorts = [
        "Hips",
        "Spine",
        "Spine1",
        "Spine2",
        "Neck",
        "Head",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "RightArm",
        "RightForeArm",
        "RightHand",
    ]
    bones = [_bn(p, s) for s in shorts]
    for b in bones:
        _ensure_xyz(arm, b)

    n = 24
    series: dict[str, list[tuple[int, tuple[float, float, float]]]] = {b: [] for b in bones}
    loc_hips: list[tuple[int, tuple[float, float, float]]] = []
    hips = _bn(p, "Hips")

    for f in range(n + 1):
        t = (f / n) * math.tau
        left = math.cos(t)
        right = math.cos(t + math.pi)
        frame = f + 1

        loc_hips.append((frame, (0.0, -0.02, -0.04)))
        series[_bn(p, "Hips")].append((frame, (0.18, 0.0, 0.0)))
        series[_bn(p, "Spine")].append((frame, (0.28, 0.0, 0.0)))
        series[_bn(p, "Spine1")].append((frame, (0.18, 0.0, 0.0)))
        series[_bn(p, "Spine2")].append((frame, (0.12, 0.0, 0.0)))
        series[_bn(p, "Neck")].append((frame, (-0.15, 0.0, 0.0)))
        series[_bn(p, "Head")].append((frame, (-0.08, 0.0, 0.0)))

        series[_bn(p, "LeftArm")].append((frame, (0.95, 0.15, 0.55)))
        series[_bn(p, "LeftForeArm")].append((frame, (0.35, 0.0, 0.0)))
        series[_bn(p, "LeftHand")].append((frame, (0.1, 0.0, 0.2)))
        series[_bn(p, "RightArm")].append((frame, (0.95, -0.15, -0.55)))
        series[_bn(p, "RightForeArm")].append((frame, (0.35, 0.0, 0.0)))
        series[_bn(p, "RightHand")].append((frame, (0.1, 0.0, -0.2)))

        series[_bn(p, "LeftUpLeg")].append((frame, (0.55 + 0.45 * left, 0.0, 0.08)))
        series[_bn(p, "LeftLeg")].append((frame, (0.9 - 0.55 * left, 0.0, 0.0)))
        series[_bn(p, "LeftFoot")].append((frame, (-0.25 + 0.15 * left, 0.0, 0.0)))
        series[_bn(p, "RightUpLeg")].append((frame, (0.55 + 0.45 * right, 0.0, -0.08)))
        series[_bn(p, "RightLeg")].append((frame, (0.9 - 0.55 * right, 0.0, 0.0)))
        series[_bn(p, "RightFoot")].append((frame, (-0.25 + 0.15 * right, 0.0, 0.0)))

    if arm.pose.bones.get(hips):
        _set_loc_keys(cb, hips, loc_hips)
    for bone, frames in series.items():
        if arm.pose.bones.get(bone):
            _set_rot_keys(cb, bone, frames)

    act.frame_start = 1
    act.frame_end = n
    bpy.ops.object.mode_set(mode="OBJECT")
    return act


def bake_scooter(arm: bpy.types.Object) -> bpy.types.Action:
    _strip_all_animation()
    act, cb = _setup_action(arm, "Scooter")
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")

    p = _mixamo_prefix(arm)
    shorts = [
        "Hips",
        "Spine",
        "Spine1",
        "Neck",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "LeftArm",
        "LeftForeArm",
        "RightArm",
        "RightForeArm",
    ]
    bones = [_bn(p, s) for s in shorts]
    for b in bones:
        _ensure_xyz(arm, b)

    n = 28
    series: dict[str, list[tuple[int, tuple[float, float, float]]]] = {b: [] for b in bones}
    loc_hips: list[tuple[int, tuple[float, float, float]]] = []
    hips = _bn(p, "Hips")

    for f in range(n + 1):
        t = (f / n) * math.tau
        push = max(0.0, math.sin(t))
        plant = 1.0 - 0.35 * push
        frame = f + 1

        loc_hips.append((frame, (0.0, 0.0, -0.01 * push)))
        series[_bn(p, "Hips")].append((frame, (0.08, 0.0, 0.04 * math.sin(t))))
        series[_bn(p, "Spine")].append((frame, (0.12, 0.0, 0.0)))
        series[_bn(p, "Spine1")].append((frame, (0.08, 0.0, 0.0)))
        series[_bn(p, "Neck")].append((frame, (-0.05, 0.0, 0.0)))

        series[_bn(p, "LeftArm")].append((frame, (1.15, 0.25, 0.35)))
        series[_bn(p, "LeftForeArm")].append((frame, (0.15, 0.0, 0.0)))
        series[_bn(p, "RightArm")].append((frame, (1.15, -0.25, -0.35)))
        series[_bn(p, "RightForeArm")].append((frame, (0.15, 0.0, 0.0)))

        series[_bn(p, "LeftUpLeg")].append((frame, (0.15 * plant, 0.0, 0.12)))
        series[_bn(p, "LeftLeg")].append((frame, (0.25 * plant, 0.0, 0.0)))
        series[_bn(p, "LeftFoot")].append((frame, (0.05, 0.0, 0.0)))
        series[_bn(p, "RightUpLeg")].append((frame, (0.35 + 0.55 * push, 0.0, -0.1)))
        series[_bn(p, "RightLeg")].append((frame, (0.4 + 0.7 * push, 0.0, 0.0)))
        series[_bn(p, "RightFoot")].append((frame, (-0.2 + 0.3 * push, 0.0, 0.0)))

    if arm.pose.bones.get(hips):
        _set_loc_keys(cb, hips, loc_hips)
    for bone, frames in series.items():
        if arm.pose.bones.get(bone):
            _set_rot_keys(cb, bone, frames)

    act.frame_start = 1
    act.frame_end = n
    bpy.ops.object.mode_set(mode="OBJECT")
    return act


def _export_glb(path: Path, act: bpy.types.Action) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only keep the clip we just baked.
    for other in list(bpy.data.actions):
        if other != act:
            bpy.data.actions.remove(other)
    ncurves = 0
    for layer in act.layers:
        for strip in layer.strips:
            for slot in act.slots:
                cb = strip.channelbag(slot, ensure=False)
                if cb:
                    ncurves += len(cb.fcurves)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        export_animations=True,
        export_skins=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_image_format="JPEG",
        export_jpeg_quality=70,
        export_apply=False,
    )
    print(f"OK {path.name} ({path.stat().st_size} bytes, {ncurves} fcurves)")


def process_character(name: str) -> None:
    src = CHAR_DIR / f"{name}_Walking.glb"
    if not src.exists():
        print(f"SKIP missing {src.name}")
        return

    _clear_scene()
    arm = _import_glb(src)
    act = bake_riding(arm)
    _export_glb(CHAR_DIR / f"{name}_Riding.glb", act)

    _clear_scene()
    arm = _import_glb(src)
    act = bake_scooter(arm)
    _export_glb(CHAR_DIR / f"{name}_Scooter.glb", act)


def main() -> int:
    for name in CHARS:
        try:
            process_character(name)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {exc}")
            import traceback

            traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
