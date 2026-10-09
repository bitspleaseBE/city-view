import json
import math
import unittest
from pathlib import Path

from cityview import landmark_kit as K
from cityview import landmark_models as LM

FIXTURE = json.loads((Path(__file__).parent / "testdata" / "landmark_footprints.json").read_text())
BY_KIND = {b["landmark"]["custom"]: b for b in FIXTURE["buildings"]}


def _built(kind):
    return LM.build_landmark(BY_KIND[kind])


class BuilderTests(unittest.TestCase):
    def test_every_manifest_builder_has_a_fixture(self):
        self.assertEqual(set(BY_KIND), set(LM.BUILDERS))

    def test_budgets_materials_and_ground(self):
        for kind in LM.BUILDERS:
            with self.subTest(kind=kind):
                m = _built(kind)
                self.assertLessEqual(m.tri_count(), LM.TRI_BUDGET[kind])
                self.assertGreater(m.tri_count(), 300)
                self.assertTrue(m.materials_used() <= K.MATERIALS)
                lo, _hi = m.bounds()
                self.assertGreaterEqual(lo[2], -0.01)
                for face in m.faces:
                    self.assertGreaterEqual(len(face), 3)

    def test_stays_on_its_footprint(self):
        for kind, bldg in BY_KIND.items():
            with self.subTest(kind=kind):
                m = _built(kind)
                xs = [p[0] for p in bldg["ring"]]
                ys = [p[1] for p in bldg["ring"]]
                lo, hi = m.bounds()
                self.assertGreater(lo[0], min(xs) - 6.0)
                self.assertLess(hi[0], max(xs) + 6.0)
                self.assertGreater(lo[1], min(ys) - 6.0)
                self.assertLess(hi[1], max(ys) + 6.0)

    def test_heights_match_survey(self):
        tops = {kind: _built(kind).bounds()[1][2] for kind in LM.BUILDERS}
        self.assertGreater(tops["zas_vincentius"], 33.0)  # bell-turret spire
        self.assertTrue(14.5 < tops["feestzaal_harmonie"] < 16.5)  # central gable ~15 m + crown
        self.assertTrue(17.0 <= tops["art_deco_ms123"] < 19.0)
        self.assertTrue(15.0 < tops["gulden_spoor"] < 18.5)  # steep slate roof + stair-tower spire
        self.assertTrue(10.0 < tops["gulden_spoor_gate"] < 16.0)
        self.assertTrue(8.0 < tops["albertpark_kiosk"] < 10.5)  # lyre finial

    def test_zas_keeps_courtyards_open(self):
        m = _built("zas_vincentius")
        holes = BY_KIND["zas_vincentius"]["holes"]
        self.assertEqual(len(holes), 6)
        self.assertTrue(all(len(c.holes) == 6 for c in m.caps))

    def test_no_photo_materials(self):
        for kind in LM.BUILDERS:
            self.assertFalse(any("photo" in mat for mat in _built(kind).materials_used()))

    def test_harmonie_entrance_on_mechelsesteenweg(self):
        bldg = BY_KIND["feestzaal_harmonie"]
        ex, ey = bldg["landmark"]["params"]["entrance_xy"]
        m = _built("feestzaal_harmonie")
        near = [v for v in m.verts if math.hypot(v[0] - ex, v[1] - ey) < 4.0 and v[2] > 8.0]
        self.assertTrue(near, "entrance pavilion pediment should stand at the surveyed door")

    def test_kiosk_stairs_face_path(self):
        bldg = BY_KIND["albertpark_kiosk"]
        tx, ty = bldg["landmark"]["params"]["stairs_toward_xy"]
        m = _built("albertpark_kiosk")
        low = [v for v in m.verts if v[2] < 0.3 and v[2] >= 0.0]
        far = max(low, key=lambda v: -math.hypot(v[0] - tx, v[1] - ty))
        cx, cy = K.centroid([tuple(p) for p in bldg["ring"]])
        self.assertGreater(math.hypot(far[0] - cx, far[1] - cy), 6.5)  # steps project past the podium

    def test_benoit_node(self):
        node = FIXTURE["nodes"][0]
        m = LM.build_node_landmark(node)
        self.assertLessEqual(m.tri_count(), LM.TRI_BUDGET["benoit_monument"])
        self.assertIn("water", m.materials_used())
        lo, hi = m.bounds()
        self.assertLess(math.hypot((lo[0] + hi[0]) / 2 - node["x"], (lo[1] + hi[1]) / 2 - node["y"]), 4.0)

    def test_unknown_kinds_return_none(self):
        self.assertIsNone(LM.build_landmark({"ring": [], "landmark": {"custom": "nope"}}))
        self.assertIsNone(LM.build_node_landmark({"custom": "nope"}))


if __name__ == "__main__":
    unittest.main()
