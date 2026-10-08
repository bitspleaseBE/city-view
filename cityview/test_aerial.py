import json
import unittest

from cityview import aerial as A
from cityview import surface_kit as kit


class AerialHelpersTests(unittest.TestCase):
    def test_pixel_mapping_corners(self):
        size = (1000, 1000)
        south, west, north, east = A.BBOX
        self.assertEqual(A.latlon_to_pixel(north, west, size), (0.0, 0.0))
        c, r = A.latlon_to_pixel(south, east, size)
        self.assertAlmostEqual(c, 1000.0)
        self.assertAlmostEqual(r, 1000.0)

    def test_origin_maps_inside_image(self):
        c, r = A.local_to_pixel(0.0, 0.0, (2240, 2240))
        self.assertTrue(0 < c < 2240 and 0 < r < 2240)
        # north is up: a point 100 m north of the origin has a smaller row.
        self.assertLess(A.local_to_pixel(0.0, 100.0, (2240, 2240))[1], r)
        self.assertGreater(A.local_to_pixel(100.0, 0.0, (2240, 2240))[0], c)

    def test_classify_roof(self):
        self.assertEqual(A.classify_roof((0.3, 0.3, 0.32), "flat"), "roof_flat")
        self.assertEqual(A.classify_roof((0.3, 0.3, 0.32), "mansard"), "roof_slate")
        self.assertEqual(A.classify_roof((0.7, 0.7, 0.72), "gable"), "roof_zinc")
        self.assertEqual(A.classify_roof((0.3, 0.3, 0.32), "gable", warm_frac=0.2), "roof_clay")

    def test_vegetation_detected(self):
        self.assertTrue(A.is_vegetation((0.2, 0.4, 0.2)))
        self.assertFalse(A.is_vegetation((0.5, 0.5, 0.52)))

    def test_reduce_sky_cast_shrinks_blue_shade_but_keeps_warm(self):
        shade = (0.16, 0.24, 0.36)
        out = A.reduce_sky_cast(shade)
        self.assertLess(out[2] - out[0], (shade[2] - shade[0]) * 0.6)
        self.assertAlmostEqual(A.luma(out), A.luma(shade), places=2)
        self.assertEqual(A.reduce_sky_cast((0.6, 0.4, 0.3)), [0.6, 0.4, 0.3])

    def test_kmeans_separates_two_colours(self):
        pts = [[0.1, 0.1, 0.1]] * 5 + [[0.9, 0.9, 0.9]] * 5
        centres, assign = A.kmeans(pts, 2)
        self.assertEqual(len(centres), 2)
        self.assertEqual(len(set(assign[:5])), 1)
        self.assertNotEqual(assign[0], assign[-1])

    def test_tint_never_exceeds_gltf_factor_limit(self):
        for t in A.tint_for((1.0, 0.9, 0.8), (0.1, 0.1, 0.1)):
            self.assertLessEqual(t, 1.0)
            self.assertGreater(t, 0.0)

    def test_tint_reproduces_target_in_linear_light(self):
        tint = A.tint_for((0.5, 0.5, 0.5), (0.6, 0.6, 0.6), gain=1.0)
        self.assertAlmostEqual(tint[0] * 0.6, A.srgb_to_linear(0.5), places=3)


class CommittedRoofDataTests(unittest.TestCase):
    def setUp(self):
        self.doc = kit.load_roof_aerial()

    def test_committed_json_is_consistent(self):
        self.assertIsNotNone(self.doc, "run `python -m cityview.aerial sample`")
        self.assertEqual(self.doc["classes"], list(A.ROOF_CLASSES))
        for key, fam in self.doc["families"].items():
            self.assertIn(key, kit.SURFACES)
            for c in fam["clusters"]:
                self.assertTrue(all(0.0 < v <= 1.0 for v in c["tint"]), c)
        for bid, (cls, cl) in self.doc["buildings"].items():
            key = self.doc["classes"][cls]
            self.assertLess(cl, len(self.doc["families"][key]["clusters"]))

    def test_roof_mix_matches_measured_mix(self):
        for shape in ("mansard", "gable"):
            measured = self.doc["mix_by_shape"][shape]
            table = dict(kit.ROOF_MIX[shape])
            for key, frac in measured.items():
                self.assertAlmostEqual(table.get(key, 0) / 100.0, frac, delta=0.04, msg=f"{shape}/{key}")

    def test_roof_choice_respects_shape(self):
        bid = next(b for b, (cls, _) in self.doc["buildings"].items() if self.doc["classes"][cls] == "roof_flat")
        self.assertIsNotNone(kit.roof_choice(self.doc, bid, "flat"))
        self.assertIsNone(kit.roof_choice(self.doc, bid, "gable"))
        self.assertIsNone(kit.roof_choice(self.doc, "999999999999", "flat"))
        self.assertIsNone(kit.roof_choice(None, bid, "flat"))

    def test_pick_roof_cluster_in_range_and_deterministic(self):
        for key, fam in self.doc["families"].items():
            i = kit.pick_roof_cluster(self.doc, key, 17)
            self.assertEqual(i, kit.pick_roof_cluster(self.doc, key, 17))
            self.assertLess(i, len(fam["clusters"]))


if __name__ == "__main__":
    unittest.main()
