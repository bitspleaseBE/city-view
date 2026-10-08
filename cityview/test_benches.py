"""Tests for surveyed bench placement and facing."""

from __future__ import annotations

import math
import unittest

from cityview.benches import (
    CARRIAGEWAY,
    osm_stop_benches,
    _Ways,
    bearing_to_facing,
    facing_to_yaw,
    osm_benches,
    parse_direction,
    plan_benches,
    yaw_to_facing,
)
from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon

ORIGIN = (51.2, 4.4)


def _ll(x: float, y: float) -> tuple[float, float]:
    return (ORIGIN[0] + y / METERS_PER_DEG_LAT, ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0]))


def _osm(x: float, y: float, bid: int = 1, **tags) -> dict:
    lat, lon = _ll(x, y)
    return {"id": bid, "type": "node", "lat": lat, "lon": lon, "tags": {"amenity": "bench", **tags}}


def _city(x: float, y: float, bid: int = 1) -> dict:
    lat, lon = _ll(x, y)
    return {"id": bid, "lat": lat, "lon": lon}


def _square(x0: float, y0: float, w: float, h: float | None = None) -> list[list[float]]:
    h = w if h is None else h
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]


def _layout(**extra) -> dict:
    base = {"buildings": [], "roads": [], "parks": [], "transit_lines": []}
    base.update(extra)
    return base


def _facing(bench: dict) -> tuple[float, float]:
    return yaw_to_facing(bench["yaw"])


def _plan(layout, osm=None, city=None):
    return plan_benches(layout, osm or [], {"antwerp": city or []}, ORIGIN)


class OrientationMathTests(unittest.TestCase):
    def test_yaw_round_trip_covers_the_compass(self):
        for deg in range(0, 360, 15):
            fx, fy = bearing_to_facing(deg)
            gx, gy = yaw_to_facing(facing_to_yaw(fx, fy))
            self.assertAlmostEqual(fx, gx, places=6)
            self.assertAlmostEqual(fy, gy, places=6)

    def test_mesh_convention_back_is_opposite_the_seat(self):
        # Seat looks along local -Y; at yaw=0 that is south. Facing north needs a half turn.
        self.assertAlmostEqual(abs(facing_to_yaw(0.0, 1.0)), math.pi, places=6)
        self.assertAlmostEqual(facing_to_yaw(0.0, -1.0), 0.0, places=6)

    def test_parse_direction(self):
        self.assertEqual(parse_direction("68"), 68.0)
        self.assertEqual(parse_direction("370"), 10.0)
        self.assertEqual(parse_direction("SW"), 225.0)
        self.assertIsNone(parse_direction("forward"))
        self.assertIsNone(parse_direction(None))


class SurveyedFacingTests(unittest.TestCase):
    def test_osm_direction_is_used_verbatim(self):
        out = _plan(_layout(), osm=[{**_osm(0, 0, direction="90"), "type": "node"}])
        fx, fy = _facing(out["benches"][0])
        self.assertAlmostEqual(fx, 1.0, places=3)  # east
        self.assertAlmostEqual(fy, 0.0, places=3)
        self.assertEqual(out["benches"][0]["rule"], "osm_direction")

    def test_heading_into_a_wall_is_flipped(self):
        wall = _square(-5, 0.6, 10, 8)  # wall 0.6 m north of the bench
        out = _plan(_layout(buildings=[{"ring": wall}]), osm=[_osm(0, 0, direction="0")])
        self.assertEqual(out["benches"][0]["rule"], "osm_direction_flipped")
        self.assertLess(_facing(out["benches"][0])[1], -0.9)

    def test_osm_way_has_no_bearing(self):
        way = {
            "elements": [
                {"type": "node", "id": 1, "lat": ORIGIN[0], "lon": ORIGIN[1]},
                {"type": "node", "id": 2, "lat": ORIGIN[0], "lon": ORIGIN[1] + 0.0001},
                {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"amenity": "bench", "direction": "90"}},
            ]
        }
        recs = osm_benches(way)
        self.assertEqual(len(recs), 1)
        out = _plan(_layout(), osm=recs)
        self.assertNotEqual(out["benches"][0]["rule"], "osm_direction")

    def test_private_benches_are_ignored(self):
        doc = {"elements": [{"type": "node", "id": 1, "lat": 51.2, "lon": 4.4, "tags": {"amenity": "bench", "access": "private"}}]}
        self.assertEqual(osm_benches(doc), [])


