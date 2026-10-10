import math
import unittest

from cityview.streetscape import (
    _WALK_INDOOR_MARGIN,
    _WALK_MIN_KEEP_M,
    _offset_polyline,
    _point_segment_dist,
    export_buildings_near_spawn,
    export_roads_near_spawn,
    export_walks_near_spawn,
    floors_from_height,
    footprint_supports_prism_roof,
    height_truth,
    nearest_road_pose,
    parse_maxspeed_kmh,
    point_in_ring,
    road_speed_kmh,
    roof_shape_for,
    safe_roof_shape,
    street_facing_edges,
)


class HeightTruthTests(unittest.TestCase):
    def test_levels(self):
        eaves, roof_h, floors = height_truth({"building:levels": "4"})
        self.assertEqual(floors, 4)
        self.assertAlmostEqual(eaves, 12.6, places=1)

    def test_roof_shape_tagged(self):
        self.assertEqual(
            roof_shape_for({"roof:shape": "gabled"}, "eclectic", 1),
            "gable",
        )

    def test_floors_from_height(self):
        self.assertEqual(floors_from_height(12.6), 4)

    def test_prism_ok_on_rectangle(self):
        ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 6.0], [0.0, 6.0]]
        self.assertTrue(footprint_supports_prism_roof(ring))
        self.assertEqual(safe_roof_shape("gable", ring), "gable")

    def test_prism_rejects_l_shape(self):
        # Classic L footprint — OBB gable would overhang the missing corner.
        ring = [
            [0.0, 0.0],
            [12.0, 0.0],
            [12.0, 4.0],
            [4.0, 4.0],
            [4.0, 10.0],
            [0.0, 10.0],
        ]
        self.assertFalse(footprint_supports_prism_roof(ring))
        self.assertEqual(safe_roof_shape("gable", ring), "mansard")
        self.assertEqual(safe_roof_shape("hip", ring), "mansard")
        self.assertEqual(safe_roof_shape("flat", ring), "flat")


class StreetEdgeTests(unittest.TestCase):
    def test_edge_faces_road(self):
        # Unit square building; road south of it.
        ring = [[0.0, 0.0], [6.0, 0.0], [6.0, 8.0], [0.0, 8.0]]
        segments = [(-2.0, -3.0, 8.0, -3.0, 6.0)]
        edges = street_facing_edges(ring, segments)
        self.assertTrue(edges)
        # Bottom edge (y=0) should be included.
        self.assertTrue(any(e["i0"] == 0 for e in edges))

    def test_spawn_snaps_to_road(self):
        roads = [{"points": [[0.0, 0.0], [20.0, 0.0]], "width": 6.0}]
        sx, sy, yaw = nearest_road_pose(10.0, 4.0, roads)
        self.assertAlmostEqual(sy, 0.0, places=3)
        self.assertAlmostEqual(sx, 10.0, places=3)
        self.assertAlmostEqual(yaw, 0.0, places=3)


