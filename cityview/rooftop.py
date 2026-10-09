"""Where chimneys and rooftop plant go (pure geometry; the Blender side only draws them).

Pitched roofs get brick stacks where terraced houses really have them: on the ridge, near
the party walls at either end of the block (hip roofs: near the apex; mansards: on the flat
top). Flat roofs get a stair/lift head, air-handling units, a vent stack and, on a few,
an aerial. Everything is seeded by the building id, kept inside an inset of the footprint,
and returned in world metres so ``blender/build_city.py`` only has to build boxes.
"""

from __future__ import annotations

import math
from typing import Any

Ring = list[list[float]]

STACK_RISE = 1.05  # a chimney clears the ridge by about a metre
STACK_BURY = 0.55  # the stack runs this far below the ridge so the slope never shows a gap
PARTY_INSET_M = 0.95  # first stack stands this far in from a party wall
MIN_FLAT_ROOF_M2 = 60.0
MIN_STAIR_ROOF_M2 = 140.0


def _unit(seed: int, salt: int) -> float:
    """Stable pseudo-random number in [0, 1) from ``(seed, salt)``."""
    v = (seed * 1103515245 + salt * 12345 + 0x9E3779B9) & 0x7FFFFFFF
    v = (v ^ (v >> 15)) * 2246822519 & 0x7FFFFFFF
    return (v ^ (v >> 13)) / 0x7FFFFFFF


def point_in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def ring_area(ring: Ring) -> float:
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))) * 0.5


def obb(ring: Ring) -> tuple[float, float, float, float, float, float, float, float]:
    """``(cx, cy, ux, uy, vx, vy, half_u, half_v)`` principal-axis box, ``u`` the long axis."""
    n = max(1, len(ring))
    cx = sum(p[0] for p in ring) / n
    cy = sum(p[1] for p in ring) / n
    cxx = sum((p[0] - cx) ** 2 for p in ring) / n
    cyy = sum((p[1] - cy) ** 2 for p in ring) / n
    cxy = sum((p[0] - cx) * (p[1] - cy) for p in ring) / n
    ang = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux
    hu = max(abs((p[0] - cx) * ux + (p[1] - cy) * uy) for p in ring)
    hv = max(abs((p[0] - cx) * vx + (p[1] - cy) * vy) for p in ring)
    if hu < hv:
        ux, uy, vx, vy, hu, hv = vx, vy, ux, uy, hv, hu
    return cx, cy, ux, uy, vx, vy, max(hu, 0.8), max(hv, 0.8)


def _inset_ok(ring: Ring, x: float, y: float, margin: float, half_w: float) -> bool:
    """A centre ``(x, y)`` whose footprint (``half_w``) plus ``margin`` stays in the ring."""
    r = half_w + margin
    for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r), (r, -r), (-r, r)):
        if not point_in_ring(x + dx, y + dy, ring):
            return False
    return True


