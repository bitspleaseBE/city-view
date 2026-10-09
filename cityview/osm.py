"""Fetch and parse OpenStreetMap data for an Antwerp tile."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cityview.building_heights import (
    FLOOR_H,
    MAX_LEVELS,
    parse_height_m,
    parse_levels,
    resolve_heights,
)
from cityview.directions import (
    parse_oneway,
    parse_oneway_bus,
    parse_track_direction,
    route_way_directions,
)
from cityview.geo import project
from cityview.landmarks import attach_landmark, load_manifest
from cityview.parking import parse_road_parking
from cityview.shop_brands import normalize_shop_brand
from cityview.streetscape import (
    annotate_layout,
    floors_from_height,
    height_truth,
    parse_maxspeed_kmh,
    roof_shape_for,
    safe_roof_shape,
)

OVERPASS_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
OSM_MAP_URL = "https://api.openstreetmap.org/api/0.6/map"

ROAD_WIDTHS = {
    "motorway": 16.0,
    "motorway_link": 8.0,
    "trunk": 12.0,
    "trunk_link": 7.0,
    "primary": 10.0,
    "primary_link": 6.5,
    "secondary": 8.0,
    "secondary_link": 6.0,
    "tertiary": 7.0,
    "tertiary_link": 5.5,
    "unclassified": 6.2,
    "residential": 6.2,
    "living_street": 5.4,
    "service": 4.0,
    "pedestrian": 8.0,
    "footway": 2.2,
    "path": 2.0,
    "cycleway": 2.4,
    "steps": 2.0,
}

SKIP_HIGHWAYS = {
    "corridor",
    "proposed",
    "construction",
    "raceway",
    "bus_guideway",
    "platform",
    "tram",
    "elevator",
    "bridleway",
}

# Late-70s / early-80s building types (centrum / eilandje default).
BUILDING_STYLES = [
    "cream-tile",
    "yellow-brick",
    "red-brick",
    "white-modern",
    "antwerp-70s",
    "brown-tile",
]

# Klein Antwerpen / Harmonie — weighted building types (photo-remixed looks).
# Kept in sync with cityview.building_types.TYPE_SPECS weight_historic.
HISTORIC_STYLES = [
    ("eclectic", 28),
    ("neoclassical", 18),
    ("neo-flemish", 11),
    ("cream-tile", 8),
    ("yellow-brick", 7),
    ("red-brick", 7),
    ("art-nouveau", 7),
    ("art-deco", 6),
    ("international", 4),
    ("modern-infill", 3),
]


def overpass_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return f"""
[out:json][timeout:90];
(
  way["highway"]({bbox});
  way["building"]({bbox});
  way["leisure"="park"]({bbox});
  way["leisure"="garden"]({bbox});
  way["landuse"="grass"]({bbox});
  way["natural"="water"]({bbox});
  way["waterway"="riverbank"]({bbox});
  way["waterway"="dock"]({bbox});
  way["landuse"="basin"]({bbox});
  way["water"]({bbox});
  way["railway"="tram"]({bbox});
  way["railway"="subway"]({bbox});
  way["railway"="light_rail"]({bbox});
  node["highway"="traffic_signals"]({bbox});
  node["highway"="crossing"]["crossing"="traffic_signals"]({bbox});
  node["amenity"="bench"]({bbox});
  way["amenity"="bench"]({bbox});
  node["highway"="bus_stop"]({bbox});
  node["railway"="tram_stop"]({bbox});
  node["public_transport"="platform"]({bbox});
  node["public_transport"="stop_position"]({bbox});
  node["amenity"~"^(place_of_worship|school|university|kindergarten|hospital|clinic|restaurant|cafe|fast_food|pharmacy)$"]({bbox});
  way["amenity"~"^(place_of_worship|school|university|kindergarten|hospital|clinic|restaurant|cafe|fast_food|pharmacy)$"]({bbox});
  node["shop"~"^(supermarket|convenience)$"]({bbox});
  way["shop"~"^(supermarket|convenience)$"]({bbox});
  relation["natural"="water"]({bbox});
  relation["water"]({bbox});
  relation["landuse"="basin"]({bbox});
  relation["leisure"="park"]({bbox});
  relation["route"~"^(tram|bus|subway|light_rail)$"]({bbox});
);
(._;>;);
out body;
""".strip()

POI_AMENITIES = {
    "place_of_worship",
    "school",
    "university",
    "kindergarten",
    "hospital",
    "clinic",
    "restaurant",
    "cafe",
    "fast_food",
    "pharmacy",
}
POI_SHOPS = {"supermarket", "convenience"}
CAMPUS_AMENITIES = {"hospital", "school", "university", "kindergarten"}
CAMPUS_AREA_MAX = 50000.0
POI_JOIN_M = 25.0
BUILDING_AREA_MAX = 12000.0


RAILWAY_MODES = {
    "tram": "tram",
    "subway": "subway",
    "light_rail": "tram",
}

ROUTE_MODES = {
    "tram": "tram",
    "bus": "bus",
    "subway": "subway",
    "light_rail": "tram",
}


def _is_underground(tags: dict[str, str]) -> bool:
    """Tunnelled / sub-surface ways (Antwerp premetro) must not be drawn at grade.

    ``tunnel=building_passage`` is an at-grade porte-cochère through a building, not
    underground — those are handled by ``cityview.passages`` when cutting footprints.
    """
    if tags.get("tunnel") in {"yes", "culvert"}:
        return True
    try:
        return int(str(tags.get("layer", "0")).split(";")[0]) < 0
    except ValueError:
        return False


def _pedestrian_crossing_kind(tags: dict[str, str]) -> str | None:
    """OSM node tags for a marked pedestrian crossing (or tram/rail level crossing)."""
    if tags.get("highway") == "crossing":
        if tags.get("crossing") in {"unmarked", "no"}:
            return None
        return "signals" if tags.get("crossing") == "traffic_signals" else "marked"
    if tags.get("railway") in {"crossing", "tram_crossing", "level_crossing"}:
        return "rail"
    return None


def _split_refs(raw: str | None) -> list[str]:
    if not raw:
        return []
    refs: list[str] = []
    for part in raw.replace(";", ",").replace("/", ",").split(","):
        ref = part.strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _stop_mode(tags: dict[str, str]) -> str | None:
    railway = tags.get("railway")
    if railway == "tram_stop":
        return "tram"
    if railway in {"subway_entrance", "station"} and tags.get("station") == "subway":
        return "subway"
    if tags.get("highway") == "bus_stop":
        return "bus"
    if tags.get("public_transport") in {"platform", "stop_position", "station"}:
        if tags.get("tram") == "yes" or railway == "tram":
            return "tram"
        if tags.get("subway") == "yes" or railway == "subway":
            return "subway"
        if tags.get("bus") == "yes" or tags.get("highway") == "bus_stop":
            return "bus"
        # Platforms along tram tracks often omit mode tags in Antwerp.
        if railway in {"platform", "tram_stop"}:
            return "tram"
        return "bus"
    return None


def _dedupe_stops(stops: list[dict[str, Any]], merge_m: float = 22.0) -> list[dict[str, Any]]:
    """Collapse nearby stop_position/platform duplicates; prefer named + platform.

    Never merge different modes (tram platform next to a bus shelter at Harmonie).
    """
    ranked = sorted(
        stops,
        key=lambda s: (
            0 if s.get("name") else 1,
            0 if s.get("role") == "platform" else 1,
            s.get("id") or 0,
        ),
    )
    kept: list[dict[str, Any]] = []
    for stop in ranked:
        sx, sy = float(stop["x"]), float(stop["y"])
        mode = stop.get("mode")
        duplicate = False
        for existing in kept:
            if existing.get("mode") != mode:
                continue
            if abs(float(existing["x"]) - sx) > merge_m or abs(float(existing["y"]) - sy) > merge_m:
                continue
            if (float(existing["x"]) - sx) ** 2 + (float(existing["y"]) - sy) ** 2 <= merge_m * merge_m:
                refs = list(existing.get("refs") or [])
                for ref in stop.get("refs") or []:
                    if ref not in refs:
                        refs.append(ref)
                existing["refs"] = refs
                if not existing.get("name") and stop.get("name"):
                    existing["name"] = stop["name"]
                duplicate = True
                break
        if not duplicate:
            clean = {k: v for k, v in stop.items() if k != "role"}
            kept.append(clean)
    return kept


def _stop_refs(tags: dict[str, str]) -> list[str]:
    refs = _split_refs(tags.get("ref") or tags.get("route_ref"))
    for key in ("route_ref:De_Lijn", "ref:De_Lijn"):
        for ref in _split_refs(tags.get(key)):
            # ref:De_Lijn is a stop id (numeric long); keep route_ref lines only.
            if key.startswith("ref:") and ref.isdigit() and len(ref) > 3:
                continue
            if ref not in refs:
                refs.append(ref)
    return refs


def _route_refs_by_way(
    rels: dict[int, dict],
) -> dict[int, list[str]]:
    """Map OSM way id → route line refs from tram/bus route relations."""
    by_way: dict[int, list[str]] = {}
    for rel in rels.values():
        tags = rel.get("tags") or {}
        mode = ROUTE_MODES.get(tags.get("route") or "")
        if not mode:
            continue
        refs = _split_refs(tags.get("ref"))
        if not refs:
            continue
        for member in rel.get("members") or []:
            if member.get("type") != "way":
                continue
            wid = int(member["ref"])
            bucket = by_way.setdefault(wid, [])
            for ref in refs:
                if ref not in bucket:
                    bucket.append(ref)
    return by_way


def _osm_xml_to_elements(xml_text: str) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    elements: list[dict[str, Any]] = []
    for node in root.findall("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
        item = {
            "type": "node",
            "id": int(node.attrib["id"]),
            "lat": float(node.attrib["lat"]),
            "lon": float(node.attrib["lon"]),
        }
        if tags:
            item["tags"] = tags
        elements.append(item)
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        item = {
            "type": "way",
            "id": int(way.attrib["id"]),
            "nodes": [int(nd.attrib["ref"]) for nd in way.findall("nd")],
        }
        if tags:
            item["tags"] = tags
        elements.append(item)
    for rel in root.findall("relation"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in rel.findall("tag")}
        item = {
            "type": "relation",
            "id": int(rel.attrib["id"]),
            "members": [
                {
                    "type": member.attrib.get("type"),
                    "ref": int(member.attrib["ref"]),
                    "role": member.attrib.get("role", ""),
                }
                for member in rel.findall("member")
            ],
        }
        if tags:
            item["tags"] = tags
        elements.append(item)
    return elements


def _fetch_overpass(south: float, west: float, north: float, east: float) -> dict[str, Any]:
    body = urllib.parse.urlencode({"data": overpass_query(south, west, north, east)}).encode()
    last_error: Exception | None = None
    for url in OVERPASS_URLS[:1]:
        req = urllib.request.Request(
            url,
            data=body,
            headers={"User-Agent": "city-view/0.1 (Antwerp procedural city)"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"Overpass fetch failed: {last_error}") from last_error


def _fetch_osm_map(south: float, west: float, north: float, east: float) -> dict[str, Any]:
    # Official map API uses minlon,minlat,maxlon,maxlat.
    url = f"{OSM_MAP_URL}?bbox={west:.6f},{south:.6f},{east:.6f},{north:.6f}"
    req = urllib.request.Request(url, headers={"User-Agent": "city-view/0.1 (Antwerp procedural city)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        xml_text = resp.read().decode()
    return {"elements": _osm_xml_to_elements(xml_text)}


def fetch_osm(bbox: tuple[float, float, float, float], cache_path: Path) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    south, west, north, east = bbox
    try:
        payload = _fetch_overpass(south, west, north, east)
    except Exception:
        payload = _fetch_osm_map(south, west, north, east)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload))
    return payload


def _index(elements: list[dict[str, Any]]) -> tuple[dict[int, dict], dict[int, dict], dict[int, dict]]:
    nodes, ways, rels = {}, {}, {}
    for el in elements:
        kind = el.get("type")
        eid = int(el["id"])
        if kind == "node":
            nodes[eid] = el
        elif kind == "way":
            ways[eid] = el
        elif kind == "relation":
            rels[eid] = el
    return nodes, ways, rels


def _way_xy(way: dict[str, Any], nodes: dict[int, dict], origin: tuple[float, float]) -> list[list[float]]:
    pts: list[list[float]] = []
    for nid in way.get("nodes") or []:
        node = nodes.get(int(nid))
        if not node:
            continue
        x, y = project(float(node["lat"]), float(node["lon"]), origin[0], origin[1])
        if pts and abs(pts[-1][0] - x) < 0.01 and abs(pts[-1][1] - y) < 0.01:
            continue
        pts.append([round(x, 3), round(y, 3)])
    return pts


def _closed(ring: list[list[float]]) -> list[list[float]]:
    if len(ring) >= 4 and ring[0] == ring[-1]:
        return ring[:-1]
    return ring


def _area(ring: list[list[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    acc = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        acc += x1 * y2 - x2 * y1
    return abs(acc) * 0.5


def height_for(tags: dict[str, str]) -> float:
    eaves, roof_h, _floors = height_truth(tags)
    return eaves + max(0.0, roof_h) * 0.5


def _stable_unit(osm_id: int) -> float:
    """Deterministic 0..1 from OSM id (not Python's randomized hash)."""
    x = (osm_id * 1103515245 + 12345) & 0x7FFFFFFF
    return x / 0x7FFFFFFF


def _weighted_historic(osm_id: int) -> str:
    roll = _stable_unit(osm_id) * 100.0
    acc = 0.0
    for name, weight in HISTORIC_STYLES:
        acc += weight
        if roll < acc:
            return name
    return HISTORIC_STYLES[-1][0]


def _levels(tags: dict[str, str]) -> float | None:
    raw = tags.get("building:levels")
    if not raw:
        return None
    try:
        return float(raw.split(";")[0])
    except ValueError:
        return None


def style_for(osm_id: int, tags: dict[str, str], policy: str = "default") -> str:
    """Assign a building type / facade look. policy: 'default' or 'historic'."""
    return building_type_for(osm_id, tags, policy)


def _special_use_type(tags: dict[str, str]) -> str | None:
    """Return a special building_type from OSM use tags, or None."""
    kind = tags.get("building", "")
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    if (
        kind in {"church", "cathedral", "chapel", "basilica", "monastery"}
        or amenity == "place_of_worship"
    ):
        return "church"
    if kind == "hospital" or amenity in {"hospital", "clinic"}:
        return "hospital"
    if kind == "school" or amenity in {"school", "university", "kindergarten"}:
        return "school"
    if shop in POI_SHOPS:
        return "supermarket"
    if amenity in {"restaurant", "cafe", "fast_food"}:
        return "restaurant"
    return None


def building_type_for(osm_id: int, tags: dict[str, str], policy: str = "default") -> str:
    """Assign a building type id for photo-remixed facades and roof preference."""
    special = _special_use_type(tags)
    if special:
        return special

    kind = tags.get("building", "")
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    levels = _levels(tags)

    if policy == "historic":
        if kind in {"industrial", "warehouse", "manufacture"}:
            return "international"
        if kind in {"apartments", "office"} or (levels is not None and levels >= 6):
            return "art-deco" if _stable_unit(osm_id + 17) < 0.55 else "international"
        if kind in {"garage", "garages", "shed", "service"}:
            return "modern-infill"
        if shop or kind in {"retail", "commercial"} or amenity == "pharmacy":
            return "cream-tile" if _stable_unit(osm_id + 3) < 0.6 else "eclectic"
        return _weighted_historic(osm_id)

    if kind in {"industrial", "warehouse", "manufacture"}:
        return "prefab-70s"
    if kind in {"apartments", "office"}:
        return "white-modern"
    if shop or kind in {"retail", "commercial"}:
        return "cream-tile"
    return BUILDING_STYLES[osm_id % len(BUILDING_STYLES)]


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray-cast point-in-polygon (ring not closed)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    if not ring:
        return (0.0, 0.0)
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def _is_poi_tags(tags: dict[str, str]) -> bool:
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    return amenity in POI_AMENITIES or shop in POI_SHOPS


def _collect_poi_nodes(
    nodes: dict[int, dict],
    origin: tuple[float, float],
) -> list[dict[str, Any]]:
    pois: list[dict[str, Any]] = []
    for node in nodes.values():
        tags = node.get("tags") or {}
        if not _is_poi_tags(tags):
            continue
        if "lat" not in node or "lon" not in node:
            continue
        x, y = project(float(node["lat"]), float(node["lon"]), origin[0], origin[1])
        pois.append(
            {
                "id": int(node["id"]),
                "x": x,
                "y": y,
                "tags": tags,
            }
        )
    return pois


def _merge_use_tags(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    """Merge POI tags onto building tags; special-use keys win from higher-priority POI."""
    out = dict(base)
    # Priority: worship/hospital/school > supermarket > restaurant > other
    prio = {
        "place_of_worship": 50,
        "hospital": 45,
        "clinic": 44,
        "school": 40,
        "university": 39,
        "kindergarten": 38,
        "supermarket": 30,
        "convenience": 28,
        "restaurant": 20,
        "cafe": 19,
        "fast_food": 18,
        "pharmacy": 10,
    }

    def score(tags: dict[str, str]) -> int:
        return max(
            prio.get(tags.get("amenity", ""), 0),
            prio.get(tags.get("shop", ""), 0),
            1 if tags.get("name") else 0,
        )

    if score(extra) >= score(base):
        for key in ("amenity", "shop", "brand", "brand:wikidata", "operator", "name"):
            if extra.get(key):
                out[key] = extra[key]
    else:
        for key in ("amenity", "shop", "brand", "operator"):
            if extra.get(key) and key not in out:
                out[key] = extra[key]
        if extra.get("name") and not out.get("name"):
            out["name"] = extra["name"]
    return out


def join_pois_to_buildings(
    buildings: list[dict[str, Any]],
    pois: list[dict[str, Any]],
    join_m: float = POI_JOIN_M,
) -> None:
    """Attach amenity/shop node tags onto nearest/containing building footprints.

    Institutional POIs (worship / school / hospital) only join when the node
    lies inside a footprint — nearest-neighbour would turn adjacent houses into
    churches when synagogues are mapped as nodes.
    """
    if not buildings or not pois:
        return
    centroids = [_ring_centroid(b["ring"]) for b in buildings]
    pip_only = {"place_of_worship", "school", "university", "kindergarten", "hospital", "clinic"}
    for poi in pois:
        px, py = float(poi["x"]), float(poi["y"])
        tags = poi.get("tags") or {}
        amenity = tags.get("amenity", "")
        require_pip = amenity in pip_only
        best_i: int | None = None
        best_d2 = join_m * join_m
        for i, bldg in enumerate(buildings):
            ring = bldg["ring"]
            if _point_in_ring(px, py, ring):
                best_i = i
                best_d2 = -1.0
                break
            if require_pip:
                continue
            cx, cy = centroids[i]
            d2 = (cx - px) ** 2 + (cy - py) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_i = i
        if best_i is None:
            continue
        bldg = buildings[best_i]
        merged = _merge_use_tags(dict(bldg.get("_tags") or {}), tags)
        bldg["_tags"] = merged
        # Prefer a real POI name over housenumber-only labels.
        poi_name = tags.get("name") or ""
        if poi_name and (not bldg.get("name") or str(bldg.get("name", "")).isdigit()):
            bldg["name"] = poi_name


def _use_fields(tags: dict[str, str]) -> dict[str, Any]:
    brand_key = (
        normalize_shop_brand(tags)
        if tags.get("shop") in POI_SHOPS or tags.get("amenity") == "bank"
        else None
    )
    use: dict[str, Any] = {}
    if tags.get("amenity"):
        use["amenity"] = tags["amenity"]
    if tags.get("shop"):
        use["shop"] = tags["shop"]
    if tags.get("brand"):
        use["brand"] = tags["brand"]
    if brand_key:
        use["brand_key"] = brand_key
    return use


def _make_building(
    osm_id: int,
    ring: list[list[float]],
    tags: dict[str, str],
    style_policy: str,
) -> dict[str, Any]:
    btype = building_type_for(osm_id, tags, style_policy)
    eaves, roof_h, floors = height_truth(tags)
    # Special types get type-aware height defaults when OSM lacks levels.
    if not tags.get("height") and not tags.get("building:levels"):
        if btype == "school":
            eaves, roof_h, floors = 14.0, max(roof_h, 1.8), 4
        elif btype == "hospital":
            eaves, roof_h, floors = 18.0, max(roof_h, 0.5), 5
        elif btype == "supermarket":
            eaves, roof_h, floors = 8.0, 0.4, 2
        elif btype == "church" and tags.get("building") not in {"cathedral"}:
            if eaves < 20.0:
                eaves, roof_h, floors = 28.0, max(roof_h, 4.0), 1
    if style_policy == "historic" and btype not in {
        "church",
        "hospital",
        "school",
        "supermarket",
        "restaurant",
    }:
        eaves = height_jitter(osm_id, eaves, amount=0.04)
        if roof_h <= 0.0:
            roof_h = min(3.8, max(1.3, eaves * 0.15))
    roof_shape = safe_roof_shape(roof_shape_for(tags, btype, osm_id), ring)
    if roof_shape == "flat":
        roof_h = max(0.35, min(roof_h, 0.6)) if roof_h else 0.4
    use = _use_fields(tags)
    brand_key = use.get("brand_key")
    name = tags.get("name") or tags.get("addr:housenumber") or ""
    bldg: dict[str, Any] = {
        "id": osm_id,
        "ring": ring,
        "height": eaves,
        "roof_height": roof_h,
        "floors": floors or floors_from_height(eaves, tags),
        "roof_shape": roof_shape,
        "building_type": btype,
        "style": btype,
        "name": name,
        "osm_building": tags.get("building") or "",
        "_tags": dict(tags),
    }
    if use:
        bldg["use"] = use
    if brand_key:
        bldg["brand_key"] = brand_key
    return bldg


def height_jitter(osm_id: int, height: float, amount: float = 0.05) -> float:
    """±amount relative height variation from a stable id hash."""
    unit = _stable_unit(osm_id ^ 0xA5A5)
    factor = 1.0 + (unit * 2.0 - 1.0) * amount
    return max(3.0, height * factor)


# Types whose massing is a fixed landmark/institution height when OSM has no numbers.
_TYPE_DEFAULT_BTYPES = {"church", "hospital", "school", "supermarket"}
_TYPE_DEFAULT_KINDS = {"church", "cathedral", "basilica", "chapel", "monastery"}
_TALL_FLAT_LEVELS = 7  # towers get flat roofs unless OSM maps a roof shape


def finalize_building_heights(
    buildings: list[dict[str, Any]],
    tags_list: list[dict[str, str]],
    style_policy: str = "default",
) -> dict[str, Any]:
    """Final height pass: OSM levels/height first, else a footprint/type prior.

    Replaces the old "everything without levels is 12 m / 4 floors" fallback (see
    ``cityview/building_heights.py``). Mutates ``height``, ``floors``, ``roof_height``,
    ``roof_shape`` and adds ``height_source``. Returns audit stats for the layout.
    """
    for bldg, tags in zip(buildings, tags_list):
        has_osm_numbers = bool(parse_height_m(tags) or parse_levels(tags))
        kind = tags.get("building", "")
        if not has_osm_numbers and (
            bldg.get("building_type") in _TYPE_DEFAULT_BTYPES or kind in _TYPE_DEFAULT_KINDS
        ):
            bldg["height_source"] = "type_default"
    counts = resolve_heights(buildings, tags_list)
    for bldg, tags in zip(buildings, tags_list):
        source = bldg["height_source"]
        levels = int(bldg.pop("levels"))
        if source == "type_default":
            continue
        if source in {"inferred", "photo"}:
            eaves = levels * FLOOR_H
            if levels >= 2:
                eaves = height_jitter(int(bldg["id"]), eaves, amount=0.03)
            bldg["height"] = eaves
        elif source == "osm_height":
            bldg["height"] = float(bldg["height"])
        bldg["floors"] = max(1, min(MAX_LEVELS, levels))
        btype = bldg.get("building_type") or ""
        if levels >= 6 and btype not in {"church", "hospital", "school", "supermarket", "restaurant"}:
            tall_tags = {**tags, "building:levels": str(levels)}
            retyped = building_type_for(int(bldg["id"]), tall_tags, style_policy)
            if retyped != btype:
                bldg["building_type"] = retyped
                bldg["style"] = retyped
                btype = retyped
        if not tags.get("roof:shape"):
            shape = roof_shape_for(tags, btype, int(bldg["id"]))
            if levels >= _TALL_FLAT_LEVELS:
                shape = "flat"
            bldg["roof_shape"] = safe_roof_shape(shape, bldg["ring"])
        eaves = float(bldg["height"])
        if bldg["roof_shape"] == "flat":
            bldg["roof_height"] = 0.4
        elif not (tags.get("roof:levels") or tags.get("roof:height")) and style_policy == "historic":
            bldg["roof_height"] = min(3.8, max(1.3, eaves * 0.15))
    return {
        "source": counts,
        "levels": _level_histogram(buildings),
        "max_levels": MAX_LEVELS,
    }


def _level_histogram(buildings: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[int, int] = {}
    for b in buildings:
        out[int(b["floors"])] = out.get(int(b["floors"]), 0) + 1
    return {str(k): out[k] for k in sorted(out)}


def road_width(tags: dict[str, str]) -> float | None:
    highway = tags.get("highway")
    if not highway or highway in SKIP_HIGHWAYS:
        return None
    # Tram / rail ways are transit tracks, never car carriageways — even when a
    # highway tag is also present on a shared corridor.
    railway = tags.get("railway")
    if railway in RAILWAY_MODES or railway in {
        "tram",
        "rail",
        "light_rail",
        "subway",
        "narrow_gauge",
        "preserved",
    }:
        return None
    return ROAD_WIDTHS.get(highway)


def _relation_rings(
    rel: dict[str, Any],
    ways: dict[int, dict],
    nodes: dict[int, dict],
    origin: tuple[float, float],
) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    for member in rel.get("members") or []:
        if member.get("type") != "way" or member.get("role") not in {"outer", ""}:
            continue
        way = ways.get(int(member["ref"]))
        if not way:
            continue
        ring = _closed(_way_xy(way, nodes, origin))
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def _is_park(tags: dict[str, str]) -> bool:
    return tags.get("leisure") in {"park", "garden"} or tags.get("landuse") in {"grass", "recreation_ground"}


def layout_from_osm(
    osm: dict[str, Any],
    origin: tuple[float, float],
    style_policy: str = "default",
) -> dict[str, Any]:
    nodes, ways, rels = _index(osm.get("elements") or [])
    buildings: list[dict[str, Any]] = []
    roads: list[dict[str, Any]] = []
    water: list[dict[str, Any]] = []
    parks: list[dict[str, Any]] = []
    transit_lines: list[dict[str, Any]] = []
    transit_stops_raw: list[dict[str, Any]] = []
    way_refs = _route_refs_by_way(rels)
    # Tram tracks carry no direction tag: it comes from the ordered route relations.
    track_dirs = route_way_directions(rels, ways)

    for way in ways.values():
        tags = way.get("tags") or {}
        pts = _way_xy(way, nodes, origin)
        if len(pts) < 2:
            continue
        railway = tags.get("railway")
        if railway in RAILWAY_MODES and "building" not in tags:
            mode = RAILWAY_MODES[railway]
            refs = list(way_refs.get(int(way["id"])) or [])
            for ref in _split_refs(tags.get("ref")):
                if ref not in refs:
                    refs.append(ref)
            transit_lines.append(
                {
                    "id": int(way["id"]),
                    "mode": mode,
                    "points": pts,
                    "refs": refs,
                    "name": tags.get("name") or "",
                    "source": "osm",
                    "tunnel": _is_underground(tags),
                    # 1 = vehicles drive along `points`, -1 = against, 0 = unknown / both.
                    "direction": parse_track_direction(tags) or track_dirs.get(int(way["id"]), 0),
                }
            )
            # Tram tracks are not roads; continue so they are not double-counted.
            continue
        # Any remaining rail/tram geometry stays off the car road graph.
        if railway in {"tram", "rail", "light_rail", "subway", "narrow_gauge", "preserved"}:
            continue
        if tags.get("highway") in {"tram", "platform"}:
            continue
        if "building" in tags:
            ring = _closed(pts)
            area = _area(ring)
            if len(ring) >= 3 and 20.0 <= area <= BUILDING_AREA_MAX:
                buildings.append(_make_building(int(way["id"]), ring, tags, style_policy))
            continue
        # Campus polygons tagged amenity=hospital|school without building=*.
        if tags.get("amenity") in CAMPUS_AMENITIES and "building" not in tags:
            ring = _closed(pts)
            area = _area(ring)
            if len(ring) >= 3 and 20.0 <= area <= CAMPUS_AREA_MAX:
                buildings.append(_make_building(int(way["id"]), ring, tags, style_policy))
            continue
        if any(
            [
                tags.get("natural") == "water",
                tags.get("waterway") in {"riverbank", "dock"},
                tags.get("landuse") == "basin",
                "water" in tags,
            ]
        ):
            ring = _closed(pts)
            if len(ring) >= 3 and _area(ring) >= 80.0:
                water.append({"id": int(way["id"]), "ring": ring})
            continue
        if _is_park(tags):
            ring = _closed(pts)
            if len(ring) >= 3 and _area(ring) >= 80.0:
                parks.append({"id": int(way["id"]), "ring": ring, "name": tags.get("name") or ""})
            continue
        width = road_width(tags)
        if width and len(pts) >= 2:
            road = {
                "id": int(way["id"]),
                "points": pts,
                "width": width,
                "kind": tags.get("highway", "residential"),
                # Street name: lets the builder group OSM ways into one street.
                "name": tags.get("name") or "",
            }
            limit = parse_maxspeed_kmh(tags)
            if limit is not None:
                road["maxspeed_kmh"] = limit
            # Kerbside parking exactly as mapped (parking:both / :left / :right); parked cars are
            # only ever drawn where this is present (cityview/parking.py).
            parking = parse_road_parking(tags)
            if parking:
                road["parking"] = parking
            # Legal travel direction along `points` (1 / -1 / 0 = both ways), from the OSM
            # oneway tags; buses may differ (oneway:bus, contraflow bus lanes).
            road["oneway"] = parse_oneway(tags)
            road["oneway_bus"] = parse_oneway_bus(tags)
            # Porte-cochère / covered driveway through a building (cut in annotate_layout).
            if tags.get("tunnel") == "building_passage":
                road["passage"] = True
            roads.append(road)

    for rel in rels.values():
        tags = rel.get("tags") or {}
        rings = _relation_rings(rel, ways, nodes, origin)
        if (
            tags.get("natural") == "water"
            or "water" in tags
            or tags.get("landuse") == "basin"
            or tags.get("waterway") in {"river", "riverbank", "dock"}
        ):
            for i, ring in enumerate(rings):
                if _area(ring) >= 80.0:
                    water.append({"id": int(rel["id"]) * 100 + i, "ring": ring})
        elif _is_park(tags):
            for i, ring in enumerate(rings):
                if _area(ring) >= 80.0:
                    parks.append({"id": int(rel["id"]) * 100 + i, "ring": ring, "name": tags.get("name") or ""})

    signals: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    for node in nodes.values():
        tags = node.get("tags") or {}
        lat = float(node["lat"])
        lon = float(node["lon"])
        x, y = project(lat, lon, origin[0], origin[1])
        if tags.get("highway") == "traffic_signals" or (
            tags.get("highway") == "crossing" and tags.get("crossing") == "traffic_signals"
        ):
            signals.append({"id": int(node["id"]), "x": x, "y": y, "kind": "traffic_signals"})
        crossing_kind = _pedestrian_crossing_kind(tags)
        if crossing_kind:
            crossings.append(
                {"id": int(node["id"]), "x": round(x, 3), "y": round(y, 3), "kind": crossing_kind}
            )
        mode = _stop_mode(tags)
        if mode:
            role = "platform" if tags.get("public_transport") == "platform" else "stop"
            transit_stops_raw.append(
                {
                    "id": int(node["id"]),
                    "mode": mode,
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "name": tags.get("name") or tags.get("ref") or "",
                    "refs": _stop_refs(tags),
                    "role": role,
                    "source": "osm",
                }
            )

    # Join amenity/shop nodes onto footprints, then reclassify from merged tags.
    pois = _collect_poi_nodes(nodes, origin)
    join_pois_to_buildings(buildings, pois)
    manifest = load_manifest()
    finalized: list[dict[str, Any]] = []
    final_tags: list[dict[str, str]] = []
    for bldg in buildings:
        tags = dict(bldg.pop("_tags", None) or {})
        if tags:
            osm_id = int(bldg["id"])
            prev = bldg.get("building_type")
            btype = building_type_for(osm_id, tags, style_policy)
            bldg["building_type"] = btype
            bldg["style"] = btype
            use = _use_fields(tags)
            if use:
                bldg["use"] = use
            else:
                bldg.pop("use", None)
            brand_key = use.get("brand_key")
            if brand_key:
                bldg["brand_key"] = brand_key
            else:
                bldg.pop("brand_key", None)
            poi_name = tags.get("name") or ""
            if poi_name and (not bldg.get("name") or str(bldg.get("name", "")).isdigit()):
                bldg["name"] = poi_name
            if btype != prev and btype in {
                "school",
                "hospital",
                "supermarket",
                "church",
                "restaurant",
            }:
                if not tags.get("height") and not tags.get("building:levels"):
                    defaults = {
                        "school": (14.0, 1.8, 4),
                        "hospital": (18.0, 0.5, 5),
                        "supermarket": (8.0, 0.4, 2),
                        "church": (28.0, 4.0, 1),
                        "restaurant": (None, None, None),
                    }
                    eh, rh, fl = defaults[btype]
                    if eh is not None:
                        bldg["height"] = eh
                        bldg["roof_height"] = rh
                        bldg["floors"] = fl
            if not tags.get("roof:shape"):
                bldg["roof_shape"] = safe_roof_shape(
                    roof_shape_for(tags, btype, osm_id), bldg["ring"]
                )
        attach_landmark(bldg, manifest)
        finalized.append(bldg)
        final_tags.append(tags)

    height_stats = finalize_building_heights(finalized, final_tags, style_policy)

    layout = {
        "origin": list(origin),
        "buildings": finalized,
        "roads": roads,
        "water": water,
        "parks": parks,
        "signals": signals,
        "crossings": crossings,
        "transit_lines": transit_lines,
        "transit_stops": _dedupe_stops(transit_stops_raw),
        "height_stats": height_stats,
    }
    return annotate_layout(layout)
