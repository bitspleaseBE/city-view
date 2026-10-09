import json
import unittest
from pathlib import Path

from cityview.directions import (
    infer_parallel_track_directions,
    mark_dual_carriageways,
    parse_oneway,
    parse_oneway_bus,
    route_way_directions,
)
from cityview.streetscape import export_roads_near_spawn, export_transit_near_spawn

VIEWER = Path(__file__).resolve().parents[1] / "viewer"


class OnewayTagTests(unittest.TestCase):
    def test_car_directions(self):
        self.assertEqual(parse_oneway({"highway": "residential", "oneway": "yes"}), 1)
        self.assertEqual(parse_oneway({"highway": "residential", "oneway": "-1"}), -1)
        self.assertEqual(parse_oneway({"highway": "residential", "oneway": "no"}), 0)
        self.assertEqual(parse_oneway({"highway": "residential"}), 0)

    def test_implicit_oneways(self):
        self.assertEqual(parse_oneway({"highway": "tertiary", "junction": "roundabout"}), 1)
        self.assertEqual(parse_oneway({"highway": "motorway"}), 1)
        # An explicit tag always beats the implicit rule.
        self.assertEqual(parse_oneway({"highway": "motorway", "oneway": "no"}), 0)

    def test_bus_follows_car_unless_exempt(self):
        tags = {"highway": "residential", "oneway": "yes"}
        self.assertEqual(parse_oneway_bus(tags), 1)
        self.assertEqual(parse_oneway_bus({**tags, "oneway:bus": "no"}), 0)
        self.assertEqual(parse_oneway_bus({**tags, "busway": "opposite_lane"}), 0)
        self.assertEqual(parse_oneway_bus({"highway": "residential"}), 0)


def _way(wid, nodes):
    return {"id": wid, "nodes": nodes}


class RouteDirectionTests(unittest.TestCase):
    def test_direction_from_ordered_route_members(self):
        # A: 1->2, B: 2->3 (stored the right way round); C is stored 4->3 but driven 3->4.
        ways = {10: _way(10, [1, 2]), 11: _way(11, [2, 3]), 12: _way(12, [4, 3])}
        rel = {
            "tags": {"type": "route", "route": "tram"},
            "members": [
                {"type": "way", "ref": 10, "role": ""},
                {"type": "way", "ref": 11, "role": ""},
                {"type": "way", "ref": 12, "role": ""},
                {"type": "node", "ref": 99, "role": "stop"},
                {"type": "way", "ref": 500, "role": "platform"},
            ],
        }
        got = route_way_directions({1: rel}, ways)
        self.assertEqual(got, {10: 1, 11: 1, 12: -1})

    def test_opposite_routes_on_one_way_cancel_out(self):
        ways = {10: _way(10, [1, 2]), 11: _way(11, [2, 3]), 12: _way(12, [0, 1])}
        out = {"tags": {"route": "tram"}, "members": [{"type": "way", "ref": r, "role": ""} for r in (12, 10, 11)]}
        back = {"tags": {"route": "tram"}, "members": [{"type": "way", "ref": r, "role": ""} for r in (11, 10, 12)]}
        got = route_way_directions({1: out, 2: back}, ways)
        self.assertEqual(got[10], 0)

    def test_parallel_tracks_use_right_hand_traffic(self):
        # Two tracks 3.5 m apart heading north. The one on the *right* (east) must be driven
        # northwards (partner on the left), so the western track runs south.
        east = {"id": "east", "points": [[3.5, 0.0], [3.5, 100.0]], "direction": 0}
        west = {"id": "west", "points": [[0.0, 0.0], [0.0, 100.0]], "direction": 0}
        infer_parallel_track_directions([east, west])
        self.assertEqual(east["direction"], 1)
        self.assertEqual(west["direction"], -1)

    def test_dual_carriageway_halves_are_flagged(self):
        a = {"name": "Boulevard", "oneway": 1, "points": [[0.0, 0.0], [0.0, 100.0]]}
        b = {"name": "Boulevard", "oneway": 1, "points": [[12.0, 100.0], [12.0, 0.0]]}
        side = {"name": "Boulevard", "oneway": 1, "points": [[-90.0, 0.0], [-90.0, 100.0]]}
        mark_dual_carriageways([a, b, side])
        self.assertTrue(a.get("dualCarriageway") and b.get("dualCarriageway"))
        self.assertFalse(side.get("dualCarriageway"))


class ExportTests(unittest.TestCase):
    def test_roads_export_carries_directions(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0, 0], [50, 0]], "oneway": 1, "oneway_bus": 0},
                {"id": 2, "kind": "residential", "width": 6.0, "points": [[0, 10], [50, 10]]},
            ],
            "transit_lines": [],
        }
        roads = export_roads_near_spawn(layout, {"x": 0, "y": 0})["roads"]
        by_id = {r["id"]: r for r in roads}
        self.assertEqual((by_id[1]["oneway"], by_id[1]["onewayBus"]), (1, 0))
        self.assertEqual((by_id[2]["oneway"], by_id[2]["onewayBus"]), (0, 0))

    def test_transit_export_directs_gtfs_and_relation_tracks(self):
        layout = {
            "roads": [],
            "transit_lines": [
                {"id": "bus1", "mode": "bus", "source": "gtfs", "points": [[0, 0], [50, 0]]},
                {"id": 7, "mode": "tram", "direction": -1, "points": [[0, 5], [50, 5]]},
                {"id": 8, "mode": "tram", "points": [[0, 40], [50, 40]]},
            ],
        }
        paths = {p["id"]: p for p in export_transit_near_spawn(layout, {"x": 0, "y": 0})["paths"]}
        self.assertEqual(paths["bus1"]["direction"], 1)
        self.assertEqual(paths[7]["direction"], -1)
        self.assertEqual(paths[8]["direction"], 0)  # lone track, no relation: unknown


class CommittedDataTests(unittest.TestCase):
    """The committed viewer data must carry the directions the runtime enforces."""

    def test_roads_json_has_oneway_and_dual_carriageway(self):
        roads = json.loads((VIEWER / "roads.json").read_text())["roads"]
        self.assertTrue(all("oneway" in r and "onewayBus" in r for r in roads))
        halves = [r for r in roads if r.get("dualCarriageway")]
        self.assertGreaterEqual(len(halves), 2)
        self.assertTrue(all(r["oneway"] in (1, -1) for r in halves))

    def test_tram_tracks_run_opposite_ways(self):
        paths = json.loads((VIEWER / "transit.json").read_text())["paths"]
        trams = [p for p in paths if p["mode"] == "tram"]
        self.assertGreaterEqual(len(trams), 2)
        self.assertTrue(all(p["direction"] in (1, -1) for p in trams))
        # The two tracks of the Mechelsesteenweg median head opposite ways in world space.
        def heading(p):
            (ax, ay), (bx, by) = p["points"][0], p["points"][-1]
            return (bx - ax) * p["direction"], (by - ay) * p["direction"]
        h = [heading(p) for p in trams[:2]]
        self.assertLess(h[0][0] * h[1][0] + h[0][1] * h[1][1], 0)

    def test_buses_follow_their_shape_order(self):
        paths = json.loads((VIEWER / "transit.json").read_text())["paths"]
        buses = [p for p in paths if p["mode"] == "bus"]
        self.assertTrue(buses)
        self.assertTrue(all(p["direction"] == 1 for p in buses))


if __name__ == "__main__":
    unittest.main()
