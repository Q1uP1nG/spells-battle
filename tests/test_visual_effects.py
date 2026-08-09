import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class VisualEffectsTests(unittest.TestCase):
    def test_postfx_defaults_to_fast_bloom_scale(self):
        from renderer.postfx import PostFX

        postfx = PostFX()

        self.assertGreaterEqual(postfx.bloom_scale, 8)

    def test_apply_screen_feedback_changes_frame_when_flash_active(self):
        from renderer.effects import apply_screen_feedback

        game = type("Game", (), {
            "screen_shake_until": 0.0,
            "screen_shake_intensity": 0.0,
            "hit_flash_until": 10.5,
            "hit_flash_intensity": 0.5,
        })()
        frame = np.zeros((80, 120, 3), dtype=np.uint8)

        apply_screen_feedback(frame, game, now=10.0)

        self.assertGreater(int(np.count_nonzero(frame)), 0)

    def test_draw_flash_messages_drops_expired_messages(self):
        from renderer.effects import draw_flash_messages

        game = type("Game", (), {
            "flash_messages": [
                {
                    "text": "COUNTERED!",
                    "pos": np.array([60.0, 40.0], dtype=np.float32),
                    "color": (255, 255, 255),
                    "created_at": 9.0,
                    "until": 9.5,
                    "duration": 0.5,
                },
                {
                    "text": "CLASH",
                    "pos": np.array([70.0, 42.0], dtype=np.float32),
                    "color": (255, 255, 255),
                    "created_at": 9.8,
                    "until": 10.5,
                    "duration": 0.7,
                },
            ],
        })()
        frame = np.zeros((80, 120, 3), dtype=np.uint8)

        draw_flash_messages(frame, game, now=10.0)

        self.assertEqual([msg["text"] for msg in game.flash_messages], ["CLASH"])
        self.assertGreater(int(np.count_nonzero(frame)), 0)


if __name__ == "__main__":
    unittest.main()
