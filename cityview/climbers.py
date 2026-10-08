"""Climbing-plant (ivy / Virginia creeper) placement and growth shape.

Pure stdlib on purpose: ``blender/build_city.py`` imports this inside Blender's
Python and unit tests import it without ``bpy``.

Placement policy
----------------
Real façade greenery is the exception, not the rule. A *street* is every OSM
way sharing one street name (a long street is split into many ways). Each
street rolls a stable hash (no ``random``, so rebuilds are reproducible):

* ~60 % of streets: no climbing plant at all
* ~34 % of streets: exactly one house with a climbing plant
* ~6 % of streets: two houses (hard cap ``MAX_PER_STREET``), >= ``MIN_SPACING`` m apart

Only street-facing façades of period houses (Art Nouveau first, then
Neo-Flemish / eclectic / neoclassical / brick) are candidates; modern infill and
international-style blocks never get one. Unnamed roads (service lanes, paths)
are not streets and never receive plants.

Growth model
------------
``generate_climber`` returns stems (thin ribbons) and leaf clusters in façade
space ``(along, z)``. The vine roots on the ground in a pier *between* windows,
climbs 2-4 floors with a wandering stem and a few side tendrils, is dense and
wide near the base and ragged / sparse at the top, has bare patches, and leaves
window / door openings mostly clear.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Any

MAX_PER_STREET = 2
MIN_SPACING = 35.0  # metres between two plants on the same street
ZERO_SHARE = 0.60  # share of streets with no plant
ONE_SHARE = 0.34  # share of streets with exactly one (rest: two)

# Streets proper (named carriageways people walk along); not paths / service lanes.
STREET_KINDS = frozenset(
    {
        "residential",
        "tertiary",
        "secondary",
        "primary",
        "unclassified",
        "living_street",
        "pedestrian",
    }
)

# Candidate weight per building type; 0 = never.
STYLE_WEIGHT = {
    "art-nouveau": 1.7,
    "neo-flemish": 1.2,
    "eclectic": 1.0,
    "neoclassical": 1.0,
    "neo-gothic": 1.0,
    "red-brick": 0.9,
    "yellow-brick": 0.8,
    "cream-tile": 0.5,
    "art-deco": 0.35,
    "international": 0.0,
    "modern-infill": 0.0,
}

MIN_EDGE_LENGTH = 6.0
MIN_EAVES = 8.5
MAX_SPAWN_DIST = 140.0  # same radius as detail == "full" in build_city

# Leaf palette indices (see build_city "climber" materials).
# Leaf draws per 0.4 m of stem climb (density knob; leaves are small and overlap).
DRAWS_PER_STEP = 24

LEAF_DARK, LEAF_MID, LEAF_LIGHT, LEAF_OLIVE, LEAF_RED, STEM = range(6)


def _unit(*parts: object) -> float:
    """Stable hash -> [0, 1)."""
    digest = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2.0**64


def street_quota(street: str) -> int:
    """How many climbing plants this street gets (0, 1 or 2)."""
    u = _unit("climber-street", street.casefold())
    if u < ZERO_SHARE:
        return 0
    if u < ZERO_SHARE + ONE_SHARE:
        return 1
    return MAX_PER_STREET


def _point_seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _street_segments(roads: list[dict[str, Any]]) -> list[tuple[str, float, float, float, float, float]]:
    segs = []
    for road in roads:
        name = str(road.get("name") or "").strip()
        if not name or (road.get("kind") or "residential") not in STREET_KINDS:
            continue
        reach = float(road.get("width") or 6.0) * 0.5 + 9.0
        pts = road.get("points") or []
        for i in range(len(pts) - 1):
            segs.append((name.casefold(), pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], reach))
    return segs


def _street_of(x: float, y: float, segs) -> str | None:
    best, best_d = None, 1e18
    for name, ax, ay, bx, by, reach in segs:
        d = _point_seg_dist(x, y, ax, ay, bx, by)
        if d <= reach and d < best_d:
            best, best_d = name, d
    return best


def plan_climbers(
    layout: dict[str, Any],
    spawn_xy: tuple[float, float] | None,
    max_dist: float = MAX_SPAWN_DIST,
) -> dict[tuple[int, int], dict[str, Any]]:
    """Choose which (building id, street_edges index) gets a climbing plant."""
    segs = _street_segments(layout.get("roads") or [])
    if not segs:
        return {}

    by_street: dict[str, list[tuple[float, int, int, float, float, dict[str, Any]]]] = {}
    for bldg in layout.get("buildings") or []:
        weight = STYLE_WEIGHT.get(str(bldg.get("building_type") or bldg.get("style") or "eclectic"), 0.8)
        if weight <= 0.0:
            continue
        ring = bldg.get("ring") or []
        if len(ring) < 3 or float(bldg.get("height", 0.0)) < MIN_EAVES:
            continue
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        if spawn_xy is not None and math.hypot(cx - spawn_xy[0], cy - spawn_xy[1]) > max_dist:
            continue
        edges = bldg.get("street_edges") or []
        best_i, best_len = -1, MIN_EDGE_LENGTH
        for i, edge in enumerate(edges):
            if float(edge.get("length", 0.0)) >= best_len:
                best_i, best_len = i, float(edge["length"])
        if best_i < 0:
            continue
        edge = edges[best_i]
        p0, p1 = ring[int(edge["i0"])], ring[int(edge["i1"])]
        out = edge.get("outward") or [0.0, 1.0]
        mx = (p0[0] + p1[0]) * 0.5 + out[0] * 3.0
        my = (p0[1] + p1[1]) * 0.5 + out[1] * 3.0
        street = _street_of(mx, my, segs)
        if street is None:
            continue
        bid = int(bldg.get("id", 0))
        score = weight * (0.35 + _unit("climber-house", bid))
        by_street.setdefault(street, []).append((score, bid, best_i, mx, my, bldg))

    plan: dict[tuple[int, int], dict[str, Any]] = {}
    for street, cands in sorted(by_street.items()):
        quota = min(MAX_PER_STREET, street_quota(street))
        if quota <= 0:
            continue
        chosen: list[tuple[float, float]] = []
        for score, bid, ei, mx, my, _bldg in sorted(cands, key=lambda c: (-c[0], c[1])):
            if len(chosen) >= quota:
                break
            if any(math.hypot(mx - cx, my - cy) < MIN_SPACING for cx, cy in chosen):
                continue
            chosen.append((mx, my))
            plan[(bid, ei)] = {
                "street": street,
                "seed": int(_unit("climber-seed", bid) * 2**31),
                "species": "creeper" if _unit("climber-species", bid) < 0.3 else "ivy",
                "height_frac": 0.62 + 0.33 * _unit("climber-height", bid),
            }
    return plan


def _leaf_roll(rng: random.Random) -> float:
    """Leaf orientation: ivy leaves mostly hang tip-down / outward, a few point up."""
    if rng.random() < 0.2:
        return rng.uniform(0.0, 2.0 * math.pi)
    return math.pi + rng.gauss(0.0, 0.8)


def _pick_root(rng: random.Random, length: float, obstacles: list[tuple[float, float, float, float]]) -> float:
    """Façade position with the widest clear pier around it (between windows)."""
    lo, hi = -length * 0.5 + 1.2, length * 0.5 - 1.2
    if hi <= lo:
        return 0.0
    scored = []
    for _ in range(24):
        a = rng.uniform(lo, hi)
        gap = 9.0
        for ac, hw, _z0, _z1 in obstacles:
            gap = min(gap, abs(a - ac) - hw)
        scored.append((gap + rng.uniform(0.0, 0.25), a))
    scored.sort(reverse=True)
    return scored[rng.randrange(min(4, len(scored)))][1]


def generate_climber(
    spec: dict[str, Any],
    length: float,
    eaves_z: float,
    plinth_h: float,
    obstacles: list[tuple[float, float, float, float]],
) -> dict[str, list[tuple[float, ...]]]:
    """Return ``{"stems": [(a0, z0, a1, z1, width)], "leaves": [(a, z, w, h, roll, depth, mat)]}``.

    ``obstacles`` are ``(along_centre, half_width, z0, z1)`` rectangles (windows, door).
    """
    rng = random.Random(int(spec["seed"]))
    creeper = spec.get("species") == "creeper"
    half = length * 0.5 - 0.25
    top = min(eaves_z - 0.35, 15.0)
    height = max(4.0, min(top, float(spec.get("height_frac", 0.8)) * eaves_z))
    root = _pick_root(rng, length, obstacles)

    # Irregular coverage: two or three bare patches along the climb.
    gaps = []
    for _ in range(rng.randint(2, 3)):
        g0 = rng.uniform(0.15, 0.9) * height
        gaps.append((g0, g0 + rng.uniform(0.5, 1.4)))

    stems: list[tuple[float, ...]] = []
    leaves: list[tuple[float, ...]] = []

    def keep(a: float, z: float) -> bool:
        if abs(a) > half or z > top or z < 0.1:
            return False
        for ac, hw, z0, z1 in obstacles:
            if abs(a - ac) < hw * 0.92 and z0 - 0.05 < z < z1 + 0.05 and rng.random() < 0.86:
                return False
        return True

    def leaf_mat(t: float) -> int:
        r = rng.random()
        if creeper:
            red_p = 0.05 + 0.22 * t
            if r < red_p:
                return LEAF_RED
            return LEAF_LIGHT if r < red_p + 0.35 else LEAF_MID
        # Ivy: dark and glossy low down, fresher growth near the tips.
        if r < 0.40 - 0.25 * t:
            return LEAF_DARK
        if r < 0.80 - 0.15 * t:
            return LEAF_MID
        return LEAF_LIGHT if rng.random() < 0.6 else LEAF_OLIVE

    def scatter(a: float, z: float, t: float, sigma: float, density: float) -> None:
        for gz0, gz1 in gaps:
            if gz0 < z < gz1:
                density *= 0.2
        for _ in range(DRAWS_PER_STEP):
            if rng.random() > density:
                continue
            la = a + rng.gauss(0.0, sigma)
            lz = z + rng.uniform(-0.3, 0.3)
            if not keep(la, lz):
                continue
            w = rng.uniform(0.12, 0.24) * (1.0 if t < 0.75 else 0.8)
            leaves.append(
                (
                    la,
                    lz,
                    w,
                    w * rng.uniform(1.0, 1.3),
                    _leaf_roll(rng),
                    rng.uniform(0.02, 0.05),
                    leaf_mat(t),
                )
            )

    def grow(a: float, z: float, heading: float, span: float, branch: bool) -> None:
        """Walk a stem upward; ``heading`` is lateral drift per metre of climb."""
        step = 0.42 if not branch else 0.36
        z_end = min(top, z + span)
        width = 0.06 if not branch else 0.035
        while z < z_end:
            a2 = a + heading * step + rng.gauss(0.0, 0.07)
            z2 = z + step
            if branch:
                a2 = min(max(a2, -half), half)
            if abs(a2) <= half and z2 <= top:
                stems.append((a, z, a2, z2, width * (1.0 - 0.35 * (z2 / max(height, 1.0)))))
            t = min(1.0, z2 / height)
            density = 0.95 * (1.0 - t**2.2) + 0.10
            sigma = (0.16 + 0.42 * (1.0 - t) ** 0.8) * (0.55 if branch else 1.0)
            scatter(a2, z2, t, sigma, density)
            a, z = a2, z2

    # Main stem(s): often two close leaders from the same root.
    lean = rng.uniform(-0.10, 0.10)
    grow(root, 0.05, lean, height, False)
    if rng.random() < 0.6:
        grow(root + rng.uniform(-0.35, 0.35), 0.05, -lean, height * rng.uniform(0.5, 0.8), False)

    # Base clump: ivy is widest where it is oldest.
    for _ in range(rng.randint(22, 34)):
        la = root + rng.gauss(0.0, 0.6)
        lz = rng.uniform(0.15, 1.5)
        if keep(la, lz):
            w = rng.uniform(0.14, 0.26)
            leaves.append((la, lz, w, w * rng.uniform(1.0, 1.3), _leaf_roll(rng), rng.uniform(0.02, 0.05), rng.choice((LEAF_DARK, LEAF_MID))))

    # Side tendrils that wander across the wall.
    for _ in range(rng.randint(2, 4) if height > 6.0 else rng.randint(1, 2)):
        z0 = rng.uniform(0.2, 0.8) * height
        sign = rng.choice((-1.0, 1.0))
        a0 = root + rng.gauss(0.0, 0.25)
        grow(a0, z0, sign * rng.uniform(0.35, 1.1), rng.uniform(1.2, 3.2), True)

    return {"stems": stems, "leaves": leaves}
