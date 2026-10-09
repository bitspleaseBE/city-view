"""Hand-modelled landmark builders (pure Python, no bpy).

Each builder takes the OSM footprint (local metres, holes included) plus the manifest
``landmark`` dict and returns a :class:`landmark_kit.Mesh` in world coordinates. The
proportions come from the Flemish heritage inventory descriptions and Wikimedia
Commons photographs listed in ``assets/landmarks/manifest.json``; everything is real
geometry with tiling materials, no photographs.

Footprint frames are derived from the surveyed ``anchor`` (front door) so the facades
follow OSM if the outline is redrawn; detail positions inside a facade are relative
to that frame.
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
    box,
    cell,
    centroid,
    clip_ring_halfplane,
    cylinder,
    extrude_ring,
    front_edge,
    frustum,
    gable_roof,
    hip_roof,
    merged_edges,
    offset_ring,
    opening,
    opening_top,
    oriented,
    pane,
    post,
    prism,
    profile_slab,
    pyramid,
    rbox,
    ring_edges,
    ring_roof,
    skin_edges,
)

# Triangle budgets (tests hold every builder to these).
TRI_BUDGET = {
    "zas_vincentius": 60000,
    "feestzaal_harmonie": 40000,
    "art_deco_ms123": 15000,
    "gulden_spoor": 15000,
    "gulden_spoor_gate": 6000,
    "albertpark_kiosk": 12000,
    "benoit_monument": 3000,
}


# ------------------------------------------------------------------------ helpers


def _dot(a: Vec2, b: Vec2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _covered(segs: list[Edge], tol: float = 0.3):
    """Predicate for ``extrude_ring(skip=)``: ring edges lying on a skinned facade run."""

    def on(e: Edge) -> bool:
        for s in segs:
            ux, uy = s.p1[0] - s.p0[0], s.p1[1] - s.p0[1]
            ln = math.hypot(ux, uy) or 1.0
            ux, uy = ux / ln, uy / ln
            ok = True
            for p in (e.p0, e.p1):
                dx, dy = p[0] - s.p0[0], p[1] - s.p0[1]
                t = dx * ux + dy * uy
                if abs(dx * uy - dy * ux) > tol or t < -tol or t > ln + tol:
                    ok = False
                    break
            if ok:
                return True
        return False

    return on


def _world_ring(f: Frame, pts: list[Vec2]) -> list[Vec2]:
    return [f.p(a, d, 0.0)[:2] for a, d in pts]


def _clean(ring: list[Vec2], eps: float = 0.05) -> list[Vec2]:
    out: list[Vec2] = []
    for p in ring:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def window_cell(
    m: Mesh,
    f: Frame,
    a0: float,
    a1: float,
    z0: float,
    z1: float,
    hole,
    wall: str,
    reveal: str,
    depth: float,
    glass: str = "glass",
    sill: str | None = None,
    d_front: float = 0.0,
) -> None:
    """Wall panel with an opening, its reveal, the glass at the back and a sill."""
    cell(m, f, a0, a1, z0, z1, hole, d_front, d_front - depth, wall, reveal)
    if hole:
        pane(m, f, hole, d_front - depth, glass)
        if sill:
            xs = [p[0] for p in hole]
            zb = min(p[1] for p in hole)
            rbox(m, f, min(xs) - 0.08, max(xs) + 0.08, d_front - 0.02, d_front + 0.1, zb - 0.12, zb, sill, skip=("-d",))


def glazing_bars(m: Mesh, f: Frame, hole, d: float, mat: str, transom: float | None = None, mullions: int = 1) -> None:
    xs = [p[0] for p in hole]
    zs = [p[1] for p in hole]
    a0, a1, zb = min(xs), max(xs), min(zs)
    top = transom if transom is not None else max(zs)
    for k in range(mullions):
        x = a0 + (a1 - a0) * (k + 1) / (mullions + 1)
        rbox(m, f, x - 0.035, x + 0.035, d, d + 0.05, zb, top, mat)
    if transom is not None:
        rbox(m, f, a0, a1, d, d + 0.05, transom - 0.035, transom + 0.035, mat)


def lyre(m: Mesh, f: Frame, ca: float, z0: float, h: float, d0: float, d1: float, mat: str, strings: int = 4) -> None:
    """Lyre relief / finial in the (a, z) plane of ``f``."""
    segs = 6
    arm = 0.055 * h
    left_in, left_out = [], []
    for i in range(segs + 1):
        t = i / segs
        x = 0.13 * h + 0.11 * h * math.sin(math.pi * t * 0.85)
        z = z0 + 0.1 * h + 0.82 * h * t
        left_in.append((ca - x, z))
        left_out.append((ca - x - arm, z))
    centre = (ca, z0 + 0.5 * h)
    band(m, f, left_in, left_out, d0, d1, mat, centre)
    band(m, f, [(2 * ca - x, z) for x, z in left_out], [(2 * ca - x, z) for x, z in left_in], d0, d1, mat, centre)
    rbox(m, f, ca - 0.2 * h, ca + 0.2 * h, d0, d1, z0, z0 + 0.11 * h, mat)
    xs = left_in[-1][0] - arm
    rbox(m, f, xs - 0.02 * h, 2 * ca - xs + 0.02 * h, d0, d1, z0 + 0.8 * h, z0 + 0.86 * h, mat)
    for k in range(strings):
        x = ca + (k - (strings - 1) * 0.5) * 0.06 * h
        dm = (d0 + d1) * 0.5
        rbox(m, f, x - 0.006 * h, x + 0.006 * h, dm - 0.01, dm + 0.01, z0 + 0.11 * h, z0 + 0.8 * h, mat)


def cross(m: Mesh, f: Frame, ca: float, z0: float, h: float, d: float, mat: str) -> None:
    t = max(0.06, h * 0.11)
    rbox(m, f, ca - t * 0.5, ca + t * 0.5, d - t * 0.5, d + t * 0.5, z0, z0 + h, mat)
    rbox(m, f, ca - h * 0.32, ca + h * 0.32, d - t * 0.5, d + t * 0.5, z0 + h * 0.6, z0 + h * 0.6 + t, mat)


def statue(m: Mesh, f: Frame, ca: float, d: float, z0: float, h: float, mat: str = "stone_white") -> None:
    """Niche figure: draped body, shoulders, head (reads as a statue at 20 m)."""
    x, y, _ = f.p(ca, d, 0.0)
    r = h * 0.15
    frustum(m, x, y, z0, z0 + h * 0.15, r * 1.25, r * 1.2, 8, mat, bottom=False)
    frustum(m, x, y, z0 + h * 0.15, z0 + h * 0.72, r * 1.2, r * 0.95, 8, mat, top=False)
    frustum(m, x, y, z0 + h * 0.72, z0 + h * 0.8, r * 0.95, r * 0.45, 8, mat, top=False)
    frustum(m, x, y, z0 + h * 0.8, z0 + h, r * 0.55, r * 0.3, 8, mat)


# ------------------------------------------------------------------- ZAS Sint-Vincentius


ZAS_H = 15.2  # wings: three storeys + mezzanine of oculi


def _zas_wing_skin(m: Mesh, f: Frame, L: float) -> None:
    """Historic neo-Gothic wing: diminishing round-arched windows, oculi, corbel table."""
    bays = max(1, round(L / 3.15))
    bw = L / bays
    rbox(m, f, 0.0, L, -0.05, 0.12, 0.0, 0.9, "bluestone", skip=("-d", "bottom"))
    rows = [
        (0.9, 5.0, lambda c: opening(c, 1.7, 1.3, 3.75, "round", 6)),
        (5.0, 5.2, None),
        (5.2, 9.2, lambda c: opening(c, 5.9, 1.3, 7.9, "round", 6)),
        (9.2, 9.4, None),
        (9.4, 12.4, lambda c: opening(c, 9.9, 1.2, 11.3, "round", 6)),
        (12.4, 14.2, lambda c: opening(c, 12.9, 0.8, 0.0, "circle", 5)),
        (14.2, ZAS_H, None),
    ]
    for i in range(bays):
        b0 = i * bw
        ca = b0 + bw * 0.5
        for z0, z1, mk in rows:
            hole = mk(ca) if mk else None
            window_cell(m, f, b0, b0 + bw, z0, z1, hole, "brick", "brick_dark", 0.3, sill="stone_white" if hole and z0 < 12 else None)
            if hole and z0 < 12:
                archivolt(m, f, hole, 0.14, 0.0, 0.08, "brick_dark")
    for z in (5.0, 9.2):
        rbox(m, f, 0.0, L, 0.0, 0.12, z, z + 0.2, "stone_white", skip=("-d",))
    n = max(1, int(L / 0.62))
    for k in range(n):
        x = (k + 0.5) * L / n
        rbox(m, f, x - 0.14, x + 0.14, 0.0, 0.16, 13.95, 14.25, "brick_dark", skip=("-d",))
    rbox(m, f, 0.0, L, 0.0, 0.2, 14.25, 14.6, "brick_dark", skip=("-d",))
    rbox(m, f, -0.05, L + 0.05, 0.0, 0.38, 14.6, ZAS_H + 0.05, "brick_dark", skip=("-d",))


def _zas_plain_skin(m: Mesh, f: Frame, L: float) -> None:
    """Later hospital blocks: brick with regular rectangular windows."""
    bays = max(1, round(L / 3.6))
    bw = L / bays
    storey = ZAS_H / 4.0
    for i in range(bays):
        b0 = i * bw
        ca = b0 + bw * 0.5
        w = min(1.6, bw - 0.9)
        for s in range(4):
            z0 = s * storey
            hole = opening(ca, z0 + 1.0, w, z0 + 2.9, "rect") if w > 0.5 else None
            window_cell(m, f, b0, b0 + bw, z0, z0 + storey, hole, "brick", "brick_dark", 0.18)
    rbox(m, f, 0.0, L, -0.05, 0.1, 0.0, 0.6, "bluestone", skip=("-d", "bottom"))
    rbox(m, f, 0.0, L, 0.0, 0.25, ZAS_H - 0.4, ZAS_H + 0.05, "brick_dark", skip=("-d",))


def _zas_front(m: Mesh, f: Frame, W: float, depth: float) -> None:
    """Chapel risalit: portal, traceried window, statue niches, three mitre gables."""
    sb = W * 0.28
    cw = W - 2 * sb
    ca = W * 0.5
    eave = 20.4
    rbox(m, f, 0.0, W, -0.05, 0.14, 0.0, 0.9, "bluestone", skip=("-d", "bottom"))
    # side bays
    for b0 in (0.0, W - sb):
        c = b0 + sb * 0.5
        rows = [
            (0.9, 5.6, opening(c, 1.8, 1.3, 3.9, "round", 6), "glass", 0.3),
            (5.6, 5.85, None, None, 0.0),
            (5.85, 11.0, opening(c, 6.6, 1.3, 9.4, "round", 6), "glass", 0.3),
            (11.0, 16.6, opening(c, 12.0, 1.5, 15.0, "round", 6), "brick_dark", 0.45),
            (16.6, eave, opening(c, 17.8, 0.9, 0.0, "circle", 6), "glass", 0.25),
        ]
        for z0, z1, hole, g, dep in rows:
            window_cell(m, f, b0, b0 + sb, z0, z1, hole, "brick", "brick_dark", dep, glass=g or "glass")
            if hole and z0 < 16:
                archivolt(m, f, hole, 0.16, 0.0, 0.12, "stone_white")
        statue(m, f, c, -0.24, 12.05, 2.2)
        rbox(m, f, c - 0.5, c + 0.5, -0.45, 0.2, 11.85, 12.05, "stone_white", skip=("-d",))
    # centre bay: portal, window, niche with the Holy Family
    a0, a1 = sb, W - sb
    portal = opening(ca, 0.9, min(2.6, cw * 0.45), 3.9, "round", 8)
    window_cell(m, f, a0, a1, 0.9, 5.6, portal, "brick", "stone_white", 0.6, glass="door")
    archivolt(m, f, portal, 0.4, 0.0, 0.25, "stone_white")
    rbox(m, f, a0, a1, -0.02, 0.12, 5.6, 5.85, "brick", skip=("-d",))
    win_w = min(4.2, cw * 0.7)
    win = opening(ca, 6.6, win_w, 11.9, "round", 10)
    window_cell(m, f, a0, a1, 5.85, 14.4, win, "brick", "stone_white", 0.5)
    archivolt(m, f, win, 0.35, 0.0, 0.25, "stone_white")
    lw = win_w / 3.0
    for k in (-1, 1):
        x = ca + k * lw * 0.5
        rbox(m, f, x - 0.08, x + 0.08, -0.5, -0.3, 6.6, 11.3, "stone_white")
    rbox(m, f, ca - win_w * 0.5, ca + win_w * 0.5, -0.5, -0.3, 9.1, 9.28, "stone_white")
    for k in (-1, 0, 1):
        c = ca + k * lw
        inner = arch_points(c, 11.0, lw * 0.5 - 0.1, "round", 6)
        outer = [(x, z + 0.14) for x, z in inner]
        band(m, f, inner, outer, -0.5, -0.3, "stone_white", (c, 11.0))
    rose_c = (ca, 12.95)
    ring_in = [(rose_c[0] + 0.55 * math.cos(t * math.tau / 12), rose_c[1] + 0.55 * math.sin(t * math.tau / 12)) for t in range(13)]
    ring_out = [(rose_c[0] + 0.7 * math.cos(t * math.tau / 12), rose_c[1] + 0.7 * math.sin(t * math.tau / 12)) for t in range(13)]
    band(m, f, ring_in, ring_out, -0.5, -0.3, "stone_white", rose_c)
    niche = opening(ca, 15.3, 1.9, 18.0, "round", 8)
    window_cell(m, f, a0, a1, 14.4, eave, niche, "brick", "brick_dark", 0.5, glass="brick_dark")
    archivolt(m, f, niche, 0.2, 0.0, 0.14, "stone_white")
    rbox(m, f, ca - 0.85, ca + 0.85, -0.5, 0.22, 15.1, 15.3, "stone_white", skip=("-d",))
    for k, h in ((-0.55, 2.0), (0.0, 2.35), (0.55, 1.6)):
        statue(m, f, ca + k, -0.25, 15.3, h)
    # buttress lisenes with pinnacles, string course, corbel frieze
    for x0, x1 in ((0.0, 0.55), (sb - 0.3, sb + 0.3), (W - sb - 0.3, W - sb + 0.3), (W - 0.55, W)):
        rbox(m, f, x0, x1, 0.0, 0.38, 0.9, eave + 0.4, "brick", skip=("-d", "bottom"))
        for z in (5.6, 11.0, 16.6):
            rbox(m, f, x0 - 0.04, x1 + 0.04, 0.0, 0.44, z, z + 0.18, "stone_white", skip=("-d",))
        xm = (x0 + x1) * 0.5
        px, py, _ = f.p(xm, 0.19, 0.0)
        frustum(m, px, py, eave + 0.4, eave + 1.9, 0.3, 0.0, 4, "stone_white", phase=math.pi / 4)
    rbox(m, f, 0.0, W, 0.0, 0.16, 5.6, 5.85, "stone_white", skip=("-d",))
    n = max(1, int(W / 0.5))
    for k in range(n):
        x = (k + 0.5) * W / n
        rbox(m, f, x - 0.12, x + 0.12, 0.0, 0.2, 19.75, 20.05, "brick_dark", skip=("-d",))
    rbox(m, f, 0.0, W, 0.0, 0.26, 20.05, eave, "brick_dark", skip=("-d",))
    # upper risalit walls and roof, then the three gables in front of it
    rbox(m, f, 0.0, W, -depth, 0.0, ZAS_H - 0.1, eave, "brick", skip=("+d", "bottom", "top"))
    ridge = 22.4

    def roof_z(a: float) -> float:
        return eave + (ridge - eave) * (1.0 - abs(a - ca) / ca)

    gable_roof(m, f, 0.0, W, -depth, 0.0, eave, ridge, "slate", ridge="d", gable_mat="brick", overhang=0.15)
    centre_gable = [(a0, eave), (a1, eave), (a1, roof_z(a1) + 0.2), (ca, 24.6), (a0, roof_z(a0) + 0.2)]
    profile_slab(m, f, centre_gable, -0.6, 0.14, "brick", back=True)
    band(m, f, [(a0 - 0.05, roof_z(a0) + 0.2), (ca, 24.6), (a1 + 0.05, roof_z(a1) + 0.2)],
         [(a0 - 0.05, roof_z(a0) + 0.5), (ca, 24.95), (a1 + 0.05, roof_z(a1) + 0.5)], -0.65, 0.26, "stone_white", (ca, eave))
    cross(m, f, ca, 24.9, 1.7, -0.2, "stone_white")
    for b0 in (0.0, W - sb):
        c = b0 + sb * 0.5
        tri = [(b0, eave), (b0 + sb, eave), (c, 23.0)]
        profile_slab(m, f, tri, -0.6, 0.14, "brick", back=True)
        band(m, f, [(b0, eave), (c, 23.0), (b0 + sb, eave)], [(b0, eave + 0.28), (c, 23.3), (b0 + sb, eave + 0.28)], -0.65, 0.24, "stone_white", (c, eave - 0.5))
        cross(m, f, c, 23.25, 1.1, -0.2, "stone_white")
    # open-work bell turret with slate spire on the ridge behind the gables
    tx, ty, _ = f.p(ca, -depth * 0.55, 0.0)
    tf = f.shifted(ca, -depth * 0.55)
    rbox(m, tf, -0.85, 0.85, -0.85, 0.85, ridge - 0.6, 24.5, "slate")
    rbox(m, tf, -0.95, 0.95, -0.95, 0.95, 24.5, 24.7, "stone_white")
    for k in range(8):
        t = math.tau * k / 8 + math.pi / 8
        post(m, tx + 0.72 * math.cos(t), ty + 0.72 * math.sin(t), 24.7, 27.3, 0.07, "stone_white")
    frustum(m, tx, ty, 24.7, 26.4, 0.3, 0.3, 6, "frame_dark")
    frustum(m, tx, ty, 27.3, 27.55, 0.95, 0.95, 8, "stone_white", phase=math.pi / 8)
    for k in range(8):
        t = math.tau * k / 8 + math.pi / 8
        px, py = tx + 0.88 * math.cos(t), ty + 0.88 * math.sin(t)
        frustum(m, px, py, 27.55, 28.4, 0.08, 0.0, 4, "stone_white")
    frustum(m, tx, ty, 27.55, 35.6, 0.9, 0.0, 8, "slate", phase=math.pi / 8)
    frustum(m, tx, ty, 34.8, 35.3, 0.16, 0.16, 6, "gold")
    cross(m, tf, 0.0, 35.4, 1.5, 0.0, "iron")


def _zas_chapel(m: Mesh, f: Frame, W: float, depth: float) -> None:
    """Chapel nave running back from the front, ending in a half-round apse."""
    ca = W * 0.5
    a0, a1 = ca - 5.5, ca + 5.5
    d_back = -depth - 18.5
    rbox(m, f, a0, a1, d_back, -depth, ZAS_H - 0.1, 18.0, "brick", skip=("+d", "bottom", "top"))
    gable_roof(m, f, a0, a1, d_back, -depth, 18.0, 23.0, "slate", ridge="d", gable_mat="brick", overhang=0.3)
    for k in range(4):
        d = -depth - 2.3 - k * 4.4
        for side, sgn in ((a0, -1.0), (a1, 1.0)):
            cf = Frame.from_edge(f.p(side, d + 0.8, 0)[:2], f.p(side, d - 0.8, 0)[:2], f.vec(sgn, 0, 0)[:2])
            hole = opening(0.8, ZAS_H + 0.2, 1.0, ZAS_H + 1.6, "round", 6)
            pane(m, cf, hole, 0.02, "glass")
            archivolt(m, cf, hole, 0.12, 0.0, 0.1, "stone_white")
    cx, cy, _ = f.p(ca, d_back, 0.0)
    yaw = math.atan2(f.uy, f.ux)
    cylinder(m, cx, cy, ZAS_H - 0.1, 18.0, 5.4, 8, "brick", phase=yaw + math.pi / 8, top=False)
    frustum(m, cx, cy, 18.0, 22.0, 5.75, 0.0, 8, "slate", phase=yaw + math.pi / 8)


def build_zas_vincentius(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    m = Mesh()
    fe = front_edge(ring, tuple(lm["anchor_xy"]))
    f = fe.frame()
    W = fe.length
    depth = float((lm.get("params") or {}).get("risalit_depth_m", 7.4))
    fn = (f.nx, f.ny)
    anchor = tuple(lm["anchor_xy"])
    skinned: list[Edge] = []
    cos_hist = math.cos(math.radians(35.0))
    for e in merged_edges(ring):
        if e.length < 5.0 and e is not fe:
            continue
        ef = e.frame()
        if e.i0 == fe.i0 and e.i1 == fe.i1:
            _zas_front(m, f, W, depth)
        elif _dot(e.outward, fn) > cos_hist and math.dist(e.mid, anchor) < 60.0:
            _zas_wing_skin(m, ef, e.length)
        else:
            _zas_plain_skin(m, ef, e.length)
        skinned.append(e)
    extrude_ring(m, ring, holes, 0.0, ZAS_H, "brick", None, skip=_covered(skinned))
    ring_roof(m, ring, holes, ZAS_H, 1.2, 1.8, "slate")
    _zas_chapel(m, f, W, depth)
    return m


# --------------------------------------------------------------------- Feestzaal Harmonie


HALL_H = 8.2


def _harmonie_skin(m: Mesh, f: Frame, L: float, doors: bool, canopy=None, shade=None) -> None:
    """Pilasters alternating with round-arched glazed doors, entablature, cornice.

    ``canopy(p)`` marks bays that get the cast-iron glass gallery, ``shade(p)`` bays in
    the portico's shadow (darker render so the columns read in front of them)."""
    bays = max(1, round(L / 3.7))
    bw = L / bays
    rbox(m, f, 0.0, L, -0.05, 0.1, 0.0, 0.55, "bluestone", skip=("-d", "bottom"))
    for i in range(bays):
        b0 = i * bw
        ca = b0 + bw * 0.5
        if doors:
            hole = opening(ca, 0.55, min(1.8, bw - 1.2), 4.4, "round", 8)
        else:
            hole = opening(ca, 1.3, min(1.5, bw - 1.2), 4.3, "round", 8)
        here = f.p(ca, 0.0, 0.0)[:2]
        wall = "render_shade" if shade is not None and shade(here) else "render_white"
        window_cell(m, f, b0, b0 + bw, 0.0, 6.3, hole, wall, "render_shade", 0.3)
        glazing_bars(m, f, hole, -0.3, "frame_white", transom=4.4 if doors else 4.3)
        archivolt(m, f, hole, 0.16, 0.0, 0.08, wall)
        cell(m, f, b0, b0 + bw, 6.3, HALL_H, None, 0.0, 0.0, wall)
        if canopy is not None and canopy(here):
            m.face([f.p(b0, 0.3, 6.0), f.p(b0 + bw, 0.3, 6.0), f.p(b0 + bw, 3.0, 5.45), f.p(b0, 3.0, 5.45)], "glass_roof", normal=(0.0, 0.0, 1.0))
            for x in (b0, b0 + bw):
                rbox(m, f, x - 0.05, x + 0.05, 0.3, 3.05, 5.45, 5.6, "iron")
                px, py, _ = f.p(x, 2.95, 0.0)
                post(m, px, py, 0.0, 5.3, 0.075, "iron")
                rbox(m, f, x - 0.12, x + 0.12, 2.83, 3.07, 0.0, 0.18, "iron")
            rbox(m, f, b0, b0 + bw, 2.88, 3.05, 5.15, 5.5, "iron")
            mid = arch_points(ca, 4.7, bw * 0.5 - 0.1, "segmental", 6, 0.45)
            band(m, f, mid, [(x, z + 0.07) for x, z in mid], 2.92, 3.0, "iron", (ca, 3.0))
    for k in range(bays + 1):
        x = min(max(k * bw, 0.3), L - 0.3)
        rbox(m, f, x - 0.3, x + 0.3, 0.0, 0.22, 0.55, 6.3, "render_white", skip=("-d", "bottom"))
        rbox(m, f, x - 0.38, x + 0.38, 0.0, 0.28, 0.55, 0.85, "render_white", skip=("-d", "bottom"))
        rbox(m, f, x - 0.38, x + 0.38, 0.0, 0.3, 6.3, 6.6, "render_white", skip=("-d",))
    rbox(m, f, 0.0, L, 0.0, 0.18, 6.6, 7.4, "render_white", skip=("-d",))
    rbox(m, f, 0.0, L, 0.0, 0.5, 7.6, HALL_H, "render_white", skip=("-d",))
    rbox(m, f, 0.0, L, 0.0, 0.3, 7.4, 7.6, "render_shade", skip=("-d",))


