"""Parked cars from the fleet GLBs (``blender/build_car_models.py``, Belgian 2025-26 mix).

Templates: ``viewer/cars/*.glb`` + ``fleet.json``. Each bay is a linked
duplicate (shared mesh data). Every import brings its own ``car_*`` materials;
they are folded back onto one shared set so the district GLB carries six car
materials and the viewer can repaint ``car_paint`` per car (``paintParkedCars``).

Fleet cars arrive from glTF with quaternion rotation mode and the nose on −Y.
We rewrite mesh vertices (not object euler) so local +X is forward, then size
to fleet metres. Instances use ``rotation_mode='XYZ'`` so parking yaw survives
glTF export (setting ``rotation_euler`` while mode is ``QUATERNION`` is a no-op
and was collapsing every car to axis-aligned, sideways proportions).
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from cityview import parking as parking_plan  # noqa: E402

CARS_DIR = _REPO_ROOT / "viewer" / "cars"
FLEET_PATH = CARS_DIR / "fleet.json"

_TEMPLATES: list[dict] | None = None
_SHARED_MATS: dict[str, bpy.types.Material] = {}


def _fleet_specs() -> list[dict]:
    if not FLEET_PATH.is_file():
        return []
    doc = json.loads(FLEET_PATH.read_text(encoding="utf-8"))
    return list(doc.get("models") or [])


def _join_selected_meshes() -> bpy.types.Object | None:
    meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if not meshes:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def _local_bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    """Axis-aligned bounds of mesh vertices in object-local space."""
    me = obj.data
    if not me.vertices:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    mn = Vector(me.vertices[0].co)
    mx = Vector(me.vertices[0].co)
    for v in me.vertices:
        for i in range(3):
            mn[i] = min(mn[i], v.co[i])
            mx[i] = max(mx[i], v.co[i])
    return mn, mx


def _share_car_materials(obj: bpy.types.Object) -> None:
    """Point each import's ``car_*`` materials at the first fleet import's and drop the copies.

    Keyed on the first *imported* material, not on name: build_city's box-car fallback
    already owns a plain ``car_glass``, so the fleet one may arrive as ``car_glass.001``.
    """
    for slot in obj.material_slots:
        m = slot.material
        if m is None:
            continue
        base = re.sub(r"\.\d{3}$", "", m.name)
        if not base.startswith("car_"):
            continue
        shared = _SHARED_MATS.setdefault(base, m)
        if shared is not m:
            slot.material = shared
            if m.users == 0:
                bpy.data.materials.remove(m)


def _normalize_mesh(obj: bpy.types.Object, spec: dict) -> None:
    """Bake fleet −Y forward → +X forward, scale to fleet L/W/H, origin at ground centre.

    Uses ``Mesh.transform`` so the fix cannot be lost to glTF quaternion rotation mode.
    """
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj.location = (0.0, 0.0, 0.0)

    me = obj.data
    if not me.vertices:
        return

    # +90° around Z: fleet length on ±Y → local ±X (parking forward).
    me.transform(Matrix.Rotation(math.pi / 2, 4, "Z"))
    me.update()

    mn, mx = _local_bounds(obj)
    size = mx - mn
    if size.x < 1e-4 or size.y < 1e-4 or size.z < 1e-4:
        return

    sx = float(spec["length"]) / size.x
    sy = float(spec["width"]) / size.y
    sz = float(spec["height"]) / size.z
    me.transform(Matrix.Diagonal((sx, sy, sz, 1.0)))
    me.update()

    mn, mx = _local_bounds(obj)
    cx = 0.5 * (mn.x + mx.x)
    cy = 0.5 * (mn.y + mx.y)
    me.transform(Matrix.Translation(Vector((-cx, -cy, -mn.z))))
    me.update()
    # bound_box / dimensions stay stale until the view layer re-evaluates.
    bpy.context.view_layer.update()


def _prepare_template(obj: bpy.types.Object, spec: dict, coll: bpy.types.Collection) -> bpy.types.Object:
    obj.name = f"tpl_{spec['id']}"
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)

    _normalize_mesh(obj, spec)
    mn, mx = _local_bounds(obj)
    size = mx - mn
    # Prefer vertex bounds over stale Object.dimensions for the build log.
    obj["fleet_size"] = (round(size.x, 3), round(size.y, 3), round(size.z, 3))

    obj.hide_set(True)
    obj.hide_render = True
    obj.hide_viewport = True
    return obj


def load_templates(*, force: bool = False) -> list[dict]:
    """Import fleet GLBs once per Blender session; return weighted template dicts."""
    global _TEMPLATES
    if _TEMPLATES is not None and not force:
        return _TEMPLATES

    specs = _fleet_specs()
    _SHARED_MATS.clear()
    out: list[dict] = []
    coll = bpy.data.collections.get("CarTemplates")
    if coll is None:
        coll = bpy.data.collections.new("CarTemplates")
        bpy.context.scene.collection.children.link(coll)

    for spec in specs:
        path = CARS_DIR / spec["file"]
        if not path.is_file():
            print(f"Car template missing: {path}")
            continue
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.import_scene.gltf(filepath=str(path))
        joined = _join_selected_meshes()
        if joined is None:
            print(f"Car template import empty: {path.name}")
            continue
        for obj in list(bpy.context.selected_objects):
            if obj != joined and obj.type != "MESH":
                bpy.data.objects.remove(obj, do_unlink=True)
        _share_car_materials(joined)
        tpl = _prepare_template(joined, spec, coll)
        size = tpl.get("fleet_size") or tuple(tpl.dimensions)
        print(
            f"  car tpl {spec['id']}: size=({size[0]:.2f},{size[1]:.2f},{size[2]:.2f}) "
            f"target=({spec['length']},{spec['width']},{spec['height']})"
        )
        out.append({"id": spec["id"], "weight": float(spec.get("weight") or 1), "object": tpl})

    _TEMPLATES = out
    print(f"Car templates loaded: {len(out)} from {CARS_DIR}")
    return out


def _pick(templates: list[dict], rng: random.Random) -> dict:
    total = sum(t["weight"] for t in templates) or 1.0
    r = rng.random() * total
    for t in templates:
        r -= t["weight"]
        if r <= 0:
            return t
    return templates[-1]


def _instance(template: dict, name: str, x: float, y: float, z: float, yaw: float, coll: bpy.types.Collection) -> None:
    src = template["object"]
    obj = src.copy()
    obj.data = src.data
    obj.name = name
    obj.hide_set(False)
    obj.hide_render = False
    obj.hide_viewport = False
    coll.objects.link(obj)
    obj.location = (x, y, z)
    # glTF imports leave QUATERNION mode; euler writes are ignored until we switch.
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = (0.0, 0.0, yaw)
    obj.scale = (1.0, 1.0, 1.0)


def add_parked_cars(
    layout: dict,
    spawn_xy: tuple[float, float],
    rails: "object",
    clear_parked: float,
    max_cars: int = 64,
    fallback=None,
) -> dict:
    """Place fleet-model cars on OSM kerbside parking. ``fallback(plan)`` builds boxes if no GLBs."""
    plan = parking_plan.plan_parked_cars(
        layout,
        spawn_xy,
        max_cars=max_cars,
        blocked=lambda x, y: rails.within(x, y, clear_parked),
    )
    templates = load_templates()
    if not templates:
        if fallback is not None:
            return fallback(plan)
        return {"cars": 0, "summary": parking_plan.summarize(plan), "models": "none"}

    coll = bpy.data.collections.get("ParkedCars")
    if coll is None:
        coll = bpy.data.collections.new("ParkedCars")
        bpy.context.scene.collection.children.link(coll)

    counts: dict[str, int] = {}
    for placed, car in enumerate(plan):
        rng = random.Random((hash((car["x"], car["y"], car["yaw"])) & 0xFFFFFFFF) ^ 0xC0FFEE)
        tpl = _pick(templates, rng)
        lift = float(car.get("lift") or 0.0)
        _instance(tpl, f"car_{placed}_{tpl['id']}", float(car["x"]), float(car["y"]), lift, float(car["yaw"]), coll)
        counts[tpl["id"]] = counts.get(tpl["id"], 0) + 1

    summary = parking_plan.summarize(plan)
    mix = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    return {"cars": len(plan), "summary": f"{summary}; models: {mix}", "models": counts}
