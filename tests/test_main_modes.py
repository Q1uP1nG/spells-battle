import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MainModeTests(unittest.TestCase):
    def test_intro_ignores_no_key_and_escape(self):
        from main import should_leave_intro

        self.assertFalse(should_leave_intro(255))
        self.assertFalse(should_leave_intro(27))

    def test_intro_leaves_on_any_regular_key(self):
        from main import should_leave_intro

        self.assertTrue(should_leave_intro(ord("a")))
        self.assertTrue(should_leave_intro(ord("1")))

    def test_escape_goes_back_to_menu_outside_menu_but_quits_from_menu(self):
        from game.mode import GameMode
        from main import should_quit, should_return_to_menu

        self.assertTrue(should_return_to_menu(27, GameMode.PVE))
        self.assertTrue(should_return_to_menu(27, GameMode.CHARACTER_SELECT))
        self.assertFalse(should_return_to_menu(27, GameMode.MENU))
        self.assertTrue(should_quit(27, GameMode.MENU))
        self.assertFalse(should_quit(27, GameMode.PVE))

    def test_x_is_quit_key_and_q_remains_spell_key(self):
        from game.mode import GameMode
        from main import should_quit

        self.assertTrue(should_quit(ord("x"), GameMode.PVE))
        self.assertTrue(should_quit(ord("X"), GameMode.MENU))
        self.assertFalse(should_quit(ord("q"), GameMode.PVE))
        self.assertFalse(should_quit(ord("Q"), GameMode.MENU))

    def test_training_label_key_only_routes_in_cv_training_mode(self):
        from main import handle_cv_training_key
        from game.mode import GameMode, ModeRunner

        class FakeRunner:
            mode = GameMode.CV_TRAINING

            def __init__(self):
                self.keys = []

            def handle_training_key(self, key, cv_controller):
                self.keys.append(key)
                return "LABEL CHANGED"

        runner = FakeRunner()

        notice = handle_cv_training_key(ord("6"), runner, object())

        self.assertEqual(notice, "LABEL CHANGED")
        self.assertEqual(runner.keys, [ord("6")])

    def test_training_label_key_ignored_in_normal_modes(self):
        from main import handle_cv_training_key
        from game.mode import GameMode, ModeRunner

        runner = ModeRunner(GameMode.SOLO)

        notice = handle_cv_training_key(ord("6"), runner, object())

        self.assertEqual(notice, "")

    def test_debug_hotkey_yields_to_training_spell_navigation(self):
        from game.mode import GameMode
        from main import should_toggle_debug

        self.assertFalse(should_toggle_debug(ord("d"), GameMode.CV_TRAINING))
        self.assertFalse(should_toggle_debug(ord("D"), GameMode.CV_TRAINING))
        self.assertTrue(should_toggle_debug(ord("d"), GameMode.PVE))
        self.assertTrue(should_toggle_debug(ord("D"), GameMode.SOLO))

    def test_space_reset_is_disabled_in_cv_training_mode(self):
        from game.mode import GameMode
        from main import should_reset_with_space

        self.assertFalse(should_reset_with_space(ord(" "), GameMode.CV_TRAINING))
        self.assertFalse(should_reset_with_space(ord("x"), GameMode.SOLO))
        self.assertTrue(should_reset_with_space(ord(" "), GameMode.SOLO))
        self.assertTrue(should_reset_with_space(ord(" "), GameMode.DUEL))

    def test_cv_training_status_uses_training_labels_for_circle(self):
        from game.cv_training import CVTrainingSession
        from main import format_cv_training_status

        session = CVTrainingSession(spell_order=["incendio", "circle"], progress_path=None)
        session.next_spell()
        status = format_cv_training_status("CV FINGER", session)

        self.assertIn("TARGET CIR 1/30", status)

        session.begin_review({"primary": {"spell": "stupefy"}}, [[0, 0], [10, 10]], track_index=0)
        review_status = format_cv_training_status("CV FINGER", session)

        self.assertIn("REVIEW CIR", review_status)

    def test_mode_keys_do_not_include_tip_capture(self):
        from main import MODES_BY_KEY
        from game.mode import GameMode

        self.assertNotIn(ord("5"), MODES_BY_KEY)
        self.assertEqual(MODES_BY_KEY[ord("4")], GameMode.CV_TRAINING)

    def test_character_keys_cycle_players_with_af_and_jk(self):
        from game.battle import BattleGame
        from main import handle_character_key

        game = BattleGame(character_ids=("harry", "snape"))

        notice = handle_character_key(ord("f"), game)
        self.assertIn("P1", notice)
        self.assertEqual(game.players[0].character_id, "hermione")

        notice = handle_character_key(ord("j"), game)  # J cycles P2 left
        self.assertIn("P2", notice)
        self.assertEqual(game.players[1].character_id, "ron")

    def test_character_cycle_avoids_duplicate_selection(self):
        from game.battle import BattleGame
        from main import handle_character_key

        game = BattleGame(character_ids=("harry", "snape"))
        game.set_player_character(1, "harry")

        # P2 presses right (K). Should skip harry (already taken by P1).
        handle_character_key(ord("k"), game)
        self.assertEqual(game.players[1].character_id, "hermione")

    def test_non_character_key_returns_empty_notice(self):
        from game.battle import BattleGame
        from main import handle_character_key

        game = BattleGame()

        self.assertEqual(handle_character_key(ord("1"), game), "")
        self.assertEqual(handle_character_key(ord("z"), game), "")
        self.assertEqual(handle_character_key(ord("d"), game), "")

    def test_solo_mode_keeps_training_dummy_damage(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 64.0
        game.players[1].mana = 30.0
        game.winner = 0

        ModeRunner(GameMode.SOLO)._apply_rules(game)

        self.assertEqual(game.players[1].hp, 64.0)
        self.assertEqual(game.players[1].mana, 100.0)
        self.assertIsNone(game.winner)

    def test_solo_dummy_defeated_when_hp_zero(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 0.0
        game.winner = 0

        ModeRunner(GameMode.SOLO)._apply_rules(game)

        self.assertTrue(game.solo_dummy_defeated)
        self.assertIsNone(game.winner)

    def test_solo_dummy_not_defeated_when_hp_positive(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 50.0

        ModeRunner(GameMode.SOLO)._apply_rules(game)

        self.assertFalse(game.solo_dummy_defeated)

    def test_solo_dummy_defeated_persists_across_frames(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 0.0

        ModeRunner(GameMode.SOLO)._apply_rules(game)
        self.assertTrue(game.solo_dummy_defeated)

        ModeRunner(GameMode.SOLO)._apply_rules(game)
        self.assertTrue(game.solo_dummy_defeated)

    def test_reset_clears_solo_dummy_defeated(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 0.0
        ModeRunner(GameMode.SOLO)._apply_rules(game)
        self.assertTrue(game.solo_dummy_defeated)

        game.reset()
        self.assertFalse(game.solo_dummy_defeated)


if __name__ == "__main__":
    unittest.main()
