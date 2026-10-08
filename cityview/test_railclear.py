"""Tests for rail-corridor clearance (no trees / pavement / zebras on tram beds)."""

from __future__ import annotations

import unittest

from cityview.osm import layout_from_osm
from cityview.railclear import (
    CLEAR_SIDEWALK,
    CLEAR_TREE,
    RailIndex,
    clear_runs,
    densify,
    rail_crossing_nodes,
    span_intervals,
    surface_rail_polylines,
    zebra_touches_rails,
)


def _layout(tunnel: bool = False) -> dict:
    return {
        "transit_lines": [
            {"id": 1, "mode": "tram", "points": [[-50.0, 0.0], [50.0, 0.0]], "tunnel": tunnel},
            {"id": 2, "mode": "bus", "points": [[0.0, -50.0], [0.0, 50.0]]},
        ]
    }


class RailIndexTests(unittest.TestCase):
    def test_distance_and_within(self):
        idx = RailIndex.from_layout(_layout())
        self.assertAlmostEqual(idx.distance(0.0, 3.0), 3.0, places=6)
        self.assertTrue(idx.within(10.0, CLEAR_TREE - 0.1, CLEAR_TREE))
        self.assertFalse(idx.within(10.0, CLEAR_TREE + 0.5, CLEAR_TREE))

    def test_buses_and_tunnels_are_not_surface_rails(self):
        self.assertEqual(len(surface_rail_polylines(_layout())), 1)
        self.assertEqual(len(surface_rail_polylines(_layout(tunnel=True))), 0)
        self.assertFalse(RailIndex.from_layout(_layout(tunnel=True)))

    def test_empty_index_is_inert(self):
        idx = RailIndex([])
        self.assertFalse(idx.within(0.0, 0.0, 10.0))
        self.assertEqual(clear_runs([[0, 0], [10, 0]], idx, CLEAR_SIDEWALK), [[[0, 0], [10, 0]]])


class ClearRunsTests(unittest.TestCase):
    def test_sidewalk_is_cut_where_it_crosses_tram_bed(self):
        idx = RailIndex.from_layout(_layout())
        walk = [[0.0, -30.0], [0.0, 30.0]]  # crosses the tram line at y=0
        runs = clear_runs(walk, idx, CLEAR_SIDEWALK)
        self.assertEqual(len(runs), 2)
        for run in runs:
            for _x, y in run:
                self.assertGreater(abs(y), CLEAR_SIDEWALK - 1e-6)

    def test_distant_sidewalk_is_untouched(self):
        idx = RailIndex.from_layout(_layout())
        walk = [[-40.0, 20.0], [40.0, 20.0]]
        self.assertEqual(clear_runs(walk, idx, CLEAR_SIDEWALK), [walk])

    def test_densify_caps_segment_length(self):
        pts = densify([[0.0, 0.0], [10.0, 0.0]], 2.0)
        self.assertEqual(len(pts), 6)


class ZebraTests(unittest.TestCase):
    def test_zebra_across_tram_is_detected(self):
        idx = RailIndex.from_layout(_layout())
        # Approach travelling +y at x=0 with the stop line 4 m before the tram.
        self.assertTrue(zebra_touches_rails(0.0, -3.0, 0.0, 1.0, 6.0, idx))

    def test_zebra_away_from_tram_is_clean(self):
        idx = RailIndex.from_layout(_layout())
        self.assertFalse(zebra_touches_rails(0.0, 30.0, 0.0, 1.0, 6.0, idx))

    def test_span_intervals_mark_on_rail_piece_only(self):
        idx = RailIndex.from_layout(_layout())
        # Stripe centred on the tram line, running across it (along y).
        pieces = span_intervals(0.0, 0.0, 0.0, 1.0, 8.0, idx)
        flags = [on for _a, _b, on in pieces]
        self.assertEqual(flags, [False, True, False])
        self.assertAlmostEqual(pieces[0][0], -4.0)
        self.assertAlmostEqual(pieces[-1][1], 4.0)

    def test_osm_crossing_on_rails_is_reported(self):
        idx = RailIndex.from_layout(_layout())
        layout = {
            "crossings": [
                {"id": 1, "x": 5.0, "y": 2.0, "kind": "marked"},
                {"id": 2, "x": 5.0, "y": 40.0, "kind": "marked"},
            ]
        }
        near = rail_crossing_nodes(layout, idx)
        self.assertEqual([n["id"] for n in near], [1])


class OsmExtractionTests(unittest.TestCase):
    def test_tunnel_flag_and_crossings(self):
        osm = {
            "elements": [
                {"type": "node", "id": 1, "lat": 51.2000, "lon": 4.4100},
                {"type": "node", "id": 2, "lat": 51.2005, "lon": 4.4110},
                {"type": "node", "id": 3, "lat": 51.2010, "lon": 4.4120},
                {"type": "node", "id": 4, "lat": 51.2020, "lon": 4.4130},
                {
                    "type": "node",
                    "id": 5,
                    "lat": 51.2005,
                    "lon": 4.4110,
                    "tags": {"highway": "crossing", "crossing": "uncontrolled"},
                },
                {
                    "type": "node",
                    "id": 6,
                    "lat": 51.2006,
                    "lon": 4.4111,
                    "tags": {"highway": "crossing", "crossing": "unmarked"},
                },
                {"type": "way", "id": 100, "nodes": [1, 2], "tags": {"railway": "tram"}},
                {
                    "type": "way",
                    "id": 101,
                    "nodes": [3, 4],
                    "tags": {"railway": "tram", "tunnel": "yes"},
                },
            ]
        }
        layout = layout_from_osm(osm, (51.2, 4.41))
        flags = {ln["id"]: ln["tunnel"] for ln in layout["transit_lines"]}
        self.assertEqual(flags, {100: False, 101: True})
        self.assertEqual([c["id"] for c in layout["crossings"]], [5])
        self.assertEqual(layout["roads"], [])


if __name__ == "__main__":
    unittest.main()
