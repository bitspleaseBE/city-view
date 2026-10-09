"""Retarget the Mixamo get-up clip onto the Rocketbox pedestrians.

Rocketbox ships no get-up / fall animation, so the IK-baked Mixamo clip
(``viewer/characters/Remy_GetUp.glb``, scripts/bake_mixamo_rider_clips.py) is carried over to
each person in ``viewer/characters/people/`` and written as an animation-only GLB to
``viewer/characters/people/getup/<id>.glb``.

The two skeletons have different rest poses and bone axes, so each bone is matched in world
space: the target bone's rest frame (its direction to the next joint plus the body's left/right
axis) is aligned to the source's, then the source's rotation away from its rest is applied.
Root motion goes on the Bip01 node (as in the walk clip), scaled by leg length.

  blender --background --python scripts/bake_rocketbox_getup.py [-- <person id> ...]
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from extract_anim_clips import read_glb, strip_to_clips, write_glb  # noqa: E402

PEOPLE = ROOT / "viewer" / "characters" / "people"
OUT = PEOPLE / "getup"
SOURCE = ROOT / "viewer" / "characters" / "Remy_GetUp.glb"
FPS = 24

# (Mixamo bone, Rocketbox bone, Mixamo next joint, Rocketbox next joint); None = last in its chain,
# aimed along the parent → bone direction instead.
SIDES = [("Left", "L"), ("Right", "R")]
FINGERS = [("Index", "1"), ("Middle", "2"), ("Ring", "3"), ("Pinky", "4")]
MAP = [
    ("Hips", "Bip01 Pelvis", "Spine", "Bip01 Spine"),
    ("Spine", "Bip01 Spine", "Spine1", "Bip01 Spine1"),
    ("Spine1", "Bip01 Spine1", "Spine2", "Bip01 Spine2"),
    ("Spine2", "Bip01 Spine2", "Neck", "Bip01 Neck"),
    ("Neck", "Bip01 Neck", "Head", "Bip01 Head"),
    ("Head", "Bip01 Head", None, None),
]
for m, r in SIDES:
    MAP += [
        (f"{m}Shoulder", f"Bip01 {r} Clavicle", f"{m}Arm", f"Bip01 {r} UpperArm"),
        (f"{m}Arm", f"Bip01 {r} UpperArm", f"{m}ForeArm", f"Bip01 {r} Forearm"),
        (f"{m}ForeArm", f"Bip01 {r} Forearm", f"{m}Hand", f"Bip01 {r} Hand"),
        (f"{m}Hand", f"Bip01 {r} Hand", f"{m}HandMiddle1", f"Bip01 {r} Finger2"),
        (f"{m}UpLeg", f"Bip01 {r} Thigh", f"{m}Leg", f"Bip01 {r} Calf"),
        (f"{m}Leg", f"Bip01 {r} Calf", f"{m}Foot", f"Bip01 {r} Foot"),
        (f"{m}Foot", f"Bip01 {r} Foot", f"{m}ToeBase", f"Bip01 {r} Toe0"),
        (f"{m}ToeBase", f"Bip01 {r} Toe0", None, None),
    ]
    # Mixamo fingers are keyed straight, which is what lays the palms flat on the paving.
    for fm, fr in FINGERS:
        chain = [(f"{m}Hand{fm}{i}", f"Bip01 {r} Finger{fr}{'' if i == 1 else i - 1}") for i in (1, 2, 3)]
        for i, (s, t) in enumerate(chain):
            nxt = chain[i + 1] if i + 1 < len(chain) else (None, None)
            MAP.append((s, t, *nxt))

# Joint heights over the floor follow the source (× leg ratio) through two-bone IK.
LIMBS = [(f"Bip01 {r} {a}", f"Bip01 {r} {b}", f"Bip01 {r} {c}", f"{m}{c_src}")
         for m, r in SIDES
         for a, b, c, c_src in (("UpperArm", "Forearm", "Hand", "Hand"), ("Thigh", "Calf", "Foot", "Foot"))]
IK_TOLERANCE = 0.01

UP = Vector((0.0, 0.0, 1.0))
FWD = Vector((0.0, -1.0, 0.0))  # both rigs face −Y in Blender (+Z in three.js)


def rot(m: Matrix) -> Matrix:
    return m.to_3x3().normalized()


def frame(primary: Vector, lateral: Vector) -> Matrix:
    x = primary.normalized()
    hint = lateral if abs(x.dot(lateral.normalized())) < 0.7 else FWD
    z = x.cross(hint).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


class Skel:
    def __init__(self, arm: bpy.types.Object, name) -> None:
        self.arm = arm
        self.name = name  # short → pose bone name
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
        self.mw = arm.matrix_world.copy()

    def rest_head(self, short: str) -> Vector:
        return self.mw @ self.arm.data.bones[self.name(short)].head_local

    def rest_rot(self, short: str) -> Matrix:
        return rot(self.mw @ self.arm.data.bones[self.name(short)].matrix_local)

    def has(self, short) -> bool:
        return short is not None and self.name(short) in self.arm.data.bones

    def aim(self, short: str, child) -> Vector:
        if self.has(child):
            return self.rest_head(child) - self.rest_head(short)
        parent = self.arm.data.bones[self.name(short)].parent
        return self.rest_head(short) - self.mw @ parent.head_local


def floor_z(arm: bpy.types.Object) -> float:
    dg = bpy.context.evaluated_depsgraph_get()
    z = float("inf")
    for o in arm.children_recursive:
        if o.type == "MESH":
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            z = min([z] + [(ev.matrix_world @ v.co).z for v in me.vertices])
            ev.to_mesh_clear()
    return z


def turn_bone(arm: bpy.types.Object, pb: bpy.types.PoseBone, delta: Matrix) -> None:
    """Rotate a pose bone by a world-space rotation about its head."""
    r = rot(arm.matrix_world)
    m = r.inverted() @ delta @ r @ rot(pb.matrix)
    pb.matrix = Matrix.Translation(pb.head) @ m.to_4x4()
    bpy.context.view_layer.update()


def world_head(arm, pb) -> Vector:
    return arm.matrix_world @ pb.head


def two_bone_ik(arm, upper, lower, end, goal: Vector) -> None:
    """Bend upper/lower so end's head reaches goal, keeping the current bend plane."""
    s, e, w = (world_head(arm, b) for b in (upper, lower, end))
    l1, l2 = (e - s).length, (w - e).length
    to_goal = goal - s
    d = min(max(to_goal.length, abs(l1 - l2) + 1e-4), (l1 + l2) * 0.999)
    u = to_goal.normalized()
    n = (e - s).cross(w - s)
    if n.length < 1e-6:
        return
    v = n.normalized().cross(u)
    if v.dot(e - s) < 0:
        v.negate()
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    elbow = s + (u * cos_a + v * (1 - cos_a * cos_a) ** 0.5) * l1
    turn_bone(arm, upper, (e - s).rotation_difference(elbow - s).to_matrix())
    e, w = world_head(arm, lower), world_head(arm, end)
    turn_bone(arm, lower, (w - e).rotation_difference(goal - e).to_matrix())


