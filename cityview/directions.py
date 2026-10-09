"""Travel directions for the runtime traffic: one-way streets and directed tram tracks.

OSM gives every way a node order, and that order *is* the reference direction:

* ``oneway=yes`` means traffic may only follow the node order, ``oneway=-1`` only the
  reverse of it. Roundabouts and motorways are implicitly one-way.
* ``oneway:bus`` / ``oneway:psv`` / ``busway=opposite_lane`` describe a bus-only exception
  (a contraflow bus lane on an otherwise one-way street).
* Tram tracks carry no tag at all. Their direction lives in the ``route=tram`` relations:
  members are listed in travel order, so the way is driven *with* its node order when the
  next member continues from its last node (or the previous member ends at its first node).
  Where relations disagree, or there is none, a parallel partner track decides (right-hand
  traffic: the partner sits on the *left* of each vehicle).

Everything here exports the same small code: ``1`` = travel along the point order,
``-1`` = against it, ``0`` = both ways allowed / unknown.
"""

from __future__ import annotations

import math
from typing import Any

_YES = {"yes", "true", "1"}
_REVERSE = {"-1", "reverse"}
_NO = {"no", "false", "0"}
_OPPOSITE_BUS_LANE = {"opposite_lane", "opposite_track", "opposite", "lane_opposite"}
_IMPLICIT_ONEWAY_HIGHWAYS = {"motorway", "motorway_link"}
_ROUTE_ROLES_SKIPPED = ("platform", "stop", "station")


def _code(value: str | None) -> int | None:
    """OSM oneway-style value → 1 / -1 / 0, or None when absent / unusable."""
    text = str(value or "").strip().lower()
    if text in _YES:
        return 1
    if text in _REVERSE:
        return -1
    if text in _NO:
        return 0
    return None


def parse_oneway(tags: dict[str, str] | None) -> int:
    """Car direction of a highway way: 1 forward only, -1 reverse only, 0 both ways."""
    tags = tags or {}
    explicit = _code(tags.get("oneway"))
    if explicit is not None:
        return explicit
    if tags.get("junction") in {"roundabout", "circular"}:
        return 1
    if tags.get("highway") in _IMPLICIT_ONEWAY_HIGHWAYS:
        return 1
    return 0


def parse_oneway_bus(tags: dict[str, str] | None) -> int:
    """Bus direction: the car rule unless a bus exception (contraflow lane) is mapped."""
    tags = tags or {}
    car = parse_oneway(tags)
    for key in ("oneway:bus", "oneway:psv"):
        explicit = _code(tags.get(key))
        if explicit is not None:
            return explicit
    if car == 0:
        return 0
    # Contraflow bus lane on a one-way street: busway(:left/:right)=opposite_lane.
    for key in ("busway", "busway:left", "busway:right", "lanes:bus:backward", "bus:backward"):
        value = str(tags.get(key) or "").lower()
        if value in _OPPOSITE_BUS_LANE or (key.endswith(":backward") and value not in {"", "no", "0"}):
            return 0
    return car


def parse_track_direction(tags: dict[str, str] | None) -> int:
    """Direction a rail way is explicitly mapped with (0 when it carries none)."""
    tags = tags or {}
    preferred = str(tags.get("railway:preferred_direction") or "").lower()
    if preferred == "forward":
        return 1
    if preferred == "backward":
        return -1
    explicit = _code(tags.get("oneway"))
    return explicit or 0


def _is_track_member(member: dict[str, Any]) -> bool:
    if member.get("type") != "way":
        return False
    role = str(member.get("role") or "").lower()
    return not role.startswith(_ROUTE_ROLES_SKIPPED)


def route_way_directions(
    rels: dict[int, dict[str, Any]],
    ways: dict[int, dict[str, Any]],
    *,
    modes: set[str] | None = None,
) -> dict[int, int]:
    """Way id → 1 / -1 / 0 from the ordered members of public-transport route relations.

    A way gets 1 (resp. -1) when every route that uses it drives it with (against) its node
    order, and 0 when routes use it both ways or its direction cannot be derived.
    """
    wanted = modes or {"tram", "subway", "light_rail", "train"}
    votes: dict[int, set[int]] = {}
    for rel in rels.values():
        tags = rel.get("tags") or {}
        if tags.get("type") not in {None, "route"} and "route" not in tags:
            continue
        if (tags.get("route") or "") not in wanted:
            continue
        members = [m for m in (rel.get("members") or []) if _is_track_member(m)]
        chain: list[tuple[int, list[int]]] = []
        for m in members:
            way = ways.get(int(m["ref"]))
            nodes = list((way or {}).get("nodes") or [])
            if len(nodes) >= 2:
                chain.append((int(m["ref"]), nodes))
        for i, (wid, nodes) in enumerate(chain):
            first, last = nodes[0], nodes[-1]
            prev_ends = set(chain[i - 1][1][::len(chain[i - 1][1]) - 1]) if i > 0 else set()
            next_ends = set(chain[i + 1][1][::len(chain[i + 1][1]) - 1]) if i + 1 < len(chain) else set()
            fwd = (last in next_ends) + (first in prev_ends)
            bwd = (first in next_ends) + (last in prev_ends)
            if fwd == bwd:
                continue  # ambiguous (loop, single member, detached) — no vote
            votes.setdefault(wid, set()).add(1 if fwd > bwd else -1)
    out: dict[int, int] = {}
    for wid, vs in votes.items():
        out[wid] = next(iter(vs)) if len(vs) == 1 else 0
    return out


