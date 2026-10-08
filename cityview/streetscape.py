"""Street-facing edges, roof shapes, and spawn helpers for district LOD2."""

from __future__ import annotations

import math
from typing import Any


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
            return max(1, min(20, int(round(float(raw.split(";")[0])))))
        except ValueError:
            pass
    return max(1, min(20, int(round(height / 3.15))))


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

    if style in {"international", "art-deco", "modern-infill", "white-modern", "prefab-70s"}:
        return "flat"
    if style in {"neo-flemish", "art-nouveau", "red-brick"}:
        return "gable" if (osm_id % 3) else "mansard"
    if style == "yellow-brick":
        return "gable" if (osm_id % 2) else "mansard"
    if style == "neo-gothic":
        return "hip"
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
            eaves = max(4.0, min(80.0, total))
        except ValueError:
            pass

    levels = tags.get("building:levels")
    if levels:
        try:
            floors = max(1, min(20, int(round(float(levels.split(";")[0])))))
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
        "garage": 4.5,
        "shed": 3.5,
        "semidetached_house": 11.5,
        "detached": 11.0,
    }

    if floors is None and eaves is not None:
        floors = max(1, min(20, int(round(eaves / floor_h))))
    if floors is None:
        eaves = eaves if eaves is not None else defaults.get(kind, 12.0)
        floors = max(1, min(20, int(round(eaves / floor_h))))
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
        "residential",
        "living_street",
        "tertiary",
        "unclassified",
        "secondary",
        "secondary_link",
    }
)


def export_roads_near_spawn(
    layout: dict[str, Any],
    spawn: dict[str, Any] | None,
    *,
    radius: float = 280.0,
    max_roads: int = 60,
) -> dict[str, Any]:
    """Lightweight road centreline sample for runtime traffic near spawn."""
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    scored: list[tuple[float, dict[str, Any]]] = []
    for road in layout.get("roads") or []:
        kind = road.get("kind") or "residential"
        if kind not in DRIVEABLE_ROAD_KINDS:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        dmin = min(_dist(sx, sy, float(p[0]), float(p[1])) for p in pts)
        if dmin > radius:
            continue
        scored.append(
            (
                dmin,
                {
                    "id": road.get("id"),
                    "kind": kind,
                    "width": float(road.get("width") or 6.0),
                    "points": [[float(p[0]), float(p[1])] for p in pts],
                },
            )
        )
    scored.sort(key=lambda item: item[0])
    return {
        "spawn": {"x": sx, "y": sy},
        "radius": radius,
        "roads": [item[1] for item in scored[:max_roads]],
    }


def export_transit_near_spawn(
    layout: dict[str, Any],
    spawn: dict[str, Any] | None,
    *,
    radius: float = 280.0,
    max_paths: int = 48,
    max_stops: int = 40,
) -> dict[str, Any]:
    """Transit paths + stops near spawn for runtime trams/buses."""
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    path_scored: list[tuple[float, dict[str, Any]]] = []
    for line in layout.get("transit_lines") or []:
        pts = line.get("points") or []
        if len(pts) < 2:
            continue
        dmin = min(_dist(sx, sy, float(p[0]), float(p[1])) for p in pts)
        if dmin > radius:
            continue
        lines = list(line.get("lines") or line.get("refs") or [])
        path_scored.append(
            (
                dmin,
                {
                    "id": line.get("id"),
                    "mode": line.get("mode") or "bus",
                    "lines": lines,
                    "points": [[float(p[0]), float(p[1])] for p in pts],
                },
            )
        )
    path_scored.sort(key=lambda item: item[0])

    stop_scored: list[tuple[float, dict[str, Any]]] = []
    for stop in layout.get("transit_stops") or []:
        x = float(stop.get("x") or 0.0)
        y = float(stop.get("y") or 0.0)
        d = _dist(sx, sy, x, y)
        if d > radius:
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
        "paths": [item[1] for item in path_scored[:max_paths]],
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
