from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cityview.jobs import add_photo_building, load_scene, resolve_photo, write_job
from cityview.osm import fetch_osm, layout_from_osm
from cityview.paths import (
    BLENDER_SCRIPTS,
    DEFAULT_BLENDER,
    DEFAULT_PLACES,
    DEFAULT_SCENE,
    OSM_CACHE,
    OUTPUT,
    ROOT,
    VIEWER,
)


def blender_bin() -> Path:
    override = os.environ.get("BLENDER_BIN")
    if override:
        return Path(override)
    return DEFAULT_BLENDER


def run_blender(job_path: Path, script: Path) -> None:
    binary = blender_bin()
    if not binary.exists():
        raise FileNotFoundError(
            f"Blender not found at {binary}. Set BLENDER_BIN to the Blender executable."
        )
    cmd = [
        str(binary),
        "--background",
        "--python",
        str(script),
        "--",
        "--job",
        str(job_path),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def build_command(args: argparse.Namespace) -> int:
    scene = load_scene(Path(args.scene))
    if args.photo:
        photo = resolve_photo(ROOT, args.photo)
        crop = [float(v) for v in args.crop.split(",")] if args.crop else None
        if crop is not None and len(crop) != 4:
            raise ValueError("--crop must be u0,v0,u1,v1 in 0-1 image space")
        scene = add_photo_building(scene, photo, args.name, crop)

    output_dir = Path(args.out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    job_path = output_dir / "job.json"
    write_job(
        job_path,
        {
            "root": str(ROOT),
            "output_dir": str(output_dir),
            "scene_name": args.street_name,
            "export_blend": True,
            "export_glb": True,
            "render": not args.no_render,
            "scene": scene,
        },
    )
    run_blender(job_path, BLENDER_SCRIPTS / "build_scene.py")

    glb = output_dir / f"{args.street_name}.glb"
    if glb.exists():
        dest = VIEWER / "antwerp_street.glb"
        shutil.copy2(glb, dest)
        print(f"Copied {glb} -> {dest}")
    print(f"Outputs in {output_dir}")
    return 0


def city_command(args: argparse.Namespace) -> int:
    places = load_scene(Path(args.places))
    if args.bbox:
        parts = [float(v) for v in args.bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("--bbox must be south,west,north,east")
        bbox = (parts[0], parts[1], parts[2], parts[3])
        origin = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        place_name = args.place or "custom"
    else:
        place_name = args.place or "centrum"
        place = places.get(place_name)
        if not place:
            known = ", ".join(sorted(places))
            raise ValueError(f"Unknown place {place_name!r}. Known: {known}")
        bbox = tuple(place["bbox"])
        origin = tuple(place.get("origin") or ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0))

    cache = OSM_CACHE / f"{place_name}.json"
    if args.refresh and cache.exists():
        cache.unlink()
    osm = fetch_osm(bbox, cache)
    layout = layout_from_osm(osm, origin)
    print(
        f"{place_name}: {len(layout['buildings'])} buildings, "
        f"{len(layout['roads'])} roads, {len(layout['water'])} water polygons"
    )

    output_dir = Path(args.out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_name = args.street_name or f"antwerp_{place_name}"
    layout_path = output_dir / f"{scene_name}_layout.json"
    layout_path.write_text(json.dumps(layout))
    job_path = output_dir / f"{scene_name}_job.json"
    write_job(
        job_path,
        {
            "root": str(ROOT),
            "output_dir": str(output_dir),
            "scene_name": scene_name,
            "render": not args.no_render,
            "layout_path": str(layout_path),
        },
    )
    run_blender(job_path, BLENDER_SCRIPTS / "build_city.py")
    glb = output_dir / f"{scene_name}.glb"
    if glb.exists():
        dest = VIEWER / "antwerp_street.glb"
        shutil.copy2(glb, dest)
        print(f"Copied {glb} -> {dest}")
    print(f"Outputs in {output_dir}")
    return 0


def serve_command(args: argparse.Namespace) -> int:
    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

    os.chdir(VIEWER)
    server = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    print(f"Street viewer at http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an Antwerp 70s-80s street in Blender from facade photos."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Generate the street .blend, .glb, and preview render")
    build.add_argument("--scene", default=str(DEFAULT_SCENE), help="Street JSON preset")
    build.add_argument("--photo", help="Replace the hero building with this facade photo")
    build.add_argument("--name", default="r-maes-15", help="Name for a --photo building")
    build.add_argument(
        "--crop",
        help="Optional UV crop u0,v0,u1,v1 (Blender UV space, origin bottom-left)",
    )
    build.add_argument("--out", default=str(OUTPUT), help="Output directory")
    build.add_argument("--street-name", default="antwerp_street")
    build.add_argument("--no-render", action="store_true")
    build.set_defaults(func=build_command)

    serve = sub.add_parser("serve", help="Serve the Three.js street viewer")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=serve_command)

    city = sub.add_parser("city", help="Build an Antwerp district from OpenStreetMap")
    city.add_argument("--place", default="centrum", help="Preset from scenes/antwerp_places.json")
    city.add_argument("--places", default=str(DEFAULT_PLACES))
    city.add_argument("--bbox", help="south,west,north,east in WGS84")
    city.add_argument("--out", default=str(OUTPUT))
    city.add_argument("--street-name", default="")
    city.add_argument("--refresh", action="store_true", help="Ignore cached OSM download")
    city.add_argument("--no-render", action="store_true")
    city.set_defaults(func=city_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
