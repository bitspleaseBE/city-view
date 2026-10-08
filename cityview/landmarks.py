"""Named church/hospital landmark photos + massing presets."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from cityview.paths import ASSETS

LANDMARKS_DIR = ASSETS / "landmarks"
MANIFEST_PATH = LANDMARKS_DIR / "manifest.json"

_MANIFEST_CACHE: dict[str, Any] | None = None


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_landmark_name(name: str) -> str:
    text = _strip_accents((name or "").strip().lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    global _MANIFEST_CACHE
    path = Path(path or MANIFEST_PATH)
    if _MANIFEST_CACHE is not None and path == MANIFEST_PATH:
        return _MANIFEST_CACHE
    if not path.exists():
        doc: dict[str, Any] = {"by_id": {}, "by_name": {}}
    else:
        doc = json.loads(path.read_text())
        doc.setdefault("by_id", {})
        doc.setdefault("by_name", {})
    if path == MANIFEST_PATH:
        _MANIFEST_CACHE = doc
    return doc


def clear_manifest_cache() -> None:
    global _MANIFEST_CACHE
    _MANIFEST_CACHE = None


def resolve_landmark_photo(entry: dict[str, Any], root: Path | None = None) -> Path | None:
    photo = entry.get("photo")
    if not photo:
        return None
    path = Path(photo)
    if not path.is_absolute():
        path = (root or LANDMARKS_DIR) / path
    return path if path.exists() else None


def match_landmark(
    osm_id: int,
    name: str,
    kind: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a landmark manifest entry for an OSM building, or None."""
    doc = manifest or load_manifest()
    by_id = doc.get("by_id") or {}
    hit = by_id.get(str(osm_id)) or by_id.get(osm_id)
    if isinstance(hit, dict):
        if kind and hit.get("kind") and hit["kind"] != kind:
            pass
        else:
            return dict(hit)

    norm = normalize_landmark_name(name)
    if not norm:
        return None
    by_name = doc.get("by_name") or {}
    hit = by_name.get(norm)
    if isinstance(hit, dict):
        if kind and hit.get("kind") and hit["kind"] != kind:
            return None
        return dict(hit)
    # Fuzzy: any key contained in name or vice versa.
    for key, entry in by_name.items():
        if not isinstance(entry, dict):
            continue
        if kind and entry.get("kind") and entry["kind"] != kind:
            continue
        if key in norm or norm in key:
            return dict(entry)
    return None


def attach_landmark(bldg: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mutate building with landmark_id / landmark fields when matched."""
    btype = bldg.get("building_type") or ""
    if btype not in {"church", "hospital"}:
        return bldg
    entry = match_landmark(int(bldg.get("id") or 0), str(bldg.get("name") or ""), btype, manifest)
    if not entry:
        return bldg
    bldg["landmark_id"] = entry.get("id") or entry.get("name") or str(bldg.get("id"))
    bldg["landmark"] = {
        "photo": entry.get("photo"),
        "crop": entry.get("crop") or [0.0, 0.0, 1.0, 1.0],
        "massing": entry.get("massing") or f"{btype}_default",
        "kind": entry.get("kind") or btype,
        "source_url": entry.get("source_url") or "",
    }
    return bldg
