import unittest

from cityview.streetscape import (
    export_roads_near_spawn,
    floors_from_height,
    footprint_supports_prism_roof,
    height_truth,
    nearest_road_pose,
    parse_maxspeed_kmh,
    road_speed_kmh,
    roof_shape_for,
    safe_roof_shape,
    street_facing_edges,
)


class HeightTruthTests(unittest.TestCase):
    def test_levels(self):
        eaves, roof_h, floors = height_truth({"building:levels": "4"})
        self.assertEqual(floors, 4)
        self.assertAlmostEqual(eaves, 12.6, places=1)

    def test_roof_shape_tagged(self):
        self.assertEqual(
            roof_shape_for({"roof:shape": "gabled"}, "eclectic", 1),
            "gable",
        )

    def test_floors_from_height(self):
        self.assertEqual(floors_from_height(12.6), 4)

    def test_prism_ok_on_rectangle(self):
        ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 6.0], [0.0, 6.0]]
        self.assertTrue(footprint_supports_prism_roof(ring))
        self.assertEqual(safe_roof_shape("gable", ring), "gable")

    def test_prism_rejects_l_shape(self):
        # Classic L footprint — OBB gable would overhang the missing corner.
        ring = [
            [0.0, 0.0],
            [12.0, 0.0],
            [12.0, 4.0],
            [4.0, 4.0],
            [4.0, 10.0],
            [0.0, 10.0],
        ]
        self.assertFalse(footprint_supports_prism_roof(ring))
        self.assertEqual(safe_roof_shape("gable", ring), "mansard")
        self.assertEqual(safe_roof_shape("hip", ring), "mansard")
        self.assertEqual(safe_roof_shape("flat", ring), "flat")


class StreetEdgeTests(unittest.TestCase):
    def test_edge_faces_road(self):
        # Unit square building; road south of it.
        ring = [[0.0, 0.0], [6.0, 0.0], [6.0, 8.0], [0.0, 8.0]]
        segments = [(-2.0, -3.0, 8.0, -3.0, 6.0)]
        edges = street_facing_edges(ring, segments)
        self.assertTrue(edges)
        # Bottom edge (y=0) should be included.
        self.assertTrue(any(e["i0"] == 0 for e in edges))

    def test_spawn_snaps_to_road(self):
        roads = [{"points": [[0.0, 0.0], [20.0, 0.0]], "width": 6.0}]
        sx, sy, yaw = nearest_road_pose(10.0, 4.0, roads)
        self.assertAlmostEqual(sy, 0.0, places=3)
        self.assertAlmostEqual(sx, 10.0, places=3)
        self.assertAlmostEqual(yaw, 0.0, places=3)


class RoadsExportTests(unittest.TestCase):
    def test_exports_driveable_near_spawn(self):
        layout = {
            "roads": [
                {
                    "id": 1,
                    "kind": "residential",
                    "width": 6.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
                {
                    "id": 2,
                    "kind": "footway",
                    "width": 2.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
                {
                    "id": 3,
                    "kind": "secondary",
                    "width": 8.0,
                    "points": [[500.0, 500.0], [520.0, 500.0]],
                },
                {
                    "id": 99,
                    "kind": "tram",
                    "width": 3.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
            ],
            "transit_lines": [
                {
                    "id": 99,
                    "mode": "tram",
                    "points": [[0.0, 1.0], [40.0, 1.0]],
                }
            ],
            "signals": [
                {"id": 10, "x": 20.0, "y": 0.0, "kind": "traffic_signals"},
                {"id": 11, "x": 22.0, "y": 1.0, "kind": "traffic_signals"},
            ],
        }
        payload = export_roads_near_spawn(
            layout, {"x": 5.0, "y": 0.0}, radius=100.0, max_roads=10
        )
        self.assertEqual(len(payload["roads"]), 1)
        self.assertEqual(payload["roads"][0]["id"], 1)
        self.assertNotIn(99, [r["id"] for r in payload["roads"]])
        self.assertEqual(payload["cycleSeconds"], 30)
        # Clustered OSM nodes → stop-line approaches, not raw centre spam.
        self.assertGreaterEqual(len(payload["signals"]), 1)
        self.assertIn("stopX", payload["signals"][0])


class MaxspeedTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "30"}), 30.0)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "50 km/h"}), 50.0)
        self.assertAlmostEqual(parse_maxspeed_kmh({"maxspeed": "20 mph"}), 32.2, places=1)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "BE-VLG:urban"}), 50.0)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "30;50"}), 30.0)
        self.assertIsNone(parse_maxspeed_kmh({"maxspeed": "none"}))
        self.assertIsNone(parse_maxspeed_kmh({}))

    def test_defaults_and_export(self):
        self.assertEqual(road_speed_kmh("residential", None), 30.0)
        self.assertEqual(road_speed_kmh("secondary", None), 50.0)
        self.assertEqual(road_speed_kmh("secondary", 30.0), 30.0)
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0,
                 "points": [[0.0, 0.0], [40.0, 0.0]], "maxspeed_kmh": 20.0},
                {"id": 2, "kind": "secondary", "width": 8.0,
                 "points": [[40.0, 0.0], [90.0, 0.0]]},
            ],
            "signals": [],
        }
        payload = export_roads_near_spawn(layout, {"x": 0.0, "y": 0.0}, radius=200.0)
        by_id = {r["id"]: r for r in payload["roads"]}
        self.assertEqual(by_id[1]["maxspeedKmh"], 20.0)
        self.assertEqual(by_id[1]["speedKmh"], 20.0)
        self.assertIsNone(by_id[2]["maxspeedKmh"])
        self.assertEqual(by_id[2]["speedKmh"], 50.0)


if __name__ == "__main__":
    unittest.main()
