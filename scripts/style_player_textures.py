"""Recolor Rocketbox body/head textures to match menu portraits.

Writes styled copies under ``viewer/characters/players/_styled/{id}/``.
Used by ``rocketbox_to_player_glb.py`` after FBX import.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
AVATAR_DIR = ROOT / "assets" / "rocketbox" / "avatars"
OUT_DIR = ROOT / "viewer" / "characters" / "players" / "_styled"


def _load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32)


def _save(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA").save(path)


def _rgb(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]


def _lum(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _shift_hue_region(
    arr: np.ndarray,
    mask: np.ndarray,
    target_rgb: tuple[float, float, float],
    *,
    keep_luma: float = 0.55,
    strength: float = 0.82,
    min_shade: float = 0.25,
) -> None:
    """Blend masked pixels toward target while preserving some shading.

    ``min_shade`` floors how dark the target can go — needed when lifting near-black
    Rocketbox jackets into light gray hoodies.
    """
    r, g, b = _rgb(arr)
    luma = _lum(r, g, b) / 255.0
    tr, tg, tb = target_rgb
    # Shade factor from original luminance (keep_luma blends toward flat target).
    shade = np.clip(0.35 + luma * 1.1, min_shade, 1.35)
    shade = shade * (1.0 - keep_luma) + 1.0 * keep_luma
    nr = np.clip(tr * shade, 0, 255)
    ng = np.clip(tg * shade, 0, 255)
    nb = np.clip(tb * shade, 0, 255)
    out = arr.copy()
    out[:, :, 0] = np.where(mask, r * (1 - strength) + nr * strength, r)
    out[:, :, 1] = np.where(mask, g * (1 - strength) + ng * strength, g)
    out[:, :, 2] = np.where(mask, b * (1 - strength) + nb * strength, b)
    arr[:] = out


def style_pieter_body(arr: np.ndarray) -> np.ndarray:
    """Charcoal jacket + terracotta shirt → navy bomber + white tee; keep blue jeans."""
    r, g, b = _rgb(arr)
    luma = _lum(r, g, b)
    h, _w = luma.shape
    yy = np.linspace(0, 1, h)[:, None]
    skin = (r > 90) & (g > 60) & (b > 40) & (r > b) & (r > g * 0.9) & (luma > 80) & (luma < 210)
    # Pants islands are the top UV band
    denim = (yy < 0.38) & (luma > 25) & ~skin
    sneaker = (yy > 0.78) & (luma > 120) & ~skin
    # Anything warm / tan / brown in the torso → white tee
    warm = (
        (yy >= 0.38)
        & (yy < 0.78)
        & ~skin
        & ~sneaker
        & (
            ((r > g * 1.05) & (r > b * 1.02) & (r > 50))
            | ((luma > 90) & (luma < 200) & (r > b) & (g > b * 0.9) & (r - b > 15))
        )
    )
    # Light collar / undershirt leftovers
    shirt = (
        (yy >= 0.38)
        & (yy < 0.78)
        & (luma > 100)
        & (luma < 220)
        & ~skin
        & ~warm
        & ~sneaker
        & (np.abs(r - g) < 40)
    )
    jacket = (yy >= 0.38) & (yy < 0.82) & (luma > 15) & ~skin & ~warm & ~shirt & ~sneaker & ~denim

    out = arr.copy()
    # Medium-wash jeans (not navy-matching the jacket).
    _shift_hue_region(out, denim, (72, 105, 168), keep_luma=0.28, strength=0.85, min_shade=0.5)
    _shift_hue_region(out, jacket, (22, 42, 88), keep_luma=0.25, strength=0.88, min_shade=0.35)
    _shift_hue_region(
        out, warm | shirt, (242, 242, 245), keep_luma=0.65, strength=0.92, min_shade=0.85
    )
    _shift_hue_region(out, sneaker, (245, 245, 248), keep_luma=0.4, strength=0.8, min_shade=0.7)
    # Hard bleach: shirt / collar / tie leftovers in the chest island → white tee.
    _h, w = luma.shape
    xx = np.linspace(0, 1, w)[None, :]
    r2, g2, b2 = _rgb(out)
    luma2 = _lum(r2, g2, b2)
    chest = (yy >= 0.38) & (yy < 0.72) & ~skin & ~sneaker
    navyish = (b2 > r2 * 1.12) & (b2 > g2 * 1.05) & (luma2 < 120)
    brown = ((r2 > g2 * 1.05) & (r2 > b2 * 1.08) & (r2 > 30) & chest) | (
        (r2 > 60) & (r2 > b2) & (g2 > b2 * 0.9) & (r2 - b2 > 20) & chest
    )
    # Center placket / tie strip on the Rocketbox torso island
    placket = chest & (xx > 0.32) & (xx < 0.68) & (yy > 0.44) & (yy < 0.68) & ~navyish
    leftover_shirt = (chest & ~navyish & (luma2 > 55)) | brown | placket
    out[:, :, 0] = np.where(leftover_shirt, 242.0, out[:, :, 0])
    out[:, :, 1] = np.where(leftover_shirt, 242.0, out[:, :, 1])
    out[:, :, 2] = np.where(leftover_shirt, 245.0, out[:, :, 2])
    # Re-assert medium jeans on the top UV band (jacket pass can navy them out).
    r3, g3, b3 = _rgb(out)
    luma3 = _lum(r3, g3, b3)
    jeans = (yy < 0.38) & (luma3 > 12) & ~skin
    _shift_hue_region(out, jeans, (78, 112, 175), keep_luma=0.2, strength=0.9, min_shade=0.55)
    # Dress shoes → white sneakers
    shoes = (yy > 0.78) & ~skin & (luma3 > 20)
    _shift_hue_region(out, shoes, (236, 236, 240), keep_luma=0.35, strength=0.9, min_shade=0.7)
    return out


def style_mo_body(arr: np.ndarray) -> np.ndarray:
    """Force light-gray hoodie + white tee + blue jeans via UV bands + chroma."""
    r, g, b = _rgb(arr)
    luma = _lum(r, g, b)
    h, _w = luma.shape
    yy = np.linspace(0, 1, h)[:, None]
    skin = (r > 90) & (g > 60) & (b > 40) & (r > b) & (luma > 85) & (luma < 210)
    # White / light sneakers live in the bottom UV strip
    sneaker = (yy > 0.78) & (luma > 140) & (np.abs(r - g) < 45) & (np.abs(g - b) < 45) & ~skin
    # Pants islands sit in the top ~38% of the Rocketbox body atlas
    pants = (yy < 0.38) & (luma > 12) & ~skin & ~sneaker
    # Teal / cyan / magenta underlayers → white tee
    teal = (b > r * 1.08) & (g > r * 1.02) & (b > 60) & (luma > 45) & ~skin
    magenta = (r > g * 1.15) & (b > g * 1.08) & (r > 70) & ~skin
    tee = (teal | magenta) & ~pants & ~sneaker
    # Everything else clothing → light gray hoodie (incl. dark vest + sleeves)
    hoodie = (luma > 12) & ~skin & ~pants & ~sneaker & ~tee

    out = arr.copy()
    # Lift near-black vest into light gray; keep mild fold shading via luma.
    _shift_hue_region(
        out, hoodie, (178, 180, 184), keep_luma=0.55, strength=0.92, min_shade=0.75
    )
    _shift_hue_region(out, tee, (245, 245, 247), keep_luma=0.7, strength=0.9, min_shade=0.85)
    _shift_hue_region(out, pants, (48, 78, 140), keep_luma=0.35, strength=0.88, min_shade=0.45)
    # Scrub any leftover brand/magenta logos on the tee.
    r2, g2, b2 = _rgb(out)
    mag = (r2 > g2 * 1.25) & (b2 > g2 * 1.15) & (r2 > 80) & (yy > 0.35) & (yy < 0.75)
    out[:, :, 0] = np.where(mag, 245, out[:, :, 0])
    out[:, :, 1] = np.where(mag, 245, out[:, :, 1])
    out[:, :, 2] = np.where(mag, 247, out[:, :, 2])
    return out


def style_mo_head(arr: np.ndarray) -> np.ndarray:
    """Keep curly dark hair/beard; slightly deepen hair."""
    r, g, b = _rgb(arr)
    luma = _lum(r, g, b)
    # Dark hair/beard regions (not skin)
    hair = (luma < 70) & (r < 90) & (g < 80) & (b < 80)
    out = arr.copy()
    out[:, :, 0] = np.where(hair, r * 0.75, r)
    out[:, :, 1] = np.where(hair, g * 0.75, g)
    out[:, :, 2] = np.where(hair, b * 0.75, b)
    return out


def style_pieter_head(arr: np.ndarray) -> np.ndarray:
    """Push hair toward warmer brown waves."""
    r, g, b = _rgb(arr)
    luma = _lum(r, g, b)
    hair = (luma < 90) & (r < 120) & (g < 110)
    out = arr.copy()
    # Slightly brown warmer hair
    out[:, :, 0] = np.where(hair, np.minimum(255, r * 0.9 + 18), r)
    out[:, :, 1] = np.where(hair, g * 0.78, g)
    out[:, :, 2] = np.where(hair, b * 0.65, b)
    return out


STYLERS = {
    "pieter": {"body": style_pieter_body, "head": style_pieter_head},
    "mo": {"body": style_mo_body, "head": style_mo_head},
}


def style_player(player_id: str, avatar_folder: str) -> Path:
    src = AVATAR_DIR / avatar_folder
    dst = OUT_DIR / player_id
    if dst.exists():
        for p in dst.iterdir():
            p.unlink()
    dst.mkdir(parents=True, exist_ok=True)

    stylers = STYLERS[player_id]
    for tex in src.iterdir():
        if tex.suffix.lower() not in {".tga", ".png", ".jpg", ".jpeg"}:
            continue
        low = tex.name.lower()
        if "normal" in low or "specular" in low or "rough" in low:
            # Still copy normals untouched
            Image.open(tex).save(dst / (tex.stem + ".png"))
            continue
        arr = _load_rgba(tex)
        if "body" in low and "color" in low:
            arr = stylers["body"](arr)
        elif "head" in low and "color" in low:
            arr = stylers["head"](arr)
        _save(arr, dst / (tex.stem + ".png"))
    return dst


def main() -> None:
    mapping = {
        "pieter": "Male_Adult_07",
        "mo": "Male_Adult_04",
    }
    for pid, folder in mapping.items():
        path = style_player(pid, folder)
        print(f"OK {pid} → {path}")


if __name__ == "__main__":
    main()
