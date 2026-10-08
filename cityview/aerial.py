"""Aerial orthophoto of Klein Antwerpen / Harmonie + per-building roof colour sampling.

Source: Digitaal Vlaanderen "Orthofotomozaïek, middenschalig, winteropnamen"
(WMS ``https://geo.api.vlaanderen.be/OMW/wms``, layer ``OMWRGB25VL`` = winter 2025, 15 cm),
free to use under the Gebruiksrecht geografische webdiensten
(https://www.vlaanderen.be/digitaal-vlaanderen/onze-oplossingen/geografische-webdiensten/gebruiksrecht-en-privacyverklaring-geografische-webdiensten).

Needs Pillow + numpy (dev tools only; the outputs are committed so CI only needs Blender):

    python -m cityview.aerial fetch      # download tiles, store assets/references/klein-antwerpen/aerial_ortho.jpg
    python -m cityview.aerial sample     # sample every building's roof -> assets/styles/roof_aerial.json

The pure-Python helpers (colour classification, clustering, pixel <-> metre mapping) have
no third-party imports so they are unit-testable (see ``cityview/test_aerial.py``).
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, Sequence

from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon
from cityview.paths import ASSETS, OSM_CACHE

WMS_URL = "https://geo.api.vlaanderen.be/OMW/wms"
WMS_LAYER = "OMWRGB25VL"
SOURCE_NOTE = (
    "Digitaal Vlaanderen, Orthofotomozaïek middenschalig winteropname 2025 (OMWRGB25VL, 15 cm), "
    "gratis gebruiksrecht geografische webdiensten"
)

# Klein Antwerpen / Harmonie tile (south, west, north, east) and projection origin.
BBOX = (51.1970, 4.4040, 51.2075, 4.4195)
ORIGIN = (51.2017, 4.4114)
TILES = 4  # fetch TILES x TILES WMS requests (server caps image size)
TILE_PX = 560

AERIAL_DIR = ASSETS / "references" / "klein-antwerpen"
AERIAL_JPG = AERIAL_DIR / "aerial_ortho.jpg"
ROOF_JSON = ASSETS / "styles" / "roof_aerial.json"
SURFACES_DIR = ASSETS / "surfaces"

LIT_BAND = (50, 92)  # luma percentiles (inside a footprint) treated as the sunlit roof surface

ROOF_CLASSES = ("roof_slate", "roof_clay", "roof_zinc", "roof_flat")


# --- pure helpers -----------------------------------------------------------------------


def latlon_to_pixel(lat: float, lon: float, size: tuple[int, int], bbox=BBOX) -> tuple[float, float]:
    """Lat/lon -> (col, row) in an image covering ``bbox`` (plate carrée, north up)."""
    south, west, north, east = bbox
    w, h = size
    return (lon - west) / (east - west) * w, (north - lat) / (north - south) * h


def local_to_pixel(x: float, y: float, size: tuple[int, int], bbox=BBOX, origin=ORIGIN) -> tuple[float, float]:
    """Local metres (east, north from ``origin``) -> aerial pixel (col, row)."""
    lat = origin[0] + y / METERS_PER_DEG_LAT
    lon = origin[1] + x / meters_per_deg_lon(origin[0])
    return latlon_to_pixel(lat, lon, size, bbox)


def is_vegetation(rgb: Sequence[float]) -> bool:
    """Tree crowns / garden roofs: green clearly leads both red and blue."""
    r, g, b = rgb
    return g > r * 1.04 and g > b * 1.10


CLAY_WARM_FRAC = 0.06  # >= 6 % clearly warm (red/orange) pixels inside a footprint -> pantile roof
SLATE_MAX_LUMA = 0.50  # sunlit grey darker than this = slate / dark tile; lighter = zinc / fibre-cement


def luma(rgb: Sequence[float]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def classify_roof(rgb: Sequence[float], shape: str, warm_frac: float = 0.0) -> str:
    """Map a sampled roof to one of the surface-kit roof families.

    ``rgb`` is the sunlit-slope median (0-1 sRGB); ``warm_frac`` is the share of the
    footprint that is clearly red/orange (a lit pantile slope covers only part of it).
    """
    if shape == "flat":
        return "roof_flat"
    if warm_frac >= CLAY_WARM_FRAC:
        return "roof_clay"
    return "roof_slate" if luma(rgb) < SLATE_MAX_LUMA else "roof_zinc"


def reduce_sky_cast(rgb: Sequence[float], strength: float = 0.6) -> list[float]:
    """Tone down the blue skylight cast of shaded roofs (shade in the orthophoto is lit by blue
    sky only: dark slate reads RGB 40/60/90). Chroma shrinks toward the luma by up to
    ``strength`` as blue exceeds red; warm / sunlit colours pass through unchanged."""
    r, g, b = rgb
    excess = max(0.0, b - r)
    k = 1.0 - strength * min(1.0, excess / 0.25)
    y = luma(rgb)
    return [min(1.0, max(0.0, y + (c - y) * k)) for c in (r, g, b)]


def kmeans(points: Sequence[Sequence[float]], k: int, iters: int = 24) -> tuple[list[list[float]], list[int]]:
    """Tiny deterministic k-means (farthest-first seeding) for 3-D colours."""
    pts = [list(map(float, p)) for p in points]
    if not pts:
        return [], []
    k = max(1, min(k, len(pts)))
    # Seed: mean-closest first, then farthest-first (deterministic).
    mean = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
    first = min(range(len(pts)), key=lambda i: sum((pts[i][c] - mean[c]) ** 2 for c in range(3)))
    centres = [pts[first][:]]
    while len(centres) < k:
        far = max(
            range(len(pts)),
            key=lambda i: min(sum((pts[i][c] - ctr[c]) ** 2 for c in range(3)) for ctr in centres),
        )
        centres.append(pts[far][:])
    assign = [0] * len(pts)
    for _ in range(iters):
        changed = False
        for i, p in enumerate(pts):
            best = min(range(k), key=lambda j: sum((p[c] - centres[j][c]) ** 2 for c in range(3)))
            if best != assign[i]:
                assign[i] = best
                changed = True
        for j in range(k):
            members = [pts[i] for i in range(len(pts)) if assign[i] == j]
            if members:
                centres[j] = [sum(m[c] for m in members) / len(members) for c in range(3)]
        if not changed:
            break
    return centres, assign


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# Linear-light multiplier between "aerial colour" and the albedo we put on the model, set by
# comparing the viewer's top-down render with the orthophoto (see README, "Roof colours").
RENDER_GAIN = 0.17


def tint_for(target_srgb: Sequence[float], tex_mean_linear: Sequence[float], gain: float = RENDER_GAIN) -> list[float]:
    """Linear Base-Color multiplier taking a roof texture to ``target_srgb``.

    glTF baseColorFactor is capped at 1, so the roof textures are bright neutral detail
    maps (cityview/surface_textures.py) and the tint carries the aerial colour.
    """
    out = []
    for t, m in zip(target_srgb, tex_mean_linear):
        out.append(round(min(1.0, max(0.004, srgb_to_linear(t) * gain / max(m, 1e-3))), 4))
    return out


# --- imaging (Pillow / numpy) ---------------------------------------------------------------


def _need_imaging():
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - dev tool message
        raise SystemExit("Pillow + numpy are required: pip install pillow numpy") from exc


def wms_url(bbox: tuple[float, float, float, float], width: int, height: int) -> str:
    q = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": WMS_LAYER,
        "styles": "",
        "crs": "EPSG:4326",  # WMS 1.3.0: axis order lat,lon
        "bbox": ",".join(f"{v:.7f}" for v in bbox),
        "width": str(width),
        "height": str(height),
        "format": "image/png",
    }
    return f"{WMS_URL}?{urllib.parse.urlencode(q, safe=',:')}"


def fetch_aerial(out: Path = AERIAL_JPG, jpeg_quality: int = 82):
    """Download the district orthophoto tile by tile and store one moderate JPEG."""
    _need_imaging()
    import io

    from PIL import Image

    south, west, north, east = BBOX
    dlat = (north - south) / TILES
    dlon = (east - west) / TILES
    full = Image.new("RGB", (TILES * TILE_PX, TILES * TILE_PX))
    for ty in range(TILES):
        for tx in range(TILES):
            t_north = north - ty * dlat
            t_south = t_north - dlat
            t_west = west + tx * dlon
            url = wms_url((t_south, t_west, t_north, t_west + dlon), TILE_PX, TILE_PX)
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            tile = Image.open(io.BytesIO(data)).convert("RGB")  # raises on a WMS XML error
            full.paste(tile, (tx * TILE_PX, ty * TILE_PX))
    out.parent.mkdir(parents=True, exist_ok=True)
    full.save(out, quality=jpeg_quality, optimize=True)
    return out


def _building_rings(osm_path: Path, origin=ORIGIN) -> list[tuple[int, list[tuple[float, float]], str]]:
    """(osm id, ring in local metres, roof:shape tag) for each OSM building way."""
    from cityview.osm import layout_from_osm

    osm = json.loads(osm_path.read_text())
    layout = layout_from_osm(osm, origin, style_policy="historic")
    return [(int(b["id"]), [tuple(p) for p in b["ring"]], b.get("roof_shape") or "mansard") for b in layout["buildings"]]


def sample_roofs(
    aerial: Path = AERIAL_JPG,
    osm_path: Path = OSM_CACHE / "harmonie.json",
    k_per_class: int = 5,
) -> dict:
    """Sample each building's roof from the aerial and cluster tints per roof family."""
    _need_imaging()
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.open(aerial).convert("RGB")
    arr = np.asarray(img).astype("float32") / 255.0
    w, h = img.size
    samples: list[tuple[int, str, list[float], str]] = []
    skipped = {"tiny": 0, "vegetation": 0, "no_pixels": 0}
    for bid, ring, shape in _building_rings(OSM_CACHE / "harmonie.json" if osm_path is None else osm_path):
        px = [local_to_pixel(x, y, (w, h)) for x, y in ring]
        xs = [p[0] for p in px]
        ys = [p[1] for p in px]
        x0, x1 = int(max(0, math.floor(min(xs)) - 1)), int(min(w, math.ceil(max(xs)) + 2))
        y0, y1 = int(max(0, math.floor(min(ys)) - 1)), int(min(h, math.ceil(max(ys)) + 2))
        if x1 - x0 < 6 or y1 - y0 < 6:
            skipped["tiny"] += 1
            continue
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(px_ - x0, py_ - y0) for px_, py_ in px], fill=255)
        # Shrink ~1 m (orthophoto lean + eaves) so street / neighbour pixels stay out.
        mask = mask.filter(ImageFilter.MinFilter(5))
        m = np.asarray(mask) > 0
        crop = arr[y0:y1, x0:x1][m]
        if len(crop) < 12:
            skipped["no_pixels"] += 1
            continue
        lum = crop @ np.array([0.2126, 0.7152, 0.0722], dtype="float32")
        # Winter low sun: the shaded slope is lit by blue skylight only (a strong blue cast),
        # so sample the sunlit half and drop blown-out highlights (skylights, glints).
        keep = (lum >= np.percentile(lum, LIT_BAND[0])) & (lum <= np.percentile(lum, LIT_BAND[1]))
        crop = crop[keep] if keep.sum() >= 8 else crop
        rgb = np.median(crop, axis=0)
        # Share of clearly warm (red / orange) pixels over the whole eroded footprint.
        full = arr[y0:y1, x0:x1][m]
        mx, mn = full.max(axis=1), full.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1e-3)
        warm = (full[:, 0] - full[:, 2]) / np.maximum(full[:, 0], 1e-3)
        warm_px = (warm > 0.20) & (sat > 0.20) & (mx > 0.30) & (full[:, 0] > full[:, 1] * 1.04)
        warm_frac = float(warm_px.mean())
        cls = classify_roof(rgb, shape, warm_frac)
        if cls == "roof_clay":
            rgb = np.median(full[warm_px], axis=0) if warm_px.sum() >= 4 else rgb
        elif is_vegetation(rgb):
            skipped["vegetation"] += 1
            continue
        if cls != "roof_clay":
            rgb = reduce_sky_cast(rgb)
        samples.append((bid, cls, [float(c) for c in rgb], shape))

    # Texture means so each cluster centre becomes a bounded multiplicative tint.
    tex_means: dict[str, list[float]] = {}
    for key in ROOF_CLASSES:
        tex = SURFACES_DIR / f"{key}.jpg"
        if tex.exists():
            t = np.asarray(Image.open(tex).convert("RGB")).astype("float32") / 255.0
            lin = np.where(t <= 0.04045, t / 12.92, ((t + 0.055) / 1.055) ** 2.4)
            tex_means[key] = [float(c) for c in lin.reshape(-1, 3).mean(axis=0)]

    families: dict[str, dict] = {}
    buildings: dict[str, list[int]] = {}
    for key in ROOF_CLASSES:
        members = [(bid, c) for bid, cls, c, _shape in samples if cls == key]
        if not members:
            continue
        centres, assign = kmeans([c for _, c in members], k_per_class)
        counts = [assign.count(j) for j in range(len(centres))]
        # Order clusters dark -> light so indices are stable and readable.
        order = sorted(range(len(centres)), key=lambda j: sum(centres[j]))
        rank = {j: i for i, j in enumerate(order)}
        tm = tex_means.get(key, [0.5, 0.5, 0.5])
        families[key] = {
            "count": len(members),
            "tex_mean_linear": [round(c, 4) for c in tm],
            "clusters": [
                {
                    "colour": [round(c, 3) for c in centres[j]],
                    "tint": tint_for(centres[j], tm),
                    "count": counts[j],
                }
                for j in order
            ],
        }
        for (bid, _), a in zip(members, assign):
            buildings[str(bid)] = [ROOF_CLASSES.index(key), rank[a]]

    total = sum(f["count"] for f in families.values())
    mix_by_shape: dict[str, dict[str, float]] = {}
    for shp in sorted({sh for *_rest, sh in samples}):
        cls_list = [c for _b, c, _rgb, sh in samples if sh == shp]
        mix_by_shape[shp] = {k: round(cls_list.count(k) / len(cls_list), 3) for k in ROOF_CLASSES if k in cls_list}
    return {
        "source": SOURCE_NOTE,
        "wms_layer": WMS_LAYER,
        "image": str(aerial.relative_to(ASSETS.parent)) if aerial.is_relative_to(ASSETS.parent) else str(aerial),
        "sampled": total,
        "skipped": skipped,
        "mix": {k: round(f["count"] / total, 3) for k, f in families.items()} if total else {},
        "classes": list(ROOF_CLASSES),
        "render_gain": RENDER_GAIN,
        "mix_by_shape": mix_by_shape,
        "families": families,
        "buildings": buildings,
    }


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fetch", "sample"])
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "fetch":
        p = fetch_aerial()
        print(f"Wrote {p} ({p.stat().st_size // 1024} KiB)")
    else:
        doc = sample_roofs()
        ROOF_JSON.parent.mkdir(parents=True, exist_ok=True)
        ROOF_JSON.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
        print(f"Wrote {ROOF_JSON} ({ROOF_JSON.stat().st_size // 1024} KiB): sampled {doc['sampled']}, mix {doc['mix']}, skipped {doc['skipped']}")
        for key, fam in doc["families"].items():
            print(key, fam["count"])
            for c in fam["clusters"]:
                print("   ", c["count"], [int(v * 255) for v in c["colour"]], "tint", c["tint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
