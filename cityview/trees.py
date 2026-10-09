"""Tree placement from real survey data, with a naturalistic fallback.

Pure stdlib on purpose (``blender/trees_blender.py`` imports this inside Blender's
Python; the tests import it without ``bpy``).

Data sources (merged, nearest-duplicate removed, in priority order)
-------------------------------------------------------------------
1. **Stad Antwerpen "Groeninventaris"** – the municipal green inventory, layer
   ``boom`` (one point per managed tree: Latin species, genus and trunk
   circumference). Public ArcGIS REST service, published by the city as open
   data (https://www.antwerpen.be/info/gratis-open-data-licentie, © Stad
   Antwerpen). Mapped by mobile-mapping survey, so positions are individual
   trees, not a procedural rhythm. ~1.3k trees inside the Harmonie tile.
2. **OpenStreetMap** ``natural=tree`` nodes and ``natural=tree_row`` ways
   (ODbL, © OpenStreetMap contributors). Smaller (~170 nodes here) but fills
   private/semi-public gardens the city does not manage.

Only when a park polygon holds *few* real trees for its size is a Poisson-disc
fill added (never a straight line); real parks keep exactly their surveyed
trees. Nothing is placed inside buildings, on carriageways or on a tram bed
(``cityview.railclear``).

Hard rule: no trunk stands on the drawn asphalt (or on its kerb). A surveyed tree whose
point lands in a carriageway - the survey is metre-accurate, OSM's road width nominal - is
snapped to the nearest legal pavement / verge / park spot (``cityview.roadclear``), or
dropped when there is none within a few metres. It is never left in a lane.
"""

from __future__ import annotations

import json
import math
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from cityview.geo import project
from cityview.paths import TREES_CACHE
from cityview.railclear import BED_HALF_SUBWAY, CLEAR_FURNITURE, CLEAR_TREE, RailIndex
from cityview.roadclear import TRUNK_MARGIN, RoadIndex, snap_off_carriageway

ANTWERP_TREE_LAYER = (
    "https://geodata.antwerpen.be/arcgissql/rest/services/"
    "P_Groeninventaris/Groeninventaris_extern/MapServer/5/query"
)
OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
ALLOWED_HOSTS = frozenset(
    {
        "geodata.antwerpen.be",
        "overpass.kumi.systems",
        "overpass.private.coffee",
        "overpass-api.de",
    }
)
USER_AGENT = "city-view/0.1 (Antwerp procedural city)"
ATTRIBUTION = (
    "Trees: (c) Stad Antwerpen Groeninventaris (open data licence); "
    "(c) OpenStreetMap contributors (ODbL)."
)

# Query box is padded so trees whose crown overhangs the tile edge are kept.
FETCH_PAD_DEG = 0.0008

CONIFER_GENERA = frozenset(
    {
        "Taxus", "Pinus", "Picea", "Abies", "Cedrus", "Thuja", "Cupressus", "Chamaecyparis",
        "Juniperus", "Sequoia", "Sequoiadendron", "Metasequoia", "Tsuga", "Pseudotsuga",
        "Cryptomeria", "Araucaria", "Sciadopitys", "Larix", "Taxodium", "Cupressocyparis",
        "Calocedrus", "Platycladus",
    }
)
# Typical mature height (m) of each genus as a paved street / square tree in Antwerp.
GENUS_MAX_HEIGHT = {
    "Platanus": 22.0, "Quercus": 20.0, "Fagus": 20.0, "Populus": 22.0, "Fraxinus": 17.0,
    "Tilia": 18.0, "Aesculus": 17.0, "Acer": 16.0, "Ulmus": 17.0, "Pterocarya": 16.0,
    "Robinia": 15.0, "Betula": 15.0, "Gleditsia": 14.0, "Alnus": 14.0, "Salix": 13.0,
    "Carpinus": 13.0, "Ginkgo": 14.0, "Liquidambar": 15.0, "Zelkova": 15.0,
    "Pyrus": 10.0, "Sorbus": 10.0, "Corylus": 9.0, "Prunus": 8.5, "Malus": 7.0,
    "Crataegus": 7.0, "Amelanchier": 6.0, "Magnolia": 8.0, "Cercis": 7.0,
}
DEFAULT_MAX_HEIGHT = 14.0
MAX_TREE_HEIGHT = 22.0  # 4-6 storey terraces are ~13-18 m; nothing should tower 2×
GIRTH_SCALE_CM = 110.0
# Narrow, upright habits (cultivar epithets) → thin crown.
COLUMNAR_MARKS = ("fastigiata", "columnaris", "pyramidalis", "fontaine", "erecta", "fastigiate")

