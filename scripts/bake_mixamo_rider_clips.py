"""Bake Mixamo-rig clips onto existing Walking character GLBs.

Produces ``viewer/characters/{Name}_Riding.glb`` (seated bike pedal),
``{Name}_Scooter.glb`` (standing on an e-scooter deck) and ``{Name}_GetUp.glb``
(scrambling up off the paving after being knocked down) from each
``{Name}_Walking.glb``. Poses are solved with a small IK so ankles sit on the
pedals / deck and wrists on the grips of the procedural vehicles in
``viewer/micromobility.js``; keep the dimension constants below in sync.

Uses Blender 5 slotted Action API (channelbags). Re-run after replacing
Walking assets (optionally only some clips), then ``scripts/extract_anim_clips.py``:

  blender --background --python scripts/bake_mixamo_rider_clips.py [-- Riding Scooter GetUp]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

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


def _set_keys(
    cb: bpy.types.ActionChannelbag,
    path: str,
    frames: list[tuple[int, tuple[float, float, float]]],
    smooth: bool,
) -> None:
    # Remove existing curves for this channel if re-baking mid-run
    for i in (0, 1, 2):
        existing = cb.fcurves.find(path, index=i)
        if existing:
            cb.fcurves.remove(existing)
    for axis in (0, 1, 2):
        fc = cb.fcurves.new(path, index=axis)
        fc.keyframe_points.add(len(frames))
        for ki, (frame, vec) in enumerate(frames):
            kp = fc.keyframe_points[ki]
            kp.co = (float(frame), float(vec[axis]))
            if smooth:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
            else:
                kp.interpolation = "LINEAR"
        fc.update()


def _set_rot_keys(cb, bone: str, frames, smooth: bool = False) -> None:
    _set_keys(cb, f'pose.bones["{bone}"].rotation_euler', frames, smooth)


def _set_loc_keys(cb, bone: str, frames, smooth: bool = False) -> None:
    _set_keys(cb, f'pose.bones["{bone}"].location', frames, smooth)


RIDER_H = 1.70  # m; micromobility.js fits riders to ~1.70 m
# Hand on a grip: wrist behind and above the bar, index/pinky knuckles across its top.
WRIST_BEHIND, WRIST_ABOVE = 0.08, 0.03
KNUCKLE_ABOVE, KNUCKLE_SPREAD = 0.025, 0.035
FINGER_CURL, THUMB_CURL = 1.0, 0.5

# Mirrors RIDE + seatRider() in viewer/micromobility.js (m, relative to the saddle).
BB_FWD, BB_DOWN, CRANK = 0.2, 0.54, 0.16
BAR_FWD, BAR_UP, GRIP_HALF = 0.46, 0.08, 0.3
HIPS_ABOVE_SADDLE = 0.07
ANKLE_ABOVE_PEDAL = 0.08

# Mirrors makeScooter() / makeShareScooter() (m, relative to the rider's soles and origin).
SC_GRIP_UP, SC_GRIP_FWD, SC_GRIP_HALF = 0.99, 0.34, 0.22
SC_FRONT_FOOT, SC_REAR_FOOT, SC_FOOT_SIDE = 0.12, -0.16, 0.07
SC_HIPS_DROP = 0.05

# Joint limits as (bone, euler axis, lo, hi). On the Mixamo rig: UpLeg +X swings the thigh
# forward, Leg −X bends the knee, Arm +X lowers / ±Z swings the arm forward, ForeArm ±Z flexes.
LEG = {
    "Left": [("LeftUpLeg", 0, -0.6, 2.2), ("LeftUpLeg", 2, -0.3, 0.3), ("LeftLeg", 0, -2.6, 0.0)],
    "Right": [("RightUpLeg", 0, -0.6, 2.2), ("RightUpLeg", 2, -0.3, 0.3), ("RightLeg", 0, -2.6, 0.0)],
}
ARM = {
    "Left": [("LeftArm", 0, -0.3, 1.6), ("LeftArm", 2, -0.2, 1.7), ("LeftForeArm", 2, 0.0, 2.3)],
    "Right": [("RightArm", 0, -0.3, 1.6), ("RightArm", 2, -1.7, 0.2), ("RightForeArm", 2, -2.3, 0.0)],
}
# Wrist and forearm twist that lay the palm on the bar.
HAND = {
    s: [(f"{s}ForeArm", 1, -1.6, 1.6), (f"{s}Hand", 0, -1.2, 1.2), (f"{s}Hand", 1, -1.0, 1.0), (f"{s}Hand", 2, -1.2, 1.2)]
    for s in ("Left", "Right")
}
# Fingers curl towards the palm with +X on both hands.
FINGERS = {
    s: [f"{s}Hand{f}{i}" for f in ("Index", "Middle", "Ring", "Pinky") for i in (1, 2, 3)]
    for s in ("Left", "Right")
}
THUMB = {s: [f"{s}HandThumb{i}" for i in (1, 2, 3)] for s in ("Left", "Right")}


class Rig:
    """Rest-pose frame of a Mixamo armature plus a small coordinate-descent IK solver."""

    def __init__(self, arm: bpy.types.Object) -> None:
        self.arm = arm
        self.pb = arm.pose.bones
        self.p = _mixamo_prefix(arm)
        self.mw = arm.matrix_world
        for b in self.pb:
            b.rotation_mode = "XYZ"
            b.rotation_euler = (0.0, 0.0, 0.0)
            b.location = (0.0, 0.0, 0.0)
        self.update()
        fwd = self.head("LeftToeBase") - self.head("LeftFoot")
        fwd.z = 0.0
        self.fwd = fwd.normalized()
        self.side = self.fwd.cross(Vector((0.0, 0.0, 1.0)))  # +side = the character's right
        zs = [
            (o.matrix_world @ Vector(c)).z
            for o in bpy.data.objects
            if o.type == "MESH" and any(md.type == "ARMATURE" for md in o.modifiers)
            for c in o.bound_box
        ]
        self.sole = min(zs)
        self.m = (max(zs) - self.sole) / RIDER_H  # world units per metre
        self.origin = Vector((self.mw.translation.x, self.mw.translation.y, 0.0))
        self.hips_z = self.head("Hips").z
        self.rest_foot = {s: self.head(f"{s}Foot") for s in ("Left", "Right")}
        self.worst: dict[str, float] = {}

    def update(self) -> None:
        bpy.context.view_layer.update()

    def bone(self, short: str) -> bpy.types.PoseBone:
        return self.pb[self.p + short]

    def head(self, short: str) -> Vector:
        return self.mw @ self.bone(short).head

    def point(self, fwd: float, side: float, z: float) -> Vector:
        """World point `fwd`/`side` metres from the rider origin at world height `z`."""
        v = self.origin + self.fwd * (fwd * self.m) + self.side * (side * self.m)
        v.z = z
        return v

    def side_of(self, short: str) -> float:
        return (self.rest_foot[short] - self.origin).dot(self.side) / self.m

    def set_rot(self, short: str, euler: tuple[float, float, float]) -> None:
        if self.p + short in self.pb:
            self.bone(short).rotation_euler = euler

    def place_hips(self, fwd: float, up: float, pitch: float, roll: float = 0.0) -> None:
        """Hips joint `fwd` m ahead of the origin and `up` m above the floor, the pelvis pitched
        forward by `pitch` (π/2 = lying face down, head ahead) and rolled `roll` (+ = right side down)."""
        hips = self.bone("Hips")
        rest = self.mw @ hips.bone.matrix_local
        rot = Matrix.Rotation(-pitch, 4, self.side) @ Matrix.Rotation(roll, 4, self.fwd)
        target = self.point(fwd, 0.0, self.sole + up * self.m)
        world = Matrix.Translation(target) @ rot @ Matrix.Translation(-rest.translation) @ rest
        hips.matrix = self.mw.inverted() @ world
        self.update()

    def drop_hips(self, metres: float) -> None:
        hips = self.bone("Hips")
        basis = (self.mw.to_3x3() @ hips.bone.matrix_local.to_3x3()).inverted()
        hips.location = basis @ Vector((0.0, 0.0, -metres * self.m))

    def solve(self, effector: str, target: Vector, chain) -> float:
        return self.solve_many([(effector, target)], chain)

    def solve_many(self, goals: list[tuple[str, Vector]], chain) -> float:
        """Move each goal bone's head onto its target; returns the worst residual in metres."""

        def err() -> float:
            self.update()
            return sum((self.head(b) - t).length for b, t in goals)

        e = err()
        step = 0.25
        while step > 0.002:
            better = False
            for short, ax, lo, hi in chain:
                pb = self.bone(short)
                for s in (step, -step):
                    old = pb.rotation_euler[ax]
                    new = min(hi, max(lo, old + s))
                    if abs(new - old) < 1e-9:
                        continue
                    pb.rotation_euler[ax] = new
                    e2 = err()
                    if e2 < e:
                        e = e2
                        better = True
                        break
                    pb.rotation_euler[ax] = old
            if not better:
                step *= 0.5
        self.update()
        worst = 0.0
        for b, t in goals:
            r = (self.head(b) - t).length / self.m
            self.worst[b] = max(self.worst.get(b, 0.0), r)
            worst = max(worst, r)
        return worst

    def grip(self, s: str, fwd: float, side: float, z: float) -> None:
        """Hand `s` ("Left"/"Right") holding a bar at `fwd`/`side` m from the origin, height `z`."""
        out = 1.0 if side > 0 else -1.0  # +side is the character's right
        dz = lambda metres: z + metres * self.m
        self.solve(f"{s}Hand", self.point(fwd - WRIST_BEHIND, side, dz(WRIST_ABOVE)), ARM[s])
        self.solve_many(
            [
                (f"{s}HandIndex1", self.point(fwd, side - out * KNUCKLE_SPREAD, dz(KNUCKLE_ABOVE))),
                (f"{s}HandPinky1", self.point(fwd, side + out * KNUCKLE_SPREAD, dz(KNUCKLE_ABOVE))),
            ],
            HAND[s],
        )
        for b in FINGERS[s]:
            self.set_rot(b, (FINGER_CURL, 0.0, 0.0))
        for b in THUMB[s]:
            self.set_rot(b, (THUMB_CURL, 0.0, 0.0))

    def snapshot(self, shorts) -> dict[str, tuple[float, float, float]]:
        return {s: tuple(self.bone(s).rotation_euler) for s in shorts if self.p + s in self.pb}


