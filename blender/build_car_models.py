"""Street cars modelled on the 2025-26 Belgian new-car mix → ``viewer/cars/*.glb``.

Each body is lofted from the real model's published length / width / height / wheelbase
and a side profile traced from press photos, then detailed with that model's signature
lighting, grille, wheels, mirrors, flush handles, roof rails and Belgian plates.

Output is consumed unchanged by ``viewer/cars.js`` (traffic) and ``blender/cars_blender.py``
(parked cars): Y-up, length on Z with the nose toward +Z, wheels as separate
``wheel-*`` nodes pivoting on their axle. Materials are named ``car_*`` so the viewer can
repaint ``car_paint`` per car and drive ``car_headlight`` / ``car_taillight`` at night.

    blender -b --factory-startup -P blender/build_car_models.py
    blender -b --factory-startup -P blender/build_car_models.py -- --only model_y
    blender -b --factory-startup -P blender/build_car_models.py -- --preview /tmp/cars
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

REPO = Path(__file__).resolve().parents[1]
CARS_DIR = REPO / "viewer" / "cars"
FLEET_PATH = CARS_DIR / "fleet.json"

SLOTS = ("paint", "glass", "trim", "metal", "headlight", "taillight")

# Surface key -> (material slot, sRGB vertex colour). Slots that read vertex colour fold
# many finishes into one draw call.
KEYS = {
    "paint": ("paint", (1.0, 1.0, 1.0)),
    "glass": ("glass", (0.11, 0.135, 0.16)),
    "gloss": ("glass", (0.025, 0.026, 0.03)),
    "lens": ("glass", (0.2, 0.21, 0.23)),
    "trim": ("trim", (0.075, 0.075, 0.08)),
    "seam": ("trim", (0.012, 0.012, 0.014)),
    "well": ("trim", (0.025, 0.025, 0.028)),
    "tire": ("trim", (0.07, 0.07, 0.075)),
    "plate": ("trim", (0.94, 0.94, 0.92)),
    "plate_red": ("trim", (0.7, 0.06, 0.08)),
    "chrome": ("metal", (0.86, 0.87, 0.89)),
    "satin": ("metal", (0.5, 0.51, 0.53)),
    "rim": ("metal", (0.66, 0.67, 0.69)),
    "rim_dark": ("metal", (0.13, 0.135, 0.14)),
    "headlight": ("headlight", (1.0, 1.0, 1.0)),
    "taillight": ("taillight", (1.0, 1.0, 1.0)),
}

# Lower-body ring heights as fractions of sill→beltline, greenhouse as belt→roof edge.
FRACS = (0.0, 0.05, 0.12, 0.2, 0.3, 0.4, 0.5, 0.59, 0.67, 0.74, 0.8, 0.85, 0.89, 0.93, 0.965, 1.0)
GFRACS = (0.0, 0.07, 0.5, 0.93, 1.0)
SEG = ("under",) * 3 + ("side",) * 15 + ("ledge", "seal", "dlo", "dlo", "pillar", "pillar", "top", "top")
CAP_S = (0.82, 0.62, 0.42, 0.22, 0.0)
END_D = (0.004, 0.012, 0.025, 0.04, 0.06, 0.085, 0.12, 0.17, 0.23, 0.3, 0.38)

# Blender build frame is x forward / y left / z up; glTF wants the nose on -Y (→ +Z).
TO_EXPORT = Matrix.Rotation(-math.pi / 2, 4, "Z")


def R(end, k, z, y=(0.0, 9.0), depth=0.3, n=0.2, d=None):
    """Paint a band of body faces: ``end`` front/rear/side, ``z``/``y`` (|y|) in metres."""
    return {"end": end, "k": k, "z": z, "y": y, "depth": depth, "n": n, "d": d}


def P(end, k, ay, z, w, h, t=0.012, r=0.0, mirror=True, frame=None, sink=0.004):
    """Stick a rounded slab onto the front/rear fascia at |y| = ``ay``, height ``z``."""
    return {"end": end, "k": k, "ay": ay, "z": z, "w": w, "h": h, "t": t, "r": r,
            "mirror": mirror, "frame": frame, "sink": sink}


def Q(end, k, y, z, layer=0, mirror=True):
    """Lamp / grille / trim panel draped over the fascia curve: ``y`` = (|y| from, to);
    ``z`` = (bottom, top) or ((bottom, top) at y0, (bottom, top) at y1) for slanted units.
    Higher ``layer`` sits proud of lower ones."""
    za, zb = (z, z) if not isinstance(z[0], (tuple, list)) else z
    return {"end": end, "k": k, "y": y, "za": za, "zb": zb, "layer": layer, "mirror": mirror}


MODELS = [
    {
        "id": "model_y", "name": "Tesla Model Y", "gen": "2025 'Juniper'", "weight": 12,
        "L": 4.79, "W": 1.92, "wb": 2.89, "fo": 0.93,
        "wheel_r": 0.356, "rim_r": 0.2413, "tire_w": 0.255, "clr": 0.167,
        "lift": (0.2, 0.22), "corner": (0.46, 0.42), "bulge": (0.05, 0.03),
        "top": [(0, 0.6), (0.03, 0.7), (0.09, 0.775), (0.25, 0.85), (0.6, 0.925), (1.0, 0.985),
                (1.18, 1.01), (1.6, 1.3), (2.02, 1.57), (2.4, 1.624), (2.9, 1.61), (3.35, 1.55),
                (3.6, 1.49), (4.1, 1.24), (4.45, 1.11), (4.6, 1.085), (4.7, 1.05), (4.79, 0.98)],
        "belt": [(0, 0.57), (0.06, 0.7), (0.25, 0.82), (0.6, 0.9), (1.18, 0.975), (2.0, 1.0),
                 (3.0, 1.02), (3.7, 1.04), (4.3, 1.04), (4.6, 1.02), (4.79, 0.95)],
        "roof_hw": 0.63, "ws": (1.18, 2.02), "rs": (3.55, 4.42), "dlo": (1.22, 3.75),
        "b_pillar": 2.42, "seams": (1.36, 2.42, 3.36), "handles": (2.2, 3.18), "handle_k": "gloss",
        "roof": "gloss", "pillar": "gloss", "mirror": "paint",
        "rim_style": "aero", "spokes": 5, "rim_k": "rim_dark",
        "plate_f": 0.44, "plate_r": 0.66,
        "patches": [
            Q("front", "headlight", (0, 0.86), (0.565, 0.582), layer=1),
            Q("front", "lens", (0.5, 0.9), ((0.46, 0.535), (0.47, 0.545))),
            Q("front", "headlight", (0.6, 0.84), ((0.49, 0.503), (0.5, 0.513)), layer=1),
            Q("front", "trim", (0, 0.55), (0.38, 0.44)),
            Q("rear", "taillight", (0, 0.9), (0.94, 0.956), layer=1),
            Q("rear", "taillight", (0.55, 0.95), ((0.885, 0.965), (0.9, 0.965))),
            Q("rear", "taillight", (0.6, 0.82), (0.5, 0.518), layer=1),
            Q("rear", "trim", (0, 0.92), (0.39, 0.47)),
        ],
        "parts": [],
    },
    {
        "id": "bmw_x1", "name": "BMW X1", "gen": "U11 (2022-)", "weight": 12,
        "L": 4.5, "W": 1.845, "wb": 2.692, "fo": 0.86,
        "wheel_r": 0.352, "rim_r": 0.2286, "tire_w": 0.225, "clr": 0.2,
        "lift": (0.22, 0.2), "corner": (0.36, 0.3), "bulge": (0.04, 0.025),
        "top": [(0, 0.8), (0.03, 0.87), (0.1, 0.93), (0.3, 0.985), (0.7, 1.03), (1.0, 1.06),
                (1.1, 1.07), (1.5, 1.33), (1.88, 1.6), (2.2, 1.642), (3.0, 1.635), (3.65, 1.61),
                (3.9, 1.57), (4.28, 1.18), (4.4, 1.12), (4.47, 1.08), (4.5, 1.03)],
        "belt": [(0, 0.77), (0.05, 0.86), (0.3, 0.96), (1.1, 1.04), (2.0, 1.07), (3.0, 1.09),
                 (3.9, 1.12), (4.3, 1.1), (4.5, 1.0)],
        "roof_hw": 0.62, "ws": (1.1, 1.88), "rs": (3.88, 4.3), "dlo": (1.14, 3.85),
        "b_pillar": 2.25, "dlo_gaps": (3.4,), "seams": (1.27, 2.25, 3.14), "handles": (2.0, 2.95),
        "roof": "paint", "pillar": "gloss", "mirror": "paint", "cladding": True, "rocker": 0.15,
        "rails": "satin", "fin": True,
        "rim_style": "vspoke", "spokes": 5, "rim_k": "rim",
        "plate_f": 0.47, "plate_r": 0.78, "badge_r": 1.0,
        "patches": [
            Q("front", "lens", (0.38, 0.9), ((0.7, 0.785), (0.72, 0.79))),
            Q("front", "headlight", (0.42, 0.86), ((0.762, 0.776), (0.768, 0.782)), layer=1),
            Q("front", "headlight", (0.42, 0.44), (0.72, 0.776), layer=1),
            Q("front", "trim", (0, 0.55), (0.43, 0.5)),
            Q("front", "trim", (0.62, 0.86), (0.45, 0.6)),
            Q("rear", "taillight", (0.48, 1.0), ((0.93, 1.015), (0.95, 1.015))),
            Q("rear", "trim", (0, 0.92), (0.41, 0.52)),
            Q("rear", "satin", (0.2, 0.6), (0.43, 0.445), layer=1),
        ],
        "parts": [P("front", "gloss", 0.165, 0.66, 0.29, 0.26, t=0.03, r=0.07, frame=("chrome", 0.016))],
    },
    {
        "id": "vw_tiguan", "name": "Volkswagen Tiguan", "gen": "Mk3 (2024-)", "weight": 9,
        "L": 4.539, "W": 1.842, "wb": 2.681, "fo": 0.89,
        "wheel_r": 0.358, "rim_r": 0.2286, "tire_w": 0.235, "clr": 0.19,
        "lift": (0.2, 0.2), "corner": (0.42, 0.32), "bulge": (0.045, 0.025),
        "top": [(0, 0.79), (0.03, 0.86), (0.1, 0.93), (0.3, 0.99), (0.7, 1.04), (1.1, 1.075),
                (1.5, 1.33), (1.9, 1.61), (2.25, 1.659), (3.2, 1.65), (3.75, 1.62), (3.95, 1.58),
                (4.32, 1.17), (4.45, 1.1), (4.539, 1.04)],
        "belt": [(0, 0.76), (0.05, 0.85), (0.3, 0.965), (1.1, 1.05), (2.2, 1.07), (3.5, 1.1),
                 (4.0, 1.12), (4.35, 1.09), (4.539, 1.0)],
        "roof_hw": 0.64, "ws": (1.1, 1.9), "rs": (3.93, 4.33), "dlo": (1.15, 3.92),
        "b_pillar": 2.3, "dlo_gaps": (3.45,), "seams": (1.3, 2.3, 3.15), "handles": (2.05, 3.0),
        "roof": "paint", "pillar": "gloss", "seal": "satin", "mirror": "paint",
        "cladding": True, "rocker": 0.14, "rails": "satin", "fin": True,
        "rim_style": "multi", "spokes": 10, "spoke_w": 0.03, "rim_k": "rim",
        "plate_f": 0.5, "plate_r": 0.78, "badge_f": 0.73, "badge_r": 0.92,
        "patches": [
            Q("front", "gloss", (0, 0.9), (0.68, 0.78)),
            Q("front", "lens", (0.42, 0.9), (0.69, 0.778), layer=1),
            Q("front", "headlight", (0, 0.9), (0.752, 0.766), layer=2),
            Q("front", "trim", (0, 0.62), (0.42, 0.6)),
            Q("front", "trim", (0.68, 0.86), (0.44, 0.58)),
            Q("rear", "taillight", (0.55, 0.95), (0.94, 1.025)),
            Q("rear", "taillight", (0, 0.92), (0.985, 1.0), layer=1),
            Q("rear", "trim", (0, 0.92), (0.4, 0.5)),
        ],
        "parts": [],
    },
    {
        "id": "peugeot_208", "name": "Peugeot 208", "gen": "2024 facelift", "weight": 10,
        "L": 4.055, "W": 1.745, "wb": 2.54, "fo": 0.83,
        "wheel_r": 0.308, "rim_r": 0.2159, "tire_w": 0.205, "clr": 0.14,
        "lift": (0.18, 0.17), "corner": (0.38, 0.3), "bulge": (0.045, 0.02),
        "top": [(0, 0.64), (0.03, 0.71), (0.1, 0.77), (0.3, 0.83), (0.6, 0.875), (0.95, 0.915),
                (1.35, 1.15), (1.72, 1.38), (2.1, 1.43), (2.9, 1.415), (3.3, 1.37), (3.45, 1.33),
                (3.85, 0.99), (3.97, 0.975), (4.055, 0.93)],
        "belt": [(0, 0.61), (0.05, 0.7), (0.3, 0.8), (0.95, 0.895), (2.0, 0.94), (3.0, 0.98),
                 (3.6, 0.97), (4.055, 0.9)],
        "roof_hw": 0.58, "ws": (0.95, 1.72), "rs": (3.42, 3.85), "dlo": (0.99, 3.15),
        "b_pillar": 2.0, "seams": (1.16, 2.0, 2.98), "handles": (1.8, 2.78),
        "roof": "gloss", "pillar": "gloss", "mirror": "gloss", "fin": True,
        "rim_style": "multi", "spokes": 10, "spoke_w": 0.028, "rim_k": "rim",
        "plate_f": 0.385, "plate_r": 0.72, "badge_f": 0.55,
        "patches": [
            Q("front", "lens", (0.44, 0.86), ((0.56, 0.628), (0.58, 0.628))),
            Q("front", "headlight", (0.5, 0.82), ((0.598, 0.61), (0.608, 0.62)), layer=1),
            Q("front", "gloss", (0, 0.46), (0.42, 0.6)),
            Q("front", "trim", (0, 0.5), (0.33, 0.4)),
            Q("rear", "gloss", (0, 0.86), (0.8, 0.9)),
            Q("rear", "trim", (0, 0.86), (0.32, 0.4)),
        ],
        "parts": [P("front", "headlight", a, 0.47, 0.022, 0.2, t=0.01, r=0.005) for a in (0.6, 0.66, 0.72)]
        + [P("rear", "taillight", 0.72, z, 0.2, 0.016, t=0.01, r=0.004) for z in (0.835, 0.865, 0.895)],
    },
    {
        "id": "dacia_sandero", "name": "Dacia Sandero Stepway", "gen": "2023 facelift", "weight": 10,
        "L": 4.099, "W": 1.768, "wb": 2.604, "fo": 0.84,
        "wheel_r": 0.326, "rim_r": 0.2032, "tire_w": 0.205, "clr": 0.174,
        "lift": (0.19, 0.18), "corner": (0.36, 0.28), "bulge": (0.04, 0.02),
        "top": [(0, 0.7), (0.03, 0.77), (0.1, 0.83), (0.3, 0.885), (0.6, 0.925), (0.95, 0.965),
                (1.35, 1.2), (1.72, 1.46), (2.1, 1.5), (2.9, 1.49), (3.3, 1.45), (3.45, 1.41),
                (3.88, 1.03), (4.0, 1.01), (4.099, 0.97)],
        "belt": [(0, 0.67), (0.05, 0.76), (0.3, 0.86), (0.95, 0.945), (2.0, 0.98), (3.0, 1.0),
                 (3.6, 1.0), (4.099, 0.94)],
        "roof_hw": 0.6, "ws": (0.95, 1.72), "rs": (3.43, 3.88), "dlo": (0.99, 3.4),
        "b_pillar": 2.03, "dlo_gaps": (3.18,), "seams": (1.22, 2.03, 3.0), "handles": (1.85, 2.8),
        "roof": "paint", "pillar": "gloss", "seal": "trim", "mirror": "paint",
        "cladding": True, "rocker": 0.16, "clad_ends": (0.55, 0.52), "rails": "satin", "fin": True,
        "rim_style": "multi", "spokes": 10, "spoke_w": 0.028, "rim_k": "rim",
        "plate_f": 0.45, "plate_r": 0.76,
        "patches": [
            Q("front", "lens", (0.44, 0.86), (0.6, 0.69)),
            Q("front", "gloss", (0, 0.44), (0.58, 0.68)),
            Q("front", "trim", (0, 0.9), (0.37, 0.55)),
            Q("front", "satin", (0, 0.42), (0.38, 0.42), layer=1),
            Q("rear", "taillight", (0.55, 0.9), (0.86, 0.95)),
            Q("rear", "trim", (0, 0.9), (0.36, 0.52)),
            Q("rear", "satin", (0, 0.42), (0.38, 0.42), layer=1),
        ],
        "parts": [
            P("front", "headlight", 0.65, 0.672, 0.24, 0.014, t=0.012, r=0.005),
            P("front", "headlight", 0.52, 0.643, 0.016, 0.07, t=0.012, r=0.005),
            P("front", "chrome", 0.0, 0.63, 0.19, 0.045, t=0.014, r=0.01, mirror=False),
        ],
    },
    {
        "id": "kia_ev3", "name": "Kia EV3", "gen": "2024-", "weight": 8,
        "L": 4.3, "W": 1.85, "wb": 2.68, "fo": 0.84,
        "wheel_r": 0.334, "rim_r": 0.2159, "tire_w": 0.215, "clr": 0.174,
        "lift": (0.18, 0.2), "corner": (0.3, 0.24), "bulge": (0.03, 0.015),
        "top": [(0, 0.76), (0.03, 0.83), (0.1, 0.88), (0.3, 0.93), (0.7, 0.98), (1.05, 1.02),
                (1.45, 1.28), (1.85, 1.53), (2.2, 1.56), (3.3, 1.55), (3.85, 1.52), (4.0, 1.49),
                (4.22, 1.18), (4.28, 1.12), (4.3, 1.06)],
        "belt": [(0, 0.73), (0.05, 0.82), (0.3, 0.91), (1.05, 1.0), (2.2, 1.03), (3.4, 1.05),
                 (4.0, 1.06), (4.25, 1.06), (4.3, 1.0)],
        "roof_hw": 0.64, "ledge": 0.045, "ws": (1.05, 1.85), "rs": (3.98, 4.22), "dlo": (1.1, 3.75),
        "b_pillar": 2.25, "seams": (1.22, 2.25, 3.12), "handles": (2.05, 3.0),
        "roof": "gloss", "pillar": "gloss", "cpillar": "gloss", "mirror": "gloss",
        "cladding": True, "rocker": 0.17, "fin": True,
        "rim_style": "aero", "spokes": 6, "rim_k": "rim",
        "plate_f": 0.44, "plate_r": 0.72,
        "patches": [
            Q("front", "headlight", (0.25, 0.92), (0.728, 0.744), layer=1),
            Q("front", "trim", (0, 0.66), (0.37, 0.5)),
            Q("front", "trim", (0.68, 0.92), (0.37, 0.6)),
            Q("rear", "gloss", (0, 0.9), (0.95, 1.03)),
            Q("rear", "taillight", (0.76, 0.91), (0.72, 1.045), layer=1),
            Q("rear", "trim", (0, 0.92), (0.385, 0.5)),
        ],
        "parts": [P("front", "lens", 0.73, 0.63, 0.12, 0.2, t=0.014, r=0.02)]
        + [P("front", "headlight", 0.73, z, 0.09, 0.03, t=0.02, r=0.006) for z in (0.575, 0.63, 0.685)],
    },
    {
        "id": "bmw_5", "name": "BMW 5 Series / i5", "gen": "G60 (2023-)", "weight": 8,
        "L": 5.06, "W": 1.9, "wb": 2.995, "fo": 0.89,
        "wheel_r": 0.351, "rim_r": 0.2413, "tire_w": 0.245, "clr": 0.14,
        "lift": (0.2, 0.2), "corner": (0.4, 0.36), "bulge": (0.04, 0.03),
        "top": [(0, 0.69), (0.03, 0.76), (0.1, 0.81), (0.35, 0.865), (0.8, 0.915), (1.3, 0.96),
                (1.45, 0.975), (1.85, 1.22), (2.3, 1.47), (2.75, 1.515), (3.45, 1.5), (3.75, 1.44),
                (4.1, 1.22), (4.42, 1.05), (4.7, 1.035), (4.95, 1.03), (5.06, 0.98)],
        "belt": [(0, 0.66), (0.05, 0.75), (0.35, 0.845), (1.45, 0.955), (2.6, 0.99), (3.8, 1.01),
                 (4.42, 1.02), (4.9, 1.005), (5.06, 0.94)],
        "roof_hw": 0.62, "ws": (1.45, 2.3), "rs": (3.72, 4.42), "dlo": (1.5, 4.08),
        "b_pillar": 2.72, "dlo_gaps": (3.72,), "seams": (1.31, 2.72, 3.52), "handles": (2.45, 3.4),
        "roof": "paint", "pillar": "gloss", "seal": "chrome", "mirror": "paint", "fin": True,
        "rim_style": "vspoke", "spokes": 5, "rim_k": "rim",
        "plate_f": 0.425, "plate_r": 0.78, "badge_r": 0.94,
        "patches": [
            Q("front", "lens", (0.44, 0.93), ((0.6, 0.68), (0.62, 0.682))),
            Q("front", "headlight", (0.5, 0.9), ((0.664, 0.675), (0.668, 0.678)), layer=1),
            Q("front", "trim", (0, 0.6), (0.35, 0.45)),
            Q("front", "trim", (0.66, 0.9), (0.38, 0.52)),
            Q("rear", "taillight", (0.45, 0.96), ((0.9, 0.965), (0.91, 0.968))),
            Q("rear", "trim", (0, 0.92), (0.35, 0.45)),
            Q("rear", "chrome", (0.1, 0.7), (0.46, 0.47), layer=1),
        ],
        "parts": [
            P("front", "gloss", 0.2, 0.555, 0.34, 0.19, t=0.03, r=0.06, frame=("chrome", 0.014)),
            P("front", "headlight", 0.6, 0.642, 0.02, 0.06, t=0.014, r=0.005),
            P("front", "headlight", 0.78, 0.645, 0.02, 0.06, t=0.014, r=0.005),
        ],
    },
    {
        "id": "model_3", "name": "Tesla Model 3", "gen": "2024 'Highland'", "weight": 6,
        "L": 4.72, "W": 1.85, "wb": 2.875, "fo": 0.86,
        "wheel_r": 0.334, "rim_r": 0.2286, "tire_w": 0.235, "clr": 0.138,
        "lift": (0.19, 0.2), "corner": (0.45, 0.4), "bulge": (0.05, 0.03),
        "top": [(0, 0.58), (0.03, 0.66), (0.1, 0.725), (0.3, 0.79), (0.7, 0.855), (1.05, 0.9),
                (1.15, 0.915), (1.6, 1.18), (2.05, 1.415), (2.45, 1.441), (2.9, 1.43), (3.2, 1.39),
                (3.6, 1.27), (4.2, 1.03), (4.45, 0.99), (4.62, 0.995), (4.72, 0.93)],
        "belt": [(0, 0.55), (0.05, 0.65), (0.3, 0.77), (1.15, 0.895), (2.4, 0.93), (3.5, 0.96),
                 (4.2, 0.975), (4.6, 0.97), (4.72, 0.9)],
        "roof_hw": 0.6, "ledge": 0.045, "ws": (1.15, 2.05), "rs": (3.1, 4.22), "dlo": (1.2, 3.62),
        "b_pillar": 2.45, "seams": (1.27, 2.45, 3.3), "handles": (2.25, 3.15), "handle_k": "gloss",
        "roof": "gloss", "pillar": "gloss", "mirror": "paint",
        "rim_style": "multi", "spokes": 10, "spoke_w": 0.045, "rim_k": "rim_dark",
        "plate_f": 0.43, "plate_r": 0.7,
        "patches": [
            Q("front", "lens", (0.5, 0.9), ((0.53, 0.568), (0.548, 0.572))),
            Q("front", "headlight", (0.56, 0.88), ((0.553, 0.563), (0.56, 0.568)), layer=1),
            Q("front", "trim", (0, 0.55), (0.34, 0.4)),
            Q("front", "trim", (0.62, 0.82), (0.34, 0.42)),
            Q("rear", "taillight", (0.5, 0.92), (0.84, 0.915)),
            Q("rear", "trim", (0, 0.9), (0.345, 0.42)),
        ],
        "parts": [],
    },
    {
        "id": "renault_5", "name": "Renault 5 E-Tech", "gen": "2024-", "weight": 7,
        "L": 3.922, "W": 1.774, "wb": 2.54, "fo": 0.76,
        "wheel_r": 0.336, "rim_r": 0.2286, "tire_w": 0.195, "clr": 0.15,
        "lift": (0.15, 0.15), "corner": (0.28, 0.22), "bulge": (0.03, 0.015),
        "top": [(0, 0.74), (0.03, 0.81), (0.1, 0.86), (0.3, 0.9), (0.6, 0.93), (0.92, 0.965),
                (1.3, 1.22), (1.66, 1.46), (2.0, 1.498), (2.9, 1.49), (3.35, 1.46), (3.5, 1.43),
                (3.76, 1.08), (3.86, 1.03), (3.922, 0.99)],
        "belt": [(0, 0.71), (0.05, 0.79), (0.3, 0.875), (0.92, 0.945), (2.0, 0.98), (3.0, 1.0),
                 (3.6, 1.01), (3.85, 0.99), (3.922, 0.94)],
        "roof_hw": 0.6, "ws": (0.92, 1.66), "rs": (3.48, 3.76), "dlo": (0.97, 3.25),
        "b_pillar": 1.98, "seams": (1.13, 1.98, 2.86), "handles": (1.75,), "handle_k": "gloss",
        "roof": "paint", "pillar": "gloss", "mirror": "gloss",
        "cladding": True, "rocker": 0.12, "fin": True,
        "rim_style": "aero", "spokes": 6, "rim_k": "rim",
        "plate_f": 0.385, "plate_r": 0.66, "badge_f": 0.67,
        "patches": [
            Q("front", "lens", (0.46, 0.83), (0.6, 0.72)),
            Q("front", "headlight", (0.48, 0.81), (0.69, 0.706), layer=1),
            Q("front", "gloss", (0, 0.46), (0.62, 0.72)),
            Q("front", "trim", (0, 0.85), (0.31, 0.45)),
            Q("rear", "taillight", (0.62, 0.86), (0.74, 0.96)),
            Q("rear", "trim", (0, 0.86), (0.31, 0.42)),
        ],
        "parts": [],
    },
    {
        "id": "transit_custom", "name": "Ford Transit Custom", "gen": "2023-", "weight": 8,
        "L": 5.05, "W": 1.99, "wb": 3.1, "fo": 0.98,
        "wheel_r": 0.343, "rim_r": 0.2032, "tire_w": 0.215, "clr": 0.175,
        "lift": (0.16, 0.14), "corner": (0.35, 0.12), "bulge": (0.04, 0.01),
        "top": [(0, 0.98), (0.03, 1.04), (0.1, 1.08), (0.3, 1.115), (0.6, 1.14), (0.8, 1.155),
                (1.25, 1.53), (1.68, 1.9), (1.95, 1.97), (4.9, 1.97), (5.0, 1.955), (5.05, 1.93)],
        "belt": [(0, 0.95), (0.05, 1.03), (0.3, 1.1), (0.8, 1.14), (2.0, 1.16), (5.0, 1.16), (5.05, 1.12)],
        "roof_hw": 0.9, "ledge": 0.03, "shoulder": 0.01, "glass_bulge": 0.01, "roof_crown": 0.03,
        "ws": (0.8, 1.7), "rs": (5.05, 5.05), "dlo": (0.86, 1.92),
        "seams": (1.4, 1.96, 3.05), "handles": (1.8, 2.15), "handle_k": "trim",
        "roof": "paint", "pillar": "paint", "mirror": "trim", "mirror_size": (0.14, 0.24, 0.26),
        "cladding": True, "rocker": 0.12, "clad_ends": (0.62, 0.6), "fin": True,
        "rim_style": "cover", "spokes": 8, "rim_k": "satin",
        "plate_f": 0.45, "plate_r": 0.7, "badge_f": 0.86,
        "rects": [R("side", "trim", (0.5, 0.58), d=(1.4, 4.65), n=0.5)],
        "patches": [
            Q("front", "gloss", (0, 0.62), (0.66, 0.95)),
            Q("front", "lens", (0.56, 0.95), (0.86, 0.965), layer=1),
            Q("front", "headlight", (0, 0.92), (0.935, 0.95), layer=2),
            Q("front", "trim", (0, 0.96), (0.34, 0.62)),
            Q("rear", "taillight", (0.84, 0.975), (0.85, 1.45)),
            Q("rear", "glass", (0.07, 0.8), (1.32, 1.8)),
            Q("rear", "trim", (0, 0.99), (0.32, 0.6)),
        ],
        "parts": [P("rear", "seam", 0.0, 1.06, 0.012, 1.48, t=0.006, mirror=False)],
    },
]


# --------------------------------------------------------------------------- maths


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def smoothstep(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def pchip(pts):
    """Monotone cubic through ``(x, y)`` points; clamps outside the range."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    dl = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = dl[0], dl[-1]
    for i in range(1, n - 1):
        if dl[i - 1] * dl[i] <= 0:
            m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / dl[i - 1] + w2 / dl[i])

    def f(x: float) -> float:
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = min(bisect.bisect_right(xs, x) - 1, n - 2)
        t = (x - xs[i]) / h[i]
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i]
                + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])

    return f