class RoadsExportTests(unittest.TestCase):
    def test_exports_driveable_near_spawn(self):
        layout = {
            "roads": [
                {
                    "id": 1,
                    "kind": "residential",
                    "width": 6.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
                {
                    "id": 2,
                    "kind": "footway",
                    "width": 2.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
                {
                    "id": 3,
                    "kind": "secondary",
                    "width": 8.0,
                    "points": [[500.0, 500.0], [520.0, 500.0]],
                },
                {
                    "id": 99,
                    "kind": "tram",
                    "width": 3.0,
                    "points": [[0.0, 0.0], [40.0, 0.0]],
                },
            ],
            "transit_lines": [
                {
                    "id": 99,
                    "mode": "tram",
                    "points": [[0.0, 1.0], [40.0, 1.0]],
                }
            ],
            "signals": [
                {"id": 10, "x": 20.0, "y": 0.0, "kind": "traffic_signals"},
                {"id": 11, "x": 22.0, "y": 1.0, "kind": "traffic_signals"},
            ],
        }
        payload = export_roads_near_spawn(
            layout, {"x": 5.0, "y": 0.0}, radius=100.0, max_roads=10
        )
        self.assertEqual(len(payload["roads"]), 1)
        self.assertEqual(payload["roads"][0]["id"], 1)
        self.assertNotIn(99, [r["id"] for r in payload["roads"]])
        self.assertEqual(payload["cycleSeconds"], 30)
        # Clustered OSM nodes → stop-line approaches, not raw centre spam.
        self.assertGreaterEqual(len(payload["signals"]), 1)
        self.assertIn("stopX", payload["signals"][0])
        self.assertIn("yaw", payload["signals"][0])
        self.assertIn("pedYaw", payload["signals"][0])


class BuildingExportTests(unittest.TestCase):
    def test_export_buildings_near_spawn(self):
        ring_near = [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
        ring_far = [[500.0, 500.0], [510.0, 500.0], [510.0, 510.0], [500.0, 510.0]]
        layout = {
            "buildings": [
                {"id": 1, "ring": ring_near},
                {"id": 2, "ring": ring_far},
                {"id": 3, "ring": [[1.0, 1.0]]},  # too few verts
            ]
        }
        payload = export_buildings_near_spawn(
            layout, {"x": 5.0, "y": 4.0}, radius=100.0, max_buildings=10
        )
        self.assertEqual(len(payload["buildings"]), 1)
        self.assertEqual(payload["buildings"][0]["id"], 1)
        self.assertTrue(point_in_ring(5.0, 4.0, payload["buildings"][0]["ring"]))
        self.assertFalse(point_in_ring(20.0, 20.0, payload["buildings"][0]["ring"]))


class MaxspeedTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "30"}), 30.0)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "50 km/h"}), 50.0)
        self.assertAlmostEqual(parse_maxspeed_kmh({"maxspeed": "20 mph"}), 32.2, places=1)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "BE-VLG:urban"}), 50.0)
        self.assertEqual(parse_maxspeed_kmh({"maxspeed": "30;50"}), 30.0)
        self.assertIsNone(parse_maxspeed_kmh({"maxspeed": "none"}))
        self.assertIsNone(parse_maxspeed_kmh({}))

    def test_defaults_and_export(self):
        self.assertEqual(road_speed_kmh("residential", None), 30.0)
        self.assertEqual(road_speed_kmh("secondary", None), 50.0)
        self.assertEqual(road_speed_kmh("secondary", 30.0), 30.0)
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0,
                 "points": [[0.0, 0.0], [40.0, 0.0]], "maxspeed_kmh": 20.0},
                {"id": 2, "kind": "secondary", "width": 8.0,
                 "points": [[40.0, 0.0], [90.0, 0.0]]},
            ],
            "signals": [],
        }
        payload = export_roads_near_spawn(layout, {"x": 0.0, "y": 0.0}, radius=200.0)
        by_id = {r["id"]: r for r in payload["roads"]}
        self.assertEqual(by_id[1]["maxspeedKmh"], 20.0)
        self.assertEqual(by_id[1]["speedKmh"], 20.0)
        self.assertIsNone(by_id[2]["maxspeedKmh"])
        self.assertEqual(by_id[2]["speedKmh"], 50.0)
        self.assertIn("walks", payload)


