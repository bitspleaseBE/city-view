"""Courtyard / yard ground surfaces from OpenStreetMap area ways.

The block interiors behind the facades used to be one flat gravel plane. OSM maps a lot of
what actually lies there as closed areas, so this is surveyed geometry, not invented detail:

===========================  ====================================  ==========  =========
OSM tags                     what it is                            default     layer
===========================  ====================================  ==========  =========
``amenity=parking``          surface car park / forecourt          asphalt     paving
``leisure=playground``       play area                             rubber      sport
``leisure=pitch``            sports pitch                          turf        sport
``leisure=schoolyard``       school playground                     paving      paving
``leisure=outdoor_seating``  terrace                               paving      paving
``leisure=dog_park``         fenced dog run                        grass       grass
``landuse=village_green``    common green                          grass       grass
``landuse=garages``          garage court                          concrete    paving
``landuse=construction``     building site                         dirt        earth
``landuse=forest`` / wood    wooded ground                         woodland    earth
``leisure=swimming_pool``    pool                                  pool        water
``amenity=fountain``         fountain basin                        pool        water
===========================  ====================================  ==========  =========

``surface=*`` overrides the default where it is mapped (paving stones, sett, concrete, gravel,
grass, artificial turf ...). Street-side / lane parking is skipped (that is the carriageway),
as are multi-storey, underground and roof parking, ``building=*`` areas, and anything the
builder already draws as a park or water body. Areas are drawn as flat polygons a few
millimetres above the yard plane and below every road / pavement layer, so overlaps with the
street resolve by themselves; nothing is clipped or invented.
"""

from __future__ import annotations

import math
from typing import Any

from cityview.geo import project

ATTRIBUTION = "Courtyard surfaces: (c) OpenStreetMap contributors (ODbL)."

# Render layers, low to high; the Z of each is set in blender/courtyards_blender.py.
LAYERS = ("earth", "grass", "paving", "sport", "water")

MIN_AREA_M2 = 12.0
MAX_AREA_M2 = 30000.0

# kind -> (default surface, layer)
KINDS: dict[str, tuple[str, str]] = {
    "parking": ("asphalt", "paving"),
    "playground": ("rubber", "sport"),
    "pitch": ("turf", "sport"),
    "schoolyard": ("paving", "paving"),
    "seating": ("paving", "paving"),
    "dog_park": ("grass", "grass"),
    "green": ("grass", "grass"),
    "garages": ("concrete", "paving"),
    "construction": ("dirt", "earth"),
    "woodland": ("woodland", "earth"),
    "pool": ("pool", "water"),
}

# ``surface=*`` -> drawn surface. Anything else keeps the kind's default.
SURFACE_MAP = {
    "asphalt": "asphalt",
    "paving_stones": "paving",
    "paving_stones:lanes": "paving",
    "paved": "paving",
    "concrete": "concrete",
    "concrete:plates": "concrete",
    "concrete:lanes": "concrete",
    "sett": "sett",
    "cobblestone": "sett",
    "unhewn_cobblestone": "sett",
    "compacted": "gravel",
    "gravel": "gravel",
    "fine_gravel": "gravel",
    "ground": "dirt",
    "dirt": "dirt",
    "earth": "dirt",
    "sand": "gravel",
    "grass": "grass",
    "grass_paver": "grass",
    "artificial_turf": "turf",
    "tartan": "rubber",
    "rubber": "rubber",
}
SKIP_PARKING = {"street_side", "lane", "on_kerb", "half_on_kerb", "multi-storey", "underground", "rooftop", "layby"}


def classify(tags: dict[str, str]) -> str | None:
    """Courtyard area kind for an OSM way's tags, or ``None`` if it is not one."""
    if "building" in tags or "building:part" in tags:
        return None
    if tags.get("location") in {"underground", "underwater", "roof", "rooftop"} or tags.get("tunnel") in {
        "yes",
        "building_passage",
    }:
        return None
    try:
        if float(str(tags.get("layer", "0")).split(";")[0]) < 0:
            return None
    except ValueError:
        pass
    amenity = tags.get("amenity")
    leisure = tags.get("leisure")
    landuse = tags.get("landuse")
    if amenity == "parking":
        if tags.get("parking") in SKIP_PARKING:
            return None
        return "parking"
    if amenity == "fountain" or leisure == "swimming_pool":
        return "pool"
    if leisure == "playground":
        return "playground"
    if leisure == "pitch":
        return "pitch"
    if leisure == "schoolyard":
        return "schoolyard"
    if leisure == "outdoor_seating":
        return "seating"
    if leisure == "dog_park":
        return "dog_park"
    if landuse == "village_green":
        return "green"
    if landuse == "garages":
        return "garages"
    if landuse == "construction":
        return "construction"
    if landuse == "forest" or tags.get("natural") == "wood":
        return "woodland"
    return None