def newell(pts) -> Vector:
    n = Vector((0.0, 0.0, 0.0))
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n.normalized() if n.length > 1e-12 else n


# --------------------------------------------------------------------------- mesh builder


class MB:
    def __init__(self):
        self.v: list[Vector] = []
        self.f: list[tuple[int, ...]] = []
        self.k: list[str] = []
        self.sm: list[bool] = []

    def add(self, p) -> int:
        self.v.append(Vector(p))
        return len(self.v) - 1

    def face(self, idx, key, smooth=True):
        self.f.append(tuple(idx))
        self.k.append(key)
        self.sm.append(smooth)

    def hexa(self, c, key, smooth=False):
        """Eight corners indexed by bits (a, b, c); faces oriented away from the centroid."""
        ids = [self.add(p) for p in c]
        cen = sum((Vector(p) for p in c), Vector()) / 8
        for bit in (4, 2, 1):
            others = [b for b in (4, 2, 1) if b != bit]
            for val in (0, bit):
                quad = [val, val + others[0], val + others[0] + others[1], val + others[1]]
                pts = [Vector(c[q]) for q in quad]
                fc = sum(pts, Vector()) / 4
                if newell(pts).dot(fc - cen) < 0:
                    quad.reverse()
                self.face([ids[q] for q in quad], key, smooth)

    def beam(self, p0, p1, side, w0, w1, t, key):
        ax = (p1 - p0).normalized()
        up = ax.cross(side).normalized()
        c = []
        for p, w in ((p0, w0), (p1, w1)):
            for sx in (-0.5, 0.5):
                for sy in (-0.5, 0.5):
                    c.append(p + side * (sx * w) + up * (sy * t))
        self.hexa(c, key)

    def rbox(self, center, size, r, key, rot=None, smooth=True):
        """Rounded box (corner radius ``r``) as a cube grid projected onto the rounded shell."""
        rot = rot or Matrix.Identity(3)
        half = [s * 0.5 for s in size]
        r = max(0.0, min(r, *half))
        inner = [h - r for h in half]
        axes = []
        fine = r >= 0.025
        for a in range(3):
            if r > 1e-5 and inner[a] > 1e-5:
                axes.append([-half[a], -inner[a] - 0.6 * r, -inner[a], inner[a], inner[a] + 0.6 * r, half[a]]
                            if fine else [-half[a], -inner[a], inner[a], half[a]])
            elif r > 1e-5:
                axes.append([-half[a], -0.6 * r, 0.6 * r, half[a]] if fine else [-half[a], half[a]])
            else:
                axes.append([-half[a], half[a]])
        c = Vector(center)
        for a in range(3):
            u, v = (a + 1) % 3, (a + 2) % 3
            for sign in (-1, 1):
                uu, vv = (u, v) if sign > 0 else (v, u)
                gu, gv = axes[uu], axes[vv]
                grid = []
                for x in gu:
                    row = []
                    for y in gv:
                        q = [0.0, 0.0, 0.0]
                        q[a], q[uu], q[vv] = sign * half[a], x, y
                        cin = Vector([max(-inner[i], min(inner[i], q[i])) for i in range(3)])
                        off = Vector(q) - cin
                        p = cin + (off.normalized() * r if r > 1e-5 and off.length > 1e-9 else off)
                        row.append(self.add(c + rot @ p))
                    grid.append(row)
                for i in range(len(gu) - 1):
                    for j in range(len(gv) - 1):
                        self.face([grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]], key, smooth)

    def lathe(self, profile, key, segs=30, smooth=True):
        """Revolve ``(radius, y)`` points around the y axis (normals follow profile × θ)."""
        rings = []
        for r, y in profile:
            if r < 1e-6:
                rings.append([self.add((0.0, y, 0.0))] * segs)
            else:
                rings.append([self.add((r * math.cos(2 * math.pi * i / segs), y,
                                        r * math.sin(2 * math.pi * i / segs))) for i in range(segs)])
        for a, b in zip(rings, rings[1:]):
            for i in range(segs):
                j = (i + 1) % segs
                quad = [a[i], b[i], b[j], a[j]]
                uniq = list(dict.fromkeys(quad))
                if len(uniq) >= 3:
                    self.face(uniq, key, smooth)

    def mirrored_y(self) -> "MB":
        out = MB()
        out.v = [Vector((p.x, -p.y, p.z)) for p in self.v]
        out.f = [tuple(reversed(f)) for f in self.f]
        out.k = list(self.k)
        out.sm = list(self.sm)
        return out


