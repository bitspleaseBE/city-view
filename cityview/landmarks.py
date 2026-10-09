"""Landmark manifest: church massing presets and hand-modelled mesh landmarks.

Churches use extruded OSM footprints with pitched roofs, portals, and parametric
towers/spires from ``massing`` — mesh + tiling brick/stone/slate only (no facade
photographs). Church photos in the manifest are reference/attribution only.
Heilige Geestkerk uses ``neo_romanesque_tower_left`` (square tower + round turret).

Entries with ``custom`` are built by ``cityview.landmark_models`` (ZAS
Sint-Vincentius, Feestzaal Harmonie, ...); manifest ``nodes`` are free-standing
monuments. Photos listed for them are references only, never textures.
"""

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


def custom_landmark_entry(osm_id: int, manifest: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Manifest entry with a ``custom`` mesh builder for this OSM id (ids only, no fuzzy names)."""
    doc = manifest or load_manifest()
    hit = (doc.get("by_id") or {}).get(str(osm_id))
    if isinstance(hit, dict) and hit.get("custom"):
        return dict(hit)
    return None


def _anchor_xy(entry: dict[str, Any], origin: tuple[float, float] | None) -> list[float] | None:
    anchor = entry.get("anchor")
    if not anchor or origin is None:
        return None
    from cityview.geo import project

    x, y = project(float(anchor[0]), float(anchor[1]), origin[0], origin[1])
    return [round(x, 3), round(y, 3)]


def _project_params(params: dict[str, Any], origin: tuple[float, float] | None) -> dict[str, Any]:
    """Copy params; every ``<name>_at`` [lat, lon] pair also gets a local ``<name>_xy``."""
    out = dict(params)
    for key, val in params.items():
        if key.endswith("_at") and isinstance(val, (list, tuple)) and len(val) == 2:
            xy = _anchor_xy({"anchor": val}, origin)
            if xy is not None:
                out[key[:-3] + "_xy"] = xy
    return out


def attach_custom_landmark(
    bldg: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    origin: tuple[float, float] | None = None,
) -> bool:
    """Tag a building for a hand-modelled mesh landmark (any building type)."""
    entry = custom_landmark_entry(int(bldg.get("id") or 0), manifest)
    if not entry:
        return False
    bldg["landmark_id"] = entry.get("id") or str(bldg.get("id"))
    bldg["landmark"] = {
        "custom": entry["custom"],
        "kind": entry.get("kind") or bldg.get("building_type") or "",
        "name": entry.get("name") or "",
        "source_url": entry.get("source_url") or "",
        "anchor_xy": _anchor_xy(entry, origin),
        "params": _project_params(entry.get("params") or {}, origin),
    }
    for key in ("levels", "height_m", "roof_height_m", "roof_shape"):
        if key in entry:
            bldg["landmark"][key] = entry[key]
    if entry.get("name") and not bldg.get("name"):
        bldg["name"] = entry["name"]
    return True


def landmark_nodes(
    nodes: dict[int, dict[str, Any]],
    origin: tuple[float, float],
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Free-standing point landmarks (monuments) listed under ``nodes`` in the manifest."""
    from cityview.geo import project

    doc = manifest or load_manifest()
    out: list[dict[str, Any]] = []
    for key, entry in sorted((doc.get("nodes") or {}).items()):
        node = nodes.get(int(key))
        if not node or not isinstance(entry, dict) or not entry.get("custom"):
            continue
        x, y = project(float(node["lat"]), float(node["lon"]), origin[0], origin[1])
        out.append(
            {
                "id": int(key),
                "x": round(x, 3),
                "y": round(y, 3),
                "name": entry.get("name") or (node.get("tags") or {}).get("name") or "",
                "custom": entry["custom"],
                "facing_xy": _anchor_xy({"anchor": entry.get("facing")}, origin),
                "params": _project_params(entry.get("params") or {}, origin),
            }
        )
    return out


def attach_landmark(
    bldg: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    origin: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Mutate building with landmark_id / landmark fields when matched."""
    if attach_custom_landmark(bldg, manifest, origin):
        return bldg
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
