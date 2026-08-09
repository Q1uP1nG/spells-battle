import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RefactorSmokeTests(unittest.TestCase):
    def test_core_modules_import(self):
        import config
        from cv.gesture_classifier import classify_cv_gesture
        from game.battle import BattleGame
        from models.player import Player
        from renderer.hud import draw_hud

        self.assertIn("incendio", config.SPELLS)
        self.assertTrue(callable(classify_cv_gesture))
        self.assertTrue(callable(draw_hud))
        self.assertEqual(Player(0, "P1", "left").name, "P1")
        self.assertEqual(len(BattleGame().players), 2)

    def test_battle_game_keyboard_casting_respects_global_cooldown(self):
        from game.battle import BattleGame
        from config import GLOBAL_CAST_COOLDOWN

        game = BattleGame()
        now = 100.0

        self.assertTrue(game.cast_spell(0, "incendio", now))
        self.assertFalse(game.cast_spell(0, "stupefy", now + 0.01))
        self.assertTrue(game.cast_spell(0, "stupefy", now + GLOBAL_CAST_COOLDOWN))
        self.assertFalse(game.cast_spell(0, "incendio", now + 0.02))
        self.assertEqual(len(game.projectiles), 2)

    def test_classifier_basic_gestures(self):
        import numpy as np
        from cv.gesture_classifier import classify_cv_gesture

        rightward = [np.array([x, 100.0], dtype=np.float32) for x in range(0, 160, 12)]
        upward = [np.array([100.0, y], dtype=np.float32) for y in range(180, 40, -12)]
        downward = [np.array([100.0, y], dtype=np.float32) for y in range(40, 190, 12)]

        self.assertEqual(classify_cv_gesture(rightward, "left")[0], "incendio")
        self.assertEqual(classify_cv_gesture(upward, "left")[0], "lumos")
        self.assertEqual(classify_cv_gesture(downward, "left")[0], "glacius")


if __name__ == "__main__":
    unittest.main()
