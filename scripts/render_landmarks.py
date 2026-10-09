"""Street-level renders of the hand-modelled landmarks (before/after comparisons).

    blender -b output/antwerp_harmonie.blend --python scripts/render_landmarks.py -- \
        --layout output/antwerp_harmonie_layout.json --tag after [--only zas_vincentius]

Cameras come from each landmark's surveyed front frame in the layout, so the same
shots work on an older .blend (pass the new layout) for the "before" set.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from cityview import landmark_kit as K  # noqa: E402

# (shot name, a, d, eye z, target a, target d, target z, lens) in the landmark's front frame;
# a/d may be strings "W" meaning a fraction of the front length.
SHOTS = {
    "zas_vincentius": [
        ("front", 0.5, 26.0, 1.7, 0.5, 0.0, 14.0, 18),
        ("wing", -14.0, 24.0, 1.7, -0.2, -6.0, 9.0, 24),
    ],
    "feestzaal_harmonie": [
        ("park", 0.5, 34.0, 1.7, 0.5, -4.0, 6.5, 24),
        ("portico", 1.15, 14.0, 1.7, 0.5, -2.0, 6.0, 26),
    ],
    "art_deco_ms123": [("street", 0.75, 16.0, 1.7, 0.5, 0.0, 9.5, 24)],
    "gulden_spoor": [
        ("street", 0.5, 10.5, 1.7, 0.6, -8.0, 7.5, 18),
        ("east", -30.0, 6.0, 1.7, 4.0, -9.0, 7.0, 24),
    ],
    "gulden_spoor_gate": [("street", 0.25, 8.0, 1.7, 0.4, 0.0, 6.0, 18)],
    "albertpark_kiosk": [("path", 0.0, 0.0, 1.7, 0.0, 0.0, 4.2, 30)],
    "benoit_monument": [("square", 0.0, 0.0, 1.7, 0.0, 0.0, 1.4, 30)],
}


def _frame_for(bldg: dict) -> tuple[K.Frame, float]:
    ring = [tuple(p) for p in bldg["ring"]]
    e = K.front_edge(ring, tuple(bldg["landmark"]["anchor_xy"]))
    return e.frame(), e.length


def _shots(layout: dict, only: set[str] | None):
    for bldg in layout.get("buildings") or []:
        kind = (bldg.get("landmark") or {}).get("custom")
        if kind not in SHOTS or (only and kind not in only):
            continue
        if kind == "albertpark_kiosk":
            ring = [tuple(p) for p in bldg["ring"]]
            cx, cy = K.centroid(ring)
            tx, ty = bldg["landmark"]["params"].get("stairs_toward_xy") or (cx, cy - 1.0)
            ln = math.hypot(tx - cx, ty - cy) or 1.0
            ux, uy = (tx - cx) / ln, (ty - cy) / ln
            eye = (cx + ux * 17.0 - uy * 4.0, cy + uy * 17.0 + ux * 4.0, 1.7)
            yield kind, "path", eye, (cx, cy, 4.2), 30
            continue
        f, L = _frame_for(bldg)
        for name, a, d, z, ta, td, tz, lens in SHOTS[kind]:
            ea = a * L if abs(a) <= 1.5 else a
            ta2 = ta * L if abs(ta) <= 1.5 else ta
            yield kind, name, f.p(ea, d, z), f.p(ta2, td, tz), lens
    for node in layout.get("landmark_nodes") or []:
        kind = node.get("custom")
        if kind not in SHOTS or (only and kind not in only):
            continue
        x, y = node["x"], node["y"]
        fx, fy = node.get("facing_xy") or (x, y + 1)
        ln = math.hypot(fx - x, fy - y) or 1.0
        nx, ny = (fx - x) / ln, (fy - y) / ln
        yield kind, "square", (x + nx * 13.0 + ny * 4.0, y + ny * 13.0 - nx * 4.0, 1.7), (x, y, 1.4), 30


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default=str(ROOT / "output" / "antwerp_harmonie_layout.json"))
    ap.add_argument("--out", default=str(ROOT / "output" / "landmark_renders"))
    ap.add_argument("--tag", default="after")
    ap.add_argument("--only", default="")
    ap.add_argument("--res", type=int, default=1280)
    args = ap.parse_args(argv)
    layout = json.loads(Path(args.layout).read_text())
    only = {s for s in args.only.split(",") if s} or None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("LandmarkCam")
    cam_data.clip_end = 900
    cam = bpy.data.objects.new("LandmarkCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = args.res
    scene.render.resolution_y = int(args.res * 0.625)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 90
    for kind, name, eye, target, lens in _shots(layout, only):
        eye_v, tgt_v = Vector(eye), Vector(target)
        cam.location = eye_v
        cam.rotation_euler = (tgt_v - eye_v).to_track_quat("-Z", "Y").to_euler()
        cam_data.lens = lens
        path = out / f"{kind}_{name}_{args.tag}.jpg"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print("Wrote", path)


main()
