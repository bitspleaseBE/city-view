"""Hand models for the second Klein Antwerpen set.

Proportions follow the Inventaris Onroerend Erfgoed descriptions (agentschap
texts for erfgoedobjecten 6850, 7453, 7455, 7456, 6802 and 10902). Geometry and
tiling materials only — no photographs.
"""

from __future__ import annotations

import math

from cityview.landmark_kit import (
    Edge,
    Frame,
    Mesh,
    Vec2,
    arch_points,
    archivolt,
    band,
    cell,
    cylinder,
    extrude_ring,
    front_edge,
    frustum,
    merged_edges,
    gable_roof,
    hip_roof,
    opening,
    pane,
    profile_slab,
    rbox,
    simplify_ring,
)

GLASS = ("glass_amber", "glass_blue", "glass_green", "glass_amber")


def _span(ring: list[Vec2], lm: dict):
    """Street frame. ``a`` runs left→right as you face the facade; ``d`` is 0 on the
    street wall and negative into the building. Returns (frame, outline, width, depth)."""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    outline = simplify_ring(pts, 0.55, 9.0) if len(pts) > 8 else pts
    if len(outline) < 3:
        outline = pts
    anchor = tuple(lm["anchor_xy"])
    edge = front_edge(outline, anchor, 14.0)
    f = edge.frame()
    locs = [f.local(*p) for p in outline]
    a0, a1 = min(p[0] for p in locs), max(p[0] for p in locs)
    d_back, d_front = min(p[1] for p in locs), max(p[1] for p in locs)
    width_all = max(0.5, a1 - a0)
    if edge.length >= 0.62 * width_all:
        width, depth = edge.length, max(2.0, -d_back)
        return f, outline, width, depth, edge
    f = f.shifted(a0, d_front)
    return f, outline, width_all, max(2.0, d_front - d_back), edge


def _skip_facing(normal: Vec2):
    def pred(e: Edge) -> bool:
        return e.outward[0] * normal[0] + e.outward[1] * normal[1] > 0.72

    return pred


def _body(m: Mesh, outline: list[Vec2], holes: list[list[Vec2]], z1: float, wall: str, front: Edge) -> None:
    extrude_ring(m, outline, holes, 0.0, z1, wall, None, skip=_skip_facing(front.outward))


def _near_street(front: Edge, wall: Frame):
    """Drop every wall on the street side of the front. A facade skin replaces them;
    leaving the short jogs in makes them read as slabs standing in front of the tower."""
    facing = _skip_facing(front.outward)

    def pred(e: Edge) -> bool:
        if facing(e):
            return True
        mx = (e.p0[0] + e.p1[0]) * 0.5
        my = (e.p0[1] + e.p1[1]) * 0.5
        return wall.local(mx, my)[1] > -4.0

    return pred


# The rest of this module is the street fronts. Each one is drawn to a specific
# photograph, not to a generic "art nouveau" or "church" recipe.


def _on_street(ring: list[Vec2], lm: dict):
    """The surveyed street edge, not the lot's long side. A townhouse front is ~7 m;
    the bbox span is the depth of the house."""
    _f, outline, _w, _d, edge = _span(ring, lm)
    wall = _wall_frame(edge.frame(), edge)
    locs = [wall.local(*p) for p in outline]
    back = max(2.0, -min(p[1] for p in locs))
    return wall, outline, edge.length, back, edge


def _wall_frame(f: Frame, edge: Edge) -> Frame:
    """d = 0 on the street wall itself, even when the footprint bbox sticks out past it."""
    return f.shifted(0.0, f.local(*edge.p0)[1])


def _present(f: Frame, width: float) -> Frame:
    """The street camera shows increasing ``a`` on the left of the picture.
    Flip the frame so a feature placed at a=0 (the left of the photograph) lands there."""
    x, y, _ = f.p(width, 0.0, 0.0)
    return Frame(x, y, -f.ux, -f.uy, f.nx, f.ny)


def _street_edges(ring: list[Vec2], lm: dict) -> list[Edge]:
    """Every long wall facing the same way as the surveyed street front."""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    main = front_edge(pts, tuple(lm["anchor_xy"]), 14.0)
    edges = [
        e
        for e in merged_edges(pts, 16.0)
        if e.length >= 8.0 and e.outward[0] * main.outward[0] + e.outward[1] * main.outward[1] > 0.9
    ]
    return edges or [main]


def _win(
    m: Mesh,
    f: Frame,
    a0: float,
    a1: float,
    z0: float,
    z1: float,
    kind: str,
    wall: str,
    glass: str = "glass",
    stone: str = "stone_white",
    *,
    divide: str = "none",
) -> None:
    """Opening with a stone surround. Houses stay one clear pane — a cross mullion
    made every Thielens window look like a church light."""
    ca = (a0 + a1) * 0.5
    w, h = a1 - a0, z1 - z0
    if w < 0.25 or h < 0.3:
        return
    arch = "round" if kind == "horseshoe" else kind
    spring = z0 + h * (0.22 if kind == "horseshoe" else 0.58 if arch in {"round", "pointed", "segmental"} else 0.86)
    hole = opening(ca, z0 + 0.05, max(0.28, w * (0.92 if kind == "horseshoe" else 0.78)), spring, arch, 6)
    cell(m, f, a0, a1, z0, z1, hole, 0.16, 0.02, wall, stone)
    pane(m, f, hole, 0.06, glass)
    if arch != "rect":
        archivolt(m, f, hole, max(0.07, w * 0.07), 0.14, 0.28, stone)
    # thin dark lining, not a cross through the glass
    t = 0.035
    rbox(m, f, a0 + w * 0.12, a0 + w * 0.12 + t, 0.08, 0.14, z0 + 0.1, spring - 0.05, "frame_dark")
    rbox(m, f, a1 - w * 0.12 - t, a1 - w * 0.12, 0.08, 0.14, z0 + 0.1, spring - 0.05, "frame_dark")
    if divide == "mullion" and w > 0.9:
        rbox(m, f, ca - 0.04, ca + 0.04, 0.07, 0.15, z0 + 0.12, spring - 0.06, "stone_white")
    if divide == "sash" and w > 0.7:
        rbox(m, f, ca - 0.025, ca + 0.025, 0.08, 0.13, z0 + 0.12, spring - 0.08, "frame_dark")


