"""Rail-corridor clearance helpers shared by the Blender builder and tests.

Pure stdlib on purpose: ``blender/build_city.py`` imports this module inside
Blender's Python, and unit tests import it without ``bpy``.

Reality model (Belgian urban tram streets)
------------------------------------------
* Trams run on a ~2.4 m wide bed, either inside the carriageway (shared) or on a
  reserved track. Either way nothing planted or street-furnished may sit on it.
* A pedestrian crossing that OSM maps over tram tracks is legitimate; it must be
  drawn *on top of* the rails. Decorative zebras derived from traffic signals are
  not placed across rail corridors unless OSM also maps a crossing there.
* Underground (``tunnel``) tram / premetro ways must not be drawn on the surface.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

RAIL_MODES = frozenset({"tram", "subway", "light_rail", "rail"})

# Bed half-width used by the builder (bed ribbon is 2.4 m, premetro 2.8 m).
BED_HALF_TRAM = 1.2
BED_HALF_SUBWAY = 1.4

# Clearance from the rail centreline (metres) per object class.
CLEAR_TREE = 3.4  # trunk + canopy radius
CLEAR_FURNITURE = 2.1  # lamps, bins, benches, bollards, racks
CLEAR_PARKED_CAR = 2.6
CLEAR_SIDEWALK = 2.4  # sidewalk ribbon is 2 m wide (half 1.0) + bed half 1.2
CLEAR_CURB = 1.55
CLEAR_MARKING = 1.5  # dashes / wear patches
CLEAR_SIGNAL_POLE = 1.7
# Zebra stripes whose centre-line lands this close to a rail are "on rails".
CLEAR_ZEBRA = 1.7

# An OSM pedestrian crossing node this close to a rail is a rail crossing.
RAIL_CROSSING_SNAP = 7.0

_CELL = 24.0


def _is_underground(line: dict[str, Any]) -> bool:
    return bool(line.get("tunnel"))


def surface_rail_polylines(layout: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Surface tram/premetro polylines (any source; tunnels excluded)."""
    out: list[list[tuple[float, float]]] = []
    for line in layout.get("transit_lines") or []:
        if (line.get("mode") or "") not in RAIL_MODES:
            continue
        if _is_underground(line):
            continue
        pts = [(float(p[0]), float(p[1])) for p in (line.get("points") or [])]
        if len(pts) >= 2:
            out.append(pts)
    return out


def point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class RailIndex:
    """Grid-bucketed distance queries against surface rail segments."""

    def __init__(self, polylines: Iterable[list[tuple[float, float]]]):
        self.segments: list[tuple[float, float, float, float]] = []
        self._grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for pts in polylines:
            for i in range(len(pts) - 1):
                self._add(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])

    @classmethod
    def from_layout(cls, layout: dict[str, Any]) -> "RailIndex":
        return cls(surface_rail_polylines(layout))

    def __bool__(self) -> bool:
        return bool(self.segments)

    def _add(self, ax: float, ay: float, bx: float, by: float) -> None:
        idx = len(self.segments)
        self.segments.append((ax, ay, bx, by))
        c0x, c1x = sorted((int(math.floor(ax / _CELL)), int(math.floor(bx / _CELL))))
        c0y, c1y = sorted((int(math.floor(ay / _CELL)), int(math.floor(by / _CELL))))
        for cx in range(c0x, c1x + 1):
            for cy in range(c0y, c1y + 1):
                self._grid[(cx, cy)].append(idx)

    def distance(self, x: float, y: float, limit: float = 60.0) -> float:
        """Distance to the nearest rail segment (``inf`` beyond ``limit``)."""
        if not self.segments:
            return math.inf
        reach = int(math.ceil(limit / _CELL))
        cx0, cy0 = int(math.floor(x / _CELL)), int(math.floor(y / _CELL))
        seen: set[int] = set()
        best = math.inf
        for cx in range(cx0 - reach, cx0 + reach + 1):
            for cy in range(cy0 - reach, cy0 + reach + 1):
                for idx in self._grid.get((cx, cy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    ax, ay, bx, by = self.segments[idx]
                    d = point_segment_distance(x, y, ax, ay, bx, by)
                    if d < best:
                        best = d
        return best if best <= limit else math.inf

    def within(self, x: float, y: float, clearance: float) -> bool:
        return self.distance(x, y, limit=clearance + 1.0) <= clearance

    def nearest_tangent(self, x: float, y: float, limit: float = 30.0) -> tuple[float, float] | None:
        """Unit tangent of the nearest rail segment."""
        best = math.inf
        tan: tuple[float, float] | None = None
        reach = int(math.ceil(limit / _CELL))
        cx0, cy0 = int(math.floor(x / _CELL)), int(math.floor(y / _CELL))
        for cx in range(cx0 - reach, cx0 + reach + 1):
            for cy in range(cy0 - reach, cy0 + reach + 1):
                for idx in self._grid.get((cx, cy), ()):
                    ax, ay, bx, by = self.segments[idx]
                    d = point_segment_distance(x, y, ax, ay, bx, by)
                    if d < best:
                        length = math.hypot(bx - ax, by - ay) or 1.0
                        best = d
                        tan = ((bx - ax) / length, (by - ay) / length)
        return tan if best <= limit else None


def densify(points: list[list[float]], step: float = 2.0) -> list[list[float]]:
    """Resample a polyline so no segment exceeds ``step`` metres."""
    if len(points) < 2:
        return [list(p) for p in points]
    out: list[list[float]] = [[float(points[0][0]), float(points[0][1])]]
    for i in range(len(points) - 1):
        ax, ay = float(points[i][0]), float(points[i][1])
        bx, by = float(points[i + 1][0]), float(points[i + 1][1])
        seg = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(seg / step)))
        for k in range(1, n + 1):
            t = k / n
            out.append([ax + (bx - ax) * t, ay + (by - ay) * t])
    return out


