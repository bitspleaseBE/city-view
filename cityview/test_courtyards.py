"""Tests for OSM courtyard surface planning."""

from __future__ import annotations

import unittest

from cityview import courtyards as cy
from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon

ORIGIN = (51.2, 4.4)


def ll(x: float, y: float) -> tuple[float, float]:
    return (ORIGIN[0] + y / METERS_PER_DEG_LAT, ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0]))


def item(wid, kind, pts, surface=None, layer=None):
    surface = surface or cy.KINDS[kind][0]
    return {"id": wid, "kind": kind, "surface": surface, "layer": layer or cy.layer_for(kind, surface), "pts": [ll(*p) for p in pts]}


def sq(x, y, s=10.0):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(cy.classify({"amenity": "parking", "parking": "surface"}), "parking")
        self.assertEqual(cy.classify({"amenity": "parking"}), "parking")
        self.assertEqual(cy.classify({"leisure": "playground"}), "playground")
        self.assertEqual(cy.classify({"leisure": "pitch"}), "pitch")
        self.assertEqual(cy.classify({"landuse": "forest"}), "woodland")
        self.assertEqual(cy.classify({"natural": "wood"}), "woodland")
        self.assertEqual(cy.classify({"leisure": "swimming_pool"}), "pool")
        self.assertEqual(cy.classify({"amenity": "fountain"}), "pool")

    def test_skips(self):
        for parking in ("street_side", "lane", "multi-storey", "underground", "rooftop"):
            self.assertIsNone(cy.classify({"amenity": "parking", "parking": parking}))
        self.assertIsNone(cy.classify({"amenity": "parking", "building": "yes"}))
        self.assertIsNone(cy.classify({"amenity": "parking", "layer": "-1"}))
        self.assertIsNone(cy.classify({"amenity": "parking", "location": "underground"}))
        self.assertIsNone(cy.classify({"highway": "residential"}))
        # Parks / gardens are drawn by the park pass, not here.
        self.assertIsNone(cy.classify({"leisure": "park"}))
        self.assertIsNone(cy.classify({"leisure": "garden"}))

    def test_surface_override(self):
        self.assertEqual(cy.surface_for({}, "parking"), "asphalt")
        self.assertEqual(cy.surface_for({"surface": "paving_stones"}, "parking"), "paving")
        self.assertEqual(cy.surface_for({"surface": "artificial_turf"}, "pitch"), "turf")
        self.assertEqual(cy.surface_for({"surface": "grass"}, "playground"), "grass")
        self.assertEqual(cy.surface_for({"surface": "lava"}, "playground"), "rubber")
        self.assertEqual(cy.surface_for({"surface": "grass"}, "pool"), "pool")

    def test_layers(self):
        self.assertEqual(cy.layer_for("playground", "rubber"), "sport")
        self.assertEqual(cy.layer_for("playground", "grass"), "grass")
        self.assertEqual(cy.layer_for("parking", "asphalt"), "paving")
        self.assertEqual(cy.layer_for("construction", "dirt"), "earth")
        self.assertEqual(cy.layer_for("pool", "pool"), "water")
        for kind, (_surface, layer) in cy.KINDS.items():
            self.assertIn(layer, cy.LAYERS, kind)


class OsmAreaTests(unittest.TestCase):
    def test_closed_ways_only(self):
        nodes = [{"type": "node", "id": i, "lat": 51.2 + i * 1e-5, "lon": 4.4 + (i % 2) * 1e-5} for i in range(1, 6)]
        closed = {"type": "way", "id": 10, "nodes": [1, 2, 3, 4, 1], "tags": {"amenity": "parking"}}
        open_way = {"type": "way", "id": 11, "nodes": [1, 2, 3, 4], "tags": {"amenity": "parking"}}
        other = {"type": "way", "id": 12, "nodes": [1, 2, 3, 4, 1], "tags": {"highway": "service"}}
        areas = cy.osm_areas({"elements": nodes + [closed, open_way, other]})
        self.assertEqual([a["id"] for a in areas], [10])
        self.assertEqual(len(areas[0]["pts"]), 4)  # closing duplicate removed


class PlanTests(unittest.TestCase):
    def test_ccw_and_stats(self):
        cw = list(reversed(sq(0, 0)))
        plan = cy.plan_courtyards([item(1, "parking", cw)], ORIGIN)
        (area,) = plan["courtyards"]
        self.assertGreater(cy.ring_area(area["ring"]), 0)
        self.assertAlmostEqual(plan["stats"]["area_m2"], 100.0, delta=1.0)
        self.assertEqual(plan["stats"]["parking"], 1)

    def test_size_limits_and_exclusion(self):
        plan = cy.plan_courtyards(
            [
                item(1, "parking", sq(0, 0, 2.0)),
                item(2, "woodland", sq(0, 0, 500.0)),
                item(3, "parking", sq(0, 0, 10.0)),
                item(4, "parking", sq(50, 0, 10.0)),
            ],
            ORIGIN,
            exclude_ids={4},
        )
        self.assertEqual([c["id"] for c in plan["courtyards"]], [3])
        self.assertEqual(plan["stats"]["dropped_small"], 1)
        self.assertEqual(plan["stats"]["dropped_large"], 1)

    def test_bbox_and_bowtie(self):
        bbox = (ORIGIN[0] - 0.001, ORIGIN[1] - 0.001, ORIGIN[0] + 0.001, ORIGIN[1] + 0.001)
        bowtie = [(0, 0), (20, 20), (20, 0), (0, 10)]
        plan = cy.plan_courtyards(
            [item(1, "parking", sq(5000, 5000)), item(2, "parking", bowtie), item(3, "parking", sq(0, 0))],
            ORIGIN,
            bbox,
        )
        self.assertEqual([c["id"] for c in plan["courtyards"]], [3])
        self.assertEqual(plan["stats"]["dropped_outside"], 1)
        self.assertEqual(plan["stats"]["dropped_invalid"], 1)

    def test_attach_skips_drawn_parks(self):
        layout = {"parks": [{"id": 7}], "water": [{"id": 8}]}
        osm = {"elements": []}
        plan = cy.attach_courtyards(layout, osm, (51.1, 4.3, 51.3, 4.5), ORIGIN)
        self.assertEqual(layout["courtyards"], [])
        self.assertEqual(plan["stats"]["area_m2"], 0.0)


if __name__ == "__main__":
    unittest.main()
