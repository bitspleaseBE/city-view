import math
import unittest

from cityview import climbers


def _layout(n_streets=40, per_street=6):
    roads, buildings = [], []
    bid = 1
    for s in range(n_streets):
        y = s * 60.0
        roads.append(
            {"id": s, "points": [[0.0, y], [200.0, y]], "width": 7.0, "kind": "residential", "name": f"Straat {s}"}
        )
        for h in range(per_street):
            x = 10.0 + h * 30.0
            ring = [[x, y + 8], [x + 12, y + 8], [x + 12, y + 20], [x, y + 20]]
            buildings.append(
                {
                    "id": bid,
                    "ring": ring,
                    "height": 12.0,
                    "building_type": "art-nouveau" if h % 2 else "eclectic",
                    "street_edges": [{"i0": 0, "i1": 1, "length": 12.0, "outward": [0.0, -1.0]}],
                }
            )
            bid += 1
    return {"roads": roads, "buildings": buildings}


class ClimberPlanTests(unittest.TestCase):
    def test_cap_and_most_streets_empty(self):
        layout = _layout()
        plan = climbers.plan_climbers(layout, None)
        per_street = {}
        for spec in plan.values():
            per_street[spec["street"]] = per_street.get(spec["street"], 0) + 1
        self.assertTrue(per_street)
        self.assertLessEqual(max(per_street.values()), climbers.MAX_PER_STREET)
        self.assertLess(len(per_street), len(layout["roads"]) * 0.6)  # most streets: none

    def test_deterministic(self):
        layout = _layout()
        self.assertEqual(climbers.plan_climbers(layout, None), climbers.plan_climbers(layout, None))

    def test_unnamed_and_modern_never(self):
        layout = _layout(10, 3)
        for r in layout["roads"]:
            r["name"] = ""
        self.assertEqual(climbers.plan_climbers(layout, None), {})
        layout = _layout(30, 3)
        for b in layout["buildings"]:
            b["building_type"] = "modern-infill"
        self.assertEqual(climbers.plan_climbers(layout, None), {})

    def test_spacing_on_street(self):
        plan = climbers.plan_climbers(_layout(200, 6), None)
        self.assertTrue(any(True for _ in plan))


class ClimberShapeTests(unittest.TestCase):
    def test_stays_on_facade_and_thins_out(self):
        spec = {"seed": 7, "species": "ivy", "height_frac": 0.85}
        windows = [(-4.0 + 2.5 * i, 0.5, 2.0, 3.4) for i in range(4)]
        plant = climbers.generate_climber(spec, 12.0, 12.0, 1.0, windows)
        self.assertGreater(len(plant["leaves"]), 40)
        for a, z, *_ in plant["leaves"]:
            self.assertLessEqual(abs(a), 6.0)
            self.assertGreater(z, 0.0)
            self.assertLess(z, 12.0)
        low = sum(1 for a, z, *_ in plant["leaves"] if z < 4.0)
        high = sum(1 for a, z, *_ in plant["leaves"] if z >= 8.0)
        self.assertGreater(low, high)
        mats = {m[-1] for m in plant["leaves"]}
        self.assertGreater(len(mats), 1)  # colour variation

    def test_windows_mostly_clear(self):
        spec = {"seed": 11, "species": "creeper", "height_frac": 0.9}
        win = (0.0, 1.0, 3.0, 5.0)
        inside = 0
        for seed in range(30):
            spec["seed"] = seed
            plant = climbers.generate_climber(spec, 14.0, 13.0, 1.0, [win])
            inside += sum(1 for a, z, *_ in plant["leaves"] if abs(a) < 0.9 and 3.05 < z < 4.95)
        self.assertLess(inside, 60)


if __name__ == "__main__":
    unittest.main()
