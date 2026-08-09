import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CharacterAssetTests(unittest.TestCase):
    def test_asset_path_uses_transparent_folder_and_character_pose_name(self):
        from renderer.character_assets import character_asset_path

        path = character_asset_path("harry", "normal")

        self.assertEqual(path.name, "harry_normal.png")
        self.assertEqual(path.parent.name, "pictures_transparent")

    def test_load_character_image_returns_bgra_and_is_cached(self):
        from renderer.character_assets import clear_character_asset_cache, load_character_image

        clear_character_asset_cache()
        first = load_character_image("harry", "normal")
        second = load_character_image("harry", "normal")

        self.assertIsNotNone(first)
        self.assertEqual(first.shape[2], 4)
        self.assertIs(first, second)

    def test_alpha_blend_bgra_changes_only_visible_pixels(self):
        from renderer.character_assets import alpha_blend_bgra

        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        sprite = np.zeros((2, 2, 4), dtype=np.uint8)
        sprite[:, :, :3] = (0, 0, 255)
        sprite[0, 0, 3] = 255

        drawn = alpha_blend_bgra(frame, sprite, bottom_center=(4, 5), max_height=2)

        self.assertTrue(drawn)
        self.assertGreater(int(frame[:, :, 2].sum()), 0)
        self.assertEqual(int(frame[:, :, 0].sum()), 0)
        self.assertEqual(int(frame[:, :, 1].sum()), 0)

    def test_draw_character_sprite_returns_false_for_missing_asset(self):
        from renderer.character_assets import draw_character_sprite

        frame = np.zeros((20, 20, 3), dtype=np.uint8)

        drawn = draw_character_sprite(
            frame,
            character_id="missing",
            pose="normal",
            bottom_center=(10, 18),
            max_height=12,
        )

        self.assertFalse(drawn)
        self.assertEqual(int(frame.sum()), 0)


if __name__ == "__main__":
    unittest.main()