def plan_chimneys(ring: Ring, eaves_z: float, roof_h: float, shape: str, seed: int) -> list[dict[str, Any]]:
    """Stacks ``{x, y, z, yaw, w, d, h, pots}`` (``z`` = base of the stack, world metres)."""
    if len(ring) < 3 or shape == "flat":
        return []
    cx, cy, ux, uy, vx, vy, hu, hv = obb(ring)
    h_roof = max(1.0, roof_h)
    yaw = math.atan2(uy, ux)
    count = 1 + int(_unit(seed, 1) * 2.4)  # 1-3 stacks
    sites: list[tuple[float, float, float]] = []  # (x, y, roof height at the site)
    if shape == "gable":
        along = hu - PARTY_INSET_M
        if along < 0.8:
            sites.append((cx, cy, eaves_z + h_roof))
        else:
            # Party-wall ends first (alternating), then one mid-ridge.
            for i in range(count):
                if i == 0:
                    s = -1.0 if _unit(seed, 2) < 0.5 else 1.0
                    u = s * along
                elif i == 1:
                    u = -sites_u(sites, cx, cy, ux, uy)
                else:
                    u = (_unit(seed, 3) - 0.5) * along
                sites.append((cx + u * ux, cy + u * uy, eaves_z + h_roof))
    elif shape == "hip":
        reach = min(hu, hv * 2.0) * 0.18
        for i in range(count):
            u = (_unit(seed, 10 + i) - 0.5) * 2.0 * reach
            # Roof height at distance u from the apex of a pyramid over the footprint's long axis.
            drop = h_roof * abs(u) / max(hu, 1.0) * 0.9
            sites.append((cx + u * ux, cy + u * uy, eaves_z + h_roof - drop))
    else:  # mansard: stand on the flat top, which is inset 1.25 m
        for i in range(count):
            u = (_unit(seed, 20 + i) - 0.5) * max(0.0, hu - 2.4)
            v = (_unit(seed, 30 + i) - 0.5) * max(0.0, hv - 2.4) * 0.6
            sites.append((cx + u * ux + v * vx, cy + u * uy + v * vy, eaves_z + h_roof))
    out: list[dict[str, Any]] = []
    for i, (x, y, roof_z) in enumerate(sites):
        w = 0.58 + 0.22 * _unit(seed, 40 + i)
        d = 0.46 + 0.14 * _unit(seed, 50 + i)
        if not _inset_ok(ring, x, y, 0.55, max(w, d) * 0.5):
            continue
        if any(math.hypot(x - o["x"], y - o["y"]) < 1.4 for o in out):
            continue
        out.append(
            {
                "x": x,
                "y": y,
                "z": roof_z - STACK_BURY,
                "yaw": yaw,
                "w": w,
                "d": d,
                "h": STACK_BURY + STACK_RISE,
                "pots": 1 + int(_unit(seed, 60 + i) * 3.0),
            }
        )
    return out


def sites_u(sites: list[tuple[float, float, float]], cx: float, cy: float, ux: float, uy: float) -> float:
    """Signed position along the ridge of the first stack (to mirror the second one)."""
    if not sites:
        return 0.0
    return (sites[0][0] - cx) * ux + (sites[0][1] - cy) * uy


def plan_roof_plant(ring: Ring, top_z: float, seed: int) -> list[dict[str, Any]]:
    """Flat-roof extras ``{kind, x, y, z, yaw, sx, sy, sz}`` (``z`` = base, world metres)."""
    if len(ring) < 3:
        return []
    area = ring_area(ring)
    if area < MIN_FLAT_ROOF_M2:
        return []
    cx, cy, ux, uy, vx, vy, hu, hv = obb(ring)
    yaw = math.atan2(uy, ux)
    out: list[dict[str, Any]] = []

    def place(kind: str, u: float, v: float, sx: float, sy: float, sz: float, margin: float = 0.7) -> None:
        x, y = cx + u * ux + v * vx, cy + u * uy + v * vy
        if not _inset_ok(ring, x, y, margin, max(sx, sy) * 0.5):
            return
        if any(math.hypot(x - o["x"], y - o["y"]) < (max(sx, sy) + max(o["sx"], o["sy"])) * 0.5 + 0.4 for o in out):
            return
        out.append({"kind": kind, "x": x, "y": y, "z": top_z - 0.02, "yaw": yaw, "sx": sx, "sy": sy, "sz": sz})

    if area >= MIN_STAIR_ROOF_M2:
        s = -1.0 if _unit(seed, 70) < 0.5 else 1.0
        place("stair", s * hu * (0.35 + 0.3 * _unit(seed, 71)), (_unit(seed, 72) - 0.5) * hv * 0.6, 2.6, 2.2, 2.5)
    for i in range(1 + int(area > 220.0) + int(area > 600.0)):
        place(
            "hvac",
            (_unit(seed, 80 + i) - 0.5) * 2.0 * hu * 0.7,
            (_unit(seed, 90 + i) - 0.5) * 2.0 * hv * 0.7,
            1.5 + 0.9 * _unit(seed, 100 + i),
            0.9 + 0.5 * _unit(seed, 110 + i),
            0.8 + 0.4 * _unit(seed, 120 + i),
        )
    place("vent", (_unit(seed, 130) - 0.5) * hu * 1.4, (_unit(seed, 131) - 0.5) * hv * 1.4, 0.2, 0.2, 1.2 + _unit(seed, 132), 0.5)
    if _unit(seed, 140) < 0.25:
        place("aerial", (_unit(seed, 141) - 0.5) * hu, (_unit(seed, 142) - 0.5) * hv, 0.1, 0.1, 3.0 + 1.5 * _unit(seed, 143), 0.5)
    return out
