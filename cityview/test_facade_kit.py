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
        self.assertEqual(len(kit.ground_quads(quads)), 1)
        q = quads[0]
        for piece in quads:  # every vertical piece of the house shows the same slice
            self.assertEqual((piece["uv"][0], piece["uv"][2]), (q["uv"][0], q["uv"][2]))
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


class TallBuildingTests(unittest.TestCase):
    """Storey counts from 2 to 20 must stack / drop strips, never smear one picture."""

    LEVELS = (2, 3, 4, 5, 6, 8, 12, 16, 20)

    def _houses(self, quads):
        houses = {}
        for q in quads:
            houses.setdefault(round(q["a0"], 6), []).append(q)
        return list(houses.values())

    def test_bands_are_committed_for_most_elevations(self):
        self.assertGreaterEqual(len(kit.band_layout()), 40)
        for fid, b in kit.band_layout().items():
            self.assertIn(fid, kit.FACADES)
            self.assertTrue(0.05 < b["lo"] < b["hi"] < 0.97, fid)
            strip_m = (b["hi"] - b["lo"]) * kit.FACADES[fid]["height_m"]
            self.assertTrue(2.4 < strip_m < 4.4, (fid, strip_m))

    def test_every_level_count_fills_ground_to_eaves_without_gaps(self):
        for levels in self.LEVELS:
            eaves = levels * 3.15
            quads = kit.plan_facade_quads(24.0, eaves, levels, "international", seed=levels)
            for house in self._houses(quads):
                house = sorted(house, key=lambda q: q["z0"])
                self.assertAlmostEqual(house[0]["z0"], 0.0)
                self.assertAlmostEqual(house[-1]["z1"], eaves, places=6)
                for lower, upper in zip(house, house[1:]):
                    self.assertAlmostEqual(lower["z1"], upper["z0"], places=6)
                    self.assertGreater(upper["z1"], upper["z0"])
                self.assertEqual(house[0]["band"], "ground")

    def test_pieces_keep_window_proportions(self):
        # Vertical metres-per-picture-metre stays near 1 for every level count (no smear).
        for levels in self.LEVELS:
            eaves = levels * 3.15
            for q in kit.plan_facade_quads(18.0, eaves, levels, "art-deco", seed=7 + levels):
                f0, f1 = q["vz"]
                metres = (f1 - f0) * kit.FACADES[q["cell"]]["height_m"]
                scale = (q["z1"] - q["z0"]) / metres
                self.assertTrue(0.5 < scale < 1.6, (levels, q["cell"], scale))

    def test_uv_stays_inside_the_cell_and_is_never_mirrored(self):
        for levels in self.LEVELS:
            for q in kit.plan_facade_quads(30.0, levels * 3.15, levels, "eclectic", seed=levels):
                u0, v0, u1, v1 = q["uv"]
                cu0, cv0, cu1, cv1 = kit.cell_uv_rect(q["cell"])
                self.assertLess(u0, u1)
                self.assertLess(v0, v1)
                self.assertTrue(cu0 - 1e-9 <= u0 and u1 <= cu1 + 1e-9)
                self.assertTrue(cv0 - 1e-9 <= v0 and v1 <= cv1 + 1e-9)

    def test_tall_strip_repeats_the_same_picture_rows(self):
        quads = kit.plan_facade_quads(9.0, 12 * 3.15, 12, "international", seed=2)
        mids = [q for q in quads if q["band"] == "mid"]
        self.assertGreaterEqual(len(mids), 4)  # a 12-level tower is mostly stacked storeys
        self.assertEqual({q["uv"] for q in mids}, {mids[0]["uv"]})

    def test_door_steps_and_awnings_only_at_street_level(self):
        quads = kit.plan_facade_quads(40.0, 12 * 3.15, 12, "international", seed=11)
        for step in kit.door_steps(quads):
            self.assertTrue(0.0 <= step["a"] <= 40.0)
        for awning in kit.shop_awnings(quads):
            ground = [q for q in kit.ground_quads(quads) if q["a0"] <= awning["a"] <= q["a1"]]
            self.assertTrue(ground)
            self.assertLessEqual(awning["z"], ground[0]["z1"] + 1e-6)

    def test_window_reveals_stay_on_their_own_piece(self):
        for levels in (4, 9, 14):
            quads = kit.plan_facade_quads(18.0, levels * 3.15, levels, "art-deco", seed=3)
            reveals = kit.window_reveals(quads)
            for r in reveals:
                self.assertGreaterEqual(r["z0"], 0.0)
                self.assertLessEqual(r["z1"], levels * 3.15 + 1e-6)
                self.assertLess(r["z0"], r["z1"])

    def test_downpipes_use_one_quad_per_house(self):
        quads = kit.plan_facade_quads(40.0, 12 * 3.15, 12, "art-deco", seed=5)
        joints = [0.5 * (l["a1"] + r["a0"]) for l, r in zip(kit.ground_quads(quads), kit.ground_quads(quads)[1:])]
        for p in kit.downpipes(quads, 12 * 3.15):
            self.assertTrue(any(abs(p["a"] - j) < 1e-6 for j in joints))

    def test_towers_use_wider_elevations_than_townhouses(self):
        tower = kit.ground_quads(kit.plan_facade_quads(36.0, 12 * 3.15, 12, "international", seed=1))
        houses = kit.ground_quads(kit.plan_facade_quads(36.0, 3 * 3.15, 3, "international", seed=1))
        self.assertLess(len(tower), len(houses))
