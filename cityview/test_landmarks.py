import unittest

from cityview.landmarks import match_landmark, normalize_landmark_name
from cityview.shop_brands import fascia_for_brand, normalize_shop_brand


class LandmarkTests(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(
            normalize_landmark_name("Sint-Bonifaciuskerk"),
            "sint bonifaciuskerk",
        )

    def test_match_by_id(self):
        hit = match_landmark(453577567, "", "church")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["massing"], "neo_gothic_tower_left")
        self.assertEqual(hit["photo"], "sint_bonifaciuskerk.jpg")

    def test_match_by_name(self):
        hit = match_landmark(1, "Heilige Geestkerk", "church")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["massing"], "neo_romanesque_tower_left")


class BrandTests(unittest.TestCase):
    def test_aldi(self):
        self.assertEqual(normalize_shop_brand({"brand": "ALDI", "shop": "supermarket"}), "aldi")

    def test_carrefour_express(self):
        self.assertEqual(
            normalize_shop_brand({"name": "Carrefour Express", "shop": "convenience"}),
            "carrefour",
        )

    def test_unknown(self):
        self.assertIsNone(normalize_shop_brand({"name": "Nachtwinkel", "shop": "convenience"}))

    def test_fascia(self):
        self.assertEqual(fascia_for_brand("aldi")["label"], "ALDI")
        self.assertEqual(fascia_for_brand(None)["label"], "")


if __name__ == "__main__":
    unittest.main()
