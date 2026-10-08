"""Public benches from survey data — real positions, real facing, no procedural spam.

Sources (merged, de-duplicated, in this priority order):

1. **OpenStreetMap** ``amenity=bench`` nodes / ways (ODbL). Mappers who surveyed a
   bench often record ``direction=*`` — per the OSM wiki that is the compass bearing a
   person *sitting* on the bench faces, so it is used verbatim.
2. **Stad Antwerpen Groeninventaris**, layer ``meubilair in parken`` (park furniture
   inventory), ``CATEGORIE = 'Bank'`` (public ArcGIS service, open-data licence,
   © Stad Antwerpen). Positions only, no orientation.
3. **OSM bus / tram platforms tagged ``bench=yes``** (De Lijn shelters). Only used where
   no surveyed bench already stands within ``STOP_SKIP_M``; the bench sits just behind
   the stop pole with its seat toward the track / carriageway.

Benches with no surveyed direction get one from their surroundings (seat toward the
open space, back to the wall / away from the road):

1. a building wall within ``WALL_BACK_M``      → back to the wall, seat away from it;
2. a footway / path ≤ ``PATH_FACE_M`` (bench beside it, not on it)
                                               → seat toward the path;
3. a carriageway within ``ROAD_BACK_M``        → back to the road, seat away from it;
4. inside a park                               → seat toward the park centre;
5. a carriageway within ``ROAD_FACE_M``        → set back on a wide pavement / plaza:
                                                 seat toward the street;
6. otherwise a stable pseudo-random 45° heading.

Rules 2-5 were checked against the 13 OSM benches in the Harmonie tile that carry a
surveyed ``direction=*`` (see README "Benches"): the thresholds are the ones that agree best.

A bench is **never** left on a carriageway (nudged to the kerb when the survey point is
within ``ROAD_NUDGE_M`` of it, otherwise dropped), nor inside a building or on a tram bed.
A fallback bench is only invented inside parks of at least ``FALLBACK_PARK_MIN_M2`` that
hold no surveyed bench at all, on an existing park footway, and at most ``FALLBACK_MAX``
per park.

Pure stdlib: ``blender/benches_blender.py`` consumes the plan inside Blender's Python.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
from pathlib import Path
from typing import Any

from cityview.geo import project
from cityview.paths import BENCHES_CACHE
from cityview.railclear import CLEAR_FURNITURE
from cityview.trees import (
    DRIVEABLE,
    _http_json,
    _Obstacles,
    _point_in_ring,
    _PointGrid,
    _seg_dist,
    ring_area,
)

ANTWERP_FURNITURE_LAYER = (
    "https://geodata.antwerpen.be/arcgissql/rest/services/"
    "P_Groeninventaris/Groeninventaris_extern/MapServer/1/query"
)
ATTRIBUTION = (
    "Benches: (c) Stad Antwerpen Groeninventaris, layer 'meubilair in parken' "
    "(open data licence); (c) OpenStreetMap contributors (ODbL)."
)
FETCH_PAD_DEG = 0.0004

# --- placement tuning -----------------------------------------------------
DEDUPE_M = 2.0  # two survey points closer than this are the same bench
BUILDING_MARGIN = 0.25  # a bench may stand against a façade, not in it
WALL_BACK_M = 2.2  # wall closer than this → back to the wall
PATH_FACE_M = 8.0  # footway closer than this → seat toward it
PATH_MIN_EDGE_M = 0.2  # …but only a bench *beside* the path, not one standing on it
ROAD_BACK_M = 4.5  # carriageway edge closer than this → back to it
ROAD_FACE_M = 12.0  # farther (plaza / wide pavement) → seat toward the street
ROAD_NUDGE_M = 2.0  # survey points this deep in a carriageway are moved to the kerb
KERB_CLEARANCE = 0.8  # where a nudged bench ends up, measured from the road surface edge
WALL_FLIP_M = 1.0  # a surveyed heading that stares into a wall this close is flipped
STOP_SKIP_M = 6.0  # a surveyed bench this close already is the stop's bench
STOP_DEDUPE_M = 6.0  # node + platform area of the same stop collapse to one bench
STOP_BEHIND_M = 1.0  # bench stands this far behind the stop pole, away from the vehicle
STOP_RAIL_REACH = 9.0
STOP_ROAD_REACH = 8.0
FALLBACK_PARK_MIN_M2 = 1800.0
FALLBACK_MAX = 2
FALLBACK_PATH_OFFSET = 2.0
FALLBACK_MIN_PATH_LEN = 12.0

FACE_PATH_KINDS = frozenset({"footway", "path"})  # pedestrian areas: surveyed benches there face away
# Carriageways: DRIVEABLE minus places where benches are mapped inside the roadway.
CARRIAGEWAY = DRIVEABLE - {"pedestrian", "service", "living_street"}

CARDINALS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}


# ---------------------------------------------------------------- fetching


def fetch_city_benches(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Page the city's park-furniture layer for ``CATEGORIE='Bank'`` in ``(s, w, n, e)``."""
    south, west, north, east = bbox
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode(
            {
                "f": "geojson",
                "where": "CATEGORIE='Bank'",
                "geometry": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "outSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "OBJECTID,ANTW_ID,CATEGORIE",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": 1000,
            }
        )
        doc = _http_json(f"{ANTWERP_FURNITURE_LAYER}?{params}")
        feats = doc.get("features") or []
        for feat in feats:
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if geom.get("type") != "Point" or len(coords) < 2:
                continue
            props = feat.get("properties") or {}
            out.append(
                {
                    "id": props.get("OBJECTID"),
                    "lat": round(float(coords[1]), 7),
                    "lon": round(float(coords[0]), 7),
                }
            )
        if not feats or not doc.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


