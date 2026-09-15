"""Fetch and parse OpenStreetMap data for an Antwerp tile."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cityview.geo import project

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

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

BUILDING_STYLES = [
    "cream-tile",
    "yellow-brick",
    "red-brick",
    "white-modern",
    "antwerp-70s",
    "brown-tile",
]


def overpass_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return f"""
[out:json][timeout:90];
(
  way["highway"]({bbox});
  way["building"]({bbox});
  way["natural"="water"]({bbox});
  way["waterway"="riverbank"]({bbox});
  way["waterway"="dock"]({bbox});
  way["landuse"="basin"]({bbox});
  way["water"]({bbox});
  relation["natural"="water"]({bbox});
  relation["water"]({bbox});
  relation["landuse"="basin"]({bbox});
);
(._;>;);
out body;
""".strip()


def fetch_osm(bbox: tuple[float, float, float, float], cache_path: Path) -> dict[str, Any]:
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    south, west, north, east = bbox
    body = urllib.parse.urlencode({"data": overpass_query(south, west, north, east)}).encode()
    last_error: Exception | None = None
    for url in OVERPASS_URLS:
        req = urllib.request.Request(
            url,
            data=body,
            headers={"User-Agent": "city-view/0.1 (Antwerp procedural city)"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            payload = None
    else:
        raise RuntimeError(f"Overpass fetch failed: {last_error}") from last_error
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
    raw = tags.get("height")
    if raw:
        try:
            return max(4.0, min(80.0, float(raw.replace("m", "").split()[0])))
        except ValueError:
            pass
    levels = tags.get("building:levels")
    if levels:
        try:
            return max(6.0, min(80.0, float(levels.split(";")[0]) * 3.15))
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
    }
    return defaults.get(kind, 12.0)


def style_for(osm_id: int, tags: dict[str, str]) -> str:
    kind = tags.get("building", "")
    if kind in {"industrial", "warehouse", "manufacture"}:
        return "prefab-70s"
    if kind in {"apartments", "office"}:
        return "white-modern"
    if kind in {"church", "cathedral", "chapel"}:
        return "cream-tile"
    return BUILDING_STYLES[osm_id % len(BUILDING_STYLES)]


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


def layout_from_osm(
    osm: dict[str, Any],
    origin: tuple[float, float],
) -> dict[str, Any]:
    nodes, ways, rels = _index(osm.get("elements") or [])
    buildings: list[dict[str, Any]] = []
    roads: list[dict[str, Any]] = []
    water: list[dict[str, Any]] = []

    for way in ways.values():
        tags = way.get("tags") or {}
        pts = _way_xy(way, nodes, origin)
        if len(pts) < 2:
            continue
        if "building" in tags:
            ring = _closed(pts)
            area = _area(ring)
            if len(ring) >= 3 and 20.0 <= area <= 12000.0:
                buildings.append(
                    {
                        "id": int(way["id"]),
                        "ring": ring,
                        "height": height_for(tags),
                        "style": style_for(int(way["id"]), tags),
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
        if not (
            tags.get("natural") == "water"
            or "water" in tags
            or tags.get("landuse") == "basin"
            or tags.get("waterway") in {"river", "riverbank", "dock"}
        ):
            continue
        for i, ring in enumerate(_relation_rings(rel, ways, nodes, origin)):
            if _area(ring) >= 80.0:
                water.append({"id": int(rel["id"]) * 100 + i, "ring": ring})

    return {
        "origin": list(origin),
        "buildings": buildings,
        "roads": roads,
        "water": water,
    }
