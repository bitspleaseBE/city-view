import unittest

from cityview import facade_kit as kit
from cityview import facade_windows as fw


class ClassifyBoxesTests(unittest.TestCase):
    def test_tall_glass_is_a_window_and_wide_low_glazing_a_shop(self):
        window = (0.30, 0.42, 0.55, 0.68, 0.9)
        shop = (0.10, 0.60, 0.08, 0.40, 0.9)
        windows, shops = fw.classify_boxes([window, shop], None, (6.0, 13.0))
        self.assertEqual(windows, [[0.3, 0.42, 0.55, 0.68]])
        self.assertEqual(shops, [[0.1, 0.6, 0.08, 0.4]])

    def test_door_and_ground_hugging_blobs_are_dropped(self):
        door_blob = (0.45, 0.58, 0.05, 0.30, 0.95)
        ground_blob = (0.2, 0.3, 0.01, 0.12, 0.95)
        windows, shops = fw.classify_boxes([door_blob, ground_blob], (0.5, 0.14), (6.0, 13.0))
        self.assertEqual((windows, shops), ([], []))

    def test_ragged_blobs_are_not_windows(self):
        windows, _ = fw.classify_boxes([(0.3, 0.42, 0.55, 0.68, 0.4)], None, (6.0, 13.0))
        self.assertEqual(windows, [])


class WindowLayoutTests(unittest.TestCase):
    def test_json_covers_every_facade_with_sane_fractions(self):
        doc = kit.window_layout()
        self.assertEqual(set(doc), set(kit.FACADES))
        total = 0
        for entry in doc.values():
            for key in ("windows", "shops"):
                for x0, x1, z0, z1 in entry[key]:
                    self.assertTrue(0.0 <= x0 < x1 <= 1.0 and 0.0 <= z0 < z1 <= 1.0)
            total += len(entry["windows"])
        self.assertGreater(total, 80)

    def test_reveals_stay_on_the_edge_and_below_the_eaves(self):
        quads = kit.plan_facade_quads(40.0, 13.0, 4, "neoclassical", seed=3)
        for rightwards in (True, False):
            reveals = kit.window_reveals(quads, rightwards=rightwards)
            self.assertTrue(reveals)
            for r in reveals:
                self.assertTrue(0.0 <= r["a"] - r["w"] / 2 and r["a"] + r["w"] / 2 <= 40.0 + 1e-6)
                self.assertTrue(0.0 < r["z0"] < r["z1"] <= 13.0)

    def test_cropped_windows_are_skipped_on_narrow_edges(self):
        narrow = kit.plan_facade_quads(3.6, 13.0, 4, "neoclassical", seed=1)
        for r in kit.window_reveals(narrow):
            self.assertTrue(0.0 <= r["a"] - r["w"] / 2 and r["a"] + r["w"] / 2 <= 3.6 + 1e-6)

    def test_detected_shop_glazing_gets_an_awning(self):
        doc = kit.window_layout()
        cell = next(f for f, e in doc.items() if e["shops"] and f not in kit.SHOPS)
        quad = {
            "a0": 0.0, "a1": 6.4, "z0": 0.0, "z1": 13.0, "cell": cell,
            "uv": kit.cell_uv_rect(cell), "flip": False,
        }
        awnings = kit.shop_awnings([quad])
        self.assertTrue(awnings)
        self.assertGreater(awnings[0]["z"], 0.5)


if __name__ == "__main__":
    unittest.main()