# --- placement tuning -----------------------------------------------------
# A surveyed trunk only has to stay off the tram bed (+ kerb margin); its crown may
# overhang the track (trams are ~3.5 m tall, branches start above that). Invented
# fill trees keep the full canopy clearance.
CLEAR_REAL_TRUNK = max(CLEAR_FURNITURE, BED_HALF_SUBWAY + 0.7)
# Real trunks must clear the drawn asphalt + kerb by roadclear.TRUNK_MARGIN (no tolerance
# inside the lane any more); offenders are snapped onto the pavement or dropped.
DEDUPE_M = 1.8  # two survey points closer than this are the same tree
BUILDING_MARGIN_REAL = 0.3  # real trunks may stand against a façade, not in it
BUILDING_MARGIN_FILL = 3.2
ROAD_EDGE_FILL = 1.2  # fill trees keep this far outside the road surface
ROW_STEP_M = 8.0  # tree_row spacing when OSM maps only the line
# A park is "sparse" when it has fewer real trees than this fraction of target.
SPARSE_FRACTION = 0.5
PARK_M2_PER_TREE = 1100.0
PARK_MIN_AREA = 350.0
PARK_MAX_FILL = 36
FILL_MIN_SPACING = 6.5
BUSH_M2_PER_BUSH = 420.0
BUSH_MAX_PER_PARK = 40
BUSH_MIN_SPACING = 3.6

DRIVEABLE = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service", "pedestrian",
    }
)


# ---------------------------------------------------------------- fetching


def _http_json(url: str, data: bytes | None = None, timeout: float = 60.0) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to fetch tree data from {parsed.hostname!r}")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep  (https + host allowlist enforced above)
        return json.loads(resp.read().decode())


