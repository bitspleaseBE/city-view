"""Tests for Velo Antwerpen GBFS station planning."""

from __future__ import annotations

import math
import unittest

from cityview.geo import METERS_PER_DEG_LAT, meters_per_deg_lon
from cityview.velo import (
    export_velo_for_viewer,
    plan_velo,
    seeded_bikes_available,
)

ORIGIN = (51.2, 4.4)


def _ll(x: float, y: float) -> tuple[float, float]:
    return (ORIGIN[0] + y / METERS_PER_DEG_LAT, ORIGIN[1] + x / meters_per_deg_lon(ORIGIN[0]))


def _station(sid: str, x: float, y: float, capacity: int = 20, **extra) -> dict:
    lat, lon = _ll(x, y)
    rec = {
        "id": sid,
        "name": f"{sid}- Test",
        "lat": lat,
        "lon": lon,
        "capacity": capacity,
        "address": "",
    }
    rec.update(extra)
    return rec


def _square(x0: float, y0: float, w: float, h: float | None = None) -> list[list[float]]:
    h = w if h is None else h
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]


def _layout(**extra) -> dict:
    base = {
        "buildings": [],
        "roads": [
            {
                "id": "r1",
                "kind": "residential",
                "width": 8.0,
                "points": [[-40.0, 0.0], [40.0, 0.0]],
            }
        ],
        "parks": [],
        "transit_lines": [],
    }
    base.update(extra)
    return base


class SeedOccupancyTests(unittest.TestCase):
    def test_seeded_occupancy_is_stable_and_in_range(self):
        a = seeded_bikes_available("042", 35)
        b = seeded_bikes_available("042", 35)
        self.assertEqual(a, b)
        self.assertGreaterEqual(a, 1)
        self.assertLess(a, 35)
        self.assertGreaterEqual(a / 35, 0.35)
        self.assertLessEqual(a / 35, 0.75)


class PlanVeloTests(unittest.TestCase):
    def test_places_station_along_street(self):
        # Pavement north of the 8 m road (half=4): y=5 is ~1 m past the kerb.
        plan = plan_velo(_layout(), {"stations": [_station("042", 0.0, 5.0, 20)]}, ORIGIN)
        self.assertEqual(plan["stats"]["placed"], 1)
        st = plan["stations"][0]
        self.assertEqual(st["id"], "042")
        self.assertEqual(st["capacity"], 20)
        self.assertEqual(st["bikesAvailable"], seeded_bikes_available("042", 20))
        self.assertEqual(st["rule"], "along_street")
        # Facing the street (−Y): yaw ≈ π so local +Y points south toward the road.
        self.assertAlmostEqual(abs(math.sin(st["yaw"])), 0.0, places=1)

    def test_dedupes_nearby_stations(self):
        plan = plan_velo(
            _layout(),
            {
                "stations": [
                    _station("046", 0.0, 5.0, 36),
                    _station("046b", 2.0, 5.5, 36),
                ]
            },
            ORIGIN,
        )
        self.assertEqual(plan["stats"]["placed"], 1)
        self.assertEqual(plan["stats"]["dropped_duplicate"], 1)

    def test_drops_inside_building(self):
        plan = plan_velo(
            _layout(buildings=[{"ring": _square(-5, 3, 10, 10)}]),
            {"stations": [_station("029", 0.0, 5.0, 18)]},
            ORIGIN,
        )
        self.assertEqual(plan["stats"]["placed"], 0)
        self.assertEqual(plan["stats"]["dropped_building"], 1)

    def test_bbox_filter(self):
        # Station far east of a tight local bbox around the origin.
        south, west = _ll(-10, -10)
        north, east = _ll(10, 10)
        plan = plan_velo(
            _layout(),
            {"stations": [_station("099", 200.0, 5.0, 24)]},
            ORIGIN,
            bbox=(south, west, north, east),
        )
        self.assertEqual(plan["stats"]["dropped_outside"], 1)
        self.assertEqual(plan["stats"]["placed"], 0)

    def test_export_viewer_coords(self):
        plan = plan_velo(_layout(), {"stations": [_station("092", 3.0, 5.0, 21)]}, ORIGIN)
        payload = export_velo_for_viewer(plan["stations"])
        self.assertEqual(len(payload["stations"]), 1)
        v = payload["stations"][0]
        self.assertAlmostEqual(v["x"], plan["stations"][0]["x"])
        self.assertAlmostEqual(v["z"], -plan["stations"][0]["y"])
        self.assertEqual(v["y"], 0.0)


if __name__ == "__main__":
    unittest.main()