def _checked_cache_path(path: Path) -> Path:
    """Bench caches live under assets/benches/*.json — nothing else is read or written."""
    resolved = Path(path).resolve()
    root = BENCHES_CACHE.resolve()
    if resolved.suffix != ".json" or root not in resolved.parents:
        raise ValueError(f"bench cache must be a .json file under {root}")
    return resolved


def fetch_bench_sources(
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Load (or download once and commit) the municipal bench payload for a tile."""
    cache_path = _checked_cache_path(cache_path)
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text())
    south, west, north, east = bbox
    padded = (south - FETCH_PAD_DEG, west - FETCH_PAD_DEG, north + FETCH_PAD_DEG, east + FETCH_PAD_DEG)
    payload: dict[str, Any] = {
        "bbox": list(padded),
        "attribution": ATTRIBUTION,
        "fetched": time.strftime("%Y-%m-%d"),
        "antwerp": [],
        "errors": [],
    }
    try:
        payload["antwerp"] = fetch_city_benches(padded)
    except Exception as exc:  # noqa: BLE001
        payload["errors"].append(f"antwerp: {exc}")
    if not payload["errors"] and payload["antwerp"]:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Path confined to assets/benches/*.json by _checked_cache_path above.
        cache_path.write_text(json.dumps(payload, separators=(",", ":")))  # nosemgrep
    return payload


# ---------------------------------------------------------------- OSM extraction


def parse_direction(raw: Any) -> float | None:
    """OSM ``direction=*`` → compass bearing in degrees (clockwise from north), or None."""
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if text.upper() in CARDINALS:
        return CARDINALS[text.upper()]
    try:
        deg = float(text.replace(",", "."))
    except ValueError:
        return None  # 'forward' / 'backward' / ranges: relative to a way, not a bearing
    return deg % 360.0


def osm_benches(osm: dict[str, Any] | None) -> list[dict[str, Any]]:
    """``amenity=bench`` nodes and ways from an Overpass-style document (lat/lon)."""
    elements = (osm or {}).get("elements") or []
    nodes = {int(e["id"]): e for e in elements if e.get("type") == "node"}
    out: list[dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags") or {}
        if tags.get("amenity") != "bench":
            continue
        if tags.get("access") in {"private", "no", "customers"}:
            continue
        if el.get("type") == "node":
            lat, lon = float(el["lat"]), float(el["lon"])
        elif el.get("type") == "way":
            pts = [nodes[int(n)] for n in el.get("nodes") or [] if int(n) in nodes]
            if not pts:
                continue
            lat = sum(float(p["lat"]) for p in pts) / len(pts)
            lon = sum(float(p["lon"]) for p in pts) / len(pts)
        else:
            continue
        out.append(
            {
                "id": int(el["id"]),
                "type": el.get("type"),
                "lat": lat,
                "lon": lon,
                "tags": {k: str(v) for k, v in tags.items()},
            }
        )
    return out


def osm_stop_benches(osm: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Bus stops / tram platforms mapped with ``bench=yes`` (point or platform area centroid)."""
    elements = (osm or {}).get("elements") or []
    nodes = {int(e["id"]): e for e in elements if e.get("type") == "node"}
    out: list[dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags") or {}
        if tags.get("bench") != "yes":
            continue
        if not (
            tags.get("highway") in {"bus_stop", "platform"}
            or tags.get("public_transport") == "platform"
            or tags.get("railway") == "platform"
        ):
            continue
        if el.get("type") == "node":
            lat, lon = float(el["lat"]), float(el["lon"])
        elif el.get("type") == "way":
            pts = [nodes[int(n)] for n in el.get("nodes") or [] if int(n) in nodes]
            if not pts:
                continue
            lat = sum(float(p["lat"]) for p in pts) / len(pts)
            lon = sum(float(p["lon"]) for p in pts) / len(pts)
        else:
            continue
        out.append(
            {
                "id": int(el["id"]),
                "lat": lat,
                "lon": lon,
                "tram": tags.get("railway") == "platform" or tags.get("tram") == "yes",
                "tags": {k: str(v) for k, v in tags.items()},
            }
        )
    return out


def _bench_length(tags: dict[str, str]) -> float:
    try:
        seats = int(float(tags.get("seats", "")))
    except ValueError:
        return 1.7
    return max(1.2, min(2.6, 0.55 * seats))


# ---------------------------------------------------------------- geometry


def _stable_unit(*parts: Any) -> float:
    h = 2166136261
    for ch in "|".join(str(p) for p in parts):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h / 0xFFFFFFFF


def facing_to_yaw(fx: float, fy: float) -> float:
    """Blender ``rotation_z`` for a bench whose seat looks along ``(fx, fy)``.

    The bench mesh has its length on local X, backrest on local +Y and the seat looking
    toward local -Y, so after rotating by ``yaw`` it looks along ``(sin yaw, -cos yaw)``.
    """
    return math.atan2(fx, -fy)


def yaw_to_facing(yaw: float) -> tuple[float, float]:
    return (math.sin(yaw), -math.cos(yaw))


def bearing_to_facing(deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return (math.sin(rad), math.cos(rad))


def _nearest_on_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float):
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    t = 0.0 if len2 < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return ax + t * dx, ay + t * dy


class _Ways:
    """Road / path segments with a coarse grid for small-radius nearest queries."""

    CELL = 24.0

    def __init__(self, layout: dict[str, Any]):
        self.segs: list[tuple[float, float, float, float, float, str]] = []
        self._grid: dict[tuple[int, int], list[int]] = {}
        for road in layout.get("roads") or []:
            pts = road.get("points") or []
            half = float(road.get("width") or 6.0) * 0.5
            kind = road.get("kind") or "residential"
            for i in range(len(pts) - 1):
                ax, ay, bx, by = pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]
                idx = len(self.segs)
                self.segs.append((ax, ay, bx, by, half, kind))
                for cx in range(int(math.floor(min(ax, bx) / self.CELL)), int(math.floor(max(ax, bx) / self.CELL)) + 1):
                    for cy in range(int(math.floor(min(ay, by) / self.CELL)), int(math.floor(max(ay, by) / self.CELL)) + 1):
                        self._grid.setdefault((cx, cy), []).append(idx)

    def nearest(self, x: float, y: float, kinds: frozenset[str] | set[str], reach: float):
        """``(edge_distance, nx, ny, kind)`` of the closest surface edge, ``nx, ny`` pointing
        from the way toward the query point (``None`` when nothing within ``reach``)."""
        cx, cy = int(math.floor(x / self.CELL)), int(math.floor(y / self.CELL))
        span = int(math.ceil((reach + 3.0) / self.CELL))
        best = None
        seen: set[int] = set()
        for gx in range(cx - span, cx + span + 1):
            for gy in range(cy - span, cy + span + 1):
                for idx in self._grid.get((gx, gy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    ax, ay, bx, by, half, kind = self.segs[idx]
                    if kind not in kinds:
                        continue
                    qx, qy = _nearest_on_seg(x, y, ax, ay, bx, by)
                    d = math.hypot(x - qx, y - qy)
                    edge = d - half
                    if edge > reach:
                        continue
                    if best is None or edge < best[0]:
                        if d < 1e-6:  # on the centreline: push to the segment's left
                            nx, ny = -(by - ay), bx - ax
                            n = math.hypot(nx, ny) or 1.0
                            nx, ny = nx / n, ny / n
                        else:
                            nx, ny = (x - qx) / d, (y - qy) / d
                        best = (edge, nx, ny, kind)
        return best


def _nearest_rail(rails, x: float, y: float, reach: float):
    """``(distance, nx, ny)`` to the closest rail centreline (n points from rail to the point)."""
    best = None
    for ax, ay, bx, by in rails.segments:
        if min(ax, bx) - reach > x or max(ax, bx) + reach < x or min(ay, by) - reach > y or max(ay, by) + reach < y:
            continue
        qx, qy = _nearest_on_seg(x, y, ax, ay, bx, by)
        d = math.hypot(x - qx, y - qy)
        if d <= reach and d > 1e-6 and (best is None or d < best[0]):
            best = (d, (x - qx) / d, (y - qy) / d)
    return best


def _nearest_wall(obstacles: _Obstacles, x: float, y: float, reach: float):
    """``(distance, nx, ny)`` to the closest building edge (n points from wall to the point)."""
    best = None
    for ring, (x0, y0, x1, y1) in obstacles.buildings:
        if x < x0 - reach or x > x1 + reach or y < y0 - reach or y > y1 + reach:
            continue
        n = len(ring)
        for i in range(n):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % n]
            qx, qy = _nearest_on_seg(x, y, ax, ay, bx, by)
            d = math.hypot(x - qx, y - qy)
            if d <= reach and (best is None or d < best[0]):
                if d < 1e-6:
                    continue
                best = (d, (x - qx) / d, (y - qy) / d)
    return best


# ---------------------------------------------------------------- orientation


def decide_facing(
    x: float,
    y: float,
    *,
    bearing: float | None,
    ways: _Ways,
    obstacles: _Obstacles,
    park_ring: list[list[float]] | None,
    seed: Any,
) -> tuple[float, float, str]:
    """Unit facing vector of the seat and the rule that produced it."""
    wall = _nearest_wall(obstacles, x, y, max(WALL_BACK_M, WALL_FLIP_M))
    if bearing is not None:
        fx, fy = bearing_to_facing(bearing)
        # A surveyed heading that stares into a wall a metre away is a projection /
        # mapping slip (nobody sits facing a façade): turn the bench around.
        if wall and wall[0] <= WALL_FLIP_M and (fx * -wall[1] + fy * -wall[2]) > 0.7:
            return -fx, -fy, "osm_direction_flipped"
        return fx, fy, "osm_direction"
    if wall and wall[0] <= WALL_BACK_M:
        return wall[1], wall[2], "back_to_wall"
    path = ways.nearest(x, y, FACE_PATH_KINDS, PATH_FACE_M)
    if path and path[0] >= PATH_MIN_EDGE_M:
        # Seat toward the path: the way→bench normal points away from it, so negate.
        return -path[1], -path[2], "face_path"
    road = ways.nearest(x, y, CARRIAGEWAY, ROAD_BACK_M)
    if road:
        return road[1], road[2], "back_to_road"
    if park_ring:
        cx = sum(p[0] for p in park_ring) / len(park_ring)
        cy = sum(p[1] for p in park_ring) / len(park_ring)
        d = math.hypot(cx - x, cy - y)
        if d >= 5.0:
            return (cx - x) / d, (cy - y) / d, "face_park_centre"
    street = ways.nearest(x, y, CARRIAGEWAY, ROAD_FACE_M)
    if street:
        return -street[1], -street[2], "face_street"
    snap = round(_stable_unit(seed, round(x, 1), round(y, 1)) * 8.0) % 8
    fx, fy = bearing_to_facing(snap * 45.0)
    return fx, fy, "hashed"


# ---------------------------------------------------------------- planning


def _candidates(
    osm_list: list[dict[str, Any]],
    payload: dict[str, Any],
    origin: tuple[float, float],
) -> list[dict[str, Any]]:
    """Surveyed points in local metres, in dedupe-priority order."""
    out: list[dict[str, Any]] = []
    for rec in osm_list:
        x, y = project(rec["lat"], rec["lon"], origin[0], origin[1])
        tags = rec.get("tags") or {}
        out.append(
            {
                "x": x,
                "y": y,
                "source": "osm",
                "id": rec["id"],
                "bearing": parse_direction(tags.get("direction")) if rec.get("type") == "node" else None,
                "backrest": tags.get("backrest") != "no",
                "length": _bench_length(tags),
            }
        )
    # Surveyed heading first: when OSM and the city list the same bench, keep the one with a heading.
    out.sort(key=lambda c: c["bearing"] is None)
    for rec in payload.get("antwerp") or []:
        x, y = project(float(rec["lat"]), float(rec["lon"]), origin[0], origin[1])
        out.append(
            {"x": x, "y": y, "source": "antwerp", "id": rec.get("id"), "bearing": None, "backrest": True, "length": 1.7}
        )
    return out


def _bounds(bbox, origin):
    if not bbox:
        return (-math.inf, -math.inf, math.inf, math.inf)
    x0, y0 = project(bbox[0], bbox[1], origin[0], origin[1])
    x1, y1 = project(bbox[2], bbox[3], origin[0], origin[1])
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _park_for(x: float, y: float, parks: list[dict[str, Any]]):
    for park in parks:
        ring = park.get("ring") or []
        if len(ring) >= 3 and _point_in_ring(x, y, ring):
            return ring
    return None


def _bench_record(x, y, fx, fy, rule, source, backrest, length) -> dict[str, Any]:
    return {
        "x": round(x, 2),
        "y": round(y, 2),
        "yaw": round(facing_to_yaw(fx, fy), 4),
        "backrest": bool(backrest),
        "length": round(length, 2),
        "source": source,
        "rule": rule,
    }


def plan_benches(
    layout: dict[str, Any],
    osm_list: list[dict[str, Any]] | None,
    payload: dict[str, Any] | None,
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
    stop_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return ``{"benches": [...], "stats": {...}}`` in local metres."""
    payload = payload or {}
    obstacles = _Obstacles(layout)
    ways = _Ways(layout)
    parks = layout.get("parks") or []
    xmin, ymin, xmax, ymax = _bounds(bbox, origin)
    stats: dict[str, int] = {
        "osm": 0,
        "antwerp": 0,
        "stop": 0,
        "fallback": 0,
        "dropped_duplicate": 0,
        "dropped_building": 0,
        "dropped_carriageway": 0,
        "dropped_rail": 0,
        "dropped_outside": 0,
        "nudged_to_kerb": 0,
        "dropped_stop_covered": 0,
        "dropped_stop_unplaceable": 0,
        "parks_fallback": 0,
    }
    benches: list[dict[str, Any]] = []
    grid = _PointGrid(cell=4.0)

    for cand in _candidates(osm_list or [], payload, origin):
        x, y, src = cand["x"], cand["y"], cand["source"]
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            stats["dropped_outside"] += 1
            continue
        if grid.near(x, y, DEDUPE_M):
            stats["dropped_duplicate"] += 1
            continue
        if obstacles.in_building(x, y, BUILDING_MARGIN):
            stats["dropped_building"] += 1
            continue
        road = ways.nearest(x, y, CARRIAGEWAY, 0.1)
        if road and road[0] < 0.1:
            depth = -road[0]
            if depth > ROAD_NUDGE_M:
                stats["dropped_carriageway"] += 1
                continue
            # Survey noise: slide out to the kerb along the road's normal.
            push = depth + KERB_CLEARANCE
            x, y = x + road[1] * push, y + road[2] * push
            stats["nudged_to_kerb"] += 1
            if obstacles.in_building(x, y, BUILDING_MARGIN) or grid.near(x, y, DEDUPE_M):
                stats["dropped_carriageway"] += 1
                continue
        if obstacles.on_rails(x, y, CLEAR_FURNITURE):
            stats["dropped_rail"] += 1
            continue
        ring = _park_for(x, y, parks)
        fx, fy, rule = decide_facing(
            x, y, bearing=cand["bearing"], ways=ways, obstacles=obstacles, park_ring=ring, seed=cand["id"]
        )
        grid.add(x, y)
        benches.append(_bench_record(x, y, fx, fy, rule, src, cand["backrest"], cand["length"]))
        stats[src] += 1

    # --- shelters: bench=yes stops with no surveyed bench next to them ---
    rails = obstacles.rails
    stop_grid = _PointGrid(cell=4.0)
    for rec in stop_list or []:
        sx, sy = project(rec["lat"], rec["lon"], origin[0], origin[1])
        if not (xmin <= sx <= xmax and ymin <= sy <= ymax):
            stats["dropped_outside"] += 1
            continue
        if grid.near(sx, sy, STOP_SKIP_M):
            stats["dropped_stop_covered"] += 1
            continue
        if stop_grid.near(sx, sy, STOP_DEDUPE_M):
            stats["dropped_duplicate"] += 1
            continue
        veh = _nearest_rail(rails, sx, sy, STOP_RAIL_REACH)
        rail_d = veh[0] if veh else math.inf
        road = ways.nearest(sx, sy, CARRIAGEWAY, STOP_ROAD_REACH)
        if veh and (not road or rec.get("tram") or rail_d <= road[0] + 1.0):
            vx, vy = -veh[1], -veh[2]  # toward the track
            behind = max(STOP_BEHIND_M, CLEAR_FURNITURE + 0.3 - rail_d)
        elif road:
            vx, vy = -road[1], -road[2]  # toward the carriageway
            behind = max(STOP_BEHIND_M, KERB_CLEARANCE + 0.3 - road[0])
        else:
            stats["dropped_stop_unplaceable"] += 1
            continue
        x, y = sx - vx * behind, sy - vy * behind
        if (
            obstacles.in_building(x, y, BUILDING_MARGIN)
            or obstacles.on_rails(x, y, CLEAR_FURNITURE)
            or (ways.nearest(x, y, CARRIAGEWAY, 0.1) or (1.0,))[0] < 0.1
            or grid.near(x, y, DEDUPE_M)
        ):
            stats["dropped_stop_unplaceable"] += 1
            continue
        stop_grid.add(sx, sy)
        grid.add(x, y)
        benches.append(_bench_record(x, y, vx, vy, "face_vehicle", "stop", True, 1.7))
        stats["stop"] += 1

    # --- fallback: parks with a path but no surveyed bench get a couple on that path ---
    for park in parks:
        ring = park.get("ring") or []
        if len(ring) < 3 or ring_area(ring) < FALLBACK_PARK_MIN_M2:
            continue
        pid = int(park.get("id") or 1)
        if any(_point_in_ring(b["x"], b["y"], ring) for b in benches):
            continue
        spots = []
        for ax, ay, bx, by, _half, kind in ways.segs:
            if kind not in FACE_PATH_KINDS:
                continue
            length = math.hypot(bx - ax, by - ay)
            mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
            if length < FALLBACK_MIN_PATH_LEN or not _point_in_ring(mx, my, ring):
                continue
            nx, ny = -(by - ay) / length, (bx - ax) / length
            side = 1.0 if _stable_unit(pid, round(mx), round(my)) < 0.5 else -1.0
            for s in (side, -side):
                px, py = mx + nx * s * FALLBACK_PATH_OFFSET, my + ny * s * FALLBACK_PATH_OFFSET
                if (
                    _point_in_ring(px, py, ring)
                    and not obstacles.in_building(px, py, 1.0)
                    and not obstacles.on_rails(px, py, CLEAR_FURNITURE)
                    and not (ways.nearest(px, py, CARRIAGEWAY, 0.5) or [1.0])[0] < 0.5
                    and not grid.near(px, py, 12.0)
                ):
                    spots.append((length, px, py, -nx * s, -ny * s))
                    break
        spots.sort(key=lambda s: -s[0])
        placed = 0
        for _length, px, py, fx, fy in spots:
            if placed >= FALLBACK_MAX or grid.near(px, py, 12.0):
                continue
            grid.add(px, py)
            benches.append(_bench_record(px, py, fx, fy, "face_path", "fallback", True, 1.7))
            stats["fallback"] += 1
            placed += 1
        if placed:
            stats["parks_fallback"] += 1

    return {"benches": benches, "stats": stats}


def attach_benches(
    layout: dict[str, Any],
    osm: dict[str, Any] | None,
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch/cached sources, plan placement and store the result on ``layout``."""
    try:
        payload = fetch_bench_sources(bbox, cache_path, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - offline builds still get the OSM benches
        print(f"WARNING: bench data unavailable ({exc}); using OSM benches only")
        payload = {}
    for err in payload.get("errors") or []:
        print(f"WARNING: bench source error: {err}")
    plan = plan_benches(layout, osm_benches(osm), payload, origin, bbox, osm_stop_benches(osm))
    layout["benches"] = plan["benches"]
    layout["bench_stats"] = plan["stats"]
    return plan


def summarize(plan: dict[str, Any]) -> str:
    s = plan["stats"]
    rules: dict[str, int] = {}
    for b in plan["benches"]:
        rules[b["rule"]] = rules.get(b["rule"], 0) + 1
    return (
        f"{len(plan['benches'])} benches ({s['osm']} OSM, {s['antwerp']} Stad Antwerpen, "
        f"{s['stop']} stop shelters, {s['fallback']} fallback in {s['parks_fallback']} bench-less parks); dropped "
        f"{s['dropped_duplicate']} dup / {s['dropped_building']} building / "
        f"{s['dropped_carriageway']} carriageway / {s['dropped_rail']} tram-bed, "
        f"{s['nudged_to_kerb']} nudged to kerb; facing: "
        + ", ".join(f"{k}={v}" for k, v in sorted(rules.items()))
    )
