"""Traffic-signal facing helpers shared by the Blender builder and roads.json export.

Street furniture in this project uses Blender ``rotation_z`` with **local +Y as the
front**. After rotating by ``yaw``, local +Y points to ``(-sin yaw, cos yaw)``.
"""

from __future__ import annotations

import math
from typing import Any


def face_yaw(fx: float, fy: float) -> float:
    """``rotation_z`` that turns local +Y onto world ``(fx, fy)``."""
    length = math.hypot(fx, fy)
    if length < 1e-9:
        return 0.0
    return math.atan2(fy / length, fx / length) - math.pi / 2.0


def face_dir(yaw: float) -> tuple[float, float]:
    """World XY direction of local +Y after ``rotation_z = yaw``."""
    return (-math.sin(yaw), math.cos(yaw))


def vehicle_signal_yaw(tx: float, ty: float) -> float:
    """Yaw so the head faces oncoming traffic for inbound approach tangent ``(tx, ty)``.

    Drivers travel along ``(tx, ty)`` toward the junction; the lenses look back at them.
    """
    return face_yaw(-tx, -ty)


ZEBRA_DEPTH_M = 3.0  # bar length along the road (Belgian minimum; the walking width)
ZEBRA_BAR_M = 0.5  # bar width across the road
ZEBRA_GAP_M = 0.5
ZEBRA_HALF_M = ZEBRA_DEPTH_M * 0.5
KERB_GAP_M = 0.3  # zebra edge to the crossing road's kerb line
STOP_GAP_M = 0.6  # stop line to the zebra's near edge
APPROACH_BINS = 8
POLE_KERB_M = 0.85  # signal pole: this far beyond the carriageway edge


