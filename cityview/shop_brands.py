"""Supermarket brand keys and fascia colours (no trademark logos)."""

from __future__ import annotations

from typing import Any

# brand_key → display label + fascia / accent RGBA
BRAND_FASCIA: dict[str, dict[str, Any]] = {
    "aldi": {
        "label": "ALDI",
        "fascia": (0.05, 0.22, 0.55, 1.0),
        "accent": (0.92, 0.45, 0.08, 1.0),
    },
    "lidl": {
        "label": "Lidl",
        "fascia": (0.05, 0.28, 0.62, 1.0),
        "accent": (0.95, 0.82, 0.08, 1.0),
    },
    "jumbo": {
        "label": "Jumbo",
        "fascia": (0.95, 0.78, 0.08, 1.0),
        "accent": (0.12, 0.12, 0.12, 1.0),
    },
    "carrefour": {
        "label": "Carrefour",
        "fascia": (0.05, 0.28, 0.62, 1.0),
        "accent": (0.85, 0.12, 0.14, 1.0),
    },
}

GENERIC_SUPERMARKET = {
    "label": "",
    "fascia": (0.28, 0.42, 0.34, 1.0),
    "accent": (0.72, 0.74, 0.70, 1.0),
}

_BRAND_ALIASES: list[tuple[str, str]] = [
    ("aldi", "aldi"),
    ("lidl", "lidl"),
    ("jumbo", "jumbo"),
    ("carrefour express", "carrefour"),
    ("carrefour market", "carrefour"),
    ("carrefour", "carrefour"),
]


def normalize_shop_brand(tags: dict[str, str]) -> str | None:
    """Map OSM brand/name tags to a known supermarket brand_key, or None."""
    for key in ("brand", "name", "operator"):
        raw = (tags.get(key) or "").strip().lower()
        if not raw:
            continue
        for needle, brand_key in _BRAND_ALIASES:
            if needle in raw:
                return brand_key
    return None


def fascia_for_brand(brand_key: str | None) -> dict[str, Any]:
    if brand_key and brand_key in BRAND_FASCIA:
        return dict(BRAND_FASCIA[brand_key])
    return dict(GENERIC_SUPERMARKET)
