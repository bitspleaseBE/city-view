"""Tests for surveyed-tree placement and the sparse-park Poisson fallback."""

from __future__ import annotations

import math
import unittest

from cityview.geo import project
from cityview.railclear import CLEAR_TREE
from cityview.roadclear import TRUNK_MARGIN
from cityview.trees import (
    CLEAR_REAL_TRUNK,
    _point_in_ring,
    plan_trees,
    poisson_fill,
    ring_area,
    tree_traits,
    _PointGrid,
)

ORIGIN = (51.2, 4.4)


def _ll(x: float, y: float) -> tuple[float, float]:
    """Local metres → lat/lon (inverse of cityview.geo.project)."""
    from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon

    return (ORIGIN[0] + y / METERS_PER_DEG_LAT, ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0]))


def _square(x0: float, y0: float, size: float) -> list[list[float]]:
    return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size]]


def _payload(points: list[tuple[float, float]], source: str = "antwerp") -> dict:
    recs = []
    for i, (x, y) in enumerate(points):
        lat, lon = _ll(x, y)
        recs.append({"id": i, "lat": lat, "lon": lon, "species": "Tilia cordata", "genus": "Tilia", "girth_cm": 90.0})
    return {"antwerp": recs} if source == "antwerp" else {"osm_trees": recs}


def _layout(**extra) -> dict:
    base = {"buildings": [], "roads": [], "parks": [], "transit_lines": []}
    base.update(extra)
    return base


def _collinear(points: list[tuple[float, float]], tol: float = 1.0) -> bool:
    """True when every point lies within ``tol`` metres of one straight line."""
    if len(points) < 3:
        return True
    (ax, ay), (bx, by) = points[0], points[-1]
    far = max(points, key=lambda p: math.hypot(p[0] - ax, p[1] - ay))
    bx, by = far
    length = math.hypot(bx - ax, by - ay) or 1.0
    return all(abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / length <= tol for x, y in points)


