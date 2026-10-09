"""Pedestrian roster built from Microsoft Rocketbox avatars (MIT).

Each entry becomes viewer/characters/people/<id>.glb with its walk clip baked in.

  src     Rocketbox avatar folder name
  age     adult | senior | child
  sex     m | f
  look    neighbourhood grouping used to compose families and groups in the viewer
  walk    Rocketbox walk clip (in-place after the build strips root travel)
  recolor garment tints, see `tint()`; applied to the body texture only
  extras  props modelled by the build (hat, beard, sidelocks, kippah, coat, skirt, ...)

Uniformed professions (fire, military, pilots, SWAT), swimwear and football kits are left
out, as is Female_Adult_16: face veils are banned in public in Belgium.
"""
from __future__ import annotations

ANIMATIONS = {
    "m_walk_neutral_01",
    "m_walk_neutral_02",
    "m_walk_stroll_01",
    "m_walk_slow_01",
    "f_walk_neutral_01",
    "f_walk_neutral_02",
    "f_walk_stroll_01",
    "f_walk_slow_01",
}


def tint(hue, to, *, sat=(0.18, 1.0), val=(0.04, 1.0), uv=None, avoid=(), keep=0.0, detail=1.0):
    """Recolour body-texture pixels whose HSV falls in hue (deg range, may wrap) / sat / val
    and, optionally, inside the UV rectangle `uv` and outside every `avoid` rectangle
    ((u0, v0, u1, v1), v = 0 at the image top) to the RGB colour `to` (0-255), keeping the
    fabric's light/dark detail (scaled by `detail`; 0 paints flat, hiding prints). `keep`
    blends back some of the original colour."""
    return {"hue": hue, "sat": sat, "val": val, "uv": uv, "avoid": avoid, "to": to, "keep": keep,
            "detail": detail}


# Darkens a charcoal suit to the black of the modelled coat.
SUIT_BLACK = tint((0, 360), (14, 14, 16), sat=(0.0, 0.2), val=(0.04, 0.3), keep=0.25)

# Hands in the top corners of a Rocketbox female body texture.
F_HANDS = ((0.0, 0.0, 0.19, 0.27), (0.81, 0.0, 1.0, 0.27))


def _adult(src, sex, look, walk=None, **kw):
    walk = walk or ("m_walk_neutral_01" if sex == "m" else "f_walk_neutral_01")
    return {"id": src, "src": src, "age": "adult", "sex": sex, "look": look, "walk": walk, **kw}


def _senior(src, sex, look, **kw):
    return _adult(src, sex, look, "m_walk_slow_01" if sex == "m" else "f_walk_slow_01", age="senior", **kw)


def _child(id_, src, sex, look, **kw):
    walk = "m_walk_neutral_02" if sex == "m" else "f_walk_neutral_02"
    return {"id": id_, "src": src, "age": "child", "sex": sex, "look": look, "walk": walk, **kw}