def _harmonie_portico(m: Mesh, f: Frame, P: float, pd: float) -> None:
    """Five-part portico: arched outer bays, four columns, entablature, steps."""
    rbox(m, f, -0.1, P + 0.1, -pd, 0.0, 0.0, 0.9, "bluestone", skip=("bottom",))
    for i in range(3):
        rbox(m, f, 2.2, P - 2.2, 0.0, (3 - i) * 0.4, i * 0.3, (i + 1) * 0.3, "bluestone", skip=("bottom", "-d"))
    wa = P * 0.2
    for b0 in (0.0, P - wa):
        hole = opening(b0 + wa * 0.5, 0.9, min(1.7, wa - 0.9), 4.0, "round", 8)
        cell(m, f, b0, b0 + wa, 0.9, 6.0, hole, 0.0, -1.0, "render_white", "render_shade")
        cell(m, f, b0, b0 + wa, 0.9, 6.0, hole, -1.0, -1.0, "render_white", None, facing=-1.0)
        skin_edges(m, f, b0, b0 + wa, 0.9, 6.0, -1.0, 0.0, "render_white")
        archivolt(m, f, hole, 0.18, 0.0, 0.1, "render_white")
    for a0, a1 in ((0.0, 0.6), (P - 0.6, P)):
        rbox(m, f, a0, a1, -pd, -1.0, 0.9, 6.0, "render_white", skip=("bottom",))
    inner0, inner1 = wa + 0.55, P - wa - 0.55
    for k in range(4):
        a = inner0 + (inner1 - inner0) * k / 3.0
        x, y, _ = f.p(a, -0.55, 0.0)
        rbox(m, f, a - 0.45, a + 0.45, -1.0, -0.1, 0.9, 1.3, "render_white")
        cylinder(m, x, y, 1.3, 5.6, 0.4, 12, "render_white", top=False)
        frustum(m, x, y, 5.45, 5.7, 0.4, 0.5, 12, "render_white", top=False)
        rbox(m, f, a - 0.5, a + 0.5, -1.05, -0.05, 5.7, 6.0, "render_white")
    rbox(m, f, -0.15, P + 0.15, -pd, 0.25, 6.0, 7.1, "render_white")
    rbox(m, f, -0.35, P + 0.35, -pd, 0.5, 7.1, 7.45, "render_white")
    rbox(m, f, 0.0, P, -pd, 0.1, 7.45, HALL_H, "render_white")
    rbox(m, f, P * 0.25, P * 0.75, 0.25, 0.3, 6.25, 6.85, "render_shade")


