import unittest
from pathlib import Path

from cityview.building_types import (
    TYPE_SPECS,
    attach_palettes,
    build_types_document,
    palette_for_building,
    variant_index,
)
from cityview.osm import building_type_for, style_for
from cityview.palette import blend_rgba, jitter_rgba, remix_palette
from cityview.paths import ASSETS


class PaletteTests(unittest.TestCase):
    def test_jitter_stable(self):
        base = [0.5, 0.4, 0.3, 1.0]
        a = jitter_rgba(base, 42)
        b = jitter_rgba(base, 42)
        c = jitter_rgba(base, 43)
        self.assertEqual(a, b)
        self.assertNotEqual(a[:3], c[:3])

    def test_blend(self):
        out = blend_rgba([[0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0, 1.0]])
        self.assertAlmostEqual(out[0], 0.5, places=3)


class BuildingTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ref = ASSETS / "references" / "klein-antwerpen"
        if not ref.exists() or not list(ref.glob("ref_*.jpg")):
            raise unittest.SkipTest("reference photos missing")
        cls.doc = build_types_document(ref)

    def test_types_cover_specs(self):
        for spec in TYPE_SPECS:
            self.assertIn(spec["id"], self.doc["types"])
            entry = self.doc["types"][spec["id"]]
            self.assertEqual(entry["window"], spec["window"])
            self.assertTrue(entry["photos"])
            self.assertEqual(len(entry["variants"]), 3)
            wall = entry["palette"]["wall"]
            self.assertEqual(len(wall), 4)
            self.assertTrue(0.0 <= wall[0] <= 1.0)

    def test_remix_uses_photos(self):
        samples = [
            self.doc["photo_samples"][name]
            for name in self.doc["types"]["neo-flemish"]["photos"]
        ]
        # photo_samples lacks secondary; reshape for remix_palette
        shaped = []
        for s in samples:
            shaped.append(
                {
                    "wall": s["wall"],
                    "trim": s["trim"],
                    "plinth": s["plinth"],
                    "roof": s["roof"],
                }
            )
        pal = remix_palette(shaped, window="arch", seed=1)
        self.assertEqual(pal["window"], "arch")
        self.assertEqual(len(pal["wall"]), 4)

    def test_palette_for_building_varies(self):
        a = palette_for_building("eclectic", 100, self.doc)
        b = palette_for_building("eclectic", 100, self.doc)
        c = palette_for_building("eclectic", 101, self.doc)
        self.assertEqual(a["wall"], b["wall"])
        self.assertEqual(a["window"], "rect")
        # Different ids may land on different variants / jitter.
        self.assertTrue(
            a["wall"] != c["wall"] or a.get("variant") != c.get("variant")
        )

    def test_attach_palettes(self):
        layout = {
            "buildings": [
                {"id": 1, "style": "neo-flemish"},
                {"id": 2, "building_type": "yellow-brick"},
            ]
        }
        attach_palettes(layout, self.doc)
        self.assertEqual(layout["buildings"][0]["building_type"], "neo-flemish")
        self.assertIn("palette", layout["buildings"][0])
        self.assertEqual(layout["buildings"][1]["style"], "yellow-brick")

    def test_variant_index_range(self):
        for i in range(50):
            self.assertIn(variant_index(i, 3), {0, 1, 2})


class AssignmentTests(unittest.TestCase):
    def test_historic_shop_type(self):
        self.assertIn(
            building_type_for(55, {"building": "yes", "shop": "bakery"}, policy="historic"),
            {"cream-tile", "eclectic"},
        )

    def test_style_for_alias(self):
        self.assertEqual(
            style_for(1, {"building": "warehouse"}),
            building_type_for(1, {"building": "warehouse"}),
        )

    def test_historic_mix_includes_new_types(self):
        seen = {
            style_for(i, {"building": "terrace"}, policy="historic")
            for i in range(200, 400)
        }
        self.assertTrue({"cream-tile", "yellow-brick", "red-brick"} & seen)


if __name__ == "__main__":
    unittest.main()
