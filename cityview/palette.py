"""Sample dominant facade colours from reference photos (Pillow or macOS sips)."""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Iterable


RGBA = tuple[float, float, float, float]
RGB = tuple[float, float, float]


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _rgb8_to_f(r: int, g: int, b: int) -> RGB:
    return (r / 255.0, g / 255.0, b / 255.0)


def _luma(rgb: RGB) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _sat(rgb: RGB) -> float:
    return max(rgb) - min(rgb)


def _decode_png_scanlines(path: Path) -> list[RGB]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    pos = 8
    width = height = None
    color_type = None
    raw = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, *_ = struct.unpack(">IIBBBBB", chunk)
            if bit_depth != 8 or color_type not in (2, 6):
                raise ValueError(f"unsupported PNG mode bit={bit_depth} type={color_type}")
        elif ctype == b"IDAT":
            raw.extend(chunk)
        elif ctype == b"IEND":
            break
    if width is None or height is None or color_type is None:
        raise ValueError("incomplete PNG")
    pixels = zlib.decompress(bytes(raw))
    bpp = 3 if color_type == 2 else 4
    stride = width * bpp
    prev = bytearray(stride)
    out: list[RGB] = []
    offset = 0

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    for _y in range(height):
        filt = pixels[offset]
        offset += 1
        row = bytearray(pixels[offset : offset + stride])
        offset += stride
        if filt == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) // 2)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i]
                up_left = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + paeth(left, up, up_left)) & 0xFF
        for x in range(width):
            i = x * bpp
            out.append(_rgb8_to_f(row[i], row[i + 1], row[i + 2]))
        prev = row
    return out