def _harmonie_centre(m: Mesh, f: Frame, P: float, pd: float, back_d: float) -> None:
    """Raised central hall: barrel vault, lunette gable with segmental pediment and lyre."""
    rbox(m, f, 0.0, P, back_d, -pd, HALL_H - 0.1, 11.6, "render_white", skip=("+d", "bottom", "top"))
    vault = arch_points(P * 0.5, 11.6, P * 0.5 + 0.25, "segmental", 10, 2.2)
    profile_slab(m, f, vault, back_d - 0.25, -pd - 0.2, "zinc", back=True)
    df, db = -pd + 0.35, -pd - 0.15
    lun = opening(P * 0.5, 9.0, 6.8, 9.0, "round", 12)
    cell(m, f, 0.3, P - 0.3, HALL_H, 12.9, lun, df, db, "render_white", "render_shade")
    skin_edges(m, f, 0.3, P - 0.3, HALL_H, 12.9, db, df, "render_white")
    pane(m, f, lun, db, "glass")
    for k in (-2, -1, 0, 1, 2):
        t = math.pi * 0.5 + k * math.pi / 6
        x = P * 0.5 + math.cos(t) * 1.7
        z = 9.0 + math.sin(t) * 1.7
        rbox(m, f, x - 0.05, x + 0.05, db, db + 0.05, 9.0, z if k else 12.4, "frame_white")
    archivolt(m, f, lun, 0.45, df, df + 0.15, "render_shade")
    rbox(m, f, 0.0, P, db, df + 0.2, 12.9, 13.15, "render_white")
    ped = arch_points(P * 0.5, 13.15, P * 0.5 - 0.1, "segmental", 10, 1.75)
    profile_slab(m, f, ped, db, df, "render_white", back=True)
    lyre(m, f, P * 0.5, 13.25, 1.35, df, df + 0.12, "render_white")
    rbox(m, f, P * 0.5 - 0.45, P * 0.5 + 0.45, db + 0.05, df - 0.05, 14.85, 15.35, "render_white")
    px, py, _ = f.p(P * 0.5, (db + df) * 0.5, 0.0)
    frustum(m, px, py, 15.35, 16.1, 0.35, 0.0, 4, "render_white", phase=math.radians(45) + math.atan2(f.uy, f.ux))
    rbox(m, f, 0.3, P - 0.3, db, df + 0.08, HALL_H, HALL_H + 0.3, "render_white")


