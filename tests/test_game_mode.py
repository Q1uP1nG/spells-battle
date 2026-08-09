import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GameModeTests(unittest.TestCase):
    # -- enter ----------------------------------------------------------------

    def test_solo_enter_resets_game_and_tracks(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner
        from models.cv_track import CVTrack, CastState

        game = BattleGame()
        game.solo_dummy_defeated = True

        class FakeCV:
            tracks = None

            @staticmethod
            def reset():
                pass

        runner = ModeRunner(GameMode.SOLO)
        runner.enter(game, FakeCV)

        self.assertFalse(game.solo_dummy_defeated)
        self.assertEqual(len(FakeCV.tracks), 2)
        self.assertIsInstance(FakeCV.tracks[0], CVTrack)
        self.assertIsNone(runner.pve_ai)

    def test_pve_enter_creates_pve_ai(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.PVE)
        runner.enter(game, FakeCV)

        self.assertIsNotNone(runner.pve_ai)
        self.assertTrue(runner.pve_paused)
        self.assertFalse(runner.pve_has_started)

    def test_duel_enter_no_pve_ai(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.DUEL)
        runner.enter(game, FakeCV)

        self.assertIsNone(runner.pve_ai)

    def test_solo_enter_randomizes_p2_character(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame(character_ids=("harry", "harry"))

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.SOLO)
        runner.enter(game, FakeCV())

        self.assertNotEqual(game.players[1].character_id, "harry")

    def test_cv_training_enter_randomizes_p1_character(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame(character_ids=("harry", "harry"))

        class FakeCV:
            tracks = None

            def begin_training_capture(self, target_spell, callback):
                pass

        runner = ModeRunner(GameMode.CV_TRAINING)
        runner.enter(game, FakeCV())

        self.assertNotEqual(game.players[0].character_id, "harry")

    def test_duel_enter_preserves_selected_characters(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame(character_ids=("ron", "hermione"))

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.DUEL)
        runner.enter(game, FakeCV())

        self.assertEqual(game.players[0].character_id, "ron")
        self.assertEqual(game.players[1].character_id, "hermione")

    def test_character_select_enter_randomizes_p2_for_pve(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame(character_ids=("harry", "harry"))

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.CHARACTER_SELECT)
        runner.pending_mode = GameMode.PVE
        runner.enter(game, FakeCV())

        self.assertNotEqual(game.players[1].character_id, "harry")

    def test_character_select_enter_does_not_change_characters_for_duel(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame(character_ids=("ron", "hermione"))

        class FakeCV:
            tracks = None

        runner = ModeRunner(GameMode.CHARACTER_SELECT)
        runner.pending_mode = GameMode.DUEL
        runner.enter(game, FakeCV())

        self.assertEqual(game.players[0].character_id, "ron")
        self.assertEqual(game.players[1].character_id, "hermione")

    # -- reset ----------------------------------------------------------------

    def test_reset_in_pve_calls_ai_reset(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        runner = ModeRunner(GameMode.PVE)
        runner.pve_ai = _FakeAI()
        runner.pve_paused = False
        runner.pve_has_started = True
        runner.reset(game)
        self.assertTrue(runner.pve_ai.was_reset)
        self.assertFalse(game.solo_dummy_defeated)
        self.assertTrue(runner.pve_paused)
        self.assertFalse(runner.pve_has_started)

    def test_reset_in_solo_no_crash(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.solo_dummy_defeated = True
        runner = ModeRunner(GameMode.SOLO)
        runner.reset(game)
        self.assertFalse(game.solo_dummy_defeated)

    # -- HUD properties -------------------------------------------------------

    def test_title(self):
        from game.mode import GameMode, ModeRunner

        self.assertEqual(ModeRunner(GameMode.SOLO).title, "SOLO SHOWCASE")
        self.assertEqual(ModeRunner(GameMode.DUEL).title, "DUEL BATTLE")
        self.assertEqual(ModeRunner(GameMode.PVE).title, "PVE BATTLE")
        self.assertEqual(ModeRunner(GameMode.CV_TRAINING).title, "CV BANK")
        self.assertEqual(ModeRunner(GameMode.CHARACTER_SELECT).title, "SELECT CHARACTERS")
        self.assertEqual(ModeRunner(GameMode.MENU).title, "")

    def test_show_solo_overlay(self):
        from game.mode import GameMode, ModeRunner

        self.assertTrue(ModeRunner(GameMode.SOLO).show_solo_overlay)
        self.assertTrue(ModeRunner(GameMode.PVE).show_solo_overlay)
        self.assertFalse(ModeRunner(GameMode.CV_TRAINING).show_solo_overlay)
        self.assertFalse(ModeRunner(GameMode.DUEL).show_solo_overlay)

    def test_force_player_index(self):
        from game.mode import GameMode, ModeRunner

        self.assertEqual(ModeRunner(GameMode.SOLO).force_player_index, 0)
        self.assertEqual(ModeRunner(GameMode.PVE).force_player_index, 0)
        self.assertEqual(ModeRunner(GameMode.CV_TRAINING).force_player_index, 0)
        self.assertIsNone(ModeRunner(GameMode.DUEL).force_player_index)

    def test_accepts_p2_keyboard(self):
        from game.mode import GameMode, ModeRunner

        self.assertTrue(ModeRunner(GameMode.DUEL).accepts_p2_keyboard)
        self.assertFalse(ModeRunner(GameMode.SOLO).accepts_p2_keyboard)
        self.assertFalse(ModeRunner(GameMode.PVE).accepts_p2_keyboard)
        self.assertFalse(ModeRunner(GameMode.CV_TRAINING).accepts_p2_keyboard)

    def test_pve_space_starts_then_pauses_and_resumes(self):
        from game.mode import GameMode, ModeRunner

        runner = ModeRunner(GameMode.PVE)
        runner.pve_paused = True
        runner.pve_has_started = False

        self.assertEqual(runner.toggle_pve_pause(), "PVE START")
        self.assertFalse(runner.pve_paused)
        self.assertTrue(runner.pve_has_started)

        self.assertEqual(runner.toggle_pve_pause(), "PVE PAUSED")
        self.assertTrue(runner.pve_paused)
        self.assertTrue(runner.pve_has_started)

        self.assertEqual(runner.toggle_pve_pause(), "PVE RESUME")
        self.assertFalse(runner.pve_paused)
        self.assertTrue(runner.pve_has_started)

    def test_pve_paused_update_runs_cv_without_casting_or_game_tick(self):
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            def __init__(self):
                self.updated = False
                self.update_kwargs = None

            def update(self, *_args, **_kwargs):
                self.updated = True
                self.update_kwargs = _kwargs

        class FakeGame:
            winner = None
            solo_dummy_defeated = False

            def __init__(self):
                self.updated = False

            def update(self, *_args):
                self.updated = True

        class FakeAI:
            def __init__(self):
                self.updated = False

            def update(self, *_args):
                self.updated = True

        runner = ModeRunner(GameMode.PVE)
        runner.pve_paused = True
        runner.pve_ai = FakeAI()
        game = FakeGame()
        cv = FakeCV()

        runner.update(None, game, cv, now=10.0, dt=0.05)

        self.assertTrue(cv.updated)
        self.assertEqual(cv.update_kwargs["force_player_index"], 0)
        self.assertFalse(cv.update_kwargs["allow_casting"])
        self.assertFalse(runner.pve_ai.updated)
        self.assertFalse(game.updated)

    def test_pve_footer_uses_space_for_pause_and_backspace_for_restart(self):
        from game.mode import GameMode, ModeRunner

        runner = ModeRunner(GameMode.PVE)
        runner.pve_paused = True
        self.assertIn("SPACE start", runner.footer_right)
        self.assertIn("Backspace restart", runner.footer_right)
        self.assertLessEqual(len(f"{runner.footer_left}   {runner.footer_right}"), 92)

        runner.pve_paused = False
        self.assertIn("SPACE pause", runner.footer_right)
        self.assertIn("Backspace restart", runner.footer_right)
        self.assertLessEqual(len(f"{runner.footer_left}   {runner.footer_right}"), 92)

    def test_tip_capture_mode_has_been_removed(self):
        from game.mode import GameMode

        self.assertFalse(hasattr(GameMode, "TIP_CAPTURE"))

    def test_cv_training_enter_enables_capture_mode(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner
        from models.cv_track import CVTrack

        class FakeCV:
            tracks = None
            capture_target = None
            callback = None

            def begin_training_capture(self, target_spell, callback):
                self.capture_target = target_spell
                self.callback = callback

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(progress_path=None),
        )
        runner.enter(BattleGame(), fake_cv)

        self.assertEqual(len(fake_cv.tracks), 2)
        self.assertIsInstance(fake_cv.tracks[0], CVTrack)
        self.assertEqual(fake_cv.capture_target, "incendio")
        self.assertIsNotNone(fake_cv.callback)

    def test_cv_training_enter_can_resume_saved_progress(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            progress_path.write_text(json.dumps({
                "schema": 1,
                "spell_order": ["incendio", "glacius"],
                "attempts_per_spell": 2,
                "accepted_counts": {"incendio": 2, "glacius": 1},
            }), encoding="utf-8")

            class FakeCV:
                tracks = None
                capture_target = None

                def begin_training_capture(self, target_spell, _callback):
                    self.capture_target = target_spell

            fake_cv = FakeCV()
            runner = ModeRunner(
                GameMode.CV_TRAINING,
                training_session_factory=lambda: CVTrainingSession(
                    spell_order=["incendio", "glacius"],
                    attempts_per_spell=2,
                    progress_path=progress_path,
                ),
            )

            runner.enter(BattleGame(), fake_cv)

            self.assertEqual(runner.training_session.accepted_counts["incendio"], 2)
            self.assertEqual(runner.training_session.accepted_counts["glacius"], 1)
            self.assertEqual(fake_cv.capture_target, "glacius")

    def test_cv_training_accept_logs_pending_sample_and_advances_attempt(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            def __init__(self):
                self.logged = []
                self.reset_states = []
                self.tracks = []

            def begin_training_capture(self, target_spell, callback):
                self.target_spell = target_spell
                self.callback = callback

            def log_gesture_event(self, event):
                self.logged.append(event)

            def reset_cv_track(self, track, state, detail):
                self.reset_states.append((state, detail))

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(progress_path=None),
        )
        runner.enter(BattleGame(), fake_cv)
        fake_cv.callback({"primary": {"spell": "incendio"}, "points": [[0, 0], [18, 0], [36, 0]]}, 0)

        notice = runner.handle_training_key(13, fake_cv)

        self.assertIn("SAVED", notice)
        self.assertEqual(len(fake_cv.logged), 1)
        self.assertEqual(fake_cv.logged[0]["intended_spell"], "incendio")
        self.assertEqual(runner.training_session.current_attempt_number, 2)
        self.assertEqual(fake_cv.reset_states[-1][0], "WAIT")

    def test_cv_training_discard_does_not_log_or_advance(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            def __init__(self):
                self.logged = []
                self.reset_states = []
                self.tracks = []

            def begin_training_capture(self, target_spell, callback):
                self.target_spell = target_spell
                self.callback = callback

            def log_gesture_event(self, event):
                self.logged.append(event)

            def reset_cv_track(self, track, state, detail):
                self.reset_states.append((state, detail))

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(progress_path=None),
        )
        runner.enter(BattleGame(), fake_cv)
        fake_cv.callback({"primary": {"spell": "incendio"}}, 0)

        notice = runner.handle_training_key(8, fake_cv)

        self.assertIn("DISCARDED", notice)
        self.assertEqual(fake_cv.logged, [])
        self.assertEqual(runner.training_session.current_attempt_number, 1)
        self.assertEqual(fake_cv.reset_states[-1][0], "WAIT")

    def test_cv_training_empty_sample_does_not_log_or_advance(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            def __init__(self):
                self.logged = []
                self.reset_states = []
                self.tracks = []

            def begin_training_capture(self, target_spell, callback):
                self.target_spell = target_spell
                self.callback = callback

            def log_gesture_event(self, event):
                self.logged.append(event)

            def reset_cv_track(self, track, state, detail):
                self.reset_states.append((state, detail))

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(progress_path=None),
        )
        runner.enter(BattleGame(), fake_cv)
        fake_cv.callback({"primary": {"spell": None}, "points": []}, 0)

        notice = runner.handle_training_key(13, fake_cv)

        self.assertEqual(notice, "EMPTY SAMPLE")
        self.assertEqual(fake_cv.logged, [])
        self.assertEqual(runner.training_session.current_attempt_number, 1)
        self.assertEqual(fake_cv.reset_states[-1], ("WAIT", "empty training sample"))

    def test_cv_training_relabel_uses_overload_not_protego_for_trajectory_samples(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            tracks = []

            def begin_training_capture(self, target_spell, callback):
                self.target_spell = target_spell
                self.callback = callback

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(progress_path=None),
        )
        runner.enter(BattleGame(), fake_cv)
        fake_cv.callback({"primary": {"spell": "incendio"}}, 0)

        notice = runner.handle_training_key(ord("7"), fake_cv)

        self.assertEqual(notice, "LABEL: OVR")
        self.assertEqual(runner.training_session.pending_label, "overload")

        notice = runner.handle_training_key(ord("9"), fake_cv)

        self.assertEqual(notice, "")
        self.assertEqual(runner.training_session.pending_label, "overload")

    def test_cv_training_slot_navigation_resyncs_capture_target(self):
        from game.battle import BattleGame
        from game.cv_training import CVTrainingSession
        from game.mode import GameMode, ModeRunner

        class FakeCV:
            tracks = []

            def __init__(self):
                self.targets = []

            def begin_training_capture(self, target_spell, callback):
                self.targets.append(target_spell)
                self.callback = callback

        fake_cv = FakeCV()
        runner = ModeRunner(
            GameMode.CV_TRAINING,
            training_session_factory=lambda: CVTrainingSession(
                spell_order=["incendio", "circle"],
                progress_path=None,
            ),
        )
        runner.enter(BattleGame(), fake_cv)

        slot_notice = runner.handle_training_key(ord("]"), fake_cv)
        spell_notice = runner.handle_training_key(ord("d"), fake_cv)

        self.assertIn("SLOT 2/30", slot_notice)
        self.assertIn("CIR", spell_notice)
        self.assertEqual(fake_cv.targets[-1], "circle")

    def test_duel_hud_allows_winner_overlay(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.solo_dummy_defeated = False

        self.assertIsNone(ModeRunner(GameMode.DUEL).solo_dummy_defeated_for_hud(game))

    def test_solo_and_pve_hud_use_dummy_defeated_flag(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.solo_dummy_defeated = True

        self.assertTrue(ModeRunner(GameMode.SOLO).solo_dummy_defeated_for_hud(game))
        self.assertTrue(ModeRunner(GameMode.PVE).solo_dummy_defeated_for_hud(game))

    def test_pve_hud_allows_winner_overlay_when_player_loses(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.winner = 1
        game.solo_dummy_defeated = False

        self.assertIsNone(ModeRunner(GameMode.PVE).solo_dummy_defeated_for_hud(game))

    # -- _apply_rules ---------------------------------------------------------

    def test_apply_rules_solo_refills_p2_mana(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].mana = 20.0
        game.winner = 0
        ModeRunner(GameMode.SOLO)._apply_rules(game)
        self.assertEqual(game.players[1].mana, 100.0)
        self.assertIsNone(game.winner)

    def test_apply_rules_pve_does_not_refill_p2_mana(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].mana = 20.0
        ModeRunner(GameMode.PVE)._apply_rules(game)
        self.assertEqual(game.players[1].mana, 20.0)

    def test_apply_rules_solo_sets_defeated_flag(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 0.0
        game.winner = 0
        self.assertFalse(game.solo_dummy_defeated)
        ModeRunner(GameMode.SOLO)._apply_rules(game)
        self.assertTrue(game.solo_dummy_defeated)


class _FakeAI:
    was_reset = False

    def reset(self):
        self.was_reset = True


if __name__ == "__main__":
    unittest.main()
