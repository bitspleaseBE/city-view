"""Headless Blender builder for an Antwerp 70s-80s side street."""

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
    "yellow-brick": {
        "wall": (0.62, 0.48, 0.32, 1.0),
        "side": (0.55, 0.42, 0.28, 1.0),
        "trim": (0.82, 0.78, 0.70, 1.0),
        "frame": (0.18, 0.12, 0.08, 1.0),
        "ground": (0.45, 0.34, 0.22, 1.0),
        "roof": (0.22, 0.22, 0.23, 1.0),
        "rough": 0.92,
    },
    "cream-tile": {
        "wall": (0.78, 0.72, 0.60, 1.0),
        "side": (0.72, 0.66, 0.55, 1.0),
        "trim": (0.88, 0.84, 0.74, 1.0),
        "frame": (0.22, 0.16, 0.12, 1.0),
        "ground": (0.84, 0.78, 0.64, 1.0),
        "roof": (0.28, 0.28, 0.27, 1.0),
        "rough": 0.88,
    },
    "white-modern": {
        "wall": (0.90, 0.89, 0.86, 1.0),
        "side": (0.84, 0.83, 0.80, 1.0),
        "trim": (0.94, 0.93, 0.90, 1.0),
        "frame": (0.05, 0.05, 0.055, 1.0),
        "ground": (0.88, 0.87, 0.84, 1.0),
        "roof": (0.16, 0.16, 0.17, 1.0),
        "rough": 0.78,
    },
    "prefab-70s": {
        "wall": (0.58, 0.56, 0.50, 1.0),
        "side": (0.52, 0.50, 0.45, 1.0),
        "trim": (0.42, 0.40, 0.36, 1.0),
        "frame": (0.10, 0.11, 0.12, 1.0),
        "ground": (0.40, 0.38, 0.34, 1.0),
        "roof": (0.20, 0.20, 0.20, 1.0),
        "rough": 0.86,
    },
    "red-brick": {
        "wall": (0.42, 0.20, 0.16, 1.0),
        "side": (0.38, 0.18, 0.14, 1.0),
        "trim": (0.80, 0.76, 0.68, 1.0),
        "frame": (0.14, 0.10, 0.08, 1.0),
        "ground": (0.28, 0.16, 0.13, 1.0),
        "roof": (0.18, 0.16, 0.15, 1.0),
        "rough": 0.94,
    },
    "brown-tile": {
        "wall": (0.36, 0.24, 0.18, 1.0),
        "side": (0.32, 0.22, 0.16, 1.0),
        "trim": (0.72, 0.64, 0.50, 1.0),
        "frame": (0.08, 0.07, 0.06, 1.0),
        "ground": (0.22, 0.14, 0.10, 1.0),
        "roof": (0.16, 0.14, 0.12, 1.0),
        "rough": 0.84,
    },
    "antwerp-70s": {
        "wall": (0.70, 0.65, 0.55, 1.0),
        "side": (0.64, 0.59, 0.50, 1.0),
        "trim": (0.86, 0.80, 0.68, 1.0),
        "frame": (0.12, 0.11, 0.10, 1.0),
        "ground": (0.82, 0.76, 0.62, 1.0),
        "roof": (0.24, 0.24, 0.23, 1.0),
        "rough": 0.9,
    },
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(argv)


def reset_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def link(obj: bpy.types.Object, parent: bpy.types.Object | None = None) -> bpy.types.Object:
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def new_empty(name: str, location: tuple[float, float, float]) -> bpy.types.Object:
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.location = location
    return link(empty)


def box_mesh(name: str, sx: float, sy: float, sz: float) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for vert in bm.verts:
        vert.co.x *= sx
        vert.co.y *= sy
        vert.co.z *= sz
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def add_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    parent: bpy.types.Object | None = None,
) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, box_mesh(name, *size))
    obj.location = location
    return link(obj, parent)