ROSTER: list[dict] = [
    # Everyday adults
    _adult("Female_Adult_01", "f", "european"),
    _adult("Female_Adult_02", "f", "european", "f_walk_stroll_01"),
    _adult("Female_Adult_03", "f", "asian"),
    _adult("Female_Adult_04", "f", "european", "f_walk_neutral_02"),
    _adult("Female_Adult_05", "f", "asian", "f_walk_stroll_01"),
    _adult("Female_Adult_06", "f", "muslim"),
    _adult("Female_Adult_07", "f", "european", "f_walk_neutral_02"),
    _adult("Female_Adult_08", "f", "european"),
    _adult("Female_Adult_09", "f", "european", "f_walk_stroll_01"),
    _adult("Female_Adult_10", "f", "muslim", "f_walk_neutral_02"),
    _adult("Female_Adult_11", "f", "mediterranean"),
    _adult("Female_Adult_12", "f", "european", "f_walk_neutral_02"),
    _adult("Female_Adult_13", "f", "slavic"),
    _adult("Female_Adult_14", "f", "european", "f_walk_stroll_01"),
    _adult("Female_Adult_15", "f", "european"),
    _adult("Female_Adult_17", "f", "slavic", "f_walk_neutral_02"),
    _adult("Female_Party_01", "f", "slavic", "f_walk_stroll_01"),
    _adult("Female_Party_02", "f", "african"),
    _adult("Male_Adult_01", "m", "european"),
    _adult("Male_Adult_02", "m", "european", "m_walk_neutral_02"),
    _senior("Male_Adult_03", "m", "european"),
    _adult("Male_Adult_04", "m", "african", "m_walk_stroll_01"),
    _adult("Male_Adult_05", "m", "slavic"),
    _adult("Male_Adult_06", "m", "european", "m_walk_neutral_02"),
    _adult("Male_Adult_07", "m", "mediterranean"),
    _adult("Male_Adult_08", "m", "european", "m_walk_stroll_01"),
    _adult("Male_Adult_09", "m", "asian"),
    _adult("Male_Adult_10", "m", "asian", "m_walk_neutral_02"),
    _adult("Male_Adult_11", "m", "slavic"),
    _adult("Male_Adult_12", "m", "african", "m_walk_stroll_01"),
    _adult("Male_Adult_13", "m", "european"),
    _senior("Male_Adult_14", "m", "european"),
    _adult("Male_Adult_15", "m", "muslim", "m_walk_neutral_02"),
    _adult("Male_Adult_16", "m", "slavic"),
    _adult("Male_Adult_17", "m", "muslim", "m_walk_stroll_01"),
    _adult("Male_Adult_18", "m", "african"),
    _adult("Male_Adult_19", "m", "arab", "m_walk_stroll_01"),
    _adult("Male_Adult_20", "m", "european", "m_walk_neutral_02"),
    _adult("Male_Adult_21", "m", "arab"),
    # Work clothes
    _adult("Business_Female_01", "f", "african"),
    _adult("Business_Female_02", "f", "slavic", "f_walk_neutral_02"),
    _adult("Business_Female_03", "f", "european"),
    _adult("Business_Female_04", "f", "european", "f_walk_neutral_02"),
    _adult("Business_Male_01", "m", "european"),
    _adult("Business_Male_02", "m", "asian", "m_walk_neutral_02"),
    _adult("Business_Male_03", "m", "european"),
    _senior("Business_Male_04", "m", "european"),
    _adult("Business_Male_05", "m", "african", "m_walk_neutral_02"),
    _adult("Business_Male_06", "m", "mediterranean"),
    _senior("Business_Male_07", "m", "slavic"),
    _adult("Chef_Female_01", "f", "asian"),
    _adult("Delivery_Male_01", "m", "european", "m_walk_neutral_02"),
    _senior("Gardener_Male_01", "m", "european"),
    _adult("Medical_Female_01", "f", "mediterranean"),
    _adult("Medical_Male_02", "m", "european", "m_walk_neutral_02"),
    _adult("Police_Male_03", "m", "european"),
    _adult("Sports_Female_02", "f", "asian", "f_walk_neutral_02"),
    _adult("Sports_Male_04", "m", "european"),
    _adult("Wood_Male_01", "m", "muslim", "m_walk_stroll_01"),
    # Children: the four Rocketbox kids plus re-dressed variants
    _child("Male_Child_01", "Male_Child_01", "m", "european"),
    _child("Male_Child_01_red", "Male_Child_01", "m", "european",
           recolor=[tint((190, 235), (150, 32, 36), sat=(0.35, 1), uv=(0.33, 0, 0.67, 0.84)),
                    tint((190, 235), (150, 32, 36), sat=(0.35, 1), uv=(0, 0.42, 1, 0.84))]),
    _child("Male_Child_01_green", "Male_Child_01", "m", "slavic",
           recolor=[tint((190, 235), (54, 92, 58), sat=(0.35, 1), uv=(0.33, 0, 0.67, 0.84)),
                    tint((190, 235), (54, 92, 58), sat=(0.35, 1), uv=(0, 0.42, 1, 0.84))]),
    _child("Male_Child_02", "Male_Child_02", "m", "african"),
    _child("Male_Child_02_blue", "Male_Child_02", "m", "african",
           recolor=[tint((5, 45), (40, 78, 140), sat=(0.45, 1), val=(0.35, 1))]),
    _child("Male_Child_02_grey", "Male_Child_02", "m", "muslim",
           recolor=[tint((5, 45), (120, 122, 126), sat=(0.45, 1), val=(0.35, 1))]),
    _child("Female_Child_01", "Female_Child_01", "f", "european"),
    _child("Female_Child_01_yellow", "Female_Child_01", "f", "slavic",
           recolor=[tint((290, 335), (222, 178, 52), sat=(0.3, 1))]),
    _child("Female_Child_01_teal", "Female_Child_01", "f", "european",
           recolor=[tint((290, 335), (36, 128, 128), sat=(0.3, 1))]),
    _child("Female_Child_02", "Female_Child_02", "f", "muslim"),
    _child("Female_Child_02_navy", "Female_Child_02", "f", "muslim",
           recolor=[tint((60, 180), (38, 48, 84), sat=(0.12, 1), val=(0.08, 1))]),
    _child("Female_Child_02_rose", "Female_Child_02", "f", "muslim",
           recolor=[tint((60, 180), (150, 92, 104), sat=(0.12, 1), val=(0.08, 1))]),
    # Hasidic family: dark suits, white shirts, hats, beards and peyos on top of Rocketbox bodies
    {**_adult("Business_Male_03", "m", "hasidic"), "id": "Hasidic_Father",
     "recolor": [tint((0, 360), (222, 222, 218), sat=(0.0, 1), uv=(0.34, 0.84, 0.62, 1.0)),
                 SUIT_BLACK],
     "extras": ["coat", "beard_dark", "peyos", "hat_wide"]},
    {**_senior("Business_Male_04", "m", "hasidic"), "id": "Hasidic_Grandfather",
     "recolor": [tint((0, 360), (212, 212, 208), sat=(0.0, 0.25), val=(0.12, 1), uv=(0.45, 0.45, 0.55, 0.6)),
                 tint((0, 360), (16, 16, 18), sat=(0.0, 0.25), keep=0.1, avoid=((0.45, 0.45, 0.55, 0.6),))],
     "extras": ["coat", "beard_grey", "peyos_grey", "hat_wide"]},
    {**_adult("Business_Male_01", "m", "hasidic", "m_walk_neutral_02"), "id": "Hasidic_Young_Man",
     "recolor": [tint((340, 20), (222, 222, 218), sat=(0.3, 1)), SUIT_BLACK],
     "extras": ["coat", "beard_short", "peyos", "hat_wide"]},
    {**_adult("Business_Female_03", "f", "hasidic"), "id": "Hasidic_Mother",
     "recolor": [tint((0, 60), (34, 38, 58), sat=(0.08, 1), val=(0.12, 1), uv=(0.0, 0.0, 1.0, 0.7), avoid=F_HANDS),
                 tint((0, 60), (40, 40, 46), sat=(0.08, 1), val=(0.12, 1), uv=(0.0, 0.7, 1.0, 1.0), keep=0.1)],
     "extras": ["skirt_long"]},
    {**_adult("Female_Adult_15", "f", "hasidic", "f_walk_stroll_01"), "id": "Hasidic_Woman",
     "recolor": [tint((190, 250), (28, 30, 44), sat=(0.12, 1)),
                 tint((0, 50), (40, 40, 46), sat=(0.1, 1), val=(0.2, 1), uv=(0.0, 0.68, 1.0, 0.97), keep=0.1)],
     "extras": ["skirt_long"]},
    {**_child("Hasidic_Boy", "Male_Child_01", "m", "hasidic"),
     "recolor": [tint((0, 360), (236, 236, 232), sat=(0.0, 1), uv=(0.4, 0.52, 0.6, 0.76), detail=0.1),
                 tint((190, 235), (236, 236, 232), sat=(0.35, 1), uv=(0.33, 0, 0.67, 0.84)),
                 tint((190, 235), (236, 236, 232), sat=(0.35, 1), uv=(0, 0.42, 1, 0.84)),
                 tint((170, 240), (22, 22, 26), sat=(0.0, 1), uv=(0, 0, 0.33, 0.42)),
                 tint((170, 240), (22, 22, 26), sat=(0.0, 1), uv=(0.67, 0, 1, 0.42))],
     "extras": ["kippah", "peyos_child"]},
    {**_child("Hasidic_Boy_Vest", "Male_Child_01", "m", "hasidic"),
     "recolor": [tint((0, 360), (33, 36, 52), sat=(0.0, 1), uv=(0.4, 0.52, 0.6, 0.76), detail=0.3),
                 tint((190, 235), (26, 28, 40), sat=(0.35, 1), uv=(0.33, 0, 0.67, 0.84)),
                 tint((190, 235), (236, 236, 232), sat=(0.35, 1), uv=(0, 0.42, 0.33, 0.84)),
                 tint((190, 235), (236, 236, 232), sat=(0.35, 1), uv=(0.67, 0.42, 1, 0.84)),
                 tint((170, 240), (22, 22, 26), sat=(0.0, 1), uv=(0, 0, 0.33, 0.42)),
                 tint((170, 240), (22, 22, 26), sat=(0.0, 1), uv=(0.67, 0, 1, 0.42))],
     "extras": ["kippah", "peyos_child"]},
    {**_child("Hasidic_Girl", "Female_Child_01", "f", "hasidic"),
     "recolor": [tint((290, 335), (30, 36, 70), sat=(0.3, 1)),
                 tint((180, 240), (34, 36, 52), sat=(0.05, 1), uv=(0, 0.55, 1, 1))],
     "extras": ["skirt_child"]},
]


def source_avatars() -> list[str]:
    return sorted({r["src"] for r in ROSTER})
