"""Tests for OSM wall / hedge / fence planning."""

from __future__ import annotations

import math
import unittest

from cityview import barriers as bw
from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon

ORIGIN = (51.2, 4.4)


def ll(x: float, y: float) -> tuple[float, float]:
    return (ORIGIN[0] + y / METERS_PER_DEG_LAT, ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0]))


def way(wid: int, kind: str, pts: list[tuple[float, float]], **tags):
    return {"id": wid, "kind": kind, "height": tags.pop("height", bw.DEFAULT_HEIGHT[kind]), "surface": "render", "pts": [ll(*p) for p in pts]}


def layout(buildings=(), roads=()):
    return {"buildings": [{"ring": r} for r in buildings], "roads": list(roads), "transit_lines": []}


def square(x, y, s=10.0):
    return [[x, y], [x + s, y], [x + s, y + s], [x, y + s]]


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(bw.classify({"barrier": "wall"}), "wall")
        self.assertEqual(bw.classify({"barrier": "retaining_wall"}), "retaining")
        self.assertEqual(bw.classify({"barrier": "hedge"}), "hedge")
        self.assertEqual(bw.classify({"barrier": "fence"}), "fence")
        self.assertIsNone(bw.classify({"barrier": "gate"}))
        self.assertIsNone(bw.classify({"barrier": "wall", "location": "underground"}))
        self.assertIsNone(bw.classify({"barrier": "wall", "layer": "-1"}))
        self.assertIsNone(bw.classify({"highway": "residential"}))

    def test_height_and_surface(self):
        self.assertEqual(bw.parse_height({"height": "2.5"}, "wall"), 2.5)
        self.assertEqual(bw.parse_height({"height": "2,5 m"}, "wall"), 2.5)
        self.assertEqual(bw.parse_height({"height": "99"}, "wall"), bw.MAX_HEIGHT)
        self.assertEqual(bw.parse_height({"height": "tall"}, "hedge"), bw.DEFAULT_HEIGHT["hedge"])
        self.assertEqual(bw.parse_height({}, "fence"), bw.DEFAULT_HEIGHT["fence"])
        self.assertEqual(bw.surface({"material": "brick"}, "wall"), "brick")
        self.assertEqual(bw.surface({}, "wall"), "render")
        self.assertEqual(bw.surface({"material": "wood"}, "wall"), "render")
        self.assertEqual(bw.surface({}, "hedge"), "hedge")

    def test_osm_barriers_reads_ways(self):
        osm = {
            "elements": [
                {"type": "node", "id": 1, "lat": 51.2, "lon": 4.4},
                {"type": "node", "id": 2, "lat": 51.2, "lon": 4.4005},
                {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"barrier": "wall", "height": "2.2", "material": "brick"}},
                {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"barrier": "gate"}},
                {"type": "way", "id": 11, "nodes": [1], "tags": {"barrier": "wall"}},
            ]
        }
        found = bw.osm_barriers(osm)
        self.assertEqual([f["id"] for f in found], [9])
        self.assertEqual((found[0]["height"], found[0]["surface"]), (2.2, "brick"))


class PlanTests(unittest.TestCase):
    def plan(self, items, lay=None, spawn=None, bbox=None):
        return bw.plan_barriers(lay or layout(), items, ORIGIN, bbox, spawn)

    def test_free_wall_is_one_run_with_its_length(self):
        out = self.plan([way(1, "wall", [(0, 0), (20, 0)])])
        self.assertEqual(len(out["barriers"]), 1)
        run = out["barriers"][0]
        self.assertAlmostEqual(math.hypot(run["x1"] - run["x0"], run["y1"] - run["y0"]), 20.0, delta=0.1)
        self.assertEqual(run["h"], bw.DEFAULT_HEIGHT["wall"])

    def test_wall_through_a_house_is_split_not_drawn_through_it(self):
        lay = layout(buildings=[square(8, -5, 10)])
        out = self.plan([way(1, "wall", [(0, 0), (30, 0)])], lay)
        self.assertEqual(len(out["barriers"]), 2)
        for run in out["barriers"]:
            for x in (run["x0"], run["x1"]):
                self.assertFalse(8 - bw.BUILDING_MARGIN < x < 18 + bw.BUILDING_MARGIN)
        self.assertGreater(out["stats"]["dropped_building"], 0)

    def test_wall_hugging_a_facade_is_dropped(self):
        lay = layout(buildings=[square(0, 0, 20)])
        out = self.plan([way(1, "wall", [(0, -0.1), (20, -0.1)])], lay)
        self.assertEqual(out["barriers"], [])

    def test_wall_on_a_carriageway_is_dropped(self):
        road = {"id": 5, "kind": "residential", "width": 8.0, "points": [[0.0, 0.0], [40.0, 0.0]]}
        out = self.plan([way(1, "wall", [(0, 0), (30, 0)]), way(2, "wall", [(0, 6), (30, 6)])], layout(roads=[road]))
        self.assertEqual([r["id"] for r in out["barriers"]], [2])

    def test_hedges_and_fences_are_lod_culled_but_walls_are_not(self):
        items = [way(1, "hedge", [(900, 0), (910, 0)]), way(2, "fence", [(900, 5), (910, 5)]), way(3, "wall", [(900, 10), (910, 10)])]
        out = self.plan(items, spawn=(0.0, 0.0))
        self.assertEqual([r["kind"] for r in out["barriers"]], ["wall"])
        near = self.plan([way(1, "hedge", [(10, 0), (20, 0)])], spawn=(0.0, 0.0))
        self.assertEqual(len(near["barriers"]), 1)

    def test_outside_bbox_dropped(self):
        bbox = (ORIGIN[0] - 0.0005, ORIGIN[1] - 0.0005, ORIGIN[0] + 0.0005, ORIGIN[1] + 0.0005)
        out = self.plan([way(1, "wall", [(-80, 0), (80, 0)])], bbox=bbox)
        self.assertEqual(len(out["barriers"]), 1)
        run = out["barriers"][0]
        self.assertLess(math.hypot(run["x1"] - run["x0"], run["y1"] - run["y0"]), 120.0)

    def test_deterministic_and_attach(self):
        items = [way(1, "wall", [(0, 0), (20, 0)]), way(2, "hedge", [(0, 5), (9, 5)])]
        self.assertEqual(self.plan(items), self.plan(items))
        lay = layout()
        osm = {"elements": []}
        plan = bw.attach_barriers(lay, osm, (51.0, 4.0, 51.4, 4.8), ORIGIN)
        self.assertEqual(lay["barriers"], [])
        self.assertIn("0 runs", bw.summarize(plan))


if __name__ == "__main__":
    unittest.main()
