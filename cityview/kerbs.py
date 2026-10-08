"""Kerb / pavement trimming at street mouths and the 3-D kerb profile maths.

Pure stdlib (no bpy) so ``blender/build_city.py`` can use it inside Blender and the
unit tests can run without it.

Why: kerbs and pavement ribbons are laid parallel to every road. Where a side street
joins, the main road's ribbon would run straight across the mouth of that street.
With a flat 8 cm bump that was barely noticeable; with a real 12 cm kerb and a raised
pavement it reads as a wall across the junction. ``split_at_carriageways`` cuts the
ribbon centreline wherever it enters another road's carriageway at a real angle (so
gentle bends of the *same* street, whose neighbouring way starts right at the node,
never cut), leaving the mouth open like a dropped kerb.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

NON_CARRIAGEWAY = frozenset({"footway", "path", "cycleway", "steps", "pedestrian", "track"})

# Vertical profile (metres above the world datum; road surface is ~0.04).
Z_ROAD_SURFACE = 0.04
KERB_TOP = 0.15  # ~11 cm reveal above the asphalt (Antwerp natuursteen kerbs run 10-14 cm)
PAVEMENT_TOP = 0.12  # pavement just under the kerb top; keeps surveyed benches' seat height sane
KERB_WIDTH = 0.28
MIN_CROSS_ANGLE_SIN = math.sin(math.radians(35.0))
CELL = 40.0


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class CarriagewayIndex:
    """Grid index of driveable road segments (centreline + half width)."""

    def __init__(self, roads: Iterable[dict]):
        self.segments: list[tuple[float, float, float, float, float, int]] = []
        self._grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for ri, road in enumerate(roads):
            if (road.get("kind") or "residential") in NON_CARRIAGEWAY:
                continue
            pts = road.get("points") or []
            half = float(road.get("width") or 6.0) * 0.5
            for i in range(len(pts) - 1):
                ax, ay = float(pts[i][0]), float(pts[i][1])
                bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
                if math.hypot(bx - ax, by - ay) < 0.05:
                    continue
                idx = len(self.segments)
                self.segments.append((ax, ay, bx, by, half, ri))
                pad = half + 1.0
                gx0, gx1 = int((min(ax, bx) - pad) // CELL), int((max(ax, bx) + pad) // CELL)
                gy0, gy1 = int((min(ay, by) - pad) // CELL), int((max(ay, by) + pad) // CELL)
                for gx in range(gx0, gx1 + 1):
                    for gy in range(gy0, gy1 + 1):
                        self._grid[(gx, gy)].append(idx)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def blocked(
        self, x: float, y: float, tx: float, ty: float, margin: float, exclude: int | None = None
    ) -> bool:
        """True if (x, y) lies inside another road's carriageway (+margin) that meets
        the ribbon tangent (tx, ty) at a genuine angle (> ~35 degrees)."""
        for si in self._grid.get((int(x // CELL), int(y // CELL)), ()):
            ax, ay, bx, by, half, ri = self.segments[si]
            if ri == exclude:
                continue
            if _seg_dist(x, y, ax, ay, bx, by) >= half + margin:
                continue
            sl = math.hypot(bx - ax, by - ay)
            cross = abs((bx - ax) * ty - (by - ay) * tx) / sl  # sin of the angle between them
            if cross >= MIN_CROSS_ANGLE_SIN:
                return True
        return False


def _densify(points: list[list[float]], step: float) -> list[list[float]]:
    out = [[float(points[0][0]), float(points[0][1])]]
    for i in range(len(points) - 1):
        ax, ay = float(points[i][0]), float(points[i][1])
        bx, by = float(points[i + 1][0]), float(points[i + 1][1])
        n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / step)))
        for k in range(1, n + 1):
            t = k / n
            out.append([ax + (bx - ax) * t, ay + (by - ay) * t])
    return out


def split_at_carriageways(
    points: list[list[float]],
    index: CarriagewayIndex,
    own_road: int | None,
    margin: float,
    step: float = 1.5,
) -> list[list[list[float]]]:
    """Split a ribbon centreline into runs that stay out of crossing carriageways.

    ``margin`` is added to the other road's half width (negative: allow a little
    overlap, so a kerb stops at the crossing road's edge rather than inside it).
    A polyline that never meets another road is returned untouched.
    """
    if len(points) < 2:
        return []
    if not index:
        return [points]
    dense = _densify(points, step)
    flags: list[bool] = []
    for i, (x, y) in enumerate(dense):
        j0, j1 = max(0, i - 1), min(len(dense) - 1, i + 1)
        tx, ty = dense[j1][0] - dense[j0][0], dense[j1][1] - dense[j0][1]
        tl = math.hypot(tx, ty) or 1.0
        flags.append(index.blocked(x, y, tx / tl, ty / tl, margin, own_road))
    if not any(flags):
        return [points]
    runs: list[list[list[float]]] = []
    cur: list[list[float]] = []
    for p, bad in zip(dense, flags):
        if bad:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
        else:
            cur.append(p)
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def kerb_strips(
    points: list[list[float]], width: float, road_side_left: bool
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], list[float]]:
    """Left/right edge points of a ribbon and cumulative distance along it.

    ``road_side_left`` only documents which edge faces the carriageway; callers
    index ``left`` / ``right`` accordingly.
    """
    half = width / 2.0
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    along = [0.0]
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == len(points) - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
        if i:
            along.append(along[-1] + math.hypot(x - points[i - 1][0], y - points[i - 1][1]))
    return left, right, along


def kerb_profile(
    points: list[list[float]],
    width: float,
    z_bottom: float,
    z_top: float,
    road_edge_is_left: bool,
    uv_tile_m: float = 1.6,
) -> tuple[list[tuple[float, float, float]], list[list[int]], list[tuple[float, float]], list[int]]:
    """Closed kerb prism along ``points``: top face, road-facing face, pavement-facing
    face and two end caps. Returns (verts, faces, per-loop uv list parallel to faces'
    flattened vertex order, face kinds 0=top 1=road face 2=walk face 3=cap).

    Faces are wound so their normals point away from the prism.
    """
    left, right, along = kerb_strips(points, width, road_edge_is_left)
    n = len(points)
    inv = 1.0 / max(uv_tile_m, 0.1)
    verts: list[tuple[float, float, float]] = []
    for (lx, ly), (rx, ry) in zip(left, right):
        verts += [(lx, ly, z_top), (rx, ry, z_top), (lx, ly, z_bottom), (rx, ry, z_bottom)]
    # per point i: 4i = L top, 4i+1 = R top, 4i+2 = L bottom, 4i+3 = R bottom
    faces: list[list[int]] = []
    uvs: list[tuple[float, float]] = []
    kinds: list[int] = []
    h = max(0.01, z_top - z_bottom)
    for i in range(n - 1):
        a, b = 4 * i, 4 * (i + 1)
        u0, u1 = along[i] * inv, along[i + 1] * inv
        # Travelling +x with left = +y.  Top (CCW from above): R_i, R_j, L_j, L_i.
        faces.append([a + 1, b + 1, b, a])
        uvs += [(u0, 0.0), (u1, 0.0), (u1, width * inv), (u0, width * inv)]
        kinds.append(0)
        # Left face, outward +y: top_i, top_j, bottom_j, bottom_i.
        faces.append([a, b, b + 2, a + 2])
        uvs += [(u0, h * inv), (u1, h * inv), (u1, 0.0), (u0, 0.0)]
        kinds.append(1 if road_edge_is_left else 2)
        # Right face, outward -y: top_i, bottom_i, bottom_j, top_j.
        faces.append([a + 1, a + 3, b + 3, b + 1])
        uvs += [(u0, h * inv), (u0, 0.0), (u1, 0.0), (u1, h * inv)]
        kinds.append(2 if road_edge_is_left else 1)
    cap_uv = [(0.0, h * inv), (0.0, 0.0), (width * inv, 0.0), (width * inv, h * inv)]
    a = 0
    faces.append([a, a + 2, a + 3, a + 1])  # start cap, outward -x
    uvs += cap_uv
    kinds.append(3)
    b = 4 * (n - 1)
    faces.append([b + 1, b + 3, b + 2, b])  # end cap, outward +x
    uvs += cap_uv
    kinds.append(3)
    return verts, faces, uvs, kinds