def _grille(m: Mesh, f: Frame, a0: float, a1: float, z0: float, z1: float, *, circle: bool = False) -> None:
    n = max(3, int((a1 - a0) / 0.32))
    for i in range(n):
        x = a0 + (a1 - a0) * (i + 0.5) / n
        rbox(m, f, x - 0.012, x + 0.012, 0.18, 0.28, z0, z1, "iron")
    rbox(m, f, a0, a1, 0.18, 0.28, z1 - 0.08, z1, "iron")
    ca = (a0 + a1) * 0.5
    arch = arch_points(ca, z0 + (z1 - z0) * 0.42, (a1 - a0) * 0.36, "round", 4)
    band(m, f, arch, [(x, z + 0.06) for x, z in arch], 0.18, 0.28, "iron", (ca, z0))
    if circle:
        ring = opening(ca, (z0 + z1) * 0.5 - 0.45, 0.9, (z0 + z1) * 0.5, "circle", 6)
        band(m, f, ring, [(x + (0.07 if x > ca else -0.07), z) for x, z in ring], 0.2, 0.3, "iron", (ca, (z0 + z1) * 0.5))


def _balcony(m: Mesh, f: Frame, a0: float, a1: float, z: float) -> None:
    """Open iron railing on a thin stone slab. A solid plate read as a grey box."""
    rbox(m, f, a0, a1, 0.02, 0.78, z, z + 0.08, "bluestone", skip=("bottom",))
    for t in (0.06, 0.5, 0.94):
        x = a0 + (a1 - a0) * t
        rbox(m, f, x - 0.07, x + 0.07, 0.12, 0.62, z - 0.42, z, "stone_grey")
    rbox(m, f, a0 + 0.04, a1 - 0.04, 0.62, 0.7, z + 0.62, z + 0.7, "iron")
    bars = max(6, int((a1 - a0) / 0.18))
    for i in range(bars):
        x = a0 + (a1 - a0) * (i + 0.5) / bars
        rbox(m, f, x - 0.012, x + 0.012, 0.58, 0.68, z + 0.08, z + 0.66, "iron")


def _cornice(m: Mesh, f: Frame, a0: float, a1: float, z: float) -> None:
    rbox(m, f, a0, a1, -0.02, 0.28, z, z + 0.16, "frame_dark", skip=("-d",))
    rbox(m, f, a0 - 0.06, a1 + 0.06, -0.02, 0.42, z + 0.16, z + 0.32, "bluestone", skip=("-d",))
    n = max(3, int((a1 - a0) / 0.85))
    for i in range(n):
        x = a0 + (a1 - a0) * (i + 0.5) / n
        rbox(m, f, x - 0.05, x + 0.05, 0.04, 0.22, z - 0.22, z, "stone_grey")


def _course(m: Mesh, f: Frame, a0: float, a1: float, z: float, mat: str = "stone_white", h: float = 0.12) -> None:
    if a1 - a0 < 0.2:
        return
    rbox(m, f, a0, a1, -0.02, 0.07, z, z + h, mat, skip=("-d",))


def _fans(m: Mesh, f: Frame, a0: float, a1: float, z: float) -> None:
    """No. 34: fan medallions and mascaron blocks. Not the swallow frieze of no. 40."""
    rbox(m, f, a0, a1, -0.01, 0.05, z, z + 0.62, "glass_blue")
    n = max(3, int((a1 - a0) / 1.15))
    for i in range(n):
        x = a0 + (a1 - a0) * (i + 0.5) / n
        rbox(m, f, x - 0.16, x + 0.16, 0.04, 0.1, z + 0.02, z + 0.2, "stone_grey")
        for k, dx in enumerate((-0.22, 0.0, 0.22)):
            m.face(
                [f.p(x + dx - 0.08, 0.08, z + 0.18), f.p(x + dx + 0.08, 0.08, z + 0.18), f.p(x + dx * 0.3, 0.08, z + 0.52)],
                "gold",
                normal=f.vec(0, 1, 0),
            )


def _birds(m: Mesh, f: Frame, a0: float, a1: float, z: float) -> None:
    """No. 40: swallows in blue and gold along the top frieze."""
    rbox(m, f, a0, a1, -0.01, 0.05, z, z + 0.58, "glass_blue")
    n = max(3, int((a1 - a0) / 1.05))
    for i in range(n):
        x = a0 + (a1 - a0) * (i + 0.5) / n
        m.face(
            [f.p(x - 0.38, 0.08, z + 0.16), f.p(x - 0.02, 0.08, z + 0.28), f.p(x - 0.08, 0.08, z + 0.46)],
            "gold",
            normal=f.vec(0, 1, 0),
        )
        m.face(
            [f.p(x + 0.38, 0.08, z + 0.16), f.p(x + 0.02, 0.08, z + 0.28), f.p(x + 0.08, 0.08, z + 0.46)],
            "gold",
            normal=f.vec(0, 1, 0),
        )
        rbox(m, f, x - 0.04, x + 0.04, 0.05, 0.1, z + 0.14, z + 0.4, "gold")


