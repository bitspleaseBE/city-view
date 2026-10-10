import unittest

from cityview.landmarks import (
    attach_landmark,
    custom_landmark_entry,
    landmark_nodes,
    match_landmark,
    normalize_landmark_name,
)
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


class CustomLandmarkTests(unittest.TestCase):
    ORIGIN = (51.2017, 4.4114)

    def test_five_custom_buildings(self):
        for osm_id, kind in (
            (7345816, "zas_vincentius"),
            (231220414, "feestzaal_harmonie"),
            (501410388, "art_deco_ms123"),
            (232921425, "gulden_spoor"),
            (117235287, "albertpark_kiosk"),
        ):
            self.assertEqual(custom_landmark_entry(osm_id)["custom"], kind)

    def test_second_set_and_streamed_church(self):
        for osm_id, kind in (
            (503713425, "harmonie_koetshuis"),
            (501637650, "benoit_34"),
            (501637651, "benoit_38"),
            (501637652, "benoit_40"),
            (453577567, "bonifacius"),
            (353285592, "heilig_hart"),
            (432190363, "heilig_hart_klooster"),
        ):
            self.assertEqual(custom_landmark_entry(osm_id)["custom"], kind)
        hit = match_landmark(501410385, "", "church")
        self.assertTrue(hit.get("stream"))

    def test_zas_campus_photo_entry_gone(self):
        self.assertIsNone(match_landmark(9715814, "", "hospital"))
        self.assertIsNone(match_landmark(1, "ZAS Sint-Vincentius", "hospital"))

    def test_attach_projects_anchor_and_params(self):
        bldg = attach_landmark({"id": 231220414, "building_type": "hall"}, origin=self.ORIGIN)
        lm = bldg["landmark"]
        self.assertEqual(lm["custom"], "feestzaal_harmonie")
        self.assertEqual(len(lm["anchor_xy"]), 2)
        self.assertEqual(len(lm["params"]["entrance_xy"]), 2)
        self.assertNotIn("photo", lm)

    def test_monument_node(self):
        nodes = {2396262252: {"lat": 51.2011606, "lon": 4.4117298, "tags": {"name": "Peter Benoit"}}}
        out = landmark_nodes(nodes, self.ORIGIN)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["custom"], "benoit_monument")
        self.assertIsNotNone(out[0]["facing_xy"])
        self.assertEqual(landmark_nodes({}, self.ORIGIN), [])


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
