"""Tests for chimney / rooftop plant planning."""

from __future__ import annotations

import math
import unittest

from cityview import rooftop as rt


def _rect(w: float, d: float, x0: float = 0.0, y0: float = 0.0):
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + d], [x0, y0 + d]]


class ChimneyTests(unittest.TestCase):
    def test_gable_stacks_stand_on_the_ridge_near_the_party_walls(self):
        ring = _rect(6.0, 16.0)  # long axis is y: ridge runs along y
        for seed in range(2, 40, 2):
            stacks = rt.plan_chimneys(ring, 12.0, 4.0, "gable", seed)
            self.assertTrue(stacks)
            for s in stacks:
                self.assertAlmostEqual(s["x"], 3.0, delta=0.8)  # on the ridge, mid-width
                self.assertTrue(rt.point_in_ring(s["x"], s["y"], ring))
                top = s["z"] + s["h"]
                self.assertGreaterEqual(top, 12.0 + 4.0 + 0.9)  # clears the ridge by ~1 m
                self.assertLess(s["z"], 12.0 + 4.0)  # buried in the roof, no gap

    def test_two_gable_stacks_mirror_across_the_ridge_centre(self):
        ring = _rect(6.0, 18.0)
        for seed in range(2, 200, 2):
            stacks = rt.plan_chimneys(ring, 10.0, 3.0, "gable", seed)
            if len(stacks) >= 2:
                self.assertAlmostEqual(stacks[0]["y"] + stacks[1]["y"], 18.0, delta=0.01)
                return
        self.fail("no seed produced two stacks")

    def test_flat_roofs_get_no_chimneys_and_tiny_ones_none_inside_the_footprint(self):
        self.assertEqual(rt.plan_chimneys(_rect(8, 8), 9.0, 0.4, "flat", 2), [])
        for s in rt.plan_chimneys(_rect(2.0, 2.0), 9.0, 2.0, "gable", 4):
            self.assertTrue(rt.point_in_ring(s["x"], s["y"], _rect(2.0, 2.0)))

    def test_planning_is_deterministic(self):
        ring = _rect(7, 15)
        self.assertEqual(rt.plan_chimneys(ring, 10, 3, "hip", 8), rt.plan_chimneys(ring, 10, 3, "hip", 8))

    def test_mansard_and_hip_stacks_stay_inside(self):
        ring = _rect(10.0, 14.0)
        for shape in ("hip", "mansard"):
            for seed in range(2, 30, 2):
                for s in rt.plan_chimneys(ring, 12.0, 3.0, shape, seed):
                    self.assertTrue(rt.point_in_ring(s["x"], s["y"], ring))
                    self.assertLessEqual(s["z"] + s["h"], 12.0 + 3.0 + rt.STACK_RISE + 0.01)


class RoofPlantTests(unittest.TestCase):
    def test_small_roofs_get_nothing_big_ones_get_a_stair_head_and_plant(self):
        self.assertEqual(rt.plan_roof_plant(_rect(5, 8), 10.0, 3), [])
        big = rt.plan_roof_plant(_rect(18, 30), 10.0, 3)
        kinds = [p["kind"] for p in big]
        self.assertIn("stair", kinds)
        self.assertIn("hvac", kinds)
        for p in big:
            self.assertTrue(rt.point_in_ring(p["x"], p["y"], _rect(18, 30)))
            self.assertAlmostEqual(p["z"], 9.98)

    def test_items_do_not_overlap(self):
        for seed in range(1, 40):
            items = rt.plan_roof_plant(_rect(20, 40), 10.0, seed)
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    gap = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                    self.assertGreater(gap, 0.5 * (max(a["sx"], a["sy"]) + max(b["sx"], b["sy"])) - 1e-6)


if __name__ == "__main__":
    unittest.main()
