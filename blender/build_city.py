"""Build an Antwerp city tile in Blender from OSM layout JSON."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


STYLES = {
    "yellow-brick": (0.62, 0.48, 0.32, 1.0),
    "cream-tile": (0.78, 0.72, 0.60, 1.0),
    "white-modern": (0.90, 0.89, 0.86, 1.0),
    "prefab-70s": (0.58, 0.56, 0.50, 1.0),
    "red-brick": (0.42, 0.20, 0.16, 1.0),
    "brown-tile": (0.36, 0.24, 0.18, 1.0),
    "antwerp-70s": (0.70, 0.65, 0.55, 1.0),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(argv)


def reset_scene() -> None:
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for block in list(coll):
            coll.remove(block)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"


def link(obj: bpy.types.Object) -> bpy.types.Object:
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)
    return obj


def principled(name: str, color, rough: float = 0.85, metallic: float = 0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = metallic
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def ring_mesh(name: str, ring: list[list[float]], height: float, z: float = 0.0) -> bpy.types.Mesh | None:
    if len(ring) < 3:
        return None
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts = [bm.verts.new((p[0], p[1], z)) for p in ring]
    bm.verts.ensure_lookup_table()
    edges = []
    for i, vert in enumerate(verts):
        edges.append(bm.edges.new((vert, verts[(i + 1) % len(verts)])))
    filled = bmesh.ops.triangle_fill(bm, edges=edges)
    faces = [ele for ele in filled.get("geom", []) if isinstance(ele, bmesh.types.BMFace)]
    if not faces:
        faces = list(bm.faces)
    if not faces:
        bm.free()
        return None
    if height > 0.05:
        extruded = bmesh.ops.extrude_face_region(bm, geom=faces)
        moved = [ele for ele in extruded["geom"] if isinstance(ele, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=moved, vec=(0.0, 0.0, height))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def add_ring(name: str, ring: list[list[float]], height: float, z: float, mat: bpy.types.Material) -> bpy.types.Object | None:
    mesh = ring_mesh(name, ring, height, z)
    if mesh is None:
        return None
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def polyline_mesh(name: str, points: list[list[float]], width: float, z: float = 0.04) -> bpy.types.Mesh | None:
    if len(points) < 2:
        return None
    half = width / 2.0
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == len(points) - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx, dy = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    verts = [(x, y, z) for x, y in left] + [(x, y, z) for x, y in reversed(right)]
    n = len(left)
    faces = [list(range(n)) + list(range(n, 2 * n))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def add_road(name: str, points: list[list[float]], width: float, mat: bpy.types.Material) -> bpy.types.Object | None:
    mesh = polyline_mesh(name, points, width)
    if mesh is None:
        return None
    obj = bpy.data.objects.new(name, mesh)
    assign(link(obj), mat)
    return obj


def bounds(layout: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for group in ("buildings", "water"):
        for item in layout.get(group) or []:
            for x, y in item.get("ring") or []:
                xs.append(x)
                ys.append(y)
    for road in layout.get("roads") or []:
        for x, y in road.get("points") or []:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (-200, -200, 200, 200)
    pad = 40.0
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def setup_world() -> None:
    world = bpy.data.worlds.new("Overcast")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.62, 0.66, 0.70, 1.0)
    bg.inputs["Strength"].default_value = 1.2
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = world
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 1.8
    sun.angle = math.radians(18)
    obj = bpy.data.objects.new("Sun", sun)
    obj.rotation_euler = (math.radians(42), 0.0, math.radians(125))
    link(obj)


def setup_camera(xmin: float, ymin: float, xmax: float, ymax: float) -> None:
    mid_x = (xmin + xmax) / 2.0
    mid_y = (ymin + ymax) / 2.0
    span = max(xmax - xmin, ymax - ymin)
    cam_data = bpy.data.cameras.new("CityCam")
    cam_data.lens = 35
    cam_data.clip_end = 8000
    cam = bpy.data.objects.new("CityCam", cam_data)
    cam.location = (mid_x - span * 0.55, mid_y - span * 0.7, max(180.0, span * 0.55))
    direction = Vector((mid_x, mid_y, 0.0)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    link(cam)
    bpy.context.scene.camera = cam


def build(layout: dict) -> None:
    reset_scene()
    xmin, ymin, xmax, ymax = bounds(layout)
    ground = bpy.data.meshes.new("ground")
    ground.from_pydata(
        [
            (xmin, ymin, -0.15),
            (xmax, ymin, -0.15),
            (xmax, ymax, -0.15),
            (xmin, ymax, -0.15),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    ground.update()
    ground_obj = bpy.data.objects.new("ground", ground)
    assign(link(ground_obj), principled("ground", (0.78, 0.77, 0.73, 1.0), 0.95))

    water_mat = principled("water", (0.16, 0.18, 0.20, 1.0), 0.22)
    road_mat = principled("asphalt", (0.08, 0.08, 0.085, 1.0), 0.95)
    style_mats = {name: principled(f"bldg_{name}", color, 0.88) for name, color in STYLES.items()}

    for i, pond in enumerate(layout.get("water") or []):
        add_ring(f"water_{pond.get('id', i)}", pond["ring"], 0.0, -0.04, water_mat)

    for i, road in enumerate(layout.get("roads") or []):
        add_road(f"road_{road.get('id', i)}", road["points"], float(road["width"]), road_mat)

    for i, bldg in enumerate(layout.get("buildings") or []):
        style = bldg.get("style", "cream-tile")
        add_ring(
            f"bldg_{bldg.get('id', i)}",
            bldg["ring"],
            float(bldg.get("height", 12.0)),
            0.0,
            style_mats.get(style, style_mats["cream-tile"]),
        )

    setup_world()
    setup_camera(xmin, ymin, xmax, ymax)


def export_outputs(output_dir: Path, name: str, do_render: bool) -> None:
    blend = output_dir / f"{name}.blend"
    glb = output_dir / f"{name}.glb"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_cameras=True,
        export_yup=True,
    )
    if do_render:
        scene = bpy.context.scene
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE"
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
        scene.render.image_settings.file_format = "JPEG"
        scene.render.image_settings.quality = 90
        preview = output_dir / f"{name}_preview.jpg"
        scene.render.filepath = str(preview)
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = 32
        bpy.ops.render.render(write_still=True)
        print(f"Wrote {preview}")
    print(f"Wrote {blend}")
    print(f"Wrote {glb}")


def main() -> None:
    args = parse_args()
    job = json.loads(Path(args.job).read_text())
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    layout = job.get("layout")
    if not layout:
        layout = json.loads(Path(job["layout_path"]).read_text())
    build(layout)
    export_outputs(output_dir, job.get("scene_name", "antwerp_city"), job.get("render", True))


if __name__ == "__main__":
    main()