def import_armature(path: Path) -> bpy.types.Object:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.type == "MESH" and not any(md.type == "ARMATURE" for md in o.modifiers):
            bpy.data.objects.remove(o, do_unlink=True)  # importer's bone-shape icosphere
    return next(o for o in bpy.data.objects if o.type == "ARMATURE" and o in new)


def retarget(pid: str) -> Path:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS

    src_arm = import_armature(SOURCE)
    prefix = next(b.name[: -len("Hips")] for b in src_arm.data.bones if b.name.endswith("Hips"))
    src = Skel(src_arm, lambda s: prefix + s)
    act = src_arm.animation_data.action
    f0, f1 = (int(round(v)) for v in act.frame_range)

    tgt_arm = import_armature(PEOPLE / f"{pid}.glb")
    if tgt_arm.animation_data:
        tgt_arm.animation_data_clear()
    for a in list(bpy.data.actions):
        if a != act:
            bpy.data.actions.remove(a)
    scene.frame_set(f0)
    # Bind pose: rest bones, glTF node transform on the Bip01 object.
    for pb in tgt_arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    tgt = Skel(tgt_arm, lambda s: s)
    bpy.context.view_layer.update()

    pairs = [(s, t, sc, tc) for s, t, sc, tc in MAP if src.has(s) and tgt.has(t)]
    depth = lambda t: len(tgt_arm.data.bones[t].parent_recursive)
    pairs.sort(key=lambda p: depth(p[1]))

    lat_s = src.rest_head("LeftUpLeg") - src.rest_head("RightUpLeg")
    lat_t = tgt.rest_head("Bip01 L Thigh") - tgt.rest_head("Bip01 R Thigh")
    align = {}
    for s, t, sc, tc in pairs:
        a = frame(src.aim(s, sc), lat_s) @ frame(tgt.aim(t, tc), lat_t).transposed()  # target → source rest frame
        align[t] = (src.rest_rot(s).inverted() @ a @ tgt.rest_rot(t))

    leg = lambda k, a, b: (k.rest_head(a) - k.rest_head(b)).length
    ratio = leg(tgt, "Bip01 L Thigh", "Bip01 L Foot") / leg(src, "LeftUpLeg", "LeftFoot")
    src_hips0 = src.rest_head("Hips")
    pelvis_local = tgt_arm.data.bones["Bip01 Pelvis"].head_local
    obj_rot = rot(tgt_arm.matrix_world)
    obj_scale = tgt_arm.matrix_world.to_scale()
    tgt_pelvis0 = tgt.rest_head("Bip01 Pelvis")
    floor_t = floor_z(tgt_arm)
    scene.frame_set(f1)
    floor_s = floor_z(src_arm)
    toe_clear = {r: tgt.rest_head(f"Bip01 {r} Toe0").z - floor_t for _, r in SIDES}

    # Rocketbox bodies and coats are bulkier around the bones than Remy: measure how far the torso
    # sinks into the floor and raise the root by that much. Hands and feet are IK'd separately;
    # shins go by the knee joint, since skirt hems and boots follow the calf bone into the floor.
    meshes = [o for o in tgt_arm.children_recursive if o.type == "MESH"]
    torso = ("Pelvis", "Spine", "Neck", "Head", "Clavicle", "UpperArm", "Thigh")
    body_verts = {}
    for o in meshes:
        names = {g.index: g.name for g in o.vertex_groups}
        body_verts[o] = [v.index for v in o.data.vertices
                         if v.groups and any(p in names[max(v.groups, key=lambda g: g.weight).group]
                                             for p in torso)][::3]
    knees = [tgt_arm.pose.bones[f"Bip01 {r} Calf"] for _, r in SIDES]
    knee_clear = 0.05 * leg(tgt, "Bip01 L Thigh", "Bip01 L Foot") / 0.78  # knee joint over the paving

    def sink() -> float:
        dg = bpy.context.evaluated_depsgraph_get()
        low = float("inf")
        for o, idx in body_verts.items():
            ev = o.evaluated_get(dg)
            me = ev.to_mesh()
            mw = ev.matrix_world
            low = min([low] + [(mw @ me.vertices[i].co).z for i in idx])
            ev.to_mesh_clear()
        knee = min(world_head(tgt_arm, k).z for k in knees)
        return max(0.0, floor_t - low, floor_t + knee_clear - knee)

    def solve(f: int, lift: float) -> None:
        scene.frame_set(f)
        src_mw = src_arm.matrix_world
        hips = src_mw @ src_arm.pose.bones[src.name("Hips")].head
        pelvis = tgt_pelvis0 + (hips - src_hips0) * ratio + UP * lift
        tgt_arm.location = pelvis - obj_rot @ Vector(p * s for p, s in zip(pelvis_local, obj_scale))
        bpy.context.view_layer.update()
        tmw_rot_inv = rot(tgt_arm.matrix_world).inverted()
        wanted = {}
        for s, t, _, _ in pairs:
            q_src = rot(src_mw @ src_arm.pose.bones[src.name(s)].matrix)
            wanted[t] = q_src @ align[t]
            pb = tgt_arm.pose.bones[t]
            pb.matrix = Matrix.Translation(pb.head) @ (tmw_rot_inv @ wanted[t]).to_4x4()
            bpy.context.view_layer.update()
        for upper, lower, end, src_end in LIMBS:
            pbs = [tgt_arm.pose.bones[n] for n in (upper, lower, end)]
            goal = world_head(tgt_arm, pbs[2])
            src_z = (src_mw @ src_arm.pose.bones[src.name(src_end)].head).z
            goal.z = floor_t + (src_z - floor_s) * ratio
            if (world_head(tgt_arm, pbs[2]) - goal).length > IK_TOLERANCE:
                two_bone_ik(tgt_arm, *pbs, goal)
                end_pb = pbs[2]
                end_pb.matrix = Matrix.Translation(end_pb.head) @ (tmw_rot_inv @ wanted[end]).to_4x4()
                bpy.context.view_layer.update()
        for _, r in SIDES:
            foot, toe = (tgt_arm.pose.bones[f"Bip01 {r} {n}"] for n in ("Foot", "Toe0"))
            fh, th = world_head(tgt_arm, foot), world_head(tgt_arm, toe)
            dip = floor_t + toe_clear[r] - th.z
            if dip > 0.005:
                # Pitch the foot about its ankle until the toe joint clears the floor.
                arm_vec = th - fh
                axis = arm_vec.cross(UP)
                if axis.length > 1e-6:
                    span = arm_vec.length
                    cur = math.asin(max(-1.0, min(1.0, arm_vec.z / span)))
                    lifted = math.asin(max(-1.0, min(1.0, (arm_vec.z + dip) / span)))
                    turn_bone(tgt_arm, foot, Matrix.Rotation(lifted - cur, 3, axis.normalized()))

    frames = range(f0, f1 + 1)
    lifts = [0.0] * len(frames)
    for _ in range(2):  # the leg IK pulls knees back down after a lift, so measure again
        sunk = []
        for f, lift in zip(frames, lifts):
            solve(f, lift)
            sunk.append(sink())
        # Widen then soften the extra lift so it never pops between frames.
        held = [max(sunk[max(0, i - 3): i + 4]) for i in range(len(sunk))]
        lifts = [lift + sum(held[max(0, i - 3): i + 4]) / len(held[max(0, i - 3): i + 4])
                 for i, lift in enumerate(lifts)]
    print(f"  {pid}: torso lift up to {max(lifts) * 100:.1f} cm")

    keys: dict[str, list] = {t: [] for _, t, _, _ in pairs}
    obj_loc = []
    for f, lift in zip(frames, lifts):
        solve(f, lift)
        for _, t, _, _ in pairs:
            q = tgt_arm.pose.bones[t].rotation_quaternion.copy()
            if keys[t] and keys[t][-1][1].dot(q) < 0:
                q.negate()
            keys[t].append((f, q))
        obj_loc.append((f, tgt_arm.location.copy()))

    # Keys straight into fcurves (inserting while solving would re-evaluate over the pose).
    out_act = bpy.data.actions.new("GetUp")
    slot = out_act.slots.new(id_type="OBJECT", name=tgt_arm.name)
    strip = out_act.layers.new("Base").strips.new(type="KEYFRAME")
    cb = strip.channelbags.new(slot)

    def curve(path, n, samples):
        for i in range(n):
            fc = cb.fcurves.new(path, index=i)
            fc.keyframe_points.add(len(samples))
            for k, (fr, v) in enumerate(samples):
                fc.keyframe_points[k].co = (fr, v[i])
                fc.keyframe_points[k].interpolation = "LINEAR"
            fc.update()

    curve("location", 3, obj_loc)
    rmode = tgt_arm.rotation_mode
    if rmode == "QUATERNION":
        curve("rotation_quaternion", 4, [(fr, tgt_arm.rotation_quaternion) for fr, _ in obj_loc])
    else:
        curve("rotation_euler", 3, [(fr, tgt_arm.rotation_euler) for fr, _ in obj_loc])
    for t, samples in keys.items():
        curve(f'pose.bones["{t}"].rotation_quaternion', 4, samples)

    for o in list(src_arm.children_recursive) + [src_arm]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.actions.remove(act)
    tgt_arm.animation_data_create()
    tgt_arm.animation_data.action = out_act
    tgt_arm.animation_data.action_slot = slot
    scene.frame_start, scene.frame_end = f0, f1

    with tempfile.TemporaryDirectory() as tmp:
        full = Path(tmp) / f"{pid}.glb"
        bpy.ops.export_scene.gltf(
            filepath=str(full),
            export_format="GLB",
            export_animations=True,
            export_animation_mode="ACTIONS",
            export_force_sampling=True,
            export_skins=True,
            export_morph=False,
            export_apply=False,
            export_yup=True,
            export_cameras=False,
            export_lights=False,
            export_image_format="NONE",
        )
        gltf, binary = read_glb(full)
    clip, blob = strip_to_clips(gltf, binary)
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{pid}.glb"
    write_glb(dst, clip, blob)
    print(f"OK {pid}: legs ×{ratio:.2f}, {len(pairs)} bones, {dst.stat().st_size // 1024} KB")
    return dst


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    people = [p["id"] for p in json.loads((PEOPLE / "manifest.json").read_text())["people"]]
    for pid in [p for p in people if not argv or p in argv]:
        retarget(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
