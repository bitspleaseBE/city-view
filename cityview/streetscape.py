"""Street-facing edges, roof shapes, and spawn helpers for district LOD2."""

from __future__ import annotations

import math
from typing import Any

from cityview.building_heights import FLOOR_H, MAX_EAVES_M, MAX_LEVELS
from cityview.directions import infer_parallel_track_directions, mark_dual_carriageways


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def _point_segment_dist(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return _dist(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return _dist(px, py, ax + t * dx, ay + t * dy)


def _centroid(ring: list[list[float]]) -> tuple[float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    n = max(1, len(ring))
    return (sum(xs) / n, sum(ys) / n)


def floors_from_height(height: float, tags: dict[str, str] | None = None) -> int:
    tags = tags or {}
    raw = tags.get("building:levels")
    if raw:
        try:
            return max(1, min(MAX_LEVELS, int(round(float(raw.split(";")[0])))))
        except ValueError:
            pass
    return max(1, min(MAX_LEVELS, int(round(height / FLOOR_H))))


def roof_shape_for(tags: dict[str, str], style: str, osm_id: int) -> str:
    tagged = (tags.get("roof:shape") or "").lower().strip()
    aliases = {
        "gabled": "gable",
        "hipped": "hip",
        "pyramidal": "hip",
        "skillion": "flat",
        "flat": "flat",
        "mansard": "mansard",
        "gambrel": "mansard",
        "half-hipped": "hip",
        "round": "hip",
    }
    if tagged in aliases:
        return aliases[tagged]
    if tagged in {"gable", "hip", "mansard", "flat"}:
        return tagged

    if style in {
        "international",
        "art-deco",
        "modern-infill",
        "white-modern",
        "prefab-70s",
        "supermarket",
        "hospital",
    }:
        return "flat"
    if style in {"neo-flemish", "art-nouveau", "red-brick"}:
        return "gable" if (osm_id % 3) else "mansard"
    if style == "yellow-brick":
        return "gable" if (osm_id % 2) else "mansard"
    if style in {"neo-gothic", "church", "school"}:
        return "hip"
    if style == "restaurant":
        return "mansard" if (osm_id % 5) < 3 else "gable"
    # neoclassical / eclectic / cream-tile default: mansard or gable
    return "mansard" if (osm_id % 5) < 3 else "gable"


def ring_signed_area(ring: list[list[float]]) -> float:
    n = len(ring)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1):
            inside = not inside
    return inside


def footprint_supports_prism_roof(ring: list[list[float]], min_fill: float = 0.82) -> bool:
    """True when an OBB gable/hip prism stays mostly inside the wall ring.

    L-shaped / concave / highly irregular footprints fail — use mansard/flat instead.
    """
    if len(ring) < 3:
        return False
    cx, cy = _centroid(ring)
    cov_xx = cov_xy = cov_yy = 0.0
    for x, y in ring:
        dx, dy = x - cx, y - cy
        cov_xx += dx * dx
        cov_xy += dx * dy
        cov_yy += dy * dy
    n = max(1, len(ring))
    cov_xx /= n
    cov_xy /= n
    cov_yy /= n
    trace = cov_xx + cov_yy
    det = cov_xx * cov_yy - cov_xy * cov_xy
    gap = math.sqrt(max(0.0, trace * trace * 0.25 - det))
    l1 = trace * 0.5 + gap
    if abs(cov_xy) > 1e-9:
        ux, uy = l1 - cov_yy, cov_xy
    else:
        ux, uy = (1.0, 0.0) if cov_xx >= cov_yy else (0.0, 1.0)
    ulen = math.hypot(ux, uy) or 1.0
    ux, uy = ux / ulen, uy / ulen
    vx, vy = -uy, ux
    hu = hv = 0.0
    for x, y in ring:
        dx, dy = x - cx, y - cy
        hu = max(hu, abs(dx * ux + dy * uy))
        hv = max(hv, abs(dx * vx + dy * vy))
    if hu < hv:
        ux, uy, vx, vy = vx, vy, ux, uy
        hu, hv = hv, hu
    hu = max(hu, 0.8)
    hv = max(hv, 0.8)
    ring_area = abs(ring_signed_area(ring))
    obb_area = 4.0 * hu * hv
    if obb_area < 1e-3:
        return False
    if ring_area / obb_area < min_fill:
        return False
    # Near-corner samples of the OBB must lie inside the footprint.
    for su, sv in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
        ix = cx + su * hu * 0.92 * ux + sv * hv * 0.92 * vx
        iy = cy + su * hu * 0.92 * uy + sv * hv * 0.92 * vy
        if not point_in_ring(ix, iy, ring):
            return False
    return True


def safe_roof_shape(shape: str, ring: list[list[float]]) -> str:
    """Demote gable/hip to mansard when the footprint cannot host an OBB prism."""
    if shape in {"gable", "hip"} and not footprint_supports_prism_roof(ring):
        return "mansard"
    return shape


def height_truth(tags: dict[str, str]) -> tuple[float, float, int]:
    """Return (eaves_height_m, roof_height_m, floors) from OSM tags."""
    floor_h = 3.15
    floors: int | None = None
    eaves: float | None = None
    roof_h = 0.0

    raw_h = tags.get("height")
    if raw_h:
        try:
            total = float(raw_h.replace("m", "").split()[0])
            eaves = max(4.0, min(MAX_EAVES_M, total))
        except ValueError:
            pass

    levels = tags.get("building:levels")
    if levels:
        try:
            floors = max(1, min(MAX_LEVELS, int(round(float(levels.split(";")[0])))))
        except ValueError:
            pass

    roof_levels = tags.get("roof:levels")
    if roof_levels:
        try:
            roof_h = max(0.0, float(roof_levels.split(";")[0]) * 2.4)
        except ValueError:
            pass

    raw_roof = tags.get("roof:height")
    if raw_roof:
        try:
            roof_h = max(0.0, float(raw_roof.replace("m", "").split()[0]))
        except ValueError:
            pass

    kind = tags.get("building", "yes")
    defaults = {
        "house": 11.2,
        "terrace": 12.0,
        "residential": 12.4,
        "apartments": 16.5,
        "commercial": 14.0,
        "retail": 11.0,
        "industrial": 10.0,
        "warehouse": 9.0,
        "church": 28.0,
        "cathedral": 42.0,
        "basilica": 32.0,
        "chapel": 18.0,
        "school": 14.0,
        "hospital": 18.0,
        "supermarket": 8.0,
        "garage": 4.5,
        "shed": 3.5,
        "semidetached_house": 11.5,
        "detached": 11.0,
    }

    if floors is None and eaves is not None:
        floors = max(1, min(MAX_LEVELS, int(round(eaves / floor_h))))
    if floors is None:
        eaves = eaves if eaves is not None else defaults.get(kind, 12.0)
        floors = max(1, min(MAX_LEVELS, int(round(eaves / floor_h))))
    if eaves is None:
        eaves = floors * floor_h

    # If total height included roof, peel a bit for roof mass when roof:shape suggests it.
    if roof_h <= 0.0 and tags.get("roof:shape") not in {None, "", "flat"}:
        roof_h = min(4.0, max(1.2, eaves * 0.16))
        eaves = max(4.0, eaves - roof_h * 0.35)

    return (float(eaves), float(roof_h), int(floors))


def _road_segments(roads: list[dict[str, Any]]) -> list[tuple[float, float, float, float, float]]:
    segs: list[tuple[float, float, float, float, float]] = []
    for road in roads:
        pts = road.get("points") or []
        half = float(road.get("width") or 6.0) * 0.5
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            segs.append((x1, y1, x2, y2, half + 5.5))
    return segs


def street_facing_edges(
    ring: list[list[float]],
    segments: list[tuple[float, float, float, float, float]],
    min_length: float = 2.8,
) -> list[dict[str, Any]]:
    """Return ring edge indices that face a nearby road (outward toward asphalt)."""
    if len(ring) < 3 or not segments:
        return []
    cx, cy = _centroid(ring)
    edges: list[dict[str, Any]] = []
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        length = _dist(x1, y1, x2, y2)
        if length < min_length:
            continue
        mx, my = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        ex, ey = x2 - x1, y2 - y1
        # Left normal; flip so it points away from centroid.
        nx, ny = -ey / length, ex / length
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        probe_x, probe_y = mx + nx * 3.0, my + ny * 3.0
        for ax, ay, bx, by, reach in segments:
            if _point_segment_dist(probe_x, probe_y, ax, ay, bx, by) <= reach:
                edges.append(
                    {
                        "i0": i,
                        "i1": (i + 1) % n,
                        "length": round(length, 3),
                        "outward": [round(nx, 5), round(ny, 5)],
                    }
                )
                break
    return edges


def annotate_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """Attach street_edges to buildings using road proximity."""
    segments = _road_segments(layout.get("roads") or [])
    for bldg in layout.get("buildings") or []:
        ring = bldg.get("ring") or []
        bldg["street_edges"] = street_facing_edges(ring, segments)
    return layout


def nearest_road_pose(
    x: float, y: float, roads: list[dict[str, Any]]
) -> tuple[float, float, float]:
    """Snap (x,y) to the nearest road centreline; return (sx, sy, yaw)."""
    best = 1e18
    sx, sy, yaw = x, y, 0.0
    for road in roads:
        pts = road.get("points") or []
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 < 1e-9:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / len2))
            px, py = ax + t * dx, ay + t * dy
            d = _dist(x, y, px, py)
            if d < best:
                best = d
                # Stand on the carriageway near the address, not inside the footprint.
                sx, sy = px, py
                yaw = math.atan2(dy, dx)
    return sx, sy, yaw


