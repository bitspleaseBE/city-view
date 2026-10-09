"""Strip ``viewer/characters/{Name}_{Riding,Scooter}.glb`` down to animation-only GLBs.

The baked rider files carry the full Walking mesh and textures (1-5 MB each) for a
5-8 KB clip. The viewer loads each character's mesh once from ``{Name}_Walking.glb``
and the extra clips from ``viewer/characters/clips/``; three.js binds tracks by node
name, so the clip files keep the node tree (names, rest TRS, children) and nothing else.

  python3 scripts/extract_anim_clips.py
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAR_DIR = ROOT / "viewer" / "characters"
OUT_DIR = CHAR_DIR / "clips"
CHARS = ("Remy", "Amy", "James", "Michelle", "Aj")
KINDS = ("Riding", "Scooter")

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"{path}: not a GLB")
    off = 12
    gltf, binary = None, b""
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8 : off + 8 + clen]
        if ctype == CHUNK_JSON:
            gltf = json.loads(chunk)
        elif ctype == CHUNK_BIN:
            binary = chunk
        off += 8 + clen
    if gltf is None:
        raise ValueError(f"{path}: no JSON chunk")
    return gltf, binary


def write_glb(path: Path, gltf: dict, binary: bytes) -> None:
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    out = struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(js), CHUNK_JSON) + js
    out += struct.pack("<II", len(binary), CHUNK_BIN) + binary
    path.write_bytes(out)


def strip_to_clips(gltf: dict, binary: bytes) -> tuple[dict, bytes]:
    anims = gltf.get("animations", [])
    if not anims:
        raise ValueError("no animations")
    acc_map: dict[int, int] = {}
    accessors, views = [], []
    blob = bytearray()

    def remap(i: int) -> int:
        if i in acc_map:
            return acc_map[i]
        acc = dict(gltf["accessors"][i])
        view = gltf["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0)
        blob.extend(b"\0" * (-len(blob) % 4))
        new_view = {"buffer": 0, "byteOffset": len(blob), "byteLength": view["byteLength"]}
        if "byteStride" in view:
            new_view["byteStride"] = view["byteStride"]
        blob.extend(binary[start : start + view["byteLength"]])
        views.append(new_view)
        acc["bufferView"] = len(views) - 1
        accessors.append(acc)
        acc_map[i] = len(accessors) - 1
        return acc_map[i]

    new_anims = []
    for a in anims:
        samplers = [
            {**s, "input": remap(s["input"]), "output": remap(s["output"])} for s in a["samplers"]
        ]
        new_anims.append({**a, "samplers": samplers})

    keep = ("name", "children", "translation", "rotation", "scale", "matrix")
    nodes = [{k: n[k] for k in keep if k in n} for n in gltf["nodes"]]
    scenes = [{k: s[k] for k in ("name", "nodes") if k in s} for s in gltf.get("scenes", [])]
    out = {
        "asset": {"version": "2.0", "generator": "city-view extract_anim_clips.py"},
        "scene": gltf.get("scene", 0),
        "scenes": scenes,
        "nodes": nodes,
        "animations": new_anims,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    return out, bytes(blob)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    for name in CHARS:
        for kind in KINDS:
            src = CHAR_DIR / f"{name}_{kind}.glb"
            if not src.exists():
                print(f"skip missing {src.name}")
                continue
            dst = OUT_DIR / src.name
            gltf, binary = read_glb(src)
            out, blob = strip_to_clips(gltf, binary)
            write_glb(dst, out, blob)
            print(f"{src.name}: {src.stat().st_size // 1024} KB -> {dst.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
