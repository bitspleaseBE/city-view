"""Mesh kit for hand-modelled landmarks (pure Python, no bpy).

Landmarks are assembled from boxes, extruded elevation profiles, arch bands and
perforated wall skins in a local *facade frame*: ``a`` runs along the wall, ``d``
points out of it (``d = 0`` is the OSM footprint wall plane) and ``z`` is height
above ground. Every face carries a logical material name (``brick``, ``render_white``,
``slate`` ...); ``blender/build_city.py`` maps the names to tiling materials and
turns a :class:`Mesh` into one object per landmark. No photographs anywhere.

Openings are real: a :func:`cell` is a wall panel with a convex hole whose reveal
runs back to the glass, so windows read by shadow from the street instead of being
painted on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

MATERIALS = frozenset(
    {
        "brick",  # dark red neo-Gothic brick (ZAS)
        "brick_dark",  # weathered / recessed brick
        "brick_brown",  # Van Kuyck mansion brick
        "brick_cream",  # pale Silesian brick (Thielens, Peter Benoitstraat 34/40)
        "brick_yellow",  # yellow brick with red bands (Peter Benoitstraat 38)
        "stone_white",  # white limestone: tracery, statues, copings
        "stone_grey",  # light grey stone / concrete (Benoit monument)
        "bluestone",  # Belgian arduin: plinths, sills, steps
        "render_white",  # painted neoclassical render (Harmonie)
        "render_cream",  # Art Deco cream render
        "render_shade",  # recessed / shadowed render panels
        "slate",
        "zinc",
        "glass",
        "glass_dark",  # deep voids: doorways, shop interiors, belfry openings
        "glass_roof",  # light, dirty glazing of iron canopies
        "glass_amber",  # stained glass
        "glass_green",
        "glass_blue",
        "frame_white",
        "frame_dark",
        "iron",  # cast iron: columns, railings, cresting
        "gold",  # gilt lyre finial
        "door",  # dark varnished timber
        "canopy",  # painted kiosk ceiling
        "water",
    }
)


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def newell_normal(pts: list[Vec3]) -> Vec3:
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx, ny, nz)


@dataclass
class Cap:
    """Flat horizontal polygon with holes; Blender triangulates it (courtyard roofs)."""

    outer: list[Vec2]
    holes: list[list[Vec2]]
    z: float
    mat: str

    def tri_estimate(self) -> int:
        return len(self.outer) + sum(len(h) for h in self.holes) + 2 * len(self.holes) - 2


@dataclass
class Mesh:
    verts: list[Vec3] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)
    mats: list[str] = field(default_factory=list)
    caps: list[Cap] = field(default_factory=list)

    def face(
        self,
        pts: list[Vec3],
        mat: str,
        normal: Vec3 | None = None,
        center: Vec3 | None = None,
    ) -> None:
        """Add one planar polygon; ``normal`` / ``center`` orient it outward."""
        if mat not in MATERIALS:
            raise ValueError(f"unknown landmark material {mat!r}")
        if len(pts) < 3:
            return
        nrm = newell_normal(pts)
        if nrm[0] * nrm[0] + nrm[1] * nrm[1] + nrm[2] * nrm[2] < 1e-10:
            return  # degenerate sliver
        want = normal
        if want is None and center is not None:
            n = len(pts)
            fc = (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)
            want = _sub(fc, center)
        if want is not None and nrm[0] * want[0] + nrm[1] * want[1] + nrm[2] * want[2] < 0.0:
            pts = list(reversed(pts))
        base = len(self.verts)
        self.verts.extend((float(x), float(y), float(z)) for x, y, z in pts)
        self.faces.append(tuple(range(base, base + len(pts))))
        self.mats.append(mat)

    def cap(self, outer: list[Vec2], holes: list[list[Vec2]], z: float, mat: str) -> None:
        if mat not in MATERIALS:
            raise ValueError(f"unknown landmark material {mat!r}")
        self.caps.append(Cap([tuple(p) for p in outer], [[tuple(p) for p in h] for h in holes], float(z), mat))

    def extend(self, other: "Mesh") -> None:
        base = len(self.verts)
        self.verts.extend(other.verts)
        self.faces.extend(tuple(i + base for i in f) for f in other.faces)
        self.mats.extend(other.mats)
        self.caps.extend(other.caps)

    def tri_count(self) -> int:
        return sum(len(f) - 2 for f in self.faces) + sum(c.tri_estimate() for c in self.caps)

    def bounds(self) -> tuple[Vec3, Vec3]:
        pts = list(self.verts) + [(x, y, c.z) for c in self.caps for x, y in c.outer]
        if not pts:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        lo = (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts))
        hi = (max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts))
        return lo, hi

    def materials_used(self) -> set[str]:
        return set(self.mats) | {c.mat for c in self.caps}


@dataclass(frozen=True)
class Frame:
    """Facade frame: origin, unit ``u`` along the wall, unit ``n`` out of it."""

    ox: float
    oy: float
    ux: float
    uy: float
    nx: float
    ny: float

    def p(self, a: float, d: float, z: float) -> Vec3:
        return (self.ox + self.ux * a + self.nx * d, self.oy + self.uy * a + self.ny * d, z)

    def vec(self, a: float, d: float, z: float) -> Vec3:
        return (self.ux * a + self.nx * d, self.uy * a + self.ny * d, z)

    def shifted(self, a: float = 0.0, d: float = 0.0) -> "Frame":
        x, y, _ = self.p(a, d, 0.0)
        return Frame(x, y, self.ux, self.uy, self.nx, self.ny)

    def turned(self, angle: float) -> "Frame":
        """Rotate u and n about z (keeps the origin)."""
        c, s = math.cos(angle), math.sin(angle)
        return Frame(
            self.ox,
            self.oy,
            self.ux * c - self.uy * s,
            self.ux * s + self.uy * c,
            self.nx * c - self.ny * s,
            self.nx * s + self.ny * c,
        )

    def local(self, x: float, y: float) -> Vec2:
        dx, dy = x - self.ox, y - self.oy
        return (dx * self.ux + dy * self.uy, dx * self.nx + dy * self.ny)

    @staticmethod
    def from_edge(p0: Vec2, p1: Vec2, outward: Vec2) -> "Frame":
        ux, uy = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(ux, uy) or 1.0
        ux, uy = ux / ln, uy / ln
        nx, ny = uy, -ux
        if nx * outward[0] + ny * outward[1] < 0.0:
            nx, ny = -nx, -ny
        return Frame(float(p0[0]), float(p0[1]), ux, uy, nx, ny)


# --------------------------------------------------------------------------- polygons


def signed_area(ring: list[Vec2]) -> float:
    acc = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return acc * 0.5


def oriented(ring: list[Vec2], ccw: bool = True) -> list[Vec2]:
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if (signed_area(pts) > 0.0) != ccw:
        pts.reverse()
    return pts


def centroid(ring: list[Vec2]) -> Vec2:
    a = signed_area(ring)
    if abs(a) < 1e-9:
        n = max(1, len(ring))
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    return (cx / (6.0 * a), cy / (6.0 * a))


def point_in_ring(x: float, y: float, ring: list[Vec2]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _seg_cross(p1: Vec2, p2: Vec2, p3: Vec2, p4: Vec2) -> bool:
    def orient(a: Vec2, b: Vec2, c: Vec2) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and (
        (d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9)
    )


def rings_cross(a: list[Vec2], b: list[Vec2] | None = None) -> bool:
    """True when ring ``a`` self-intersects (b None) or crosses ring ``b``."""
    na = len(a)
    if b is None:
        for i in range(na):
            for j in range(i + 2, na):
                if i == 0 and j == na - 1:
                    continue
                if _seg_cross(a[i], a[(i + 1) % na], a[j], a[(j + 1) % na]):
                    return True
        return False
    nb = len(b)
    return any(
        _seg_cross(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]) for i in range(na) for j in range(nb)
    )


def offset_ring(ring: list[Vec2], dist: float, miter_limit: float = 2.5) -> list[Vec2]:
    """Miter offset to the *left* of each edge (inward for CCW, outward for CW rings)."""
    n = len(ring)
    out: list[Vec2] = []
    for i in range(n):
        p0, p1, p2 = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
        e0 = (p1[0] - p0[0], p1[1] - p0[1])
        e1 = (p2[0] - p1[0], p2[1] - p1[1])
        l0 = math.hypot(*e0) or 1.0
        l1 = math.hypot(*e1) or 1.0
        n0 = (-e0[1] / l0, e0[0] / l0)
        n1 = (-e1[1] / l1, e1[0] / l1)
        bx, by = n0[0] + n1[0], n0[1] + n1[1]
        bl = math.hypot(bx, by)
        if bl < 1e-9:
            bx, by, bl = n0[0], n0[1], 1.0
        bx, by = bx / bl, by / bl
        cos_half = max(1.0 / miter_limit, bx * n0[0] + by * n0[1])
        out.append((p1[0] + bx * dist / cos_half, p1[1] + by * dist / cos_half))
    return out


def simplify_ring(ring: list[Vec2], min_edge: float = 0.6, max_turn_deg: float = 4.0) -> list[Vec2]:
    """Drop near-duplicate and near-collinear vertices (keeps the outline within cm)."""
    pts = [tuple(p) for p in ring]
    changed = True
    cos_lim = math.cos(math.radians(max_turn_deg))
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            e0 = (p1[0] - p0[0], p1[1] - p0[1])
            e1 = (p2[0] - p1[0], p2[1] - p1[1])
            l0, l1 = math.hypot(*e0), math.hypot(*e1)
            if l0 < 1e-6 or (l0 < min_edge and l1 > l0):
                pts.pop(i)
                changed = True
                break
            if l1 > 1e-6 and (e0[0] * e1[0] + e0[1] * e1[1]) / (l0 * l1) > cos_lim:
                pts.pop(i)
                changed = True
                break
    return pts


def clip_ring_halfplane(ring: list[Vec2], p: Vec2, n: Vec2) -> list[Vec2]:
    """Sutherland-Hodgman: keep the part of ``ring`` where (x - p) . n <= 0."""
    out: list[Vec2] = []
    m = len(ring)

    def side(q: Vec2) -> float:
        return (q[0] - p[0]) * n[0] + (q[1] - p[1]) * n[1]

    for i in range(m):
        a, b = ring[i], ring[(i + 1) % m]
        sa, sb = side(a), side(b)
        if sa <= 0.0:
            out.append(a)
        if (sa < 0.0 < sb) or (sb < 0.0 < sa):
            t = sa / (sa - sb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def split_ring(ring: list[Vec2], p: Vec2, n: Vec2) -> tuple[list[Vec2], list[Vec2]]:
    return clip_ring_halfplane(ring, p, n), clip_ring_halfplane(ring, p, (-n[0], -n[1]))


@dataclass(frozen=True)
class Edge:
    i0: int
    i1: int
    p0: Vec2
    p1: Vec2
    outward: Vec2

    @property
    def length(self) -> float:
        return math.hypot(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])

    @property
    def mid(self) -> Vec2:
        return ((self.p0[0] + self.p1[0]) * 0.5, (self.p0[1] + self.p1[1]) * 0.5)

    def frame(self) -> Frame:
        return Frame.from_edge(self.p0, self.p1, self.outward)


def ring_edges(ring: list[Vec2]) -> list[Edge]:
    """Edges of a ring with outward normals (ring orientation is detected)."""
    ccw = signed_area(ring) > 0.0
    out = []
    n = len(ring)
    for i in range(n):
        p0, p1 = ring[i], ring[(i + 1) % n]
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(ex, ey)
        if ln < 1e-6:
            continue
        nrm = (ey / ln, -ex / ln) if ccw else (-ey / ln, ex / ln)
        out.append(Edge(i, (i + 1) % n, tuple(p0), tuple(p1), nrm))
    return out


def merged_edges(ring: list[Vec2], max_turn_deg: float = 8.0) -> list[Edge]:
    """Chains of near-collinear edges merged into one facade run each."""
    edges = ring_edges(ring)
    if not edges:
        return []
    cos_lim = math.cos(math.radians(max_turn_deg))

    def joins(e0: Edge, e1: Edge) -> bool:
        return e0.outward[0] * e1.outward[0] + e0.outward[1] * e1.outward[1] > cos_lim

    start = 0
    for i in range(len(edges)):
        if not joins(edges[i - 1], edges[i]):
            start = i
            break
    else:
        return edges
    order = edges[start:] + edges[:start]
    runs: list[list[Edge]] = [[order[0]]]
    for e in order[1:]:
        if joins(runs[-1][-1], e):
            runs[-1].append(e)
        else:
            runs.append([e])
    out = []
    for run in runs:
        p0, p1 = run[0].p0, run[-1].p1
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(ex, ey) or 1.0
        nrm = (ey / ln, -ex / ln)
        if nrm[0] * run[0].outward[0] + nrm[1] * run[0].outward[1] < 0.0:
            nrm = (-nrm[0], -nrm[1])
        out.append(Edge(run[0].i0, run[-1].i1, p0, p1, nrm))
    return out


def front_edge(ring: list[Vec2], anchor: Vec2, max_turn_deg: float = 8.0) -> Edge:
    """The merged facade run whose midpoint is nearest the surveyed front anchor."""

    def seg_dist(e: Edge) -> float:
        ax, ay = e.p0
        bx, by = e.p1
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((anchor[0] - ax) * dx + (anchor[1] - ay) * dy) / ((dx * dx + dy * dy) or 1e-9)))
        return math.hypot(anchor[0] - ax - dx * t, anchor[1] - ay - dy * t)

    return min(merged_edges(ring, max_turn_deg), key=seg_dist)


def ngon(cx: float, cy: float, r: float, sides: int, phase: float = 0.0) -> list[Vec2]:
    return [
        (cx + r * math.cos(phase + math.tau * i / sides), cy + r * math.sin(phase + math.tau * i / sides))
        for i in range(sides)
    ]


# --------------------------------------------------------------------- 2-D outlines (a, z)


def arch_points(ca: float, z_spring: float, half_w: float, kind: str = "round", segs: int = 8, rise: float | None = None) -> list[Vec2]:
    """Intrados from the left springing point over the crown to the right one."""
    if kind == "flat" or half_w <= 0.0:
        return [(ca - half_w, z_spring), (ca + half_w, z_spring)]
    if kind == "pointed":
        h = rise if rise is not None else half_w * 1.6
        r = (half_w * half_w + h * h) / (2.0 * half_w)
        cl = ca - half_w + r  # centre of the left arc (the right one mirrors it)
        a_top = math.atan2(h, ca - cl)
        half = max(2, segs // 2)
        angles = [math.pi - (math.pi - a_top) * i / half for i in range(half)]
        left = [(cl + r * math.cos(t), z_spring + r * math.sin(t)) for t in angles]
        right = [(2 * ca - x, z) for x, z in reversed(left)]
        return left + [(ca, z_spring + h)] + right
    if kind == "segmental":
        h = rise if rise is not None else half_w * 0.35
        r = (half_w * half_w + h * h) / (2.0 * h)
        zc = z_spring + h - r
        a0 = math.atan2(z_spring - zc, -half_w)
        a1 = math.atan2(z_spring - zc, half_w)
        return [(ca + r * math.cos(a0 + (a1 - a0) * i / segs), zc + r * math.sin(a0 + (a1 - a0) * i / segs)) for i in range(segs + 1)]
    # round (semicircular)
    return [(ca + half_w * math.cos(math.pi * (1 - i / segs)), z_spring + half_w * math.sin(math.pi * (1 - i / segs))) for i in range(segs + 1)]


def opening(ca: float, z0: float, w: float, z_spring: float, kind: str = "round", segs: int = 8, rise: float | None = None) -> list[Vec2]:
    """Closed convex outline of a window / door: rectangle with an arched head (CCW in a-z)."""
    hw = w * 0.5
    if kind == "circle":
        r = hw
        return [(ca + r * math.cos(math.tau * i / (segs * 2)), z0 + r + r * math.sin(math.tau * i / (segs * 2))) for i in range(segs * 2)]
    if kind == "rect":
        return [(ca - hw, z0), (ca + hw, z0), (ca + hw, z_spring), (ca - hw, z_spring)]
    head = arch_points(ca, z_spring, hw, kind, segs, rise)
    pts = [(ca - hw, z0), (ca + hw, z0)] + list(reversed(head))
    out: list[Vec2] = []
    for q in pts:
        if not out or abs(q[0] - out[-1][0]) + abs(q[1] - out[-1][1]) > 1e-6:
            out.append(q)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) + abs(out[0][1] - out[-1][1]) <= 1e-6:
        out.pop()
    return out


def opening_top(outline: list[Vec2]) -> float:
    return max(z for _, z in outline)


def _ray_hit(cx: float, cz: float, dx: float, dz: float, poly: list[Vec2]) -> float:
    """Distance along the ray (c + t d) to the boundary of a convex polygon around c."""
    best = 1e18
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        ex, ez = bx - ax, bz - az
        den = dx * ez - dz * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - cx) * ez - (az - cz) * ex) / den
        s = ((ax - cx) * dz - (az - cz) * dx) / den
        if t > 1e-9 and -1e-9 <= s <= 1.0 + 1e-9:
            best = min(best, t)
    return best if best < 1e17 else 0.0


# ----------------------------------------------------------------------- primitives


_BOX_FACES = {
    "bottom": (0, 1, 2, 3),
    "top": (4, 5, 6, 7),
    "-d": (0, 1, 5, 4),
    "+a": (1, 2, 6, 5),
    "+d": (2, 3, 7, 6),
    "-a": (3, 0, 4, 7),
}


def box(m: Mesh, f: Frame, a: float, d: float, z: float, w: float, dep: float, h: float, mat: str, skip: tuple[str, ...] = ()) -> None:
    """Box centred on (a, d), standing on z (w along the wall, dep out of it).

    ``skip`` drops faces that would be coplanar with a skin or buried in a wall
    (``bottom``, ``top``, ``-a``, ``+a``, ``-d``, ``+d``)."""
    if w <= 0 or dep <= 0 or h <= 0:
        return
    hw, hd = w * 0.5, dep * 0.5
    c = f.p(a, d, z + h * 0.5)
    q = [f.p(a + sa * hw, d + sd * hd, zz) for zz in (z, z + h) for sa, sd in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for name, idx in _BOX_FACES.items():
        if name not in skip:
            m.face([q[i] for i in idx], mat, center=c)


def rbox(m: Mesh, f: Frame, a0: float, a1: float, d0: float, d1: float, z0: float, z1: float, mat: str, skip: tuple[str, ...] = ()) -> None:
    """Box from local extents (a0..a1, d0..d1, z0..z1)."""
    box(m, f, (a0 + a1) * 0.5, (d0 + d1) * 0.5, z0, a1 - a0, d1 - d0, z1 - z0, mat, skip)


def wbox(m: Mesh, cx: float, cy: float, z: float, sx: float, sy: float, h: float, yaw: float, mat: str) -> None:
    """World box centred on (cx, cy) rotated by ``yaw``, standing on z."""
    f = Frame(cx, cy, math.cos(yaw), math.sin(yaw), -math.sin(yaw), math.cos(yaw))
    box(m, f, 0.0, 0.0, z, sx, sy, h, mat)


def profile_slab(m: Mesh, f: Frame, outline: list[Vec2], d0: float, d1: float, mat: str, back: bool = False) -> None:
    """Extrude a convex elevation outline (a, z) from depth d0 to d1."""
    if len(outline) < 3 or d1 <= d0:
        return
    n = len(outline)
    ca = sum(p[0] for p in outline) / n
    cz = sum(p[1] for p in outline) / n
    c = f.p(ca, (d0 + d1) * 0.5, cz)
    m.face([f.p(a, d1, z) for a, z in outline], mat, normal=f.vec(0.0, 1.0, 0.0))
    if back:
        m.face([f.p(a, d0, z) for a, z in outline], mat, normal=f.vec(0.0, -1.0, 0.0))
    for i in range(n):
        (a0, z0), (a1, z1) = outline[i], outline[(i + 1) % n]
        m.face([f.p(a0, d0, z0), f.p(a1, d0, z1), f.p(a1, d1, z1), f.p(a0, d1, z0)], mat, center=c)


def band(m: Mesh, f: Frame, inner: list[Vec2], outer: list[Vec2], d0: float, d1: float, mat: str, centre: Vec2 | None = None) -> None:
    """Moulding between two matched polylines (archivolts, gable copings)."""
    if len(inner) != len(outer) or len(inner) < 2:
        raise ValueError("band needs two polylines of equal length")
    if centre is None:
        centre = (sum(p[0] for p in inner) / len(inner), min(p[1] for p in inner))
    cw = f.p(centre[0], (d0 + d1) * 0.5, centre[1])
    for i in range(len(inner) - 1):
        ia, ib, oa, ob = inner[i], inner[i + 1], outer[i], outer[i + 1]
        m.face([f.p(ia[0], d1, ia[1]), f.p(ib[0], d1, ib[1]), f.p(ob[0], d1, ob[1]), f.p(oa[0], d1, oa[1])], mat, normal=f.vec(0.0, 1.0, 0.0))
        intr = [f.p(ia[0], d0, ia[1]), f.p(ib[0], d0, ib[1]), f.p(ib[0], d1, ib[1]), f.p(ia[0], d1, ia[1])]
        mid = ((ia[0] + ib[0]) * 0.5, (ia[1] + ib[1]) * 0.5)
        m.face(intr, mat, normal=f.vec(centre[0] - mid[0], 0.0, centre[1] - mid[1]))
        extr = [f.p(oa[0], d0, oa[1]), f.p(ob[0], d0, ob[1]), f.p(ob[0], d1, ob[1]), f.p(oa[0], d1, oa[1])]
        m.face(extr, mat, center=cw)


def offset_polyline(pts: list[Vec2], dist: float, centre: Vec2) -> list[Vec2]:
    """Push each point of an arch/gable line away from ``centre`` by ``dist``."""
    out = []
    for x, z in pts:
        dx, dz = x - centre[0], z - centre[1]
        ln = math.hypot(dx, dz) or 1.0
        out.append((x + dx / ln * dist, z + dz / ln * dist))
    return out


def archivolt(m: Mesh, f: Frame, outline: list[Vec2], width: float, d0: float, d1: float, mat: str) -> None:
    """Moulded surround following an opening outline (jambs + arch), proud of the wall."""
    n = len(outline)
    ca = sum(p[0] for p in outline) / n
    zb = min(p[1] for p in outline)
    head = [p for p in outline if p[1] > zb + 1e-6]
    if len(head) < 2:
        return
    # outline is CCW starting bottom-left: [BL, BR, ...head right->left...]
    hw = max(p[0] for p in outline) - ca
    spring = min(p[1] for p in head)
    if max(p[1] for p in head) - spring < 1e-6:  # flat head: lintel + jambs
        box(m, f, ca, (d0 + d1) * 0.5, spring, hw * 2.0 + width * 2.0, d1 - d0, width, mat)
        for side in (-1.0, 1.0):
            box(m, f, ca + side * (hw + width * 0.5), (d0 + d1) * 0.5, zb, width, d1 - d0, spring - zb, mat)
        return
    centre = (ca, spring)
    inner = list(reversed(head))  # left -> right
    outer = []
    for x, z in inner:
        if z <= spring + 1e-6:
            outer.append((x + (-width if x < ca else width), z))
        else:
            dx, dz = x - ca, z - spring
            ln = math.hypot(dx, dz) or 1.0
            outer.append((x + dx / ln * width, z + dz / ln * width))
    band(m, f, inner, outer, d0, d1, mat, centre)
    for side in (-1.0, 1.0):
        x = ca + side * hw
        box(m, f, x + side * width * 0.5, (d0 + d1) * 0.5, zb, width, d1 - d0, spring - zb, mat)


def cell(
    m: Mesh,
    f: Frame,
    a0: float,
    a1: float,
    z0: float,
    z1: float,
    hole: list[Vec2] | None,
    d_front: float,
    d_back: float,
    wall: str,
    reveal: str | None = None,
    facing: float = 1.0,
) -> None:
    """Wall panel [a0,a1]x[z0,z1] at depth d_front with a convex hole and its reveal.

    ``facing`` -1 builds the back side of a pierced block (normal along -n)."""
    if a1 - a0 < 1e-4 or z1 - z0 < 1e-4:
        return
    nrm = f.vec(0.0, facing, 0.0)
    if not hole:
        m.face([f.p(a0, d_front, z0), f.p(a1, d_front, z0), f.p(a1, d_front, z1), f.p(a0, d_front, z1)], wall, normal=nrm)
        return
    hc = (sum(p[0] for p in hole) / len(hole), sum(p[1] for p in hole) / len(hole))
    rect = [(a0, z0), (a1, z0), (a1, z1), (a0, z1)]
    angs = sorted(
        {round(math.atan2(z - hc[1], x - hc[0]), 9) for x, z in hole}
        | {round(math.atan2(z - hc[1], x - hc[0]), 9) for x, z in rect}
    )
    ring_h, ring_r = [], []
    for t in angs:
        dx, dz = math.cos(t), math.sin(t)
        th = _ray_hit(hc[0], hc[1], dx, dz, hole)
        tr = _ray_hit(hc[0], hc[1], dx, dz, rect)
        ring_h.append((hc[0] + dx * th, hc[1] + dz * th))
        ring_r.append((hc[0] + dx * max(tr, th), hc[1] + dz * max(tr, th)))
    k = len(angs)
    for i in range(k):
        j = (i + 1) % k
        quad = [ring_h[i], ring_h[j], ring_r[j], ring_r[i]]
        m.face([f.p(x, d_front, z) for x, z in quad], wall, normal=nrm)
    if abs(d_front - d_back) > 1e-4:
        rmat = reveal or wall
        for i in range(len(hole)):
            pa, pb = hole[i], hole[(i + 1) % len(hole)]
            mid = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5)
            m.face(
                [f.p(pa[0], d_back, pa[1]), f.p(pb[0], d_back, pb[1]), f.p(pb[0], d_front, pb[1]), f.p(pa[0], d_front, pa[1])],
                rmat,
                normal=f.vec(hc[0] - mid[0], 0.0, hc[1] - mid[1]),
            )


def pane(m: Mesh, f: Frame, outline: list[Vec2], d: float, mat: str = "glass") -> None:
    m.face([f.p(a, d, z) for a, z in outline], mat, normal=f.vec(0.0, 1.0, 0.0))


def skin_edges(m: Mesh, f: Frame, a0: float, a1: float, z0: float, z1: float, d_back: float, d_front: float, mat: str) -> None:
    """Close the ends and top of a proud wall skin."""
    for a, sgn in ((a0, -1.0), (a1, 1.0)):
        m.face([f.p(a, d_back, z0), f.p(a, d_front, z0), f.p(a, d_front, z1), f.p(a, d_back, z1)], mat, normal=f.vec(sgn, 0.0, 0.0))
    m.face([f.p(a0, d_back, z1), f.p(a1, d_back, z1), f.p(a1, d_front, z1), f.p(a0, d_front, z1)], mat, normal=(0.0, 0.0, 1.0))


def prism(m: Mesh, pts: list[Vec2], z0: float, z1: float, mat: str, top: bool = True, bottom: bool = False, top_mat: str | None = None) -> None:
    """Vertical extrusion of a convex footprint."""
    n = len(pts)
    c2 = centroid(pts)
    c = (c2[0], c2[1], (z0 + z1) * 0.5)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        m.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat, center=c)
    if top:
        m.face([(p[0], p[1], z1) for p in pts], top_mat or mat, normal=(0.0, 0.0, 1.0))
    if bottom:
        m.face([(p[0], p[1], z0) for p in pts], mat, normal=(0.0, 0.0, -1.0))


def frustum(m: Mesh, cx: float, cy: float, z0: float, z1: float, r0: float, r1: float, sides: int, mat: str, phase: float = 0.0, top: bool = True, bottom: bool = False) -> None:
    """Tapered n-gon (r1 = 0 gives a spire / cone)."""
    lo = ngon(cx, cy, r0, sides, phase)
    hi = ngon(cx, cy, r1, sides, phase) if r1 > 1e-6 else None
    c = (cx, cy, (z0 + z1) * 0.5)
    for i in range(sides):
        j = (i + 1) % sides
        if hi is None:
            m.face([(lo[i][0], lo[i][1], z0), (lo[j][0], lo[j][1], z0), (cx, cy, z1)], mat, center=c)
        else:
            m.face([(lo[i][0], lo[i][1], z0), (lo[j][0], lo[j][1], z0), (hi[j][0], hi[j][1], z1), (hi[i][0], hi[i][1], z1)], mat, center=c)
    if top and hi is not None:
        m.face([(p[0], p[1], z1) for p in hi], mat, normal=(0.0, 0.0, 1.0))
    if bottom:
        m.face([(p[0], p[1], z0) for p in lo], mat, normal=(0.0, 0.0, -1.0))


def cylinder(m: Mesh, cx: float, cy: float, z0: float, z1: float, r: float, sides: int, mat: str, phase: float = 0.0, top: bool = True) -> None:
    frustum(m, cx, cy, z0, z1, r, r, sides, mat, phase, top=top)


def post(m: Mesh, x: float, y: float, z0: float, z1: float, r: float, mat: str) -> None:
    """Slender column: a cheap 6-sided shaft."""
    frustum(m, x, y, z0, z1, r, r, 6, mat, top=False)


def pyramid(m: Mesh, pts: list[Vec2], z0: float, apex: Vec3, mat: str) -> None:
    """Spirelet / hood over any convex footprint."""
    n = len(pts)
    c2 = centroid(pts)
    c = (c2[0], c2[1], z0)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        m.face([(a[0], a[1], z0), (b[0], b[1], z0), apex], mat, center=c)


def gable_roof(m: Mesh, f: Frame, a0: float, a1: float, d0: float, d1: float, z_eave: float, z_ridge: float, mat: str, ridge: str = "d", gable_mat: str | None = None, overhang: float = 0.25) -> None:
    """Saddle roof over a local rectangle; ``ridge`` = 'd' runs the ridge out of the wall
    (front-facing gable), 'a' along it. Gable triangles in ``gable_mat`` (wall material)."""
    c = f.p((a0 + a1) * 0.5, (d0 + d1) * 0.5, (z_eave + z_ridge) * 0.5)
    if ridge == "d":
        am = (a0 + a1) * 0.5
        o = overhang
        for side in (a0 - o, a1 + o):
            m.face([f.p(side, d0 - o, z_eave), f.p(side, d1 + o, z_eave), f.p(am, d1 + o, z_ridge), f.p(am, d0 - o, z_ridge)], mat, center=c)
        if gable_mat:
            for d in (d0, d1):
                m.face([f.p(a0, d, z_eave), f.p(a1, d, z_eave), f.p(am, d, z_ridge)], gable_mat, center=c)
    else:
        dm = (d0 + d1) * 0.5
        o = overhang
        for side in (d0 - o, d1 + o):
            m.face([f.p(a0 - o, side, z_eave), f.p(a1 + o, side, z_eave), f.p(a1 + o, dm, z_ridge), f.p(a0 - o, dm, z_ridge)], mat, center=c)
        if gable_mat:
            for a in (a0, a1):
                m.face([f.p(a, d0, z_eave), f.p(a, d1, z_eave), f.p(a, dm, z_ridge)], gable_mat, center=c)


def hip_roof(m: Mesh, f: Frame, a0: float, a1: float, d0: float, d1: float, z_eave: float, z_ridge: float, mat: str, overhang: float = 0.3) -> None:
    """Hipped roof over a local rectangle, ridge along the longer side."""
    a0, a1, d0, d1 = a0 - overhang, a1 + overhang, d0 - overhang, d1 + overhang
    wa, wd = a1 - a0, d1 - d0
    c = f.p((a0 + a1) * 0.5, (d0 + d1) * 0.5, z_eave)
    if wa >= wd:
        inset = wd * 0.5
        r0, r1 = f.p(a0 + inset, (d0 + d1) * 0.5, z_ridge), f.p(a1 - inset, (d0 + d1) * 0.5, z_ridge)
        e = [f.p(a0, d0, z_eave), f.p(a1, d0, z_eave), f.p(a1, d1, z_eave), f.p(a0, d1, z_eave)]
        m.face([e[0], e[1], r1, r0], mat, center=c)
        m.face([e[2], e[3], r0, r1], mat, center=c)
        m.face([e[1], e[2], r1], mat, center=c)
        m.face([e[3], e[0], r0], mat, center=c)
    else:
        inset = wa * 0.5
        r0, r1 = f.p((a0 + a1) * 0.5, d0 + inset, z_ridge), f.p((a0 + a1) * 0.5, d1 - inset, z_ridge)
        e = [f.p(a0, d0, z_eave), f.p(a1, d0, z_eave), f.p(a1, d1, z_eave), f.p(a0, d1, z_eave)]
        m.face([e[1], e[2], r1, r0], mat, center=c)
        m.face([e[3], e[0], r0, r1], mat, center=c)
        m.face([e[0], e[1], r0], mat, center=c)
        m.face([e[2], e[3], r1], mat, center=c)


# ------------------------------------------------------------------ footprint masses


def extrude_ring(m: Mesh, outer: list[Vec2], holes: list[list[Vec2]], z0: float, z1: float, wall: str, top: str | None, skip=None) -> None:
    """Footprint walls (outer + courtyard walls) with a flat top cap.

    ``skip(edge) -> bool`` leaves out outer walls that a facade skin replaces."""
    o = oriented(outer, ccw=True)
    hs = [oriented(h, ccw=False) for h in holes]
    for ring in [o] + hs:
        for e in ring_edges(ring):
            if skip is not None and ring is o and skip(e):
                continue
            nrm = (e.outward[0], e.outward[1], 0.0)
            if ring is not o:
                nrm = (-nrm[0], -nrm[1], 0.0)  # courtyard walls face into the yard
            m.face([(e.p0[0], e.p0[1], z0), (e.p1[0], e.p1[1], z0), (e.p1[0], e.p1[1], z1), (e.p0[0], e.p0[1], z1)], wall, normal=nrm)
    if top:
        m.cap(o, hs, z1, top)


def ring_roof(m: Mesh, outer: list[Vec2], holes: list[list[Vec2]], z0: float, rise: float, inset: float, mat: str, insets: tuple[float, ...] | None = None) -> float:
    """Low pitched roof skirt around a courtyard block; returns the inset used (0 = flat).

    Outer ring goes in, courtyard rings go out by ``inset`` while rising ``rise``; the
    middle is a flat cap. Falls back to smaller insets, then a flat cap, when the
    offset outline would self-intersect on short jogs.
    """
    o = oriented(simplify_ring(outer), ccw=True)
    hs = [oriented(simplify_ring(h), ccw=False) for h in holes]
    for d in insets or (inset, inset * 0.6, inset * 0.35):
        oo = offset_ring(o, d)
        ho = [offset_ring(h, d) for h in hs]
        rings = [oo] + ho
        if signed_area(oo) <= 0 or any(signed_area(h) >= 0 for h in ho):
            continue
        if any(rings_cross(r) for r in rings):
            continue
        flipped = False
        for base, top in zip([o] + hs, rings):
            for i in range(len(base)):
                j = (i + 1) % len(base)
                eb = (base[j][0] - base[i][0], base[j][1] - base[i][1])
                et = (top[j][0] - top[i][0], top[j][1] - top[i][1])
                if eb[0] * et[0] + eb[1] * et[1] <= 0.0:
                    flipped = True  # inset wider than the wing: the edge turned over
        if flipped:
            continue
        if any(rings_cross(rings[i], rings[j]) for i in range(len(rings)) for j in range(i + 1, len(rings))):
            continue
        if any(rings_cross(r, base) for r in rings for base in [o] + hs):
            continue
        if not all(point_in_ring(p[0], p[1], o) for r in rings for p in r):
            continue
        if any(point_in_ring(p[0], p[1], h) for r in rings for p in r for h in hs):
            continue
        for base, top in zip([o] + hs, rings):
            n = len(base)
            for i in range(n):
                j = (i + 1) % n
                m.face(
                    [(base[i][0], base[i][1], z0), (base[j][0], base[j][1], z0), (top[j][0], top[j][1], z0 + rise), (top[i][0], top[i][1], z0 + rise)],
                    mat,
                    normal=(0.0, 0.0, 1.0),
                )
        m.cap(oo, ho, z0 + rise, mat)
        return d
    m.cap(o, hs, z0 + 0.05, mat)
    return 0.0