def surface_for(tags: dict[str, str], kind: str) -> str:
    """Drawn surface: the mapped ``surface=*`` when we know it, else the kind's default."""
    default = KINDS[kind][0]
    if kind in {"pool", "woodland"}:
        return default
    mapped = SURFACE_MAP.get(str(tags.get("surface", "")).lower())
    return mapped or default


def layer_for(kind: str, surface: str) -> str:
    """Draw layer: a grass playground sits with the grass, a dirt court with the earth."""
    layer = KINDS[kind][1]
    if layer == "water":
        return layer
    if surface == "grass":
        return "grass"
    if surface == "dirt":
        return "earth"
    return layer


def osm_areas(osm: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Classified closed areas ``{id, kind, surface, pts: [(lat, lon)...]}`` (open ways dropped)."""
    elements = (osm or {}).get("elements") or []
    nodes = {int(e["id"]): e for e in elements if e.get("type") == "node"}
    out: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = {k: str(v) for k, v in (el.get("tags") or {}).items()}
        kind = classify(tags)
        if kind is None:
            continue
        ids = [int(n) for n in el.get("nodes") or []]
        if len(ids) < 4 or ids[0] != ids[-1]:
            continue
        pts = [(float(nodes[n]["lat"]), float(nodes[n]["lon"])) for n in ids[:-1] if n in nodes]
        if len(pts) < 3:
            continue
        surface = surface_for(tags, kind)
        out.append(
            {
                "id": int(el["id"]),
                "kind": kind,
                "surface": surface,
                "layer": layer_for(kind, surface),
                "pts": pts,
            }
        )
    return out


def ring_area(ring: list[list[float]]) -> float:
    """Signed shoelace area (positive = counter-clockwise)."""
    n = len(ring)
    total = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total * 0.5


def _simple(ring: list[list[float]]) -> bool:
    """False for self-intersecting rings (triangle fill would produce junk)."""
    n = len(ring)

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = ring[j], ring[(j + 1) % n]
            if ccw(a, b, c) * ccw(a, b, d) < 0 and ccw(c, d, a) * ccw(c, d, b) < 0:
                return False
    return True


def plan_courtyards(
    items: list[dict[str, Any]],
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
    exclude_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Return ``{"courtyards": [...], "stats": {...}}``; each area is ``{id, kind, surface, layer, ring}``.

    Rings are local metres, counter-clockwise, without the closing duplicate. ``exclude_ids`` are
    ways the builder already draws (parks, water) so nothing is drawn twice.
    """
    exclude_ids = exclude_ids or set()
    stats: dict[str, Any] = {"area_m2": 0.0, "dropped_small": 0, "dropped_large": 0, "dropped_outside": 0, "dropped_invalid": 0}
    if bbox is not None:
        x_lo, y_lo = project(bbox[0], bbox[1], origin[0], origin[1])
        x_hi, y_hi = project(bbox[2], bbox[3], origin[0], origin[1])
    else:
        x_lo = y_lo = -math.inf
        x_hi = y_hi = math.inf
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: (i["kind"], i["id"])):
        if int(item["id"]) in exclude_ids:
            continue
        ring = [[round(x, 3), round(y, 3)] for x, y in (project(lat, lon, origin[0], origin[1]) for lat, lon in item["pts"])]
        if not any(x_lo <= x <= x_hi and y_lo <= y <= y_hi for x, y in ring):
            stats["dropped_outside"] += 1
            continue
        area = ring_area(ring)
        if abs(area) < MIN_AREA_M2:
            stats["dropped_small"] += 1
            continue
        if abs(area) > MAX_AREA_M2:
            stats["dropped_large"] += 1
            continue
        if not _simple(ring):
            stats["dropped_invalid"] += 1
            continue
        if area < 0:
            ring.reverse()
        out.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "surface": item["surface"],
                "layer": item["layer"],
                "ring": ring,
            }
        )
        stats[item["kind"]] = stats.get(item["kind"], 0) + 1
        stats["area_m2"] += abs(area)
    stats["area_m2"] = round(stats["area_m2"], 1)
    return {"courtyards": out, "stats": stats}


def attach_courtyards(
    layout: dict[str, Any],
    osm: dict[str, Any] | None,
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
) -> dict[str, Any]:
    """Plan OSM courtyard surfaces and store them on ``layout`` (OSM already loaded)."""
    drawn = {int(p["id"]) for p in layout.get("parks") or []} | {int(w["id"]) for w in layout.get("water") or []}
    plan = plan_courtyards(osm_areas(osm), origin, bbox, exclude_ids=drawn)
    layout["courtyards"] = plan["courtyards"]
    layout["courtyard_stats"] = plan["stats"]
    return plan


def summarize(plan: dict[str, Any]) -> str:
    s = plan["stats"]
    placed = ", ".join(f"{k}={s[k]}" for k in KINDS if s.get(k))
    dropped = ", ".join(f"{k[8:]}={v}" for k, v in s.items() if k.startswith("dropped_") and v)
    return f"{len(plan['courtyards'])} areas, {s['area_m2']:.0f} m2 ({placed or 'none'}); dropped: {dropped or 'none'}"
