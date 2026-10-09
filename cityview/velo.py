"""Velo Antwerpen docking stations from the official Clear Channel GBFS feed.

Source
------
Clear Channel SmartBike GBFS for Antwerp (``system_id=cc_smartbike_antwerp``):

  https://gbfs.smartbike.com/antwerp/1.0/gbfs.json
  → …/nl/station_information.json

Station locations and capacities are authoritative. Live ``station_status`` is
not polled — dock occupancy is seeded from ``capacity`` so CI builds stay offline.

OSM ``amenity=bicycle_rental`` / ``network=Velo`` nodes exist but drift and
duplicate (e.g. two De Merode refs); they are not used for placement.

Pure stdlib: ``blender/velo_blender.py`` consumes the plan inside Blender's Python.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cityview.benches import CARRIAGEWAY, KERB_CLEARANCE, _Ways
from cityview.clutter import _yaw_from_facing
from cityview.geo import project
from cityview.paths import VELO_CACHE
from cityview.railclear import CLEAR_FURNITURE
from cityview.trees import _Obstacles, _PointGrid

STATION_INFORMATION_URL = (
    "https://gbfs.smartbike.com/antwerp/1.0/nl/station_information.json"
)
ALLOWED_HOSTS = frozenset({"gbfs.smartbike.com"})
USER_AGENT = "city-view/0.1 (Antwerp procedural city)"
ATTRIBUTION = (
    "Velo Antwerpen docking stations: Clear Channel SmartBike GBFS "
    "(https://gbfs.smartbike.com/antwerp/1.0/gbfs.json)."
)
FETCH_PAD_DEG = 0.0004

DEDUPE_M = 25.0  # same station_id should win; also collapse near-duplicates
BUILDING_MARGIN = 0.25
# GBFS points can sit a few metres inside OSM's nominal asphalt (survey vs. mapped width).
ROAD_NUDGE_M = 3.5
FACE_REACH_M = 18.0
# Gameplay keeps full capacity; Blender rails size from this slot spacing.
SLOT_SPACING_M = 0.95
# Seeded occupancy fraction of capacity (deterministic per station id).
OCCUPANCY_LO = 0.40
OCCUPANCY_HI = 0.70


# ---------------------------------------------------------------- fetching


def _http_json(url: str, timeout: float = 60.0) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to fetch Velo data from {parsed.hostname!r}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep  (https + host allowlist)
        return json.loads(resp.read().decode())


def _checked_cache_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    root = VELO_CACHE.resolve()
    if resolved.suffix != ".json" or root not in resolved.parents:
        raise ValueError(f"velo cache must be a .json file under {root}")
    return resolved


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


def fetch_gbfs_stations(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Download GBFS station_information and keep points inside ``bbox`` (s,w,n,e)."""
    doc = _http_json(STATION_INFORMATION_URL)
    stations = ((doc.get("data") or {}).get("stations")) or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for st in stations:
        try:
            lat = float(st["lat"])
            lon = float(st["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _in_bbox(lat, lon, bbox):
            continue
        sid = str(st.get("station_id") or st.get("short_name") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        cap_raw = st.get("capacity")
        try:
            capacity = int(cap_raw) if cap_raw is not None else 20
        except (TypeError, ValueError):
            capacity = 20
        capacity = max(1, min(capacity, 80))
        name = str(st.get("name") or f"{sid}- Velo")
        out.append(
            {
                "id": sid,
                "name": name,
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "capacity": capacity,
                "address": str(st.get("address") or ""),
            }
        )
    out.sort(key=lambda s: s["id"])
    return out


def fetch_velo_sources(
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Load (or download once and commit) the GBFS station payload for a tile."""
    cache_path = _checked_cache_path(cache_path)
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text())
    south, west, north, east = bbox
    padded = (
        south - FETCH_PAD_DEG,
        west - FETCH_PAD_DEG,
        north + FETCH_PAD_DEG,
        east + FETCH_PAD_DEG,
    )
    payload: dict[str, Any] = {
        "bbox": list(padded),
        "attribution": ATTRIBUTION,
        "fetched": time.strftime("%Y-%m-%d"),
        "stations": [],
        "errors": [],
    }
    try:
        payload["stations"] = fetch_gbfs_stations(padded)
    except Exception as exc:  # noqa: BLE001
        payload["errors"].append(f"gbfs: {exc}")
    if not payload["errors"] and payload["stations"]:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Path confined to assets/velo/*.json by _checked_cache_path above.
        cache_path.write_text(json.dumps(payload, separators=(",", ":")))  # nosemgrep
    return payload


# ---------------------------------------------------------------- planning


def _stable_unit(station_id: str, salt: str = "") -> float:
    digest = hashlib.blake2b(f"{station_id}:{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "little") / float(2**64)


def seeded_bikes_available(station_id: str, capacity: int) -> int:
    """Deterministic dock occupancy in ``[OCCUPANCY_LO, OCCUPANCY_HI]`` of capacity."""
    if capacity <= 0:
        return 0
    u = _stable_unit(station_id, "bikes")
    frac = OCCUPANCY_LO + (OCCUPANCY_HI - OCCUPANCY_LO) * u
    n = int(round(capacity * frac))
    return max(1, min(capacity - 1 if capacity > 1 else 1, n))


def plan_velo(
    layout: dict[str, Any],
    payload: dict[str, Any] | None,
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Return ``{"stations": [...], "stats": {...}}`` in local metres."""
    stations_in = list((payload or {}).get("stations") or [])
    obstacles = _Obstacles(layout)
    ways = _Ways(layout)
    stats = {
        "placed": 0,
        "dropped_duplicate": 0,
        "dropped_building": 0,
        "dropped_carriageway": 0,
        "dropped_rail": 0,
        "dropped_outside": 0,
        "nudged_to_kerb": 0,
        "bikes_total": 0,
        "slots_total": 0,
    }
    if bbox is not None:
        x_lo, y_lo = project(bbox[0], bbox[1], origin[0], origin[1])
        x_hi, y_hi = project(bbox[2], bbox[3], origin[0], origin[1])
        if x_lo > x_hi:
            x_lo, x_hi = x_hi, x_lo
        if y_lo > y_hi:
            y_lo, y_hi = y_hi, y_lo
    else:
        x_lo = y_lo = -math.inf
        x_hi = y_hi = math.inf

    grid = _PointGrid(cell=8.0)
    out: list[dict[str, Any]] = []
    for st in sorted(stations_in, key=lambda s: str(s.get("id") or "")):
        sid = str(st.get("id") or "")
        if not sid:
            continue
        lat, lon = float(st["lat"]), float(st["lon"])
        x, y = project(lat, lon, origin[0], origin[1])
        if not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
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
            push = depth + KERB_CLEARANCE
            x, y = x + road[1] * push, y + road[2] * push
            stats["nudged_to_kerb"] += 1
            if obstacles.in_building(x, y, BUILDING_MARGIN) or grid.near(x, y, DEDUPE_M):
                stats["dropped_carriageway"] += 1
                continue
        if obstacles.on_rails(x, y, CLEAR_FURNITURE):
            stats["dropped_rail"] += 1
            continue
        near = ways.nearest(x, y, CARRIAGEWAY, FACE_REACH_M)
        if near:
            # Face the street (same convention as bike_rack clutter): rail along kerb.
            fx, fy, rule = -near[1], -near[2], "along_street"
        else:
            seed = _stable_unit(sid, "yaw") * 360.0
            fx, fy, rule = math.cos(math.radians(seed)), math.sin(math.radians(seed)), "seeded"
        capacity = max(1, int(st.get("capacity") or 20))
        bikes = seeded_bikes_available(sid, capacity)
        rail_len = max(4.0, (capacity - 1) * SLOT_SPACING_M + 1.2)
        grid.add(x, y)
        out.append(
            {
                "id": sid,
                "name": str(st.get("name") or sid),
                "address": str(st.get("address") or ""),
                "x": round(x, 3),
                "y": round(y, 3),
                "yaw": round(_yaw_from_facing(fx, fy), 4),
                "capacity": capacity,
                "bikesAvailable": bikes,
                "railLength": round(rail_len, 2),
                "slotSpacing": SLOT_SPACING_M,
                "rule": rule,
                "source": "gbfs",
            }
        )
        stats["placed"] += 1
        stats["bikes_total"] += bikes
        stats["slots_total"] += capacity
    return {"stations": out, "stats": stats}


def attach_velo(
    layout: dict[str, Any],
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch/cached GBFS stations, plan placement and store the result on ``layout``."""
    try:
        payload = fetch_velo_sources(bbox, cache_path, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Velo data unavailable ({exc})")
        payload = {"stations": [], "errors": [str(exc)]}
    for err in payload.get("errors") or []:
        print(f"WARNING: Velo source error: {err}")
    plan = plan_velo(layout, payload, origin, bbox)
    layout["velo_stations"] = plan["stations"]
    layout["velo_stats"] = plan["stats"]
    return plan


def export_velo_for_viewer(stations: list[dict[str, Any]]) -> dict[str, Any]:
    """Three.js coords: Blender (x, y) → (x, 0, -y)."""
    out = []
    for st in stations:
        out.append(
            {
                "id": st["id"],
                "name": st["name"],
                "address": st.get("address") or "",
                "x": st["x"],
                "y": 0.0,
                "z": -st["y"],
                "yaw": st["yaw"],
                "capacity": st["capacity"],
                "bikesAvailable": st["bikesAvailable"],
                "railLength": st.get("railLength"),
                "slotSpacing": st.get("slotSpacing", SLOT_SPACING_M),
            }
        )
    return {
        "attribution": ATTRIBUTION,
        "stations": out,
    }


def summarize(plan: dict[str, Any]) -> str:
    s = plan["stats"]
    return (
        f"{s['placed']} Velo stations ({s['bikes_total']} bikes / "
        f"{s['slots_total']} docks); nudged {s['nudged_to_kerb']}; dropped "
        f"{s['dropped_duplicate']} dup / {s['dropped_building']} building / "
        f"{s['dropped_carriageway']} carriageway / {s['dropped_rail']} tram-bed / "
        f"{s['dropped_outside']} outside"
    )
