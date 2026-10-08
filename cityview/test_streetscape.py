import unittest

from cityview.streetscape import (
    floors_from_height,
    height_truth,
    nearest_road_pose,
    roof_shape_for,
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


if __name__ == "__main__":
    unittest.main()