# --------------------------------------------------------------------------- car geometry


class Car:
    def __init__(self, s: dict):
        self.s = s
        self.L = s["L"]
        self.hw0 = s["W"] / 2
        self.top = pchip(s["top"])
        self.belt_f = pchip(s["belt"])
        self.axles = (s["fo"], s["fo"] + s["wb"])
        self.R = s["wheel_r"]
        self.ra = self.R + 0.04
        self.bvh: BVHTree | None = None

    def hw(self, d: float) -> float:
        rf, rr = self.s["corner"]
        e = None
        if d < rf:
            e, rad = rf - d, rf
        elif self.L - d < rr:
            e, rad = rr - (self.L - d), rr
        if e is None:
            return self.hw0
        return self.hw0 - rad + math.sqrt(max(0.0, rad * rad - e * e))

    def zb_c(self, d: float) -> float:
        lf, lr = self.s["lift"]
        z = self.s["clr"]
        if d < 0.45:
            z += lf * (1 - d / 0.45) ** 2
        if self.L - d < 0.45:
            z += lr * (1 - (self.L - d) / 0.45) ** 2
        return z

    def zarch(self, d: float) -> float:
        best = 0.0
        for a in self.axles:
            dx = d - a
            if abs(dx) < self.ra:
                best = max(best, self.R + math.sqrt(self.ra * self.ra - dx * dx))
        return best

    def zs(self, d: float) -> float:
        return max(self.zb_c(d), self.zarch(d))

    def belt(self, d: float) -> float:
        return max(self.belt_f(d), self.zs(d) + 0.12)

    def side_y(self, hw: float, f: float, zrel: float) -> float:
        tuck = 0.055 * max(0.0, 1 - zrel / 0.26) ** 2
        sh = self.s.get("shoulder", 0.025) * max(0.0, (f - 0.8) / 0.2) ** 2
        return hw - tuck - sh

    def rake(self, end: str, d: float, z: float) -> float:
        """How far the nose / tail is pulled in at height ``z`` so fascias lean instead of
        standing as vertical slabs (fades out over the first 0.6 m)."""
        idx = 0 if end == "front" else 1
        amount = self.s.get("rake", (0.09, 0.06))[idx]
        depth = d if end == "front" else self.L - d
        w = max(0.0, 1 - depth / 0.6) ** 2
        if w <= 0 or amount <= 0:
            return 0.0
        de = 0.0 if end == "front" else self.L
        z0, z1 = self.zb_c(de), self.top(de)
        u = (z - (z0 + 0.42 * (z1 - z0))) / max(0.05, (z1 - z0) / 2)
        return amount * min(1.5, u * u) * w

    def body_y(self, d: float, z: float) -> float:
        zs, belt = self.zs(d), self.belt(d)
        f = min(1.0, max(0.0, (z - zs) / max(1e-3, belt - zs)))
        return self.side_y(self.hw(d), f, z - self.zb_c(d))

    def ring(self, d: float):
        s = self.s
        hw, zbc, zs = self.hw(d), self.zb_c(d), self.zs(d)
        belt = self.belt(d)
        top = max(self.top(d), belt + 0.004)
        well = max(0.02, hw - 0.34)
        pts = [(0.0, zbc), (well, zbc), (well, zs)]
        for f in FRACS:
            z = zs + f * (belt - zs)
            pts.append((self.side_y(hw, f, z - zbc), z))
        g = smoothstep(0.06, 0.3, top - belt)
        hw_r = lerp(hw - 0.1, min(s["roof_hw"], hw - 0.1), g)
        crown = lerp(s.get("bonnet_crown", 0.035), s.get("roof_crown", 0.045), g)
        ce = max(0.002, min(crown, top - belt - 0.006))
        ze = top - ce
        ledge, bul = s.get("ledge", 0.05), s.get("glass_bulge", 0.025)
        for sg in GFRACS:
            z = belt + 0.004 + sg * (ze - belt - 0.004)
            pts.append((lerp(hw - ledge, hw_r, sg) + bul * math.sin(math.pi * sg) * g, z))
        pts += [(hw_r - 0.06, ze + ce * 0.4), (hw_r * 0.5, ze + ce * 0.88), (0.0, top)]
        return pts

    def stations(self):
        s, L = self.s, self.L
        n = max(8, round(L / 0.14))
        ds = {L * i / n for i in range(n + 1)}
        for e in END_D:
            ds |= {e, L - e}
        for a in self.axles:
            ds.add(a)
            for k in (0.3, 0.6, 0.82, 0.94):
                ds |= {a + k * self.ra, a - k * self.ra}
            for off in (self.ra - 0.004, self.ra + 0.004, self.ra + 0.08):
                ds |= {a + off, a - off}
        for sd in s.get("seams", ()):
            ds |= {sd - 0.007, sd + 0.007}
        if s.get("b_pillar") is not None:
            bw = s.get("b_w", 0.09) / 2
            ds |= {s["b_pillar"] - bw, s["b_pillar"] + bw}
        for gd in s.get("dlo_gaps", ()):
            ds |= {gd - 0.03, gd + 0.03}
        for pair in (s["ws"], s["rs"], s["dlo"]):
            ds |= set(pair)
        for r in s.get("rects", ()):
            if r.get("d"):
                ds |= set(r["d"])
        out = sorted(d for d in ds if 0.0 <= d <= L)
        merged = [out[0]]
        for d in out[1:]:
            if d - merged[-1] > 0.003:
                merged.append(d)
        merged[0], merged[-1] = 0.0, L
        return merged

    def snap(self, pos: Vector, nrm: Vector) -> tuple[Vector, Vector]:
        """Move an analytic surface point onto the faceted body (the loft pulls in near the
        greenhouse and end caps, where the analytic fascia would float or sink)."""
        if self.bvh is None:
            return pos, nrm
        hit, hn, _i, _dist = self.bvh.ray_cast(pos + nrm * 0.2, -nrm, 0.4)
        if hit is None:
            return pos, nrm
        if hn.dot(nrm) < 0:
            hn = -hn
        if hn.dot(nrm) < 0.35:
            return pos, nrm
        return hit, hn.normalized()

    def fascia_depth(self, end: str, ay: float) -> float:
        rad = self.s["corner"][0 if end == "front" else 1]
        u = ay - (self.hw0 - rad)
        if u <= 0:
            return 0.0
        u = min(u, rad * 0.999)
        return rad - math.sqrt(rad * rad - u * u)

    def fascia(self, end: str, ay: float, z: float):
        """Point on the front/rear fascia at |y| = ay (left side) and its outward plan normal."""
        idx = 0 if end == "front" else 1
        rad = self.s["corner"][idx]
        bulge = self.s["bulge"][idx]
        flat = self.hw0 - rad
        if ay <= flat:
            dx = bulge * (1 - (ay / max(flat, 1e-3)) ** 2)
            yaw = math.atan(2 * bulge * ay / max(flat, 1e-3) ** 2)
            depth = -dx
        else:
            u = min(ay - flat, rad * 0.999)
            e = math.sqrt(rad * rad - u * u)
            depth = rad - e
            yaw = math.atan2(u, e)
        d = depth if end == "front" else self.L - depth
        dc = min(max(d, 0.0), self.L)
        zrel = z - self.zb_c(dc)
        sink = 0.055 * max(0.0, 1 - zrel / 0.26) ** 2
        if ay > flat:
            zs, belt = self.zs(dc), self.belt(dc)
            f = (z - zs) / max(1e-3, belt - zs)
            sink += self.s.get("shoulder", 0.025) * max(0.0, (f - 0.8) / 0.2) ** 2
        rk = self.rake(end, dc, z)
        x = self.L / 2 - d - rk if end == "front" else self.L / 2 - d + rk
        nrm = Vector((math.cos(yaw), math.sin(yaw), 0.0))
        if end == "rear":
            nrm.x = -nrm.x
        pos = Vector((x, ay, z)) - nrm * sink
        return pos, nrm


