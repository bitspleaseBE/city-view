"""Shop / bank brand keys and fascia colours (no trademark logos — colour + label only)."""

from __future__ import annotations

import re
from typing import Any

# brand_key → display label + fascia / accent / glass RGBA + shopfront mood
BRAND_FASCIA: dict[str, dict[str, Any]] = {
    # Supermarkets (existing)
    "aldi": {
        "label": "ALDI",
        "fascia": (0.05, 0.22, 0.55, 1.0),
        "accent": (0.92, 0.45, 0.08, 1.0),
        "glass": (0.55, 0.65, 0.75, 1.0),
        "mood": "retail",
    },
    "lidl": {
        "label": "Lidl",
        "fascia": (0.05, 0.28, 0.62, 1.0),
        "accent": (0.95, 0.82, 0.08, 1.0),
        "glass": (0.55, 0.65, 0.75, 1.0),
        "mood": "retail",
    },
    "jumbo": {
        "label": "Jumbo",
        "fascia": (0.95, 0.78, 0.08, 1.0),
        "accent": (0.12, 0.12, 0.12, 1.0),
        "glass": (0.55, 0.65, 0.75, 1.0),
        "mood": "retail",
    },
    "carrefour": {
        "label": "Carrefour",
        "fascia": (0.05, 0.28, 0.62, 1.0),
        "accent": (0.85, 0.12, 0.14, 1.0),
        "glass": (0.55, 0.65, 0.75, 1.0),
        "mood": "retail",
    },
    # Belgian high-street banks — regional office look, muted corporate colours
    "belfius": {
        "label": "Belfius",
        "fascia": (0.55, 0.08, 0.42, 1.0),
        "accent": (1.0, 1.0, 1.0, 1.0),
        "glass": (0.72, 0.78, 0.85, 1.0),
        "mood": "bank",
    },
    "kbc": {
        "label": "KBC",
        "fascia": (0.00, 0.45, 0.28, 1.0),
        "accent": (0.95, 0.82, 0.10, 1.0),
        "glass": (0.70, 0.78, 0.82, 1.0),
        "mood": "bank",
    },
    "crelan": {
        "label": "Crelan",
        "fascia": (0.05, 0.38, 0.22, 1.0),
        "accent": (0.95, 0.95, 0.92, 1.0),
        "glass": (0.68, 0.76, 0.80, 1.0),
        "mood": "bank",
    },
    "bpost": {
        "label": "bpost bank",
        "fascia": (0.92, 0.55, 0.05, 1.0),
        "accent": (0.12, 0.12, 0.12, 1.0),
        "glass": (0.70, 0.75, 0.78, 1.0),
        "mood": "bank",
    },
    "ing": {
        "label": "ING",
        "fascia": (0.95, 0.55, 0.05, 1.0),
        "accent": (0.10, 0.10, 0.12, 1.0),
        "glass": (0.70, 0.75, 0.80, 1.0),
        "mood": "bank",
    },
    "argenta": {
        "label": "Argenta",
        "fascia": (0.72, 0.08, 0.18, 1.0),
        "accent": (1.0, 1.0, 1.0, 1.0),
        "glass": (0.70, 0.76, 0.82, 1.0),
        "mood": "bank",
    },
    "bnp": {
        "label": "BNP Paribas Fortis",
        "fascia": (0.05, 0.22, 0.55, 1.0),
        "accent": (0.85, 0.12, 0.18, 1.0),
        "glass": (0.70, 0.76, 0.82, 1.0),
        "mood": "bank",
    },
}

# Hipster Antwerp café defaults (rotated by shop id) — no brand needed
CAFE_PALETTES: list[dict[str, Any]] = [
    {
        "fascia": (0.14, 0.22, 0.18, 1.0),
        "accent": (0.92, 0.78, 0.42, 1.0),
        "glass": (0.55, 0.48, 0.38, 1.0),
        "mood": "cafe",
    },
    {
        "fascia": (0.42, 0.12, 0.14, 1.0),
        "accent": (0.94, 0.88, 0.72, 1.0),
        "glass": (0.48, 0.42, 0.36, 1.0),
        "mood": "cafe",
    },
    {
        "fascia": (0.18, 0.16, 0.14, 1.0),
        "accent": (0.85, 0.55, 0.28, 1.0),
        "glass": (0.42, 0.40, 0.36, 1.0),
        "mood": "cafe",
    },
    {
        "fascia": (0.12, 0.28, 0.32, 1.0),
        "accent": (0.90, 0.82, 0.62, 1.0),
        "glass": (0.45, 0.50, 0.48, 1.0),
        "mood": "cafe",
    },
]