class RealTreeTests(unittest.TestCase):
    def test_real_points_are_kept_with_traits(self):
        pts = [(10.0, 10.0), (25.0, 40.0), (60.0, 15.0)]
        plan = plan_trees(_layout(), _payload(pts), ORIGIN)
        self.assertEqual(plan["stats"]["antwerp"], 3)
        self.assertEqual(plan["stats"]["fill"], 0)
        for tree, (x, y) in zip(plan["trees"], pts):
            self.assertAlmostEqual(tree["x"], x, delta=0.2)
            self.assertAlmostEqual(tree["y"], y, delta=0.2)
            self.assertGreater(tree["height"], 5.0)

    def test_duplicates_across_sources_collapse(self):
        payload = _payload([(5.0, 5.0)])
        payload.update(_payload([(5.6, 5.2), (30.0, 30.0)], source="osm"))
        plan = plan_trees(_layout(), payload, ORIGIN)
        self.assertEqual(plan["stats"]["antwerp"], 1)
        self.assertEqual(plan["stats"]["osm"], 1)
        self.assertEqual(plan["stats"]["dropped_duplicate"], 1)

    def test_nothing_inside_buildings(self):
        layout = _layout(buildings=[{"id": 1, "ring": _square(0.0, 0.0, 20.0)}])
        plan = plan_trees(layout, _payload([(10.0, 10.0), (40.0, 40.0)]), ORIGIN)
        self.assertEqual(len(plan["trees"]), 1)
        self.assertEqual(plan["stats"]["dropped_building"], 1)

    def test_trunks_stay_off_tram_beds(self):
        layout = _layout(
            transit_lines=[{"id": 1, "mode": "tram", "points": [[-100.0, 0.0], [100.0, 0.0]]}]
        )
        pts = [(0.0, 0.5), (10.0, 1.9), (20.0, CLEAR_REAL_TRUNK + 0.4), (30.0, 8.0)]
        plan = plan_trees(layout, _payload(pts), ORIGIN)
        self.assertEqual(plan["stats"]["dropped_rail"], 2)
        for tree in plan["trees"]:
            self.assertGreater(abs(tree["y"]), CLEAR_REAL_TRUNK - 0.2)

    def test_crown_pulled_back_from_tram_bed(self):
        layout = _layout(
            transit_lines=[{"id": 1, "mode": "tram", "points": [[-100.0, 0.0], [100.0, 0.0]]}]
        )
        payload = _payload([(0.0, 2.6)])
        payload["antwerp"][0]["girth_cm"] = 250.0  # big old tree, wide crown
        tree = plan_trees(layout, payload, ORIGIN)["trees"][0]
        self.assertLessEqual(tree["radius"], 2.6 - 1.4 + 1e-6)
        # Pruned as a whole: no tall bare pole under a shrunken crown.
        self.assertLessEqual(tree["height"], 2.4 + 3.4 * tree["radius"] + 1e-6)

    def test_heights_stay_in_street_scale(self):
        huge = tree_traits({"species": "Platanus hispanica", "girth_cm": 420.0}, 0, 0)
        self.assertLessEqual(huge["height"], 22.0)
        self.assertGreater(huge["height"], 17.0)
        cherry = tree_traits({"species": "Prunus serrulata", "girth_cm": 300.0}, 0, 0)
        self.assertLessEqual(cherry["height"], 8.5 * 1.07 + 1e-6)
        for girth in (20.0, 80.0, 160.0, 260.0):
            t = tree_traits({"species": "Tilia cordata", "girth_cm": girth}, 3.0, 4.0)
            # Crown spread stays plausible for the height (≥ ~45 % of it).
            self.assertGreaterEqual(2 * t["radius"], 0.45 * t["height"] - 0.3)

    def test_small_surveyed_crown_caps_height(self):
        t = tree_traits({"species": "Tilia cordata", "girth_cm": 220.0, "crown": "2"}, 0, 0)
        self.assertLessEqual(t["height"], 2.4 + 3.4 * t["radius"] + 1e-6)

    def test_trees_off_carriageway(self):
        layout = _layout(roads=[{"id": 1, "kind": "residential", "width": 8.0, "points": [[-50.0, 0.0], [50.0, 0.0]]}])
        plan = plan_trees(layout, _payload([(0.0, 0.5), (30.0, 6.0)]), ORIGIN)
        # The in-lane tree is snapped onto the pavement (not dropped, never left in the lane).
        self.assertEqual(len(plan["trees"]), 2)
        self.assertEqual(plan["stats"]["relocated_road"], 1)
        for tree in plan["trees"]:
            self.assertGreaterEqual(abs(tree["y"]) - 4.0, TRUNK_MARGIN - 0.01)

    def test_snap_keeps_tree_on_its_own_side_and_close(self):
        layout = _layout(roads=[{"id": 1, "kind": "residential", "width": 8.0, "points": [[-50.0, 0.0], [50.0, 0.0]]}])
        plan = plan_trees(layout, _payload([(0.0, -2.5), (20.0, 3.0)]), ORIGIN)
        low, high = sorted(plan["trees"], key=lambda t: t["x"])
        self.assertLess(low["y"], -4.0)  # was on the -y half: stays on the -y pavement
        self.assertGreater(high["y"], 4.0)
        self.assertLess(math.hypot(low["x"] - 0.0, low["y"] + 2.5), 2.6)

    def test_tree_in_lane_dropped_when_no_legal_ground_nearby(self):
        # Centre of a very wide road: nowhere within snap range is clear of the asphalt.
        layout = _layout(roads=[{"id": 1, "kind": "primary", "width": 16.0, "points": [[-50.0, 0.0], [50.0, 0.0]]}])
        plan = plan_trees(layout, _payload([(0.0, 0.0)]), ORIGIN)
        self.assertEqual(plan["trees"], [])
        self.assertEqual(plan["stats"]["dropped_road"], 1)

    def test_snap_does_not_walk_into_buildings_or_trams(self):
        layout = _layout(
            roads=[{"id": 1, "kind": "residential", "width": 8.0, "points": [[-50.0, 0.0], [50.0, 0.0]]}],
            buildings=[{"id": 1, "ring": [[-50.0, 4.2], [50.0, 4.2], [50.0, 20.0], [-50.0, 20.0]]}],
        )
        plan = plan_trees(layout, _payload([(0.0, 1.0)]), ORIGIN)
        # +y pavement is a façade; the tree goes to the free -y side or is dropped, never into the wall.
        for tree in plan["trees"]:
            self.assertLess(tree["y"], -4.0)

    def test_footpaths_are_not_carriageway(self):
        layout = _layout(roads=[{"id": 1, "kind": "footway", "width": 2.2, "points": [[-50.0, 0.0], [50.0, 0.0]]}])
        plan = plan_trees(layout, _payload([(0.0, 0.3)]), ORIGIN)
        self.assertEqual(len(plan["trees"]), 1)
        self.assertEqual(plan["stats"]["relocated_road"], 0)

    def test_fill_trees_never_on_carriageway(self):
        park = {"id": 9, "ring": _square(-60.0, -60.0, 120.0)}
        layout = _layout(
            parks=[park],
            roads=[{"id": 1, "kind": "residential", "width": 8.0, "points": [[-60.0, 0.0], [60.0, 0.0]]}],
        )
        plan = plan_trees(layout, {}, ORIGIN)
        self.assertTrue(plan["trees"])
        for tree in plan["trees"]:
            self.assertGreaterEqual(abs(tree["y"]) - 4.0, TRUNK_MARGIN)