class InferredFacingTests(unittest.TestCase):
    def test_back_to_the_wall(self):
        wall = _square(-5, -9, 10, 8)  # wall's north face at y = -1
        out = _plan(_layout(buildings=[{"ring": wall}]), city=[_city(0, 0)])
        b = out["benches"][0]
        self.assertEqual(b["rule"], "back_to_wall")
        self.assertGreater(_facing(b)[1], 0.9)  # seat looks north, away from the wall

    def test_seat_faces_a_footpath(self):
        path = {"id": 1, "kind": "footway", "width": 1.5, "points": [[-20, 3], [20, 3]]}
        out = _plan(_layout(roads=[path]), city=[_city(0, 0)])
        b = out["benches"][0]
        self.assertEqual(b["rule"], "face_path")
        self.assertGreater(_facing(b)[1], 0.9)

        below = _plan(_layout(roads=[path]), city=[_city(0, 6, 2)])  # other side
        self.assertEqual(below["benches"][0]["rule"], "face_path")
        self.assertLess(_facing(below["benches"][0])[1], -0.9)

    def test_back_to_the_road_not_along_it(self):
        road = {"id": 1, "kind": "residential", "width": 6.0, "points": [[3 + 4, -50], [3 + 4, 50]]}
        # carriageway spans x in [4, 10]; bench on the western pavement at x = 2.5
        out = _plan(_layout(roads=[road]), city=[_city(2.5, 0)])
        b = out["benches"][0]
        self.assertEqual(b["rule"], "back_to_road")
        fx, fy = _facing(b)
        self.assertLess(fx, -0.9)  # looks west, away from the road
        self.assertLess(abs(fy), 0.2)  # never along the street

    def test_set_back_bench_looks_at_the_street(self):
        road = {"id": 1, "kind": "residential", "width": 6.0, "points": [[7, -50], [7, 50]]}
        out = _plan(_layout(roads=[road]), city=[_city(-4.0, 0)])  # 7 m from the kerb
        b = out["benches"][0]
        self.assertEqual(b["rule"], "face_street")
        self.assertGreater(_facing(b)[0], 0.9)

    def test_bench_standing_on_a_pedestrian_way_ignores_it(self):
        plaza = {"id": 1, "kind": "pedestrian", "width": 8.0, "points": [[0, -50], [0, 50]]}
        road = {"id": 2, "kind": "residential", "width": 6.0, "points": [[8, -50], [8, 50]]}
        out = _plan(_layout(roads=[plaza, road]), city=[_city(1.0, 0)])
        self.assertEqual(out["benches"][0]["rule"], "back_to_road")

    def test_park_bench_looks_into_the_park(self):
        park = {"id": 5, "ring": _square(0, 0, 40)}
        out = _plan(_layout(parks=[park]), city=[_city(3, 20)])
        b = out["benches"][0]
        self.assertEqual(b["rule"], "face_park_centre")
        self.assertGreater(_facing(b)[0], 0.9)


class KeepOffTheRoadTests(unittest.TestCase):
    ROAD = {"id": 1, "kind": "residential", "width": 6.0, "points": [[0, -60], [0, 60]]}

    def test_deep_in_carriageway_is_dropped(self):
        out = _plan(_layout(roads=[self.ROAD]), osm=[_osm(0.0, 0.0)])
        self.assertEqual(out["benches"], [])
        self.assertEqual(out["stats"]["dropped_carriageway"], 1)

    def test_shallow_survey_error_is_nudged_to_the_kerb(self):
        out = _plan(_layout(roads=[self.ROAD]), osm=[_osm(2.0, 10.0)])
        self.assertEqual(len(out["benches"]), 1)
        b = out["benches"][0]
        ways = _Ways(_layout(roads=[self.ROAD]))
        edge = ways.nearest(b["x"], b["y"], CARRIAGEWAY, 5.0)[0]
        self.assertGreaterEqual(edge, 0.5)
        self.assertGreater(b["x"], 3.0)  # pushed out the side it was on
        self.assertEqual(out["stats"]["nudged_to_kerb"], 1)

    def test_pedestrian_ways_do_not_count_as_carriageway(self):
        plaza = {"id": 2, "kind": "pedestrian", "width": 12.0, "points": [[0, -60], [0, 60]]}
        out = _plan(_layout(roads=[plaza]), osm=[_osm(0.0, 0.0)])
        self.assertEqual(len(out["benches"]), 1)

    def test_nothing_inside_buildings(self):
        out = _plan(_layout(buildings=[{"ring": _square(-5, -5, 10)}]), osm=[_osm(0, 0)])
        self.assertEqual(out["benches"], [])
        self.assertEqual(out["stats"]["dropped_building"], 1)