def _pruner(m: Mesh, f: Frame, a0: float, a1: float, z0: float, z1: float) -> None:
    """No. 38: a kneeling figure pruning a rose, not a green rectangle."""
    rbox(m, f, a0, a1, -0.01, 0.05, z0, z1, "glass_green")
    ca = (a0 + a1) * 0.5
    rbox(m, f, ca - 0.22, ca + 0.02, 0.05, 0.1, z0 + 0.12, z1 * 0.55 + z0 * 0.45, "stone_white")
    rbox(m, f, ca - 0.1, ca + 0.06, 0.06, 0.11, z1 - 0.38, z1 - 0.12, "stone_white")
    m.face(
        [f.p(ca + 0.05, 0.08, z0 + 0.35), f.p(ca + 0.42, 0.08, z0 + 0.15), f.p(ca + 0.28, 0.08, z1 - 0.15)],
        "gold",
        normal=f.vec(0, 1, 0),
    )


def _petal(m: Mesh, f: Frame, ca: float, zc: float, rel: list[Vec2], d: float, mat: str) -> None:
    xs = [p[0] for p in rel]

    def put(sign: float) -> None:
        m.face([f.p(ca + sign * x, d, zc + z) for x, z in rel], mat, normal=f.vec(0, 1, 0))

    if min(xs) >= -1e-3:
        put(1.0)
        put(-1.0)
    else:
        put(1.0)


def _rose(m: Mesh, f: Frame, ca: float, z_sill: float, r: float) -> None:
    """Harmoniestraat 24. One round leaded window: symmetric amber wings, blue mid,
    green hearts. The horseshoes are on the side bays, not here."""
    hole = opening(ca, z_sill, r * 2, z_sill, "circle", 8)
    pane(m, f, hole, 0.03, "glass_blue")
    archivolt(m, f, hole, max(0.18, r * 0.11), 0.02, 0.32, "stone_white")
    for s in (-1.0, 1.0):
        profile_slab(
            m, f,
            [(ca + s * r * 0.95, z_sill - 0.05), (ca + s * r * 1.35, z_sill - 0.15), (ca + s * r * 1.05, z_sill + r * 0.42)],
            0.1, 0.34, "stone_white", back=True,
        )
    zc = z_sill + r * 0.48
    s = r * 0.72
    _petal(m, f, ca, zc, [(0.0, 0.55 * s), (0.28 * s, 0.12 * s), (-0.28 * s, 0.12 * s)], 0.06, "gold")
    _petal(m, f, ca, zc, [(0.05 * s, 0.22 * s), (0.85 * s, 0.28 * s), (0.35 * s, -0.05 * s)], 0.06, "glass_amber")
    _petal(m, f, ca, zc, [(0.04 * s, -0.05 * s), (0.72 * s, -0.08 * s), (0.18 * s, -0.48 * s)], 0.06, "glass_green")
    _petal(m, f, ca, zc, [(0.08 * s, 0.05 * s), (0.42 * s, 0.18 * s), (0.22 * s, -0.22 * s)], 0.07, "gold")
    for x in (-0.28, 0.0, 0.28):
        rbox(m, f, ca + x * r - 0.03, ca + x * r + 0.03, 0.08, 0.14, z_sill + 0.15, z_sill + r * (1.55 - abs(x) * 0.7), "iron")
    for t in (0.35, 0.7):
        half = r * math.sin(math.acos(max(-1.0, min(1.0, (t - 0.5) * 2)))) * 0.85
        rbox(m, f, ca - half, ca + half, 0.08, 0.13, z_sill + r * t, z_sill + r * t + 0.05, "iron")
    rbox(m, f, ca - 0.16, ca + 0.16, 0.18, 0.36, z_sill + r * 1.85, z_sill + r * 2.05, "stone_white")


def _tracery(m: Mesh, f: Frame, ca: float, z0: float, w: float, z1: float, wall: str) -> None:
    """Two lights under a circle, with amber and blue glass so it is not a black void."""
    _win(m, f, ca - w * 0.5, ca + w * 0.5, z0, z1, "pointed", wall, "glass_dark", "stone_white", divide="mullion")
    r = w * 0.18
    cz = z1 - (z1 - z0) * 0.2
    hole = opening(ca, cz - r, r * 2, cz, "circle", 6)
    cell(m, f, ca - r - 0.1, ca + r + 0.1, cz - r, cz + r + 0.12, hole, 0.04, -0.12, wall, "stone_white")
    pane(m, f, hole, -0.08, "glass_blue")
    span = w * 0.32
    for s, mat in ((-1.0, "glass_amber"), (1.0, "glass_blue")):
        rbox(m, f, ca + s * span * 0.55 - span * 0.28, ca + s * span * 0.55 + span * 0.28, 0.05, 0.09, z0 + 0.4, cz - r - 0.15, mat)


def _pinnacle(m: Mesh, x: float, y: float, z: float, h: float = 2.0) -> None:
    frustum(m, x, y, z, z + h * 0.45, 0.22, 0.12, 4, "stone_white", top=False)
    frustum(m, x, y, z + h * 0.45, z + h, 0.12, 0.0, 4, "stone_white")


def _cross(m: Mesh, f: Frame, a: float, d: float, z: float, h: float = 1.1) -> None:
    rbox(m, f, a - 0.04, a + 0.04, d - 0.04, d + 0.04, z, z + h, "iron")
    rbox(m, f, a - 0.28, a + 0.28, d - 0.04, d + 0.04, z + h * 0.62, z + h * 0.62 + 0.08, "iron")


