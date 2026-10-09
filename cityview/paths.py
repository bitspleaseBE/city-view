from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PHOTOS = ASSETS / "photos"
MAPS = ASSETS / "maps"
OSM_CACHE = ASSETS / "osm"
GTFS_CACHE = ASSETS / "gtfs"
TREES_CACHE = ASSETS / "trees"
BENCHES_CACHE = ASSETS / "benches"
VELO_CACHE = ASSETS / "velo"
SCENES = ROOT / "scenes"
BLENDER_SCRIPTS = ROOT / "blender"
OUTPUT = ROOT / "output"
VIEWER = ROOT / "viewer"

DEFAULT_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
DEFAULT_SCENE = SCENES / "antwerp_side_street.json"
DEFAULT_PLACES = SCENES / "antwerp_places.json"
