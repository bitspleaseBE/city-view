"""Building heights: OSM first, then a footprint/type prior with a realistic spread.

Pure Python (no bpy), unit-testable. The old pipeline fell back to a single default
eaves height (12 m -> "4 floors") for every building without ``building:levels`` /
``height``; in the Harmonie tile that is 96 % of the footprints, so the whole district
extruded to one flat terrace. This module replaces that fallback.

Order of evidence (``height_source`` in the layout):

1. ``osm_height``   OSM ``height`` (metres, parsed leniently).
2. ``osm_levels``   OSM ``building:levels`` (minus ``building:min_level`` when mapped).
3. ``photo``        surveyed storey counts from ``assets/heights/photo_levels.json``
                    (only where OSM is silent; OSM always wins).
4. ``inferred``     a deterministic draw from a type / footprint distribution
                    (see ``infer_levels``), made coherent along party walls.

Distribution brief (from the project owner): minimum 2 levels per house (a few),
3 levels the majority (townhouses), small apartment buildings ~4, large blocks may
reach 10+, and never more than ``MAX_LEVELS`` (20) anywhere.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

FLOOR_H = 3.15  # metres per level (eaves = levels * FLOOR_H)
MAX_LEVELS = 20  # hard cap, applies to OSM-tagged values too
MAX_EAVES_M = MAX_LEVELS * FLOOR_H
MIN_HOUSE_LEVELS = 2

PHOTO_LEVELS_PATH = Path(__file__).resolve().parent.parent / "assets" / "heights" / "photo_levels.json"

# Buildings that are not "houses": sheds, garages, canopies. One level, never a facade tower.
OUTBUILDING_KINDS = frozenset(
    {
        "garage", "garages", "shed", "service", "roof", "carport", "hut", "cabin", "kiosk",
        "greenhouse", "parking", "allotment_house", "toilets", "bunker", "transformer_tower",
        "storage_tank", "container", "stable", "barn", "farm_auxiliary",
    }
)
INDUSTRIAL_KINDS = frozenset({"industrial", "warehouse", "manufacture", "hangar", "factory"})

# (levels, weight) tables. Weights need not sum to 1.
TOWNHOUSE = ((2, 0.10), (3, 0.60), (4, 0.26), (5, 0.04))
MID_FOOTPRINT = ((3, 0.15), (4, 0.45), (5, 0.30), (6, 0.10))  # 300 - 650 m2 non-apartments
LARGE_FOOTPRINT = ((4, 0.45), (5, 0.35), (6, 0.20))  # > 650 m2 non-apartments (merged terraces, blocks)
COMMERCIAL = ((3, 0.30), (4, 0.40), (5, 0.30))
HOTEL = ((4, 0.40), (5, 0.40), (6, 0.20))
INDUSTRIAL = ((2, 0.70), (3, 0.30))
APARTMENTS_SMALL = ((3, 0.12), (4, 0.50), (5, 0.25), (6, 0.10), (7, 0.03))  # < 300 m2, mean ~4.4
APARTMENTS_MID = ((4, 0.20), (5, 0.30), (6, 0.25), (7, 0.15), (8, 0.10))  # 300 - 500 m2
APARTMENTS_LARGE = ((6, 0.20), (7, 0.20), (8, 0.20), (9, 0.15), (10, 0.15), (12, 0.10))  # >= 500 m2

# Chance a freshly inferred townhouse copies a touching neighbour's level (party-wall runs).
NEIGHBOUR_COPY_P = 0.55
NEIGHBOUR_MAX_COPY_LEVELS = 6  # towers are never "copied" onto the houses beside them
_PARTY_WALL_M = 0.6


def _unit(osm_id: int, salt: str) -> float:
    """Deterministic, well-mixed value in [0, 1) (not Python's randomized ``hash``)."""
    digest = hashlib.blake2b(f"{osm_id}:{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def _pick(table: Iterable[tuple[int, float]], u: float) -> int:
    rows = list(table)
    total = sum(w for _, w in rows)
    acc = 0.0
    for levels, weight in rows:
        acc += weight / total
        if u < acc:
            return levels
    return rows[-1][0]


def ring_area(ring: list[list[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    acc = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        acc += x1 * y2 - x2 * y1
    return abs(acc) * 0.5


def _number(raw: str | None) -> float | None:
    if not raw:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(raw).split(";")[0])
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_levels(tags: dict[str, str]) -> int | None:
    """OSM ``building:levels`` as a visible level count in 1..MAX_LEVELS (None if unmapped)."""
    value = _number(tags.get("building:levels"))
    if value is None or value < 1:
        return None
    levels = int(round(value))
    min_level = _number(tags.get("building:min_level"))
    if min_level and min_level > 0:
        levels = max(1, levels - int(round(min_level)))  # floating part: only the storeys above the gap
    return max(1, min(MAX_LEVELS, levels))


def parse_height_m(tags: dict[str, str]) -> float | None:
    """OSM ``height`` (or ``building:height``) in metres, capped at MAX_LEVELS storeys."""
    for key in ("height", "building:height"):
        raw = tags.get(key)
        value = _number(raw)
        if value is None or value <= 0:
            continue
        if raw and re.search(r"\b(ft|feet|')", str(raw)):
            value *= 0.3048
        return max(3.0, min(MAX_EAVES_M, value))
    return None


_PHOTO_CACHE: dict[str, dict[str, Any]] | None = None


def photo_levels(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Surveyed storey counts (``{osm_id: {"levels": n, "source": "..."}}``), cached."""
    global _PHOTO_CACHE
    if path is not None:
        try:
            return json.loads(path.read_text()).get("buildings", {})
        except (OSError, ValueError):
            return {}
    if _PHOTO_CACHE is None:
        try:
            _PHOTO_CACHE = json.loads(PHOTO_LEVELS_PATH.read_text()).get("buildings", {})
        except (OSError, ValueError):
            _PHOTO_CACHE = {}
    return _PHOTO_CACHE


def infer_levels(osm_id: int, tags: dict[str, str], area: float) -> tuple[int, str]:
    """Footprint / type prior -> (levels, class). Deterministic per OSM id.

    The class (``townhouse`` / ``mid`` / ``large`` / ``apartments`` / ``commercial`` /
    ``outbuilding`` ...) tells the neighbour-coherence pass which buildings may copy a
    party-wall neighbour.
    """
    kind = (tags.get("building") or "yes").lower()
    u = _unit(osm_id, "levels")
    if kind in OUTBUILDING_KINDS:
        return 1, "outbuilding"
    if kind == "construction":
        return 2, "outbuilding"
    if kind in INDUSTRIAL_KINDS:
        return _pick(INDUSTRIAL, u), "industrial"
    if kind == "hotel":
        return _pick(HOTEL, u), "commercial"
    if kind in {"commercial", "retail", "office", "government", "public", "civic", "supermarket"}:
        return _pick(COMMERCIAL, u), "commercial"
    if kind == "apartments":
        if area < 300:
            return _pick(APARTMENTS_SMALL, u), "apartments"
        if area < 500:
            return _pick(APARTMENTS_MID, u), "apartments"
        return _pick(APARTMENTS_LARGE, u), "apartments"
    # yes / house / residential / terrace / detached / semidetached_house / ...
    has_address = bool(tags.get("addr:housenumber"))
    if not has_address and not tags.get("name"):
        # Unaddressed small footprints are rear annexes, sheds and extensions, not houses.
        if area < 60:
            return 1, "outbuilding"
        if area < 150:
            return 2, "outbuilding"
    if area < 300:
        return _pick(TOWNHOUSE, u), "townhouse"
    if area < 650:
        return _pick(MID_FOOTPRINT, u), "mid"
    return _pick(LARGE_FOOTPRINT, u), "large"


def eaves_for_levels(levels: int) -> float:
    return round(levels * FLOOR_H, 3)


class _VertexGrid:
    """Spatial hash of ring vertices for party-wall adjacency tests."""

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float, int]]] = {}

    @staticmethod
    def _cell(x: float, y: float) -> tuple[int, int]:
        return int(math.floor(x)), int(math.floor(y))

    def add(self, index: int, ring: list[list[float]]) -> None:
        for x, y in ring:
            self.cells.setdefault(self._cell(x, y), []).append((x, y, index))

    def neighbours(self, index: int, ring: list[list[float]]) -> set[int]:
        found: set[int] = set()
        for x, y in ring:
            cx, cy = self._cell(x, y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for ox, oy, other in self.cells.get((cx + dx, cy + dy), ()):
                        if other != index and math.hypot(ox - x, oy - y) <= _PARTY_WALL_M:
                            found.add(other)
        return found


def resolve_heights(buildings: list[dict[str, Any]], tags_by_index: list[dict[str, str]]) -> dict[str, int]:
    """Decide ``levels`` for every building; writes ``levels`` + ``height_source`` onto each.

    ``buildings`` need ``id`` and ``ring``; ``tags_by_index[i]`` are the merged OSM tags
    of ``buildings[i]``. Buildings already carrying a hard-coded type height (church,
    hospital, school, supermarket without OSM data) must set ``height_source`` to
    ``"type_default"`` beforehand and are left alone. Returns a source -> count summary.
    """
    photo = photo_levels()
    n = len(buildings)
    grid = _VertexGrid()
    for i, b in enumerate(buildings):
        grid.add(i, b["ring"])
    areas = [ring_area(b["ring"]) for b in buildings]
    classes: list[str] = [""] * n
    pending: list[int] = []

    for i, b in enumerate(buildings):
        if b.get("height_source") == "type_default":
            b["levels"] = int(b["floors"])
            continue
        tags = tags_by_index[i]
        osm_id = int(b["id"])
        h_m = parse_height_m(tags)
        lv = parse_levels(tags)
        if h_m is not None:
            b["height_source"] = "osm_height"
            b["levels"] = max(1, min(MAX_LEVELS, lv if lv else int(round(h_m / FLOOR_H))))
            b["height_m_osm"] = round(h_m, 2)
        elif lv is not None:
            b["height_source"] = "osm_levels"
            b["levels"] = lv
        elif str(osm_id) in photo:
            b["height_source"] = "photo"
            b["levels"] = max(1, min(MAX_LEVELS, int(photo[str(osm_id)]["levels"])))
        else:
            levels, cls = infer_levels(osm_id, tags, areas[i])
            b["height_source"] = "inferred"
            b["levels"] = levels
            classes[i] = cls
            pending.append(i)

    # Party-wall coherence: a terrace reads as runs of the same cornice line with the odd
    # step, not as independent dice rolls. Only house-like classes copy, only from low
    # neighbours, and deterministically (lowest-id already-decided neighbour).
    house_like = {"townhouse", "mid"}
    pending.sort(key=lambda i: int(buildings[i]["id"]))
    pending_set = set(pending)
    decided = {i for i in range(n) if i not in pending_set}
    for i in pending:
        if classes[i] in house_like:
            donors = sorted(
                (j for j in grid.neighbours(i, buildings[i]["ring"]) if j in decided),
                key=lambda j: int(buildings[j]["id"]),
            )
            donors = [
                j
                for j in donors
                if MIN_HOUSE_LEVELS <= buildings[j]["levels"] <= NEIGHBOUR_MAX_COPY_LEVELS
                and (classes[j] in house_like or buildings[j]["height_source"] != "inferred")
                and buildings[j].get("height_source") != "type_default"
            ]
            if donors and _unit(int(buildings[i]["id"]), "copy") < NEIGHBOUR_COPY_P:
                buildings[i]["levels"] = buildings[donors[0]]["levels"]
        decided.add(i)

    counts: dict[str, int] = {}
    for b in buildings:
        counts[b["height_source"]] = counts.get(b["height_source"], 0) + 1
    return counts


def distribution(levels: Iterable[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for lv in levels:
        out[lv] = out.get(lv, 0) + 1
    return dict(sorted(out.items()))
