"""Carriageway ironwork: manhole covers and kerbside gully grates.

Pure stdlib (no bpy) so the planner is unit-testable; ``blender/roadware_blender.py``
turns the plan into merged meshes.

Every Antwerp street has cast-iron manhole covers down the lane and a gully grate
(``kolk``) in the gutter at regular intervals, so a plain asphalt ribbon reads as a
flat texture. These are not surveyed in OSM, so they are *infrastructure rhythm*, not
claims about exact positions: deterministic per road id, laid at fixed pitches and kept
well clear of junction mouths (where the carriageway index says another street meets
this one) and of road ends.

* ``manhole``: round cover ~0.65 m on the lane centre-line offset (never on the road
  centre dashes), one every ``MANHOLE_PITCH_M`` with jitter.
* ``gully``: ~0.5 x 0.32 m grate against the kerb, long side along the road, alternating
  sides every ``GULLY_PITCH_M``.
"""

from __future__ import annotations

import math
from typing import Iterable

from cityview import kerbs

DRIVEABLE = frozenset({"residential", "tertiary", "secondary", "primary", "unclassified", "living_street", "service"})

NEAR_SPAWN_M = 200.0
MANHOLE_PITCH_M = 42.0
GULLY_PITCH_M = 26.0
END_MARGIN_M = 9.0  # stay out of junction mouths at road ends
CROSS_MARGIN_M = 3.0  # extra clearance from any crossing carriageway
GULLY_KERB_GAP_M = 0.04  # grate edge sits this far off the kerb face
GULLY_W = 0.32  # across the road
GULLY_L = 0.52  # along the road
MANHOLE_R = 0.33
MAX_ITEMS = 220


def _hash01(a: int, b: int) -> float:
    """Deterministic pseudo-random in [0, 1) from two ints (no global RNG state)."""
    v = (a * 73856093) ^ (b * 19349663) ^ 0x9E3779B9
    v = (v ^ (v >> 13)) * 0x5BD1E995 & 0xFFFFFFFF
    return ((v ^ (v >> 15)) & 0xFFFF) / 65536.0


def plan_roadware(
    roads: list[dict],
    spawn_xy: tuple[float, float],
    max_items: int = MAX_ITEMS,
) -> list[dict]:
    """Return ``[{kind, x, y, yaw}]`` for manholes and gullies around ``spawn_xy``.

    ``yaw`` is the road bearing at the item (the gully's long side runs along it).
    """
    index = kerbs.CarriagewayIndex(roads)
    out: list[dict] = []
    sx, sy = spawn_xy
    for ri, road in enumerate(roads):
        kind = road.get("kind") or "residential"
        if kind not in DRIVEABLE:
            continue
        pts = road.get("points") or []
        if len(pts) < 2:
            continue
        half = float(road.get("width") or 6.0) * 0.5
        if half < 1.6:  # lanes / alleys: no ironwork worth the triangles
            continue
        rid = int(road.get("id") or ri)
        seglens = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
        total = sum(seglens)
        if total < 2 * END_MARGIN_M + 4.0:
            continue
        for item_kind, pitch in (("manhole", MANHOLE_PITCH_M), ("gully", GULLY_PITCH_M)):
            phase = _hash01(rid, 17 if item_kind == "manhole" else 29) * pitch
            s = END_MARGIN_M + phase
            n = 0
            while s < total - END_MARGIN_M:
                n += 1
                x, y, tx, ty = _along(pts, seglens, s)
                s_next = s + pitch * (0.85 + 0.3 * _hash01(rid, n * 7 + len(item_kind)))
                s = s_next
                if math.hypot(x - sx, y - sy) > NEAR_SPAWN_M:
                    continue
                nx, ny = -ty, tx  # left normal
                if item_kind == "manhole":
                    side = 1.0 if _hash01(rid, n) < 0.5 else -1.0
                    lat = side * half * 0.5
                else:
                    side = 1.0 if n % 2 else -1.0
                    lat = side * (half - GULLY_W * 0.5 - GULLY_KERB_GAP_M)
                px, py = x + nx * lat, y + ny * lat
                if index.blocked(px, py, tx, ty, CROSS_MARGIN_M, exclude=ri):
                    continue
                out.append({"kind": item_kind, "x": px, "y": py, "yaw": math.atan2(ty, tx)})
    out.sort(key=lambda r: math.hypot(r["x"] - sx, r["y"] - sy))
    return out[:max_items]


def _along(pts: list, seglens: list[float], s: float) -> tuple[float, float, float, float]:
    """Point and unit tangent at arc length ``s`` along a polyline."""
    for i, ln in enumerate(seglens):
        if s <= ln or i == len(seglens) - 1:
            t = 0.0 if ln < 1e-9 else min(1.0, s / ln)
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            tx, ty = (bx - ax) / max(ln, 1e-9), (by - ay) / max(ln, 1e-9)
            return ax + (bx - ax) * t, ay + (by - ay) * t, tx, ty
        s -= ln
    raise ValueError("empty polyline")


def count_kinds(items: Iterable[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it["kind"]] = out.get(it["kind"], 0) + 1
    return out