def _harmonie_entrance(m: Mesh, fp: Frame, Lp: float, body: float) -> None:
    """Entrance pavilion on Mechelsesteenweg: door under lyre tympanum, medallion, broken pediment."""
    A0, A1 = -0.25, Lp + 0.25
    ca = Lp * 0.5
    rbox(m, fp, A0, A1, -body, 0.0, 0.0, 7.0, "render_white", skip=("+d", "bottom", "top"))
    rbox(m, fp, A0, A1, -body, 0.0, 7.0, 7.05, "zinc", skip=("bottom",))
    rbox(m, fp, A0, A1, -0.05, 0.12, 0.0, 0.5, "bluestone", skip=("-d", "bottom"))
    door = opening(ca, 0.5, min(1.9, Lp - 1.8), 3.5, "round", 8)
    cell(m, fp, A0, A1, 0.0, 4.9, door, 0.0, -0.35, "render_white", "render_shade")
    pane(m, fp, door, -0.35, "door")
    tymp = [p for p in door if p[1] >= 3.5 - 1e-6]
    profile_slab(m, fp, tymp, -0.35, -0.22, "render_shade")
    rbox(m, fp, ca - 0.95, ca + 0.95, -0.34, -0.16, 3.35, 3.5, "render_white")
    lyre(m, fp, ca, 3.55, 0.8, -0.22, -0.14, "render_white")
    archivolt(m, fp, door, 0.18, 0.0, 0.1, "render_white")
    cell(m, fp, A0, A1, 4.9, 7.0, None, 0.0, 0.0, "render_white")
    med = [(ca + 0.6 * math.cos(t * math.tau / 16), 5.75 + 0.6 * math.sin(t * math.tau / 16)) for t in range(16)]
    profile_slab(m, fp, med, 0.0, 0.12, "render_shade")
    rbox(m, fp, ca - 0.32, ca + 0.32, 0.0, 0.16, 6.38, 6.68, "gold")
    for x0, x1 in ((A0, A0 + 0.45), (A1 - 0.45, A1)):
        rbox(m, fp, x0, x1, 0.0, 0.2, 0.5, 6.6, "render_white", skip=("-d", "bottom"))
    rbox(m, fp, A0 - 0.1, A1 + 0.1, 0.0, 0.45, 6.6, 7.0, "render_white", skip=("-d",))
    ped = [(A0 - 0.1, 7.0), (A1 + 0.1, 7.0), (A1 + 0.1, 7.35), (ca + 0.85, 8.3), (ca - 0.85, 8.3), (A0 - 0.1, 7.35)]
    profile_slab(m, fp, ped, -0.3, 0.4, "render_white", back=True)
    top = opening(ca, 8.3, 1.3, 8.8, "round", 8)
    profile_slab(m, fp, top, -0.1, 0.3, "render_white", back=True)


