"""Street clutter from OpenStreetMap point features — mapped objects, not procedural spam.

Every record comes from a tagged OSM node (or the centroid of a tagged way/area), so a bin,
bike hoop, bollard, hydrant, post box, recycling bring-site, street cabinet, ticket
machine, flagpole or street lamp stands where a mapper surveyed it:

=====================  ===========================================  ==================
kind                   OSM tags                                     facing
=====================  ===========================================  ==================
``bin``                ``amenity=waste_basket``                     (round)
``bike_rack``          ``amenity=bicycle_parking``  (``capacity``)   hoops along the road
``bollard``            ``barrier=bollard``                          (round)
``hydrant``            ``emergency=fire_hydrant`` (pillar only)     (round)
``post_box``           ``amenity=post_box``                         slot toward the street
``recycling``          ``amenity=recycling`` (containers)           doors toward the street
``cabinet``            ``man_made=street_cabinet``                  door toward the street
``meter``              ``vending=parking_tickets`` (pay & display)  face toward the street
``flagpole``           ``man_made=flagpole``                        (round)
``lamp``               ``highway=street_lamp``                      arm over the carriageway
``picnic_table``       ``leisure=picnic_table``                     table along the path
``charging``           ``amenity=charging_station``                 face toward the street
``vending``            ``amenity=vending_machine`` (not tickets)    face toward the street
``artwork``            ``tourism=artwork``                          face toward the street
``guidepost``          ``tourism=information`` / guidepost          board toward the street
=====================  ===========================================  ==================

Placement reuses the bench rules: duplicates within ``DEDUPE_M`` of the same kind collapse,
anything inside a building footprint, deep in a carriageway or on a tram bed is dropped, and
a point that only sits a little inside the carriageway (survey noise) slides out to the kerb.
Objects the survey does not map are *not* invented; the old every-7-m bins, bollards and
bike racks are gone.
"""

from __future__ import annotations

import math
from typing import Any

from cityview.benches import CARRIAGEWAY, KERB_CLEARANCE, _Ways
from cityview.geo import project
from cityview.railclear import CLEAR_FURNITURE
from cityview.trees import _Obstacles, _PointGrid

ATTRIBUTION = "Street clutter: (c) OpenStreetMap contributors (ODbL)."

KINDS = (
    "bin",
    "bike_rack",
    "bollard",
    "hydrant",
    "post_box",
    "recycling",
    "cabinet",
    "meter",
    "flagpole",
    "lamp",
    "picnic_table",
    "charging",
    "vending",
    "artwork",
    "guidepost",
)

DEDUPE_M = {
    "bin": 0.8,
    "bike_rack": 2.5,
    "bollard": 0.5,
    "hydrant": 1.0,
    "post_box": 1.0,
    "recycling": 2.5,
    "cabinet": 1.0,
    "meter": 1.0,
    "flagpole": 1.0,
    "lamp": 1.5,
    "picnic_table": 2.0,
    "charging": 1.5,
    "vending": 1.2,
    "artwork": 2.0,
    "guidepost": 1.5,
}
BUILDING_MARGIN = 0.15
ROAD_NUDGE_M = 1.6  # survey points up to this deep in a carriageway slide to the kerb
FACE_REACH_M = 14.0  # how far to look for the street an object faces
# Bollards close pedestrian streets and guard kerbs: they may stand on the road surface.
ON_ROAD_OK = frozenset({"bollard", "flagpole"})
# Hoops per bike_parking node when ``capacity`` is missing, and the cap per site.
DEFAULT_HOOPS = 2
MAX_HOOPS = 6
HOOP_SPACING_M = 0.8
# Max distance from the spawn for the small items (LOD); the landmarks (hydrants, post
# boxes, cabinets, flagpoles, lamps) are kept tile-wide.
SMALL_ITEM_RADIUS_M = 450.0
SMALL_KINDS = frozenset({"bin", "bike_rack", "bollard", "meter", "vending", "guidepost"})