def _shell(ring, holes, lm, wall: str, eaves: float, ridge: float) -> tuple[Mesh, Frame, float]:
    m = Mesh()
    wall_f, outline, width, depth, edge = _on_street(ring, lm)
    f = _present(wall_f, width)
    _body(m, outline, holes, eaves, wall, edge)
    gable_roof(m, f, 0.1, width - 0.1, -min(depth, 14.0), 0.15, eaves, ridge, "slate", ridge="a", gable_mat=wall, overhang=0.12)
    _course(m, f, 0.0, width, 0.0, "bluestone", 0.85)
    return m, f, width


# ---------------------------------------------------------------- carriage house


def _koets_side(m: Mesh, f: Frame, a0: float, a1: float) -> None:
    """Side bay: horseshoe pair, mosaic lunette, basket window, balustrade, shouldered dormer."""
    ca = (a0 + a1) * 0.5
    cell(m, f, a0, a1, 0.55, 6.4, None, 0.0, 0.0, "brick")
    for z in (1.15, 3.45, 6.15):
        _course(m, f, a0 + 0.08, a1 - 0.08, z, "stone_white", 0.1)
    hw = min(0.48, (a1 - a0) * 0.2)
    for s in (-1.0, 1.0):
        c = ca + s * hw * 1.25
        _win(m, f, c - hw * 0.85, c + hw * 0.85, 1.25, 3.15, "horseshoe", "brick", "glass")
        _grille(m, f, c - hw * 0.7, c + hw * 0.7, 1.4, 2.9)
    _pruner(m, f, a0 + 0.2, a1 - 0.2, 3.2, 3.85)
    _win(m, f, a0 + 0.28, a1 - 0.28, 4.15, 5.85, "segmental", "brick", "glass")
    for x in (a0 + 0.28, ca, a1 - 0.28):
        rbox(m, f, x - 0.05, x + 0.05, 0.12, 0.28, 6.2, 6.85, "stone_white")
    rbox(m, f, a0 + 0.12, a1 - 0.12, -0.02, 0.32, 6.35, 8.05, "brick", skip=("bottom",))
    _win(m, f, ca - 0.32, ca + 0.32, 6.55, 7.55, "rect", "brick", "glass")
    profile_slab(m, f, [(a0 + 0.08, 8.05), (a1 - 0.08, 8.05), (ca, 8.85)], -0.02, 0.36, "stone_white", back=True)
    rbox(m, f, ca - 0.08, ca + 0.08, 0.1, 0.32, 8.85, 9.45, "stone_white")


