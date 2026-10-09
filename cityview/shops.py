"""Shopfronts for the browser viewer from OpenStreetMap shop / amenity nodes.

Each ``shop=*`` (and street-facing amenity: café, bar, bank, pharmacy, ...) node is
snapped onto the street façade of the building it sits in (or the nearest one), so
the viewer can hang a named fascia + blade sign there and light it while the place
is open. ``opening_hours`` is reduced to a weekly table (Sunday first, like JS
``Date.getDay``); places without (parsable) hours get a typical schedule for their
category. Pure stdlib, Blender-free.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from cityview.geo import project

# OSM tag value → viewer category (colour + icon + default hours).
AMENITY_CATS = {
    "restaurant": "horeca",
    "cafe": "horeca",
    "bar": "horeca",
    "pub": "horeca",
    "fast_food": "horeca",
    "ice_cream": "horeca",
    "biergarten": "horeca",
    "bank": "service",
    "pharmacy": "pharmacy",
    "dentist": "care",
    "doctors": "care",
    "veterinary": "care",
    "post_office": "service",
    "bureau_de_change": "service",
    "money_transfer": "service",
}
FOOD_SHOPS = frozenset(
    {
        "bakery", "butcher", "greengrocer", "deli", "convenience", "supermarket", "cheese",
        "chocolate", "confectionery", "pastry", "seafood", "alcohol", "beverages", "wine",
        "coffee", "tea", "spices", "frozen_food", "health_food", "farm",
    }
)
SERVICE_SHOPS = frozenset(
    {
        "hairdresser", "beauty", "massage", "tattoo", "laundry", "dry_cleaning", "copyshop",
        "optician", "travel_agency", "funeral_directors", "estate_agent", "mobile_phone",
        "computer", "electronics", "repair", "tailor", "photo", "pawnbroker",
    }
)
SKIP_SHOPS = frozenset({"vacant", "no", "yes"})

DEFAULT_HOURS: dict[str, list[list[tuple[float, float]]]] = {
    # Sunday .. Saturday
    "food": [[(8.0, 13.0)]] + [[(7.5, 19.0)]] * 6,
    "horeca": [[(11.0, 23.0)]] + [[(11.0, 23.0)]] * 4 + [[(11.0, 25.0)]] * 2,
    "retail": [[]] + [[(10.0, 18.0)]] * 6,
    "service": [[]] + [[(9.0, 18.0)]] * 5 + [[(9.0, 16.0)]],
    "pharmacy": [[]] + [[(8.5, 18.5)]] * 5 + [[(9.0, 12.5)]],
    "care": [[]] + [[(8.0, 18.0)]] * 5 + [[]],
}

FACADE_SEARCH_M = 14.0  # a shop node farther than this from any façade is dropped
MIN_SPACING_M = 3.2  # two signs on one façade keep this far apart
SIGN_MAX_W = 6.5
SIGN_MIN_W = 2.4


def category_for(tags: dict[str, str]) -> tuple[str, str] | None:
    """(kind, category) for a tag dict, or None when it is not a shopfront."""
    shop = (tags.get("shop") or "").strip()
    if shop and shop not in SKIP_SHOPS:
        if shop in FOOD_SHOPS:
            return shop, "food"
        if shop in SERVICE_SHOPS:
            return shop, "service"
        return shop, "retail"
    amenity = (tags.get("amenity") or "").strip()
    if amenity in AMENITY_CATS:
        return amenity, AMENITY_CATS[amenity]
    return None


# ---------------------------------------------------------------- opening_hours

_DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\+?")
_DAY_TOKEN = re.compile(r"^(Mo|Tu|We|Th|Fr|Sa|Su|PH)(?:\s*-\s*(Mo|Tu|We|Th|Fr|Sa|Su))?$")


def _expand_days(spec: str) -> list[int] | None:
    days: list[int] = []
    for part in re.split(r"[,\s]+(?=(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)\b)|,", spec):
        part = part.strip()
        if not part:
            continue
        m = _DAY_TOKEN.match(part)
        if not m:
            return None
        if m.group(1) == "PH":
            continue  # public holidays: ignored (the game has none)
        a = _DAYS.index(m.group(1))
        b = _DAYS.index(m.group(2)) if m.group(2) else a
        # OSM weeks run Mo..Su; a range like Fr-Mo wraps.
        i = a
        while True:
            days.append(i)
            if i == b:
                break
            i = (i + 1) % 7
    return days


def _split_rules(raw: str) -> list[str]:
    """Split on ';' and on ', <Day>' (a common shorthand for a new rule)."""
    out: list[str] = []
    for chunk in raw.split(";"):
        out.extend(re.split(r"(?<=\d),\s*(?=(?:Mo|Tu|We|Th|Fr|Sa|Su)\b)", chunk))
    return [c.strip() for c in out if c.strip()]


def parse_opening_hours(raw: str | None) -> list[list[tuple[float, float]]] | None:
    """Weekly table (Sunday first) of open intervals in hours, close may exceed 24.

    Supports the common subset: ``Mo-Fr 09:00-18:00``, day lists, ``off``,
    ``24/7``, several time ranges per rule, rules without days (= every day).
    Later rules override earlier ones for the days they name. Returns None when
    the value uses syntax outside that subset.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw == "24/7":
        return [[(0.0, 24.0)] for _ in range(7)]
    week: list[list[tuple[float, float]]] = [[] for _ in range(7)]
    any_rule = False
    for rule in _split_rules(raw):
        m = re.match(r"^([A-Za-z,\-\s]*?)\s*((?:\d|off|closed).*)$", rule)
        if not m:
            return None
        day_spec, body = m.group(1).strip(), m.group(2).strip()
        days = _expand_days(day_spec) if day_spec else list(range(7))
        if days is None:
            if day_spec.startswith("PH"):
                continue
            return None
        if not days:
            continue  # PH-only rule
        if body in ("off", "closed"):
            for d in days:
                week[d] = []
            any_rule = True
            continue
        spans = []
        for t in _TIME.finditer(body):
            o = int(t.group(1)) + int(t.group(2)) / 60.0
            c = int(t.group(3)) + int(t.group(4)) / 60.0
            if c <= o:
                c += 24.0  # past midnight
            spans.append((round(o, 3), round(c, 3)))
        if not spans:
            return None
        for d in days:
            week[d] = list(spans)
        any_rule = True
    return week if any_rule else None


