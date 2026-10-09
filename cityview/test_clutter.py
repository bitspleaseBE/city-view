"""Tests for OSM-grounded street clutter."""

from __future__ import annotations

import math
import unittest

from cityview.clutter import classify, hoop_count, osm_clutter, plan_clutter
from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon

ORIGIN = (51.2, 4.4)


def _node(x: float, y: float, nid: int, **tags) -> dict:
    lat = ORIGIN[0] + y / METERS_PER_DEG_LAT
    lon = ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0])
    return {"id": nid, "type": "node", "lat": lat, "lon": lon, "tags": tags}


def _road(y: float = 0.0, width: float = 6.0, kind: str = "residential") -> dict:
    return {"id": 1, "kind": kind, "width": width, "points": [[-60.0, y], [60.0, y]]}


def _layout(**extra) -> dict:
    base = {"buildings": [], "roads": [_road()], "parks": [], "transit_lines": []}
    base.update(extra)
    return base


def _plan(osm_nodes, layout=None, spawn=None):
    items = osm_clutter({"elements": osm_nodes})
    return plan_clutter(layout or _layout(), items, ORIGIN, None, spawn)


class ClassifyTests(unittest.TestCase):
    def test_kinds_come_from_osm_tags(self):
        self.assertEqual(classify({"amenity": "waste_basket"}), "bin")
        self.assertEqual(classify({"amenity": "bicycle_parking", "capacity": "6"}), "bike_rack")
        self.assertEqual(classify({"barrier": "bollard"}), "bollard")
        self.assertEqual(classify({"emergency": "fire_hydrant", "fire_hydrant:type": "pillar"}), "hydrant")
        self.assertEqual(classify({"amenity": "post_box"}), "post_box")
        self.assertEqual(classify({"man_made": "street_cabinet"}), "cabinet")
        self.assertEqual(classify({"vending": "parking_tickets", "amenity": "vending_machine"}), "meter")
        self.assertEqual(classify({"highway": "street_lamp"}), "lamp")

    def test_things_that_do_not_stand_on_the_pavement_are_ignored(self):
        self.assertIsNone(classify({"emergency": "fire_hydrant", "fire_hydrant:type": "underground"}))
        self.assertIsNone(classify({"amenity": "bicycle_parking", "bicycle_parking": "building"}))
        self.assertIsNone(classify({"amenity": "waste_basket", "access": "private"}))
        self.assertIsNone(classify({"amenity": "recycling", "recycling_type": "centre"}))
        self.assertIsNone(classify({"amenity": "bench"}))

    def test_hoops_follow_capacity(self):
        self.assertEqual(hoop_count({"capacity": "6"}), 3)
        self.assertEqual(hoop_count({"capacity": "1"}), 1)
        self.assertEqual(hoop_count({"capacity": "80"}), 6)
        self.assertEqual(hoop_count({}), 2)
        self.assertEqual(hoop_count({"capacity": "many"}), 2)


class PlanTests(unittest.TestCase):
    def test_a_mapped_bin_is_placed_and_faces_the_street(self):
        out = _plan([_node(5.0, 6.0, 1, amenity="waste_basket")])
        self.assertEqual([c["kind"] for c in out["clutter"]], ["bin"])
        c = out["clutter"][0]
        # Street is south of the bin: front (local +Y rotated by yaw) points to -y.
        fy = math.cos(c["yaw"])
        self.assertLess(fy, -0.9)

    def test_nothing_is_invented(self):
        self.assertEqual(_plan([])["clutter"], [])

    def test_duplicates_collapse_per_kind_but_not_across_kinds(self):
        out = _plan(
            [
                _node(5.0, 6.0, 1, amenity="waste_basket"),
                _node(5.3, 6.0, 2, amenity="waste_basket"),
                _node(5.3, 6.0, 3, amenity="post_box"),
            ]
        )
        self.assertEqual(sorted(c["kind"] for c in out["clutter"]), ["bin", "post_box"])
        self.assertEqual(out["stats"]["dropped_duplicate"], 1)

    def test_inside_a_building_is_dropped(self):
        house = {"id": 9, "ring": [[0, 5], [10, 5], [10, 15], [0, 15]]}
        out = _plan([_node(5.0, 10.0, 1, amenity="waste_basket")], _layout(buildings=[house]))
        self.assertEqual(out["clutter"], [])
        self.assertEqual(out["stats"]["dropped_building"], 1)

    def test_carriageway_survey_noise_slides_to_the_kerb_but_deep_points_drop(self):
        shallow = _plan([_node(5.0, 2.5, 1, amenity="waste_basket")])  # 0.5 m into a 6 m road
        self.assertEqual(len(shallow["clutter"]), 1)
        self.assertGreaterEqual(shallow["clutter"][0]["y"], 3.0)
        self.assertEqual(shallow["stats"]["nudged_to_kerb"], 1)
        deep = _plan([_node(5.0, 0.0, 1, amenity="waste_basket")])
        self.assertEqual(deep["clutter"], [])
        self.assertEqual(deep["stats"]["dropped_carriageway"], 1)

    def test_bollards_may_stand_on_the_road(self):
        out = _plan([_node(5.0, 0.5, 1, barrier="bollard")])
        self.assertEqual([c["kind"] for c in out["clutter"]], ["bollard"])

    def test_small_items_far_from_the_spawn_are_lod_culled_landmarks_are_not(self):
        far = [
            _node(5.0, 6.0, 1, amenity="waste_basket"),
            _node(8.0, 6.0, 2, emergency="fire_hydrant", **{"fire_hydrant:type": "pillar"}),
        ]
        out = _plan(far, spawn=(5000.0, 5000.0))
        self.assertEqual([c["kind"] for c in out["clutter"]], ["hydrant"])
        self.assertEqual(out["stats"]["dropped_far"], 1)

    def test_bike_racks_carry_a_hoop_count_and_run_along_the_kerb(self):
        out = _plan([_node(5.0, 6.0, 1, amenity="bicycle_parking", capacity="8")])
        rack = out["clutter"][0]
        self.assertEqual(rack["hoops"], 4)
        # Local X (hoop row) is perpendicular to the front, which faces the street (-y): row runs along x.
        self.assertAlmostEqual(abs(math.cos(rack["yaw"])), 1.0, places=2)

    def test_way_centroids_work_for_areas(self):
        elements = [
            {"id": 1, "type": "node", "lat": 51.2, "lon": 4.4, "tags": {}},
            {"id": 2, "type": "node", "lat": 51.2, "lon": 4.4004, "tags": {}},
            {"id": 3, "type": "way", "nodes": [1, 2], "tags": {"amenity": "bicycle_parking", "capacity": "4"}},
        ]
        items = osm_clutter({"elements": elements})
        self.assertEqual([i["kind"] for i in items], ["bike_rack"])
        self.assertAlmostEqual(items[0]["lon"], 4.4002, places=5)


if __name__ == "__main__":
    unittest.main()