def load_pixels(path: Path, size: int = 48) -> list[RGB]:
    path = Path(path)
    try:
        from PIL import Image  # type: ignore

        img = Image.open(path).convert("RGB")
        img.thumbnail((size, size))
        return [_rgb8_to_f(r, g, b) for r, g, b in img.getdata()]
    except Exception:
        with tempfile.TemporaryDirectory(prefix="cityview-palette-") as tmp:
            out = Path(tmp) / "thumb.png"
            proc = subprocess.run(
                ["sips", "-s", "format", "png", "-z", str(size), str(size), str(path), "--out", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(f"sips failed for {path}: {proc.stderr.strip()}")
            return _decode_png_scanlines(out)


def quantize_key(rgb: RGB, bins: int = 12) -> tuple[int, int, int]:
    scale = bins - 1
    return (
        int(round(_clamp01(rgb[0]) * scale)),
        int(round(_clamp01(rgb[1]) * scale)),
        int(round(_clamp01(rgb[2]) * scale)),
    )


def _facade_band_pixels(pixels: list[RGB], size: int) -> list[RGB]:
    if size <= 0 or len(pixels) < size * size:
        return pixels
    out: list[RGB] = []
    y0, y1 = int(size * 0.18), int(size * 0.78)
    x0, x1 = int(size * 0.12), int(size * 0.88)
    for y in range(y0, y1):
        row = y * size
        for x in range(x0, x1):
            out.append(pixels[row + x])
    return out or pixels


def sample_photo(path: Path, size: int = 96) -> dict:
    pixels = load_pixels(path, size=size)
    band = _facade_band_pixels(pixels, size)
    wall_candidates = [
        p for p in band if 0.14 < _luma(p) < 0.90 and (_sat(p) > 0.035 or 0.28 < _luma(p) < 0.78)
    ]
    pool = wall_candidates or band
    votes: Counter[tuple[int, int, int]] = Counter(quantize_key(p, bins=14) for p in pool)
    top_keys = [k for k, _ in votes.most_common(8)]
    clusters: dict[tuple[int, int, int], list[RGB]] = {k: [] for k in top_keys}
    for p in pool:
        k = quantize_key(p, bins=14)
        if k in clusters:
            clusters[k].append(p)

    def mean(cols: Iterable[RGB]) -> RGB:
        cols = list(cols)
        n = max(1, len(cols))
        return (sum(c[0] for c in cols) / n, sum(c[1] for c in cols) / n, sum(c[2] for c in cols) / n)

    scored: list[tuple[float, RGB]] = []
    for k in top_keys:
        cols = clusters.get(k) or []
        if not cols:
            continue
        m = mean(cols)
        score = len(cols) * (0.35 + _sat(m) * 2.4) * (1.0 - abs(_luma(m) - 0.52) * 0.8)
        scored.append((score, m))
    scored.sort(key=lambda item: item[0], reverse=True)
    ranked = [m for _score, m in scored]
    wall = ranked[0] if ranked else mean(pool)
    by_luma = sorted(ranked, key=_luma)
    trim = max(ranked, key=lambda c: _luma(c) * (0.4 + _sat(c))) if ranked else wall
    plinth = by_luma[0] if len(by_luma) == 1 else by_luma[min(1, len(by_luma) - 1)]
    dark_pixels = sorted(band, key=_luma)[: max(8, len(band) // 14)]
    roof = mean(dark_pixels)
    roof = (_clamp01(roof[0] * 0.45 + 0.10), _clamp01(roof[1] * 0.45 + 0.095), _clamp01(roof[2] * 0.45 + 0.09))
    brightness = sum(_luma(p) for p in band) / max(1, len(band))
    return {
        "file": Path(path).name,
        "wall": [*wall, 1.0],
        "trim": [*trim, 1.0],
        "plinth": [*plinth, 1.0],
        "roof": [*roof, 1.0],
        "brightness": round(brightness, 4),
    }


def blend_rgba(colors: list[list[float] | RGBA], weights: list[float] | None = None) -> list[float]:
    if not colors:
        return [0.5, 0.5, 0.5, 1.0]
    if weights is None:
        weights = [1.0] * len(colors)
    total = sum(weights) or 1.0
    acc = [0.0, 0.0, 0.0, 0.0]
    for col, w in zip(colors, weights):
        for i in range(4):
            acc[i] += float(col[i] if i < len(col) else 1.0) * w
    return [_clamp01(v / total) for v in acc]


def jitter_rgba(color: list[float] | RGBA, seed: int, amount: float = 0.045) -> list[float]:
    x = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    channels = []
    for _i in range(3):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        channels.append(_clamp01(float(color[_i]) + ((x / 0x7FFFFFFF) * 2.0 - 1.0) * amount))
    return channels + [float(color[3]) if len(color) > 3 else 1.0]


def derive_frame(wall: list[float], window_kind: str) -> list[float]:
    if window_kind == "arch":
        return [_clamp01(wall[0] * 0.35), _clamp01(wall[1] * 0.28 + 0.04), _clamp01(wall[2] * 0.22), 1.0]
    if window_kind == "ribbon":
        return [0.08, 0.08, 0.09, 1.0]
    shade = 0.18 if _luma((wall[0], wall[1], wall[2])) > 0.55 else 0.12
    return [shade, shade * 0.9, shade * 0.8, 1.0]


def derive_glass(window_kind: str, wall: list[float]) -> list[float]:
    if window_kind == "arch":
        return [0.22, 0.28, 0.26, 1.0]
    if window_kind == "ribbon":
        return [0.28, 0.34, 0.38, 1.0]
    return [
        _clamp01(0.18 + (1.0 - wall[0]) * 0.04),
        _clamp01(0.24 + (1.0 - wall[1]) * 0.03),
        _clamp01(0.30 + (1.0 - wall[2]) * 0.02),
        1.0,
    ]


def remix_palette(
    samples: list[dict],
    *,
    window: str = "rect",
    seed: int = 0,
    wall_bias: list[float] | RGBA | None = None,
    bias_amount: float = 0.0,
) -> dict:
    if not samples:
        raise ValueError("remix_palette requires samples")
    ordered = sorted(samples, key=lambda s: _sat(tuple(s["wall"][:3])), reverse=True)
    n = len(ordered)
    weights = [1.15] + [0.4] * (n - 1)
    wall = blend_rgba([s["wall"] for s in ordered], weights)
    trim = blend_rgba([s.get("trim") or s["wall"] for s in samples], [0.55] + [1.0] * (n - 1) if n > 1 else [1.0])
    plinth = blend_rgba([s.get("plinth") or s["wall"] for s in samples], list(reversed(weights)))
    roof = blend_rgba([s.get("roof") or [0.18, 0.17, 0.16, 1.0] for s in samples], weights)
    if wall_bias and bias_amount > 0:
        wall = blend_rgba([wall, list(wall_bias)], [1.0 - bias_amount, bias_amount])
        plinth = blend_rgba([plinth, [_clamp01(c * 0.72) for c in wall_bias[:3]] + [1.0]], [0.55, 0.45])
    wall = jitter_rgba(wall, seed ^ 0xA11CE, amount=0.03)
    trim = jitter_rgba(trim, seed ^ 0x7E11, amount=0.025)
    plinth = jitter_rgba(plinth, seed ^ 0xB01D, amount=0.03)
    roof = jitter_rgba(roof, seed ^ 0xF00D, amount=0.02)
    return {
        "wall": wall,
        "roof": roof,
        "frame": derive_frame(wall, window),
        "glass": derive_glass(window, wall),
        "plinth": plinth,
        "trim": trim,
        "window": window,
        "rough": round(0.82 + (_luma((wall[0], wall[1], wall[2])) * -0.06), 3),
    }