def classify(car: Car, d, ay, z, n, seg, cap):
    s = car.s
    if seg == "under":
        return "well"
    for r in s.get("rects", ()):
        end = r["end"]
        if end == "front":
            depth, facing = d, n.x
        elif end == "rear":
            depth, facing = car.L - d, -n.x
        else:
            depth, facing = 0.0, abs(n.y)
        if depth > r["depth"] or facing < r["n"]:
            continue
        if r["d"] and not r["d"][0] <= d <= r["d"][1]:
            continue
        if r["z"][0] <= z <= r["z"][1] and r["y"][0] <= ay <= r["y"][1]:
            return r["k"]
    if cap:
        return "paint"
    ws0, ws1 = s["ws"]
    rs0, rs1 = s["rs"]
    cabin_end = max(rs1, ws1)
    if seg == "top":
        if ws0 <= d <= ws1 and ay < s["roof_hw"] + 0.04:
            return "glass"
        if rs0 <= d <= rs1 and ay < s["roof_hw"] - 0.05:
            return "glass"
        if ws0 <= d <= ws1 or rs0 <= d <= rs1:
            return s.get("pillar", "paint")
        if ws1 < d < rs0:
            return s.get("roof", "paint")
    elif seg == "pillar":
        if ws0 <= d <= cabin_end:
            return s.get("pillar", "paint")
    elif seg in ("dlo", "seal"):
        d0, d1 = s["dlo"]
        if d0 <= d <= d1:
            b = s.get("b_pillar")
            if b is not None and abs(d - b) <= s.get("b_w", 0.09) / 2:
                return "gloss"
            if any(abs(d - g) <= 0.03 for g in s.get("dlo_gaps", ())):
                return "gloss"
            return "glass" if seg == "dlo" else s.get("seal", "gloss")
        if seg == "dlo" and ws0 <= d <= cabin_end:
            return s.get("cpillar", "paint")
    elif seg == "side":
        zs, belt = car.zs(d), car.belt(d)
        for sd in s.get("seams", ()):
            if abs(d - sd) < 0.0072 and zs + 0.03 < z < belt - 0.015:
                return "seam"
    return "paint"


