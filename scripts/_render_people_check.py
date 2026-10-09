"""QA lineup of exported pedestrian GLBs mid-stride.

  blender --background --python scripts/_render_people_check.py -- out.png [frame] Id1 Id2 ...
      [--close] [--camz=1.6] [--yaw=22]
"""
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
PEOPLE = ROOT / "viewer" / "characters" / "people"

args = sys.argv[sys.argv.index("--") + 1 :]
out = args[0]
frame = int(args[1]) if len(args) > 1 and args[1].isdigit() else 10
flags = {a[2:].split("=")[0]: (a.split("=")[1] if "=" in a else "1") for a in args if a.startswith("--")}
ids = [a for a in args[1:] if not a.isdigit() and not a.startswith("--")]
ids = ids or sorted(p.stem for p in PEOPLE.glob("*.glb"))
close = "close" in flags

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = min(3200, 280 * len(ids)) if not close else 1400
scene.render.resolution_y = 900
scene.render.film_transparent = False
scene.view_settings.view_transform = "AgX"
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.6, 0.68, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
scene.world = world

spacing = 0.9
for i, pid in enumerate(ids):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(PEOPLE / f"{pid}.glb"))
    new = set(bpy.data.objects) - before
    holder = bpy.data.objects.new(f"at_{pid}", None)
    scene.collection.objects.link(holder)
    holder.location.x = (i - (len(ids) - 1) / 2) * spacing
    for r in [o for o in new if o.parent is None]:
        r.parent = holder
    for o in new:
        if o.animation_data and o.animation_data.action:
            o.animation_data.action.use_fake_user = True

scene.frame_set(frame)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3.5
sun.rotation_euler = (math.radians(50), 0, math.radians(30))
scene.collection.objects.link(sun)
bpy.ops.mesh.primitive_plane_add(size=60)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
width = len(ids) * spacing
if close:
    cam.data.lens = 85
    yaw = math.radians(float(flags.get("yaw", 22)))
    cam.location = (2.35 * math.sin(yaw), -2.35 * math.cos(yaw), float(flags.get("camz", 1.6)))
    cam.rotation_euler = (math.radians(88), 0, yaw)
else:
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(width + 0.6, 2.2 * scene.render.resolution_x / scene.render.resolution_y)
    cam.location = (0, -10, 0.95)
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.ortho_scale = max(width + 0.4, 2.1) * 1.0
    scene.render.resolution_y = int(scene.render.resolution_x * 2.1 / cam.data.ortho_scale)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
