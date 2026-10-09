"""Building passages (OSM tunnel=building_passage) open sealed alley mouths."""

from __future__ import annotations

import unittest

from cityview.passages import (
    PART_ID_OFFSET,
    apply_building_passages,
    cut_ring_for_passage,
)
from cityview.streetscape import annotate_layout, point_in_ring


def _hex_pinched() -> list[list[float]]:
    """Street-west hexagon that pinches at mid-front and mid-back portals.

    Same topology as Mechelsesteenweg 141: two short street edges meet at the
    passage mouth so a naïve façade pass reads as a dead-end wall.
    """
    return [
        [0.0, 3.0],  # NW
        [0.0, 0.0],  # W portal
        [0.0, -3.0],  # SW
        [20.0, -3.0],  # SE
        [20.0, 0.0],  # E portal
        [20.0, 3.0],  # NE
    ]


class CutRingTests(unittest.TestCase):
    def test_splits_pinched_footprint_into_two_open_parts(self):
        ring = _hex_pinched()
        parts = cut_ring_for_passage(ring, 0.0, 0.0, 20.0, 0.0, half_w=1.2)
        self.assertIsNotNone(parts)
        assert parts is not None
        self.assertEqual(len(parts), 2)
        # Corridor mid-point is outdoors.
        self.assertFalse(any(point_in_ring(10.0, 0.0, p) for p in parts))
        # Each flank keeps mass north / south of the alley.
        north = next(p for p in parts if sum(y for _x, y in p) / len(p) > 0)
        south = next(p for p in parts if sum(y for _x, y in p) / len(p) < 0)
        self.assertTrue(point_in_ring(10.0, 2.0, north))
        self.assertTrue(point_in_ring(10.0, -2.0, south))
        # Street mouth opens: west frontage no longer a continuous wall at x=0.
        west_ys = sorted(y for x, y in north + south if abs(x) < 0.05)
        self.assertGreaterEqual(len(west_ys), 2)
        self.assertGreater(max(west_ys) - min(west_ys), 2.0)

    def test_rejects_when_portals_missing(self):
        ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
        self.assertIsNone(cut_ring_for_passage(ring, 5.0, -2.0, 5.0, 10.0))


class ApplyPassagesTests(unittest.TestCase):
    def test_annotate_layout_splits_and_leaves_alley_gap(self):
        layout = {
            "buildings": [
                {
                    "id": 501410381,
                    "ring": _hex_pinched(),
                    "height": 12.0,
                    "floors": 4,
                    "roof_height": 1.5,
                    "roof_shape": "mansard",
                    "building_type": "eclectic",
                    "style": "eclectic",
                }
            ],
            "roads": [
                {
                    "id": 1,
                    "kind": "secondary",
                    "width": 8.0,
                    "points": [[-6.0, -10.0], [-6.0, 10.0]],
                    "name": "Mechelsesteenweg",
                },
                {
                    "id": 785350668,
                    "kind": "service",
                    "width": 4.0,
                    "points": [[0.0, 0.0], [20.0, 0.0]],
                    "passage": True,
                    "name": "",
                },
            ],
        }
        annotate_layout(layout)
        buildings = layout["buildings"]
        self.assertEqual(len(buildings), 2)
        ids = {b["id"] for b in buildings}
        self.assertIn(501410381, ids)
        self.assertIn(501410381 + PART_ID_OFFSET, ids)
        self.assertTrue(all(b.get("passage_cut") for b in buildings))
        # Walker can stand in the alley without being inside a footprint.
        self.assertFalse(any(point_in_ring(10.0, 0.0, b["ring"]) for b in buildings))
        stats = layout.get("passage_stats") or {}
        self.assertEqual(stats.get("buildings_split"), 1)
        self.assertEqual(stats.get("parts"), 2)

    def test_no_passage_roads_leaves_buildings_alone(self):
        layout = {
            "buildings": [{"id": 1, "ring": _hex_pinched()}],
            "roads": [
                {
                    "id": 2,
                    "kind": "service",
                    "width": 4.0,
                    "points": [[0.0, 0.0], [20.0, 0.0]],
                }
            ],
        }
        stats = apply_building_passages(layout)
        self.assertEqual(stats["buildings_split"], 0)
        self.assertEqual(len(layout["buildings"]), 1)


if __name__ == "__main__":
    unittest.main()