def build_body(car: Car, mb: MB) -> None:
    s, L = car.s, car.L
    st = []
    pr, br = car.ring(L), s["bulge"][1]
    for sc in reversed(CAP_S):
        st.append((-L / 2 - br * (1 - sc * sc), [(y * sc, z) for y, z in pr], L, True))
    for d in reversed(car.stations()):
        st.append((L / 2 - d, car.ring(d), d, False))
    pf, bf = car.ring(0.0), s["bulge"][0]
    for sc in CAP_S:
        st.append((L / 2 + bf * (1 - sc * sc), [(y * sc, z) for y, z in pf], 0.0, True))

    rings = []
    for x, pts, d, _cap in st:
        pts = pts + [(-y, z) for y, z in reversed(pts[1:-1])]
        ring = []
        for y, z in pts:
            px = x - car.rake("front", d, z) + car.rake("rear", d, z)
            ring.append(mb.add((px, y, z)))
        rings.append(ring)
    nr = len(rings[0])
    nh = len(SEG)
    for i in range(len(st) - 1):
        cap = st[i][3] or st[i + 1][3]
        dn = 0.5 * (st[i][2] + st[i + 1][2])
        a, b = rings[i], rings[i + 1]
        for j in range(nr):
            k = (j + 1) % nr
            quad = [a[j], a[k], b[k], b[j]]
            pts = [mb.v[q] for q in quad]
            c = sum(pts, Vector()) / 4
            seg = SEG[j] if j < nh else SEG[2 * nh - 1 - j]
            key = classify(car, dn, abs(c.y), c.z, newell(pts), seg, cap)
            mb.face(quad, key)


