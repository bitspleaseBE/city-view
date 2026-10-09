"""Clothing and accessories modelled on top of Rocketbox avatars, fitted to each avatar's own
head and legs in the T-pose and skinned to its Biped bones so they move with the walk.

Extras (see rocketbox_roster.py):
  hat_wide                    black felt hat with a wide brim
  kippah                      velvet skullcap on the back of the crown
  beard_dark / beard_grey / beard_short
  peyos / peyos_grey / peyos_child   curled sidelocks from the temples
  coat                        long coat skirt from the hips to below the knee
  skirt_long / skirt_child    mid-calf skirt / pleated knee-length skirt
"""
from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

UP = Vector((0, 0, 1))

HAIR = {
    "dark": (0.05, 0.036, 0.026),
    "grey": (0.46, 0.44, 0.42),
    "brown": (0.07, 0.045, 0.03),
    "child": (0.04, 0.03, 0.022),
}


# --- avatar measurements -----------------------------------------------------------------


class Body:
    """World-space T-pose measurements of one avatar."""

    def __init__(self, arm, mesh):
        self.arm, self.mesh = arm, mesh
        bpy.context.view_layer.update()
        me = mesh.data
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        mw = np.array(mesh.matrix_world)
        co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
        self.P = co
        head_bones = {b.name for b in arm.data.bones if self._under_head(b)}
        gi = {g.index for g in mesh.vertex_groups if g.name in head_bones}
        w = np.zeros(len(me.vertices))
        for v in me.vertices:
            w[v.index] = sum(g.weight for g in v.groups if g.group in gi)
        self.head_w = w
        self.head_mask = w > 0.5
        self.headb = self.bone("Head")
        nose = self.bone("MNose")
        f = nose - self.headb
        f.z = 0
        self.fwd = f.normalized()
        self.side = self.fwd.cross(UP).normalized()
        self.eye_z = (self.bone("REye").z + self.bone("LEye").z) / 2
        self.nose = nose
        self.mouth = (self.bone("MUpperLip") + self.bone("MBottomLip")) / 2
        self.neck = self.bone("Neck")
        self.pelvis = self.bone("Pelvis")
        self.hip_z = (self.bone("L Thigh").z + self.bone("R Thigh").z) / 2
        self.knee_z = (self.bone("L Calf").z + self.bone("R Calf").z) / 2
        self.left_sign = 1.0 if (self.bone("L Thigh") - self.pelvis).dot(self.side) > 0 else -1.0
        d = self.P - np.array(self.headb)
        self.hs = d @ np.array(self.side)
        self.hf = d @ np.array(self.fwd)

    def _under_head(self, b) -> bool:
        while b:
            if b.name == "Bip01 Head":
                return True
            b = b.parent
        return False

    def bone(self, leaf: str) -> Vector:
        return self.arm.matrix_world @ self.arm.data.bones[f"Bip01 {leaf}"].head_local

    def to_world(self, origin: Vector, x: float, y: float, z: float) -> Vector:
        return origin + self.side * x + self.fwd * y + UP * z


# --- mesh helpers ------------------------------------------------------------------------


