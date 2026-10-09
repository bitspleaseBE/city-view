"""Tests for kerb prisms and junction trimming (no bpy needed)."""

from __future__ import annotations

import unittest

from cityview import facade_kit
from cityview.kerbs import CarriagewayIndex, kerb_profile, split_at_carriageways


def _normal(verts, face):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = (verts[face[0]], verts[face[1]], verts[face[2]])
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - bx, cy - by, cz - bz
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


class KerbProfileTests(unittest.TestCase):
    def setUp(self):
        # Ribbon runs along +x; left edge is +y.
        self.pts = [[0.0, 0.0], [4.0, 0.0], [8.0, 0.0]]

    def test_top_faces_up_and_sides_face_outwards(self):
        verts, faces, uvs, kinds = kerb_profile(self.pts, 0.28, 0.04, 0.165, road_edge_is_left=True)
        self.assertEqual(sum(len(f) for f in faces), len(uvs))
        for face, kind in zip(faces, kinds):
            nx, ny, nz = _normal(verts, face)
            if kind == 0:
                self.assertGreater(nz, 0.0)
            elif kind == 1:  # road face: left edge, outward +y
                self.assertGreater(ny, 0.0)
            elif kind == 2:  # pavement face: right edge, outward -y
                self.assertLess(ny, 0.0)

    def test_road_face_flips_with_side(self):
        verts, faces, _uvs, kinds = kerb_profile(self.pts, 0.28, 0.04, 0.165, road_edge_is_left=False)
        for face, kind in zip(faces, kinds):
            _nx, ny, _nz = _normal(verts, face)
            if kind == 1:
                self.assertLess(ny, 0.0)  # road face is now the right edge

    def test_end_caps_close_the_prism(self):
        verts, faces, _uvs, kinds = kerb_profile(self.pts, 0.28, 0.04, 0.165, road_edge_is_left=True)
        caps = [f for f, k in zip(faces, kinds) if k == 3]
        self.assertEqual(len(caps), 2)
        self.assertLess(_normal(verts, caps[0])[0], 0.0)
        self.assertGreater(_normal(verts, caps[1])[0], 0.0)

    def test_reveal_height(self):
        verts, *_ = kerb_profile(self.pts, 0.28, 0.04, 0.165, road_edge_is_left=True)
        self.assertAlmostEqual(max(v[2] for v in verts) - min(v[2] for v in verts), 0.125, places=6)


class JunctionTrimTests(unittest.TestCase):
    @staticmethod
    def _roads():
        main = {"kind": "residential", "width": 7.0, "points": [[-60.0, 0.0], [60.0, 0.0]]}
        side = {"kind": "residential", "width": 6.0, "points": [[0.0, 0.0], [0.0, 60.0]]}
        return [main, side]

    def test_main_road_kerb_is_cut_across_the_side_street(self):
        roads = self._roads()
        idx = CarriagewayIndex(roads)
        kerb = [[-60.0, 3.62], [60.0, 3.62]]  # left kerb of the main road (north side)
        runs = split_at_carriageways(kerb, idx, own_road=0, margin=-0.3)
        self.assertEqual(len(runs), 2)
        self.assertLess(runs[0][-1][0], -2.0)
        self.assertGreater(runs[1][0][0], 2.0)
        self.assertLess(runs[0][-1][0], 0.0)

    def test_kerb_on_the_far_side_is_untouched(self):
        roads = self._roads()
        idx = CarriagewayIndex(roads)
        kerb = [[-60.0, -3.62], [60.0, -3.62]]
        self.assertEqual(split_at_carriageways(kerb, idx, own_road=0, margin=-0.3), [kerb])

    def test_continuing_way_does_not_cut_its_own_street(self):
        a = {"kind": "residential", "width": 7.0, "points": [[-60.0, 0.0], [0.0, 0.0]]}
        b = {"kind": "residential", "width": 7.0, "points": [[0.0, 0.0], [60.0, 0.0]]}
        idx = CarriagewayIndex([a, b])
        kerb = [[-60.0, 3.62], [0.0, 3.62]]
        self.assertEqual(split_at_carriageways(kerb, idx, own_road=0, margin=-0.3), [kerb])

    def test_footways_never_cut(self):
        roads = [
            {"kind": "residential", "width": 7.0, "points": [[-60.0, 0.0], [60.0, 0.0]]},
            {"kind": "footway", "width": 3.0, "points": [[0.0, 0.0], [0.0, 60.0]]},
        ]
        kerb = [[-60.0, 3.62], [60.0, 3.62]]
        self.assertEqual(split_at_carriageways(kerb, CarriagewayIndex(roads), 0, -0.3), [kerb])


class DoorStepTests(unittest.TestCase):
    def test_every_door_belongs_to_a_known_facade(self):
        for fid, (centre, width) in facade_kit.DOORS.items():
            self.assertIn(fid, facade_kit.FACADES)
            self.assertTrue(0.05 < centre < 0.95)
            self.assertTrue(0.05 <= width <= 0.32)  # facade_26 has a double carriage door

    def test_step_lands_on_the_door_and_follows_the_mapping(self):
        quads = facade_kit.plan_facade_quads(6.4, 12.0, 4, "red-brick", seed=3)
        steps = facade_kit.door_steps(quads)
        mirrored = facade_kit.door_steps(quads, rightwards=False)
        self.assertEqual(len(steps), len(mirrored))
        for q in quads:
            door = facade_kit.DOORS.get(q["cell"])
            if not door:
                continue
            s = facade_kit.door_steps([q])[0]
            m = facade_kit.door_steps([q], rightwards=False)[0]
            span = q["a1"] - q["a0"]
            self.assertAlmostEqual(s["a"] - q["a0"], door[0] * span, places=3)
            self.assertAlmostEqual((s["a"] - q["a0"]) + (m["a"] - q["a0"]), span, places=3)
            self.assertAlmostEqual(s["w"], door[1] * span, places=3)

    def test_cropped_out_door_gets_no_step(self):
        # Only a narrow slice is visible and the door is outside it.
        fid = "facade_26"
        u0, v0, u1, v1 = facade_kit.cell_uv_rect(fid)
        quad = {"cell": fid, "a0": 0.0, "a1": 3.0, "uv": (u0 + 0.6 * (u1 - u0), v0, u1, v1)}
        self.assertEqual(facade_kit.door_steps([quad]), [])


if __name__ == "__main__":
    unittest.main()
