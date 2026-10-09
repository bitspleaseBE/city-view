#!/usr/bin/env python3
"""Re-export viewer roads/buildings/transit/velo JSON without Blender.

``python3 -m cityview city`` writes these files as a side effect of the (slow) Blender
build. When only the road / transit / Velo / building graph changed, this re-runs the
exact same OSM -> layout -> GTFS -> Velo -> export steps and rewrites the JSON files.

    python3 scripts/export_viewer_data.py [--place klein-antwerpen]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cityview import cli  # noqa: E402
from cityview.gtfs_delijn import enrich_layout_transit  # noqa: E402
from cityview.jobs import load_scene  # noqa: E402
from cityview.osm import fetch_osm, layout_from_osm  # noqa: E402
from cityview.paths import VELO_CACHE  # noqa: E402
from cityview.streetscape import (  # noqa: E402
    export_buildings_near_spawn,
    export_roads_near_spawn,
    export_transit_near_spawn,
    spawn_from_place,
)
from cityview.velo import attach_velo, export_velo_for_viewer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", default="klein-antwerpen")
    parser.add_argument("--places", default=str(cli.DEFAULT_PLACES))
    parser.add_argument("--refresh", action="store_true", help="re-download Velo GBFS cache")
    args = parser.parse_args()

    place = load_scene(Path(args.places))[args.place]
    bbox = tuple(place["bbox"])
    origin = tuple(place.get("origin") or ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0))
    key = place.get("osm_cache") or args.place
    osm = fetch_osm(bbox, cli.OSM_CACHE / f"{key}.json")
    layout = layout_from_osm(osm, origin, style_policy=place.get("style_policy") or "default")
    enrich_layout_transit(layout, origin, bbox, cli.GTFS_CACHE / f"delijn_{key}.json")
    spawn = spawn_from_place(place, origin, layout)
    attach_velo(layout, bbox, origin, VELO_CACHE / f"{key}.json", refresh=bool(args.refresh))

    roads = export_roads_near_spawn(layout, spawn)
    buildings = export_buildings_near_spawn(layout, spawn)
    transit = export_transit_near_spawn(layout, spawn)
    velo = export_velo_for_viewer(layout.get("velo_stations") or [])
    (cli.VIEWER / "roads.json").write_text(json.dumps(roads) + "\n")
    (cli.VIEWER / "buildings.json").write_text(json.dumps(buildings) + "\n")
    (cli.VIEWER / "transit.json").write_text(json.dumps(transit) + "\n")
    (cli.VIEWER / "velo.json").write_text(json.dumps(velo) + "\n")
    if spawn:
        (cli.VIEWER / "spawn.json").write_text(json.dumps(spawn, indent=2) + "\n")

    one_way = sum(1 for r in roads["roads"] if r["oneway"])
    dual = sum(1 for r in roads["roads"] if r.get("dualCarriageway"))
    print(f"roads.json: {len(roads['roads'])} roads, {one_way} one-way, {dual} dual-carriageway halves")
    print(f"buildings.json: {len(buildings['buildings'])} footprints")
    for path in transit["paths"]:
        print(
            f"transit.json: {path['mode']:4s} {str(path['id']):32s} "
            f"direction={path['direction']:2d} ({path['directionSource']})"
        )
    print(f"velo.json: {len(velo['stations'])} stations")
    if spawn:
        print(f"spawn.json: {spawn.get('label')} ({spawn['lat']:.5f}, {spawn['lon']:.5f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
