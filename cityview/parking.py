"""OSM-grounded kerbside parked cars.

The old builder dropped a box car every ~13 m on *both* kerbs of every residential /
secondary street within 150 m of the spawn, whether or not OSM says anyone may park
there. Those boxes sat inside the driving lane (the runtime traffic lane is 1.15 m off the
centreline) and read as a permanent traffic jam.

Reality model
-------------
* OSM tags kerbside parking per side of a way: ``parking:both`` / ``parking:left`` /
  ``parking:right`` = ``lane`` | ``street_side`` | ``on_kerb`` | ``half_on_kerb`` | ``yes``
  (allowed) or ``no`` / ``separate`` (not).  A way with no parking tag gets **no** cars.
* Only parallel parking (``parking:<side>:orientation`` = ``parallel`` or unset) is drawn;
  perpendicular / diagonal bays need a different footprint and are skipped, not guessed.
* A parked car never intrudes into the runtime driving lane: its inner edge stays clear
  of lane-centre + half a car width + a mirror's margin.  On narrow streets that pushes the
  car to the carriageway edge (a half-on-kerb park), exactly like a Belgian side street.
* Tram-shared carriageways get no cars (runtime lane is at the kerb there).
* Cars keep clear of junctions (other motor roads), pedestrian crossings, traffic signals,
  transit stops, tram beds and surveyed trees / benches / street clutter.

Pure stdlib: ``blender/build_city.py`` imports this inside Blender's Python and the unit
tests import it without ``bpy``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable, Iterable

from cityview.streetscape import _road_near_tram, _tram_segments

# Parking values that put a car at the kerb of the carriageway.
ALLOWED = frozenset({"lane", "street_side", "on_kerb", "half_on_kerb", "yes"})
DENIED = frozenset({"no", "separate", "no_parking", "no_stopping", "no_standing", "none"})
PARALLEL = frozenset({"", "parallel"})

# Highway kinds that are not motor carriageways: nobody parks a car on them, and they do
# not count as junction arms for clearance purposes.
NON_MOTOR = frozenset({"footway", "cycleway", "path", "pedestrian", "steps", "track", "corridor"})
NO_PARK_KINDS = NON_MOTOR | {"secondary_link", "primary_link", "tertiary_link", "motorway", "motorway_link"}

CAR_LEN = 4.2
CAR_WID = 1.75
HALF_LEN = CAR_LEN / 2.0
HALF_WID = CAR_WID / 2.0

# Runtime traffic lane centre (viewer/traffic.js LANE_OFFSET) + car half width + mirror gap.
LANE_CLEAR_CENTRE = 1.15 + HALF_WID + 0.15 + HALF_WID  # parked-car centre >= 3.05 m off the centreline
PARK_SLOT_M = 6.0  # one parallel bay (car + gap)
END_MARGIN_M = 6.0  # no parking right at the end of a way (junction / unmapped neighbour)
OCCUPANCY = 0.55  # fraction of bays with a car (kerbs are busy, not wall-to-wall)
JUNCTION_GAP_M = 0.4  # extra gap between a car's end and another street's edge
CROSSING_CLEAR_M = 4.5
SIGNAL_CLEAR_M = 12.0
STOP_CLEAR_M = 14.0
FURNITURE_CLEAR_M = 1.3
CAR_SPACING_M = 4.8  # centre-to-centre floor between any two parked cars
KERB_LIFT_M = 0.12  # pavement top: cars parked fully on the kerb ride up onto it


def _side_value(tags: dict[str, str], side: str) -> tuple[str, str]:
    """(parking type, orientation) for ``left`` / ``right``; type '' when unmapped."""
    kind = ""
    orient = ""
    for prefix in ("parking:both", f"parking:{side}"):  # the specific side wins
        v = (tags.get(prefix) or "").strip()
        if v:
            kind = v
        o = (tags.get(f"{prefix}:orientation") or "").strip()
        if o:
            orient = o
    return kind, orient


def parse_road_parking(tags: dict[str, str]) -> dict[str, dict[str, str]] | None:
    """Kerbside parking mapped on an OSM way, per side relative to the way direction.

    Returns ``{"left": {"type": ..., "orientation": ...}, "right": {...}}`` holding only
    the sides that carry a ``parking:*`` tag, or ``None`` when the way has none.
    """
    out: dict[str, dict[str, str]] = {}
    for side in ("left", "right"):
        kind, orient = _side_value(tags, side)
        if not kind:
            continue
        out[side] = {"type": kind, "orientation": orient}
    return out or None


def side_allows_car(info: dict[str, str] | None) -> bool:
    """True when a mapped side permits parallel parking at the kerb."""
    if not info:
        return False
    kind = (info.get("type") or "").strip()
    if kind in DENIED or kind not in ALLOWED:
        return False
    return (info.get("orientation") or "").strip() in PARALLEL


def _unit(*parts: object) -> float:
    """Deterministic 0..1 hash of a few values (stable across runs / platforms)."""
    h = 2166136261
    for part in parts:
        for ch in str(part):
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return (h % 100003) / 100003.0


def car_offset(half_width: float) -> float:
    """Centre offset from the way centreline for a parked car (always clear of the lane)."""
    return min(max(half_width - 0.9, LANE_CLEAR_CENTRE), half_width + 0.9)


class _Grid:
    """Tiny point spatial hash."""

    def __init__(self, cell: float = 8.0) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)

    def add(self, x: float, y: float) -> None:
        self.cells[(int(x // self.cell), int(y // self.cell))].append((x, y))

    def near(self, x: float, y: float, r: float) -> bool:
        c = self.cell
        r2 = r * r
        for gx in range(int((x - r) // c), int((x + r) // c) + 1):
            for gy in range(int((y - r) // c), int((y + r) // c) + 1):
                for px, py in self.cells.get((gx, gy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r2:
                        return True
        return False


def _seg_dist(px: float, py: float, a: list[float], b: list[float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    t = 0.0 if den <= 1e-12 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / den))
    return math.hypot(px - a[0] - t * dx, py - a[1] - t * dy)


def _polyline_len(pts: list[list[float]]) -> float:
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def _point_at(pts: list[list[float]], s: float) -> tuple[float, float, float, float]:
    """(x, y, tx, ty) at arc length ``s`` along the polyline (unit tangent)."""
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if seg <= 1e-9:
            continue
        if s <= seg or i == len(pts) - 2:
            f = min(max(s / seg, 0.0), 1.0)
            tx = (pts[i + 1][0] - pts[i][0]) / seg
            ty = (pts[i + 1][1] - pts[i][1]) / seg
            return pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f, tx, ty
        s -= seg
    x, y = pts[-1]
    return x, y, 1.0, 0.0


def _endpoints(road: dict[str, Any]) -> set[tuple[int, int]]:
    pts = road.get("points") or []
    if len(pts) < 2:
        return set()
    return {(round(pts[0][0] * 2), round(pts[0][1] * 2)), (round(pts[-1][0] * 2), round(pts[-1][1] * 2))}


def plan_parked_cars(
    layout: dict[str, Any],
    spawn_xy: tuple[float, float] | None,
    radius: float = 150.0,
    max_cars: int = 64,
    blocked: Callable[[float, float], bool] | None = None,
) -> list[dict[str, Any]]:
    """Parked cars (centre, yaw, road id, side) only where OSM maps parallel kerb parking.

    ``blocked(x, y)`` lets the builder veto a spot (tram beds).  Returned cars never
    overlap each other and keep ``LANE_CLEAR_CENTRE`` off the way centreline.
    """
    roads = layout.get("roads") or []
    motor = [r for r in roads if (r.get("kind") or "residential") not in NON_MOTOR and len(r.get("points") or []) >= 2]
    ends = {id(r): _endpoints(r) for r in motor}
    tram_segs = _tram_segments(layout)

    crossings = _Grid()
    for c in layout.get("crossings") or []:
        crossings.add(float(c["x"]), float(c["y"]))
    signals = _Grid()
    for s in layout.get("signals") or []:
        signals.add(float(s["x"]), float(s["y"]))
    stops = _Grid()
    for s in layout.get("transit_stops") or []:
        if s.get("x") is not None and s.get("y") is not None:
            stops.add(float(s["x"]), float(s["y"]))
    furniture = _Grid()
    for key in ("trees", "benches", "clutter"):
        for item in layout.get(key) or []:
            if item.get("x") is not None and item.get("y") is not None:
                furniture.add(float(item["x"]), float(item["y"]))

    placed: list[dict[str, Any]] = []
    placed_grid = _Grid()

    def near_road(r: dict[str, Any]) -> bool:
        if spawn_xy is None:
            return True
        return any(math.hypot(p[0] - spawn_xy[0], p[1] - spawn_xy[1]) <= radius + 120.0 for p in r["points"])

    for road in sorted(motor, key=lambda r: int(r.get("id") or 0)):
        kind = road.get("kind") or "residential"
        parking = road.get("parking")
        if kind in NO_PARK_KINDS or not parking or not near_road(road):
            continue
        pts = road["points"]
        # Tram-shared carriageway: the runtime car lane sits at the kerb (2.4 m), so there is no
        # room for a parked car without blocking the lane (and trams already run on the street).
        if _road_near_tram(pts, tram_segs):
            continue
        length = _polyline_len(pts)
        if length < 2 * END_MARGIN_M + CAR_LEN:
            continue
        half = float(road.get("width") or 6.0) * 0.5
        rid = int(road.get("id") or 0)
        centre_off = car_offset(half)
        my_name = road.get("name") or ""
        # Side streets / alleys that could be blocked by a parked car at this road's kerb.
        others: list[tuple[dict[str, Any], float]] = []
        for other in motor:
            if other is road:
                continue
            if my_name and other.get("name") == my_name and ends[id(other)] & ends[id(road)]:
                continue  # the same street carrying on: not a junction arm
            others.append((other, float(other.get("width") or 6.0) * 0.5))

        for side, sign in (("left", 1.0), ("right", -1.0)):
            if not side_allows_car(parking.get(side)):
                continue
            n_slots = int((length - 2 * END_MARGIN_M) // PARK_SLOT_M)
            lead = END_MARGIN_M + ((length - 2 * END_MARGIN_M) - n_slots * PARK_SLOT_M) * 0.5
            for k in range(n_slots):
                if _unit(rid, side, k) > OCCUPANCY:
                    continue
                s = lead + (k + 0.5) * PARK_SLOT_M
                cx, cy, tx, ty = _point_at(pts, s)
                x = cx + (-ty) * sign * centre_off
                y = cy + tx * sign * centre_off
                if spawn_xy is not None and math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > radius:
                    continue
                if len(placed) >= max_cars:
                    return placed
                # Right-hand traffic: cars parked on the way's right face along it, on the left against it.
                yaw = math.atan2(ty, tx) + (0.0 if side == "right" else math.pi)
                if _blocked_spot(x, y, tx, ty, crossings, signals, stops, furniture, placed_grid, blocked):
                    continue
                if any(
                    min(_seg_dist(x, y, o["points"][i], o["points"][i + 1]) for i in range(len(o["points"]) - 1))
                    < ow + HALF_LEN + JUNCTION_GAP_M
                    for o, ow in others
                    if _bbox_near(o["points"], x, y, ow + HALF_LEN + JUNCTION_GAP_M)
                ):
                    continue
                lift = KERB_LIFT_M if centre_off - HALF_WID > half + 0.1 else 0.0
                placed.append(
                    {
                        "x": round(x, 3),
                        "y": round(y, 3),
                        "yaw": round(yaw, 4),
                        "road_id": rid,
                        "side": side,
                        "parking": (parking.get(side) or {}).get("type", ""),
                        "lift": lift,
                    }
                )
                placed_grid.add(x, y)
    return placed


def _bbox_near(pts: list[list[float]], x: float, y: float, r: float) -> bool:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) - r <= x <= max(xs) + r and min(ys) - r <= y <= max(ys) + r


def _blocked_spot(
    x: float,
    y: float,
    tx: float,
    ty: float,
    crossings: _Grid,
    signals: _Grid,
    stops: _Grid,
    furniture: _Grid,
    placed_grid: _Grid,
    blocked: Callable[[float, float], bool] | None,
) -> bool:
    if crossings.near(x, y, CROSSING_CLEAR_M + HALF_LEN * 0.5):
        return True
    if signals.near(x, y, SIGNAL_CLEAR_M):
        return True
    if stops.near(x, y, STOP_CLEAR_M):
        return True
    if placed_grid.near(x, y, CAR_SPACING_M):
        return True
    for d in (-1.4, 0.0, 1.4):  # nose, middle, tail of the car
        px, py = x + tx * d, y + ty * d
        if furniture.near(px, py, FURNITURE_CLEAR_M):
            return True
        if blocked is not None and blocked(px, py):
            return True
    return False


def summarize(cars: Iterable[dict[str, Any]]) -> str:
    cars = list(cars)
    by_type: dict[str, int] = defaultdict(int)
    for car in cars:
        by_type[car.get("parking") or "?"] += 1
    kinds = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
    return f"{len(cars)} parked cars ({kinds or 'none'})"