def junction_approaches(
    jx: float,
    jy: float,
    roads: list[dict[str, Any]],
    *,
    search_r: float = 16.0,
    kinds: frozenset[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Inbound arms of the junction around ``(jx, jy)`` with zebra / stop-line placement.

    Each arm is anchored where its own centreline meets the junction (the road node, or
    the foot of the perpendicular for a road running straight through) — never at the
    signal-cluster centroid, which can sit off the carriageway. The zebra is set back
    past the widest crossing arm's kerb so arms' zebras never overlap inside the
    junction, and the stop line sits before the zebra. A signal with no crossing arm
    (mid-block pedestrian lights) gets its zebra right at the anchor.

    Returns dicts with ``tx, ty`` (inbound unit tangent), ``width``, ``zebra_x/y``,
    ``stop_x/y`` and ``ax/ay`` (anchor).
    """
    raw: list[dict[str, Any]] = []
    for ri, road in enumerate(roads):
        if kinds is not None and str(road.get("kind") or "residential").lower() not in kinds:
            continue
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            bx, by = float(pts[i + 1][0]), float(pts[i + 1][1])
            dx, dy = bx - ax, by - ay
            seg = math.hypot(dx, dy)
            if seg < 1.0:
                continue
            tx, ty = dx / seg, dy / seg
            t = ((jx - ax) * dx + (jy - ay) * dy) / (seg * seg)
            if 0.02 < t < 0.98:
                cx, cy = ax + t * dx, ay + t * dy
                if math.hypot(cx - jx, cy - jy) <= search_r * 0.6:
                    for sign in (1.0, -1.0):
                        raw.append(
                            {
                                "tx": tx * sign,
                                "ty": ty * sign,
                                "ax": cx,
                                "ay": cy,
                                "width": width,
                                "road": ri,
                            }
                        )
                continue
            for ex, ey, sign in ((bx, by, 1.0), (ax, ay, -1.0)):
                if math.hypot(ex - jx, ey - jy) <= search_r:
                    raw.append(
                        {
                            "tx": tx * sign,
                            "ty": ty * sign,
                            "ax": ex,
                            "ay": ey,
                            "width": width,
                            "road": ri,
                        }
                    )

    # One arm per compass bin; the anchor nearest the junction wins.
    bins: dict[int, dict[str, Any]] = {}
    for ap in raw:
        key = int(round(math.atan2(ap["ty"], ap["tx"]) / (2 * math.pi / APPROACH_BINS))) % APPROACH_BINS
        ap["d"] = math.hypot(ap["ax"] - jx, ap["ay"] - jy)
        prev = bins.get(key)
        if prev is None or ap["d"] < prev["d"]:
            bins[key] = ap
    arms = sorted(bins.values(), key=lambda a: a["d"])[:4]

    for ap in arms:
        cross_half = max(
            (o["width"] * 0.5 for o in arms if o is not ap and abs(o["tx"] * ap["tx"] + o["ty"] * ap["ty"]) < 0.8),
            default=None,
        )
        if cross_half is None:
            zebra_back = 0.0
        else:
            zebra_back = min(16.0, cross_half + KERB_GAP_M + ZEBRA_HALF_M)
        stop_back = zebra_back + ZEBRA_HALF_M + STOP_GAP_M
        # Mapped centrelines rarely meet exactly (split carriageways, offset nodes): back
        # off until the kerb pole beside the stop line is clear of every other road.
        half = ap["width"] * 0.5 + POLE_KERB_M
        rx, ry = ap["ty"], -ap["tx"]
        for _ in range(10):
            px = ap["ax"] - ap["tx"] * stop_back + rx * half
            py = ap["ay"] - ap["ty"] * stop_back + ry * half
            if not _in_carriageway(px, py, roads, kinds, skip=ap["road"]):
                break
            zebra_back += 1.0
            stop_back += 1.0
        ap["zebra_x"] = ap["ax"] - ap["tx"] * zebra_back
        ap["zebra_y"] = ap["ay"] - ap["ty"] * zebra_back
        ap["stop_x"] = ap["ax"] - ap["tx"] * stop_back
        ap["stop_y"] = ap["ay"] - ap["ty"] * stop_back
        del ap["d"], ap["road"]
    return arms


def road_at(
    x: float, y: float, roads: list[dict[str, Any]], kinds=None
) -> tuple[float, float, float, float, float, float] | None:
    """Nearest carriageway to ``(x, y)``: ``(foot_x, foot_y, tx, ty, width, dist)``.

    ``(tx, ty)`` is the local road direction, so a crossing laid along its normal runs
    straight from kerb to kerb.
    """
    best = None
    for road in roads:
        if kinds is not None and str(road.get("kind") or "residential").lower() not in kinds:
            continue
        pts = road.get("points") or []
        width = float(road.get("width") or 6.0)
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            dx, dy = float(pts[i + 1][0]) - ax, float(pts[i + 1][1]) - ay
            l2 = dx * dx + dy * dy
            if l2 < 1e-6:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            fx, fy = ax + t * dx, ay + t * dy
            d = math.hypot(x - fx, y - fy)
            if best is None or d < best[5]:
                n = math.sqrt(l2)
                best = (fx, fy, dx / n, dy / n, width, d)
    return best


def zebra_bars(span: float) -> list[float]:
    """Offsets across the carriageway (from its centreline) of each zebra bar's centre.

    Bars lie parallel to the kerb, ``ZEBRA_BAR_M`` wide, separated by ``ZEBRA_GAP_M``,
    centred on the road and kept clear of both kerbs.
    """
    pitch = ZEBRA_BAR_M + ZEBRA_GAP_M
    n = max(1, int((span - ZEBRA_BAR_M) // pitch) + 1)
    first = -(n - 1) * pitch * 0.5
    return [first + k * pitch for k in range(n)]


def in_carriageway(
    x: float,
    y: float,
    roads: list[dict[str, Any]],
    kinds=None,
    *,
    skip: int | None = None,
    margin: float = 0.2,
) -> bool:
    """True if ``(x, y)`` sits inside a driveable road strip (minus ``margin``)."""
    for k, road in enumerate(roads):
        if skip is not None and k == skip:
            continue
        if kinds is not None and str(road.get("kind") or "residential").lower() not in kinds:
            continue
        pts = road.get("points") or []
        half = float(road.get("width") or 6.0) * 0.5 - margin
        for i in range(len(pts) - 1):
            ax, ay = float(pts[i][0]), float(pts[i][1])
            dx, dy = float(pts[i + 1][0]) - ax, float(pts[i + 1][1]) - ay
            l2 = dx * dx + dy * dy
            if l2 < 1e-9:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            if math.hypot(x - ax - t * dx, y - ay - t * dy) < half:
                return True
    return False


def _in_carriageway(
    x: float, y: float, roads: list[dict[str, Any]], kinds, *, skip: int, margin: float = 0.2
) -> bool:
    return in_carriageway(x, y, roads, kinds, skip=skip, margin=margin)


def pedestrian_signal_yaw(rx: float, ry: float, side: float) -> float:
    """Yaw so a pedestrian head on the curb faces people waiting to cross.

    ``(rx, ry)`` is the right-hand perpendicular of the inbound tangent; ``side`` is
    ``+1`` when the pole sits on that right curb (``-1`` on the left). The face looks
    across the carriageway from the curb (into the zebra).
    """
    return face_yaw(-rx * side, -ry * side)
