import json
import unittest
from collections import Counter

from cityview import building_heights as bh
from cityview.osm import finalize_building_heights, layout_from_osm
from cityview.paths import ASSETS

OSM_HARMONIE = ASSETS / "osm" / "harmonie.json"
ORIGIN = (51.2017, 4.4114)


def square(x: float, y: float, side: float) -> list[list[float]]:
    return [[x, y], [x + side, y], [x + side, y + side], [x, y + side]]


class ParseTests(unittest.TestCase):
    def test_levels_and_height_parse_leniently(self):
        self.assertEqual(bh.parse_levels({"building:levels": "4"}), 4)
        self.assertEqual(bh.parse_levels({"building:levels": "3;4"}), 3)
        self.assertEqual(bh.parse_levels({"building:levels": "3.5"}), 4)
        self.assertIsNone(bh.parse_levels({"building:levels": "many"}))
        self.assertIsNone(bh.parse_levels({"building:levels": "0"}))
        self.assertEqual(bh.parse_height_m({"height": "12.5 m"}), 12.5)
        self.assertEqual(bh.parse_height_m({"height": "9,5"}), 9.5)
        self.assertIsNone(bh.parse_height_m({"height": "tall"}))

    def test_hard_cap_is_twenty_levels(self):
        self.assertEqual(bh.parse_levels({"building:levels": "45"}), 20)
        self.assertAlmostEqual(bh.parse_height_m({"height": "300"}), 20 * bh.FLOOR_H)

    def test_min_level_is_subtracted(self):
        self.assertEqual(bh.parse_levels({"building:levels": "9", "building:min_level": "2"}), 7)


class InferTests(unittest.TestCase):
    def draw(self, tags, area, n=4000):
        return Counter(bh.infer_levels(i * 7 + 3, tags, area)[0] for i in range(n))

    def test_townhouses_are_mostly_three_levels_never_below_two(self):
        c = self.draw({"building": "yes", "addr:housenumber": "5"}, 90.0)
        total = sum(c.values())
        self.assertGreater(c[3] / total, 0.5)  # the majority
        self.assertGreater(c[2], 0)  # a few
        self.assertLess(c[2] / total, 0.15)
        self.assertEqual(min(c), 2)
        self.assertLessEqual(max(c), 5)

    def test_small_apartments_average_about_four(self):
        c = self.draw({"building": "apartments", "addr:housenumber": "1"}, 200.0)
        mean = sum(k * v for k, v in c.items()) / sum(c.values())
        self.assertTrue(3.8 < mean < 4.9, mean)

    def test_large_apartment_blocks_reach_ten_plus_but_never_over_twenty(self):
        c = self.draw({"building": "apartments", "addr:housenumber": "1"}, 900.0)
        self.assertTrue(any(k >= 10 for k in c))
        self.assertLessEqual(max(c), bh.MAX_LEVELS)

    def test_outbuildings_are_not_houses(self):
        self.assertEqual(bh.infer_levels(1, {"building": "garage"}, 20.0)[0], 1)
        self.assertEqual(bh.infer_levels(2, {"building": "yes"}, 25.0)[0], 1)  # unaddressed annex
        self.assertEqual(bh.infer_levels(3, {"building": "yes", "addr:housenumber": "2"}, 25.0)[0] >= 2, True)

    def test_inference_is_deterministic(self):
        tags = {"building": "yes", "addr:housenumber": "8"}
        self.assertEqual(bh.infer_levels(42, tags, 100.0), bh.infer_levels(42, tags, 100.0))


