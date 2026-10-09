"""Tests for carriageway clearance and snapping (``cityview.roadclear``)."""

from __future__ import annotations

import math
import unittest

from cityview.roadclear import TRUNK_MARGIN, RoadIndex, snap_off_carriageway

ROAD = {"id": 1, "kind": "residential", "width": 6.0, "points": [[-100.0, 0.0], [100.0, 0.0]]}
FOOT = {"id": 2, "kind": "footway", "width": 2.0, "points": [[0.0, 20.0], [50.0, 20.0]]}


def _free(_x: float, _y: float) -> bool:
    return True


class RoadIndexTests(unittest.TestCase):
    def test_clearance_is_signed_distance_to_asphalt_edge(self):
        idx = RoadIndex([ROAD])
        self.assertAlmostEqual(idx.clearance(0.0, 0.0), -3.0)
        self.assertAlmostEqual(idx.clearance(10.0, 5.0), 2.0)

    def test_footways_are_not_carriageway(self):
        idx = RoadIndex([FOOT])
        self.assertFalse(idx)
        self.assertFalse(idx.on_carriageway(10.0, 20.0, 1.0))

    def test_margin_covers_kerb(self):
        idx = RoadIndex([ROAD])
        self.assertTrue(idx.on_carriageway(0.0, 3.0 + TRUNK_MARGIN - 0.05, TRUNK_MARGIN))
        self.assertFalse(idx.on_carriageway(0.0, 3.0 + TRUNK_MARGIN + 0.05, TRUNK_MARGIN))

    def test_junction_union(self):
        side = {"id": 3, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [0.0, 80.0]]}
        idx = RoadIndex([ROAD, side])
        self.assertTrue(idx.on_carriageway(0.0, 40.0, TRUNK_MARGIN))  # inside the side street
        self.assertFalse(idx.on_carriageway(10.0, 40.0, TRUNK_MARGIN))


class SnapTests(unittest.TestCase):
    def test_legal_point_is_unchanged(self):
        self.assertEqual(snap_off_carriageway(5.0, 6.0, RoadIndex([ROAD]), _free), (5.0, 6.0))

    def test_moves_to_nearest_pavement_on_same_side(self):
        x, y = snap_off_carriageway(5.0, -1.0, RoadIndex([ROAD]), _free)
        self.assertLess(y, 0.0)
        self.assertGreaterEqual(-y - 3.0, TRUNK_MARGIN - 1e-6)
        self.assertLess(math.hypot(x - 5.0, y + 1.0), 3.0)

    def test_centreline_point_resolves_deterministically(self):
        a = snap_off_carriageway(5.0, 0.0, RoadIndex([ROAD]), _free)
        b = snap_off_carriageway(5.0, 0.0, RoadIndex([ROAD]), _free)
        self.assertEqual(a, b)
        self.assertIsNotNone(a)

    def test_respects_extra_obstacles(self):
        idx = RoadIndex([ROAD])
        spot = snap_off_carriageway(5.0, 0.5, idx, lambda _x, y: y < 0.0)
        self.assertIsNotNone(spot)
        self.assertLess(spot[1], 0.0)

    def test_gives_up_beyond_snap_range(self):
        wide = {"id": 9, "kind": "primary", "width": 20.0, "points": [[-100.0, 0.0], [100.0, 0.0]]}
        self.assertIsNone(snap_off_carriageway(0.0, 0.0, RoadIndex([wide]), _free))


if __name__ == "__main__":
    unittest.main()
