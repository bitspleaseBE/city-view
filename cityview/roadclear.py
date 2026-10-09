"""Carriageway clearance for trees (the road counterpart of ``cityview.railclear``).

Pure stdlib on purpose: ``cityview.trees`` plans placement with it, ``blender/trees_blender.py``
re-checks with it inside Blender's Python, and the tests import it without ``bpy``.

Reality model (Antwerp streets)
-------------------------------
* A street tree stands in a pit in the *pavement* (or a verge / park), never in a driving
  lane.  The builder draws every driveable way as an asphalt ribbon of ``width`` metres
  centred on the OSM line, then a kerb (``half + 0.12``, 0.28 m wide) and a 2 m pavement
  outside it.  A trunk therefore has to stand at least ``TRUNK_MARGIN`` beyond the
  asphalt edge: past the kerb stone and with the whole trunk (up to ~0.4 m radius) on
  the pavement.
* Municipal survey points are good to a metre or two, and OSM's nominal road width is a
  guess, so a surveyed trunk can land a little inside the drawn carriageway.  Rather than
  leaving it in the lane it is snapped to the nearest legal spot (pavement, verge, park)
  within ``SNAP_MAX_M``; if no such spot exists it is dropped.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable

# Ways drawn as asphalt a vehicle (or cyclist) can use.  Footways, paths and steps are
# pedestrian-only surfaces, so a tree beside/over them is not "in the road".
CARRIAGEWAY_KINDS = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service", "pedestrian", "cycleway", "track",
    }
)

# Trunk centre must stand this far outside the drawn asphalt edge (kerb 0.28 m + trunk).
TRUNK_MARGIN = 0.65
# A surveyed trunk is moved at most this far to reach legal ground (otherwise dropped).
SNAP_MAX_M = 4.5
SNAP_STEP_M = 0.25
SNAP_ANGLES = 24

_CELL = 24.0


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class RoadIndex:
    """Grid-bucketed signed-distance queries against drawn carriageway edges."""

    def __init__(self, roads: Iterable[dict[str, Any]]):
        self.segments: list[tuple[float, float, float, float, float]] = []
        self._grid: dict[tuple[int, int], list[int]] = {}
        for road in roads:
            if (road.get("kind") or "residential") not in CARRIAGEWAY_KINDS:
                continue
            pts = road.get("points") or []
            half = float(road.get("width") or 6.0) * 0.5
            for i in range(len(pts) - 1):
                ax, ay = float(pts[i][0]), float(pts[i][1])
                bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
                idx = len(self.segments)
                self.segments.append((ax, ay, bx, by, half))
                pad = half
                for cx in range(int(math.floor((min(ax, bx) - pad) / _CELL)), int(math.floor((max(ax, bx) + pad) / _CELL)) + 1):
                    for cy in range(int(math.floor((min(ay, by) - pad) / _CELL)), int(math.floor((max(ay, by) + pad) / _CELL)) + 1):
                        self._grid.setdefault((cx, cy), []).append(idx)

    @classmethod
    def from_layout(cls, layout: dict[str, Any]) -> "RoadIndex":
        return cls(layout.get("roads") or [])

    def __bool__(self) -> bool:
        return bool(self.segments)

    def _nearest(self, x: float, y: float) -> tuple[float, tuple[float, float, float, float, float] | None]:
        cx, cy = int(math.floor(x / _CELL)), int(math.floor(y / _CELL))
        best = math.inf
        best_seg = None
        seen: set[int] = set()
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for idx in self._grid.get((gx, gy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    seg = self.segments[idx]
                    d = _seg_dist(x, y, seg[0], seg[1], seg[2], seg[3]) - seg[4]
                    if d < best:
                        best, best_seg = d, seg
        return best, best_seg

    def clearance(self, x: float, y: float) -> float:
        """Distance to the nearest drawn asphalt edge (negative = on the carriageway)."""
        return self._nearest(x, y)[0]

    def on_carriageway(self, x: float, y: float, margin: float = 0.0) -> bool:
        """True if ``(x, y)`` is on the asphalt or closer than ``margin`` to its edge."""
        return self.clearance(x, y) < margin

    def away_direction(self, x: float, y: float) -> tuple[float, float]:
        """Unit vector pointing from the nearest road centreline toward ``(x, y)``."""
        _, seg = self._nearest(x, y)
        if seg is None:
            return (1.0, 0.0)
        ax, ay, bx, by, _half = seg
        dx, dy = bx - ax, by - ay
        len2 = dx * dx + dy * dy
        t = 0.0 if len2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / len2))
        vx, vy = x - (ax + t * dx), y - (ay + t * dy)
        n = math.hypot(vx, vy)
        if n < 1e-6:  # dead on the centreline: pick the left-hand normal, deterministically
            ln = math.sqrt(len2) or 1.0
            return (-dy / ln, dx / ln)
        return (vx / n, vy / n)


def snap_off_carriageway(
    x: float,
    y: float,
    roads: RoadIndex,
    ok: Callable[[float, float], bool],
    *,
    margin: float = TRUNK_MARGIN,
    max_move: float = SNAP_MAX_M,
) -> tuple[float, float] | None:
    """Nearest legal ground to ``(x, y)``: clear of the asphalt by ``margin`` and ``ok``.

    Candidates are tried on growing rings, starting in the direction away from the road the
    point sits on (so a tree moves to its own kerb's pavement, not across the street).
    ``ok(x, y)`` carries the other obstacles (buildings, tram bed, neighbouring trees).
    Returns ``None`` when no such spot exists within ``max_move`` metres.
    """
    if roads.clearance(x, y) >= margin and ok(x, y):
        return (x, y)
    ux, uy = roads.away_direction(x, y)
    base = math.atan2(uy, ux)
    # Offsets 0, +15, -15, +30, ... so ties resolve toward the "away" side.
    order = [0.0]
    for k in range(1, SNAP_ANGLES // 2 + 1):
        step = k * math.tau / SNAP_ANGLES
        order.extend((step, -step) if k < SNAP_ANGLES // 2 else (step,))
    r = SNAP_STEP_M
    while r <= max_move + 1e-9:
        for off in order:
            ang = base + off
            px, py = x + math.cos(ang) * r, y + math.sin(ang) * r
            if roads.clearance(px, py) >= margin and ok(px, py):
                return (px, py)
        r += SNAP_STEP_M
    return None