def nearest_road_yaw(x: float, y: float, roads: list[dict[str, Any]]) -> float:
    """Yaw (radians around Z) along the nearest road tangent at (x, y)."""
    _sx, _sy, yaw = nearest_road_pose(x, y, roads)
    return yaw


DRIVEABLE_ROAD_KINDS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
    }
)

# Never put these on the car graph (tram/rail/pedestrian/service alleys).
NON_DRIVEABLE_ROAD_KINDS = frozenset(
    {
        "tram",
        "rail",
        "light_rail",
        "subway",
        "narrow_gauge",
        "platform",
        "footway",
        "path",
        "cycleway",
        "steps",
        "pedestrian",
        "service",
        "bus_guideway",
        "corridor",
        "construction",
        "proposed",
        "raceway",
        "bridleway",
        "elevator",
    }
)

_TRAM_TRANSIT_MODES = frozenset({"tram", "subway", "light_rail", "rail"})

# Belgian urban defaults (km/h) when OSM carries no maxspeed. Antwerp centre is
# largely a 30 zone; arterials are 50.
DEFAULT_URBAN_SPEED_KMH = {
    "motorway": 70.0,
    "motorway_link": 50.0,
    "trunk": 50.0,
    "trunk_link": 50.0,
    "primary": 50.0,
    "primary_link": 40.0,
    "secondary": 50.0,
    "secondary_link": 40.0,
    "tertiary": 50.0,
    "tertiary_link": 40.0,
    "unclassified": 30.0,
    "residential": 30.0,
    "living_street": 20.0,
}
_MIN_SPEED_KMH = 5.0
_MAX_SPEED_KMH = 120.0