def polyline_near_rails(points: list[list[float]], index: RailIndex, margin: float = 30.0) -> bool:
    if not index or len(points) < 2:
        return False
    for p in densify(points, 12.0):
        if index.distance(p[0], p[1], limit=margin) < math.inf:
            return True
    return False


def clear_runs(
    points: list[list[float]],
    index: RailIndex,
    clearance: float,
    *,
    step: float = 2.0,
) -> list[list[list[float]]]:
    """Split a ribbon centreline into runs that keep ``clearance`` from rails.

    Polylines that never come near a rail are returned untouched (single run).
    """
    if not index or not polyline_near_rails(points, index, margin=clearance + 12.0):
        return [points] if len(points) >= 2 else []
    dense = densify(points, step)
    runs: list[list[list[float]]] = []
    cur: list[list[float]] = []
    for p in dense:
        if index.within(p[0], p[1], clearance):
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
        else:
            cur.append(p)
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def span_intervals(
    cx: float,
    cy: float,
    ux: float,
    uy: float,
    span: float,
    index: RailIndex,
    clearance: float = CLEAR_ZEBRA,
    *,
    step: float = 0.4,
) -> list[tuple[float, float, bool]]:
    """Split a stripe's long axis into ``(t0, t1, on_rail)`` pieces.

    The stripe runs from ``-span/2`` to ``+span/2`` along unit vector (ux, uy)
    through (cx, cy). ``on_rail`` pieces overlap the rail corridor.
    """
    half = span * 0.5
    n = max(1, int(math.ceil(span / step)))
    flags: list[bool] = []
    for k in range(n):
        t = -half + (k + 0.5) * span / n
        flags.append(index.within(cx + ux * t, cy + uy * t, clearance) if index else False)
    out: list[tuple[float, float, bool]] = []
    start = 0
    for k in range(1, n + 1):
        if k == n or flags[k] != flags[start]:
            out.append((-half + start * span / n, -half + k * span / n, flags[start]))
            start = k
    return out


def zebra_touches_rails(
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    span: float,
    index: RailIndex,
    *,
    along: tuple[float, ...] = (-1.6, -0.8, 0.0, 0.8, 1.6),
) -> bool:
    """True if any stripe of a signal-approach zebra overlaps a rail corridor."""
    if not index:
        return False
    ux, uy = -ty, tx  # across the carriageway
    for a in along:
        cx, cy = sx + tx * a, sy + ty * a
        if any(on for _t0, _t1, on in span_intervals(cx, cy, ux, uy, span, index)):
            return True
    return False


def nearest_crossing_node(
    x: float, y: float, crossings: list[dict[str, Any]], radius: float
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_d = radius
    for node in crossings:
        d = math.hypot(float(node["x"]) - x, float(node["y"]) - y)
        if d <= best_d:
            best, best_d = node, d
    return best


def rail_crossing_nodes(layout: dict[str, Any], index: RailIndex) -> list[dict[str, Any]]:
    """OSM pedestrian-crossing nodes that sit on/next to surface rails."""
    if not index:
        return []
    return [
        node
        for node in layout.get("crossings") or []
        if index.within(float(node["x"]), float(node["y"]), RAIL_CROSSING_SNAP)
    ]