def _hand_bones() -> list[str]:
    return _posed_bones([*ARM.values(), *HAND.values()]) + [
        b for s in ("Left", "Right") for b in FINGERS[s] + THUMB[s]
    ]


def _posed_bones(chains) -> list[str]:
    out: list[str] = []
    for chain in chains:
        for short, *_ in chain:
            if short not in out:
                out.append(short)
    return out


def _write_keys(rig: Rig, cb, frames: list[dict], hips_loc: Vector | None) -> None:
    for short in frames[0]:
        _set_rot_keys(cb, rig.p + short, [(i + 1, f[short]) for i, f in enumerate(frames)])
    if hips_loc is not None:
        loc = tuple(hips_loc)
        _set_loc_keys(cb, rig.p + "Hips", [(i + 1, loc) for i in range(len(frames))])


def bake_riding(arm: bpy.types.Object) -> bpy.types.Action:
    _strip_all_animation()
    act, cb = _setup_action(arm, "Riding")
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rig = Rig(arm)

    # Lean over the bars, eyes up the road.
    torso = {
        "Spine": (0.3, 0.0, 0.0),
        "Spine1": (0.25, 0.0, 0.0),
        "Spine2": (0.2, 0.0, 0.0),
        "Neck": (-0.35, 0.0, 0.0),
        "Head": (-0.3, 0.0, 0.0),
    }
    for short, e in torso.items():
        rig.set_rot(short, e)

    saddle_z = rig.hips_z - HIPS_ABOVE_SADDLE * rig.m
    for s, sign in (("Left", -1.0), ("Right", 1.0)):
        rig.grip(s, BAR_FWD, sign * GRIP_HALF, saddle_z + BAR_UP * rig.m)
    arms = rig.snapshot(_hand_bones())

    n = 24
    frames = []
    for f in range(n):
        t = (f / n) * math.tau
        pose = dict(torso)
        pose.update(arms)
        for s, phase in (("Left", 0.0), ("Right", math.pi)):
            a = -(t + phase)  # forward pedalling: the top of the stroke moves ahead
            fwd = BB_FWD + CRANK * math.cos(a)
            up = -BB_DOWN + CRANK * math.sin(a) + ANKLE_ABOVE_PEDAL
            ankle = rig.point(fwd, rig.side_of(s), saddle_z + up * rig.m)
            rig.solve(f"{s}Foot", ankle, LEG[s])
        pose.update(rig.snapshot(_posed_bones(LEG.values())))
        frames.append(pose)

    _write_keys(rig, cb, frames, None)
    print("  Riding IK residual cm", {k: round(v * 100, 1) for k, v in rig.worst.items()})
    act.frame_start = 1
    act.frame_end = n
    bpy.ops.object.mode_set(mode="OBJECT")
    return act