def classify(tags: dict[str, str]) -> str | None:
    """Clutter kind of an OSM tag set, or ``None`` when it is not street clutter."""
    if tags.get("access") in {"private", "no"}:
        return None
    amenity = tags.get("amenity")
    if amenity == "waste_basket":
        return "bin"
    if amenity == "bicycle_parking":
        if tags.get("covered") == "yes" or tags.get("bicycle_parking") in {"building", "shed", "lockers"}:
            return None  # an enclosed shelter / garage entrance, not hoops on the pavement
        return "bike_rack"
    if tags.get("barrier") == "bollard":
        return "bollard"
    if tags.get("emergency") == "fire_hydrant":
        if tags.get("fire_hydrant:type") in {"underground", "wall"}:
            return None  # nothing standing above the pavement
        return "hydrant"
    if amenity == "post_box":
        return "post_box"
    if amenity == "recycling":
        if tags.get("recycling_type") == "centre":
            return None
        return "recycling"
    if tags.get("man_made") == "street_cabinet":
        return "cabinet"
    if tags.get("vending") == "parking_tickets":
        return "meter"
    if amenity == "vending_machine":
        return "vending"
    if amenity == "charging_station":
        return "charging"
    if tags.get("leisure") == "picnic_table":
        return "picnic_table"
    if tags.get("tourism") == "artwork":
        return "artwork"
    if tags.get("tourism") == "information" or tags.get("information") in {
        "guidepost",
        "board",
        "map",
        "trail_blaze",
    }:
        return "guidepost"
    if tags.get("man_made") == "flagpole":
        return "flagpole"
    if tags.get("highway") == "street_lamp":
        return "lamp"
    return None


