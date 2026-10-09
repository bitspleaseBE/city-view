import json
import unittest
from collections import Counter

from cityview import facade_kit as kit
from cityview.paths import ASSETS


class FacadeKitTests(unittest.TestCase):
    def test_there_are_fifty_generated_facades_with_source_files(self):
        self.assertEqual(kit.FACADE_COUNT, 50)
        self.assertEqual(len(set(kit.cell_ids())), 50)
        for fid, f in kit.FACADES.items():
            self.assertTrue((ASSETS / kit.FACADE_SRC_DIR / f["file"]).exists(), fid)

    def test_every_type_has_facades_and_a_wall_tile(self):
        for type_id, tile in kit.TYPE_WALL_TILE.items():
            self.assertIn(tile, kit.WALL_TILES)
            self.assertTrue(kit.facades_for_type(type_id), type_id)
        for tile in kit.WALL_TILES.values():
            self.assertTrue((ASSETS / kit.WALL_SRC_DIR / tile["src"]).exists())

    def test_cell_uv_rects_stay_inside_atlas_and_do_not_overlap(self):
        rects = []
        for cid in kit.cell_ids():
            u0, v0, u1, v1 = kit.cell_uv_rect(cid)
            self.assertTrue(0.0 <= u0 < u1 <= 1.0)
            self.assertTrue(0.0 <= v0 < v1 <= 1.0)
            rects.append((u0, v0, u1, v1))
        for i, a in enumerate(rects):
            for b in rects[i + 1 :]:
                overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                self.assertFalse(overlap)

    def test_plan_is_a_straight_unmirrored_terrace_covering_the_edge(self):
        quads = kit.plan_facade_quads(26.0, 13.0, 4, "art-nouveau", seed=3)
        self.assertGreaterEqual(len(quads), 3)
        self.assertAlmostEqual(quads[0]["a0"], 0.0)
        self.assertAlmostEqual(quads[-1]["a1"], 26.0)
        for left, right in zip(quads, quads[1:]):
            self.assertAlmostEqual(left["a1"], right["a0"])
            self.assertNotEqual(left["cell"], right["cell"])  # neighbours differ: a terrace
        for q in quads:
            self.assertFalse(q["flip"])
            self.assertLess(q["uv"][0], q["uv"][2])  # u runs left->right, never mirrored
            self.assertAlmostEqual(q["z0"], 0.0)
            self.assertAlmostEqual(q["z1"], 13.0)  # one full elevation, ground to eaves

    def test_short_edge_is_cropped_not_squashed(self):
        quads = kit.plan_facade_quads(3.0, 9.0, 3, "art-nouveau", seed=1)
        self.assertEqual(len(quads), 1)
        q = quads[0]
        full = kit.cell_uv_rect(q["cell"])
        self.assertLess(q["uv"][2] - q["uv"][0], full[2] - full[0])
        self.assertGreaterEqual(q["uv"][0], full[0] - 1e-9)
        self.assertLessEqual(q["uv"][2], full[2] + 1e-9)

    def test_pick_prefers_matching_storeys(self):
        for floors in (3, 4, 5):
            picks = Counter(
                kit.FACADES[kit.pick_facade("eclectic", floors, 6.4, f"k{i}")]["storeys"] for i in range(60)
            )
            self.assertEqual(picks.most_common(1)[0][0], floors, floors)

    def test_many_distinct_facades_get_used(self):
        used = set()
        types = list(kit.TYPE_WALL_TILE)
        for i in range(1500):
            floors = 3 + i % 3
            length = 14.0 + (i % 5) * 4
            for q in kit.plan_facade_quads(length, floors * 3.2, floors, types[i % len(types)], seed=i * 7919):
                used.add(q["cell"])
        self.assertGreaterEqual(len(used), 45)

    def test_pick_is_stable_and_valid(self):
        a = kit.pick_cell("art-nouveau__v1", 42)
        self.assertEqual(a, kit.pick_cell("art-nouveau__v1", 42))
        self.assertIn(a, kit.FACADES)
        self.assertIn(kit.pick_cell("never-heard-of-it", 1), kit.FACADES)

    def test_committed_textures_exist_with_expected_size(self):
        atlas = ASSETS / kit.TEXTURES_DIRNAME / kit.ATLAS_FILE
        self.assertTrue(atlas.exists(), "run python -m cityview.facade_textures")
        self.assertGreater(atlas.stat().st_size, 500_000)
        for tid in kit.WALL_TILES:
            self.assertTrue((ASSETS / kit.TEXTURES_DIRNAME / kit.wall_tile_file(tid)).exists(), tid)
        # JPEG SOI + SOF dimensions must match the kit's atlas geometry.
        data = atlas.read_bytes()
        self.assertEqual(data[:2], b"\xff\xd8")
        i = 2
        while i < len(data):
            marker = data[i + 1]
            length = int.from_bytes(data[i + 2 : i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2):
                h = int.from_bytes(data[i + 5 : i + 7], "big")
                w = int.from_bytes(data[i + 7 : i + 9], "big")
                self.assertEqual((w, h), kit.atlas_size())
                break
            i += 2 + length

    def test_building_types_json_lists_generated_facades(self):
        doc = json.loads((ASSETS / "styles" / "building_types.json").read_text())
        self.assertEqual(doc["facade_kit"]["count"], 50)
        self.assertEqual(len(doc["facade_kit"]["facades"]), 50)
        for type_id, entry in doc["types"].items():
            self.assertTrue(entry.get("facade_cells"), type_id)
            for cell in entry["facade_cells"]:
                self.assertIn(cell, kit.FACADES)
            self.assertIn(entry.get("wall_tile"), kit.WALL_TILES)


    def test_downpipes_sit_on_joints_clear_of_doors_and_thinned(self):
        quads = kit.plan_facade_quads(40.0, 13.0, 4, "art-nouveau", seed=5)
        joints = [0.5 * (l["a1"] + r["a0"]) for l, r in zip(quads, quads[1:])]
        pipes = kit.downpipes(quads, 13.0)
        self.assertTrue(pipes)
        for p in pipes:
            self.assertTrue(any(abs(p["a"] - j) < 1e-6 for j in joints))
            self.assertAlmostEqual(p["z1"], 12.85)
        gaps = [b["a"] - a["a"] for a, b in zip(pipes, pipes[1:])]
        self.assertTrue(all(g >= 5.0 for g in gaps))
        blocked = kit.downpipes(quads, 13.0, keep_clear=[(j, 2.0) for j in joints])
        self.assertEqual(blocked, [])


if __name__ == "__main__":
    unittest.main()


class ShopAwningTests(unittest.TestCase):
    def test_awning_over_known_shopfront(self):
        quads = kit.plan_facade_quads(6.4, 12.0, 4, "eclectic", 0)
        quads[0]["cell"] = "facade_01"
        u0, v0, u1, v1 = kit.cell_uv_rect("facade_01")
        quads[0]["uv"] = (u0, v0, u1, v1)
        awnings = kit.shop_awnings(quads, rightwards=True)
        self.assertEqual(len(awnings), 1)
        a = awnings[0]
        self.assertGreater(a["w"], 1.4)
        self.assertAlmostEqual(a["z"], 0.32 * 12.0, places=3)
        self.assertTrue(0.0 < a["a"] < 6.4)

    def test_no_awning_without_shop(self):
        quads = kit.plan_facade_quads(6.4, 12.0, 4, "eclectic", 0)
        quads[0]["cell"] = "facade_05"
        self.assertEqual(kit.shop_awnings(quads), [])

    def test_awning_mirrors_with_edge_orientation(self):
        quads = kit.plan_facade_quads(6.4, 12.0, 4, "eclectic", 0)
        quads[0]["cell"] = "facade_01"
        quads[0]["uv"] = kit.cell_uv_rect("facade_01")
        r = kit.shop_awnings(quads, rightwards=True)[0]["a"]
        l = kit.shop_awnings(quads, rightwards=False)[0]["a"]
        self.assertAlmostEqual(r + l, 6.4, places=3)
