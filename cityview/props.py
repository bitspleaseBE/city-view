"""Solid street props for the walk viewer's collision (Blender XY, metres).

Tree trunks, benches, bike racks and fences/walls are baked into the GLB as merged
meshes, so the viewer cannot collide against them; this exports their footprints:

* ``trunks``   ``[x, y, r]`` – same trunk radius rule as ``blender/trees_blender.py``
* ``boxes``    ``[x, y, yaw, half_len, half_depth]`` – benches and bike racks
* ``segments`` ``[x0, y0, x1, y1, half_thickness]`` – fences, walls, hedges
"""

from __future__ import annotations

import math
from typing import Any

BARRIER_KINDS = frozenset({"fence", "wall", "hedge", "retaining"})
POST_RADIUS = {
    "bollard": 0.09, "hydrant": 0.14, "bin": 0.25, "cabinet": 0.38, "recycling": 0.65,
    "post_box": 0.28, "meter": 0.12, "flagpole": 0.08, "charging": 0.28, "vending": 0.35,
    "artwork": 0.45, "guidepost": 0.12,
}
BOX_KINDS = {
    "picnic_table": (0.9, 0.55),  # half_len, half_depth
}


def trunk_radius(height: float, crown_radius: float) -> float:
    return max(0.09, min(0.36, 0.07 + 0.016 * height, 0.06 + 0.07 * crown_radius))


def export_props_for_viewer(
    layout: dict[str, Any], spawn: dict[str, Any] | None = None, radius: float = 1500.0
) -> dict[str, Any]:
    sx = float(spawn["x"]) if spawn else 0.0
    sy = float(spawn["y"]) if spawn else 0.0

    def near(x: float, y: float) -> bool:
        return math.hypot(x - sx, y - sy) <= radius

    trunks = []
    for t in layout.get("trees") or []:
        x, y = float(t["x"]), float(t["y"])
        if near(x, y):
            r = trunk_radius(float(t.get("height") or 8.0), float(t.get("radius") or 2.5))
            trunks.append([round(x, 2), round(y, 2), round(r, 2)])

    boxes = []
    for b in layout.get("benches") or []:
        x, y = float(b["x"]), float(b["y"])
        if near(x, y):
            half_len = float(b.get("length") or 1.8) * 0.5
            boxes.append([round(x, 2), round(y, 2), round(float(b.get("yaw") or 0.0), 3), round(half_len, 2), 0.3])
    for c in layout.get("clutter") or []:
        x, y = float(c["x"]), float(c["y"])
        kind = c.get("kind")
        if kind in POST_RADIUS and near(x, y):
            trunks.append([round(x, 2), round(y, 2), POST_RADIUS[kind]])
            continue
        if kind == "bike_rack" and near(x, y):
            half_len = max(0.6, int(c.get("hoops") or 4) * 0.4)
            boxes.append([round(x, 2), round(y, 2), round(float(c.get("yaw") or 0.0), 3), round(half_len, 2), 0.12])
            continue
        if kind in BOX_KINDS and near(x, y):
            half_len, half_depth = BOX_KINDS[kind]
            boxes.append(
                [round(x, 2), round(y, 2), round(float(c.get("yaw") or 0.0), 3), half_len, half_depth]
            )

    segments = []
    for w in layout.get("barriers") or []:
        if w.get("kind") not in BARRIER_KINDS or "x0" not in w:
            continue
        x0, y0, x1, y1 = (float(w[k]) for k in ("x0", "y0", "x1", "y1"))
        if near(x0, y0) or near(x1, y1):
            half_t = 0.3 if w.get("kind") == "hedge" else 0.12
            segments.append([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2), half_t])

    return {"trunks": trunks, "boxes": boxes, "segments": segments}