def build_harmonie_koetshuis(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Harmoniestraat 24. Striped red brick, centre round stained-glass window over
    the carriage door, mosaic gable with a horse head. Horseshoes are the side bays."""
    m = Mesh()
    wall, outline, L, depth, edge = _on_street(ring, lm)
    f = _present(wall, L)
    _body(m, outline, holes, 6.5, "brick", edge)
    gable_roof(m, f, 0.15, L - 0.15, -min(depth, 14.0), 0.15, 6.5, 8.4, "slate", ridge="a", gable_mat="brick", overhang=0.12)
    _course(m, f, 0.0, L, 0.0, "bluestone", 0.5)
    c0, c1 = L * 0.26, L * 0.74
    _koets_side(m, f, 0.12, c0 - 0.08)
    _koets_side(m, f, c1 + 0.08, L - 0.12)
    ca = (c0 + c1) * 0.5
    for x in (c0, c1):
        rbox(m, f, x - 0.14, x + 0.14, -0.02, 0.28, 0.45, 9.6, "stone_white")
    rbox(m, f, c0, c1, 0.0, 0.35, 0.45, 8.5, "brick", skip=("+d", "bottom"))
    cf = f.shifted(0.0, 0.35)
    door = min(2.15, (c1 - c0) * 0.38)
    _win(m, cf, ca - door * 0.5, ca + door * 0.5, 0.55, 2.95, "rect", "brick", "door", "bluestone")
    # metope frieze and curved pediment with a rosette
    for i in range(5):
        x = ca - door * 0.7 + door * 1.4 * (i + 0.5) / 5
        rbox(m, cf, x - 0.08, x + 0.08, 0.02, 0.14, 3.0, 3.28, "stone_white")
    profile_slab(
        m, cf,
        [(ca - door * 0.85, 3.3), (ca + door * 0.85, 3.3), (ca + door * 0.4, 3.85), (ca - door * 0.4, 3.85)],
        0.0, 0.2, "stone_white", back=True,
    )
    disc = opening(ca, 3.45, 0.55, 3.45, "circle", 6)
    profile_slab(m, cf, disc, 0.14, 0.26, "gold")
    rose_r = min(2.05, (c1 - c0) * 0.34)
    _rose(m, cf, ca, 4.05, rose_r)
    # mosaic pediment, horse-head roundel
    profile_slab(m, cf, [(c0 + 0.3, 8.35), (c1 - 0.3, 8.35), (ca, 10.85)], -0.02, 0.16, "brick", back=True)
    profile_slab(m, cf, [(c0 + 0.65, 8.55), (c1 - 0.65, 8.55), (ca, 10.45)], 0.1, 0.2, "glass_green", back=True)
    _petal(m, cf, ca, 9.2, [(0.0, 0.85), (1.05, 0.05), (-1.05, 0.05)], 0.22, "gold")
    med = opening(ca, 9.35, 0.85, 9.35, "circle", 6)
    profile_slab(m, cf, med, 0.2, 0.32, "gold")
    rbox(m, cf, ca - 0.06, ca + 0.16, 0.28, 0.36, 9.15, 9.55, "brick_dark")
    rbox(m, cf, ca + 0.1, ca + 0.28, 0.28, 0.36, 9.28, 9.42, "brick_dark")
    return m


def build_benoit_34(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Peter Benoitstraat 34. Pale brick. Horseshoe and circle-grille on the left,
    door with two suns on the right, open balcony, rectangular triple, round triple,
    fan medallions. Not no. 40."""
    m, f, L = _shell(ring, holes, lm, "brick_cream", 13.2, 15.2)
    cell(m, f, 0.0, L, 0.8, 13.2, None, 0.0, 0.0, "brick_cream")
    left = L * 0.62
    _win(m, f, 0.25, left - 0.12, 1.0, 3.7, "horseshoe", "brick_cream", "glass", "stone_grey")
    _grille(m, f, 0.45, left - 0.28, 1.2, 3.4, circle=True)
    _win(m, f, L * 0.7, L - 0.18, 1.0, 3.05, "rect", "brick_cream", "door", "bluestone")
    for s in (-0.16, 0.16):
        disc = opening(L * 0.82 + s, 3.38, 0.28, 3.38, "circle", 5)
        profile_slab(m, f, disc, 0.04, 0.12, "gold")
    _balcony(m, f, 0.18, L - 0.14, 4.05)
    bay = (L - 0.5) / 3
    for i in range(3):
        a0 = 0.25 + i * bay
        _win(m, f, a0, a0 + bay - 0.12, 4.45, 7.55, "rect", "brick_cream", "glass", "stone_grey", divide="sash")
        _win(m, f, a0, a0 + bay - 0.12, 8.05, 11.35, "round", "brick_cream", "glass", "stone_grey")
    _fans(m, f, 0.15, L - 0.15, 11.55)
    _cornice(m, f, 0.0, L, 12.85)
    return m


def build_benoit_38(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Peter Benoitstraat 38. Yellow brick, two unequal bays. Wide bay: dark stone
    shopfront, the only balcony, rose-pruner mosaics, pointed gable. Narrow bay:
    pedimented door and a stack of windows."""
    m, f, L = _shell(ring, holes, lm, "brick_yellow", 11.0, 13.2)
    cell(m, f, 0.0, L, 0.8, 11.0, None, 0.0, 0.0, "brick_yellow")
    wide = L * 0.66
    for z in (4.2, 7.55):
        _course(m, f, 0.15, L - 0.1, z, "brick", 0.1)
    for x in (0.12, wide):
        rbox(m, f, x - 0.09, x + 0.09, -0.02, 0.14, 0.75, 12.55, "stone_grey")
    rbox(m, f, 0.2, wide - 0.08, -0.02, 0.18, 0.75, 4.05, "stone_grey", skip=("bottom",))
    _win(m, f, 0.4, wide - 0.35, 1.0, 3.75, "rect", "stone_grey", "glass", "bluestone")
    _grille(m, f, 0.55, wide - 0.5, 1.15, 3.45)
    _balcony(m, f, 0.32, wide - 0.22, 4.15)
    _win(m, f, 0.45, wide - 0.35, 4.55, 7.25, "round", "brick_yellow", "glass", "stone_grey")
    _pruner(m, f, 0.4, wide * 0.52, 7.4, 8.35)
    _pruner(m, f, wide * 0.54, wide - 0.3, 7.4, 8.35)
    half = (wide - 0.85) / 2
    for i in range(2):
        a0 = 0.42 + i * half
        _win(m, f, a0, a0 + half - 0.12, 8.55, 10.7, "round", "brick_yellow", "glass", "stone_grey")
    gc = wide * 0.48
    rbox(m, f, 0.28, wide - 0.12, -0.02, 0.26, 10.9, 12.7, "brick_yellow", skip=("bottom",))
    _win(m, f, gc - 0.32, gc + 0.32, 11.15, 12.4, "rect", "brick_yellow", "glass")
    profile_slab(m, f, [(0.18, 12.7), (wide - 0.05, 12.7), (gc, 16.2)], -0.02, 0.3, "stone_grey", back=True)
    rbox(m, f, gc - 0.06, gc + 0.06, 0.08, 0.28, 16.2, 16.7, "stone_white")
    na0, na1 = wide + 0.18, L - 0.14
    _win(m, f, na0, na1, 0.95, 3.25, "rect", "brick_yellow", "door", "stone_grey")
    profile_slab(m, f, [(na0 - 0.04, 3.3), (na1 + 0.04, 3.3), ((na0 + na1) * 0.5, 4.15)], 0.0, 0.14, "stone_grey", back=True)
    _win(m, f, na0 + 0.04, na1 - 0.04, 4.45, 7.05, "rect", "brick_yellow", "glass", "stone_grey", divide="sash")
    _pruner(m, f, na0, na1, 7.2, 8.05)
    _win(m, f, na0 + 0.04, na1 - 0.04, 8.25, 10.55, "round", "brick_yellow", "glass", "stone_grey")
    _cornice(m, f, wide + 0.05, L, 10.9)
    return m


def build_benoit_40(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Peter Benoitstraat 40. Pale brick like 34, but an iron shopfront instead of
    a horseshoe, red relieving arches, and a swallow frieze."""
    m, f, L = _shell(ring, holes, lm, "brick_cream", 13.2, 15.2)
    cell(m, f, 0.0, L, 0.85, 13.2, None, 0.0, 0.0, "brick_cream")
    shop1 = L * 0.6
    _win(m, f, 0.28, shop1, 1.15, 3.85, "rect", "brick_cream", "glass", "bluestone")
    _grille(m, f, 0.45, shop1 - 0.15, 1.35, 3.45)
    rbox(m, f, 0.28, shop1, 0.06, 0.18, 3.7, 3.95, "iron")
    for t in (0.2, 0.5, 0.8):
        x = 0.28 + (shop1 - 0.28) * t
        disc = opening(x, 3.82, 0.22, 3.82, "circle", 5)
        profile_slab(m, f, disc, 0.14, 0.22, "gold")
    _win(m, f, L * 0.68, L - 0.2, 1.05, 3.15, "rect", "brick_cream", "glass_blue", "bluestone")
    rbox(m, f, L * 0.72, L - 0.28, 0.04, 0.1, 3.15, 3.55, "glass_amber")
    # yellow-blue whiplash under the balcony, between the consoles
    rbox(m, f, 0.35, L - 0.3, 0.02, 0.08, 3.95, 4.35, "glass_blue")
    _petal(m, f, L * 0.35, 4.15, [(0.0, 0.12), (0.35, 0.0), (-0.35, 0.0)], 0.09, "gold")
    _balcony(m, f, 0.22, L - 0.16, 4.4)
    bay = (L - 0.55) / 3
    for i in range(3):
        a0 = 0.28 + i * bay
        a1 = a0 + bay - 0.12
        ca = (a0 + a1) * 0.5
        _win(m, f, a0, a1, 4.75, 7.35, "rect", "brick_cream", "glass", "stone_grey", divide="sash")
        arch = arch_points(ca, 7.3, (a1 - a0) * 0.48, "segmental", 4, 0.28)
        band(m, f, arch, [(x, z + 0.1) for x, z in arch], -0.01, 0.08, "brick", (ca, 7.15))
        rbox(m, f, ca - 0.28, ca + 0.28, 0.02, 0.08, 7.45, 8.05, "glass_blue")
        _petal(m, f, ca, 7.75, [(0.0, 0.16), (0.18, 0.0), (-0.18, 0.0)], 0.09, "gold")
        _win(m, f, a0, a1, 8.3, 11.55, "round", "brick_cream", "glass", "stone_grey")
    _birds(m, f, 0.2, L - 0.2, 11.75)
    _cornice(m, f, 0.0, L, 12.9)
    return m


def build_bonifacius(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Sint-Bonifaciuskerk from Grétrystraat. Square banded tower on the left of
    the photograph, one traceried west window, round stair turret on the right.
    No spire. The west front is the whole street line (~17 m), not the 9 m run
    OSM stored as a single edge — that short run left the rest of the wall as a hole."""
    m = Mesh()
    raw, outline, _width, depth, edge = _on_street(ring, lm)
    locs = [raw.local(*p) for p in outline]
    near = [a for a, d in locs if -1.2 <= d <= 2.5]
    span0, span1 = (min(near), max(near)) if near else (0.0, edge.length)
    W = max(8.0, span1 - span0)
    # a=0 is the left of the Grétrystraat photograph (the tower).
    f = _present(raw.shifted(span0, 0.0), W)
    aisle = 12.2
    # Street-side jogs are not a second wall in front of the tower. The flat skin
    # covers them; only the nave walls, well behind the west front, stay extruded.
    extrude_ring(m, outline, holes, 0.0, aisle, "brick", None, skip=_near_street(edge, raw))
    cell(m, f, 0.05, W - 0.05, 0.15, 15.0, None, 0.0, 0.0, "brick")
    tw = min(4.3, W * 0.26)
    tw0, tw1 = 0.25, 0.25 + tw
    th = 21.6
    rbox(m, f, tw0, tw1, -0.15, 0.55, 0.0, th, "brick", skip=("+d", "bottom"))
    tf = f.shifted(0.0, 0.55)
    for z in (0.15, 5.2, 10.0, 15.0, th - 0.35):
        _course(m, tf, tw0 + 0.12, tw1 - 0.12, z, "stone_white", 0.22)
    _win(m, tf, tw0 + 0.45, tw1 - 0.45, 0.35, 3.6, "pointed", "brick", "door", "stone_white")
    profile_slab(m, tf, [(tw0 + 0.3, 3.7), (tw1 - 0.3, 3.7), ((tw0 + tw1) * 0.5, 5.5)], -0.02, 0.16, "stone_white", back=True)
    med = opening((tw0 + tw1) * 0.5, 4.55, 0.7, 4.55, "circle", 6)
    profile_slab(m, tf, med, 0.1, 0.2, "stone_white")
    _win(m, tf, tw0 + 0.7, tw1 - 0.7, 6.0, 9.4, "pointed", "brick", "glass_dark", "stone_white", divide="mullion")
    bca = (tw0 + tw1) * 0.5
    for s in (-0.85, 0.85):
        _win(m, tf, bca + s - 0.55, bca + s + 0.55, 15.4, 19.2, "pointed", "brick", "glass_dark", "stone_white")
    rbox(m, f, tw0 - 0.08, tw1 + 0.08, -0.25, 0.7, th, th + 0.28, "bluestone")
    for a in (tw0 + 0.35, bca, tw1 - 0.35):
        rbox(m, tf, a - 0.06, a + 0.06, -0.12, 0.06, th, th + 0.7, "stone_white")
    for a, d in ((tw0 + 0.4, 0.35), (tw1 - 0.4, 0.35), (tw0 + 0.4, -0.05), (tw1 - 0.4, -0.05)):
        x, y, _ = f.p(a, d, 0.0)
        _pinnacle(m, x, y, th + 0.2, 2.05)
    # round stair turret on the right, shorter than the tower, slate cone
    tr = 1.35
    ta = W - tr - 0.55
    tx, ty, _ = f.p(ta, 0.45, 0.0)
    cylinder(m, tx, ty, 0.0, 16.2, tr, 10, "brick", top=False)
    for z in (4.2, 8.4, 12.4):
        cylinder(m, tx, ty, z, z + 0.18, tr + 0.08, 10, "stone_white")
    frustum(m, tx, ty, 16.2, 19.2, tr + 0.06, 0.08, 10, "slate")
    # the west window fills the wall between the tower and the turret
    g0, g1 = tw1 + 0.35, ta - tr - 0.4
    if g1 - g0 < 2.4:
        g0, g1 = tw1 + 0.2, min(W * 0.7, tw1 + 4.0)
    gc = (g0 + g1) * 0.5
    _tracery(m, f, gc, 2.4, g1 - g0 - 0.35, 12.6, "brick")
    profile_slab(m, f, [(g0, 13.0), (g1, 13.0), (gc, 15.4)], -0.15, 0.14, "brick", back=True)
    band(
        m, f,
        [(g0, 13.0), (gc, 15.4), (g1, 13.0)],
        [(g0 - 0.1, 12.85), (gc, 15.65), (g1 + 0.1, 12.85)],
        -0.04, 0.16, "stone_white", (gc, 13.0),
    )
    _cross(m, f, gc, 0.05, 15.5, 1.05)
    gable_roof(
        m, f, g0 - 0.15, g1 + 0.15, -min(depth, 22.0), -0.25,
        aisle, aisle + 3.8, "slate", ridge="d", gable_mat="brick", overhang=0.15,
    )
    return m


def build_heilig_hart(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Basiliek van het Heilig Hart, De Merodelei gable. Stair turret on the left,
    triple lancet, porch with its roof below the window, bellcote spire above.
    Not a pair of floating slabs."""
    m = Mesh()
    wall, outline, L, depth, edge = _on_street(ring, lm)
    f = _present(wall, L)
    eaves = 14.6
    _body(m, outline, holes, eaves, "brick", edge)
    g0, g1 = 2.15, L - 0.35
    if g1 - g0 < 4.5:
        g0, g1 = 0.4, L - 0.2
    gc = (g0 + g1) * 0.5
    gable_roof(
        m, f, g0, g1, -min(depth, 24.0), -0.2,
        eaves, eaves + 5.2, "slate", ridge="d", gable_mat="brick", overhang=0.12,
    )
    cell(m, f, g0, g1, 0.15, eaves + 5.6, None, 0.0, 0.0, "brick")
    # bands stop either side of the window
    for z in (3.4, 6.5, 11.6):
        _course(m, f, g0, gc - 1.55, z)
        _course(m, f, gc + 1.55, g1, z)
    # stair turret, photo left, shorter than the bellcote
    tr = 1.25
    ta = 1.15
    tx, ty, _ = f.p(ta, 0.15, 0.0)
    cylinder(m, tx, ty, 0.0, eaves + 0.4, tr, 8, "brick", top=False)
    for z in (3.8, 7.6, 11.4):
        cylinder(m, tx, ty, z, z + 0.18, tr + 0.08, 8, "stone_white")
    rbox(m, f, ta - 0.35, ta + 0.28, -0.05, 0.35, 6.4, 8.3, "stone_white")
    frustum(m, tx, ty, eaves + 0.4, eaves + 6.2, tr + 0.05, 0.06, 8, "slate")
    _cross(m, f, ta, 0.15, eaves + 6.2, 1.05)
    # projecting porch, roof finishes below the lancets
    pw = min(3.2, (g1 - g0) * 0.48)
    p0 = gc - pw * 0.5
    rbox(m, f, p0, p0 + pw, 0.0, 1.35, 0.0, 4.6, "stone_white", skip=("+d", "bottom", "top"))
    pf = f.shifted(0.0, 1.35)
    _win(m, pf, p0 + 0.35, p0 + pw - 0.35, 0.25, 3.15, "pointed", "stone_white", "door", "bluestone")
    profile_slab(m, pf, [(p0 + 0.25, 3.1), (p0 + pw - 0.25, 3.1), (gc, 4.15)], 0.0, 0.12, "stone_grey", back=True)
    profile_slab(m, f, [(p0 - 0.05, 4.55), (p0 + pw + 0.05, 4.55), (gc, 6.15)], 0.35, 1.4, "slate", back=True)
    for s in (-1.0, 1.0):
        rbox(m, f, gc + s * (pw * 0.5 + 0.15), gc + s * (pw * 0.5 + 0.15) + 0.16 * s, 0.2, 0.9, 0.0, 0.35, "bluestone")
    # triple lancet under one pointed arch
    win_w = min(3.1, (g1 - g0) * 0.42)
    z_win, z_top = 6.7, 13.6
    outer = opening(gc, z_win - 0.15, win_w + 0.7, z_win + (z_top - z_win) * 0.45, "pointed", 6)
    archivolt(m, f, outer, 0.16, 0.02, 0.22, "stone_white")
    side = win_w * 0.26
    _win(m, f, gc - win_w * 0.5, gc - win_w * 0.5 + side, z_win, z_win + (z_top - z_win) * 0.62, "pointed", "brick", "glass", "stone_white")
    _win(m, f, gc - side * 0.7, gc + side * 0.7, z_win, z_top, "pointed", "brick", "glass_blue", "stone_white", divide="mullion")
    _win(m, f, gc + win_w * 0.5 - side, gc + win_w * 0.5, z_win, z_win + (z_top - z_win) * 0.62, "pointed", "brick", "glass", "stone_white")
    eye = opening(gc, eaves + 1.3, 0.85, eaves + 1.3, "circle", 6)
    profile_slab(m, f, eye, 0.02, 0.1, "stone_white")
    profile_slab(m, f, [(g0, eaves), (g1, eaves), (gc, eaves + 5.8)], -0.25, 0.12, "brick", back=True)
    band(
        m, f,
        [(g0, eaves), (gc, eaves + 5.8), (g1, eaves)],
        [(g0 + 0.1, eaves + 0.05), (gc, eaves + 6.05), (g1 - 0.1, eaves + 0.05)],
        -0.02, 0.16, "stone_white", (gc, eaves),
    )
    for a in (g0 + 0.25, g1 - 0.25):
        x, y, _ = f.p(a, 0.1, 0.0)
        _pinnacle(m, x, y, eaves + 0.3, 1.6)
    # bellcote, the taller spire
    rbox(m, f, gc - 0.5, gc + 0.5, -0.35, 0.15, eaves + 5.3, eaves + 7.6, "stone_white", skip=("bottom",))
    _win(m, f, gc - 0.32, gc + 0.32, eaves + 5.6, eaves + 7.3, "pointed", "stone_white", "glass_dark", "stone_white")
    px, py, _ = f.p(gc, -0.1, 0.0)
    frustum(m, px, py, eaves + 7.6, eaves + 11.4, 0.62, 0.04, 6, "slate")
    _cross(m, f, gc, -0.1, eaves + 11.4, 1.2)
    # low door on the right, the side chapel, not a second church front
    _win(m, f, L - 1.35, L - 0.45, 0.3, 2.6, "pointed", "brick", "door", "stone_white")
    return m


def _convent_front(m: Mesh, f: Frame, L: float) -> None:
    """Long red-brick convent wall: rectangular windows in round recesses, a corbel
    table, and a few steep gables. Not a rank of church lancets."""
    H = 10.2
    cell(m, f, 0.0, L, 0.2, H, None, 0.0, 0.0, "brick")
    _course(m, f, 0.0, L, 0.0, "bluestone", 0.55)
    _course(m, f, 0.0, L, 3.85, "stone_white", 0.12)
    _course(m, f, 0.0, L, 7.15, "stone_white", 0.12)
    n = max(8, int(L / 0.5))
    for i in range(n):
        x = L * (i + 0.5) / n
        rbox(m, f, x - 0.055, x + 0.055, -0.02, 0.16, H - 0.42, H - 0.08, "brick_dark")
    bays = max(3, int(round(L / 3.7)))
    bw = L / bays
    for i in range(bays):
        a0 = i * bw + bw * 0.16
        a1 = (i + 1) * bw - bw * 0.16
        if i == 0:
            _win(m, f, a0 - 0.1, a1 + 0.1, 0.7, 3.35, "segmental", "brick", "door", "stone_white")
        elif i == bays - 2:
            _win(m, f, (a0 + a1) * 0.5 - 0.55, (a0 + a1) * 0.5 + 0.55, 0.7, 3.4, "pointed", "brick", "door", "stone_white")
        elif i % 2 == 0:
            mid = (a0 + a1) * 0.5
            _win(m, f, a0, mid - 0.06, 1.05, 3.35, "rect", "brick", "glass", "stone_white")
            _win(m, f, mid + 0.06, a1, 1.05, 3.35, "rect", "brick", "glass", "stone_white")
        else:
            _win(m, f, a0, a1, 1.0, 3.4, "rect", "brick", "glass", "stone_white")
        _win(m, f, a0, a1, 4.15, 6.85, "round", "brick", "glass", "stone_white")
        # rectangular sash inside the round recess
        ix0, ix1 = a0 + (a1 - a0) * 0.2, a1 - (a1 - a0) * 0.2
        rbox(m, f, ix0, ix0 + 0.05, 0.1, 0.16, 4.45, 6.3, "frame_dark")
        rbox(m, f, ix1 - 0.05, ix1, 0.1, 0.16, 4.45, 6.3, "frame_dark")
        rbox(m, f, ix0, ix1, 0.1, 0.16, 6.2, 6.28, "frame_dark")
        if i % 3 == 1:
            ca = (a0 + a1) * 0.5
            rbox(m, f, a0 - 0.05, a1 + 0.05, -0.08, 0.28, H, H + 2.15, "brick", skip=("bottom",))
            _win(m, f, ca - 0.38, ca + 0.38, H + 0.35, H + 1.7, "round", "brick", "glass_dark", "stone_white")
            profile_slab(
                m, f,
                [(a0 - 0.15, H + 2.15), (a1 + 0.15, H + 2.15), (ca, H + 3.7)],
                -0.08, 0.32, "brick", back=True,
            )
            rbox(m, f, ca - 0.05, ca + 0.05, 0.05, 0.3, H + 3.7, H + 4.25, "stone_white")
        else:
            _win(m, f, a0 + 0.08, a1 - 0.08, 7.45, 9.7, "rect", "brick", "glass", "stone_white")


def build_heilig_hart_klooster(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Klooster along De Merodelei: a long brick block with gables and a corbel
    table. The basilica's spires stay on the basilica."""
    m = Mesh()
    edges = _street_edges(ring, lm)
    primary = max(edges, key=lambda e: e.length)
    _wall, outline, _w, depth, edge = _on_street(ring, lm)
    _body(m, outline, holes, 10.2, "brick", edge)
    pf = _present(_wall_frame(primary.frame(), primary), primary.length)
    hip_roof(m, pf, 0.2, primary.length - 0.2, -min(depth, 16.0), 0.15, 10.2, 13.4, "slate", overhang=0.25)
    for e in edges:
        ef = _present(_wall_frame(e.frame(), e), e.length)
        _convent_front(m, ef, e.length)
    return m


BUILDERS = {
    "harmonie_koetshuis": build_harmonie_koetshuis,
    "benoit_34": build_benoit_34,
    "benoit_38": build_benoit_38,
    "benoit_40": build_benoit_40,
    "bonifacius": build_bonifacius,
    "heilig_hart": build_heilig_hart,
    "heilig_hart_klooster": build_heilig_hart_klooster,
}