def build_feestzaal_harmonie(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    m = Mesh()
    params = lm.get("params") or {}
    fe = front_edge(ring, tuple(lm["anchor_xy"]))
    f = fe.frame()
    P = fe.length
    loc = [f.local(*p) for p in ring]
    near = [d for a, d in loc if d < -2.0 and (abs(a) < 0.6 or abs(a - P) < 0.6)]
    pd = -sum(near) / len(near) if near else 5.4
    body = [(a, d) for a, d in loc if not (d > -2.0 and -0.6 < a < P + 0.6)]
    ent = params.get("entrance_xy")
    ea = f.local(*ent)[0] if ent else min(a for a, _ in loc)
    cut = ea + float(params.get("arm_len_m", 23.15))
    hall_l = _clean(clip_ring_halfplane(body, (cut, 0.0), (-1.0, 0.0)))
    arm_l = _clean(clip_ring_halfplane(body, (cut, 0.0), (1.0, 0.0)))
    hall = _world_ring(f, hall_l)
    back_d = min(d for a, d in hall_l if 0.0 <= a <= P) if hall_l else -30.0
    fn = (f.nx, f.ny)
    skinned: list[Edge] = []
    for e in merged_edges(hall):
        c = _dot(e.outward, fn)
        if e.length < 3.0 or c < -0.5:
            continue
        if c > 0.9:

            def under_portico(p):
                a, d = f.local(*p)
                return -0.3 < a < P + 0.3 and d < -pd + 1.0

            _harmonie_skin(m, e.frame(), e.length, True, lambda p: not under_portico(p), under_portico)
        else:
            _harmonie_skin(m, e.frame(), e.length, False)
        skinned.append(e)
    extrude_ring(m, hall, [], 0.0, HALL_H, "render_white", None, skip=_covered(skinned))
    ring_roof(m, hall, [], HALL_H, 1.3, 3.0, "zinc")
    _harmonie_portico(m, f, P, pd)
    _harmonie_centre(m, f, P, 1.2, back_d + 1.5)
    if len(arm_l) >= 3:
        arm = _world_ring(f, arm_l)
        out = (-f.ux, -f.uy)
        end = max((e for e in ring_edges(oriented(arm)) if _dot(e.outward, out) > 0.9), key=lambda e: _dot(e.mid, out), default=None)
        extrude_ring(m, arm, [], 0.0, 4.8, "render_white", "zinc", skip=_covered([end]) if end else None)
        rbox(m, f, cut - 0.05, ea + 6.2, min(d for _, d in arm_l) - 0.02, max(d for _, d in arm_l) + 0.02, 4.8, 5.1, "render_white", skip=("bottom",))
        if end is not None:
            _harmonie_entrance(m, end.frame(), end.length, 6.0)
    return m


# ------------------------------------------------------------- Art Deco Mechelsesteenweg 123


DECO_H = 17.6


def build_art_deco_ms123(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    m = Mesh()
    fe = front_edge(ring, tuple(lm["anchor_xy"]))
    f = fe.frame()
    L = fe.length
    extrude_ring(m, ring, holes, 0.0, DECO_H, "render_cream", None, skip=_covered([fe]))
    m.cap(oriented(ring), [oriented(h, ccw=False) for h in holes], DECO_H, "zinc")
    ca, hw = L * 0.5, 1.7
    w = ca - hw
    rows = [
        (3.9, 7.4, lambda c: opening(c, 4.5, 1.6, 6.7, "rect")),
        (7.4, 11.0, lambda c: opening(c, 8.2, 1.6, 10.4, "rect")),
        (11.0, 14.0, lambda c: opening(c, 11.6, 1.6, 13.6, "rect")),
        (14.0, 17.0, lambda c: opening(c, 14.5, 1.6, 15.8, "round", 8)),
        (17.0, DECO_H, None),
    ]
    for side in (0, 1):
        s0 = 0.0 if side == 0 else ca + hw
        cols = (s0 + w * 0.29, s0 + w * 0.78) if side == 0 else (s0 + w * 0.22, s0 + w * 0.71)
        cutx = (cols[0] + cols[1]) * 0.5
        shop = opening(0.0, 0.25, 1.0, 2.75, "rect")
        sx0, sx1 = (0.5, w - 0.3) if side == 0 else (s0 + 0.3, L - 0.5)
        shop = [(sx0, 0.25), (sx1, 0.25), (sx1, 2.75), (sx0, 2.75)]
        window_cell(m, f, s0, s0 + w, 0.0, 3.9, shop, "render_cream", "frame_dark", 0.25, glass="glass_dark")
        glazing_bars(m, f, shop, -0.25, "frame_dark", transom=2.2, mullions=2)
        for c0, c1, c in ((s0, cutx, cols[0]), (cutx, s0 + w, cols[1])):
            for z0, z1, mk in rows:
                hole = mk(c) if mk else None
                window_cell(m, f, c0, c1, z0, z1, hole, "render_cream", "render_shade", 0.22, sill="render_shade" if hole else None)
                if hole:
                    glazing_bars(m, f, hole, -0.22, "frame_white", transom=opening_top(hole) - 0.55)
            rbox(m, f, c - 0.15, c + 0.15, 0.0, 0.08, 16.65, 16.95, "render_shade", skip=("-d",))
        for x in (s0, cutx, s0 + w):
            x0 = min(max(x - 0.2, 0.0), L - 0.4)
            rbox(m, f, x0, x0 + 0.4, 0.0, 0.14, 3.9, 17.0, "render_cream", skip=("-d", "bottom"))
        for z in (7.4, 11.0, 14.0):
            rbox(m, f, s0, s0 + w, 0.0, 0.1, z - 0.08, z + 0.08, "render_shade", skip=("-d",))
    door = [(ca - 0.75, 0.02), (ca + 0.75, 0.02), (ca + 0.75, 2.75), (ca - 0.75, 2.75)]
    window_cell(m, f, ca - hw, ca + hw, 0.0, 3.9, door, "render_cream", "frame_dark", 0.3, glass="door")
    rbox(m, f, 0.0, L, 0.0, 0.12, 2.95, 3.75, "render_shade", skip=("-d",))
    # full-height rounded bay window
    proj = 0.9
    R = (hw * hw + proj * proj) / (2.0 * proj)
    dc = proj - R
    t0, t1 = math.atan2(-dc, -hw), math.atan2(-dc, hw)
    k = 10
    arc = [(ca + R * math.cos(t0 + (t1 - t0) * i / k), dc + R * math.sin(t0 + (t1 - t0) * i / k)) for i in range(k + 1)]
    bands = [(3.9, 4.5, "render_cream"), (4.5, 6.7, "glass"), (6.7, 8.2, "render_cream"), (8.2, 10.4, "glass"),
             (10.4, 11.6, "render_cream"), (11.6, 13.6, "glass"), (13.6, 14.5, "render_cream"), (14.5, 16.4, "glass"), (16.4, 17.0, "render_cream")]
    cpt = f.p(ca, dc, 10.0)
    for i in range(k):
        (a0, d0), (a1, d1) = arc[i], arc[i + 1]
        for z0, z1, mat in bands:
            m.face([f.p(a0, d0, z0), f.p(a1, d1, z0), f.p(a1, d1, z1), f.p(a0, d0, z1)], mat, center=(cpt[0], cpt[1], (z0 + z1) * 0.5))
        if i % 2 == 0 and i:
            x, y, _ = f.p(a0, d0, 0.0)
            post(m, x, y, 4.5, 16.4, 0.05, "frame_white")
    m.face([f.p(a, d, 3.9) for a, d in arc], "render_cream", normal=(0.0, 0.0, -1.0))
    m.face([f.p(a, d, 17.0) for a, d in arc], "render_cream", normal=(0.0, 0.0, 1.0))
    rbox(m, f, 0.0, L, 0.0, 0.45, 17.0, DECO_H, "render_cream", skip=("-d",))
    rbox(m, f, -0.05, L + 0.05, 0.0, 0.55, DECO_H - 0.15, DECO_H, "render_shade", skip=("-d",))
    return m


# ------------------------------------------------------------------- In de Gulden Spoor


def _cross_windows(m: Mesh, f: Frame, a0: float, a1: float, cols: list[float], rows: list[tuple[float, float, float, float]], w: float = 1.25) -> None:
    """Red-brick wall with white-stone framed cross windows (Van Kuyck neotraditional)."""
    cuts = [a0] + [(cols[i] + cols[i + 1]) * 0.5 for i in range(len(cols) - 1)] + [a1]
    for i, c in enumerate(cols):
        for z0, z1, h0, h1 in rows:
            hole = opening(c, h0, w, h1, "rect")
            window_cell(m, f, cuts[i], cuts[i + 1], z0, z1, hole, "brick_brown", "stone_white", 0.22, sill="stone_white")
            glazing_bars(m, f, hole, -0.22, "stone_white", transom=h0 + (h1 - h0) * 0.66)
            rbox(m, f, c - w * 0.5 - 0.12, c + w * 0.5 + 0.12, 0.0, 0.1, h1, h1 + 0.22, "stone_white", skip=("-d",))
    if not cols:
        for z0, z1, _h0, _h1 in rows:
            cell(m, f, a0, a1, z0, z1, None, 0.0, 0.0, "brick_brown")


def _quoins(m: Mesh, f: Frame, a: float, z0: float, z1: float, sgn: float) -> None:
    k = 0
    z = z0
    while z + 0.3 < z1:
        w = 0.55 if k % 2 == 0 else 0.32
        a0, a1 = (a, a + w) if sgn > 0 else (a - w, a)
        rbox(m, f, a0, a1, 0.0, 0.05, z, z + 0.3, "stone_white", skip=("-d",))
        z += 0.3
        k += 1


def build_gulden_spoor(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Frans Claes' house-museum by Van Kuyck (1902-1911): red-brick main house under a
    steep hipped slate roof with a stepped dormer gable, the flat-roofed 1911 south
    extension with corner pinnacles, the round stair tower in the angle between them
    and the low connecting gallery towards the gatehouse."""
    m = Mesh()
    fe = front_edge(ring, tuple(lm["anchor_xy"]))
    f = fe.frame()
    L = fe.length
    ext = (0.0, L, -9.2, 0.0)
    wing = (L + 0.2, L + 10.0, -9.2, -5.7)
    main = (1.1, 17.2, -21.4, -9.2)
    tc, tr = (-1.55, -5.4), 1.35
    blocks = [ext, wing, main]
    EXT_H, MAIN_H = 5.0, 8.6

    def inside(e: Edge) -> bool:
        a, d = f.local(*e.mid)
        if math.hypot(a - tc[0], d - tc[1]) < tr + 0.6:
            return True
        return any(b[0] - 0.4 <= a <= b[1] + 0.4 and b[2] - 0.4 <= d <= b[3] + 0.4 for b in blocks)

    # connecting gallery: low brick wall with round-arched windows and a stone coping
    gallery = [e for e in merged_edges(ring) if e.length > 8.0 and not inside(e) and _dot(e.outward, (f.nx, f.ny)) > 0.8]
    for e in gallery:
        gf = e.frame()
        n = max(1, round(e.length / 3.0))
        for k in range(n):
            a0, a1 = e.length * k / n, e.length * (k + 1) / n
            hole = opening((a0 + a1) * 0.5, 0.9, 1.1, 2.0, "round", 6)
            window_cell(m, gf, a0, a1, 0.0, 3.0, hole, "brick_brown", "stone_white", 0.2, sill="stone_white")
        rbox(m, gf, 0.0, e.length, -0.05, 0.1, 0.0, 0.5, "stone_white", skip=("-d", "bottom"))
        rbox(m, gf, 0.0, e.length, -0.1, 0.12, 3.0, 3.15, "stone_white", skip=("bottom",))
    extrude_ring(m, ring, holes, 0.0, 3.0, "brick_brown", "stone_grey", skip=lambda e: inside(e) or _covered(gallery)(e))
    # 1911 extension: souterrain + one storey, flat roof, diagonal corner pinnacles
    a0, a1, d0, d1 = ext
    rbox(m, f, a0, a1, d0, d1, 0.0, EXT_H, "brick_brown", skip=("+d", "-a", "bottom", "top"))
    rbox(m, f, a0, a1, d0, d1, EXT_H, EXT_H + 0.05, "zinc", skip=("bottom",))
    rows = [(0.0, 1.3, 0.35, 1.0), (1.3, EXT_H, 1.7, 4.0)]
    rbox(m, f, a0, a1, -0.05, 0.12, 0.0, 1.3, "stone_white", skip=("-d", "bottom"))
    _cross_windows(m, f, a0, a1, [a1 * 0.27, a1 * 0.73], rows, w=1.6)
    side = Frame.from_edge(f.p(0.0, -6.3, 0)[:2], f.p(0.0, 0.0, 0)[:2], (-f.ux, -f.uy))
    _cross_windows(m, side, 0.0, 6.3, [3.4], rows, w=1.2)
    for x in (0.0, L):
        _quoins(m, f, x, 1.3, EXT_H, 1.0 if x == 0.0 else -1.0)
    rbox(m, f, a0 - 0.1, a1 + 0.1, 0.0, 0.25, EXT_H - 0.35, EXT_H, "stone_white", skip=("-d",))
    rbox(m, f, a0, a1, -0.25, 0.0, EXT_H, EXT_H + 0.7, "brick_brown")
    rbox(m, f, a0 - 0.05, a1 + 0.05, -0.3, 0.05, EXT_H + 0.7, EXT_H + 0.82, "stone_white")
    for x in (0.25, L - 0.25):
        px, py, _ = f.p(x, -0.15, 0.0)
        frustum(m, px, py, EXT_H, EXT_H + 1.3, 0.24, 0.24, 4, "stone_white", top=False)
        frustum(m, px, py, EXT_H + 1.3, EXT_H + 2.2, 0.26, 0.0, 4, "stone_white")
    w0, w1, wd0, wd1 = wing
    rbox(m, f, w0, w1, wd0, wd1, 0.0, EXT_H, "brick_brown", skip=("+d", "bottom", "top"))
    rbox(m, f, w0, w1, wd0, wd1, EXT_H, EXT_H + 0.05, "zinc", skip=("bottom",))
    fw = f.shifted(0.0, wd1)
    rbox(m, fw, w0, w1, -0.05, 0.12, 0.0, 1.3, "stone_white", skip=("-d", "bottom"))
    _cross_windows(m, fw, w0, w1, [w0 + (w1 - w0) * t for t in (0.2, 0.5, 0.8)], rows)
    rbox(m, fw, w0 - 0.1, w1 + 0.1, 0.0, 0.25, EXT_H - 0.35, EXT_H, "stone_white", skip=("-d",))
    # main house: two storeys over a souterrain, steep hipped slate roof
    a0, a1, d0, d1 = main
    rbox(m, f, a0, a1, d0, d1, 0.0, MAIN_H, "brick_brown", skip=("+d", "-a", "bottom", "top"))
    fm = f.shifted(0.0, d1)
    _cross_windows(m, fm, a0, a1, [a0 + (a1 - a0) * t for t in (0.1, 0.3, 0.5, 0.7, 0.9)], [(0.0, EXT_H + 0.2, 2.0, 4.2), (EXT_H + 0.2, MAIN_H, 5.9, 7.9)])
    east = Frame.from_edge(f.p(a0, d0, 0)[:2], f.p(a0, d1, 0)[:2], (-f.ux, -f.uy))
    rbox(m, east, 0.0, d1 - d0, -0.05, 0.12, 0.0, 1.3, "stone_white", skip=("-d", "bottom"))
    _cross_windows(m, east, 0.0, d1 - d0, [2.2, 6.2, 10.0], [(0.0, 4.6, 1.8, 4.0), (4.6, MAIN_H, 5.9, 7.9)])
    for x in (0.0, d1 - d0):
        _quoins(m, east, x, 1.3, MAIN_H, 1.0 if x == 0.0 else -1.0)
    for fr, ln in ((fm, a1), (east, d1 - d0)):
        rbox(m, fr, (a0 if fr is fm else 0.0) - 0.1, ln + 0.1, 0.0, 0.3, MAIN_H - 0.3, MAIN_H, "stone_white", skip=("-d",))
    hip_roof(m, f, a0, a1, d0, d1, MAIN_H, 15.4, "slate", overhang=0.35)
    # stepped dormer gable ("getrapt aandak") on the street slope
    gc = (a0 + a1) * 0.5
    gable_roof(m, f, gc - 2.3, gc + 2.3, -13.6, d1 + 0.1, MAIN_H, 12.6, "slate", ridge="d", gable_mat=None, overhang=0.1)
    for k, wk in enumerate((5.0, 4.0, 3.0, 2.0, 1.0)):
        z0 = MAIN_H + k * 0.85
        rbox(m, f, gc - wk * 0.5, gc + wk * 0.5, d1 - 0.1, d1 + 0.35, z0, z0 + 0.85, "brick_brown", skip=("bottom",))
        for sgn in (-1.0, 1.0):
            x = gc + sgn * wk * 0.5
            rbox(m, f, *sorted((x, x - sgn * 0.55)), d1 - 0.12, d1 + 0.42, z0 + 0.85, z0 + 0.95, "stone_white")
    hole = opening(gc, MAIN_H + 0.5, 1.1, MAIN_H + 1.9, "round", 6)
    rbox(m, f, gc - 0.7, gc + 0.7, d1 + 0.35, d1 + 0.42, MAIN_H + 0.35, MAIN_H + 2.55, "stone_white")
    pane(m, f, hole, d1 + 0.43, "glass")
    rbox(m, f, 3.4, 4.2, -17.0, -16.4, MAIN_H, 16.8, "brick_brown")
    rbox(m, f, 3.3, 4.3, -17.1, -16.3, 16.8, 17.0, "stone_white")
    rbox(m, f, 14.6, 15.4, -19.6, -19.0, MAIN_H, 16.2, "brick_brown")
    rbox(m, f, 14.5, 15.5, -19.7, -18.9, 16.2, 16.4, "stone_white")
    # round stair tower: octagonal top stage under a waisted slate spire
    tx, ty, _ = f.p(*tc, 0.0)
    yaw = math.atan2(f.uy, f.ux)
    cylinder(m, tx, ty, 0.0, 9.6, tr, 12, "brick_brown", top=False)
    for z, h in ((0.0, 1.3), (4.75, 0.25), (8.4, 0.25)):
        cylinder(m, tx, ty, z, z + h, tr + 0.05, 12, "stone_white", top=False)
    for k in range(3):
        t = math.atan2(f.ny, f.nx) + (k - 1) * 1.0
        ox, oy = tx + math.cos(t) * (tr - 0.03), ty + math.sin(t) * (tr - 0.03)
        for z in (2.2 + k * 1.1, 5.6 + k * 0.6):
            box(m, Frame(ox, oy, -math.sin(t), math.cos(t), math.cos(t), math.sin(t)), 0.0, 0.0, z, 0.45, 0.08, 1.1, "glass")
    cylinder(m, tx, ty, 9.6, 11.4, tr + 0.08, 8, "brick_brown", phase=yaw + math.pi / 8, top=False)
    for k in range(8):
        t = yaw + math.pi / 8 + math.tau * k / 8
        post(m, tx + math.cos(t) * (tr + 0.08), ty + math.sin(t) * (tr + 0.08), 9.6, 11.4, 0.07, "stone_white")
    cylinder(m, tx, ty, 11.4, 11.6, tr + 0.22, 8, "stone_white", phase=yaw + math.pi / 8)
    frustum(m, tx, ty, 11.6, 12.5, tr + 0.25, 0.75, 8, "slate", phase=yaw + math.pi / 8, top=False)
    frustum(m, tx, ty, 12.5, 13.1, 0.75, 0.55, 8, "slate", phase=yaw + math.pi / 8, top=False)
    frustum(m, tx, ty, 13.1, 17.2, 0.55, 0.0, 8, "slate", phase=yaw + math.pi / 8)
    post(m, tx, ty, 16.9, 17.9, 0.04, "iron")
    return m


def build_gulden_spoor_gate(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Neo-Gothic gatehouse after Het Steen: white-stone front, basket-arch carriage gate,
    three-sided oriel under a slate hood, cornice between finialed postaments. The rest of
    the plot is the blind rendered gable seen from Sint-Vincentiusstraat."""
    m = Mesh()
    fe = front_edge(ring, tuple(lm["anchor_xy"]))
    f = fe.frame()
    L = fe.length
    gw = min(4.8, L * 0.5)
    g = (lm.get("params") or {}).get("gallery_xy")
    at_start = g is None or math.dist(fe.p0, g) <= math.dist(fe.p1, g)
    g0, g1 = (0.0, gw) if at_start else (L - gw, L)
    h0, h1 = (gw, L) if at_start else (0.0, L - gw)
    gc = (g0 + g1) * 0.5
    dmin = min(f.local(*p)[1] for p in ring)
    H = 8.0
    extrude_ring(m, ring, holes, 0.0, H, "render_cream", "zinc", skip=_covered([fe]))
    # blind gable wall of the house behind
    cell(m, f, h0, h1, 0.0, H, None, 0.0, 0.0, "render_cream")
    rbox(m, f, h0, h1, -0.05, 0.1, 0.0, 0.6, "bluestone", skip=("-d", "bottom"))
    gable_roof(m, f, h0, h1, dmin, 0.0, H, H + 6.4, "slate", ridge="d", gable_mat="render_cream", overhang=0.2)
    rbox(m, f, (h0 + h1) * 0.5 - 0.35, (h0 + h1) * 0.5 + 0.35, dmin * 0.55 - 0.3, dmin * 0.55 + 0.3, H + 4.0, H + 7.4, "brick_brown")
    # gatehouse front
    rbox(m, f, g0, g1, -0.05, 0.14, 0.0, 0.5, "bluestone", skip=("-d", "bottom"))
    gate = opening(gc, 0.5, min(3.0, gw - 1.4), 2.7, "segmental", 8, 0.75)
    window_cell(m, f, g0, g1, 0.5, 4.1, gate, "stone_white", "stone_white", 0.45, glass="door")
    archivolt(m, f, gate, 0.2, 0.0, 0.12, "stone_white")
    for k in range(1, 5):
        x = gc + (k - 2.5) * 0.6
        rbox(m, f, x - 0.02, x + 0.02, -0.45, -0.42, 0.5, 3.3, "iron")
    cell(m, f, g0, g1, 4.1, H, None, 0.0, 0.0, "stone_white")
    for x in (g0, g1):
        rbox(m, f, x - 0.25, x + 0.25, 0.0, 0.5, 0.0, H, "stone_white", skip=("-d", "bottom"))
        px, py, _ = f.p(x, 0.25, 0.0)
        frustum(m, px, py, H + 0.35, H + 1.5, 0.28, 0.0, 4, "stone_white", phase=math.pi / 4 + math.atan2(f.uy, f.ux))
        rbox(m, f, x - 0.3, x + 0.3, -0.05, 0.55, H, H + 0.35, "stone_white")
    rbox(m, f, g0, g1, 0.0, 0.35, H - 0.1, H + 0.35, "stone_white", skip=("-d",))
    rbox(m, f, gc - 0.9, gc + 0.9, 0.0, 0.1, 3.7, 4.25, "stone_white", skip=("-d",))
    orl = [f.p(a, d, 0.0)[:2] for a, d in ((gc - 1.25, 0.0), (gc + 1.25, 0.0), (gc + 0.75, 0.75), (gc - 0.75, 0.75))]
    prism(m, orl, 4.5, 7.2, "stone_white", top=False)
    for k in range(3):
        step = [f.p(a, d, 0.0)[:2] for a, d in ((gc - 1.25 + k * 0.2, 0.0), (gc + 1.25 - k * 0.2, 0.0), (gc + 0.75 - k * 0.2, 0.75 - k * 0.22), (gc - 0.75 + k * 0.2, 0.75 - k * 0.22))]
        prism(m, step, 4.5 - (k + 1) * 0.22, 4.5 - k * 0.22, "stone_white", top=False, bottom=True)
    mid = f.p(gc, 0.3, 0.0)
    for i in range(3):
        p0, p1 = orl[(i + 1) % 4], orl[(i + 2) % 4]
        of = Frame.from_edge(p0, p1, (p0[0] + p1[0] - 2 * mid[0], p0[1] + p1[1] - 2 * mid[1]))
        ln = math.dist(p0, p1)
        rbox(m, of, 0.12, ln - 0.12, 0.0, 0.04, 4.95, 6.85, "glass")
        for x in (ln * 0.5,):
            rbox(m, of, x - 0.05, x + 0.05, 0.0, 0.08, 4.95, 6.85, "stone_white")
        rbox(m, of, 0.12, ln - 0.12, 0.0, 0.08, 6.0, 6.08, "stone_white")
    hood = offset_ring(oriented(orl), -0.12)
    pyramid(m, hood, 7.2, f.p(gc, 0.25, 8.3), "slate")
    m.face([(x, y, 7.2) for x, y in hood], "stone_white", normal=(0.0, 0.0, -1.0))
    gable_roof(m, f, g0 - 0.15, g1 + 0.15, -5.0, 0.35, H + 0.35, H + 3.4, "slate", ridge="a", gable_mat="stone_white", overhang=0.15)
    rbox(m, f, gc - 0.6, gc + 0.6, -1.4, 0.15, H + 0.4, H + 1.6, "frame_dark", skip=("bottom",))
    gable_roof(m, f, gc - 0.7, gc + 0.7, -1.4, 0.15, H + 1.6, H + 2.3, "slate", ridge="d", gable_mat="frame_dark", overhang=0.08)
    rbox(m, f, gc - 0.4, gc + 0.4, 0.15, 0.17, H + 0.6, H + 1.45, "glass")
    return m


# -------------------------------------------------------------- Koning Albertpark kiosk


def build_albertpark_kiosk(ring: list[Vec2], holes: list[list[Vec2]], lm: dict) -> Mesh:
    """Octagonal bandstand: bluestone podium with blind arcades, cast-iron columns and
    railing, concave zinc canopy with fascia pendants, gilt lyre finial."""
    m = Mesh()
    pts = oriented(ring)
    c = centroid(pts)
    r = sum(math.dist(p, c) for p in pts) / len(pts)
    edges = ring_edges(pts)
    target = (lm.get("params") or {}).get("stairs_toward_xy")
    if target:
        dirv = (target[0] - c[0], target[1] - c[1])
        stair = max(range(len(edges)), key=lambda i: _dot(edges[i].outward, dirv))
    else:
        stair = 0
    floor = 1.62
    for i, e in enumerate(edges):
        ef = e.frame()
        L = e.length
        if i == stair:
            cell(m, ef, 0.0, L, 0.0, 1.45, None, 0.0, 0.0, "bluestone")
            for s in range(6):
                rbox(m, ef, 0.5, L - 0.5, 0.0, (6 - s) * 0.3, s * 0.27, (s + 1) * 0.27, "bluestone", skip=("bottom", "-d"))
            for x0 in (0.15, L - 0.5):
                rbox(m, ef, x0, x0 + 0.35, 0.0, 1.9, 0.0, 0.5, "bluestone", skip=("bottom", "-d"))
                rbox(m, ef, x0, x0 + 0.35, 1.5, 1.9, 0.5, 1.1, "bluestone", skip=("bottom",))
            continue
        n = 3
        for k in range(n):
            a0, a1 = L * k / n, L * (k + 1) / n
            hole = opening((a0 + a1) * 0.5, 0.25, (a1 - a0) * 0.55, 0.85, "round", 6)
            window_cell(m, ef, a0, a1, 0.0, 1.45, hole, "bluestone", "bluestone", 0.12, glass="bluestone")
    m.face([(p[0], p[1], 1.45) for p in pts], "bluestone", normal=(0.0, 0.0, 1.0))
    lip = offset_ring(pts, -0.14)
    prism(m, lip, 1.45, floor, "bluestone")
    # columns, railing, arched brackets
    k = (r - 0.45) / r
    cols = [(c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k) for p in pts]
    for x, y in cols:
        post(m, x, y, floor, 5.3, 0.09, "iron")
        frustum(m, x, y, floor, floor + 0.3, 0.17, 0.12, 6, "iron", top=False)
        frustum(m, x, y, 5.05, 5.3, 0.1, 0.18, 6, "iron", top=False)
    for i in range(len(cols)):
        p0, p1 = cols[i], cols[(i + 1) % len(cols)]
        cf = Frame.from_edge(p0, p1, edges[i].outward)
        L = math.dist(p0, p1)
        rbox(m, cf, 0.0, L, -0.07, 0.07, 5.15, 5.35, "iron")
        inner = arch_points(L * 0.5, 4.55, L * 0.5 - 0.12, "segmental", 8, 0.5)
        band(m, cf, inner, [(x, z + 0.09) for x, z in inner], -0.03, 0.03, "iron", (L * 0.5, 3.0))
        for t in (0.25, 0.75):
            rbox(m, cf, L * t - 0.02, L * t + 0.02, -0.02, 0.02, 4.75, 5.15, "iron")
        if i == stair:
            continue
        rbox(m, cf, 0.1, L - 0.1, -0.035, 0.035, 2.52, 2.6, "iron")
        rbox(m, cf, 0.1, L - 0.1, -0.025, 0.025, 1.78, 1.84, "iron")
        nb = max(2, int(L / 0.3))
        for b in range(1, nb):
            x = L * b / nb
            rbox(m, cf, x - 0.016, x + 0.016, -0.016, 0.016, 1.84, 2.52, "iron")
    # concave canopy
    def ringat(rad: float, z: float) -> list[tuple[float, float, float]]:
        s = rad / r
        return [(c[0] + (p[0] - c[0]) * s, c[1] + (p[1] - c[1]) * s, z) for p in pts]

    re = r + 0.55
    profile = [(re, 5.55), (re * 0.66, 6.4), (re * 0.34, 7.05), (re * 0.12, 7.45)]
    rings = [ringat(rr, z) for rr, z in profile]
    ctr = (c[0], c[1], 4.0)
    for lo, hi in zip(rings, rings[1:]):
        for i in range(len(pts)):
            j = (i + 1) % len(pts)
            m.face([lo[i], lo[j], hi[j], hi[i]], "zinc", center=ctr)
    eave = ringat(re, 5.55)
    m.face(list(eave), "canopy", normal=(0.0, 0.0, -1.0))
    fas = ringat(re, 5.25)
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        m.face([fas[i], fas[j], eave[j], eave[i]], "canopy", center=(c[0], c[1], 5.4))
        ef = Frame.from_edge(fas[i][:2], fas[j][:2], edges[i].outward)
        L = math.dist(fas[i][:2], fas[j][:2])
        npend = max(3, int(L / 0.45))
        for q in range(npend):
            x0, x1 = L * q / npend, L * (q + 1) / npend
            m.face([ef.p(x0, 0.0, 5.25), ef.p(x1, 0.0, 5.25), ef.p((x0 + x1) * 0.5, 0.0, 5.02)], "canopy", normal=ef.vec(0.0, 1.0, 0.0))
        rbox(m, ef, 0.0, L, -0.01, 0.01, 5.55, 5.72, "iron")
        x, y, _ = eave[i]
        post(m, x, y, 5.55, 5.95, 0.03, "iron")
        frustum(m, x, y, 5.95, 6.15, 0.09, 0.0, 6, "gold")
    top = rings[-1]
    m.face(list(top), "zinc", normal=(0.0, 0.0, 1.0))
    frustum(m, c[0], c[1], 7.45, 7.95, 0.34, 0.2, 8, "iron")
    frustum(m, c[0], c[1], 7.95, 8.1, 0.24, 0.24, 8, "gold")
    e0 = edges[stair]
    base = Frame(c[0], c[1], -e0.outward[1], e0.outward[0], e0.outward[0], e0.outward[1])
    for fr in (base, base.turned(math.pi / 2)):
        lyre(m, fr, 0.0, 8.1, 1.15, -0.04, 0.04, "gold")
    return m


# -------------------------------------------------------------- Peter Benoit monument


def build_benoit_monument(node: dict) -> Mesh:
    """Henry van de Velde's memorial: long bluestone wall, raised lyre pier, basin."""
    m = Mesh()
    x, y = float(node["x"]), float(node["y"])
    fx, fy = node.get("facing_xy") or (x, y + 1.0)
    nx, ny = fx - x, fy - y
    ln = math.hypot(nx, ny) or 1.0
    nx, ny = nx / ln, ny / ln
    f = Frame(x, y, ny, -nx, nx, ny)
    rbox(m, f, -8.6, 8.6, -0.6, 0.0, 0.0, 1.5, "stone_grey")
    rbox(m, f, -8.75, 8.75, -0.7, 0.1, 1.5, 1.62, "bluestone")
    for s in (-1.0, 1.0):
        rbox(m, f, *sorted((s * 8.6, s * 9.5)), -0.6, 0.0, 0.0, 0.9, "stone_grey")
        rbox(m, f, *sorted((s * 2.0, s * 3.3)), -0.75, 0.25, 0.0, 1.95, "stone_grey")
        rbox(m, f, *sorted((s * 1.95, s * 3.35)), -0.8, 0.3, 1.95, 2.05, "bluestone")
        rbox(m, f, *sorted((s * 3.6, s * 8.3)), 0.0, 0.55, 0.0, 0.45, "bluestone", skip=("-d", "bottom"))
        for k in range(1, 4):
            a = s * (3.3 + k * 1.3)
            rbox(m, f, a - 0.02, a + 0.02, 0.0, 0.01, 0.5, 1.5, "bluestone")
        rbox(m, f, *sorted((s * 3.0, s * 6.2)), 5.3, 5.7, 0.0, 0.9, "stone_grey")
        rbox(m, f, *sorted((s * 5.8, s * 6.2)), 2.8, 5.3, 0.0, 0.9, "stone_grey")
    rbox(m, f, -1.6, 1.6, -0.9, 0.3, 0.0, 2.9, "stone_grey")
    rbox(m, f, -1.75, 1.75, -1.0, 0.4, 2.9, 3.05, "bluestone")
    lyre(m, f, 0.0, 1.25, 1.5, 0.3, 0.42, "bluestone")
    rbox(m, f, -1.6, 1.6, 0.3, 2.1, 0.0, 0.12, "bluestone", skip=("bottom",))
    for a0, a1, d0, d1 in ((-1.6, 1.6, 1.8, 2.1), (-1.6, -1.3, 0.3, 1.8), (1.3, 1.6, 0.3, 1.8)):
        rbox(m, f, a0, a1, d0, d1, 0.12, 0.45, "bluestone")
    m.face([f.p(-1.3, 0.3, 0.36), f.p(1.3, 0.3, 0.36), f.p(1.3, 1.8, 0.36), f.p(-1.3, 1.8, 0.36)], "water", normal=(0.0, 0.0, 1.0))
    rbox(m, f, -0.12, 0.12, 0.3, 0.42, 1.0, 1.15, "bluestone")
    return m


BUILDERS = {
    "zas_vincentius": build_zas_vincentius,
    "feestzaal_harmonie": build_feestzaal_harmonie,
    "art_deco_ms123": build_art_deco_ms123,
    "gulden_spoor": build_gulden_spoor,
    "gulden_spoor_gate": build_gulden_spoor_gate,
    "albertpark_kiosk": build_albertpark_kiosk,
}
NODE_BUILDERS = {"benoit_monument": build_benoit_monument}


def build_landmark(bldg: dict) -> Mesh | None:
    lm = bldg.get("landmark") or {}
    fn = BUILDERS.get(lm.get("custom"))
    if fn is None:
        return None
    ring = [(float(p[0]), float(p[1])) for p in bldg["ring"]]
    holes = [[(float(p[0]), float(p[1])) for p in h] for h in bldg.get("holes") or []]
    return fn(ring, holes, lm)


def build_node_landmark(node: dict) -> Mesh | None:
    fn = NODE_BUILDERS.get(node.get("custom"))
    return fn(node) if fn else None
