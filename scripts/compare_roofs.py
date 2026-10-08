"""Compare a top-down render of the district (scripts/topdown_probe.html) with the aerial.

    python scripts/compare_roofs.py CDP_RESPONSE.json OUT.jpg [--aerial ...]

``CDP_RESPONSE.json`` is the saved ``Runtime.evaluate`` result of ``window.__probe.jpeg``
(or a bare ``data:image/jpeg;base64,...`` text file). Prints, over all OSM building
footprints (eroded), the median / mean roof colour of the render vs the orthophoto,
per roof family and overall, and writes a side-by-side JPEG (aerial | render).
Needs Pillow + numpy.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from cityview import aerial as A  # noqa: E402
from cityview import surface_kit as kit  # noqa: E402


def load_probe(path: Path) -> Image.Image:
    raw = path.read_text()
    try:
        doc = json.loads(raw)
        raw = doc["result"]["value"] if isinstance(doc, dict) and "result" in doc else doc
    except ValueError:
        pass
    b64 = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def building_colours(img: Image.Image, rings, bounds_size):
    """Median colour inside each eroded footprint (img covers the aerial bbox)."""
    arr = np.asarray(img).astype("float32") / 255.0
    w, h = img.size
    out = {}
    for bid, ring, _shape in rings:
        px = [A.local_to_pixel(x, y, (w, h)) for x, y in ring]
        xs, ys = [p[0] for p in px], [p[1] for p in px]
        x0, x1 = int(max(0, min(xs) - 1)), int(min(w, max(xs) + 2))
        y0, y1 = int(max(0, min(ys) - 1)), int(min(h, max(ys) + 2))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        m = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(m).polygon([(a - x0, b - y0) for a, b in px], fill=255)
        mask = np.asarray(m.filter(ImageFilter.MinFilter(3))) > 0
        c = arr[y0:y1, x0:x1][mask]
        if len(c) >= 8:
            out[bid] = np.median(c, axis=0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("probe")
    ap.add_argument("out")
    ap.add_argument("--aerial", default=str(A.AERIAL_JPG))
    args = ap.parse_args()

    render = load_probe(Path(args.probe))
    aer = Image.open(args.aerial).convert("RGB")
    size = render.size
    aer_small = aer.resize(size, Image.LANCZOS)
    rings = A._building_rings(A.OSM_CACHE / "harmonie.json")
    doc = kit.load_roof_aerial() or {}
    fam_of = {int(b): (doc.get("classes") or A.ROOF_CLASSES)[v[0]] for b, v in (doc.get("buildings") or {}).items()}

    ca = building_colours(aer_small, rings, size)
    cr = building_colours(render, rings, size)
    common = [b for b in ca if b in cr]

    def lum(c):
        return float(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])

    def report(label, ids):
        if not ids:
            return
        a = np.array([ca[b] for b in ids])
        r = np.array([cr[b] for b in ids])
        print(
            f"{label:10s} n={len(ids):4d}  aerial med RGB {(np.median(a, 0) * 255).astype(int).tolist()} "
            f"L={lum(np.median(a, 0)):.3f} | render med RGB {(np.median(r, 0) * 255).astype(int).tolist()} "
            f"L={lum(np.median(r, 0)):.3f} | mean|dL|={np.mean([abs(lum(ca[b]) - lum(cr[b])) for b in ids]):.3f}"
        )

    report("ALL", common)
    for fam in A.ROOF_CLASSES:
        report(fam, [b for b in common if fam_of.get(b) == fam])
    # Tint-gain hint: ratio of linear luminance (render / aerial) over sampled buildings.
    ids = [b for b in common if b in fam_of]
    if ids:
        la = np.median([A.srgb_to_linear(lum(ca[b])) for b in ids])
        lr = np.median([A.srgb_to_linear(lum(cr[b])) for b in ids])
        print(f"linear median L: aerial {la:.4f} render {lr:.4f} -> suggested RENDER_GAIN x {la / max(lr, 1e-6):.3f}")

    # Yards: pixels outside buildings, roads (+ pavements) and parks - the "ground" plane.
    from cityview.osm import layout_from_osm

    layout = layout_from_osm(json.loads((A.OSM_CACHE / "harmonie.json").read_text()), A.ORIGIN, style_policy="historic")
    w, h = size
    ym = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(ym)
    for b in layout["buildings"]:
        dr.polygon([A.local_to_pixel(x, y, size) for x, y in b["ring"]], fill=255)
    for g in layout["parks"] + layout["water"]:
        dr.polygon([A.local_to_pixel(x, y, size) for x, y in g["ring"]], fill=255)
    ppm = w / 1081.0
    for rd in layout["roads"]:
        dr.line([A.local_to_pixel(x, y, size) for x, y in rd["points"]], fill=255, width=max(1, int((rd["width"] + 7) * ppm)))
    yard = np.asarray(ym.filter(ImageFilter.MaxFilter(3))) == 0
    ya = np.asarray(aer_small).astype("float32")[yard] / 255.0
    yr = np.asarray(render).astype("float32")[yard] / 255.0
    print(
        f"yards      n={int(yard.sum()):6d}  aerial med RGB {(np.median(ya, 0) * 255).astype(int).tolist()} "
        f"L={lum(np.median(ya, 0)):.3f} | render med RGB {(np.median(yr, 0) * 255).astype(int).tolist()} "
        f"L={lum(np.median(yr, 0)):.3f}"
    )

    side = Image.new("RGB", (size[0] * 2, size[1]))
    side.paste(aer_small, (0, 0))
    side.paste(render, (size[0], 0))
    side.save(args.out, quality=88)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
