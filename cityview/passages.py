"""Cut OSM ``tunnel=building_passage`` driveways through sealed building footprints.

Mappers often draw a single building ring that pinches to a point at the porte-cochère
portals, plus a service way tagged ``tunnel=building_passage``. Without a cut, the
extruded LOD1 block and two short street façades read as a dead end even though the
driveway continues through. Splitting the ring into the masses on either side of a
narrow corridor leaves a real alley mouth (and walkable footprint gap).
"""

from __future__ import annotations

import math
from typing import Any

# Half-width of the cut corridor (full opening ≈ 2.8 m). Clamped per portal so thin
# pier remnants stay on each flank of the mouth.
PASSAGE_HALF_W = 1.4
MIN_HALF_W = 0.7
MIN_PART_AREA = 18.0  # m²; drop a sliver that would not read as a house
PORTAL_SNAP_M = 1.75
# Second half of a split keeps a stable unique id outside the OSM way range.
PART_ID_OFFSET = 1_000_000_000_000


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def _ring_area(ring: list[list[float]]) -> float:
    n = len(ring)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def _portal_index(ring: list[list[float]], px: float, py: float) -> int | None:
    best_i: int | None = None
    best_d = PORTAL_SNAP_M
    for i, (x, y) in enumerate(ring):
        d = _dist(x, y, px, py)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def _chain_interior(ring: list[list[float]], i_from: int, i_to: int) -> list[list[float]]:
    """Vertices strictly between ``i_from`` and ``i_to`` walking forward around the ring."""
    n = len(ring)
    out: list[list[float]] = []
    i = (i_from + 1) % n
    guard = 0
    while i != i_to and guard <= n:
        out.append([float(ring[i][0]), float(ring[i][1])])
        i = (i + 1) % n
        guard += 1
    return out


def _portal_half_width(ring: list[list[float]], idx: int, half_w: float) -> float:
    """Clamp corridor half-width so each street pier keeps some frontage."""
    n = len(ring)
    px, py = ring[idx]
    prev = ring[(idx - 1) % n]
    nxt = ring[(idx + 1) % n]
    clearance = min(_dist(px, py, prev[0], prev[1]), _dist(px, py, nxt[0], nxt[1])) * 0.45
    return max(MIN_HALF_W, min(half_w, clearance))


def cut_ring_for_passage(
    ring: list[list[float]],
    ax: float,
    ay: float,
    bx: float,
    by: float,
    half_w: float = PASSAGE_HALF_W,
) -> list[list[list[float]]] | None:
    """Split ``ring`` into the two masses beside a portal-to-portal corridor.

    Returns ``None`` when the passage does not pinch two ring vertices (nothing to cut).
    """
    if len(ring) < 4:
        return None
    ia = _portal_index(ring, ax, ay)
    ib = _portal_index(ring, bx, by)
    if ia is None or ib is None or ia == ib:
        return None

    ax, ay = float(ring[ia][0]), float(ring[ia][1])
    bx, by = float(ring[ib][0]), float(ring[ib][1])
    span = _dist(ax, ay, bx, by)
    if span < 2.0:
        return None
    dx, dy = (bx - ax) / span, (by - ay) / span
    nx, ny = -dy, dx

    hw = min(_portal_half_width(ring, ia, half_w), _portal_half_width(ring, ib, half_w))
    cx, cy = (ax + bx) * 0.5, (ay + by) * 0.5

    parts: list[list[list[float]]] = []
    for i_start, i_end in ((ia, ib), (ib, ia)):
        interior = _chain_interior(ring, i_start, i_end)
        if not interior:
            continue
        mx = sum(p[0] for p in interior) / len(interior)
        my = sum(p[1] for p in interior) / len(interior)
        sign = 1.0 if (mx - cx) * nx + (my - cy) * ny >= 0.0 else -1.0
        sx, sy = ring[i_start]
        ex, ey = ring[i_end]
        part = [
            [sx + sign * nx * hw, sy + sign * ny * hw],
            *interior,
            [ex + sign * nx * hw, ey + sign * ny * hw],
        ]
        if len(part) >= 3 and _ring_area(part) >= MIN_PART_AREA:
            parts.append(part)

    if len(parts) < 2:
        return None
    # Passage midpoint must sit outside both parts (open corridor).
    if any(_point_in_ring(cx, cy, part) for part in parts):
        return None
    return parts


def _passage_endpoints(road: dict[str, Any]) -> tuple[float, float, float, float] | None:
    pts = road.get("points") or []
    if len(pts) < 2:
        return None
    a, b = pts[0], pts[-1]
    return float(a[0]), float(a[1]), float(b[0]), float(b[1])


def _building_crosses_passage(ring: list[list[float]], ax: float, ay: float, bx: float, by: float) -> bool:
    """True when both portals snap to the ring and the mid-point lies inside it."""
    if _portal_index(ring, ax, ay) is None or _portal_index(ring, bx, by) is None:
        return False
    return _point_in_ring((ax + bx) * 0.5, (ay + by) * 0.5, ring)


def apply_building_passages(layout: dict[str, Any]) -> dict[str, int]:
    """Split buildings sealed across ``passage`` roads. Mutates ``layout['buildings']``."""
    roads = layout.get("roads") or []
    passages = [r for r in roads if r.get("passage")]
    stats = {"passages": len(passages), "buildings_split": 0, "parts": 0}
    if not passages:
        return stats

    buildings = list(layout.get("buildings") or [])
    out: list[dict[str, Any]] = []

    for bldg in buildings:
        ring = bldg.get("ring") or []
        bid = bldg.get("id")
        if len(ring) < 4:
            out.append(bldg)
            continue

        matched: list[list[list[float]]] | None = None
        for road in passages:
            ends = _passage_endpoints(road)
            if ends is None:
                continue
            ax, ay, bx, by = ends
            if not _building_crosses_passage(ring, ax, ay, bx, by):
                continue
            half = float(road.get("width") or 4.0) * 0.35
            half = max(MIN_HALF_W, min(PASSAGE_HALF_W, half))
            matched = cut_ring_for_passage(ring, ax, ay, bx, by, half_w=half)
            if matched:
                break

        if not matched:
            out.append(bldg)
            continue

        stats["buildings_split"] += 1
        for pi, part_ring in enumerate(matched):
            part = dict(bldg)
            part["ring"] = part_ring
            part["passage_cut"] = True
            if pi == 0:
                part["id"] = bid
            else:
                try:
                    part["id"] = int(bid) + PART_ID_OFFSET + (pi - 1)
                except (TypeError, ValueError):
                    part["id"] = f"{bid}_passage{pi}"
                part["parent_id"] = bid
            part.pop("street_edges", None)
            out.append(part)
            stats["parts"] += 1

    layout["buildings"] = out
    layout["passage_stats"] = stats
    return stats
