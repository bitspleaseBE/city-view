"""Download Microsoft Rocketbox avatars (MIT) used for the viewer's pedestrians.

Only the rig FBX, colour/normal/opacity textures and the in-place walk clips are fetched;
specular maps and the facial-blendshape FBX are skipped. Files land in assets/rocketbox/
(gitignored) and are skipped when already present.

Usage:
  python3 scripts/fetch_rocketbox.py            # every avatar in the roster
  python3 scripts/fetch_rocketbox.py Male_Adult_01 Female_Child_02
"""
from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rocketbox_roster import ANIMATIONS, source_avatars  # noqa: E402

REPO = "microsoft/Microsoft-Rocketbox"
RAW = f"https://raw.githubusercontent.com/{REPO}/master/"
TREE = f"https://api.github.com/repos/{REPO}/git/trees/master?recursive=1"
ANIM_DIR = "Assets/Animations/all_animations_max_motextr_xy/"
CACHE = Path(__file__).resolve().parents[1] / "assets" / "rocketbox"


def wanted(path: str, names: set[str]) -> bool:
    parts = path.split("/")
    if path.startswith(ANIM_DIR):
        return parts[-1].removesuffix(".max.fbx") in ANIMATIONS
    if len(parts) < 5 or not path.startswith("Assets/Avatars/") or parts[3] not in names:
        return False
    leaf = parts[-1]
    if parts[4] == "Export":
        return leaf == f"{parts[3]}.fbx"
    if parts[4] == "Textures":
        return leaf.removesuffix("_a.tga").removesuffix(".tga").endswith(("_color", "_normal"))
    return False


def target(path: str) -> Path:
    parts = path.split("/")
    if path.startswith(ANIM_DIR):
        dst = CACHE / "animations" / parts[-1]
    else:
        dst = CACHE / "avatars" / parts[3] / parts[-1]
    if not dst.resolve().is_relative_to(CACHE.resolve()):
        raise ValueError(f"refusing path outside the cache: {path}")
    return dst


def fetch(path: str) -> str:
    dst = target(path)
    if dst.exists() and dst.stat().st_size > 0:
        return f"have {dst.name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(RAW + path, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dst)
    return f"got  {dst.relative_to(CACHE)}"


def main() -> None:
    names = set(sys.argv[1:]) or set(source_avatars())
    with urllib.request.urlopen(TREE, timeout=60) as r:
        tree = json.load(r)["tree"]
    by_target = {}
    for x in tree:
        if x["type"] == "blob" and wanted(x["path"], names):
            by_target.setdefault(target(x["path"]), x["path"])
    paths = list(by_target.values())
    missing = names - {p.split("/")[3] for p in paths if "/Avatars/" in p}
    if missing:
        sys.exit(f"Unknown Rocketbox avatars: {sorted(missing)}")
    with ThreadPoolExecutor(8) as pool:
        for line in pool.map(fetch, paths):
            print(line)


if __name__ == "__main__":
    main()