def emit_shell(mb: MB, surf, nrms, off: float, key: str) -> None:
    """Grid of surface points lifted ``off`` along their normals, walled back into the body."""
    ni, nj = len(surf), len(surf[0])
    outer = [[mb.add(surf[i][j] + nrms[i][j] * off) for j in range(nj)] for i in range(ni)]
    inner = [[mb.add(surf[i][j] - nrms[i][j] * 0.006) for j in range(nj)] for i in range(ni)]

    def emit(quad, ref, smooth=True):
        if newell([mb.v[q] for q in quad]).dot(ref) < 0:
            quad = quad[::-1]
        mb.face(quad, key, smooth)

    for i in range(ni - 1):
        for j in range(nj - 1):
            emit([outer[i][j], outer[i + 1][j], outer[i + 1][j + 1], outer[i][j + 1]], nrms[i][j])
    # Each boundary edge with the grid row just inside it, so walls face away from the panel.
    edges = [([(i, 0) for i in range(ni)], (0, 1)), ([(i, nj - 1) for i in range(ni)], (0, -1)),
             ([(0, j) for j in range(nj)], (1, 0)), ([(ni - 1, j) for j in range(nj)], (-1, 0))]
    for edge, (di, dj) in edges:
        for (i, j), (i2, j2) in zip(edge, edge[1:]):
            quad = [outer[i][j], outer[i2][j2], inner[i2][j2], inner[i][j]]
            mid = (mb.v[outer[i][j]] + mb.v[outer[i2][j2]]) / 2
            ins = (mb.v[outer[i + di][j + dj]] + mb.v[outer[i2 + di][j2 + dj]]) / 2
            emit(quad, mid - ins, smooth=False)


def add_patch(car: Car, mb: MB, p: dict) -> None:
    """Lamp / panel shell lofted over the analytic fascia curve."""
    y0, y1 = p["y"]
    y1 = min(y1, car.hw0 - 0.004)
    if y1 <= y0:
        return
    zbot = car.zb_c(0.0 if p["end"] == "front" else car.L)
    za, zb = p["za"], p["zb"]
    to_bottom = min(za[0], zb[0]) - zbot < 0.03
    ny = max(2, int((y1 - y0) / 0.035) + 1)
    nz = 3
    for sg in ((1, -1) if p["mirror"] else (1,)):
        surf, nrms = [], []
        for i in range(ny):
            t = i / (ny - 1)
            ay = lerp(y0, y1, t)
            z0, z1 = lerp(za[0], zb[0], t), lerp(za[1], zb[1], t)
            if to_bottom:
                d = car.fascia_depth(p["end"], ay)
                z0 = car.zb_c(d if p["end"] == "front" else car.L - d) - 0.015
            rs, rn = [], []
            for j in range(nz):
                pos, nrm = car.fascia(p["end"], ay, lerp(z0, z1, j / (nz - 1)))
                pos.y *= sg
                nrm.y *= sg
                pos, nrm = car.snap(pos, nrm)
                rs.append(pos)
                rn.append(nrm)
            surf.append(rs)
            nrms.append(rn)
        emit_shell(mb, surf, nrms, 0.005 + 0.004 * p["layer"], p["k"])


def add_side_strip(car: Car, mb: MB, rows, key: str, off: float = 0.01) -> None:
    """Panel draped on the body side; ``rows`` = [(d_in, z_in, d_out, z_out), ...]."""
    for sg in (1, -1):
        surf, nrms = [], []
        for d0, z0, d1, z1 in rows:
            rs, rn = [], []
            for j in range(3):
                d, z = lerp(d0, d1, j / 2), lerp(z0, z1, j / 2)
                x = car.L / 2 - d - car.rake("front", d, z) + car.rake("rear", d, z)
                rs.append(Vector((x, sg * car.body_y(d, z), z)))
                rn.append(Vector((0.0, float(sg), 0.0)))
            surf.append(rs)
            nrms.append(rn)
        emit_shell(mb, surf, nrms, off, key)


def add_cladding(car: Car, mb: MB) -> None:
    """Black arch flares and sill panels (crossovers, vans) as smooth strips."""
    s = car.s
    w, rocker = 0.075, s.get("rocker", 0.14)
    for a in car.axles:
        rows = []
        lo_f, lo_r = car.zb_c(a - car.ra) - 0.01, car.zb_c(a + car.ra) - 0.01
        for k in range(4):
            z = lerp(lo_f, car.R, k / 3)
            rows.append((a - car.ra + 0.01, z, a - car.ra - w, z))
        for k in range(1, 18):
            th = math.pi * k / 18
            c, sn = math.cos(th), math.sin(th)
            rows.append((a - (car.ra - 0.01) * c, car.R + (car.ra - 0.01) * sn,
                         a - (car.ra + w) * c, car.R + (car.ra + w) * sn))
        for k in range(4):
            z = lerp(car.R, lo_r, k / 3)
            rows.append((a + car.ra - 0.01, z, a + car.ra + w, z))
        add_side_strip(car, mb, rows, "trim")
    rf, rr = s["corner"]
    spans = ((rf * 0.9, car.axles[0] - car.ra), (car.axles[0] + car.ra, car.axles[1] - car.ra),
             (car.axles[1] + car.ra, car.L - rr * 0.9))
    ends = s.get("clad_ends")
    for n, (d0, d1) in enumerate(spans):
        k = max(2, int((d1 - d0) / 0.1) + 1)
        rows = []
        for i in range(k):
            d = lerp(d0, d1, i / (k - 1))
            zb = car.zb_c(d)
            top = zb + rocker
            if ends and n == 0:
                top = lerp(ends[0], top, smoothstep(d0, d1, d))
            elif ends and n == 2:
                top = lerp(top, ends[1], smoothstep(d0, d1, d))
            rows.append((d, top, d, zb - 0.015))
        add_side_strip(car, mb, rows, "trim")