# ---------------------------------------------------------------- façade snap


def _seg_project(px: float, py: float, ax: float, ay: float, bx: float, by: float):
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    if ll < 1e-9:
        return 0.0, math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
    return t, math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _signed_area(ring: list[list[float]]) -> float:
    return 0.5 * sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _edges(bldg: dict[str, Any]) -> Iterable[tuple[int, int, tuple[float, float], bool]]:
    """(i0, i1, outward normal, street-facing) for every edge of the footprint."""
    ring = bldg["ring"]
    street = {}
    for e in bldg.get("street_edges") or []:
        street[(int(e["i0"]), int(e["i1"]))] = tuple(e.get("outward") or (0.0, 0.0))
    ccw = _signed_area(ring) > 0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        if (i, j) in street:
            yield i, j, street[(i, j)], True
            continue
        dx, dy = ring[j][0] - ring[i][0], ring[j][1] - ring[i][1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = (dy / ln, -dx / ln) if ccw else (-dy / ln, dx / ln)
        yield i, j, (nx, ny), False


class _BuildingIndex:
    def __init__(self, buildings: list[dict[str, Any]], cell: float = 25.0) -> None:
        self.cell = cell
        self.grid: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for b in buildings:
            ring = b.get("ring") or []
            if len(ring) < 3:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            for gx in range(int(math.floor(min(xs) / cell)), int(math.floor(max(xs) / cell)) + 1):
                for gy in range(int(math.floor(min(ys) / cell)), int(math.floor(max(ys) / cell)) + 1):
                    self.grid.setdefault((gx, gy), []).append(b)

    def near(self, x: float, y: float, r: float) -> list[dict[str, Any]]:
        seen: dict[int, dict[str, Any]] = {}
        c = self.cell
        for gx in range(int(math.floor((x - r) / c)), int(math.floor((x + r) / c)) + 1):
            for gy in range(int(math.floor((y - r) / c)), int(math.floor((y + r) / c)) + 1):
                for b in self.grid.get((gx, gy), ()):
                    seen[id(b)] = b
        return list(seen.values())


def snap_to_facade(
    x: float, y: float, index: _BuildingIndex
) -> dict[str, Any] | None:
    """Nearest façade point (street-facing edges preferred) for a shop node."""
    best = None
    for b in index.near(x, y, FACADE_SEARCH_M):
        ring = b["ring"]
        inside = _point_in_ring(x, y, ring)
        for i0, i1, (nx, ny), street in _edges(b):
            a, c = ring[i0], ring[i1]
            length = math.hypot(c[0] - a[0], c[1] - a[1])
            if length < SIGN_MIN_W + 0.6:
                continue
            t, d = _seg_project(x, y, a[0], a[1], c[0], c[1])
            if d > FACADE_SEARCH_M:
                continue
            # A node outside a building must sit in front of the face it snaps to.
            if not inside and (x - a[0]) * nx + (y - a[1]) * ny < -0.5:
                continue
            score = d - (4.0 if street else 0.0) - (2.0 if inside else 0.0)
            if best is None or score < best[0]:
                best = (score, b, i0, i1, t, length, (nx, ny), street)
    if best is None:
        return None
    _, b, i0, i1, t, length, (nx, ny), street = best
    ring = b["ring"]
    a, c = ring[i0], ring[i1]
    w = max(SIGN_MIN_W, min(SIGN_MAX_W, length * 0.7))
    margin = (w * 0.5 + 0.3) / length
    t = min(max(t, margin), 1.0 - margin) if margin < 0.5 else 0.5
    return {
        "x": a[0] + (c[0] - a[0]) * t,
        "y": a[1] + (c[1] - a[1]) * t,
        "nx": nx,
        "ny": ny,
        "w": w,
        "edge": (b.get("id"), i0),
        "t": t,
        "length": length,
        "street": street,
        "floors": int(b.get("floors") or 0),
    }


def plan_shops(
    osm: dict[str, Any], layout: dict[str, Any], origin: tuple[float, float]
) -> list[dict[str, Any]]:
    """Shopfront records (Blender XY) for every shop node that snaps onto a façade."""
    index = _BuildingIndex(layout.get("buildings") or [])
    placed: list[dict[str, Any]] = []
    per_edge: dict[Any, list[float]] = {}
    nodes = [e for e in osm.get("elements") or [] if e.get("type") == "node" and e.get("tags")]
    # Named places first so they win a crowded façade.
    nodes.sort(key=lambda e: (not e["tags"].get("name"), int(e["id"])))
    for node in nodes:
        tags = node["tags"]
        cat = category_for(tags)
        if cat is None or "lat" not in node:
            continue
        kind, category = cat
        x, y = project(float(node["lat"]), float(node["lon"]), origin[0], origin[1])
        snap = snap_to_facade(x, y, index)
        if snap is None:
            continue
        along = snap["t"] * snap["length"]
        taken = per_edge.setdefault(snap["edge"], [])
        if any(abs(along - o) < MIN_SPACING_M for o in taken):
            continue
        taken.append(along)
        hours = parse_opening_hours(tags.get("opening_hours"))
        rec = {
            "id": int(node["id"]),
            "name": (tags.get("name") or tags.get("brand") or "").strip()[:28],
            "kind": kind,
            "cat": category,
            "x": round(snap["x"], 2),
            "y": round(snap["y"], 2),
            "nx": round(snap["nx"], 4),
            "ny": round(snap["ny"], 4),
            "w": round(snap["w"], 2),
            "hours": [[list(s) for s in day] for day in (hours or DEFAULT_HOURS[category])],
            "hoursKnown": hours is not None,
        }
        placed.append(rec)
    return placed


def export_shops_for_viewer(
    shops: list[dict[str, Any]], spawn: dict[str, Any] | None, radius: float = 900.0
) -> dict[str, Any]:
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0
    near = [s for s in shops if math.hypot(s["x"] - sx, s["y"] - sy) <= radius]
    return {
        "attribution": "Shops: (c) OpenStreetMap contributors (ODbL)",
        "shops": near,
    }