def _tangent_and_mid(points: list[list[float]]) -> tuple[float, float, float, float] | None:
    if len(points) < 2:
        return None
    a = points[0]
    b = points[-1]
    dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    mid = points[len(points) // 2]
    return dx / length, dy / length, float(mid[0]), float(mid[1])


def _nearest_on_polyline(
    px: float, py: float, points: list[list[float]]
) -> tuple[float, float, float, float, float]:
    """(dist, foot_x, foot_y, tan_x, tan_y) of the closest point on a polyline."""
    best = (math.inf, 0.0, 0.0, 1.0, 0.0)
    for i in range(1, len(points)):
        ax, ay = float(points[i - 1][0]), float(points[i - 1][1])
        bx, by = float(points[i][0]), float(points[i][1])
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        fx, fy = ax + dx * t, ay + dy * t
        d = math.hypot(px - fx, py - fy)
        if d < best[0]:
            length = math.sqrt(l2)
            best = (d, fx, fy, dx / length, dy / length)
    return best


def infer_parallel_track_directions(
    tracks: list[dict[str, Any]],
    *,
    max_gap: float = 14.0,
) -> None:
    """Direct still-undirected tram tracks from a parallel partner (right-hand traffic).

    ``tracks`` are exported dicts with ``points`` and ``direction``. A vehicle drives with
    the partner track on its *left*; that fixes the direction of both tracks of a pair.
    """
    for track in tracks:
        if track.get("direction"):
            continue
        info = _tangent_and_mid(track.get("points") or [])
        if not info:
            continue
        tx, ty, mx, my = info
        best = None
        for other in tracks:
            if other is track:
                continue
            d, fx, fy, ox, oy = _nearest_on_polyline(mx, my, other.get("points") or [])
            if d > max_gap or abs(ox * tx + oy * ty) < 0.9:
                continue
            if best is None or d < best[0]:
                best = (d, fx, fy, other)
        if not best:
            continue
        _d, fx, fy, other = best
        # Left of (tx, ty) in x-east / y-north metres is (-ty, tx).
        left = (fx - mx) * -ty + (fy - my) * tx
        track["direction"] = 1 if left > 0 else -1
        track["directionSource"] = "parallel-track"
        if not other.get("direction"):
            # Partner runs the other way: its own reference direction decides the sign.
            o_info = _tangent_and_mid(other.get("points") or [])
            if o_info:
                dot = o_info[0] * tx + o_info[1] * ty
                want = -track["direction"]  # partner travels opposite to us…
                # …expressed along *its* point order: same orientation as us → want; else flip.
                other["direction"] = want if dot > 0 else -want
                other["directionSource"] = "parallel-track"


def mark_dual_carriageways(roads: list[dict[str, Any]], *, max_gap: float = 45.0) -> None:
    """Flag one-way halves that face an opposite one-way half of the same street.

    Adds ``dualCarriageway: True``. Pure metadata for the viewer / audit: the directions
    themselves already come from each half's own ``oneway`` tag.
    """
    halves = [r for r in roads if r.get("oneway") in (1, -1) and r.get("name")]
    for road in halves:
        info = _tangent_and_mid(road.get("points") or [])
        if not info:
            continue
        tx, ty, mx, my = info
        sign = road["oneway"]
        for other in halves:
            if other is road or other.get("name") != road.get("name"):
                continue
            d, _fx, _fy, ox, oy = _nearest_on_polyline(mx, my, other.get("points") or [])
            if d > max_gap or abs(ox * tx + oy * ty) < 0.8:
                continue
            # Opposite travel directions in world space.
            if (tx * ox + ty * oy) * sign * other["oneway"] < 0:
                road["dualCarriageway"] = True
                break
