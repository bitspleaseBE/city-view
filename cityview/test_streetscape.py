import unittest

from cityview.streetscape import (
    _offset_polyline,
    export_buildings_near_spawn,
    export_roads_near_spawn,
    export_walks_near_spawn,
    floors_from_height,
    footprint_supports_prism_roof,
    height_truth,
    nearest_road_pose,
    parse_maxspeed_kmh,
    point_in_ring,
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
        self.assertIn("yaw", payload["signals"][0])
        self.assertIn("pedYaw", payload["signals"][0])


class BuildingExportTests(unittest.TestCase):
    def test_export_buildings_near_spawn(self):
        ring_near = [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
        ring_far = [[500.0, 500.0], [510.0, 500.0], [510.0, 510.0], [500.0, 510.0]]
        layout = {
            "buildings": [
                {"id": 1, "ring": ring_near},
                {"id": 2, "ring": ring_far},
                {"id": 3, "ring": [[1.0, 1.0]]},  # too few verts
            ]
        }
        payload = export_buildings_near_spawn(
            layout, {"x": 5.0, "y": 4.0}, radius=100.0, max_buildings=10
        )
        self.assertEqual(len(payload["buildings"]), 1)
        self.assertEqual(payload["buildings"][0]["id"], 1)
        self.assertTrue(point_in_ring(5.0, 4.0, payload["buildings"][0]["ring"]))
        self.assertFalse(point_in_ring(20.0, 20.0, payload["buildings"][0]["ring"]))


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
        self.assertIn("walks", payload)


class WalkExportTests(unittest.TestCase):
    def test_offset_is_perpendicular(self):
        left = _offset_polyline([[0.0, 0.0], [10.0, 0.0]], 2.0)
        self.assertAlmostEqual(left[0][1], 2.0, places=5)
        self.assertAlmostEqual(left[1][1], 2.0, places=5)

    def test_exports_sidewalks_not_carriageway_centres(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                {"id": 2, "kind": "footway", "width": 2.0, "points": [[0.0, 5.0], [40.0, 5.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        kinds = {w["kind"] for w in walks}
        self.assertIn("footway", kinds)
        self.assertIn("sidewalk", kinds)
        sw = [w for w in walks if w["kind"] == "sidewalk"]
        self.assertTrue(any(abs(w["points"][0][1]) > 2.5 for w in sw))

    def test_living_street_uses_sidewalks_not_centreline(self):
        layout = {
            "roads": [
                {"id": 9, "kind": "living_street", "width": 5.0, "points": [[0.0, 0.0], [50.0, 0.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 25.0, "y": 0.0}, radius=80.0)
        self.assertTrue(walks)
        self.assertTrue(all(w["kind"] == "sidewalk" for w in walks))
        self.assertTrue(all(abs(w["points"][0][1]) > 2.0 for w in walks))

    def test_crossing_links_opposite_kerbs(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 8.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
            ],
            "crossings": [{"id": 99, "x": 20.0, "y": 0.0, "kind": "uncontrolled"}],
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        crosses = [w for w in walks if w["kind"] == "crossing"]
        self.assertEqual(len(crosses), 1)
        self.assertFalse(crosses[0]["safe"])
        y0, y1 = crosses[0]["points"][0][1], crosses[0]["points"][1][1]
        self.assertGreater(abs(y0 - y1), 6.0)

    def test_skips_building_passage_footways(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                {
                    "id": 2,
                    "kind": "footway",
                    "width": 2.0,
                    "passage": True,
                    "points": [[10.0, 0.0], [10.0, 20.0]],
                },
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        self.assertFalse(any(w["id"].startswith("w2") for w in walks))

    def test_skips_courtyard_paths_far_from_streets(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                # Deep yard path, well clear of the street.
                {"id": 3, "kind": "footway", "width": 2.0, "points": [[10.0, 40.0], [30.0, 40.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=80.0)
        self.assertFalse(any(w["id"].startswith("w3") for w in walks))
        self.assertTrue(any(w["kind"] == "sidewalk" for w in walks))

    def test_skips_sidewalk_ribbons_through_buildings(self):
        # Street along y=0; building covers the north kerb so the L ribbon is indoors.
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
            ],
            "buildings": [
                {"id": 9, "ring": [[0.0, 2.0], [40.0, 2.0], [40.0, 12.0], [0.0, 12.0]]},
            ],
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        sides = {w.get("side") for w in walks if w["kind"] == "sidewalk"}
        self.assertIn("R", sides)
        self.assertNotIn("L", sides)


if __name__ == "__main__":
    unittest.main()
