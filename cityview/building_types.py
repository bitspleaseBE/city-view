"""Building types: photo-remixed facade looks for OSM / Blender assignment."""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any

from cityview.palette import jitter_rgba, remix_palette, sample_photo
from cityview.paths import ASSETS, ROOT


def _stable_hash(text: str) -> int:
    return zlib.adler32(text.encode("utf-8")) & 0xFFFFFFFF


REFERENCES_DIR = ASSETS / "references" / "klein-antwerpen"
BUILDING_TYPES_PATH = ASSETS / "styles" / "building_types.json"

# Photos remixed into typed palettes; wall_bias pulls washed samples toward family hue.
TYPE_SPECS: list[dict[str, Any]] = [
    {
        "id": "neo-flemish",
        "name": "Neo-Flemish townhouse",
        "window": "arch",
        "roof_kind": "mansard",
        "photos": ["ref_08.jpg", "ref_11.jpg", "ref_16.jpg"],
        "wall_bias": [0.42, 0.18, 0.14, 1.0],
        "bias_amount": 0.55,
        "weight_historic": 11,
    },
    {
        "id": "red-brick",
        "name": "Red-brick terrace",
        "window": "rect",
        "roof_kind": "gable",
        "photos": ["ref_11.jpg", "ref_16.jpg", "ref_08.jpg"],
        "wall_bias": [0.45, 0.20, 0.16, 1.0],
        "bias_amount": 0.5,
        "weight_historic": 7,
    },
    {
        "id": "neoclassical",
        "name": "Cream stucco neoclassical",
        "window": "rect",
        "roof_kind": "mansard",
        "photos": ["ref_06.jpg", "ref_10.jpg", "ref_17.jpg"],
        "wall_bias": [0.78, 0.74, 0.64, 1.0],
        "bias_amount": 0.42,
        "weight_historic": 18,
    },
    {
        "id": "cream-tile",
        "name": "Cream-tile shop",
        "window": "rect",
        "roof_kind": "mansard",
        "photos": ["ref_14.jpg", "ref_04.jpg", "ref_12.jpg"],
        "wall_bias": [0.82, 0.76, 0.62, 1.0],
        "bias_amount": 0.45,
        "weight_historic": 8,
    },
    {
        "id": "eclectic",
        "name": "Buff eclectic walk-up",
        "window": "rect",
        "roof_kind": "mansard",
        "photos": ["ref_01.jpg", "ref_04.jpg", "ref_15.jpg"],
        "wall_bias": [0.68, 0.58, 0.44, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 28,
    },
    {
        "id": "yellow-brick",
        "name": "Yellow-brick row",
        "window": "rect",
        "roof_kind": "gable",
        "photos": ["ref_07.jpg", "ref_09.jpg", "ref_05.jpg"],
        "wall_bias": [0.72, 0.55, 0.32, 1.0],
        "bias_amount": 0.45,
        "weight_historic": 7,
    },
    {
        "id": "art-nouveau",
        "name": "Art-Nouveau bay",
        "window": "arch",
        "roof_kind": "mansard",
        "photos": ["ref_05.jpg", "ref_07.jpg", "ref_21.jpg"],
        "wall_bias": [0.66, 0.54, 0.36, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 7,
    },
    {
        "id": "art-deco",
        "name": "Art-Deco pale",
        "window": "tall",
        "roof_kind": "flat",
        "photos": ["ref_03.jpg", "ref_13.jpg"],
        "wall_bias": [0.74, 0.70, 0.62, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 6,
    },
    {
        "id": "international",
        "name": "International modern",
        "window": "ribbon",
        "roof_kind": "flat",
        "photos": ["ref_20.jpg", "ref_13.jpg", "ref_19.jpg"],
        "wall_bias": [0.58, 0.58, 0.56, 1.0],
        "bias_amount": 0.35,
        "weight_historic": 4,
    },
    {
        "id": "modern-infill",
        "name": "Modern infill",
        "window": "ribbon",
        "roof_kind": "flat",
        "photos": ["ref_19.jpg", "ref_14.jpg"],
        "wall_bias": [0.82, 0.82, 0.78, 1.0],
        "bias_amount": 0.35,
        "weight_historic": 3,
    },
    {
        "id": "neo-gothic",
        "name": "Neo-Gothic stone",
        "window": "arch",
        "roof_kind": "hip",
        "photos": ["ref_14.jpg", "ref_08.jpg"],
        "wall_bias": [0.36, 0.32, 0.28, 1.0],
        "bias_amount": 0.45,
        "weight_historic": 0,
    },
    {
        "id": "white-modern",
        "name": "White modern slab",
        "window": "ribbon",
        "roof_kind": "flat",
        "photos": ["ref_19.jpg", "ref_20.jpg"],
        "wall_bias": [0.90, 0.89, 0.86, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 0,
    },
    {
        "id": "prefab-70s",
        "name": "Prefab 70s",
        "window": "ribbon",
        "roof_kind": "flat",
        "photos": ["ref_20.jpg", "ref_13.jpg"],
        "wall_bias": [0.58, 0.56, 0.50, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 0,
    },
    {
        "id": "brown-tile",
        "name": "Brown tile",
        "window": "rect",
        "roof_kind": "gable",
        "photos": ["ref_16.jpg", "ref_15.jpg"],
        "wall_bias": [0.36, 0.24, 0.18, 1.0],
        "bias_amount": 0.45,
        "weight_historic": 0,
    },
    {
        "id": "antwerp-70s",
        "name": "Antwerp 70s cream",
        "window": "rect",
        "roof_kind": "mansard",
        "photos": ["ref_12.jpg", "ref_04.jpg", "ref_18.jpg"],
        "wall_bias": [0.72, 0.66, 0.54, 1.0],
        "bias_amount": 0.4,
        "weight_historic": 0,
    },
]

VARIANT_COUNT = 3


def historic_weights() -> list[tuple[str, int]]:
    return [(spec["id"], int(spec["weight_historic"])) for spec in TYPE_SPECS if spec["weight_historic"] > 0]


def sample_reference_library(ref_dir: Path | None = None) -> dict[str, dict]:
    ref_dir = Path(ref_dir or REFERENCES_DIR)
    return {path.name: sample_photo(path) for path in sorted(ref_dir.glob("ref_*.jpg"))}


def build_types_document(ref_dir: Path | None = None) -> dict[str, Any]:
    samples = sample_reference_library(ref_dir)
    types: dict[str, Any] = {}
    for spec in TYPE_SPECS:
        photo_ids = [p for p in spec["photos"] if p in samples] or list(samples.keys())[:3]
        chosen = [samples[p] for p in photo_ids]
        type_seed = _stable_hash(spec["id"])
        bias = spec.get("wall_bias")
        bias_amt = float(spec.get("bias_amount") or 0.0)
        base = remix_palette(
            chosen, window=spec["window"], seed=type_seed & 0xFFFF, wall_bias=bias, bias_amount=bias_amt
        )
        variants = []
        for vi in range(VARIANT_COUNT):
            v = remix_palette(
                chosen,
                window=spec["window"],
                seed=(type_seed ^ (vi * 9973)) & 0xFFFF,
                wall_bias=bias,
                bias_amount=bias_amt,
            )
            v["wall"] = jitter_rgba(v["wall"], vi * 17 + 3, amount=0.035)
            variants.append({k: v[k] for k in ("wall", "roof", "frame", "glass", "plinth", "trim")})
        types[spec["id"]] = {
            "name": spec["name"],
            "window": spec["window"],
            "roof_kind": spec["roof_kind"],
            "photos": photo_ids,
            "weight_historic": spec["weight_historic"],
            "palette": {k: base[k] for k in ("wall", "roof", "frame", "glass", "plinth", "trim", "rough")},
            "variants": variants,
        }
    return {
        "title": "Klein Antwerpen building types (photo-remixed)",
        "references_dir": str(REFERENCES_DIR.relative_to(ROOT)),
        "variant_count": VARIANT_COUNT,
        "types": types,
        "photo_samples": {
            name: {
                "wall": s["wall"],
                "trim": s["trim"],
                "plinth": s["plinth"],
                "roof": s["roof"],
                "brightness": s["brightness"],
            }
            for name, s in samples.items()
        },
    }


def write_building_types(path: Path | None = None, ref_dir: Path | None = None) -> Path:
    path = Path(path or BUILDING_TYPES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_types_document(ref_dir=ref_dir), indent=2) + "\n")
    return path


def load_building_types(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or BUILDING_TYPES_PATH)
    if not path.exists():
        write_building_types(path)
    return json.loads(path.read_text())


def variant_index(osm_id: int, variant_count: int = VARIANT_COUNT) -> int:
    x = ((osm_id ^ 0xC0FFEE) * 1103515245 + 12345) & 0x7FFFFFFF
    return int((x / 0x7FFFFFFF) * variant_count) % max(1, variant_count)


def palette_for_building(type_id: str, osm_id: int, types_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = types_doc or load_building_types()
    entry = (doc.get("types") or {}).get(type_id) or (doc.get("types") or {}).get("eclectic")
    if not entry:
        raise KeyError(type_id)
    variants = entry.get("variants") or []
    base = dict(entry.get("palette") or {})
    if variants:
        base.update(variants[variant_index(osm_id, len(variants))])
    for key in ("wall", "plinth", "trim"):
        if key in base:
            base[key] = jitter_rgba(base[key], osm_id ^ (_stable_hash(key) & 0xFFFF), amount=0.02)
    base["window"] = entry.get("window", "rect")
    base["roof_kind"] = entry.get("roof_kind", "mansard")
    base["building_type"] = type_id
    base["variant"] = variant_index(osm_id, len(variants) or VARIANT_COUNT)
    return base


def attach_palettes(layout: dict[str, Any], types_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = types_doc or load_building_types()
    for bldg in layout.get("buildings") or []:
        type_id = bldg.get("building_type") or bldg.get("style") or "eclectic"
        bldg["building_type"] = type_id
        bldg["style"] = type_id
        pal = palette_for_building(type_id, int(bldg.get("id") or 0), doc)
        bldg["palette"] = {k: pal[k] for k in ("wall", "roof", "frame", "glass", "plinth", "trim", "window", "roof_kind")}
        bldg["type_variant"] = pal.get("variant", 0)
        if pal.get("roof_kind") and not bldg.get("roof_shape"):
            bldg["roof_shape"] = pal["roof_kind"]
    layout["building_types_path"] = str(BUILDING_TYPES_PATH)
    return layout
