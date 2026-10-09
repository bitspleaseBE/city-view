"""Street-level Heilige Geestkerk render from Mechelsesteenweg (Gounod side)."""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

eye = Vector((-100.0, 450.0, 4.5))
target = Vector((-74.0, 450.0, 18.0))

cam_data = bpy.data.cameras.new("GeestCam")
cam_data.lens = 28
cam_data.clip_end = 800
cam = bpy.data.objects.new("GeestCam", cam_data)
bpy.context.scene.collection.objects.link(cam)
cam.location = eye
cam.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()

scene = bpy.context.scene
scene.camera = cam
try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except Exception:
    scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1600
scene.render.resolution_y = 1000
scene.render.image_settings.file_format = "JPEG"
scene.render.image_settings.quality = 92
out = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "output", "heilige_geestkerk_check.jpg")
)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("Wrote", out)

# Closer portal shot
eye2 = Vector((-92.0, 448.0, 2.8))
target2 = Vector((-75.0, 449.5, 10.0))
cam.location = eye2
cam.rotation_euler = (target2 - eye2).to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 35
out2 = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "output", "heilige_geestkerk_portal.jpg")
)
scene.render.filepath = out2
bpy.ops.render.render(write_still=True)
print("Wrote", out2)

for ob in bpy.data.objects:
    if "501410385" in ob.name:
        mats = []
        if ob.data and hasattr(ob.data, "materials"):
            mats = [m.name if m else None for m in ob.data.materials[:5]]
        print(ob.name, mats)