def parse_maxspeed_kmh(tags: dict[str, str] | None) -> float | None:
    """Parse an OSM ``maxspeed`` tag to km/h, or ``None`` if absent/unusable.

    Handles ``"30"``, ``"50 km/h"``, ``"20 mph"``, ``"walk"`` and ``"BE:urban"``
    style implicit values. Lists (``"30;50"``) take the lowest value.
    """
    if not tags:
        return None
    raw = tags.get("maxspeed") or tags.get("maxspeed:forward") or tags.get("maxspeed:backward")
    if not raw:
        return None
    best: float | None = None
    for part in str(raw).replace(",", ";").split(";"):
        text = part.strip().lower()
        if not text:
            continue
        value: float | None = None
        if text == "walk":
            value = 7.0
        elif text.endswith("urban") or text.endswith(":urban"):
            value = 50.0
        else:
            num = ""
            for ch in text:
                if ch.isdigit() or (ch == "." and "." not in num):
                    num += ch
                elif num:
                    break
            if num:
                try:
                    value = float(num)
                except ValueError:
                    value = None
                if value is not None and "mph" in text:
                    value *= 1.609344
        if value is None or value <= 0:
            continue
        value = max(_MIN_SPEED_KMH, min(_MAX_SPEED_KMH, value))
        best = value if best is None else min(best, value)
    return best