def material(name, color, rough=0.8, image=None, clip=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Specular IOR Level"].default_value = 0.3
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if clip:
            rnd = nt.nodes.new("ShaderNodeMath")
            rnd.operation = "ROUND"
            nt.links.new(tex.outputs["Alpha"], rnd.inputs[0])
            nt.links.new(rnd.outputs[0], bsdf.inputs["Alpha"])
    return mat


def new_object(name, verts, faces, mats, face_mats=None, uvs=None, smooth=True, sharp_deg=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    for m in mats:
        me.materials.append(m)
    if face_mats is not None:
        me.polygons.foreach_set("material_index", face_mats)
    if uvs is not None:
        layer = me.uv_layers.new(name="UVChannel_1")
        for poly in me.polygons:
            for li, vi in zip(poly.loop_indices, poly.vertices):
                layer.data[li].uv = uvs[vi]
    me.shade_smooth() if smooth else me.shade_flat()
    if sharp_deg:
        me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def face_out(obj, center, axis=None):
    """Flip the mesh if most faces point towards `center` (or the vertical line through `axis`)."""
    me = obj.data
    score = 0.0
    for p in me.polygons:
        c = p.center
        ref = Vector((axis.x, axis.y, c.z)) if axis is not None else center
        score += p.normal.dot(c - ref) * p.area
    if score < 0:
        me.flip_normals()


def skin(obj, weights: dict[str, list[float]] | str):
    """weights: bone name -> per-vertex weight list, or one bone name for a rigid part."""
    n = len(obj.data.vertices)
    if isinstance(weights, str):
        weights = {weights: [1.0] * n}
    for bone, ws in weights.items():
        vg = obj.vertex_groups.new(name=bone)
        for i, w in enumerate(ws):
            if w > 1e-4:
                vg.add([i], float(w), "REPLACE")


def join(mesh, parts):
    if not parts:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    bpy.ops.object.join()


def tube(path, radii, segs=6):
    """Sweep a circle along `path` (list of Vector). Returns verts, faces."""
    verts, faces = [], []
    prev_n = None
    for i, p in enumerate(path):
        t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        ref = prev_n if prev_n is not None else (UP if abs(t.dot(UP)) < 0.9 else Vector((1, 0, 0)))
        n = (ref - t * ref.dot(t)).normalized()
        b = t.cross(n)
        prev_n = n
        for k in range(segs):
            a = 2 * math.pi * k / segs
            verts.append(p + (n * math.cos(a) + b * math.sin(a)) * radii[i])
    for i in range(len(path) - 1):
        for k in range(segs):
            a, b2 = i * segs + k, i * segs + (k + 1) % segs
            faces.append((a, b2, b2 + segs, a + segs))
    verts.append(path[-1] + (path[-1] - path[-2]).normalized() * radii[-1])
    tip = len(verts) - 1
    last = (len(path) - 1) * segs
    for k in range(segs):
        faces.append((last + k, last + (k + 1) % segs, tip))
    return verts, faces


# --- hair texture ------------------------------------------------------------------------


def strand_image(name, color, density, seed):
    """Vertical hair strands tiled in v; density 1 = opaque mat of hair."""
    rng = np.random.default_rng(seed)
    W = H = 256
    rgba = np.zeros((H, W, 4), np.float32)
    base = np.array(color, np.float32)
    if density >= 1:
        rgba[..., :3] = base * 0.85
        rgba[..., 3] = 1
    for _ in range(int(2600 * min(density, 1.0) + 900)):
        x0 = rng.uniform(0, W)
        y0 = rng.integers(0, H)
        length = rng.integers(H // 6, H // 2)
        slant = rng.normal(0, 0.12)
        shade = base * rng.uniform(0.5, 2.0)
        ys = (y0 + np.arange(length)) % H
        xs = (x0 + slant * np.arange(length) + 2 * np.sin(np.arange(length) / 9 + x0)).astype(int) % W
        rgba[ys, xs, :3] = shade
        rgba[ys, xs, 3] = 1
    img = bpy.data.images.new(name, W, H, alpha=True)
    img.pixels.foreach_set(np.clip(rgba[::-1], 0, 1).ravel())
    img.pack()
    return img


# --- hats ----------------------------------------------------------------------------------


def add_hat_wide(body: Body):
    hm = body.head_mask
    top = body.P[hm, 2].max()
    base_z = top - 0.09
    band = hm & (body.P[:, 2] > base_z - 0.01)
    s, f = body.hs[band], body.hf[band]
    sc, fc = (s.max() + s.min()) / 2, (f.max() + f.min()) / 2
    rx = float(np.clip((s.max() - s.min()) / 2 + 0.012, 0.082, 0.105))
    ry = float(np.clip((f.max() - f.min()) / 2 + 0.012, 0.098, 0.125))
    origin = body.headb + body.side * sc + body.fwd * fc
    origin.z = base_z
    crown_h = top - base_z + 0.05

    N = 56
    verts, faces, fm = [], [], []

    def ring(scale_x, scale_y, z, crease=0.0):
        start = len(verts)
        for k in range(N):
            a = 2 * math.pi * k / N
            x, y = math.cos(a) * scale_x, math.sin(a) * scale_y
            dz = -crease * math.exp(-((x / max(rx, 1e-3)) / 0.35) ** 2)
            verts.append(body.to_world(origin, x, y, z + dz))
        return start

    def bridge(a, b, mat):
        for k in range(N):
            k2 = (k + 1) % N
            faces.append((a + k, a + k2, b + k2, b + k))
            fm.append(mat)

    # Crown wall: band (satin) then felt, tapering slightly, rounded into a creased top.
    wall = [(0.0, 1.012, 0), (0.034, 1.012, 0), (0.035, 1.0, 1)]
    for t in np.linspace(0.08, 1.0, 6):
        wall.append((0.035 + (crown_h - 0.05) * t, 1.0 - 0.06 * t, 1))
    rings = [ring(rx * sc_, ry * sc_, z) for z, sc_, _ in wall]
    for i in range(len(rings) - 1):
        bridge(rings[i], rings[i + 1], 0 if wall[i][2] == 0 and wall[i + 1][2] == 0 else 1)
    edge_s = wall[-1][1]
    shoulder = [(0.012, 0.97), (0.022, 0.9), (0.028, 0.75), (0.032, 0.5), (0.034, 0.25)]
    prev = rings[-1]
    zt = wall[-1][0]
    for dz, sc_ in shoulder:
        r = ring(rx * edge_s * sc_, ry * edge_s * sc_, zt + dz, crease=0.024 * (1 - sc_ * 0.6))
        bridge(prev, r, 1)
        prev = r
    apex = len(verts)
    verts.append(body.to_world(origin, 0, 0, zt + 0.034 - 0.024))
    for k in range(N):
        faces.append((prev + k, prev + (k + 1) % N, apex))
        fm.append(1)

    # Brim: flat felt annulus with a bound edge, dipping slightly front and back.
    def brim_ring(extra_x, extra_y, z, dip):
        start = len(verts)
        for k in range(N):
            a = 2 * math.pi * k / N
            x = math.cos(a) * (rx * 1.012 + extra_x)
            y = math.sin(a) * (ry * 1.012 + extra_y)
            verts.append(body.to_world(origin, x, y, z - dip * math.sin(a) ** 2))
        return start

    bt0 = brim_ring(0, 0, 0.0, 0)
    bt1 = brim_ring(0.068, 0.072, 0.002, 0.008)
    bt2 = brim_ring(0.07, 0.074, -0.003, 0.008)
    bb1 = brim_ring(0.064, 0.068, -0.007, 0.008)
    bb0 = brim_ring(0, 0, -0.006, 0)
    bridge(bt0, bt1, 1)
    bridge(bt1, bt2, 1)
    bridge(bt2, bb1, 1)
    bridge(bb1, bb0, 1)

    felt = material("HatFelt", (0.008, 0.008, 0.009), 0.9)
    satin = material("HatBand", (0.006, 0.006, 0.007), 0.32)
    obj = new_object("Hat", verts, faces, [satin, felt], fm, sharp_deg=55)
    face_out(obj, origin + UP * 0.04)
    skin(obj, "Bip01 Head")
    return [obj]


def add_kippah(body: Body, color=(0.012, 0.012, 0.016)):
    hm = body.head_mask
    top_i = np.argmax(np.where(hm, body.P[:, 2], -1e9))
    apex = Vector(body.P[top_i]) - body.fwd * 0.018
    child = body.P[hm, 2].max() - body.P[hm, 2].min() < 0.27
    radius = 0.058 if child else 0.064
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body.mesh, depsgraph)
    inv = body.mesh.matrix_world.inverted()
    mw = body.mesh.matrix_world
    R, S = 6, 36
    verts = []
    for ri in range(R + 1):
        r = radius * ri / R
        for k in range(S if ri else 1):
            a = 2 * math.pi * k / S
            p = apex + body.side * (math.cos(a) * r) + body.fwd * (math.sin(a) * r)
            start = p + UP * 0.2
            loc, nrm, _, _ = bvh.ray_cast(inv @ start, (inv.to_3x3() @ -UP).normalized())
            hit = mw @ loc if loc is not None else p
            verts.append(hit + UP * 0.004)
    faces = []
    for k in range(S):
        faces.append((0, 1 + k, 1 + (k + 1) % S))
    for ri in range(1, R):
        a0 = 1 + (ri - 1) * S
        b0 = 1 + ri * S
        for k in range(S):
            k2 = (k + 1) % S
            faces.append((a0 + k, b0 + k, b0 + k2, a0 + k2))
    # Smooth heights so hair cards do not make the cap lumpy.
    zs = np.array([v.z for v in verts])
    for ri in range(1, R + 1):
        sl = slice(1 + (ri - 1) * S, 1 + ri * S)
        ring_z = zs[sl]
        zs[sl] = np.maximum(ring_z, np.convolve(np.r_[ring_z[-2:], ring_z, ring_z[:2]], np.ones(5) / 5, "valid"))
    for v, z in zip(verts, zs):
        v.z = float(z)
    obj = new_object("Kippah", verts, faces, [material("Kippah", color, 0.95)])
    face_out(obj, apex - UP * 0.1)
    skin(obj, "Bip01 Head")
    return [obj]


# --- facial hair -------------------------------------------------------------------------


def beard_region(body: Body) -> np.ndarray:
    P = body.P
    s, f, z = body.hs, body.hf, P[:, 2]
    mouth_f = (body.mouth - body.headb).dot(body.fwd)
    # Moustache up to the nose; beyond the mouth corners the cheek line rises to the sideburns.
    a = np.abs(s)
    lo, hi = body.mouth.z + 0.008, body.eye_z - 0.012
    cheek = np.where(a < 0.036, body.nose.z - 0.012, np.minimum(hi, lo + (a - 0.036) / 0.03 * (hi - lo)))
    jaw = (z < cheek) & (z > body.neck.z + 0.015) & (f > 0.004)
    lips = (a < 0.022) & (np.abs(z - body.mouth.z) < 0.0095) & (f > mouth_f - 0.03)
    return body.head_mask & jaw & ~lips


def erode(faces, rings):
    """Drop faces touching the open boundary, `rings` times."""
    for _ in range(rings):
        count = {}
        for fc in faces:
            for i in range(len(fc)):
                e = tuple(sorted((fc[i], fc[(i + 1) % len(fc)])))
                count[e] = count.get(e, 0) + 1
        edge_v = {v for e, n in count.items() if n == 1 for v in e}
        faces = [fc for fc in faces if not edge_v.intersection(fc)]
    return faces


def add_beard(body: Body, color, length, layers=3, seed=1):
    me = body.mesh.data
    head_mat = next(i for i, m in enumerate(me.materials) if m.name.lower().endswith("head"))
    region = beard_region(body)
    polys = [p for p in me.polygons if p.material_index == head_mat and all(region[v] for v in p.vertices)]
    if not polys:
        return []
    used = sorted({v for p in polys for v in p.vertices})
    remap = {v: i for i, v in enumerate(used)}
    P = body.P[used]
    mw3 = body.mesh.matrix_world.to_3x3()
    N = np.array([(mw3 @ me.vertices[v].normal).normalized()[:] for v in used])
    f = body.hf[used]
    z = P[:, 2]
    chin_f = float(np.percentile(f, 95))
    z_mouth = body.mouth.z
    z_low = float(z.min())
    hang = np.clip((z_mouth - z) / max(z_mouth - z_low, 1e-3), 0, 1) ** 1.4
    fwd = np.array(body.fwd)
    groups = {g.index: g.name for g in body.mesh.vertex_groups}
    weights: dict[str, list[float]] = {}
    for i, v in enumerate(used):
        for g in me.vertices[v].groups:
            weights.setdefault(groups[g.group], [0.0] * len(used))[i] = g.weight
    faces = [tuple(remap[v] for v in p.vertices) for p in polys]

    # Cylindrical UVs around the head so strands run downwards.
    ang = np.arctan2(body.hs[used], f)
    objs = []
    for li in range(layers):
        t = li / max(layers - 1, 1)
        off = 0.0018 + 0.012 * t
        down = length * t * hang
        pull = np.maximum(0, chin_f - f) * 0.7 * t * hang
        Q = P + N * off + (-np.array([0, 0, 1.0]))[None] * down[:, None] + fwd[None] * (pull[:, None] + 0.25 * down[:, None])
        uvs = [(float(a / math.pi * 2.5), float((z_mouth + 0.05 - q[2]) / 0.12)) for a, q in zip(ang, Q)]
        img = strand_image(f"BeardStrands{li}", color, 1.0 if li == 0 else 0.6 - 0.2 * t, seed + li)
        mat = material(f"Beard{li}", color, 0.72, image=img, clip=li > 0)
        layer_faces = erode(faces, 2) if li == 0 else faces
        obj = new_object(f"Beard{li}", [Vector(q) for q in Q], layer_faces, [mat], uvs=uvs)
        skin(obj, weights)
        objs.append(obj)
    return objs


def add_peyos(body: Body, color, length, curl_r=0.0065):
    hm = body.head_mask
    near_eye = hm & (np.abs(body.P[:, 2] - body.eye_z) < 0.025) & (body.hf > -0.01) & (body.hf < 0.04)
    half_w = float(np.abs(body.hs[near_eye]).max())
    objs = []
    mat = material("Peyos", color, 0.5)
    for side in (-1, 1):
        anchor = body.to_world(body.headb, side * (half_w - 0.006), 0.022, 0) + UP * (body.eye_z - body.headb.z + 0.005)
        verts, faces = [], []
        for strand in range(3):
            phase = strand * 2 * math.pi / 3
            path, radii = [], []
            n = 36
            for i in range(n + 1):
                t = i / n
                a = phase + side * t * 5.5 * 2 * math.pi
                r = curl_r * (0.4 + 0.6 * min(1, t * 4))
                p = anchor + body.side * (side * (0.007 + r * math.cos(a))) + body.fwd * (r * math.sin(a) + 0.004 * t)
                path.append(p - UP * (length * t))
                radii.append(0.0026 * (1 - 0.55 * t))
            v, fc = tube(path, radii)
            base = len(verts)
            verts += v
            faces += [tuple(base + k for k in face) for face in fc]
        obj = new_object("Peyos", verts, faces, [mat])
        skin(obj, "Bip01 Head")
        objs.append(obj)
    return objs


# --- skirts and coat tails ------------------------------------------------------------------


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def add_skirt(body: Body, z_top, z_bot, color, rough, *, margin=0.02, flare=0.05, pleats=0, name="Skirt"):
    P = body.P
    rel = P - np.array(body.pelvis)
    s = rel @ np.array(body.side)
    f = rel @ np.array(body.fwd)
    legs = (np.abs(s) < 0.3) & (np.abs(f) < 0.3)
    N, K = 48, 12
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
    dirs = np.stack([np.cos(angles), np.sin(angles)], 1)
    levels = np.linspace(z_top, z_bot, K)
    radii = np.zeros((K, N))
    for k, zk in enumerate(levels):
        band = legs & (np.abs(P[:, 2] - zk) < 0.03)
        pts = np.stack([s[band], f[band]], 1)
        h = (pts @ dirs.T).max(0) if len(pts) else np.full(N, 0.12)
        radii[k] = h + margin
        if k:
            t = k / (K - 1)
            radii[k] = np.maximum(radii[k], radii[k - 1]) + flare / (K - 1) * (0.4 + t)
    for _ in range(3):
        radii = (np.roll(radii, 1, 1) + 2 * radii + np.roll(radii, -1, 1)) / 4
    if pleats:
        t = np.linspace(0, 1, K)[:, None]
        radii *= 1 + 0.03 * np.cos(pleats * angles)[None] * (0.3 + 0.7 * t)

    verts, uvs = [], []
    for k, zk in enumerate(levels):
        for j in range(N):
            x, y = dirs[j] * radii[k, j]
            verts.append(body.to_world(Vector((body.pelvis.x, body.pelvis.y, zk)), x, y, 0))
            uvs.append((j / N, k / (K - 1)))
    # Turned-up hem gives the bottom edge some thickness.
    for j in range(N):
        x, y = dirs[j] * (radii[-1, j] - 0.006)
        verts.append(body.to_world(Vector((body.pelvis.x, body.pelvis.y, levels[-1] + 0.03)), x, y, 0))
        uvs.append((j / N, 1.0))
    faces = []
    for k in range(K):
        for j in range(N):
            j2 = (j + 1) % N
            a, b = k * N + j, k * N + j2
            faces.append((a, b, b + N, a + N))

    V = np.array([v[:] for v in verts])
    vs = (V - np.array(body.pelvis)) @ np.array(body.side)
    vz = V[:, 2]
    hang = np.clip((body.hip_z + 0.04 - vz) / (body.hip_z + 0.04 - body.knee_z), 0, 1)
    to_left = smoothstep(-0.05, 0.05, vs * body.left_sign)
    thigh = 0.9 * hang
    calf = 0.3 * np.clip((body.knee_z - vz) / 0.2, 0, 1)
    thigh = thigh - calf
    weights = {
        "Bip01 Pelvis": list(1 - thigh - calf),
        "Bip01 L Thigh": list(thigh * to_left),
        "Bip01 R Thigh": list(thigh * (1 - to_left)),
        "Bip01 L Calf": list(calf * to_left),
        "Bip01 R Calf": list(calf * (1 - to_left)),
    }
    obj = new_object(name, [Vector(v) for v in verts], faces, [material(name, color, rough)], uvs=uvs)
    face_out(obj, None, axis=body.pelvis)
    skin(obj, weights)
    return [obj]


# --- entry point -------------------------------------------------------------------------


def add_extras(entry, arm, mesh) -> None:
    extras = entry.get("extras") or []
    if not extras:
        return
    body = Body(arm, mesh)
    parts = []
    for ex in extras:
        if ex == "hat_wide":
            parts += add_hat_wide(body)
        elif ex == "kippah":
            parts += add_kippah(body)
        elif ex == "beard_dark":
            parts += add_beard(body, HAIR["dark"], 0.11)
        elif ex == "beard_grey":
            parts += add_beard(body, HAIR["grey"], 0.15)
        elif ex == "beard_short":
            parts += add_beard(body, HAIR["brown"], 0.035)
        elif ex == "peyos":
            parts += add_peyos(body, HAIR["dark"], 0.13)
        elif ex == "peyos_grey":
            parts += add_peyos(body, HAIR["grey"], 0.12)
        elif ex == "peyos_child":
            parts += add_peyos(body, HAIR["child"], 0.08, curl_r=0.005)
        elif ex == "coat":
            parts += add_skirt(body, body.hip_z + 0.0, body.knee_z - 0.07, (0.011, 0.011, 0.012), 0.62,
                               margin=0.01, flare=0.015, name="Coat")
        elif ex == "skirt_long":
            parts += add_skirt(body, body.hip_z + 0.07, body.knee_z - 0.22, (0.018, 0.02, 0.034), 0.8,
                               margin=0.015, flare=0.09, name="SkirtLong")
        elif ex == "skirt_child":
            parts += add_skirt(body, body.hip_z + 0.05, body.knee_z - 0.04, (0.02, 0.024, 0.05), 0.8,
                               margin=0.012, flare=0.07, pleats=14, name="SkirtPleated")
        else:
            raise ValueError(f"unknown extra {ex!r} for {entry['id']}")
    join(mesh, parts)