def bake_scooter(arm: bpy.types.Object) -> bpy.types.Action:
    """Electric share scooter: both feet on the deck, hands on the grips, a gentle sway."""
    _strip_all_animation()
    act, cb = _setup_action(arm, "Scooter")
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rig = Rig(arm)

    rig.drop_hips(SC_HIPS_DROP)
    hips_loc = rig.bone("Hips").location.copy()
    for s, fwd, sign in (("Left", SC_FRONT_FOOT, -1.0), ("Right", SC_REAR_FOOT, 1.0)):
        ankle = rig.point(fwd, sign * SC_FOOT_SIDE, rig.rest_foot[s].z)
        rig.solve(f"{s}Foot", ankle, LEG[s])
    feet = rig.snapshot(_posed_bones(LEG.values()))

    n = 28
    frames = []
    for f in range(n):
        t = (f / n) * math.tau
        torso = {
            "Spine": (0.1, 0.0, 0.03 * math.sin(t)),
            "Spine1": (0.06, 0.0, 0.0),
            "Neck": (-0.08, 0.0, -0.02 * math.sin(t)),
        }
        for short, e in torso.items():
            rig.set_rot(short, e)
        for s, sign in (("Left", -1.0), ("Right", 1.0)):
            rig.grip(s, SC_GRIP_FWD, sign * SC_GRIP_HALF, rig.sole + SC_GRIP_UP * rig.m)
        pose = dict(torso)
        pose.update(feet)
        pose.update(rig.snapshot(_hand_bones()))
        frames.append(pose)

    _write_keys(rig, cb, frames, hips_loc)
    print("  Scooter IK residual cm", {k: round(v * 100, 1) for k, v in rig.worst.items()})
    act.frame_start = 1
    act.frame_end = n
    bpy.ops.object.mode_set(mode="OBJECT")
    return act