class ResolveTests(unittest.TestCase):
    def build(self, specs):
        buildings, tags = [], []
        for i, (x, side, t) in enumerate(specs):
            buildings.append({"id": 1000 + i, "ring": square(x, 0.0, side), "floors": 4})
            tags.append(t)
        return buildings, tags

    def test_osm_levels_and_height_win(self):
        b, t = self.build(
            [
                (0, 10, {"building": "yes", "building:levels": "12", "addr:housenumber": "1"}),
                (50, 10, {"building": "yes", "height": "21", "addr:housenumber": "2"}),
            ]
        )
        counts = bh.resolve_heights(b, t)
        self.assertEqual((b[0]["levels"], b[0]["height_source"]), (12, "osm_levels"))
        self.assertEqual((b[1]["levels"], b[1]["height_source"]), (round(21 / bh.FLOOR_H), "osm_height"))
        self.assertEqual(counts["osm_levels"], 1)

    def test_photo_levels_only_fill_gaps(self):
        photo = bh.photo_levels()
        self.assertIn("449843110", photo)
        osm_id = 449843110
        b = [{"id": osm_id, "ring": square(0, 0, 30), "floors": 4}]
        bh.resolve_heights(b, [{"building": "apartments", "building:levels": "9"}])
        self.assertEqual((b[0]["levels"], b[0]["height_source"]), (9, "osm_levels"))  # OSM wins
        b = [{"id": osm_id, "ring": square(0, 0, 30), "floors": 4}]
        bh.resolve_heights(b, [{"building": "apartments"}])
        self.assertEqual((b[0]["levels"], b[0]["height_source"]), (7, "photo"))

    def test_type_default_buildings_are_left_alone(self):
        b = [{"id": 5, "ring": square(0, 0, 30), "floors": 5, "height_source": "type_default"}]
        bh.resolve_heights(b, [{"building": "hospital"}])
        self.assertEqual(b[0]["levels"], 5)

    def test_party_wall_neighbours_often_share_a_cornice_line(self):
        n = 400
        buildings = [{"id": 100 + i, "ring": square(i * 6.0, 0.0, 6.0), "floors": 4} for i in range(n)]
        tags = [{"building": "yes", "addr:housenumber": str(i)} for i in range(n)]
        bh.resolve_heights(buildings, tags)
        same = sum(1 for a, c in zip(buildings, buildings[1:]) if a["levels"] == c["levels"])
        self.assertGreater(same / (n - 1), 0.5)  # independent draws would give ~0.40
        # ... and the marginal stays a 3-level majority.
        counts = Counter(b["levels"] for b in buildings)
        self.assertEqual(counts.most_common(1)[0][0], 3)

    def test_towers_are_never_copied_onto_neighbouring_houses(self):
        buildings = [
            {"id": 1, "ring": square(0, 0, 6), "floors": 4},
            {"id": 2, "ring": square(6, 0, 6), "floors": 4},
        ]
        tags = [
            {"building": "apartments", "building:levels": "14", "addr:housenumber": "1"},
            {"building": "yes", "addr:housenumber": "2"},
        ]
        for _ in range(3):
            bh.resolve_heights(buildings, tags)
            self.assertLessEqual(buildings[1]["levels"], 6)


class LayoutTests(unittest.TestCase):
    def test_layout_never_exceeds_twenty_levels_and_records_source(self):
        osm = {
            "elements": [
                {"type": "node", "id": 1, "lat": 51.221, "lon": 4.400},
                {"type": "node", "id": 2, "lat": 51.221, "lon": 4.4003},
                {"type": "node", "id": 3, "lat": 51.2212, "lon": 4.4003},
                {"type": "node", "id": 4, "lat": 51.2212, "lon": 4.400},
                {
                    "type": "way",
                    "id": 10,
                    "nodes": [1, 2, 3, 4, 1],
                    "tags": {"building": "apartments", "building:levels": "60"},
                },
            ]
        }
        layout = layout_from_osm(osm, (51.221, 4.400))
        b = layout["buildings"][0]
        self.assertEqual(b["floors"], 20)
        self.assertLessEqual(b["height"], 20 * bh.FLOOR_H + 1e-6)
        self.assertEqual(b["height_source"], "osm_levels")
        self.assertEqual(b["roof_shape"], "flat")  # towers get flat roofs

    def test_finalize_marks_church_without_numbers_as_type_default(self):
        b = [
            {
                "id": 9,
                "ring": square(0, 0, 20),
                "height": 28.0,
                "floors": 9,
                "roof_height": 4.0,
                "roof_shape": "hip",
                "building_type": "church",
                "style": "church",
            }
        ]
        finalize_building_heights(b, [{"building": "church"}], "historic")
        self.assertEqual(b[0]["height_source"], "type_default")
        self.assertEqual(b[0]["height"], 28.0)

    @unittest.skipUnless(OSM_HARMONIE.exists(), "harmonie OSM cache not present")
    def test_harmonie_tile_has_height_contrast_and_respects_osm(self):
        layout = layout_from_osm(json.loads(OSM_HARMONIE.read_text()), ORIGIN, style_policy="historic")
        levels = Counter(b["floors"] for b in layout["buildings"])
        total = sum(levels.values())
        self.assertLessEqual(max(levels), bh.MAX_LEVELS)
        self.assertLess(levels[4] / total, 0.4)  # was 94.7 % before the fix
        self.assertEqual(levels.most_common(1)[0][0], 3)
        self.assertGreater(len(levels), 8)  # a real spread of heights
        by_id = {b["id"]: b for b in layout["buildings"]}
        tall = by_id[448506550]  # Mechelsesteenweg 142 "Amberes", OSM building:levels=12
        self.assertEqual((tall["floors"], tall["height_source"]), (12, "osm_levels"))
        gounod = [by_id[i] for i in (503586584, 503586583, 503569025, 503569024) if i in by_id]
        self.assertTrue(gounod)
        self.assertGreaterEqual(tall["floors"] - max(g["floors"] for g in gounod), 6)
        for b in layout["buildings"]:
            self.assertIn("height_source", b)


if __name__ == "__main__":
    unittest.main()
