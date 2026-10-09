"""Tests for OSM-grounded kerbside parked cars."""

from __future__ import annotations

import math
import unittest

from cityview.parking import (
    HALF_LEN,
    HALF_WID,
    LANE_CLEAR_CENTRE,
    car_offset,
    parse_road_parking,
    plan_parked_cars,
    side_allows_car,
    summarize,
)


def _road(rid=1, parking=None, y=0.0, width=6.2, kind="residential", x0=-80.0, x1=80.0, name="Teststraat"):
    road = {"id": rid, "kind": kind, "width": width, "name": name, "points": [[x0, y], [x1, y]]}
    if parking is not None:
        road["parking"] = parking
    return road


BOTH = {"left": {"type": "street_side", "orientation": "parallel"}, "right": {"type": "street_side", "orientation": "parallel"}}


def _plan(roads, **extra):
    layout = {"roads": roads}
    layout.update(extra)
    return plan_parked_cars(layout, (0.0, 0.0), radius=200.0)


class ParseTests(unittest.TestCase):
    def test_both_expands_to_each_side(self):
        got = parse_road_parking({"parking:both": "lane", "parking:both:orientation": "parallel"})
        self.assertEqual(got["left"], {"type": "lane", "orientation": "parallel"})
        self.assertEqual(got["right"], {"type": "lane", "orientation": "parallel"})

    def test_specific_side_overrides_both(self):
        got = parse_road_parking({"parking:both": "no", "parking:right": "on_kerb"})
        self.assertEqual(got["left"]["type"], "no")
        self.assertEqual(got["right"]["type"], "on_kerb")

    def test_untagged_way_has_no_parking(self):
        self.assertIsNone(parse_road_parking({"highway": "residential"}))

    def test_only_allowed_parallel_sides_get_cars(self):
        self.assertTrue(side_allows_car({"type": "lane", "orientation": ""}))
        self.assertFalse(side_allows_car({"type": "no", "orientation": ""}))
        self.assertFalse(side_allows_car({"type": "lane", "orientation": "perpendicular"}))
        self.assertFalse(side_allows_car({"type": "street_side", "orientation": "diagonal"}))
        self.assertFalse(side_allows_car(None))


class PlanTests(unittest.TestCase):
    def test_untagged_roads_get_no_cars(self):
        self.assertEqual(_plan([_road(parking=None)]), [])

    def test_no_parking_side_gets_no_cars(self):
        denied = {"left": {"type": "no", "orientation": ""}, "right": {"type": "no", "orientation": ""}}
        self.assertEqual(_plan([_road(parking=denied)]), [])

    def test_one_sided_parking_stays_on_that_side(self):
        one = {"left": {"type": "no", "orientation": ""}, "right": {"type": "lane", "orientation": "parallel"}}
        cars = _plan([_road(parking=one)])
        self.assertTrue(cars)
        self.assertTrue(all(c["side"] == "right" and c["y"] < 0 for c in cars))

    def test_cars_clear_the_runtime_traffic_lane_and_follow_the_kerb(self):
        for width in (5.4, 6.2, 8.0):
            cars = _plan([_road(parking=BOTH, width=width)])
            self.assertTrue(cars)
            for c in cars:
                self.assertGreaterEqual(abs(c["y"]) - HALF_WID, 1.15 + HALF_WID + 0.1)  # past the driver's lane
                self.assertAlmostEqual(math.sin(c["yaw"]), 0.0, places=3)  # parallel to the street
        self.assertGreaterEqual(car_offset(3.1), LANE_CLEAR_CENTRE)

    def test_right_hand_traffic_facing(self):
        cars = _plan([_road(parking=BOTH)])
        for c in cars:
            east = math.cos(c["yaw"]) > 0
            self.assertEqual(east, c["side"] == "right")

    def test_cars_do_not_overlap_and_keep_off_junctions(self):
        side = _road(rid=2, parking=None, kind="residential", x0=0.0, x1=0.0, name="Zijstraat")
        side["points"] = [[0.0, -40.0], [0.0, 40.0]]
        cars = _plan([_road(parking=BOTH), side])
        for i, a in enumerate(cars):
            for b in cars[i + 1 :]:
                self.assertGreater(math.hypot(a["x"] - b["x"], a["y"] - b["y"]), 4.2)
            self.assertGreaterEqual(abs(a["x"]), 3.1 + HALF_LEN)  # not across the side street

    def test_keeps_clear_of_crossings_signals_and_stops(self):
        base = _plan([_road(parking=BOTH)])
        self.assertTrue(base)
        c0 = base[0]
        for key, extra in (
            ("crossings", {"crossings": [{"x": c0["x"], "y": 0.0}]}),
            ("signals", {"signals": [{"x": c0["x"], "y": 0.0}]}),
            ("stops", {"transit_stops": [{"x": c0["x"], "y": 0.0}]}),
        ):
            cars = _plan([_road(parking=BOTH)], **extra)
            self.assertFalse(
                any(math.hypot(c["x"] - c0["x"], c["y"] - c0["y"]) < 4.0 for c in cars),
                key,
            )

    def test_blocked_callback_vetoes_spots(self):
        layout = {"roads": [_road(parking=BOTH)]}
        cars = plan_parked_cars(layout, (0.0, 0.0), radius=200.0, blocked=lambda x, y: x > 0)
        self.assertTrue(cars)
        self.assertTrue(all(c["x"] <= 1.5 for c in cars))

    def test_footways_and_links_never_get_cars(self):
        self.assertEqual(_plan([_road(parking=BOTH, kind="footway")]), [])
        self.assertEqual(_plan([_road(parking=BOTH, kind="secondary_link")]), [])

    def test_max_cars_cap_and_summary(self):
        cars = plan_parked_cars({"roads": [_road(parking=BOTH)]}, (0.0, 0.0), radius=200.0, max_cars=3)
        self.assertEqual(len(cars), 3)
        self.assertIn("3 parked cars", summarize(cars))

    def test_plan_is_deterministic(self):
        self.assertEqual(_plan([_road(parking=BOTH)]), _plan([_road(parking=BOTH)]))


if __name__ == "__main__":
    unittest.main()