# Getting up off the paving after a knock-down (viewer/pedestrians.js blends into the first key
# while thrown, holds it while lying, plays the rest). Wider joint ranges than the riding poses.
GU_FPS = 24
GU_REF_LEG = 0.767  # m, Remy's hip-to-ankle length the keys below are authored for
GU_LEG = {
    s: [(f"{s}UpLeg", 0, -1.0, 2.3), (f"{s}UpLeg", 2, -0.5, 0.5), (f"{s}UpLeg", 1, -0.6, 0.6), (f"{s}Leg", 0, -2.7, 0.0)]
    for s in ("Left", "Right")
}
GU_ARM = {
    "Left": [("LeftArm", 0, -1.2, 1.6), ("LeftArm", 2, -0.6, 1.9), ("LeftArm", 1, -0.9, 0.9), ("LeftForeArm", 2, 0.0, 2.4)],
    "Right": [("RightArm", 0, -1.2, 1.6), ("RightArm", 2, -1.9, 0.6), ("RightArm", 1, -0.9, 0.9), ("RightForeArm", 2, -2.4, 0.0)],
}
GU_SPINE = ("Spine", "Spine1", "Spine2", "Neck", "Head")
GU_FEET = ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase")
ZERO = (0.0, 0.0, 0.0)
# Each key: time (s); hips (fwd, up, pitch[, roll]) in m / rad; spine / feet / fk local eulers;
# IK goals as (fwd, side, up) m from the clip origin (+side = the character's right).
# The clip ends standing at the origin so the walk cycle picks up without a slide.
GETUP_KEYS = [
    {  # face down where they landed, cheek on the paving, hands by the shoulders
        "t": 0.0,
        "hips": (-0.6, 0.11, math.pi / 2, 0.08),
        "spine": {"Neck": (-0.15, 0.0, 0.0), "Head": (-0.1, 0.9, 0.0)},
        "fk": {"LeftUpLeg": ZERO, "LeftLeg": (-0.04, 0.0, 0.0), "RightUpLeg": (0.0, 0.0, -0.08), "RightLeg": (-0.2, 0.0, 0.0)},
        "feet": {"LeftFoot": (-0.9, 0.0, 0.0), "RightFoot": (-0.7, 0.0, 0.0)},
        "hands": {"Left": (-0.2, -0.34, 0.04), "Right": (-0.05, 0.32, 0.04)},
        "palms": ("Left", "Right"),
    },
    {  # press up on the arms, look up
        "t": 0.5,
        "hips": (-0.58, 0.17, 1.2),
        "spine": {"Spine": (-0.12, 0.0, 0.0), "Spine1": (-0.1, 0.0, 0.0), "Neck": (-0.35, 0.0, 0.0), "Head": (-0.2, 0.0, 0.0)},
        # Hips extended by the torso's rise so the legs stay along the paving.
        "fk": {"LeftUpLeg": (-0.37, 0.0, 0.0), "LeftLeg": (-0.1, 0.0, 0.0), "RightUpLeg": (-0.37, 0.0, 0.0), "RightLeg": (-0.1, 0.0, 0.0)},
        "feet": {"LeftFoot": (-0.8, 0.0, 0.0), "RightFoot": (-0.8, 0.0, 0.0)},
        "hands": {"Left": (-0.08, -0.26, 0.04), "Right": (-0.08, 0.26, 0.04)},
        "palms": ("Left", "Right"),
    },
    {  # knees drawn under the hips: on all fours
        "t": 1.0,
        "hips": (-0.52, 0.49, 1.45),
        "spine": {"Spine": (0.12, 0.0, 0.0), "Spine1": (0.08, 0.0, 0.0), "Neck": (-0.45, 0.0, 0.0), "Head": (-0.2, 0.0, 0.0)},
        "knees": {"Left": (-0.5, -0.11, 0.06), "Right": (-0.5, 0.11, 0.06)},
        "ankles": {"Left": (-0.92, -0.11, 0.08), "Right": (-0.92, 0.11, 0.08)},
        "feet": {"LeftFoot": (-0.8, 0.0, 0.0), "RightFoot": (-0.8, 0.0, 0.0)},
        "hands": {"Left": (-0.08, -0.24, 0.04), "Right": (-0.08, 0.24, 0.04)},
        "palms": ("Left", "Right"),
    },
    {  # bring the left foot through, weight on the right hand and knee
        "t": 1.4,
        "hips": (-0.48, 0.5, 1.32),
        "spine": {"Spine": (0.15, 0.0, 0.0), "Spine1": (0.1, 0.0, 0.0), "Neck": (-0.4, 0.0, 0.0)},
        "ankles": {"Left": (-0.42, -0.15, 0.16), "Right": (-0.92, 0.11, 0.08)},
        "knees": {"Right": (-0.5, 0.11, 0.06)},
        "feet": {"LeftFoot": (0.0, 0.0, 0.0), "RightFoot": (-0.8, 0.0, 0.0)},
        "hands": {"Left": (-0.04, -0.24, 0.14), "Right": (-0.06, 0.24, 0.04)},
        "palms": ("Right",),
    },
    {  # kneeling lunge, both hands pushing on the front knee
        "t": 1.8,
        "hips": (-0.36, 0.52, 0.55),
        "spine": {"Spine": (0.25, 0.0, 0.0), "Spine1": (0.12, 0.0, 0.0), "Neck": (-0.3, 0.0, 0.0)},
        "fk": {"LeftHand": (0.3, 0.0, 0.0), "RightHand": (0.3, 0.0, 0.0)},
        "ankles": {"Left": (0.0, -0.13, 0.08), "Right": (-0.88, 0.11, 0.08)},
        "knees": {"Right": (-0.48, 0.11, 0.06)},
        "feet": {"LeftFoot": ZERO, "RightFoot": (-0.8, 0.0, 0.0)},
        "hands": {"Left": (0.02, -0.16, 0.54), "Right": (-0.1, -0.06, 0.55)},
    },
    {  # push off the knee, back foot swinging up
        "t": 2.3,
        "hips": (-0.16, 0.82, 0.32),
        "spine": {"Spine": (0.2, 0.0, 0.0), "Spine1": (0.08, 0.0, 0.0), "Neck": (-0.2, 0.0, 0.0)},
        "ankles": {"Left": (0.0, -0.12, 0.08), "Right": (-0.3, 0.11, 0.16)},
        "feet": {"LeftFoot": ZERO, "RightFoot": (-0.3, 0.0, 0.0)},
        "hands": {"Left": (0.04, -0.17, 0.66), "Right": (-0.03, -0.06, 0.7)},
    },
    {  # standing, arms down
        "t": 2.8,
        "hips": None,
        "fk": {
            "LeftUpLeg": ZERO, "LeftLeg": ZERO, "RightUpLeg": ZERO, "RightLeg": ZERO,
            "LeftArm": (1.25, 0.0, 0.12), "RightArm": (1.25, 0.0, -0.12),
            "LeftForeArm": (0.0, 0.0, 0.25), "RightForeArm": (0.0, 0.0, -0.25),
            "LeftHand": ZERO, "RightHand": ZERO,
        },
        "feet": {"LeftFoot": ZERO, "RightFoot": ZERO},
    },
]


