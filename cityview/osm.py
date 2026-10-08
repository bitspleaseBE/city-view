"""Fetch and parse OpenStreetMap data for an Antwerp tile."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cityview.geo import project
from cityview.streetscape import annotate_layout, floors_from_height, height_truth, roof_shape_for

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

SKIP_HIGHWAYS = {"corridor", "proposed", "construction", "raceway", "bus_guideway"}

# Late-70s / early-80s palette (centrum / eilandje default).
BUILDING_STYLES = [
    "cream-tile",
    "yellow-brick",
    "red-brick",
    "white-modern",
    "antwerp-70s",
    "brown-tile",
]

# Klein Antwerpen / Harmonie 2018 historic LOD1 mix (stable weighted hash).
HISTORIC_STYLES = [
    ("eclectic", 40),
    ("neoclassical", 25),
    ("neo-flemish", 12),
    ("art-nouveau", 8),
    ("art-deco", 7),
    ("international", 5),
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
  node["highway"="traffic_signals"]({bbox});
  node["highway"="crossing"]["crossing"="traffic_signals"]({bbox});
  relation["natural"="water"]({bbox});
  relation["water"]({bbox});
  relation["landuse"="basin"]({bbox});
  relation["leisure"="park"]({bbox});
);
(._;>;);
out body;
""".strip()


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
    """Assign a facade palette. policy: 'default' (70s) or 'historic' (Klein Antwerpen)."""
    kind = tags.get("building", "")
    amenity = tags.get("amenity", "")
    levels = _levels(tags)

    if policy == "historic":
        if kind in {"church", "cathedral", "chapel"} or amenity == "place_of_worship":
            return "neo-gothic" if _stable_unit(osm_id) < 0.55 else "neoclassical"
        if kind in {"industrial", "warehouse", "manufacture"}:
            return "international"
        if kind in {"apartments", "office"} or (levels is not None and levels >= 6):
            return "art-deco" if _stable_unit(osm_id + 17) < 0.55 else "international"
        if kind in {"garage", "garages", "shed", "service"}:
            return "modern-infill"
        return _weighted_historic(osm_id)

    if kind in {"industrial", "warehouse", "manufacture"}:
        return "prefab-70s"
    if kind in {"apartments", "office"}:
        return "white-modern"
    if kind in {"church", "cathedral", "chapel"}:
        return "cream-tile"
    return BUILDING_STYLES[osm_id % len(BUILDING_STYLES)]


def height_jitter(osm_id: int, height: float, amount: float = 0.05) -> float:
    """±amount relative height variation from a stable id hash."""
    unit = _stable_unit(osm_id ^ 0xA5A5)
    factor = 1.0 + (unit * 2.0 - 1.0) * amount
    return max(3.0, height * factor)


def road_width(tags: dict[str, str]) -> float | None:
    highway = tags.get("highway")
    if not highway or highway in SKIP_HIGHWAYS:
        return None
    return ROAD_WIDTHS.get(highway, 5.5)


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

    for way in ways.values():
        tags = way.get("tags") or {}
        pts = _way_xy(way, nodes, origin)
        if len(pts) < 2:
            continue
        if "building" in tags:
            ring = _closed(pts)
            area = _area(ring)
            if len(ring) >= 3 and 20.0 <= area <= 12000.0:
                osm_id = int(way["id"])
                style = style_for(osm_id, tags, style_policy)
                eaves, roof_h, floors = height_truth(tags)
                if style_policy == "historic":
                    eaves = height_jitter(osm_id, eaves, amount=0.04)
                    if roof_h <= 0.0:
                        roof_h = min(3.8, max(1.3, eaves * 0.15))
                roof_shape = roof_shape_for(tags, style, osm_id)
                if roof_shape == "flat":
                    roof_h = max(0.35, min(roof_h, 0.6)) if roof_h else 0.4
                buildings.append(
                    {
                        "id": osm_id,
                        "ring": ring,
                        "height": eaves,
                        "roof_height": roof_h,
                        "floors": floors or floors_from_height(eaves, tags),
                        "roof_shape": roof_shape,
                        "style": style,
                        "name": tags.get("name") or tags.get("addr:housenumber") or "",
                    }
                )
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
            roads.append(
                {
                    "id": int(way["id"]),
                    "points": pts,
                    "width": width,
                    "kind": tags.get("highway", "residential"),
                }
            )

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
    for node in nodes.values():
        tags = node.get("tags") or {}
        if tags.get("highway") == "traffic_signals" or (
            tags.get("highway") == "crossing" and tags.get("crossing") == "traffic_signals"
        ):
            lat = float(node["lat"])
            lon = float(node["lon"])
            x, y = project(lat, lon, origin[0], origin[1])
            signals.append({"id": int(node["id"]), "x": x, "y": y, "kind": "traffic_signals"})

    layout = {
        "origin": list(origin),
        "buildings": buildings,
        "roads": roads,
        "water": water,
        "parks": parks,
        "signals": signals,
    }
    return annotate_layout(layout)