def principled(
    name: str,
    color,
    rough: float = 0.8,
    metallic: float = 0.0,
    spec: float = 0.3,
    transmission: float = 0.0,
):
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
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = spec
    if transmission and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def photo_material(name: str, image_path: Path, crop: list[float], rough: float) -> bpy.types.Material:
    image = bpy.data.images.load(str(image_path))
    image.colorspace_settings.name = "sRGB"
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    mapping = nodes.new("ShaderNodeMapping")
    uv = nodes.new("ShaderNodeTexCoord")
    tex.image = image
    tex.extension = "CLIP"
    u0, v0, u1, v1 = crop
    mapping.inputs["Location"].default_value = (u0, v0, 0.0)
    mapping.inputs["Scale"].default_value = (max(u1 - u0, 0.001), max(v1 - v0, 0.001), 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.18
    links.new(uv.outputs["UV"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def assign(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def unwrap_front_face(obj: bpy.types.Object, street_axis: str = "+Y") -> None:
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for face in bm.faces:
        n = face.normal
        if street_axis == "+Y":
            is_front = n.y > 0.5
        else:
            is_front = n.y < -0.5
        xs = [loop.vert.co.x for loop in face.loops]
        zs = [loop.vert.co.z for loop in face.loops]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        dx = max(max_x - min_x, 1e-6)
        dz = max(max_z - min_z, 1e-6)
        for loop in face.loops:
            u = (loop.vert.co.x - min_x) / dx
            v = (loop.vert.co.z - min_z) / dz
            if is_front:
                loop[uv_layer].uv = (u, v)
            else:
                loop[uv_layer].uv = (u * 0.15, v * 0.15)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def style_of(spec: dict) -> dict:
    return STYLES.get(spec.get("style", "cream-tile"), STYLES["cream-tile"])


def resolve_photo(root: Path, spec: dict) -> Path:
    photo = Path(spec["photo"])
    if not photo.is_absolute():
        photo = root / photo
    return photo


def build_photo_building(spec: dict, origin: Vector, facing: int, root: Path) -> bpy.types.Object:
    style = style_of(spec)
    width, depth, height = spec["width"], spec["depth"], spec["height"]
    parapet = spec.get("parapet", 0.4)
    recess = spec.get("shop_recess", 0.7)
    parent = new_empty(spec["name"], (origin.x, origin.y, 0.0))

    body = add_box(
        f"{spec['name']}_body",
        (width, depth, height),
        (0.0, facing * (depth / 2.0), height / 2.0),
        parent,
    )
    assign(body, principled(f"{spec['name']}_side", style["side"], style["rough"]))
    unwrap_front_face(body, "+Y" if facing > 0 else "-Y")

    facade_depth = 0.08
    facade = add_box(
        f"{spec['name']}_facade",
        (width + 0.02, facade_depth, height + 0.02),
        (0.0, facing * (depth + facade_depth / 2.0 - 0.01), height / 2.0),
        parent,
    )
    crop = spec.get("crop") or [0.0, 0.0, 1.0, 1.0]
    assign(facade, photo_material(f"{spec['name']}_photo", resolve_photo(root, spec), crop, 0.86))
    unwrap_front_face(facade, "+Y" if facing > 0 else "-Y")

    if recess > 0:
        hole = add_box(
            f"{spec['name']}_recess",
            (width * 0.42, recess, height * 0.28),
            (width * 0.16, facing * (depth - recess / 2.0 + 0.02), height * 0.16),
            parent,
        )
        assign(hole, principled(f"{spec['name']}_void", (0.04, 0.04, 0.045, 1.0), 0.7))

    cornice = add_box(
        f"{spec['name']}_cornice",
        (width + 0.18, 0.28, 0.16),
        (0.0, facing * (depth + 0.08), height * 0.34),
        parent,
    )
    assign(cornice, principled(f"{spec['name']}_trim", style["trim"], 0.7))

    cap = add_box(
        f"{spec['name']}_parapet",
        (width + 0.12, 0.22, parapet),
        (0.0, facing * (depth + 0.04), height + parapet / 2.0),
        parent,
    )
    assign(cap, principled(f"{spec['name']}_parapet", style["trim"], 0.75))

    roof = add_box(
        f"{spec['name']}_roof",
        (width - 0.3, depth - 0.4, 0.18),
        (0.0, facing * (depth / 2.0 - 0.1), height + 0.05),
        parent,
    )
    assign(roof, principled(f"{spec['name']}_roof", style["roof"], 0.55, metallic=0.15))
    return parent


def add_window(name: str, w: float, h: float, loc: tuple[float, float, float], parent, style, facing: int):
    frame_t = 0.07
    frame = add_box(f"{name}_frame", (w, 0.1, h), loc, parent)
    assign(frame, principled(f"{name}_frame", style["frame"], 0.45, metallic=0.35))
    glass = add_box(
        f"{name}_glass",
        (w - frame_t * 2, 0.04, h - frame_t * 2),
        (loc[0], loc[1] + facing * 0.03, loc[2]),
        parent,
    )
    assign(
        glass,
        principled(f"{name}_glass", (0.15, 0.20, 0.24, 1.0), 0.08, spec=0.7, transmission=0.35),
    )


def build_procedural_building(spec: dict, origin: Vector, facing: int) -> bpy.types.Object:
    style = style_of(spec)
    width, depth, height = spec["width"], spec["depth"], spec["height"]
    floors = int(spec.get("floors", 3))
    bays = int(spec.get("bays", 2))
    ground = spec.get("ground", "shop")
    parent = new_empty(spec["name"], (origin.x, origin.y, 0.0))

    body = add_box(
        f"{spec['name']}_body",
        (width, depth, height),
        (0.0, facing * (depth / 2.0), height / 2.0),
        parent,
    )
    assign(body, principled(f"{spec['name']}_wall", style["wall"], style["rough"]))

    ground_h = height * 0.32 if floors <= 3 else height * 0.26
    upper_h = height - ground_h
    floor_h = upper_h / max(floors - 1, 1)

    # Ground-floor band
    band = add_box(
        f"{spec['name']}_plinth",
        (width + 0.06, 0.12, ground_h),
        (0.0, facing * (depth + 0.02), ground_h / 2.0),
        parent,
    )
    assign(band, principled(f"{spec['name']}_plinth", style["ground"], 0.82))

    if ground == "shop":
        shop_w = width * 0.78
        shop_h = ground_h * 0.72
        add_window(
            f"{spec['name']}_shop",
            shop_w,
            shop_h,
            (0.0, facing * (depth + 0.08), ground_h * 0.48),
            parent,
            style,
            facing,
        )
    else:
        door_w, door_h = 1.05, ground_h * 0.78
        door = add_box(
            f"{spec['name']}_door",
            (door_w, 0.08, door_h),
            (-width * 0.28, facing * (depth + 0.06), door_h / 2.0 + 0.04),
            parent,
        )
        assign(door, principled(f"{spec['name']}_door", (0.86, 0.86, 0.84, 1.0), 0.55))
        add_window(
            f"{spec['name']}_gwin",
            width * 0.34,
            ground_h * 0.42,
            (width * 0.18, facing * (depth + 0.08), ground_h * 0.52),
            parent,
            style,
            facing,
        )

    win_w = min(1.15, (width - 0.7) / bays - 0.15)
    win_h = min(1.55, floor_h * 0.58)
    for floor in range(1, floors):
        z = ground_h + (floor - 0.55) * floor_h
        for bay in range(bays):
            x = -width / 2 + (bay + 0.5) * (width / bays)
            add_window(
                f"{spec['name']}_w{floor}_{bay}",
                win_w,
                win_h,
                (x, facing * (depth + 0.08), z),
                parent,
                style,
                facing,
            )

    cornice = add_box(
        f"{spec['name']}_cornice",
        (width + 0.2, 0.26, 0.18),
        (0.0, facing * (depth + 0.08), height - 0.12),
        parent,
    )
    assign(cornice, principled(f"{spec['name']}_cornice", style["trim"], 0.7))

    roof = add_box(
        f"{spec['name']}_roof",
        (width - 0.2, depth - 0.35, 0.2),
        (0.0, facing * (depth / 2.0 - 0.05), height + 0.08),
        parent,
    )
    assign(roof, principled(f"{spec['name']}_roof", style["roof"], 0.5, metallic=0.2))
    return parent


def place_row(buildings: list[dict], y: float, facing: int, root: Path) -> float:
    total = sum(b["width"] for b in buildings)
    x = -total / 2.0
    for spec in buildings:
        x += spec["width"] / 2.0
        origin = Vector((x, y, 0.0))
        if spec.get("kind") == "photo":
            build_photo_building(spec, origin, facing, root)
        else:
            build_procedural_building(spec, origin, facing)
        x += spec["width"] / 2.0
    return total


def build_ground(street: dict, block_length: float) -> None:
    road_w = street["road_width"]
    walk_w = street["sidewalk_width"]
    curb_h = street["curb_height"]
    length = max(block_length + 8.0, street.get("length", block_length))

    road = add_box("road", (length, road_w, 0.08), (0.0, 0.0, -0.04))
    assign(road, principled("asphalt", (0.07, 0.07, 0.075, 1.0), 0.95))

    for side, y in ((1, road_w / 2 + walk_w / 2), (-1, -(road_w / 2 + walk_w / 2))):
        walk = add_box(f"sidewalk_{side}", (length, walk_w, 0.1), (0.0, y, curb_h / 2))
        assign(walk, principled(f"paver_{side}", (0.62, 0.61, 0.58, 1.0), 0.9))
        curb = add_box(
            f"curb_{side}",
            (length, 0.12, curb_h + 0.04),
            (0.0, side * (road_w / 2 + 0.04), curb_h / 2),
        )
        assign(curb, principled(f"curbmat_{side}", (0.55, 0.54, 0.50, 1.0), 0.85))

    # Center line dashes
    dash_mat = principled("centerline", (0.72, 0.68, 0.42, 1.0), 0.7)
    for i, x in enumerate(range(-int(length / 2) + 2, int(length / 2) - 1, 4)):
        dash = add_box(f"dash_{i}", (1.6, 0.12, 0.01), (float(x), 0.0, 0.01))
        assign(dash, dash_mat)


def add_lamp(name: str, x: float, y: float) -> None:
    pole = add_box(f"{name}_pole", (0.12, 0.12, 4.2), (x, y, 2.1))
    assign(pole, principled(f"{name}_pole", (0.25, 0.25, 0.24, 1.0), 0.55, metallic=0.4))
    head = add_box(f"{name}_head", (0.55, 0.35, 0.18), (x, y, 4.25))
    assign(head, principled(f"{name}_head", (0.85, 0.78, 0.55, 1.0), 0.35))


def setup_world() -> None:
    world = bpy.data.worlds.new("AntwerpOvercast")
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.55, 0.60, 0.66, 1.0)
    bg.inputs["Strength"].default_value = 1.35
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = world

    sun_data = bpy.data.lights.new("OvercastSun", "SUN")
    sun_data.energy = 1.6
    sun_data.angle = math.radians(25)
    sun_data.color = (0.95, 0.96, 1.0)
    sun = bpy.data.objects.new("OvercastSun", sun_data)
    sun.rotation_euler = (math.radians(48), 0.0, math.radians(35))
    link(sun)


def setup_camera(target: Vector) -> None:
    cam_data = bpy.data.cameras.new("StreetCam")
    cam_data.lens = 32
    cam_data.clip_end = 400
    cam = bpy.data.objects.new("StreetCam", cam_data)
    cam.location = (1.4, -8.6, 1.65)
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    link(cam)
    bpy.context.scene.camera = cam

    three_q = bpy.data.cameras.new("ThreeQuarterCam")
    three_q.lens = 35
    three_q.clip_end = 400
    q = bpy.data.objects.new("ThreeQuarterCam", three_q)
    q.location = (18.0, -16.0, 7.5)
    q.rotation_euler = (target - q.location).to_track_quat("-Z", "Y").to_euler()
    link(q)


def setup_render(output_dir: Path, name: str) -> Path:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 90
    preview = output_dir / f"{name}_preview.jpg"
    scene.render.filepath = str(preview)
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = 64
    return preview


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
        preview = setup_render(output_dir, name)
        bpy.ops.render.render(write_still=True)
        print(f"Wrote {preview}")
    print(f"Wrote {blend}")
    print(f"Wrote {glb}")


def build(job: dict) -> None:
    reset_scene()
    scene = job["scene"]
    root = Path(job["root"])
    street = scene["street"]
    buildings = scene["buildings"]
    opposite = scene.get("opposite") or []

    sidewalk = street["sidewalk_width"]
    road_w = street["road_width"]
    front_y = road_w / 2 + sidewalk
    back_y = -(road_w / 2 + sidewalk)

    length = place_row(buildings, front_y, facing=1, root=root)
    if opposite:
        place_row(opposite, back_y, facing=-1, root=root)
    build_ground(street, length)

    for i, x in enumerate((-18.0, -6.0, 6.0, 18.0)):
        add_lamp(f"lamp_n_{i}", x, front_y - 0.45)
        add_lamp(f"lamp_s_{i}", x + 2.0, back_y + 0.45)

    setup_world()
    hero = next((b for b in buildings if b.get("kind") == "photo"), buildings[len(buildings) // 2])
    setup_camera(Vector((0.0, front_y + 0.2, hero["height"] * 0.45)))


def main() -> None:
    args = parse_args()
    job = json.loads(Path(args.job).read_text())
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    build(job)
    export_outputs(output_dir, job.get("scene_name", "antwerp_street"), job.get("render", True))


if __name__ == "__main__":
    main()
