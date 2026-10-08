from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_scene(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Scene file must be a JSON object: {path}")
    return data


def resolve_photo(root: Path, photo: str) -> Path:
    candidate = Path(photo)
    if not candidate.is_absolute():
        candidate = root / candidate
    if not candidate.exists():
        raise FileNotFoundError(f"Facade photo not found: {candidate}")
    return candidate.resolve()


def write_job(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def add_photo_building(
    scene: dict[str, Any],
    photo: Path,
    name: str,
    crop: list[float] | None = None,
) -> dict[str, Any]:
    """Insert or replace a photo-textured hero building in the street."""
    buildings = list(scene.get("buildings") or [])
    hero = {
        "name": name,
        "kind": "photo",
        "width": 7.4,
        "height": 12.4,
        "depth": 10.2,
        "photo": str(photo),
        "crop": crop or [0.0, 0.27, 0.805, 0.995],
        "style": "antwerp-70s",
        "parapet": 0.45,
        "shop_recess": 0.85,
    }
    replaced = False
    for i, building in enumerate(buildings):
        if building.get("kind") == "photo":
            buildings[i] = {**building, **hero}
            replaced = True
            break
    if not replaced:
        mid = len(buildings) // 2
        buildings.insert(mid, hero)
    scene["buildings"] = buildings
    return scene