def road_speed_kmh(kind: str, maxspeed_kmh: float | None) -> float:
    """Effective cruising limit: tagged maxspeed, else a Belgian urban default."""
    if maxspeed_kmh is not None and maxspeed_kmh > 0:
        return float(maxspeed_kmh)
    return DEFAULT_URBAN_SPEED_KMH.get(str(kind or "").lower(), 30.0)


def _tram_way_ids(layout: dict[str, Any]) -> set[Any]:
    ids: set[Any] = set()
    for line in layout.get("transit_lines") or []:
        mode = (line.get("mode") or "").lower()
        if mode in _TRAM_TRANSIT_MODES:
            ids.add(line.get("id"))
    return ids


def _road_near_tram(
    pts: list[list[float]],
    tram_segs: list[tuple[float, float, float, float]],
    *,
    sample_n: int = 6,
    avg_thresh: float = 3.5,
) -> bool:
    """True when a highway centreline hugs tram rails (shared corridor)."""
    if not tram_segs or len(pts) < 2:
        return False
    samples: list[tuple[float, float]] = []
    for i in range(sample_n):
        t = i / max(1, sample_n - 1)
        idx = t * (len(pts) - 1)
        i0 = int(idx)
        i1 = min(len(pts) - 1, i0 + 1)
        f = idx - i0
        samples.append(
            (
                float(pts[i0][0]) * (1 - f) + float(pts[i1][0]) * f,
                float(pts[i0][1]) * (1 - f) + float(pts[i1][1]) * f,
            )
        )
    total = 0.0
    for px, py in samples:
        best = min(
            _point_segment_dist(px, py, ax, ay, bx, by) for ax, ay, bx, by in tram_segs
        )
        total += best
    return (total / len(samples)) <= avg_thresh