def bake_getup(arm: bpy.types.Object) -> bpy.types.Action:
    _strip_all_animation()
    act, cb = _setup_action(arm, "GetUp")
    act.use_cyclic = False
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rig = Rig(arm)
    rest_up = (rig.hips_z - rig.sole) / rig.m
    # Keys are authored for Remy's legs; scale every distance for longer / shorter legs.
    k = (rig.head("LeftUpLeg").z - rig.head("LeftFoot").z) / rig.m / GU_REF_LEG
    at = lambda g: rig.point(g[0] * k, g[1] * k, rig.sole + g[2] * k * rig.m)

    limbs = _posed_bones([*GU_LEG.values(), *GU_ARM.values()])
    keyed = ["Hips", *GU_SPINE, *limbs, *GU_FEET, "LeftHand", "RightHand"]
    keyed = [b for b in keyed if rig.p + b in rig.pb]
    rots: dict[str, list] = {b: [] for b in keyed}
    locs: list = []
    prev_hips = None

    def pose_key(key, drop: float) -> float:
        """Pose one key with the hips `drop` m lower; returns how far the knees stay above the floor."""
        rig.worst = {}
        if key["hips"]:
            rig.place_hips(key["hips"][0] * k, key["hips"][1] * k - drop, *key["hips"][2:])
        else:
            rig.place_hips(0.0, rest_up, 0.0)
        for short in GU_SPINE:
            rig.set_rot(short, key.get("spine", {}).get(short, ZERO))
        for short, e in {**key.get("fk", {}), **key.get("feet", {})}.items():
            rig.set_rot(short, e)
        hover = 0.0
        for s in ("Left", "Right"):
            goals = []
            if s in key.get("knees", {}):
                goals.append((f"{s}Leg", at(key["knees"][s])))
            if s in key.get("ankles", {}):
                goals.append((f"{s}Foot", at(key["ankles"][s])))
            if goals:
                rig.solve_many(goals, GU_LEG[s])
            if s in key.get("knees", {}):
                hover = max(hover, (rig.head(f"{s}Leg").z - at(key["knees"][s]).z) / rig.m)
            if s in key.get("hands", {}):
                h = key["hands"][s]
                rig.solve(f"{s}Hand", at(h), GU_ARM[s])
                if s in key.get("palms", ()):
                    # Palm flat on the paving, fingers pointing ahead.
                    out = 1.0 if h[1] > 0 else -1.0
                    knuckle = lambda spread: rig.point(h[0] * k + 0.09, h[1] * k + spread, rig.sole + 0.025 * rig.m)
                    rig.solve_many(
                        [(f"{s}HandIndex1", knuckle(-out * 0.035)), (f"{s}HandPinky1", knuckle(out * 0.035))],
                        HAND[s],
                    )
        rig.update()
        return hover

    for key in GETUP_KEYS:
        frame = round(key["t"] * GU_FPS) + 1
        drop = 0.0
        for _ in range(4):  # kneeling: lower the hips until the knees reach the paving
            hover = pose_key(key, drop)
            if hover < 0.015:
                break
            drop += hover
        hb = rig.bone("Hips")
        eul = hb.rotation_euler.copy()
        if prev_hips is not None:
            eul.make_compatible(prev_hips)
        prev_hips = eul
        for b in keyed:
            rots[b].append((frame, tuple(eul) if b == "Hips" else tuple(rig.bone(b).rotation_euler)))
        locs.append((frame, tuple(hb.location)))
        res = {b: round(v * 100, 1) for b, v in rig.worst.items() if v > 0.03}
        print(f"  GetUp t={key['t']:.1f} hips −{drop * 100:.0f} cm, IK residual > 3 cm", res)

    for b, frames in rots.items():
        _set_rot_keys(cb, rig.p + b, frames, smooth=True)
    _set_loc_keys(cb, rig.p + "Hips", locs, smooth=True)
    act.frame_start = 1
    act.frame_end = round(GETUP_KEYS[-1]["t"] * GU_FPS) + 1
    bpy.context.scene.render.fps = GU_FPS
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


BAKERS = {"Riding": bake_riding, "Scooter": bake_scooter, "GetUp": bake_getup}


def process_character(name: str, kinds) -> None:
    src = CHAR_DIR / f"{name}_Walking.glb"
    if not src.exists():
        print(f"SKIP missing {src.name}")
        return
    for kind in kinds:
        _clear_scene()
        arm = _import_glb(src)
        act = BAKERS[kind](arm)
        _export_glb(CHAR_DIR / f"{name}_{kind}.glb", act)


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    kinds = [k for k in argv if k in BAKERS] or list(BAKERS)
    names = [n for n in argv if n in CHARS] or list(CHARS)
    for name in names:
        try:
            process_character(name, kinds)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {exc}")
            import traceback

            traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