GENERIC_SUPERMARKET = {
    "label": "",
    "fascia": (0.28, 0.42, 0.34, 1.0),
    "accent": (0.72, 0.74, 0.70, 1.0),
    "glass": (0.55, 0.65, 0.75, 1.0),
    "mood": "retail",
}

GENERIC_BANK = {
    "label": "",
    "fascia": (0.12, 0.18, 0.28, 1.0),
    "accent": (0.90, 0.90, 0.88, 1.0),
    "glass": (0.70, 0.76, 0.82, 1.0),
    "mood": "bank",
}

_BRAND_ALIASES: list[tuple[str, str]] = [
    ("aldi", "aldi"),
    ("lidl", "lidl"),
    ("jumbo", "jumbo"),
    ("carrefour express", "carrefour"),
    ("carrefour market", "carrefour"),
    ("carrefour", "carrefour"),
    ("belfius", "belfius"),
    ("kbc brussels", "kbc"),
    ("kbc", "kbc"),
    ("crelan", "crelan"),
    ("bpost bank", "bpost"),
    ("bpost", "bpost"),
    ("ing bank", "ing"),
    ("ing", "ing"),
    ("argenta", "argenta"),
    ("bnp paribas fortis", "bnp"),
    ("bnp paribas", "bnp"),
    ("fortis", "bnp"),
]
# Bank keys must not hitch a ride on everyday words ("Voeding", "Printing", …).
_BANK_BRANDS = frozenset({"belfius", "kbc", "crelan", "bpost", "ing", "argenta", "bnp"})


def _phrase_in_text(needle: str, text: str) -> bool:
    """True when ``needle`` appears as whole word(s), not a substring of a longer token."""
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text) is not None


def normalize_shop_brand(tags: dict[str, str]) -> str | None:
    """Map OSM brand/name/operator tags to a known brand_key, or None."""
    amenity = (tags.get("amenity") or "").lower()
    shop = (tags.get("shop") or "").lower()
    is_bank = amenity == "bank" or shop == "bank"
    for key in ("brand", "operator", "name"):
        raw = (tags.get(key) or "").strip().lower()
        if not raw:
            continue
        name_says_bank = key == "name" and _phrase_in_text("bank", raw)
        for needle, brand_key in _BRAND_ALIASES:
            if not _phrase_in_text(needle, raw):
                continue
            # Bank fascia only for real banks, brand=/operator=, or a name that says "bank".
            if brand_key in _BANK_BRANDS and key == "name" and not is_bank and not name_says_bank:
                continue
            return brand_key
    return None


def fascia_for_brand(brand_key: str | None) -> dict[str, Any]:
    if brand_key and brand_key in BRAND_FASCIA:
        return dict(BRAND_FASCIA[brand_key])
    return dict(GENERIC_SUPERMARKET)


def shopfront_style(
    tags: dict[str, str] | None,
    kind: str,
    category: str,
    shop_id: int = 0,
) -> dict[str, Any]:
    """Viewer / Blender shopfront look: brand when known, else mood from kind."""
    tags = tags or {}
    brand = normalize_shop_brand(tags)
    if brand and brand in BRAND_FASCIA:
        out = dict(BRAND_FASCIA[brand])
        out["brand"] = brand
        return out
    if kind == "bank" or category == "service" and kind == "bank":
        out = dict(GENERIC_BANK)
        out["label"] = (tags.get("name") or tags.get("brand") or "Bank")[:22]
        out["brand"] = None
        return out
    if kind in {"cafe", "coffee"} or (category == "horeca" and kind in {"cafe", "bar"}):
        out = dict(CAFE_PALETTES[shop_id % len(CAFE_PALETTES)])
        out["label"] = (tags.get("name") or tags.get("brand") or "")[:22]
        out["brand"] = None
        return out
    if kind == "supermarket" or category == "food" and kind == "supermarket":
        return dict(GENERIC_SUPERMARKET)
    return {
        "label": (tags.get("name") or "")[:22],
        "fascia": (0.22, 0.18, 0.16, 1.0),
        "accent": (0.92, 0.84, 0.62, 1.0),
        "glass": (0.50, 0.48, 0.44, 1.0),
        "mood": "retail",
        "brand": None,
    }
