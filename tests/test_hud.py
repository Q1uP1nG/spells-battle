import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HudTests(unittest.TestCase):
    def test_spell_status_text_prefers_spell_cooldown(self):
        from renderer.hud import spell_status_text

        self.assertEqual(spell_status_text(3.2, 0.8, True), "CD")

    def test_spell_status_text_shows_global_cooldown(self):
        from renderer.hud import spell_status_text

        self.assertEqual(spell_status_text(0.0, 0.8, True), "WAIT")

    def test_spell_status_text_shows_no_mana(self):
        from renderer.hud import spell_status_text

        self.assertEqual(spell_status_text(0.0, 0.0, False), "MANA")

    def test_spell_status_text_shows_ready(self):
        from renderer.hud import spell_status_text

        self.assertEqual(spell_status_text(0.0, 0.0, True), "READY")

    def test_footer_hint_is_compact(self):
        from renderer.hud import compact_footer_hint

        hint = compact_footer_hint()

        self.assertIn("V", hint)
        self.assertIn("M", hint)
        self.assertLessEqual(len(hint), 64)

    def test_player_condition_text_hides_empty_statuses(self):
        from renderer.hud import player_condition_text

        self.assertEqual(player_condition_text(0.0, 0.0), "")
        self.assertEqual(player_condition_text(1.4, 0.0), "SILENCE")
        self.assertEqual(player_condition_text(0.0, 0.6), "RECOVER")

    def test_draw_hud_hides_debug_labels_by_default(self):
        import cv2
        import numpy as np
        from unittest.mock import patch

        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.hud import draw_hud

        game = BattleGame(character_ids=("harry", "ron"))
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from renderer.hud import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.hud.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_hud(frame, game, now=10.0, fps=59.8, cv_status="CV WAND LOCKED")

        text = " ".join(drawn_text)
        self.assertNotIn("FPS", text)
        self.assertNotIn("CV WAND LOCKED", text)

    def test_draw_hud_can_show_debug_labels(self):
        import cv2
        import numpy as np
        from unittest.mock import patch

        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.hud import draw_hud

        game = BattleGame(character_ids=("harry", "ron"))
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from renderer.hud import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.hud.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_hud(
                frame,
                game,
                now=10.0,
                fps=59.8,
                cv_status="CV WAND LOCKED",
                show_debug=True,
            )

        text = " ".join(drawn_text)
        self.assertIn("FPS", text)
        self.assertIn("CV WAND LOCKED", text)


if __name__ == "__main__":
    unittest.main()
