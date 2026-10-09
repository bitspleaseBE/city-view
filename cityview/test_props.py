import unittest

from cityview.props import export_props_for_viewer, trunk_radius


class PropsExportTest(unittest.TestCase):
    def test_trunk_radius_clamped(self):
        self.assertAlmostEqual(trunk_radius(2.0, 0.5), 0.095)
        self.assertEqual(trunk_radius(30.0, 8.0), 0.36)

    def test_exports_solids_near_spawn_only(self):
        layout = {
            "trees": [{"x": 1, "y": 2, "height": 10, "radius": 3}, {"x": 5000, "y": 0}],
            "benches": [{"x": 3, "y": 4, "yaw": 0.5, "length": 2.0}],
            "clutter": [
                {"kind": "bollard", "x": 0, "y": 1},
                {"kind": "bike_rack", "x": 2, "y": 2, "hoops": 5, "yaw": 1.0},
                {"kind": "picnic_table", "x": 4, "y": 1, "yaw": 0.25},
                {"kind": "charging", "x": 1, "y": 1},
                {"kind": "flower_tub", "x": 2, "y": 3},
            ],
            "barriers": [
                {"kind": "hedge", "x0": 0, "y0": 0, "x1": 10, "y1": 0},
                {"kind": "kerb", "x0": 0, "y0": 0, "x1": 1, "y1": 0},
            ],
        }
        out = export_props_for_viewer(layout, {"x": 0, "y": 0}, radius=100)
        self.assertEqual(out["trunks"], [[1.0, 2.0, 0.23], [0.0, 1.0, 0.09], [1.0, 1.0, 0.28]])
        self.assertEqual(
            out["boxes"],
            [
                [3.0, 4.0, 0.5, 1.0, 0.3],
                [2.0, 2.0, 1.0, 2.0, 0.12],
                [4.0, 1.0, 0.25, 0.9, 0.55],
            ],
        )
        self.assertEqual(out["segments"], [[0.0, 0.0, 10.0, 0.0, 0.3]])


if __name__ == "__main__":
    unittest.main()