def add_parts(car: Car, mb: MB) -> None:
    s, L = car.s, car.L
    car.bvh = BVHTree.FromPolygons(mb.v, mb.f)
    for p in s.get("patches", ()):
        add_patch(car, mb, p)
    if s.get("cladding"):
        add_cladding(car, mb)
    for p in s.get("parts", ()):
        sides = (1, -1) if p["mirror"] and p["ay"] > 1e-3 else (1,)
        for sg in sides:
            pos, nrm = car.fascia(p["end"], p["ay"], p["z"])
            yaw = math.atan2(nrm.y, nrm.x)
            if sg < 0:
                pos.y, yaw = -pos.y, -yaw
            rot = Matrix.Rotation(yaw, 3, "Z")
            out = Vector((math.cos(yaw), math.sin(yaw), 0.0))
            ctr = pos + out * (p["t"] / 2 - p["sink"])
            mb.rbox(ctr, (p["t"], p["w"], p["h"]), p["r"], p["k"], rot)
            if p["frame"]:
                fk, m = p["frame"]
                mb.rbox(ctr - out * 0.006, (p["t"] * 0.7, p["w"] + 2 * m, p["h"] + 2 * m),
                        p["r"] + m, fk, rot)

    for end, z, badge in (("front", s.get("plate_f"), s.get("badge_f")), ("rear", s.get("plate_r"), s.get("badge_r"))):
        if z:
            pos, nrm = car.fascia(end, 0.0, z)
            mb.rbox(pos + nrm * 0.004, (0.012, 0.52, 0.11), 0.006, "plate", smooth=False)
            mb.rbox(pos + nrm * 0.011, (0.004, 0.4, 0.052), 0.0, "plate_red", smooth=False)
        if badge:
            pos, nrm = car.fascia(end, 0.0, badge)
            mb.rbox(pos + nrm * 0.006, (0.014, 0.085, 0.085), 0.03, "chrome")

    # Door mirrors on the door skin just behind the A-pillar base.
    dm = s["ws"][0] + 0.16
    zm = car.belt(dm) + 0.1
    hy = car.hw(dm)
    mx, my, mz = s.get("mirror_size", (0.12, 0.19, 0.13))
    for sg in (1, -1):
        x = L / 2 - dm
        mb.beam(Vector((x + 0.01, sg * (hy - 0.1), zm - 0.06)), Vector((x - 0.01, sg * (hy - 0.03), zm - 0.03)),
                Vector((1, 0, 0)), 0.07, 0.05, 0.03, "trim")
        hc = Vector((x, sg * (hy - 0.06 + my / 2), zm))
        mb.rbox(hc, (mx, my, mz), min(mx, mz) * 0.35, s.get("mirror", "paint"))
        mb.rbox(hc + Vector((-mx / 2 - 0.002, 0, 0)), (0.006, my * 0.8, mz * 0.72), 0.01, "chrome")

    hk = s.get("handle_k", "paint")
    for dh in s.get("handles", ()):
        zh = car.belt(dh) - 0.075
        yh = car.body_y(dh, zh)
        for sg in (1, -1):
            mb.rbox((L / 2 - dh, sg * (yh + 0.003), zh), (0.16, 0.016, 0.028), 0.007, hk)

    if s.get("rails"):
        d0, d1 = s["ws"][1] + 0.12, s["rs"][0] - 0.05
        k = max(3, int((d1 - d0) / 0.12))
        for sg in (1, -1):
            prev = None
            for i in range(k + 1):
                d = lerp(d0, d1, i / k)
                pts = car.ring(d)
                y, z = pts[-3]
                cur = Vector((L / 2 - d, sg * (y - 0.005), z + 0.045))
                if prev is not None:
                    mb.beam(prev, cur, Vector((0, 1, 0)), 0.03, 0.03, 0.03, s["rails"])
                prev = cur
            for d in (d0 + 0.04, d1 - 0.04):
                y, z = car.ring(d)[-3]
                mb.rbox((L / 2 - d, sg * (y - 0.005), z + 0.02), (0.06, 0.028, 0.05), 0.01, "trim")

    if s.get("fin"):
        df = s["rs"][0] - 0.14
        mb.rbox((L / 2 - df, 0.0, car.top(df) + 0.025), (0.16, 0.05, 0.06), 0.022, "gloss")


def build_wheel(car: Car) -> MB:
    s = car.s
    mb = MB()
    R_, rr, h = s["wheel_r"], s["rim_r"], s["tire_w"] / 2
    mb.lathe([(rr * 0.97, -h * 0.78), (rr + 0.012, -h * 0.93), (R_ - 0.04, -h), (R_ - 0.008, -h * 0.82),
              (R_, -h * 0.55), (R_, h * 0.55), (R_ - 0.008, h * 0.82), (R_ - 0.04, h),
              (rr + 0.012, h * 0.93), (rr * 0.97, h * 0.78)], "tire")
    face = h * 0.78
    rim = s.get("rim_k", "rim")
    lip = rr * 0.88
    mb.lathe([(rr * 0.97, face), (rr * 0.93, face + 0.006), (lip, face - 0.004)], rim)
    mb.lathe([(lip, face - 0.004), (lip, -h * 0.55)], "well")
    mb.lathe([(lip, -h * 0.55), (0.0, -h * 0.55)], "well")
    mb.lathe([(rr * 0.74, face - 0.07), (0.07, face - 0.07)], "satin")
    mb.lathe([(0.085, face - 0.03), (0.085, face - 0.006), (0.065, face + 0.004), (0.0, face + 0.008)], rim, 16)

    style, n = s.get("rim_style", "multi"), s.get("spokes", 10)
    r0, r1 = 0.075, lip + 0.008
    Y = Vector((0, 1, 0))
    if style == "aero":
        mb.lathe([(lip, face - 0.03), (0.0, face - 0.03)], "rim_dark" if rim == "rim" else "satin")
    if style == "cover":
        mb.lathe([(lip, face - 0.002), (0.0, face - 0.002)], rim)
    for i in range(n):
        th = 2 * math.pi * i / n
        rad = Vector((math.cos(th), 0, math.sin(th)))
        side = Vector((-math.sin(th), 0, math.cos(th)))
        if style == "multi":
            w = s.get("spoke_w", 0.032)
            mb.beam(rad * r0 + Y * (face - 0.004), rad * r1 + Y * (face - 0.022), side, w * 1.15, w * 0.8, 0.026, rim)
        elif style == "aero":
            w1 = 2 * math.pi * r1 / n * 0.55
            mb.beam(rad * r0 + Y * (face - 0.002), rad * r1 + Y * (face - 0.014), side, 0.06, w1, 0.024, rim)
        elif style == "vspoke":
            dlt = math.pi / n * 0.32
            for o in (-dlt, dlt):
                outer = Vector((math.cos(th + o), 0, math.sin(th + o))) * r1
                arm = (outer - rad * r0).normalized()
                sd = Vector((-arm.z, 0, arm.x))
                mb.beam(rad * r0 + Y * (face - 0.004), outer + Y * (face - 0.022), sd, 0.026, 0.02, 0.024, rim)
        elif style == "cover":
            mb.beam(rad * 0.1 + Y * (face + 0.001), rad * (lip * 0.9) + Y * (face + 0.001), side, 0.012, 0.018, 0.004, "well")
    return mb


# --------------------------------------------------------------------------- Blender side


