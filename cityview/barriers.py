"""Garden walls, hedges, fences and retaining walls from OpenStreetMap ``barrier=*`` ways.

Courtyards, back gardens and plot boundaries are what make a block read as lived-in from
street level instead of a ring of facades around a flat void. OSM maps them as lines, so
this is surveyed geometry, not invented clutter:

=====================  =========================  =========  ========
kind                   OSM tags                   height     section
=====================  =========================  =========  ========
``wall``               ``barrier=wall``           1.8 m      0.22 m
``retaining``          ``barrier=retaining_wall`` 1.0 m      0.40 m
``hedge``              ``barrier=hedge``          1.3 m      0.70 m
``fence``              ``barrier=fence``          1.2 m      posts + rails
=====================  =========================  =========  ========

``height=*`` (metres) and ``material=*`` are honoured when mapped (brick / concrete / stone /
render; unmapped walls get a neutral render colour, never a random brick-or-not guess).
Gates, underground / tunnel ways and anything not a plain line are skipped.

Each way is walked in ``STEP_M`` samples and only the stretches that are actually visible
survive: not inside (or hugging, ``BUILDING_MARGIN``) a building footprint, where the wall
is just the party wall already modelled; not on a carriageway; not on a tram bed. Contiguous
surviving samples are emitted as one straight run so a wall that crosses a house is split
into the two stretches either side of it, not drawn through the roof.

LOD: hedges and fences are small, so they are only kept within ``DETAIL_RADIUS_M`` of the
spawn; walls (which silhouette whole courtyards) are kept tile-wide.
"""

from __future__ import annotations

import math
from typing import Any

from cityview.benches import CARRIAGEWAY, _Ways
from cityview.geo import project
from cityview.railclear import CLEAR_FURNITURE
from cityview.trees import _Obstacles

ATTRIBUTION = "Walls, hedges and fences: (c) OpenStreetMap contributors (ODbL)."

KINDS = ("wall", "retaining", "hedge", "fence")
BARRIER_KIND = {"wall": "wall", "retaining_wall": "retaining", "hedge": "hedge", "fence": "fence"}
DEFAULT_HEIGHT = {"wall": 1.8, "retaining": 1.0, "hedge": 1.3, "fence": 1.2}
THICKNESS = {"wall": 0.22, "retaining": 0.4, "hedge": 0.7, "fence": 0.05}
MAX_HEIGHT = 6.0
MIN_HEIGHT = 0.4
STEP_M = 0.8  # visibility sampling along a way
BUILDING_MARGIN = 0.3  # a wall this close to a footprint is the building's own party wall
MIN_RUN_M = 0.8  # drop slivers shorter than this
DETAIL_RADIUS_M = 450.0
DETAIL_KINDS = frozenset({"hedge", "fence"})
# Neutral stand-ins for ``material=*``; unmapped walls use ``render``.
MATERIALS = {
    "brick": "brick",
    "bricks": "brick",
    "concrete": "concrete",
    "cement_block": "concrete",
    "stone": "stone",
    "granite": "stone",
    "limestone": "stone",
    "sandstone": "stone",
    "plaster": "render",
    "stucco": "render",
    "render": "render",
}


def classify(tags: dict[str, str]) -> str | None:
    kind = BARRIER_KIND.get(tags.get("barrier", ""))
    if kind is None:
        return None
    if tags.get("location") in {"underground", "underwater"} or tags.get("tunnel") in {"yes", "building_passage"}:
        return None
    try:
        if float(str(tags.get("layer", "0")).split(";")[0]) < 0:
            return None
    except ValueError:
        pass
    return kind


def parse_height(tags: dict[str, str], kind: str) -> float:
    """Mapped ``height`` in metres (clamped), else the per-kind default."""
    raw = str(tags.get("height", "")).replace(",", ".").replace("m", "").strip()
    try:
        h = float(raw)
    except ValueError:
        return DEFAULT_HEIGHT[kind]
    if not math.isfinite(h) or h <= 0:
        return DEFAULT_HEIGHT[kind]
    return max(MIN_HEIGHT, min(MAX_HEIGHT, h))


def surface(tags: dict[str, str], kind: str) -> str:
    if kind == "hedge":
        return "hedge"
    if kind == "fence":
        return "metal"
    return MATERIALS.get(str(tags.get("material", "")).lower(), "render")


