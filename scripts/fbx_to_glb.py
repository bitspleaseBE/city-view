"""Convert Mixamo FBX characters to compact GLB for the web viewer.

Usage:
  blender --background --python scripts/fbx_to_glb.py -- \
    viewer/characters/*.fbx
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy


def convert(fbx_path: Path, glb_path: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Mixamo FBX is usually in cm; Blender import can apply scale.
    bpy.ops.import_scene.fbx(
        filepath=str(fbx_path),
        automatic_bone_orientation=True,
        use_anim=True,
        ignore_leaf_bones=True,
        global_scale=0.01,  # cm → m
    )

    # Prefer smaller textures for web
    for img in bpy.data.images:
        if img.size[0] > 1024 or img.size[1] > 1024:
            try:
                img.scale(min(img.size[0], 1024), min(img.size[1], 1024))
            except Exception:
                pass

    glb_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        export_animations=True,
        export_skins=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_image_format="JPEG",
        export_jpeg_quality=70,
        export_apply=False,
    )
    print(f"OK {fbx_path.name} -> {glb_path} ({glb_path.stat().st_size} bytes)")


def main() -> None:
    argv = sys.argv
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    if not args:
        root = Path(__file__).resolve().parents[1] / "viewer" / "characters"
        args = [str(p) for p in sorted(root.glob("*_Walking.fbx"))]
    for arg in args:
        fbx = Path(arg).resolve()
        if not fbx.exists():
            print(f"SKIP missing {fbx}")
            continue
        glb = fbx.with_suffix(".glb")
        convert(fbx, glb)


if __name__ == "__main__":
    main()
