"""De Lijn GTFS static feed — stop/route enrichment for Antwerp tiles."""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from cityview.geo import project

GTFS_URL = (
    "https://opendata-discovery-gtfs-static.api.production.belgianmobility.io"
    "/api/gtfs/feed/delijn/static"
)

# GTFS route_type → scene mode
ROUTE_TYPE_MODE = {
    "0": "tram",  # tram / light rail
    "1": "subway",  # metro / premetro
    "2": "rail",
    "3": "bus",
    "5": "bus",  # cable car rarely; treat as bus if present
    "11": "tram",  # trolleybus → surface transit
}

MATCH_M = 40.0
SHAPE_MARGIN_DEG = 0.01  # ~1 km


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _local_dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def _norm_line(ref: str, mode: str) -> str:
    ref = ref.strip()
    if not ref:
        return ""
    # Keep De Lijn short names as-is; prefix bus only when purely numeric ambiguity helps UI.
    if mode == "bus" and ref.isdigit():
        return f"bus {ref}"
    return ref


def _read_csv(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    raw = zf.read(name)
    text = raw.decode("utf-8-sig")
    return csv.DictReader(io.StringIO(text))


def _download_gtfs_zip() -> bytes:
    req = urllib.request.Request(
        GTFS_URL,
        headers={"User-Agent": "city-view/0.1 (Antwerp procedural city)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def build_gtfs_subset(
    zip_bytes: bytes,
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
) -> dict[str, Any]:
    """Parse De Lijn GTFS ZIP into a bbox-clipped JSON-serialisable subset."""
    south, west, north, east = bbox
    ms, mw = south - SHAPE_MARGIN_DEG, west - SHAPE_MARGIN_DEG
    mn, me = north + SHAPE_MARGIN_DEG, east + SHAPE_MARGIN_DEG

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        stops_in: list[dict[str, Any]] = []
        stop_ids: set[str] = set()
        for row in _read_csv(zf, "stops.txt"):
            try:
                lat = float(row["stop_lat"])
                lon = float(row["stop_lon"])
            except (KeyError, ValueError):
                continue
            if not (ms <= lat <= mn and mw <= lon <= me):
                continue
            sid = row["stop_id"]
            stop_ids.add(sid)
            x, y = project(lat, lon, origin[0], origin[1])
            stops_in.append(
                {
                    "stop_id": sid,
                    "name": (row.get("stop_name") or "").strip(),
                    "lat": lat,
                    "lon": lon,
                    "x": round(x, 3),
                    "y": round(y, 3),
                }
            )

        routes: dict[str, dict[str, str]] = {}
        if "routes.txt" in names:
            for row in _read_csv(zf, "routes.txt"):
                rid = row.get("route_id") or ""
                if not rid:
                    continue
                rtype = row.get("route_type") or "3"
                mode = ROUTE_TYPE_MODE.get(rtype, "bus")
                if mode == "rail":
                    continue
                short = (row.get("route_short_name") or row.get("route_long_name") or "").strip()
                routes[rid] = {"short_name": short, "mode": mode, "route_type": rtype}

        # trip_id → route_id, shape_id
        trip_route: dict[str, str] = {}
        trip_shape: dict[str, str] = {}
        if "trips.txt" in names:
            for row in _read_csv(zf, "trips.txt"):
                tid = row.get("trip_id") or ""
                rid = row.get("route_id") or ""
                if not tid or rid not in routes:
                    continue
                trip_route[tid] = rid
                sid = (row.get("shape_id") or "").strip()
                if sid:
                    trip_shape[tid] = sid

        stop_route_ids: dict[str, set[str]] = {sid: set() for sid in stop_ids}
        shape_ids_needed: set[str] = set()
        if "stop_times.txt" in names and stop_ids:
            for row in _read_csv(zf, "stop_times.txt"):
                sid = row.get("stop_id") or ""
                if sid not in stop_ids:
                    continue
                tid = row.get("trip_id") or ""
                rid = trip_route.get(tid)
                if not rid:
                    continue
                stop_route_ids[sid].add(rid)
                shape = trip_shape.get(tid)
                if shape:
                    shape_ids_needed.add(shape)

        shapes_raw: dict[str, list[tuple[int, float, float]]] = {}
        if "shapes.txt" in names and shape_ids_needed:
            for row in _read_csv(zf, "shapes.txt"):
                shid = row.get("shape_id") or ""
                if shid not in shape_ids_needed:
                    continue
                try:
                    lat = float(row["shape_pt_lat"])
                    lon = float(row["shape_pt_lon"])
                    seq = int(float(row.get("shape_pt_sequence") or 0))
                except (KeyError, ValueError):
                    continue
                if not (ms <= lat <= mn and mw <= lon <= me):
                    continue
                shapes_raw.setdefault(shid, []).append((seq, lat, lon))

        # If stop_times yielded no shapes, fall back to shape points in the core bbox (capped).
        if not shapes_raw and "shapes.txt" in names:
            for row in _read_csv(zf, "shapes.txt"):
                shid = row.get("shape_id") or ""
                try:
                    lat = float(row["shape_pt_lat"])
                    lon = float(row["shape_pt_lon"])
                    seq = int(float(row.get("shape_pt_sequence") or 0))
                except (KeyError, ValueError):
                    continue
                if not (south <= lat <= north and west <= lon <= east):
                    continue
                shapes_raw.setdefault(shid, []).append((seq, lat, lon))
                if len(shapes_raw) > 80:
                    break

        # Map shape → route via trips
        shape_routes: dict[str, set[str]] = {}
        for tid, shid in trip_shape.items():
            if shid not in shapes_raw:
                continue
            rid = trip_route.get(tid)
            if rid:
                shape_routes.setdefault(shid, set()).add(rid)

        shape_paths: list[dict[str, Any]] = []
        for shid, pts in shapes_raw.items():
            pts.sort(key=lambda t: t[0])
            xy: list[list[float]] = []
            for _seq, lat, lon in pts:
                x, y = project(lat, lon, origin[0], origin[1])
                if xy and abs(xy[-1][0] - x) < 0.5 and abs(xy[-1][1] - y) < 0.5:
                    continue
                xy.append([round(x, 3), round(y, 3)])
            if len(xy) < 2:
                continue
            rids = shape_routes.get(shid) or set()
            modes = {routes[r]["mode"] for r in rids if r in routes}
            mode = "tram" if "tram" in modes or "subway" in modes else "bus"
            if "subway" in modes and "tram" not in modes and "bus" not in modes:
                mode = "subway"
            lines: list[str] = []
            for rid in sorted(rids):
                info = routes.get(rid)
                if not info:
                    continue
                label = _norm_line(info["short_name"], info["mode"])
                if label and label not in lines:
                    lines.append(label)
            shape_paths.append(
                {
                    "id": f"gtfs_shape_{shid}",
                    "mode": mode,
                    "points": xy,
                    "lines": lines,
                    "source": "gtfs",
                }
            )

        stop_lines: dict[str, list[str]] = {}
        for sid, rids in stop_route_ids.items():
            labels: list[str] = []
            for rid in sorted(rids):
                info = routes.get(rid)
                if not info:
                    continue
                label = _norm_line(info["short_name"], info["mode"])
                if label and label not in labels:
                    labels.append(label)
            stop_lines[sid] = labels

    return {
        "bbox": list(bbox),
        "origin": list(origin),
        "stops": stops_in,
        "stop_lines": stop_lines,
        "shapes": shape_paths,
        "routes": routes,
    }


def fetch_gtfs_subset(
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    cache_path: Path,
    *,
    refresh: bool = False,
) -> dict[str, Any] | None:
    """Load cached GTFS subset or download and build one. Returns None on failure."""
    if cache_path.exists() and not refresh:
        try:
            return json.loads(cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    try:
        raw = _download_gtfs_zip()
        subset = build_gtfs_subset(raw, bbox, origin)
    except Exception as exc:  # noqa: BLE001
        print(f"De Lijn GTFS fetch failed ({exc}); continuing with OSM refs only")
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(subset))
    return subset


def _nearest_gtfs_stop(
    x: float,
    y: float,
    gtfs_stops: list[dict[str, Any]],
    max_m: float = MATCH_M,
) -> dict[str, Any] | None:
    best = None
    best_d = max_m
    for stop in gtfs_stops:
        d = _local_dist(x, y, float(stop["x"]), float(stop["y"]))
        if d <= best_d:
            best_d = d
            best = stop
    return best


def _merge_lines(existing: list[str] | None, extra: list[str] | None) -> list[str]:
    out: list[str] = []
    for ref in list(existing or []) + list(extra or []):
        if ref and ref not in out:
            out.append(ref)
    return out


def enrich_layout_transit(
    layout: dict[str, Any],
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    *,
    refresh: bool = False,
    gtfs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach De Lijn line numbers to OSM stops/lines; add bus paths from GTFS shapes.

    Mutates and returns ``layout``. Safe if GTFS is unavailable.
    """
    stops = layout.setdefault("transit_stops", [])
    lines = layout.setdefault("transit_lines", [])

    # Normalise OSM refs → lines field for viewer/Blender.
    for stop in stops:
        stop["lines"] = _merge_lines(stop.get("lines"), stop.get("refs"))
    for line in lines:
        line["lines"] = _merge_lines(line.get("lines"), line.get("refs"))

    subset = gtfs if gtfs is not None else fetch_gtfs_subset(bbox, origin, cache_path, refresh=refresh)
    if not subset:
        return layout

    gtfs_stops = subset.get("stops") or []
    stop_lines_map = subset.get("stop_lines") or {}
    matched = 0
    for stop in stops:
        hit = _nearest_gtfs_stop(float(stop["x"]), float(stop["y"]), gtfs_stops)
        if not hit:
            continue
        matched += 1
        stop["delijn_stop_id"] = hit["stop_id"]
        if hit.get("name"):
            stop["name"] = hit["name"]
        dl_lines = stop_lines_map.get(hit["stop_id"]) or []
        stop["lines"] = _merge_lines(stop.get("lines"), dl_lines)
        # Prefer De Lijn mode when OSM was generic bus and GTFS says tram.
        for label in dl_lines:
            if label.startswith("bus ") or "bus" in label.lower():
                continue
            # Numeric tram/premetro lines often match Harmonie tram stops.
            if stop.get("mode") == "bus" and not label.lower().startswith("bus"):
                # Leave mode; line labels still useful.
                pass

    # Attach line labels to OSM tram ways from nearby GTFS shape polylines.
    gtfs_shapes = subset.get("shapes") or []
    for line in lines:
        if line.get("source") == "gtfs":
            continue
        pts = line.get("points") or []
        if len(pts) < 2:
            continue
        mid = pts[len(pts) // 2]
        mx, my = float(mid[0]), float(mid[1])
        best_lines: list[str] = []
        best_d = 35.0
        for shape in gtfs_shapes:
            if shape.get("mode") not in {"tram", "subway", line.get("mode")}:
                if line.get("mode") in {"tram", "subway"} and shape.get("mode") == "bus":
                    continue
            spts = shape.get("points") or []
            if len(spts) < 2:
                continue
            dmin = min(_local_dist(mx, my, float(p[0]), float(p[1])) for p in spts[:: max(1, len(spts) // 12)])
            if dmin < best_d:
                best_d = dmin
                best_lines = list(shape.get("lines") or [])
        if best_lines:
            line["lines"] = _merge_lines(line.get("lines"), best_lines)

    # Add bus (and missing tram) motion paths from GTFS shapes.
    existing_ids = {str(line.get("id")) for line in lines}
    bus_added = 0
    for shape in gtfs_shapes:
        sid = str(shape.get("id"))
        if sid in existing_ids:
            continue
        mode = shape.get("mode") or "bus"
        # Prefer OSM track geometry for trams; only inject GTFS tram shapes if none nearby.
        if mode in {"tram", "subway"}:
            mid = (shape.get("points") or [None])[len(shape.get("points") or []) // 2]
            if mid is None:
                continue
            nearby_osm = any(
                ln.get("mode") in {"tram", "subway"}
                and ln.get("source") != "gtfs"
                and min(
                    _local_dist(float(mid[0]), float(mid[1]), float(p[0]), float(p[1]))
                    for p in (ln.get("points") or [[1e9, 1e9]])
                )
                < 40.0
                for ln in lines
            )
            if nearby_osm:
                continue
        lines.append(
            {
                "id": sid,
                "mode": mode,
                "points": shape["points"],
                "lines": list(shape.get("lines") or []),
                "refs": list(shape.get("lines") or []),
                "name": "",
                "source": "gtfs",
            }
        )
        if mode == "bus":
            bus_added += 1
        existing_ids.add(sid)

    layout["transit_stops"] = stops
    layout["transit_lines"] = lines
    layout["transit_meta"] = {
        "gtfs_stops": len(gtfs_stops),
        "matched_stops": matched,
        "bus_paths_added": bus_added,
        "gtfs_shapes": len(gtfs_shapes),
    }
    return layout


# Re-export haversine for tests
haversine_m = _haversine_m