def osm_clutter(osm: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Classified point features (nodes, plus way centroids) from an Overpass-style document."""
    elements = (osm or {}).get("elements") or []
    nodes = {int(e["id"]): e for e in elements if e.get("type") == "node"}
    out: list[dict[str, Any]] = []
    for el in elements:
        tags = {k: str(v) for k, v in (el.get("tags") or {}).items()}
        if not tags:
            continue
        kind = classify(tags)
        if kind is None:
            continue
        if el.get("type") == "node":
            lat, lon = float(el["lat"]), float(el["lon"])
        elif el.get("type") == "way":
            pts = [nodes[int(n)] for n in el.get("nodes") or [] if int(n) in nodes]
            if not pts:
                continue
            if kind in {"bollard", "bin", "hydrant", "post_box", "meter"}:
                continue  # a point object mapped as an area makes no sense; skip
            lat = sum(float(p["lat"]) for p in pts) / len(pts)
            lon = sum(float(p["lon"]) for p in pts) / len(pts)
        else:
            continue
        out.append({"id": int(el["id"]), "kind": kind, "lat": lat, "lon": lon, "tags": tags})
    return out


def hoop_count(tags: dict[str, str]) -> int:
    """Number of U-hoops for a bicycle_parking: ``capacity`` bikes / 2 per hoop, clamped."""
    try:
        cap = int(float(str(tags.get("capacity", "")).replace(",", ".")))
    except ValueError:
        return DEFAULT_HOOPS
    return max(1, min(MAX_HOOPS, (cap + 1) // 2))


def _yaw_from_facing(fx: float, fy: float) -> float:
    """Local +Y is the object's front; ``rotation_z`` that turns +Y onto ``(fx, fy)``."""
    return math.atan2(fy, fx) - math.pi / 2.0


def _record(item: dict[str, Any], x: float, y: float, yaw: float, rule: str) -> dict[str, Any]:
    rec = {"kind": item["kind"], "x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 4), "rule": rule, "id": item["id"]}
    if item["kind"] == "bike_rack":
        rec["hoops"] = hoop_count(item["tags"])
    elif item["kind"] == "recycling":
        rec["bins"] = 3 if item["tags"].get("recycling_type") == "container" else 2
    return rec


def plan_clutter(
    layout: dict[str, Any],
    items: list[dict[str, Any]],
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
    spawn_xy: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Return ``{"clutter": [...], "stats": {...}}`` in local metres."""
    obstacles = _Obstacles(layout)
    ways = _Ways(layout)
    stats: dict[str, int] = {k: 0 for k in KINDS}
    stats.update(
        {
            "dropped_duplicate": 0,
            "dropped_building": 0,
            "dropped_carriageway": 0,
            "dropped_rail": 0,
            "dropped_outside": 0,
            "dropped_far": 0,
            "nudged_to_kerb": 0,
        }
    )
    if bbox is not None:
        x_lo, y_lo = project(bbox[0], bbox[1], origin[0], origin[1])
        x_hi, y_hi = project(bbox[2], bbox[3], origin[0], origin[1])
    else:
        x_lo = y_lo = -math.inf
        x_hi = y_hi = math.inf
    grids = {k: _PointGrid(cell=4.0) for k in KINDS}
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: (i["kind"], i["id"])):
        kind = item["kind"]
        x, y = project(item["lat"], item["lon"], origin[0], origin[1])
        if not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
            stats["dropped_outside"] += 1
            continue
        if kind in SMALL_KINDS and spawn_xy is not None:
            if math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > SMALL_ITEM_RADIUS_M:
                stats["dropped_far"] += 1
                continue
        if grids[kind].near(x, y, DEDUPE_M[kind]):
            stats["dropped_duplicate"] += 1
            continue
        if obstacles.in_building(x, y, BUILDING_MARGIN):
            stats["dropped_building"] += 1
            continue
        road = ways.nearest(x, y, CARRIAGEWAY, 0.1)
        if road and road[0] < 0.1 and kind not in ON_ROAD_OK:
            depth = -road[0]
            if depth > ROAD_NUDGE_M:
                stats["dropped_carriageway"] += 1
                continue
            push = depth + KERB_CLEARANCE
            x, y = x + road[1] * push, y + road[2] * push
            stats["nudged_to_kerb"] += 1
            if obstacles.in_building(x, y, BUILDING_MARGIN) or grids[kind].near(x, y, DEDUPE_M[kind]):
                stats["dropped_carriageway"] += 1
                continue
        if obstacles.on_rails(x, y, CLEAR_FURNITURE):
            stats["dropped_rail"] += 1
            continue
        near = ways.nearest(x, y, CARRIAGEWAY, FACE_REACH_M)
        if near:
            # (nx, ny) points from the street toward the object: the front faces back at it.
            # Bike hoops are laid out along local X, so they end up running along the kerb.
            fx, fy, rule = -near[1], -near[2], "face_street"
        else:
            seed = (item["id"] * 2654435761) % 360
            fx, fy, rule = math.cos(math.radians(seed)), math.sin(math.radians(seed)), "seeded"
        grids[kind].add(x, y)
        out.append(_record(item, x, y, _yaw_from_facing(fx, fy), rule))
        stats[kind] += 1
    return {"clutter": out, "stats": stats}


def attach_clutter(
    layout: dict[str, Any],
    osm: dict[str, Any] | None,
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    spawn_xy: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Plan OSM street clutter and store it on ``layout`` (no network: OSM is already loaded)."""
    plan = plan_clutter(layout, osm_clutter(osm), origin, bbox, spawn_xy)
    layout["clutter"] = plan["clutter"]
    layout["clutter_stats"] = plan["stats"]
    return plan


def summarize(plan: dict[str, Any]) -> str:
    s = plan["stats"]
    placed = ", ".join(f"{k}={s[k]}" for k in KINDS if s.get(k))
    dropped = ", ".join(f"{k[8:]}={v}" for k, v in s.items() if k.startswith("dropped_") and v)
    return f"{len(plan['clutter'])} placed ({placed or 'none'}); nudged to kerb {s['nudged_to_kerb']}; dropped: {dropped or 'none'}"
