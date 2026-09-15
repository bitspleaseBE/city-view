import json
import tempfile
import unittest
from pathlib import Path

from cityview.jobs import add_photo_building, load_scene, write_job


class JobTests(unittest.TestCase):
    def test_replaces_existing_photo_building(self):
        scene = {
            "buildings": [
                {"name": "a", "kind": "procedural", "width": 6},
                {"name": "hero", "kind": "photo", "width": 7},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "facade.jpg"
            photo.write_bytes(b"x")
            updated = add_photo_building(scene, photo, "new-hero")
        kinds = [b["kind"] for b in updated["buildings"]]
        self.assertEqual(kinds, ["procedural", "photo"])
        self.assertEqual(updated["buildings"][1]["name"], "new-hero")
        self.assertTrue(updated["buildings"][1]["photo"].endswith("facade.jpg"))

    def test_write_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.json"
            write_job(path, {"title": "test", "buildings": []})
            data = load_scene(path)
        self.assertEqual(data["title"], "test")


if __name__ == "__main__":
    unittest.main()
