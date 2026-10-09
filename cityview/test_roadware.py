"""Tests for manhole / gully planning."""

from __future__ import annotations

import math
import unittest

from cityview import roadware as rw


def _street(rid=1, length=200.0, width=7.0, y=0.0):
    return {"id": rid, "kind": "residential", "width": width, "points": [[0.0, y], [length, y]]}


class RoadwareTests(unittest.TestCase):
    def test_deterministic(self):
        roads = [_street()]
        self.assertEqual(rw.plan_roadware(roads, (100, 0)), rw.plan_roadware(roads, (100, 0)))

    def test_gullies_hug_the_kerb_and_manholes_sit_in_the_lane(self):
        items = rw.plan_roadware([_street(width=7.0)], (100, 0))
        kinds = rw.count_kinds(items)
        self.assertGreater(kinds.get("gully", 0), 3)
        self.assertGreater(kinds.get("manhole", 0), 1)
        for it in items:
            lat = abs(it["y"])
            if it["kind"] == "gully":
                self.assertTrue(3.0 < lat < 3.5)  # inside the 3.5 m half width
            else:
                self.assertAlmostEqual(lat, 1.75, places=3)  # lane centre, not the dash line
            self.assertAlmostEqual(it["yaw"], 0.0)

    def test_gullies_alternate_sides(self):
        sides = [1 if it["y"] > 0 else -1 for it in rw.plan_roadware([_street()], (100, 0)) if it["kind"] == "gully"]
        self.assertTrue(any(a != b for a, b in zip(sides, sides[1:])))

    def test_road_ends_and_far_roads_are_skipped(self):
        for it in rw.plan_roadware([_street(length=200.0)], (100, 0)):
            self.assertGreaterEqual(it["x"], rw.END_MARGIN_M - 1e-6)
            self.assertLessEqual(it["x"], 200.0 - rw.END_MARGIN_M + 1e-6)
        self.assertEqual(rw.plan_roadware([_street(y=900.0)], (0, 0)), [])

    def test_junction_mouth_stays_clear(self):
        side = {"id": 2, "kind": "residential", "width": 6.0, "points": [[100.0, 0.0], [100.0, 120.0]]}
        for it in rw.plan_roadware([_street(), side], (100, 0)):
            if abs(it["y"]) < 5.0:  # main street only (side-street items start at y >= 9)
                self.assertGreater(abs(it["x"] - 100.0), 3.0 + 3.0 - 1e-6)

    def test_narrow_lanes_and_footways_get_nothing(self):
        lane = {"id": 3, "kind": "residential", "width": 2.5, "points": [[0, 0], [100, 0]]}
        foot = {"id": 4, "kind": "footway", "width": 7.0, "points": [[0, 10], [100, 10]]}
        self.assertEqual(rw.plan_roadware([lane, foot], (50, 0)), [])

    def test_cap(self):
        roads = [_street(rid=i, y=i * 12.0) for i in range(1, 12)]
        self.assertLessEqual(len(rw.plan_roadware(roads, (100, 60), max_items=25)), 25)

    def test_yaw_follows_the_road(self):
        road = {"id": 5, "kind": "tertiary", "width": 7.0, "points": [[0.0, 0.0], [0.0, 150.0]]}
        for it in rw.plan_roadware([road], (0, 75)):
            self.assertAlmostEqual(it["yaw"], math.pi / 2)


if __name__ == "__main__":
    unittest.main()