def osm_barriers(osm: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Classified open polylines ``{id, kind, height, surface, pts: [(lat, lon)...]}``."""
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
        pts = [(float(nodes[int(n)]["lat"]), float(nodes[int(n)]["lon"])) for n in el.get("nodes") or [] if int(n) in nodes]
        if len(pts) < 2:
            continue
        out.append(
            {
                "id": int(el["id"]),
                "kind": kind,
                "height": parse_height(tags, kind),
                "surface": surface(tags, kind),
                "pts": pts,
            }
        )
    return out


def _walk(ax: float, ay: float, bx: float, by: float) -> list[tuple[float, float, float]]:
    """Samples ``(t, x, y)`` along a segment, always including both ends."""
    length = math.hypot(bx - ax, by - ay)
    n = max(1, int(math.ceil(length / STEP_M)))
    return [(i / n, ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)]


def plan_barriers(
    layout: dict[str, Any],
    items: list[dict[str, Any]],
    origin: tuple[float, float],
    bbox: tuple[float, float, float, float] | None = None,
    spawn_xy: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Return ``{"barriers": [...], "stats": {...}}`` with straight runs in local metres.

    Each run is ``{kind, surface, h, x0, y0, x1, y1, id}``.
    """
    obstacles = _Obstacles(layout)
    ways = _Ways(layout)
    stats: dict[str, Any] = {k: 0 for k in KINDS}
    stats.update({"metres": 0.0, "dropped_building": 0, "dropped_carriageway": 0, "dropped_rail": 0, "dropped_outside": 0, "dropped_far": 0})
    if bbox is not None:
        x_lo, y_lo = project(bbox[0], bbox[1], origin[0], origin[1])
        x_hi, y_hi = project(bbox[2], bbox[3], origin[0], origin[1])
    else:
        x_lo = y_lo = -math.inf
        x_hi = y_hi = math.inf
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda i: (i["kind"], i["id"])):
        kind = item["kind"]
        local = [project(lat, lon, origin[0], origin[1]) for lat, lon in item["pts"]]
        for (ax, ay), (bx, by) in zip(local, local[1:]):
            if math.hypot(bx - ax, by - ay) < 1e-6:
                continue
            run_start: tuple[float, float] | None = None
            run_end: tuple[float, float] | None = None
            samples = _walk(ax, ay, bx, by)
            for idx, (_t, x, y) in enumerate(samples):
                reason = None
                if not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
                    reason = "dropped_outside"
                elif kind in DETAIL_KINDS and spawn_xy is not None and math.hypot(x - spawn_xy[0], y - spawn_xy[1]) > DETAIL_RADIUS_M:
                    reason = "dropped_far"
                elif obstacles.in_building(x, y, BUILDING_MARGIN):
                    reason = "dropped_building"
                else:
                    road = ways.nearest(x, y, CARRIAGEWAY, 0.0)
                    if road and road[0] < 0.0:
                        reason = "dropped_carriageway"
                    elif obstacles.on_rails(x, y, CLEAR_FURNITURE):
                        reason = "dropped_rail"
                if reason is None:
                    if run_start is None:
                        run_start = (x, y)
                    run_end = (x, y)
                    if idx < len(samples) - 1:
                        continue
                else:
                    stats[reason] += 1
                if run_start is not None and run_end is not None:
                    length = math.hypot(run_end[0] - run_start[0], run_end[1] - run_start[1])
                    if length >= MIN_RUN_M:
                        out.append(
                            {
                                "id": item["id"],
                                "kind": kind,
                                "surface": item["surface"],
                                "h": round(item["height"], 2),
                                "x0": round(run_start[0], 3),
                                "y0": round(run_start[1], 3),
                                "x1": round(run_end[0], 3),
                                "y1": round(run_end[1], 3),
                            }
                        )
                        stats[kind] += 1
                        stats["metres"] += length
                run_start = run_end = None
    stats["metres"] = round(stats["metres"], 1)
    return {"barriers": out, "stats": stats}


def attach_barriers(
    layout: dict[str, Any],
    osm: dict[str, Any] | None,
    bbox: tuple[float, float, float, float],
    origin: tuple[float, float],
    spawn_xy: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Plan OSM walls / hedges / fences and store them on ``layout`` (OSM already loaded)."""
    plan = plan_barriers(layout, osm_barriers(osm), origin, bbox, spawn_xy)
    layout["barriers"] = plan["barriers"]
    layout["barrier_stats"] = plan["stats"]
    return plan


def summarize(plan: dict[str, Any]) -> str:
    s = plan["stats"]
    placed = ", ".join(f"{k}={s[k]}" for k in KINDS if s.get(k))
    dropped = ", ".join(f"{k[8:]}={v}" for k, v in s.items() if k.startswith("dropped_") and v)
    return f"{len(plan['barriers'])} runs, {s['metres']:.0f} m ({placed or 'none'}); dropped samples: {dropped or 'none'}"