def make_materials() -> dict:
    spec = {
        "paint": dict(base=(0.42, 0.44, 0.47), metal=0.5, rough=0.32, vcol=False),
        "glass": dict(metal=0.1, rough=0.24),
        "trim": dict(metal=0.0, rough=0.72),
        "metal": dict(metal=0.85, rough=0.3),
        "headlight": dict(base=(0.86, 0.87, 0.86), metal=0.0, rough=0.12, vcol=False),
        "taillight": dict(base=(0.55, 0.03, 0.03), metal=0.0, rough=0.2, vcol=False),
    }
    mats = {}
    for slot in SLOTS:
        cfg = spec[slot]
        m = bpy.data.materials.new(f"car_{slot}")
        if getattr(m, "node_tree", None) is None:
            m.use_nodes = True
        nt = m.node_tree
        bsdf = next(nd for nd in nt.nodes if nd.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Metallic"].default_value = cfg["metal"]
        bsdf.inputs["Roughness"].default_value = cfg["rough"]
        if cfg.get("vcol", True):
            vc = nt.nodes.new("ShaderNodeVertexColor")
            vc.layer_name = "Col"
            nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            bsdf.inputs["Base Color"].default_value = (*cfg["base"], 1.0)
        mats[slot] = m
    return mats


def to_object(mb: MB, name: str, mats: dict, weld: bool) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in mb.v]
    col = bm.loops.layers.float_color.new("Col")
    for idx, key, sm in zip(mb.f, mb.k, mb.sm):
        if len(set(idx)) < 3:
            continue
        try:
            f = bm.faces.new([verts[i] for i in idx])
        except ValueError:
            continue
        slot, rgb = KEYS[key]
        f.material_index = SLOTS.index(slot)
        f.smooth = sm
        c = (*(srgb_to_linear(v) for v in rgb), 1.0)
        for loop in f.loops:
            loop[col] = c
    if weld:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0005)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-5, edges=bm.edges[:])
    bm.to_mesh(me)
    bm.free()
    for slot in SLOTS:
        me.materials.append(mats[slot])
    me.set_sharp_from_angle(angle=math.radians(38))
    me.transform(TO_EXPORT)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_car(spec: dict, mats: dict) -> list:
    car = Car(spec)
    mb = MB()
    build_body(car, mb)
    add_parts(car, mb)
    body = to_object(mb, "body", mats, weld=True)

    wl = build_wheel(car)
    meshes = {}
    for sg, mb_w in ((1, wl), (-1, wl.mirrored_y())):
        tmp = to_object(mb_w, f"{spec['id']}_wheel", mats, weld=False)
        meshes[sg] = tmp.data
        bpy.data.objects.remove(tmp)
    y = car.hw0 - 0.035 - spec["tire_w"] / 2
    objs = [body]
    for axle, label in ((car.axles[0], "front"), (car.axles[1], "back")):
        for sg, side in ((1, "left"), (-1, "right")):
            o = bpy.data.objects.new(f"wheel-{label}-{side}", meshes[sg])
            o.location = TO_EXPORT @ Vector((car.L / 2 - axle, sg * y, car.R))
            bpy.context.scene.collection.objects.link(o)
            objs.append(o)
    return objs


def bounds(objs) -> tuple[Vector, Vector]:
    bpy.context.view_layer.update()
    mn = Vector((1e9, 1e9, 1e9))
    mx = -mn
    for o in objs:
        mw = o.matrix_world
        for v in o.data.vertices:
            p = mw @ v.co
            mn = Vector(map(min, mn, p))
            mx = Vector(map(max, mx, p))
    return mn, mx


def export_glb(objs, path: Path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    kw = dict(filepath=str(path), export_format="GLB", use_selection=True, export_apply=True,
              export_yup=True, export_texcoords=False, export_normals=True, export_materials="EXPORT",
              export_cameras=False, export_lights=False, export_extras=False, export_animations=False)
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color="MATERIAL")
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)


def preview(builds, out_prefix: str) -> None:
    scene = bpy.context.scene
    palette = [(0.92, 0.92, 0.9), (0.05, 0.05, 0.055), (0.22, 0.24, 0.26), (0.11, 0.17, 0.3),
               (0.6, 0.62, 0.64), (0.5, 0.08, 0.08), (0.18, 0.25, 0.2), (0.38, 0.4, 0.42),
               (0.72, 0.66, 0.55), (0.92, 0.92, 0.9)]
    for i, (_spec, objs) in enumerate(builds):
        body = objs[0]
        m = body.data.materials[0].copy()
        bsdf = next(nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = (*(srgb_to_linear(c) for c in palette[i % len(palette)]), 1)
        body.data.materials[0] = m

    bpy.ops.mesh.primitive_plane_add(size=400)
    gm = bpy.data.materials.new("ground")
    gm.diffuse_color = (0.25, 0.25, 0.25, 1)
    bpy.context.active_object.data.materials.append(gm)
    world = bpy.data.worlds.new("w")
    scene.world = world
    bg = next((nd for nd in world.node_tree.nodes if nd.type == "BACKGROUND"), None) if world.node_tree else None
    if bg:
        bg.inputs["Color"].default_value = (0.55, 0.62, 0.72, 1)
        bg.inputs["Strength"].default_value = 0.9
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))
    scene.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y = 1800, 1000
    scene.view_settings.view_transform = "Standard"

    def place(layout):
        for (_spec, objs), (ox, oy) in zip(builds, layout):
            for o in objs:
                if "base" not in o:
                    o["base"] = list(o.location)
                b = Vector(o["base"])
                o.location = b + Vector((ox, oy, 0))

    def look(pos, target, lens=50, ortho=None):
        cam.location = pos
        cam.rotation_euler = (Vector(target) - Vector(pos)).to_track_quat("-Z", "Y").to_euler()
        if ortho:
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = ortho
        else:
            cam.data.type = "PERSP"
            cam.data.lens = lens

    cols = 5
    grid = [((i % cols) * 3.0, (i // cols) * 7.5) for i in range(len(builds))]
    place(grid)
    cx = (min(cols, len(builds)) - 1) * 3.0 / 2
    cy = (len(builds) - 1) // cols * 7.5 / 2
    for tag, pos in (("front", (cx - 7, cy - 17, 6.5)), ("rear", (cx + 7, cy + 17, 6.5))):
        look(pos, (cx, cy, 0.6), lens=42)
        scene.render.filepath = f"{out_prefix}_{tag}.png"
        bpy.ops.render.render(write_still=True)
    side = []
    x = 0.0
    for spec, _ in builds:
        side.append((0.0, x + spec["L"] / 2))
        x += spec["L"] + 0.6
    place([(sx, sy - x / 2) for sx, sy in side])
    look((30, 0, 0.8), (0, 0, 0.8), ortho=x * 1.02)
    scene.render.resolution_x, scene.render.resolution_y = 2400, 340
    scene.render.filepath = f"{out_prefix}_side.png"
    bpy.ops.render.render(write_still=True)

    # Per-car close-ups, tiled 5 wide, so lamp / grille detail is readable.
    import numpy as np

    tw, th = 640, 400
    scene.render.resolution_x, scene.render.resolution_y = tw, th
    place([(0.0, 0.0)] * len(builds))
    for tag, sgn in (("front", -1), ("rear", 1)):
        tiles = []
        for i, (spec, objs) in enumerate(builds):
            for j, (_s, other) in enumerate(builds):
                for o in other:
                    o.hide_render = j != i
            look((3.3 * sgn, sgn * (spec["L"] / 2 + 3.4), 1.7), (0, sgn * 0.6, 0.72), lens=38)
            tmp = f"{out_prefix}_{tag}_{spec['id']}.png"
            scene.render.filepath = tmp
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(tmp, check_existing=False)
            tiles.append(np.array(img.pixels[:], dtype=np.float32).reshape(th, tw, 4))
            bpy.data.images.remove(img)
        rows = (len(tiles) + cols - 1) // cols
        sheet = np.ones((rows * th, min(cols, len(tiles)) * tw, 4), dtype=np.float32)
        for i, t in enumerate(tiles):
            r, c = divmod(i, cols)
            y0 = (rows - 1 - r) * th
            sheet[y0:y0 + th, c * tw:(c + 1) * tw] = t
        out = bpy.data.images.new(f"sheet_{tag}", sheet.shape[1], sheet.shape[0], alpha=True)
        out.pixels = sheet.ravel()
        out.filepath_raw = f"{out_prefix}_close_{tag}.png"
        out.file_format = "PNG"
        out.save()


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--preview", default=None, help="render preview PNGs to this path prefix instead")
    args = ap.parse_args(argv)
    specs = [m for m in MODELS if not args.only or m["id"] in args.only]

    if args.preview:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mats = make_materials()
        preview([(s, build_car(s, mats)) for s in specs], args.preview)
        return

    CARS_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in specs:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        objs = build_car(spec, make_materials())
        mn, mx = bounds(objs)
        size = mx - mn
        path = CARS_DIR / f"{spec['id']}.glb"
        export_glb(objs, path)
        tris = sum(len(p.vertices) - 2 for o in objs for p in o.data.polygons)
        print(f"  {spec['id']}: {size.y:.2f} x {size.x:.2f} x {size.z:.2f} m, ~{tris} tris -> {path.name}")
        entries.append({
            "id": spec["id"], "file": path.name, "weight": spec["weight"],
            "length": round(size.y, 3), "width": round(size.x, 3), "height": round(size.z, 3),
            "model": spec["name"], "generation": spec["gen"],
        })

    if args.only and FLEET_PATH.is_file():
        old = json.loads(FLEET_PATH.read_text(encoding="utf-8")).get("models", [])
        fresh = {e["id"]: e for e in entries}
        entries = [fresh.pop(e["id"], e) for e in old] + list(fresh.values())
    doc = {
        "source": "blender/build_car_models.py (procedural, original geometry)",
        "note": "Real-model proportions from published dimensions; weights follow the 2025-26 "
                "Belgian new-registration mix (company-car SUVs and EVs, city hatchbacks, vans). "
                "Sizes are measured bounds including mirrors.",
        "models": entries,
    }
    FLEET_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} models to {FLEET_PATH}")


if __name__ == "__main__":
    main()
