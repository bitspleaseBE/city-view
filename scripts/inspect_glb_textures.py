"""Report image textures inside a GLB: ``python3 scripts/inspect_glb_textures.py viewer/klein_antwerpen.glb``.

Exits non-zero when no photo façade texture is present (guards CI against flat-colour regressions).
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def read_gltf_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path} is not a GLB")
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON":
        raise ValueError("first GLB chunk is not JSON")
    return json.loads(data[20 : 20 + chunk_len])


def summarize(doc: dict) -> dict:
    images = doc.get("images") or []
    views = doc.get("bufferViews") or []
    sizes = {}
    for img in images:
        view = views[img["bufferView"]] if "bufferView" in img else {}
        sizes[img.get("name", "?")] = view.get("byteLength", 0)
    materials = doc.get("materials") or []
    textured = [
        m for m in materials if (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture") is not None
    ]
    uv_meshes = sum(
        1
        for mesh in doc.get("meshes") or []
        for prim in mesh.get("primitives") or []
        if "TEXCOORD_0" in (prim.get("attributes") or {})
    )
    return {
        "images": sizes,
        "textures": len(doc.get("textures") or []),
        "materials": len(materials),
        "textured_materials": [m.get("name") for m in textured],
        "primitives_with_uv": uv_meshes,
    }


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "viewer/klein_antwerpen.glb")
    info = summarize(read_gltf_json(path))
    print(f"{path}: {info['materials']} materials, {info['textures']} textures, {len(info['images'])} images")
    for name, size in sorted(info["images"].items()):
        print(f"  image {name}: {size // 1024} KiB")
    print(f"  textured materials: {len(info['textured_materials'])}")
    print(f"  primitives with UVs: {info['primitives_with_uv']}")
    if "facade_photo_atlas" not in info["textured_materials"]:
        print("ERROR: facade_photo_atlas material has no baseColorTexture", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