class WalkExportTests(unittest.TestCase):
    def test_offset_is_perpendicular(self):
        left = _offset_polyline([[0.0, 0.0], [10.0, 0.0]], 2.0)
        self.assertAlmostEqual(left[0][1], 2.0, places=5)
        self.assertAlmostEqual(left[1][1], 2.0, places=5)

    def test_exports_sidewalks_not_carriageway_centres(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                {"id": 2, "kind": "footway", "width": 2.0, "points": [[0.0, 5.0], [40.0, 5.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        kinds = {w["kind"] for w in walks}
        self.assertIn("footway", kinds)
        self.assertIn("sidewalk", kinds)
        sw = [w for w in walks if w["kind"] == "sidewalk"]
        self.assertTrue(any(abs(w["points"][0][1]) > 2.5 for w in sw))

    def test_living_street_uses_sidewalks_not_centreline(self):
        layout = {
            "roads": [
                {"id": 9, "kind": "living_street", "width": 5.0, "points": [[0.0, 0.0], [50.0, 0.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 25.0, "y": 0.0}, radius=80.0)
        self.assertTrue(walks)
        self.assertTrue(all(w["kind"] == "sidewalk" for w in walks))
        self.assertTrue(all(abs(w["points"][0][1]) > 2.0 for w in walks))

    def test_crossing_links_opposite_kerbs(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 8.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
            ],
            "crossings": [{"id": 99, "x": 20.0, "y": 0.0, "kind": "uncontrolled"}],
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        crosses = [w for w in walks if w["kind"] == "crossing"]
        self.assertEqual(len(crosses), 1)
        self.assertFalse(crosses[0]["safe"])
        y0, y1 = crosses[0]["points"][0][1], crosses[0]["points"][1][1]
        self.assertGreater(abs(y0 - y1), 6.0)

    def test_skips_building_passage_footways(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                {
                    "id": 2,
                    "kind": "footway",
                    "width": 2.0,
                    "passage": True,
                    "points": [[10.0, 0.0], [10.0, 20.0]],
                },
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        self.assertFalse(any(w["id"].startswith("w2") for w in walks))

    def test_skips_courtyard_paths_far_from_streets(self):
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
                # Deep yard path, well clear of the street.
                {"id": 3, "kind": "footway", "width": 2.0, "points": [[10.0, 40.0], [30.0, 40.0]]},
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=80.0)
        self.assertFalse(any(w["id"].startswith("w3") for w in walks))
        self.assertTrue(any(w["kind"] == "sidewalk" for w in walks))

    def test_skips_sidewalk_ribbons_through_buildings(self):
        # Street along y=0; building covers the north kerb so the L ribbon is indoors.
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [40.0, 0.0]]},
            ],
            "buildings": [
                {"id": 9, "ring": [[0.0, 2.0], [40.0, 2.0], [40.0, 12.0], [0.0, 12.0]]},
            ],
        }
        walks = export_walks_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=50.0)
        sides = {w.get("side") for w in walks if w["kind"] == "sidewalk"}
        self.assertIn("R", sides)
        self.assertNotIn("L", sides)

    def test_dual_carriageway_outer_kerb_only(self):
        # RH-traffic boulevard: eastbound south half + westbound north half.
        # Outer kerbs only — not the median between the halves.
        layout = {
            "roads": [
                {
                    "id": 10,
                    "name": "Boulevard",
                    "kind": "secondary",
                    "width": 8.0,
                    "oneway": 1,
                    "points": [[0.0, -4.0], [80.0, -4.0]],
                },
                {
                    "id": 11,
                    "name": "Boulevard",
                    "kind": "secondary",
                    "width": 8.0,
                    "oneway": 1,
                    "points": [[80.0, 4.0], [0.0, 4.0]],
                },
            ]
        }
        walks = export_walks_near_spawn(layout, {"x": 40.0, "y": 0.0}, radius=100.0)
        by_host: dict[str, set[str]] = {}
        for w in walks:
            if w["kind"] != "sidewalk":
                continue
            host = w["id"].split("_")[0].removeprefix("sw")
            by_host.setdefault(host, set()).add(w.get("side") or "")
        self.assertEqual(by_host.get("10"), {"R"})
        self.assertEqual(by_host.get("11"), {"R"})
        # Outer ribbons sit outside the ±4 m carriageway centres.
        for w in walks:
            if w["kind"] != "sidewalk":
                continue
            ys = [p[1] for p in w["points"]]
            if w.get("side") == "R" and "sw10" in w["id"]:
                self.assertTrue(all(y < -6.0 for y in ys), ys)
            if w.get("side") == "R" and "sw11" in w["id"]:
                self.assertTrue(all(y > 6.0 for y in ys), ys)


def _ring_clearance(x: float, y: float, rings: list[list[list[float]]]) -> float:
    """Distance to the nearest ring edge; negative when (x, y) is inside a ring."""
    best = float("inf")
    for ring in rings:
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            best = min(best, _point_segment_dist(x, y, a[0], a[1], b[0], b[1]))
        if point_in_ring(x, y, ring):
            return -best
    return best


def _assert_walks_outdoors(test: unittest.TestCase, walks, rings) -> None:
    """Every vertex and every ~1 m sample along each walk clears all rings by the margin."""
    for w in walks:
        pts = w["points"]
        for i, (x, y) in enumerate(pts):
            test.assertGreaterEqual(_ring_clearance(x, y, rings), _WALK_INDOOR_MARGIN, (w["id"], x, y))
            if i + 1 < len(pts):
                x2, y2 = pts[i + 1]
                n = max(1, int(math.hypot(x2 - x, y2 - y)))
                for k in range(1, n):
                    t = k / n
                    sx, sy = x + (x2 - x) * t, y + (y2 - y) * t
                    test.assertGreaterEqual(
                        _ring_clearance(sx, sy, rings), _WALK_INDOOR_MARGIN, (w["id"], sx, sy)
                    )


def _alley_layout(clear: float, *, kind: str = "living_street", **road_extra) -> dict:
    """E-W alley along y=0 between two building rows leaving ``clear`` metres of gap."""
    h = clear / 2.0
    road = {"id": 7, "kind": kind, "width": 5.0, "points": [[0.0, 0.0], [60.0, 0.0]]}
    road.update(road_extra)
    return {
        "roads": [road],
        "buildings": [
            {"id": 1, "ring": [[-5.0, h], [65.0, h], [65.0, h + 10.0], [-5.0, h + 10.0]]},
            {"id": 2, "ring": [[-5.0, -h - 10.0], [65.0, -h - 10.0], [65.0, -h], [-5.0, -h]]},
        ],
    }


class AlleyWalkTests(unittest.TestCase):
    SPAWN = {"x": 30.0, "y": 0.0}

    def _rings(self, layout):
        return [b["ring"] for b in layout["buildings"]]

    def test_alley_sidewalks_clamped_inside_clear_width(self):
        layout = _alley_layout(3.8)  # clear half-width 1.9 → offset 1.4 (nominal would be 3.5)
        walks = export_walks_near_spawn(layout, self.SPAWN, radius=80.0)
        self.assertTrue(walks)
        _assert_walks_outdoors(self, walks, self._rings(layout))
        for w in walks:
            self.assertEqual(w["kind"], "sidewalk")
            for _x, y in w["points"]:
                self.assertLessEqual(abs(y), 1.4 + 1e-6)
                self.assertGreaterEqual(abs(y), 1.2)
        self.assertEqual({w["side"] for w in walks}, {"L", "R"})
        payload = export_roads_near_spawn(layout, self.SPAWN, radius=100.0)
        road = payload["roads"][0]
        self.assertIs(road["carFree"], True)
        _assert_walks_outdoors(self, payload["walks"], self._rings(layout))

    def test_alley_too_tight_for_sidewalks_uses_centreline(self):
        layout = _alley_layout(3.0)  # clear half-width 1.5 → 1.0 < 1.2: both sides skipped
        walks = export_walks_near_spawn(layout, self.SPAWN, radius=80.0)
        self.assertEqual(len(walks), 1)
        w = walks[0]
        self.assertIn(w["kind"], ("pedestrian", "sidewalk"))
        self.assertTrue(w["safe"])
        self.assertTrue(all(abs(y) < 1e-6 for _x, y in w["points"]))
        _assert_walks_outdoors(self, walks, self._rings(layout))
        road = export_roads_near_spawn(layout, self.SPAWN, radius=100.0)["roads"][0]
        self.assertIs(road["carFree"], True)

    def test_non_living_street_has_no_centreline_fallback(self):
        layout = _alley_layout(3.0, kind="residential")
        walks = export_walks_near_spawn(layout, self.SPAWN, radius=80.0)
        self.assertEqual(walks, [])

    def test_ribbon_split_at_indoor_samples_and_short_runs_dropped(self):
        # Street y=0 (half 3 → kerb offset 4). A block juts out at x 20..22 across the
        # north kerb; the R (south) kerb is clear. Pieces either side of the block are
        # long enough to keep; none may touch the block (± margin).
        block = [[20.0, 2.0], [22.0, 2.0], [22.0, 8.0], [20.0, 8.0]]
        layout = {
            "roads": [{"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [60.0, 0.0]]}],
            "buildings": [{"id": 5, "ring": block}],
        }
        walks = export_walks_near_spawn(layout, {"x": 30.0, "y": 0.0}, radius=80.0)
        left = [w for w in walks if w.get("side") == "L"]
        self.assertEqual(len(left), 2)
        _assert_walks_outdoors(self, walks, [block])
        for w in walks:
            self.assertGreaterEqual(
                sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(w["points"], w["points"][1:])),
                _WALK_MIN_KEEP_M,
            )
        # A narrow gap leaves only a short stub between two blocks → dropped.
        layout["buildings"] = [
            {"id": 5, "ring": block},
            {"id": 6, "ring": [[30.0, 2.0], [32.0, 2.0], [32.0, 8.0], [30.0, 8.0]]},
        ]
        walks = export_walks_near_spawn(layout, {"x": 30.0, "y": 0.0}, radius=80.0)
        self.assertEqual(len([w for w in walks if w.get("side") == "L"]), 2)

    def test_any_indoor_sample_rejects_footway(self):
        # Short building cut well under 12% of a long footway still must not be walked.
        layout = {
            "roads": [
                {"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [100.0, 0.0]]},
                {"id": 2, "kind": "footway", "width": 2.0, "points": [[0.0, 6.0], [100.0, 6.0]]},
            ],
            "buildings": [{"id": 8, "ring": [[48.0, 5.0], [51.0, 5.0], [51.0, 9.0], [48.0, 9.0]]}],
        }
        walks = export_walks_near_spawn(layout, {"x": 50.0, "y": 0.0}, radius=120.0)
        foot = [w for w in walks if w["kind"] == "footway"]
        self.assertEqual(len(foot), 2)
        _assert_walks_outdoors(self, walks, [b["ring"] for b in layout["buildings"]])

    def test_wide_street_not_car_free(self):
        layout = _alley_layout(9.0, kind="residential")
        road = export_roads_near_spawn(layout, self.SPAWN, radius=100.0)["roads"][0]
        self.assertIs(road["carFree"], False)
        # Open (building-free) streets are never car-free by width.
        plain = {"roads": [{"id": 1, "kind": "living_street", "width": 5.0, "points": [[0.0, 0.0], [50.0, 0.0]]}]}
        self.assertIs(export_roads_near_spawn(plain, self.SPAWN, radius=100.0)["roads"][0]["carFree"], False)

    def test_narrow_living_street_with_open_gaps_is_car_free(self):
        # Mostly 3.5–4.0 m clear, but the south row has a gap (open side) and the rest
        # of the street is open-ended: median-with-inf would be inf, lower quartile is ~3.5.
        layout = {
            "roads": [{"id": 9, "kind": "living_street", "width": 5.0, "points": [[0.0, 0.0], [80.0, 0.0]]}],
            "buildings": [
                {"id": 1, "ring": [[0.0, 1.75], [80.0, 1.75], [80.0, 9.0], [0.0, 9.0]]},
                {"id": 2, "ring": [[0.0, -9.0], [20.0, -9.0], [20.0, -1.75], [0.0, -1.75]]},
                {"id": 3, "ring": [[20.0, -9.0], [40.0, -9.0], [40.0, -2.0], [20.0, -2.0]]},
                # open-side gap 40..80 on the south: no building
            ],
        }
        road = export_roads_near_spawn(layout, {"x": 20.0, "y": 0.0}, radius=100.0)["roads"][0]
        self.assertIs(road["carFree"], True)
        # Fewer than 2 finite both-sides samples → not car-free by width.
        sparse = {
            "roads": [{"id": 9, "kind": "living_street", "width": 5.0, "points": [[0.0, 0.0], [80.0, 0.0]]}],
            "buildings": [{"id": 1, "ring": [[0.0, 1.75], [80.0, 1.75], [80.0, 9.0], [0.0, 9.0]]}],
        }
        road = export_roads_near_spawn(sparse, {"x": 20.0, "y": 0.0}, radius=100.0)["roads"][0]
        self.assertIs(road["carFree"], False)

    def test_car_free_from_osm_tags(self):
        base = {"roads": [{"id": 1, "kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [50.0, 0.0]]}]}

        def car_free(**extra):
            layout = {"roads": [{**base["roads"][0], **extra}]}
            return export_roads_near_spawn(layout, self.SPAWN, radius=100.0)["roads"][0]["carFree"]

        self.assertIs(car_free(), False)
        self.assertIs(car_free(motor_vehicle="no"), True)
        self.assertIs(car_free(access="no", foot="designated"), True)
        self.assertIs(car_free(tags={"motor_vehicle": "no", "foot": "designated"}), True)
        self.assertIs(car_free(tags={"access": "no", "motor_vehicle": "destination"}), False)
        self.assertIs(car_free(tags={"foot": "designated"}), False)


if __name__ == "__main__":
    unittest.main()
