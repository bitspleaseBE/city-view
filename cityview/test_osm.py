import unittest

from cityview.geo import project
from cityview.osm import height_for, layout_from_osm, style_for


class GeoTests(unittest.TestCase):
    def test_origin_is_zero(self):
        self.assertEqual(project(51.22, 4.40, 51.22, 4.40), (0.0, 0.0))

    def test_north_is_positive_y(self):
        x, y = project(51.221, 4.40, 51.22, 4.40)
        self.assertAlmostEqual(x, 0.0, places=3)
        self.assertGreater(y, 100.0)


class OsmLayoutTests(unittest.TestCase):
    def test_height_from_levels(self):
        self.assertAlmostEqual(height_for({"building:levels": "4"}), 12.6, places=1)

    def test_industrial_style(self):
        self.assertEqual(style_for(1, {"building": "warehouse"}), "prefab-70s")

    def test_historic_church_style(self):
        self.assertIn(
            style_for(42, {"building": "church"}, policy="historic"),
            {"neo-gothic", "neoclassical"},
        )

    def test_historic_residential_stable(self):
        a = style_for(1001, {"building": "terrace"}, policy="historic")
        b = style_for(1001, {"building": "terrace"}, policy="historic")
        self.assertEqual(a, b)
        self.assertIn(
            a,
            {
                "eclectic",
                "neoclassical",
                "neo-flemish",
                "cream-tile",
                "yellow-brick",
                "red-brick",
                "art-nouveau",
                "art-deco",
                "international",
                "modern-infill",
            },
        )

    def test_historic_tall_apartments(self):
        self.assertIn(
            style_for(9, {"building": "apartments", "building:levels": "8"}, policy="historic"),
            {"art-deco", "international"},
        )

    def test_parses_building_and_road(self):
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
                    "tags": {"building": "yes", "building:levels": "3"},
                },
                {
                    "type": "way",
                    "id": 11,
                    "nodes": [1, 2],
                    "tags": {"highway": "residential"},
                },
                {
                    "type": "way",
                    "id": 12,
                    "nodes": [1, 2, 3, 4, 1],
                    "tags": {"leisure": "park", "name": "Harmoniepark"},
                },
            ]
        }
        layout = layout_from_osm(osm, (51.221, 4.400))
        self.assertEqual(len(layout["buildings"]), 1)
        self.assertEqual(len(layout["roads"]), 1)
        self.assertEqual(len(layout["parks"]), 1)
        self.assertGreater(layout["buildings"][0]["height"], 8.0)
        self.assertIn("street_edges", layout["buildings"][0])
        self.assertIn("roof_shape", layout["buildings"][0])
        self.assertGreaterEqual(layout["buildings"][0]["floors"], 1)


if __name__ == "__main__":
    unittest.main()
