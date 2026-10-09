import unittest

from cityview.geo import project
from cityview.shops import category_for, has_terrace, parse_opening_hours, plan_shops

ORIGIN = (51.2017, 4.4114)


def _latlon(x: float, y: float) -> tuple[float, float]:
    """Invert the local projection numerically (small offsets only)."""
    lat, lon = ORIGIN
    for _ in range(6):
        px, py = project(lat, lon, *ORIGIN)
        lat += (y - py) / 111_320.0
        lon += (x - px) / (111_320.0 * 0.6265)
    return lat, lon


def _node(nid: int, x: float, y: float, **tags) -> dict:
    lat, lon = _latlon(x, y)
    return {"type": "node", "id": nid, "lat": lat, "lon": lon, "tags": tags}


def _layout() -> dict:
    # A 20 x 10 m block; its south face (y = 0) is on the street.
    ring = [[0.0, 0.0], [20.0, 0.0], [20.0, 10.0], [0.0, 10.0]]
    return {
        "buildings": [
            {
                "id": 1,
                "ring": ring,
                "floors": 4,
                "street_edges": [{"i0": 0, "i1": 1, "length": 20.0, "outward": [0.0, -1.0]}],
            }
        ]
    }


class TerraceTests(unittest.TestCase):
    def test_horeca_defaults_to_terrace_unless_tagged_no(self):
        self.assertTrue(has_terrace({}, "cafe", "horeca"))
        self.assertFalse(has_terrace({"outdoor_seating": "no"}, "pub", "horeca"))
        self.assertFalse(has_terrace({}, "fast_food", "horeca"))
        self.assertTrue(has_terrace({"outdoor_seating": "yes"}, "bakery", "food"))
        self.assertFalse(has_terrace({}, "clothes", "retail"))


class OpeningHoursTests(unittest.TestCase):
    def test_common_forms(self):
        week = parse_opening_hours("Mo-Fr 09:00-18:00; Sa 10:00-17:00")
        self.assertEqual(week[0], [])  # Sunday closed
        self.assertEqual(week[1], [(9.0, 18.0)])
        self.assertEqual(week[6], [(10.0, 17.0)])

    def test_overrides_split_ranges_and_midnight(self):
        week = parse_opening_hours("Mo-Sa 07:30-20:00; Th off; Su 08:30-19:00")
        self.assertEqual(week[4], [])
        self.assertEqual(week[0], [(8.5, 19.0)])
        week = parse_opening_hours("Tu,We,Su 11:00-23:00, Th-Sa 11:00-01:00; Mo off")
        self.assertEqual(week[5], [(11.0, 25.0)])
        self.assertEqual(week[1], [])
        week = parse_opening_hours("Mo, We, Fr 09:30-12:30, 13:30-17:00; Sa 09:30-13:00")
        self.assertEqual(week[3], [(9.5, 12.5), (13.5, 17.0)])

    def test_everyday_and_unknown(self):
        self.assertEqual(parse_opening_hours("24/7")[3], [(0.0, 24.0)])
        self.assertEqual(parse_opening_hours("07:00-23:00")[0], [(7.0, 23.0)])
        self.assertIsNone(parse_opening_hours("by appointment"))
        self.assertIsNone(parse_opening_hours(None))


class ShopPlanTests(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(category_for({"shop": "bakery"}), ("bakery", "food"))
        self.assertEqual(category_for({"amenity": "pub"}), ("pub", "horeca"))
        self.assertEqual(category_for({"shop": "books"}), ("books", "retail"))
        self.assertIsNone(category_for({"shop": "vacant"}))
        self.assertIsNone(category_for({"amenity": "bench"}))

    def test_snaps_to_street_face_and_spaces_signs(self):
        osm = {
            "elements": [
                _node(10, 6.0, 4.0, shop="bakery", name="Bakkerij Jan"),
                _node(11, 6.5, 3.0, shop="butcher"),  # same spot: skipped
                _node(12, 15.0, 6.0, amenity="cafe", name="Café", opening_hours="Mo-Su 08:00-22:00"),
                _node(13, 300.0, 300.0, shop="florist"),  # nowhere near a façade
            ]
        }
        shops = plan_shops(osm, _layout(), ORIGIN)
        by_id = {s["id"]: s for s in shops}
        self.assertEqual(sorted(by_id), [10, 12])
        for s in shops:
            self.assertAlmostEqual(s["y"], 0.0, places=1)
            self.assertEqual((s["nx"], s["ny"]), (0.0, -1.0))
            self.assertLessEqual(s["w"], 20.0)
        cafe = by_id[12]
        self.assertTrue(cafe["hoursKnown"])
        self.assertEqual(cafe["hours"][0], [[8.0, 22.0]])
        self.assertFalse(by_id[10]["hoursKnown"])
        self.assertEqual(len(by_id[10]["hours"]), 7)


if __name__ == "__main__":
    unittest.main()