def _tram_segments(layout: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    segs: list[tuple[float, float, float, float]] = []
    for line in layout.get("transit_lines") or []:
        if (line.get("mode") or "").lower() not in _TRAM_TRANSIT_MODES:
            continue
        pts = line.get("points") or []
        for i in range(1, len(pts)):
            segs.append(
                (
                    float(pts[i - 1][0]),
                    float(pts[i - 1][1]),
                    float(pts[i][0]),
                    float(pts[i][1]),
                )
            )
    return segs


def _direction_code(value: Any) -> int:
    """Normalise a travel-direction code to 1 (along points) / -1 (against) / 0 (both)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return 1 if n > 0 else (-1 if n < 0 else 0)


def export_roads_near_spawn(
    layout: dict[str, Any],
    spawn: dict[str, Any] | None,
    *,
    radius: float = 280.0,
    max_roads: int = 60,
) -> dict[str, Any]:
    """Lightweight driveable road centrelines + signals for runtime traffic."""
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    tram_ids = _tram_way_ids(layout)
    tram_segs = _tram_segments(layout)
    scored: list[tuple[float, dict[str, Any]]] = []
    for road in layout.get("roads") or []:
        kind = str(road.get("kind") or "residential").lower()
        if kind in NON_DRIVEABLE_ROAD_KINDS or kind not in DRIVEABLE_ROAD_KINDS:
            continue
        rid = road.get("id")
        # Transit tram/rail polylines must never appear as car paths.
        if rid in tram_ids:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        dmin = min(_dist(sx, sy, float(p[0]), float(p[1])) for p in pts)
        if dmin > radius:
            continue
        shared = _road_near_tram(pts, tram_segs)
        tagged = road.get("maxspeed_kmh")
        tagged_kmh = float(tagged) if isinstance(tagged, (int, float)) and tagged > 0 else None
        scored.append(
            (
                dmin,
                {
                    "id": rid,
                    "kind": kind,
                    "name": str(road.get("name") or ""),
                    "width": float(road.get("width") or 6.0),
                    # Posted limit from OSM (null when untagged) + the limit
                    # traffic actually uses (tagged or urban default), km/h.
                    "maxspeedKmh": tagged_kmh,
                    "speedKmh": road_speed_kmh(kind, tagged_kmh),
                    # Wider right-lane offset when highway hugs tram rails.
                    "laneOffset": 2.4 if shared else 1.15,
                    "tramShared": shared,
                    # Legal direction along `points` (1 / -1 / 0 = both ways) from OSM
                    # oneway tags; buses may be exempt (contraflow bus lane).
                    "oneway": _direction_code(road.get("oneway")),
                    "onewayBus": _direction_code(road.get("oneway_bus", road.get("oneway"))),
                    "points": [[float(p[0]), float(p[1])] for p in pts],
                },
            )
        )
    scored.sort(key=lambda item: item[0])

    signals = _export_signal_stop_lines(
        layout, sx, sy, radius=min(radius, 220.0), max_clusters=14
    )
    chosen_roads = [item[1] for item in scored[:max_roads]]
    mark_dual_carriageways(chosen_roads)

    return {
        "spawn": {"x": sx, "y": sy},
        "radius": radius,
        "roads": chosen_roads,
        "signals": signals,
        "cycleSeconds": 30,
    }


def export_buildings_near_spawn(
    layout: dict[str, Any],
    spawn: dict[str, Any] | None,
    *,
    radius: float = 280.0,
    max_buildings: int = 1500,
) -> dict[str, Any]:
    """Building footprint rings near spawn for runtime outdoors collision.

    Viewer keeps the walker outside these rings (solid extruded boxes have no
    interiors). Rings use the same Blender XY as roads.json.
    """
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    scored: list[tuple[float, dict[str, Any]]] = []
    for bldg in layout.get("buildings") or []:
        ring = bldg.get("ring") or []
        if len(ring) < 3:
            continue
        pts = [[float(p[0]), float(p[1])] for p in ring]
        dmin = min(_dist(sx, sy, p[0], p[1]) for p in pts)
        if dmin > radius:
            continue
        scored.append(
            (
                dmin,
                {
                    "id": bldg.get("id"),
                    "ring": pts,
                },
            )
        )
    scored.sort(key=lambda item: item[0])
    return {
        "spawn": {"x": sx, "y": sy},
        "radius": radius,
        "buildings": [item[1] for item in scored[:max_buildings]],
    }


def _export_signal_stop_lines(
    layout: dict[str, Any],
    sx: float,
    sy: float,
    *,
    radius: float,
    max_clusters: int,
) -> list[dict[str, Any]]:
    """Deduped OSM signal clusters → curb poles + stop-lines for the viewer."""
    raw: list[tuple[float, float, Any]] = []
    for sig in layout.get("signals") or []:
        x = float(sig.get("x") or 0.0)
        y = float(sig.get("y") or 0.0)
        if _dist(sx, sy, x, y) > radius:
            continue
        raw.append((x, y, sig.get("id")))
    if not raw:
        return []

    # Greedy 12m clustering (same rule as Blender).
    clusters: list[list[tuple[float, float, Any]]] = []
    for item in sorted(raw, key=lambda p: _dist(sx, sy, p[0], p[1])):
        placed = False
        for cluster in clusters:
            cx = sum(p[0] for p in cluster) / len(cluster)
            cy = sum(p[1] for p in cluster) / len(cluster)
            if _dist(item[0], item[1], cx, cy) <= 12.0:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    clusters.sort(
        key=lambda c: _dist(
            sx, sy, sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)
        )
    )

    roads = [
        r
        for r in (layout.get("roads") or [])
        if str(r.get("kind") or "").lower() in DRIVEABLE_ROAD_KINDS
    ]
    out: list[dict[str, Any]] = []
    used: list[tuple[float, float]] = []
    for cluster in clusters[:max_clusters]:
        jx = sum(p[0] for p in cluster) / len(cluster)
        jy = sum(p[1] for p in cluster) / len(cluster)
        approaches = _runtime_approaches(jx, jy, roads)
        if not approaches:
            hit = _runtime_nearest_road(jx, jy, roads)
            if hit is None:
                continue
            cx, cy, tx, ty, width = hit
            approaches = [
                {
                    "tx": tx,
                    "ty": ty,
                    "stop_x": cx - tx * 3.0,
                    "stop_y": cy - ty * 3.0,
                    "width": width,
                }
            ]
        for ap in approaches:
            stop_x, stop_y = float(ap["stop_x"]), float(ap["stop_y"])
            if any(_dist(stop_x, stop_y, ux, uy) < 5.5 for ux, uy in used):
                continue
            used.append((stop_x, stop_y))
            tx, ty = float(ap["tx"]), float(ap["ty"])
            width = float(ap["width"])
            half = width * 0.5
            rx, ry = ty, -tx
            out.append(
                {
                    "id": cluster[0][2],
                    "x": stop_x + rx * (half + 0.85),
                    "y": stop_y + ry * (half + 0.85),
                    "stopX": stop_x,
                    "stopY": stop_y,
                    "tx": tx,
                    "ty": ty,
                    "width": width,
                    "kind": "traffic_signals",
                }
            )
    return out[:36]


def _runtime_nearest_road(
    px: float, py: float, roads: list[dict[str, Any]]
) -> tuple[float, float, float, float, float] | None:
    best: tuple[float, float, float, float, float, float] | None = None
    for road in roads:
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            if len2 < 1e-6:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
            cx, cy = ax + t * dx, ay + t * dy
            dist = _dist(px, py, cx, cy)
            if best is None or dist < best[5]:
                length = math.sqrt(len2)
                best = (cx, cy, dx / length, dy / length, width, dist)
    if best is None:
        return None
    return best[0], best[1], best[2], best[3], best[4]


def _runtime_approaches(
    jx: float, jy: float, roads: list[dict[str, Any]], search_r: float = 16.0
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for road in roads:
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
            for ex, ey, ox, oy in ((ax, ay, bx, by), (bx, by, ax, ay)):
                if _dist(ex, ey, jx, jy) > search_r:
                    continue
                dx, dy = ex - ox, ey - oy
                length = math.hypot(dx, dy) or 1.0
                tx, ty = dx / length, dy / length
                raw.append(
                    {
                        "tx": tx,
                        "ty": ty,
                        "stop_x": ex - tx * 3.2,
                        "stop_y": ey - ty * 3.2,
                        "width": width,
                    }
                )
    bins: dict[int, dict[str, Any]] = {}
    for ap in raw:
        key = int(round(math.atan2(ap["ty"], ap["tx"]) / (math.pi / 4.0))) % 8
        prev = bins.get(key)
        if prev is None:
            bins[key] = ap
            continue
        d_new = abs(_dist(ap["stop_x"], ap["stop_y"], jx, jy) - 3.2)
        d_old = abs(_dist(prev["stop_x"], prev["stop_y"], jx, jy) - 3.2)
        if d_new < d_old:
            bins[key] = ap
    return list(bins.values())[:4]


def export_transit_near_spawn(
    layout: dict[str, Any],
    spawn: dict[str, Any] | None,
    *,
    radius: float = 280.0,
    max_paths: int = 48,
    max_stops: int = 80,
) -> dict[str, Any]:
    """Transit paths + stops near spawn for runtime trams/buses."""
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    path_scored: list[tuple[float, dict[str, Any]]] = []
    for line in layout.get("transit_lines") or []:
        pts = line.get("points") or []
        if len(pts) < 2:
            continue
        # Premetro/tunnel ways are underground: runtime vehicles must not
        # drive them at street level.
        if line.get("tunnel"):
            continue
        dmin = min(_dist(sx, sy, float(p[0]), float(p[1])) for p in pts)
        if dmin > radius:
            continue
        lines = list(line.get("lines") or line.get("refs") or [])
        direction = _direction_code(line.get("direction"))
        source = "relation" if direction else "none"
        if not direction and line.get("source") == "gtfs":
            # GTFS shapes are ordered stop-to-stop: always driven along their points.
            direction, source = 1, "gtfs"
        path_scored.append(
            (
                dmin,
                {
                    "id": line.get("id"),
                    "mode": line.get("mode") or "bus",
                    "lines": lines,
                    # Vehicles may only drive `points` forward (1) / backward (-1); 0 = both.
                    "direction": direction,
                    "directionSource": source,
                    "points": [[float(p[0]), float(p[1])] for p in pts],
                },
            )
        )
    path_scored.sort(key=lambda item: item[0])
    chosen_paths = [item[1] for item in path_scored[:max_paths]]
    # Undirected tram tracks: a parallel partner (right-hand traffic) fixes the direction.
    infer_parallel_track_directions([p for p in chosen_paths if p["mode"] in {"tram", "subway"}])

    def _stop_near_paths(x: float, y: float, thresh: float = 35.0) -> bool:
        for path in chosen_paths:
            pts = path.get("points") or []
            for p in pts[:: max(1, len(pts) // 16)]:
                if _dist(x, y, float(p[0]), float(p[1])) <= thresh:
                    return True
        return False

    stop_scored: list[tuple[float, dict[str, Any]]] = []
    for stop in layout.get("transit_stops") or []:
        x = float(stop.get("x") or 0.0)
        y = float(stop.get("y") or 0.0)
        d = _dist(sx, sy, x, y)
        # Keep stops near spawn, or anywhere along an exported path (for halt dwell).
        if d > radius and not _stop_near_paths(x, y):
            continue
        stop_scored.append(
            (
                d,
                {
                    "id": stop.get("id"),
                    "mode": stop.get("mode") or "bus",
                    "name": stop.get("name") or "",
                    "lines": list(stop.get("lines") or stop.get("refs") or []),
                    "x": x,
                    "y": y,
                },
            )
        )
    stop_scored.sort(key=lambda item: item[0])
    return {
        "spawn": {"x": sx, "y": sy},
        "radius": radius,
        "paths": chosen_paths,
        "stops": [item[1] for item in stop_scored[:max_stops]],
    }


def spawn_from_place(
    place: dict[str, Any],
    origin: tuple[float, float],
    layout: dict[str, Any],
) -> dict[str, Any] | None:
    """Project place.spawn lat/lon into local metres with human eye height.

    The OSM address point is usually the building centroid — we snap onto the
    nearest road centreline so the human camera is in the street, not inside a wall.
    """
    from cityview.geo import project

    spawn = place.get("spawn")
    if not spawn:
        return None
    lat = float(spawn["lat"])
    lon = float(spawn["lon"])
    bx, by = project(lat, lon, origin[0], origin[1])
    eye = float(spawn.get("eye_height", 1.7))
    roads = layout.get("roads") or []
    if "yaw" in spawn:
        x, y, _auto_yaw = nearest_road_pose(bx, by, roads)
        yaw = float(spawn["yaw"])
    else:
        x, y, yaw = nearest_road_pose(bx, by, roads)
    return {
        "label": spawn.get("label") or "spawn",
        "lat": lat,
        "lon": lon,
        "x": x,
        "y": y,
        "z": eye,
        "yaw": yaw,
        "eye_height": eye,
        "building_xy": [bx, by],
    }
