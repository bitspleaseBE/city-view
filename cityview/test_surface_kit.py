import unittest
from collections import Counter

from cityview import surface_kit as kit
from cityview.paths import ASSETS


class SurfaceKitTests(unittest.TestCase):
    def test_roof_mix_weights_sum_to_100_and_reference_known_surfaces(self):
        for shape, mix in kit.ROOF_MIX.items():
            self.assertEqual(sum(w for _, w in mix), 100, shape)
            for key, _ in mix:
                self.assertIn(key, kit.SURFACES)

    def test_pick_roof_surface_is_deterministic(self):
        self.assertEqual(kit.pick_roof_surface("mansard", 42), kit.pick_roof_surface("mansard", 42))

    def test_pick_roof_surface_follows_mix_roughly(self):
        counts = Counter(kit.pick_roof_surface("gable", i) for i in range(2000))
        self.assertGreater(counts["roof_clay"], counts["roof_zinc"] * 3)
        self.assertGreater(counts["roof_slate"], 400)
        self.assertEqual(set(kit.pick_roof_surface("flat", i) for i in range(50)), {"roof_flat"})

    def test_unknown_shape_falls_back_to_mansard_mix(self):
        self.assertIn(kit.pick_roof_surface("weird", 7), {k for k, _ in kit.ROOF_MIX["mansard"]})

    def test_committed_textures_exist(self):
        for key in kit.SURFACES:
            self.assertTrue((ASSETS / kit.TEXTURES_DIRNAME / kit.surface_file(key)).exists(), key)

    def test_tile_sizes_positive(self):
        for key in kit.SURFACES:
            self.assertGreater(kit.surface_tile_m(key), 0.0)


if __name__ == "__main__":
    unittest.main()
