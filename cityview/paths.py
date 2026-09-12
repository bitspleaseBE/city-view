from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PHOTOS = ASSETS / "photos"
SCENES = ROOT / "scenes"
BLENDER_SCRIPTS = ROOT / "blender"
OUTPUT = ROOT / "output"
VIEWER = ROOT / "viewer"

DEFAULT_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
DEFAULT_SCENE = SCENES / "antwerp_side_street.json"