class MergeAndFallbackTests(unittest.TestCase):
    def test_same_bench_in_both_sources_counts_once_and_keeps_the_heading(self):
        out = _plan(_layout(), osm=[_osm(0, 0, direction="180")], city=[_city(0.5, 0.3)])
        self.assertEqual(len(out["benches"]), 1)
        self.assertEqual(out["benches"][0]["source"], "osm")
        self.assertEqual(out["benches"][0]["rule"], "osm_direction")

    def test_distinct_benches_are_kept(self):
        out = _plan(_layout(), osm=[_osm(0, 0, 1)], city=[_city(20, 0, 2)])
        self.assertEqual(len(out["benches"]), 2)

    def test_backrest_no_is_preserved(self):
        out = _plan(_layout(), osm=[_osm(0, 0, backrest="no")])
        self.assertFalse(out["benches"][0]["backrest"])

    def test_fallback_only_in_benchless_parks_with_a_path(self):
        park = {"id": 7, "ring": _square(0, 0, 80)}
        path = {"id": 1, "kind": "footway", "width": 1.6, "points": [[5, 40], [75, 40]]}
        bare = _plan(_layout(parks=[park], roads=[path]))
        self.assertGreaterEqual(len(bare["benches"]), 1)
        self.assertLessEqual(len(bare["benches"]), 2)
        self.assertTrue(all(b["source"] == "fallback" for b in bare["benches"]))
        for b in bare["benches"]:  # and they sit on the park, facing the path
            self.assertTrue(0 < b["x"] < 80 and 0 < b["y"] < 80)
            self.assertAlmostEqual(abs(_facing(b)[1]), 1.0, places=1)

        covered = _plan(_layout(parks=[park], roads=[path]), city=[_city(10, 10)])
        self.assertEqual([b["source"] for b in covered["benches"]], ["antwerp"])

    def test_no_pathless_or_tiny_park_gets_invented_benches(self):
        self.assertEqual(_plan(_layout(parks=[{"id": 1, "ring": _square(0, 0, 80)}]))["benches"], [])
        tiny = {"id": 2, "ring": _square(0, 0, 20)}
        path = {"id": 3, "kind": "footway", "width": 1.6, "points": [[1, 10], [19, 10]]}
        self.assertEqual(_plan(_layout(parks=[tiny], roads=[path]))["benches"], [])


class StopBenchTests(unittest.TestCase):
    RAIL = {"id": 1, "mode": "tram", "points": [[0.0, -80.0], [0.0, 80.0]], "refs": [], "tunnel": False}

    def _stop(self, x, y, bid=1):
        lat, lon = _ll(x, y)
        return {"id": bid, "lat": lat, "lon": lon, "tags": {"bench": "yes", "highway": "bus_stop"}}

    def _plan(self, layout, stops, osm=None, city=None):
        return plan_benches(layout, osm or [], {"antwerp": city or []}, ORIGIN, None, stops)

    def test_tram_platform_bench_faces_the_track_from_behind_the_pole(self):
        layout = _layout(transit_lines=[self.RAIL])
        out = self._plan(layout, [self._stop(2.0, 10.0)])
        self.assertEqual(len(out["benches"]), 1)
        b = out["benches"][0]
        self.assertEqual(b["source"], "stop")
        self.assertLess(_facing(b)[0], -0.9)  # looks west, at the rail
        self.assertGreaterEqual(b["x"], 2.0 + 0.1)  # sits behind the pole, off the bed
        self.assertGreaterEqual(abs(b["x"]), 2.1)

    def test_bus_stop_bench_faces_the_carriageway(self):
        road = {"id": 1, "kind": "residential", "width": 6.0, "points": [[0, -60], [0, 60]]}
        out = self._plan(_layout(roads=[road]), [self._stop(-4.0, 5.0)])
        b = out["benches"][0]
        self.assertGreater(_facing(b)[0], 0.9)  # looks east, at the road
        self.assertLess(b["x"], -4.0)  # behind the stop pole

    def test_surveyed_bench_at_the_stop_wins(self):
        layout = _layout(transit_lines=[self.RAIL])
        out = self._plan(layout, [self._stop(2.5, 10.0)], osm=[_osm(3.5, 11.0)])
        self.assertEqual([b["source"] for b in out["benches"]], ["osm"])
        self.assertEqual(out["stats"]["dropped_stop_covered"], 1)

    def test_stop_with_nothing_to_face_is_skipped(self):
        out = self._plan(_layout(), [self._stop(0.0, 0.0)])
        self.assertEqual(out["benches"], [])

    def test_only_bench_yes_platforms_are_extracted(self):
        doc = {
            "elements": [
                {"type": "node", "id": 1, "lat": 51.2, "lon": 4.4, "tags": {"highway": "bus_stop", "bench": "yes"}},
                {"type": "node", "id": 2, "lat": 51.2, "lon": 4.4, "tags": {"highway": "bus_stop", "bench": "no"}},
                {"type": "node", "id": 3, "lat": 51.2, "lon": 4.4, "tags": {"shop": "bakery", "bench": "yes"}},
            ]
        }
        self.assertEqual([r["id"] for r in osm_stop_benches(doc)], [1])


if __name__ == "__main__":
    unittest.main()
