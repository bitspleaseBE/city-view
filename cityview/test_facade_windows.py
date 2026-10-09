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


class LayeredDetectionTests(unittest.TestCase):
    def test_overlap_is_relative_to_the_smaller_box(self):
        self.assertEqual(fw.box_overlap((0, 0, 10, 10), (20, 0, 30, 10)), 0.0)
        self.assertAlmostEqual(fw.box_overlap((0, 0, 10, 10), (5, 0, 15, 10)), 0.5)
        self.assertEqual(fw.box_overlap((0, 0, 100, 100), (10, 10, 20, 20)), 1.0)

    def test_grow_and_inset_round_trip_roughly(self):
        glass = (100, 100, 140, 160)
        frame = fw.grow_box(glass, *fw.FRAME_PAD)
        self.assertTrue(frame[0] < glass[0] and frame[3] > glass[3])
        back = fw.inset_box(frame, *fw.GLASS_INSET)
        self.assertLessEqual(abs(back[0] - glass[0]), 3)
        self.assertLessEqual(abs(back[3] - glass[3]), 4)

    def test_pick_nested_prefers_two_children_over_a_merged_parent(self):
        parent = (0.3, (0, 0, 60, 30))
        kid_a = (0.7, (2, 2, 25, 28))
        kid_b = (0.7, (35, 2, 58, 28))
        self.assertEqual(sorted(fw.pick_nested([parent, kid_a, kid_b])), [kid_a[1], kid_b[1]])

    def test_pick_nested_keeps_a_parent_with_a_single_child(self):
        parent = (0.3, (0, 0, 30, 40))
        kid = (0.7, (3, 3, 27, 37))
        self.assertEqual(fw.pick_nested([parent, kid]), [parent[1]])

    def test_merge_new_skips_collisions_and_respects_the_limit(self):
        have = [(0, 0, 10, 20)]
        extra = [(1, 1, 9, 19), (30, 0, 40, 20), (31, 1, 39, 19), (60, 0, 70, 20)]
        self.assertEqual(fw.merge_new(have, extra), [(30, 0, 40, 20), (60, 0, 70, 20)])
        self.assertEqual(fw.merge_new(have, extra, limit=1), [(30, 0, 40, 20)])