class ParkFillTests(unittest.TestCase):
    def _park(self, size: float = 120.0) -> dict:
        return {"id": 42, "ring": _square(0.0, 0.0, size)}

    def test_well_surveyed_park_gets_no_fill(self):
        park = self._park()
        # 14 real trees on a jittered grid inside a 14 400 m² park: plenty.
        pts = [(15.0 + 25.0 * i + (7 * j) % 5, 15.0 + 25.0 * j + (3 * i) % 4) for i in range(4) for j in range(4)]
        plan = plan_trees(_layout(parks=[park]), _payload(pts), ORIGIN)
        self.assertEqual(plan["stats"]["fill"], 0)
        self.assertEqual(plan["stats"]["antwerp"], len(pts))

    def test_sparse_park_is_filled_naturalistically(self):
        park = self._park()
        plan = plan_trees(_layout(parks=[park]), _payload([(60.0, 60.0)]), ORIGIN)
        fill = [t for t in plan["trees"] if t["source"] == "fill"]
        self.assertGreaterEqual(len(fill), 6)
        pts = [(t["x"], t["y"]) for t in fill]
        # Never a parade: no straight line, and blue-noise spacing between neighbours.
        self.assertFalse(_collinear(pts, tol=3.0))
        for i, a in enumerate(pts):
            for b in pts[i + 1 :]:
                self.assertGreater(math.hypot(a[0] - b[0], a[1] - b[1]), 5.0)
        for x, y in pts:
            self.assertTrue(_point_in_ring(x, y, park["ring"]))

    def test_fill_avoids_rails_buildings_and_is_deterministic(self):
        park = self._park()
        layout = _layout(
            parks=[park],
            buildings=[{"id": 9, "ring": _square(80.0, 80.0, 30.0)}],
            transit_lines=[{"id": 1, "mode": "tram", "points": [[0.0, 60.0], [120.0, 60.0]]}],
        )
        a = plan_trees(layout, {}, ORIGIN)
        b = plan_trees(layout, {}, ORIGIN)
        self.assertEqual(a["trees"], b["trees"])
        for tree in a["trees"]:
            self.assertGreater(abs(tree["y"] - 60.0), CLEAR_TREE - 0.1)
            self.assertFalse(80.0 <= tree["x"] <= 110.0 and 80.0 <= tree["y"] <= 110.0)

    def test_tiny_parks_are_skipped(self):
        plan = plan_trees(_layout(parks=[{"id": 1, "ring": _square(0.0, 0.0, 10.0)}]), {}, ORIGIN)
        self.assertEqual(plan["stats"]["fill"], 0)

    def test_bushes_not_on_a_line(self):
        plan = plan_trees(_layout(parks=[self._park()]), {}, ORIGIN)
        pts = [(b["x"], b["y"]) for b in plan["bushes"]]
        self.assertGreaterEqual(len(pts), 10)
        self.assertFalse(_collinear(pts, tol=3.0))


class HelperTests(unittest.TestCase):
    def test_poisson_fill_respects_spacing(self):
        import random

        ring = _square(0.0, 0.0, 80.0)
        pts = poisson_fill(ring, random.Random(1), 25, 7.0, 1.0, lambda x, y: True, _PointGrid())
        self.assertGreater(len(pts), 10)
        for i, a in enumerate(pts):
            for b in pts[i + 1 :]:
                self.assertGreaterEqual(math.hypot(a[0] - b[0], a[1] - b[1]), 7.0)
        self.assertGreater(ring_area(ring), 0)

    def test_traits_scale_with_girth_and_genus(self):
        young = tree_traits({"species": "Acer campestre", "girth_cm": 20.0}, 0, 0)
        old = tree_traits({"species": "Acer campestre", "girth_cm": 250.0}, 0, 0)
        self.assertGreater(old["height"], young["height"])
        self.assertGreater(old["radius"], young["radius"])
        self.assertEqual(tree_traits({"species": "Taxus baccata"}, 0, 0)["shape"], "conifer")
        col = tree_traits({"species": "Carpinus betulus 'Fastigiata'", "girth_cm": 90.0}, 0, 0)
        self.assertEqual(col["shape"], "columnar")
        plain = tree_traits({"species": "Carpinus betulus", "girth_cm": 90.0}, 0, 0)
        self.assertLess(col["radius"], plain["radius"])

    def test_project_roundtrip_helper(self):
        lat, lon = _ll(50.0, -30.0)
        x, y = project(lat, lon, *ORIGIN)
        self.assertAlmostEqual(x, 50.0, places=2)
        self.assertAlmostEqual(y, -30.0, places=2)


if __name__ == "__main__":
    unittest.main()
