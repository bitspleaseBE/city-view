import math
import re
import unittest
from pathlib import Path

from cityview import landmark_kit as K


def _square(s=10.0, ox=0.0, oy=0.0):
    return [(ox, oy), (ox + s, oy), (ox + s, oy + s), (ox, oy + s)]


class MaterialMappingTests(unittest.TestCase):
    def test_blender_maps_every_kit_material(self):
        src = (Path(__file__).resolve().parents[1] / "blender" / "build_city.py").read_text()
        body = src.split("def make_landmark_materials", 1)[1].split("\ndef ", 1)[0]
        mapped = set(re.findall(r'^\s+"(\w+)": \(', body, re.M))
        self.assertEqual(set(K.MATERIALS) - mapped, set())


class FrameTests(unittest.TestCase):
    def test_from_edge_points_outward(self):
        f = K.Frame.from_edge((0.0, 0.0), (10.0, 0.0), (0.0, -1.0))
        self.assertAlmostEqual(f.ny, -1.0)
        x, y, z = f.p(2.0, 1.0, 3.0)
        self.assertEqual((round(x, 6), round(y, 6), z), (2.0, -1.0, 3.0))

    def test_local_inverts_p(self):
        f = K.Frame.from_edge((3.0, 4.0), (7.0, 9.0), (1.0, -1.0))
        x, y, _ = f.p(1.5, -2.25, 0.0)
        a, d = f.local(x, y)
        self.assertAlmostEqual(a, 1.5)
        self.assertAlmostEqual(d, -2.25)


class PolygonTests(unittest.TestCase):
    def test_ring_edges_outward_for_both_windings(self):
        for ring in (_square(), list(reversed(_square()))):
            for e in K.ring_edges(ring):
                mx, my = e.mid
                self.assertFalse(K.point_in_ring(mx + e.outward[0] * 0.1, my + e.outward[1] * 0.1, ring))

    def test_merged_edges_join_collinear_runs(self):
        ring = [(0, 0), (5, 0.05), (10, 0), (10, 10), (0, 10)]
        self.assertEqual(len(K.merged_edges(ring)), 4)

    def test_front_edge_nearest_anchor(self):
        e = K.front_edge(_square(), (5.0, -1.0))
        self.assertAlmostEqual(e.mid[1], 0.0)

    def test_offset_ring_inward_for_ccw(self):
        inner = K.offset_ring(_square(), 1.0)
        self.assertAlmostEqual(abs(K.signed_area(inner)), 64.0, places=4)

    def test_clip_halfplane(self):
        left, right = K.split_ring(_square(), (4.0, 0.0), (1.0, 0.0))
        self.assertAlmostEqual(abs(K.signed_area(left)), 40.0)
        self.assertAlmostEqual(abs(K.signed_area(right)), 60.0)

    def test_rings_cross(self):
        bow = [(0, 0), (10, 10), (10, 0), (0, 10)]
        self.assertTrue(K.rings_cross(bow))
        self.assertFalse(K.rings_cross(_square()))


class OutlineTests(unittest.TestCase):
    def test_round_arch_top(self):
        o = K.opening(0.0, 1.0, 2.0, 3.0, "round")
        self.assertAlmostEqual(K.opening_top(o), 4.0)

    def test_pointed_arch_is_symmetric(self):
        pts = K.arch_points(0.0, 0.0, 1.0, "pointed", 8)
        for (x0, z0), (x1, z1) in zip(pts, reversed(pts)):
            self.assertAlmostEqual(x0, -x1)
            self.assertAlmostEqual(z0, z1)
        self.assertAlmostEqual(max(z for _, z in pts), 1.6)

    def test_opening_has_no_duplicate_points(self):
        o = K.opening(0.0, 2.0, 4.0, 2.0, "round", 8)
        for a, b in zip(o, o[1:] + o[:1]):
            self.assertGreater(math.dist(a, b), 1e-6)


class MeshTests(unittest.TestCase):
    def test_unknown_material_rejected(self):
        with self.assertRaises(ValueError):
            K.Mesh().face([(0, 0, 0), (1, 0, 0), (0, 1, 0)], "chrome")

    def test_box_faces_point_outward(self):
        m = K.Mesh()
        K.wbox(m, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 0.3, "brick")
        self.assertEqual(len(m.faces), 6)
        for face in m.faces:
            pts = [m.verts[i] for i in face]
            n = K.newell_normal(pts)
            c = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
            self.assertGreater(n[0] * c[0] + n[1] * c[1] + n[2] * (c[2] - 1.0), 0.0)

    def test_box_skip(self):
        m = K.Mesh()
        K.rbox(m, K.Frame(0, 0, 1, 0, 0, 1), 0, 1, 0, 1, 0, 1, "stone_white", skip=("bottom", "-d"))
        self.assertEqual(len(m.faces), 4)

    def test_cell_tiles_panel_around_hole(self):
        m = K.Mesh()
        f = K.Frame(0, 0, 1, 0, 0, -1)
        hole = K.opening(1.0, 0.5, 1.0, 1.5, "round", 6)
        K.cell(m, f, 0.0, 2.0, 0.0, 3.0, hole, 0.0, -0.3, "brick", "brick_dark")
        wall = 0.0
        for face, mat in zip(m.faces, m.mats):
            if mat == "brick":
                pts = [(m.verts[i][0], m.verts[i][2]) for i in face]
                wall += abs(K.signed_area(pts))
        hole_area = abs(K.signed_area(hole))
        self.assertAlmostEqual(wall + hole_area, 6.0, places=3)
        self.assertIn("brick_dark", m.mats)

    def test_extrude_ring_with_hole_and_skip(self):
        m = K.Mesh()
        hole = _square(4.0, 3.0, 3.0)
        K.extrude_ring(m, _square(), [hole], 0.0, 5.0, "brick", "slate", skip=lambda e: e.mid[1] < 0.1)
        self.assertEqual(len(m.faces), 3 + 4)
        self.assertEqual(len(m.caps), 1)
        self.assertEqual(len(m.caps[0].holes), 1)

    def test_ring_roof_rises_and_falls_back(self):
        m = K.Mesh()
        used = K.ring_roof(m, _square(20.0), [_square(6.0, 7.0, 7.0)], 10.0, 1.0, 1.5, "slate")
        self.assertAlmostEqual(used, 1.5)
        self.assertAlmostEqual(m.bounds()[1][2], 11.0)
        tiny = K.Mesh()
        self.assertEqual(K.ring_roof(tiny, _square(2.0), [], 5.0, 1.0, 3.0, "slate"), 0.0)


if __name__ == "__main__":
    unittest.main()