def fetch_antwerp_trees(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Page the city's ``boom`` layer for ``(south, west, north, east)``."""
    south, west, north, east = bbox
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode(
            {
                "f": "geojson",
                "where": "1=1",
                "geometry": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "outSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "OBJECTID,LATBOOMSOORT,GENUS,STAMOMTREK,ANTW_ID",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": 1000,
            }
        )
        doc = _http_json(f"{ANTWERP_TREE_LAYER}?{params}")
        feats = doc.get("features") or []
        for feat in feats:
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if geom.get("type") != "Point" or len(coords) < 2:
                continue
            props = feat.get("properties") or {}
            girth = props.get("STAMOMTREK")
            out.append(
                {
                    "id": props.get("OBJECTID"),
                    "lat": round(float(coords[1]), 7),
                    "lon": round(float(coords[0]), 7),
                    "species": props.get("LATBOOMSOORT") or "",
                    "genus": props.get("GENUS") or "",
                    "girth_cm": float(girth) if girth not in (None, "") else None,
                }
            )
        if not feats or not doc.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


def _overpass_trees_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    return (
        "[out:json][timeout:60];("
        f'node["natural"="tree"]({box});'
        f'way["natural"="tree_row"]({box});'
        ");out body;>;out skel qt;"
    )


def fetch_osm_trees(
    bbox: tuple[float, float, float, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """OSM ``natural=tree`` nodes and ``natural=tree_row`` lines (lat/lon)."""
    body = urllib.parse.urlencode({"data": _overpass_trees_query(bbox)}).encode()
    last: Exception | None = None
    doc: dict[str, Any] | None = None
    for _ in range(2):
        for url in OVERPASS_URLS:
            try:
                doc = _http_json(url, data=body, timeout=75.0)
                break
            except Exception as exc:  # noqa: BLE001 - mirror failover
                last = exc
        if doc is not None:
            break
        time.sleep(3.0)
    if doc is None:
        raise RuntimeError(f"Overpass tree fetch failed: {last}") from last
    nodes = {
        int(el["id"]): el for el in doc.get("elements") or [] if el.get("type") == "node"
    }
    trees: list[dict[str, Any]] = []
    for el in nodes.values():
        tags = el.get("tags") or {}
        if tags.get("natural") != "tree":
            continue
        trees.append(
            {
                "id": int(el["id"]),
                "lat": float(el["lat"]),
                "lon": float(el["lon"]),
                "species": tags.get("species") or tags.get("taxon") or "",
                "genus": tags.get("genus") or "",
                "leaf_type": tags.get("leaf_type") or "",
                "height": tags.get("height") or "",
                "crown": tags.get("diameter_crown") or "",
            }
        )
    rows: list[dict[str, Any]] = []
    for el in doc.get("elements") or []:
        if el.get("type") != "way" or (el.get("tags") or {}).get("natural") != "tree_row":
            continue
        pts = [
            [float(nodes[int(n)]["lat"]), float(nodes[int(n)]["lon"])]
            for n in el.get("nodes") or []
            if int(n) in nodes
        ]
        if len(pts) >= 2:
            rows.append(
                {
                    "id": int(el["id"]),
                    "points": pts,
                    "leaf_type": (el.get("tags") or {}).get("leaf_type") or "",
                }
            )
    return trees, rows


def _checked_cache_path(path: Path) -> Path:
    """Tree caches live under assets/trees/*.json — nothing else is read or written."""
    resolved = Path(path).resolve()
    root = TREES_CACHE.resolve()
    if resolved.suffix != ".json" or root not in resolved.parents:
        raise ValueError(f"tree cache must be a .json file under {root}")
    return resolved


def fetch_tree_sources(
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Load (or download once and commit) the raw tree payload for a tile."""
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
        "osm_trees": [],
        "osm_tree_rows": [],
        "errors": [],
    }
    try:
        payload["antwerp"] = fetch_antwerp_trees(padded)
    except Exception as exc:  # noqa: BLE001
        payload["errors"].append(f"antwerp: {exc}")
    try:
        payload["osm_trees"], payload["osm_tree_rows"] = fetch_osm_trees(padded)
    except Exception as exc:  # noqa: BLE001
        payload["errors"].append(f"osm: {exc}")
    if not payload["errors"] and (payload["antwerp"] or payload["osm_trees"]):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Path confined to assets/trees/*.json by _checked_cache_path above.
        cache_path.write_text(json.dumps(payload, separators=(",", ":")))  # nosemgrep
    return payload


# ---------------------------------------------------------------- geometry


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def ring_area(ring: list[list[float]]) -> float:
    acc = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        acc += x1 * y2 - x2 * y1
    return abs(acc) * 0.5


class _PointGrid:
    """Spatial hash for 'is anything within r metres' queries."""

    def __init__(self, cell: float = 8.0):
        self.cell = cell
        self._cells: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def add(self, x: float, y: float) -> None:
        key = (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))
        self._cells.setdefault(key, []).append((x, y))

    def near(self, x: float, y: float, r: float) -> bool:
        cx, cy = int(math.floor(x / self.cell)), int(math.floor(y / self.cell))
        reach = int(math.ceil(r / self.cell))
        r2 = r * r
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for px, py in self._cells.get((gx, gy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r2:
                        return True
        return False


class _Obstacles:
    """Buildings, road surfaces and tram beds a tree must stay clear of."""

    CELL = 30.0

    def __init__(self, layout: dict[str, Any]):
        self.buildings: list[tuple[list[list[float]], tuple[float, float, float, float]]] = []
        self._bgrid: dict[tuple[int, int], list[int]] = {}
        for b in layout.get("buildings") or []:
            ring = b.get("ring") or []
            if len(ring) < 3:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            idx = len(self.buildings)
            box = (min(xs), min(ys), max(xs), max(ys))
            self.buildings.append((ring, box))
            for cx in range(int(math.floor(box[0] / self.CELL)), int(math.floor(box[2] / self.CELL)) + 1):
                for cy in range(int(math.floor(box[1] / self.CELL)), int(math.floor(box[3] / self.CELL)) + 1):
                    self._bgrid.setdefault((cx, cy), []).append(idx)
        # (ax, ay, bx, by, half_width, driveable)
        self.segments: list[tuple[float, float, float, float, float, bool]] = []
        self._sgrid: dict[tuple[int, int], list[int]] = {}
        for road in layout.get("roads") or []:
            pts = road.get("points") or []
            half = float(road.get("width") or 6.0) * 0.5
            drive = (road.get("kind") or "residential") in DRIVEABLE
            for i in range(len(pts) - 1):
                ax, ay, bx, by = pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]
                idx = len(self.segments)
                self.segments.append((ax, ay, bx, by, half, drive))
                for cx in range(int(math.floor(min(ax, bx) / self.CELL)), int(math.floor(max(ax, bx) / self.CELL)) + 1):
                    for cy in range(int(math.floor(min(ay, by) / self.CELL)), int(math.floor(max(ay, by) / self.CELL)) + 1):
                        self._sgrid.setdefault((cx, cy), []).append(idx)
        self.rails = RailIndex.from_layout(layout)
        self.roads = RoadIndex.from_layout(layout)

    def in_building(self, x: float, y: float, margin: float = 0.0) -> bool:
        cx, cy = int(math.floor(x / self.CELL)), int(math.floor(y / self.CELL))
        seen: set[int] = set()
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for idx in self._bgrid.get((gx, gy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    ring, (x0, y0, x1, y1) = self.buildings[idx]
                    if x < x0 - margin or x > x1 + margin or y < y0 - margin or y > y1 + margin:
                        continue
                    if _point_in_ring(x, y, ring):
                        return True
                    if margin > 0.0:
                        n = len(ring)
                        for i in range(n):
                            ax, ay = ring[i]
                            bx, by = ring[(i + 1) % n]
                            if _seg_dist(x, y, ax, ay, bx, by) < margin:
                                return True
        return False

    def road_clearance(self, x: float, y: float, driveable_only: bool = False) -> float:
        """Distance from ``(x, y)`` to the nearest road *surface* edge (negative = on it)."""
        cx, cy = int(math.floor(x / self.CELL)), int(math.floor(y / self.CELL))
        best = math.inf
        seen: set[int] = set()
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for idx in self._sgrid.get((gx, gy), ()):
                    if idx in seen:
                        continue
                    seen.add(idx)
                    ax, ay, bx, by, half, drive = self.segments[idx]
                    if driveable_only and not drive:
                        continue
                    d = _seg_dist(x, y, ax, ay, bx, by) - half
                    if d < best:
                        best = d
        return best

    def on_rails(self, x: float, y: float, clearance: float = CLEAR_TREE) -> bool:
        return self.rails.within(x, y, clearance)


# ---------------------------------------------------------------- tree traits


def _stable_unit(*parts: Any) -> float:
    """Deterministic 0..1 from arbitrary ids (not Python's randomised hash)."""
    h = 2166136261
    for ch in "|".join(str(p) for p in parts):
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h / 0xFFFFFFFF


def _parse_metres(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).lower().replace("m", "").replace(",", ".").strip())
    except ValueError:
        return None


def tree_traits(rec: dict[str, Any], x: float, y: float) -> dict[str, Any]:
    """Height / crown / shape from species, trunk girth and tags."""
    species = (rec.get("species") or "").strip()
    genus = (rec.get("genus") or (species.split(" ")[0] if species else "")).strip().capitalize()
    low = species.lower()
    leaf = (rec.get("leaf_type") or "").lower()
    conifer = genus in CONIFER_GENERA or leaf == "needleleaved"
    columnar = any(m in low for m in COLUMNAR_MARKS)
    tone = _stable_unit(round(x, 1), round(y, 1))

    h_max = GENUS_MAX_HEIGHT.get(genus, DEFAULT_MAX_HEIGHT)
    height = _parse_metres(rec.get("height"))
    girth = rec.get("girth_cm")
    if height is None:
        if girth:
            # Circumference at breast height → urban height, saturating towards the
            # genus' street-tree maximum (growth slows long before girth does).
            height = 2.5 + (h_max - 2.5) * (1.0 - math.exp(-float(girth) / GIRTH_SCALE_CM))
        else:
            height = 6.5 + tone * 4.5
        height *= 0.93 + 0.14 * tone
    height = max(3.5, min(h_max, MAX_TREE_HEIGHT, height))
    if conifer:
        height = min(height, 16.0)

    crown_d = _parse_metres(rec.get("crown"))
    if crown_d:
        radius = crown_d * 0.5
    else:
        # Open-grown urban broadleaves: crown spread ≈ 0.55–0.7 × height.
        radius = 0.3 * height + 0.3 + (tone - 0.5) * 0.7
    if columnar:
        radius *= 0.5
    elif conifer:
        radius *= 0.75
    radius = max(1.0, min(7.0, radius))
    shape = "conifer" if conifer else ("columnar" if columnar else "broadleaf")
    return {
        "genus": genus,
        "species": species,
        "height": round(fit_height_to_crown(height, radius, shape), 2),
        "radius": round(radius, 2),
        "shape": shape,
        "tone": round(tone, 3),
    }


def fit_height_to_crown(height: float, radius: float, shape: str) -> float:
    """Cap height so a crown never sits on a bare pole (pruned / narrow crowns)."""
    ratio = {"broadleaf": 3.4, "columnar": 7.0, "conifer": 5.0}.get(shape, 3.4)
    return max(3.5, min(height, 2.4 + ratio * radius))


# ---------------------------------------------------------------- merge + fill


def _real_candidates(
    payload: dict[str, Any], origin: tuple[float, float]
) -> list[dict[str, Any]]:
    """All surveyed trees in local metres, in dedupe-priority order."""
    out: list[dict[str, Any]] = []
    for rec in payload.get("antwerp") or []:
        x, y = project(float(rec["lat"]), float(rec["lon"]), origin[0], origin[1])
        out.append({"x": x, "y": y, "source": "antwerp", "rec": rec})
    for rec in payload.get("osm_trees") or []:
        x, y = project(float(rec["lat"]), float(rec["lon"]), origin[0], origin[1])
        out.append({"x": x, "y": y, "source": "osm", "rec": rec})
    for row in payload.get("osm_tree_rows") or []:
        pts = [project(p[0], p[1], origin[0], origin[1]) for p in row.get("points") or []]
        rec = {"leaf_type": row.get("leaf_type") or ""}
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            seg = math.hypot(bx - ax, by - ay)
            n = max(1, int(round(seg / ROW_STEP_M)))
            for k in range(n + 1 if i == len(pts) - 2 else n):
                t = k / n
                out.append(
                    {
                        "x": ax + (bx - ax) * t,
                        "y": ay + (by - ay) * t,
                        "source": "osm_row",
                        "rec": rec,
                    }
                )
    return out


def _bounds(layout: dict[str, Any], bbox: tuple[float, float, float, float] | None, origin) -> tuple[float, float, float, float]:
    if bbox:
        x0, y0 = project(bbox[0], bbox[1], origin[0], origin[1])
        x1, y1 = project(bbox[2], bbox[3], origin[0], origin[1])
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return (-math.inf, -math.inf, math.inf, math.inf)


def poisson_fill(
    ring: list[list[float]],
    rng: random.Random,
    count: int,
    min_spacing: float,
    edge_inset: float,
    accept,
    taken: _PointGrid,
    attempts_per: int = 60,
) -> list[tuple[float, float]]:
    """Dart-throwing Poisson-disc sampling inside ``ring`` (blue-noise, never a row)."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    out: list[tuple[float, float]] = []
    mine = _PointGrid(cell=max(2.0, min_spacing))
    for _ in range(count * attempts_per):
        if len(out) >= count:
            break
        x = rng.uniform(x0, x1)
        y = rng.uniform(y0, y1)
        if not _point_in_ring(x, y, ring):
            continue
        if edge_inset > 0.0 and any(
            _seg_dist(x, y, ring[i][0], ring[i][1], ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1])
            < edge_inset
            for i in range(len(ring))
        ):
            continue
        if mine.near(x, y, min_spacing) or taken.near(x, y, min_spacing * 0.85):
            continue
        if not accept(x, y):
            continue
        mine.add(x, y)
        out.append((x, y))
    return out


def plan_trees(
    layout: dict[str, Any],
    payload: dict[str, Any] | None,
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Return ``{"trees": [...], "bushes": [...], "stats": {...}}`` in local metres."""
    payload = payload or {}
    obstacles = _Obstacles(layout)
    xmin, ymin, xmax, ymax = _bounds(layout, bbox, origin)
    stats: dict[str, int] = {
        "antwerp": 0,
        "osm": 0,
        "osm_row": 0,
        "fill": 0,
        "dropped_duplicate": 0,
        "dropped_building": 0,
        "dropped_road": 0,
        "relocated_road": 0,
        "dropped_rail": 0,
        "dropped_outside": 0,
        "bushes": 0,
        "parks_filled": 0,
        "parks_sparse_total": 0,
    }
    trees: list[dict[str, Any]] = []
    grid = _PointGrid(cell=4.0)
    for cand in _real_candidates(payload, origin):
        x, y, src = cand["x"], cand["y"], cand["source"]
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            stats["dropped_outside"] += 1
            continue
        if grid.near(x, y, DEDUPE_M):
            stats["dropped_duplicate"] += 1
            continue
        if obstacles.on_rails(x, y, CLEAR_REAL_TRUNK):
            stats["dropped_rail"] += 1
            continue
        if obstacles.in_building(x, y, BUILDING_MARGIN_REAL):
            stats["dropped_building"] += 1
            continue
        # HARD RULE: a trunk never stands on the carriageway (or its kerb). Snap it onto
        # the nearest legal ground instead of leaving it in the lane; drop if none close by.
        if obstacles.roads.on_carriageway(x, y, TRUNK_MARGIN):
            spot = snap_off_carriageway(
                x,
                y,
                obstacles.roads,
                lambda px, py: (
                    not obstacles.on_rails(px, py, CLEAR_REAL_TRUNK)
                    and not obstacles.in_building(px, py, BUILDING_MARGIN_REAL)
                    and not grid.near(px, py, DEDUPE_M)
                ),
            )
            if spot is None:
                stats["dropped_road"] += 1
                continue
            x, y = spot
            stats["relocated_road"] += 1
        grid.add(x, y)
        tree = {"x": round(x, 2), "y": round(y, 2), "source": src}
        tree.update(tree_traits(cand["rec"], x, y))
        # Keep the crown clear of the tram bed even though it may overhang the track.
        rail_d = obstacles.rails.distance(x, y, limit=8.0)
        if rail_d < tree["radius"] + BED_HALF_SUBWAY:
            tree["radius"] = round(max(0.9, rail_d - BED_HALF_SUBWAY - 0.1), 2)
            # Tram-side trees are pruned as a whole, not just stripped on one side.
            tree["height"] = round(
                fit_height_to_crown(tree["height"], tree["radius"], tree["shape"]), 2
            )
        trees.append(tree)
        stats[src] += 1

    # --- fallback: Poisson fill only inside parks the survey barely covers ---
    bushes: list[dict[str, Any]] = []
    bush_grid = _PointGrid(cell=4.0)

    def clear_of_world(x: float, y: float, building_margin: float) -> bool:
        if obstacles.on_rails(x, y) or obstacles.in_building(x, y, building_margin):
            return False
        return (
            obstacles.road_clearance(x, y) >= ROAD_EDGE_FILL
            and not obstacles.roads.on_carriageway(x, y, TRUNK_MARGIN)
        )

    for park in layout.get("parks") or []:
        ring = park.get("ring") or []
        if len(ring) < 3:
            continue
        area = ring_area(ring)
        if area < PARK_MIN_AREA:
            continue
        pid = int(park.get("id") or 1)
        rng = random.Random(pid * 7919 + 13)
        real = sum(1 for t in trees if _point_in_ring(t["x"], t["y"], ring))
        target = max(3, int(area / PARK_M2_PER_TREE))
        # Sparse = survey holds < half the density a lightly wooded park would have.
        if real < target * SPARSE_FRACTION:
            stats["parks_sparse_total"] += 1
            need = min(PARK_MAX_FILL, target - real)
            if need > 0:
                spots = poisson_fill(
                    ring,
                    rng,
                    need,
                    FILL_MIN_SPACING + min(2.5, math.sqrt(area) / 60.0),
                    2.2,
                    lambda x, y: clear_of_world(x, y, BUILDING_MARGIN_FILL),
                    grid,
                )
                for x, y in spots:
                    rec = {"height": "", "girth_cm": None}
                    tone = _stable_unit(pid, round(x, 1), round(y, 1))
                    rec["girth_cm"] = 60.0 + tone * 110.0
                    tree = {"x": round(x, 2), "y": round(y, 2), "source": "fill"}
                    tree.update(tree_traits(rec, x, y))
                    trees.append(tree)
                    grid.add(x, y)
                    stats["fill"] += 1
                if spots:
                    stats["parks_filled"] += 1
        # Bushes: blue-noise too (the old LCG scatter lined up on a lattice).
        n_bush = max(3, min(BUSH_MAX_PER_PARK, int(area / BUSH_M2_PER_BUSH)))
        brng = random.Random(pid * 104729 + 7)
        for x, y in poisson_fill(
            ring,
            brng,
            n_bush,
            BUSH_MIN_SPACING,
            1.2,
            lambda x, y: clear_of_world(x, y, 1.6) and not grid.near(x, y, 2.2),
            bush_grid,
        ):
            u = _stable_unit("b", pid, round(x, 1), round(y, 1))
            bushes.append(
                {
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "w": round(1.2 + u * 0.9, 2),
                    "h": round(0.9 + (1.0 - u) * 0.6, 2),
                    "tone": round(u, 3),
                }
            )
            bush_grid.add(x, y)
            stats["bushes"] += 1

    return {"trees": trees, "bushes": bushes, "stats": stats}


def attach_trees(
    layout: dict[str, Any],
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    cache_path: Path,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch/cached sources, plan placement and store results on ``layout``."""
    try:
        payload = fetch_tree_sources(bbox, cache_path, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - offline builds still get park fill
        print(f"WARNING: tree data unavailable ({exc}); using park fill only")
        payload = {}
    for err in payload.get("errors") or []:
        print(f"WARNING: tree source error: {err}")
    plan = plan_trees(layout, payload, origin, bbox)
    layout["trees"] = plan["trees"]
    layout["bushes"] = plan["bushes"]
    layout["tree_stats"] = plan["stats"]
    return plan


def summarize(stats: dict[str, int]) -> str:
    real = stats.get("antwerp", 0) + stats.get("osm", 0) + stats.get("osm_row", 0)
    return (
        f"{real + stats.get('fill', 0)} trees "
        f"({stats.get('antwerp', 0)} Stad Antwerpen inventory, {stats.get('osm', 0)} OSM nodes, "
        f"{stats.get('osm_row', 0)} OSM tree_row samples, {stats.get('fill', 0)} fallback fill in "
        f"{stats.get('parks_filled', 0)} sparse parks), {stats.get('bushes', 0)} bushes; dropped "
        f"{stats.get('dropped_duplicate', 0)} dup / {stats.get('dropped_building', 0)} building / "
        f"{stats.get('dropped_road', 0)} road / {stats.get('dropped_rail', 0)} tram-bed; "
        f"{stats.get('relocated_road', 0)} snapped off the carriageway onto the pavement"
    )


def iter_points(items: Iterable[dict[str, Any]]) -> list[tuple[float, float]]:
    return [(float(i["x"]), float(i["y"])) for i in items]
