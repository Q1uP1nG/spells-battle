import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MenuLayoutTests(unittest.TestCase):
    def test_long_subtitle_scale_fits_available_width(self):
        from renderer.menu import fit_text_scale

        text = "Two players cast spells, collide projectiles, use HP, Mana, shield and cooldowns."
        scale = fit_text_scale(text, cv2.FONT_HERSHEY_SIMPLEX, 600, 0.54, 1)
        width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]

        self.assertLessEqual(width, 600)
        self.assertLess(scale, 0.54)

    def test_short_subtitle_keeps_default_scale(self):
        from renderer.menu import fit_text_scale

        text = "Practice every spell with CV or keyboard."
        scale = fit_text_scale(text, cv2.FONT_HERSHEY_SIMPLEX, 600, 0.54, 1)

        self.assertEqual(scale, 0.54)

    def test_intro_screen_draws_nonblank_rule_page(self):
        from config import HEIGHT, WIDTH
        from renderer.menu import draw_intro

        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        draw_intro(frame, "CV READY", 60.0, 12)

        self.assertGreater(int(np.count_nonzero(frame)), 2000)

    def test_intro_rule_panels_are_tall_enough_for_all_rows(self):
        from config import HEIGHT, WIDTH
        from renderer.menu import draw_intro

        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        calls = []

        def capture_panel(_frame, _x, _y, _w, h, title, rows):
            calls.append((title, h, len(rows)))

        with patch("renderer.menu.draw_rule_panel", side_effect=capture_panel):
            draw_intro(frame, "CV READY", 60.0, 12)

        self.assertGreaterEqual(len(calls), 4)
        for title, height, row_count in calls:
            required = 62 + max(0, row_count - 1) * 26 + 31
            self.assertGreaterEqual(height, required, title)

    def test_rule_panel_aligns_description_column_for_mixed_label_widths(self):
        from renderer.menu import draw_rule_panel

        frame = np.zeros((240, 520, 3), dtype=np.uint8)
        rows = [
            ("Finger", "Point and draw the spell trail."),
            ("Wand", "Press V, lock a bright tip with C."),
            ("Shield", "Open palm and hold for Protego."),
            ("Keyboard", "P1 Q/W/E/R/T, P2 U/I/O/P/L."),
        ]
        description_x = []
        from renderer.menu import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            if args[1] in {text for _key, text in rows}:
                description_x.append(args[2][0])
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.menu.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_rule_panel(frame, 20, 20, 460, 180, "HOW TO CAST", rows)

        self.assertEqual(len(description_x), len(rows))
        self.assertEqual(len(set(description_x)), 1)

    def test_menu_option_subtitles_are_short_enough_for_cards(self):
        from renderer.menu import MENU_OPTIONS, fit_text_scale

        for _key, _title, subtitle in MENU_OPTIONS:
            scale = fit_text_scale(subtitle, cv2.FONT_HERSHEY_SIMPLEX, 500, 0.48, 1)
            width = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0]
            self.assertLessEqual(width, 500)

    def test_menu_excludes_tip_capture_mode(self):
        from renderer.menu import INTRO_MODE_ROWS, MENU_OPTIONS

        menu_titles = {title for _key, title, _subtitle in MENU_OPTIONS}
        intro_text = {text for _key, text in INTRO_MODE_ROWS}

        self.assertNotIn("TIP CAPTURE", menu_titles)
        self.assertNotIn("Tip capture dataset.", intro_text)
        self.assertEqual(
            {key for key, _title, _subtitle in MENU_OPTIONS},
            {"1", "2", "3", "4", "5"},
        )

    def test_intro_spell_shapes_lists_all_player_spells(self):
        from renderer.menu import INTRO_SPELL_SHAPES

        labels = {label for label, _text in INTRO_SPELL_SHAPES}

        self.assertEqual(labels, {"INC", "STU", "GLA", "PRO", "LUM", "OVR"})

    def test_remote_lobby_draws_room_and_controls(self):
        from config import HEIGHT, WIDTH
        from game.remote_session import RemoteBattleSession
        from renderer.menu import draw_remote_lobby

        session = RemoteBattleSession(network_client=object())
        session.room_code = "ABC123"
        session.player_index = 0
        session.status_message = "READY_CHECK"
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        draw_remote_lobby(frame, session)

        self.assertGreater(int(np.count_nonzero(frame)), 2000)

    def test_training_overlay_relabel_hint_excludes_protego(self):
        from config import HEIGHT, WIDTH
        from game.cv_training import CVTrainingSession
        from renderer.menu import draw_training_overlay

        session = CVTrainingSession(progress_path=None)
        session.begin_review({"primary": {"spell": "incendio"}}, [[1.0, 2.0]], track_index=0)
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from renderer.menu import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.menu.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_training_overlay(frame, session)

        text = " ".join(drawn_text)
        self.assertIn("4/5/6/7/8 relabel", text)
        self.assertIn("Slot 1/30", text)
        self.assertNotIn("S=", text)
        self.assertNotIn("4-8 relabel", text)

    def test_template_preview_preserves_vertical_orientation(self):
        from renderer.menu import draw_template_preview

        frame = np.zeros((220, 220, 3), dtype=np.uint8)
        points = [[0, 0], [1, 40], [-1, 80], [0, 120]]

        draw_template_preview(frame, points, 20, 20, 170, 170, (110, 235, 255))

        mask = (
            (frame[:, :, 0] > 90)
            & (frame[:, :, 1] > 180)
            & (frame[:, :, 2] > 180)
        )
        ys, xs = np.where(mask)

        self.assertGreater(len(xs), 20)
        self.assertLess(xs.max() - xs.min(), 45)
        self.assertGreater(ys.max() - ys.min(), 120)

    def test_player_facing_pve_copy_stays_simple(self):
        from renderer.menu import INTRO_MODE_ROWS, MENU_OPTIONS, solo_overlay_label

        text = " ".join(
            [subtitle for _key, _title, subtitle in MENU_OPTIONS]
            + [row_text for _key, row_text in INTRO_MODE_ROWS]
            + [solo_overlay_label("pve")]
        )

        self.assertNotIn("AI", text)
        self.assertIn("PVE Battle", text)
        self.assertEqual(solo_overlay_label("pve"), "PVE Battle")

    def test_solo_overlay_does_not_draw_spell_guide_panel(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.menu import draw_solo_overlay

        game = BattleGame()
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from renderer.menu import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.menu.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_solo_overlay(frame, game, now=10.0, cv_status="CV READY", mode="solo")

        text = " ".join(drawn_text)
        self.assertNotIn("Spell Guide", text)
        self.assertNotIn("Draw shape, then stop", text)

    def test_character_select_preview_always_uses_normal_pose(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.menu import draw_character_select

        game = BattleGame(character_ids=("harry", "hermione"))
        game.players[0].set_visual_state("casting", now=0.0, duration=999.0)
        game.players[1].hp = 0.0
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from renderer.menu import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(args[1])
            return original_draw_cv_text(*args, **kwargs)

        with patch("renderer.menu.draw_cv_text", side_effect=capture_draw_cv_text):
            draw_character_select(frame, game, fps=60.0, tick=1)

        text = " ".join(str(item) for item in drawn_text)
        self.assertIn("POSE: FOCUSED", text)
        self.assertIn("POSE: PRECISE", text)
        self.assertNotIn("POSE: BOLD CAST", text)
        self.assertNotIn("POSE: FALL BACK", text)

    def test_character_select_requests_normal_character_art(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.menu import draw_character_select

        game = BattleGame(character_ids=("harry", "hermione"))
        game.players[0].set_visual_state("casting", now=0.0, duration=999.0)
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        with patch("renderer.menu.draw_character_sprite", return_value=True) as draw_sprite:
            draw_character_select(frame, game, fps=60.0, tick=1)

        calls = draw_sprite.call_args_list
        self.assertEqual(calls[0].kwargs["character_id"], "harry")
        self.assertEqual(calls[0].kwargs["pose"], "normal")
        self.assertEqual(calls[1].kwargs["character_id"], "hermione")
        self.assertEqual(calls[1].kwargs["pose"], "normal")


if __name__ == "__main__":
    unittest.main()
