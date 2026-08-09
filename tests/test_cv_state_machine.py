import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CVStateMachineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _gesture_logger(self):
        from cv.gesture_log import GestureLogger

        return GestureLogger(log_dir=str(Path(self._tmp.name) / "cv_sessions"))

    def test_initial_state_is_idle(self):
        from models.cv_track import CVTrack, CastState

        track = CVTrack()
        self.assertEqual(track.state, CastState.IDLE)

    def test_reset_sets_state_to_idle(self):
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        track.state = CastState.RECORDING
        controller.reset_cv_track(track, "NO HAND", "show hand")
        self.assertEqual(track.state, CastState.IDLE)

    def test_reset_cast_state(self):
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        controller.reset_cv_track(track, "CAST", "incendio")
        self.assertEqual(track.state, CastState.CASTING)

    def test_reset_blocked_state(self):
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        controller.reset_cv_track(track, "BLOCKED", "no mana")
        self.assertEqual(track.state, CastState.WAIT)

    def test_reset_lost_hold_state(self):
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        controller.reset_cv_track(track, "LOST HOLD", "hand lost")
        self.assertEqual(track.state, CastState.LOST)

    def test_all_caststate_values_are_distinct(self):
        from models.cv_track import CastState

        values = [e.value for e in CastState]
        self.assertEqual(len(values), len(set(values)))

    def test_state_detail_is_set_by_reset(self):
        from models.cv_track import CVTrack
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        controller.reset_cv_track(track, "NO HAND", "camera lost")
        self.assertEqual(track.state_detail, "camera lost")

    # -- Classify state is set during evaluation -------------------------------

    def test_evaluate_sets_classify_state(self):
        import numpy as np
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False  # needed for evaluate_track_for_spell
        from cv.gesture_pipeline import GesturePipeline
        controller.gesture_pipeline = GesturePipeline()
        controller.gesture_logger = self._gesture_logger()
        track = CVTrack()
        # Build enough points to pass the length threshold
        for x in range(0, 260, 13):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))
        track.path_length = 260.0

        # Need a minimal game for player side lookup
        from game.battle import BattleGame
        game = BattleGame()

        controller.evaluate_track_for_spell(game, 0, track, 100.0, "detail", "TRACKING")
        # After evaluation, state should be CLASSIFY (or overridden to CASTING/WAIT)
        # Since we have enough points for incendio, it might cast. But CLASSIFY was set.
        self.assertIn(track.state, [CastState.CLASSIFY, CastState.CASTING, CastState.WAIT])

    def test_tracking_no_match_returns_to_recording_state(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False
        from cv.gesture_pipeline import GesturePipeline
        controller.gesture_pipeline = GesturePipeline()
        controller.gesture_logger = self._gesture_logger()
        track = CVTrack()
        track.state = CastState.RECORDING
        for x in range(0, 50, 10):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))

        controller.evaluate_track_for_spell(BattleGame(), 0, track, 10.0, "detail", "TRACKING")

        self.assertEqual(track.state, CastState.RECORDING)
        self.assertTrue(track.recording)

    def test_motion_gate_preserves_points_when_ready_to_classify(self):
        import numpy as np
        from config import CV_TRACK_TIMEOUT
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        track.state = CastState.RECORDING
        track.last_motion_time = 10.0
        track.idle_anchor = np.array([100.0, 100.0], dtype=np.float32)
        track.velocity = np.array([0.0, 0.0], dtype=np.float32)
        track.points.append(np.array([100.0, 100.0], dtype=np.float32))
        track.points.append(np.array([170.0, 100.0], dtype=np.float32))

        transition = controller.update_motion_gate(
            track,
            np.array([170.0, 100.0], dtype=np.float32),
            10.0 + CV_TRACK_TIMEOUT + 0.05,
        )

        self.assertTrue(transition.should_classify)
        self.assertEqual(transition.state, CastState.CLASSIFY)
        self.assertEqual(len(track.points), 2)

    def test_lost_hold_reacquire_continues_existing_gesture(self):
        import numpy as np
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        track.state = CastState.LOST
        track.idle_anchor = np.array([100.0, 300.0], dtype=np.float32)
        track.last_motion_time = 10.0
        track.velocity = np.array([0.0, 0.0], dtype=np.float32)
        track.points.append(np.array([100.0, 300.0], dtype=np.float32))
        track.points.append(np.array([150.0, 240.0], dtype=np.float32))
        before_points = [point.copy() for point in track.points]

        transition = controller.update_motion_gate(
            track,
            np.array([190.0, 250.0], dtype=np.float32),
            10.08,
        )

        self.assertTrue(transition.should_record)
        self.assertEqual(transition.state, CastState.RECORDING)
        self.assertEqual(len(track.points), len(before_points))
        for actual, expected in zip(track.points, before_points):
            self.assertTrue(np.array_equal(actual, expected))

    def test_tracking_updates_prediction_without_casting_mid_gesture(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False
        game = BattleGame()
        track = CVTrack()
        track.state = CastState.RECORDING
        track.idle_anchor = np.array([100.0, 300.0], dtype=np.float32)
        track.last_motion_time = 10.0
        track.velocity = np.array([260.0, 0.0], dtype=np.float32)
        for x in range(100, 250, 15):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))

        controller._process_tracked_point(
            track,
            game,
            0,
            np.array([265.0, 300.0], dtype=np.float32),
            "smooth 15px",
            10.10,
        )

        self.assertEqual(len(game.projectiles), 0)
        self.assertEqual(game.players[0].mana, 100.0)
        self.assertEqual(track.state, CastState.RECORDING)
        self.assertEqual(track.last_prediction, "INC")
        self.assertIn("CAND", track.debug_detail)

    def test_gesture_ended_allows_cast_after_recording(self):
        import numpy as np
        from config import CV_TRACK_TIMEOUT
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False
        from cv.gesture_pipeline import GesturePipeline
        controller.gesture_pipeline = GesturePipeline()
        controller.gesture_logger = self._gesture_logger()
        game = BattleGame()
        track = CVTrack()
        track.state = CastState.RECORDING
        track.idle_anchor = np.array([100.0, 300.0], dtype=np.float32)
        track.last_motion_time = 10.0
        track.velocity = np.array([0.0, 0.0], dtype=np.float32)
        for x in range(100, 280, 15):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))

        controller._process_tracked_point(
            track,
            game,
            0,
            np.array([266.0, 300.0], dtype=np.float32),
            "smooth 0px",
            10.0 + CV_TRACK_TIMEOUT + 0.05,
        )

        self.assertEqual(len(game.projectiles), 1)
        self.assertEqual(track.state, CastState.CASTING)

    def test_regular_player_hit_does_not_directly_clear_cv_track(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from models.projectile import Projectile

        game = BattleGame()
        track = CVTrack()
        track.state = CastState.RECORDING
        track.points.append(np.array([100.0, 300.0], dtype=np.float32))
        track.points.append(np.array([145.0, 300.0], dtype=np.float32))
        before_points = [point.copy() for point in track.points]
        proj = Projectile(
            owner=1,
            spell="incendio",
            pos=game.players[0].center(),
            vel=np.array([-760.0, 0.0], dtype=np.float32),
            radius=28,
            damage=22,
            color=(40, 130, 255),
        )

        game.apply_player_hit(game.players[0], proj, 10.0)

        self.assertEqual(len(track.points), 2)
        for actual, expected in zip(track.points, before_points):
            self.assertTrue(np.array_equal(actual, expected))

    def test_silence_block_clears_current_cv_track_with_clear_reason(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        game = BattleGame()
        game.players[0].silenced_until = 11.0
        track = CVTrack()
        track.state = CastState.RECORDING
        track.points.append(np.array([100.0, 300.0], dtype=np.float32))
        track.points.append(np.array([150.0, 300.0], dtype=np.float32))

        controller._process_tracked_point(
            track,
            game,
            0,
            np.array([180.0, 300.0], dtype=np.float32),
            "smooth 30px",
            10.0,
        )

        self.assertEqual(len(track.points), 0)
        self.assertEqual(track.debug_state, "WAIT")
        self.assertIn("SILENCE", track.debug_detail)

    def test_global_cooldown_block_clears_current_cv_track_with_clear_reason(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        game = BattleGame()
        game.players[0].global_cooldown_until = 10.5
        track = CVTrack()
        track.state = CastState.RECORDING
        track.points.append(np.array([100.0, 300.0], dtype=np.float32))
        track.points.append(np.array([150.0, 300.0], dtype=np.float32))

        controller._process_tracked_point(
            track,
            game,
            0,
            np.array([180.0, 300.0], dtype=np.float32),
            "smooth 30px",
            10.0,
        )

        self.assertEqual(len(track.points), 0)
        self.assertEqual(track.debug_state, "WAIT")
        self.assertIn("GCD", track.debug_detail)

    def test_gesture_log_includes_runtime_intent_and_attempt_id(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack
        from cv.controller import CVGestureController
        from cv.gesture_pipeline import GesturePipeline

        class CapturingLogger:
            def __init__(self):
                self.events = []

            def log_gesture(self, event):
                self.events.append(event)

        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False
        controller.input_mode = "finger"
        controller.gesture_pipeline = GesturePipeline()
        controller.gesture_logger = CapturingLogger()
        controller.intended_spell = "glacius"
        controller.gesture_attempt_id = 0

        track = CVTrack()
        for x in range(0, 260, 13):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))

        controller.evaluate_track_for_spell(BattleGame(), 0, track, 100.0, "detail", "CLASSIFY")

        self.assertEqual(len(controller.gesture_logger.events), 1)
        event = controller.gesture_logger.events[0]
        self.assertEqual(event["intended_spell"], "glacius")
        self.assertEqual(event["attempt_id"], 1)
        self.assertEqual(event["schema"], 1)
        self.assertEqual(event["shadow"]["method"], "normalized_heuristic_shadow")
        self.assertEqual(event["shadow"]["scale_source"], "trajectory_span_fallback")
        self.assertTrue(event["pipeline_version"].startswith("gesture-pipeline-v2"))
        self.assertTrue(event["agreement"])

    def test_training_capture_freezes_track_without_casting_or_logging(self):
        import numpy as np
        from game.battle import BattleGame
        from models.cv_track import CVTrack, CastState
        from cv.controller import CVGestureController
        from cv.gesture_pipeline import GesturePipeline

        class CapturingLogger:
            def __init__(self):
                self.events = []

            def log_gesture(self, event):
                self.events.append(event)

        captured = []
        controller = object.__new__(CVGestureController)
        controller.verbose_debug = False
        controller.input_mode = "finger"
        controller.gesture_pipeline = GesturePipeline()
        controller.gesture_logger = CapturingLogger()
        controller.gesture_attempt_id = 0
        controller.begin_training_capture("glacius", lambda event, track_index: captured.append((event, track_index)))

        game = BattleGame()
        track = CVTrack()
        track.state = CastState.RECORDING
        for x in range(0, 260, 13):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))

        did_cast = controller.evaluate_track_for_spell(game, 0, track, 100.0, "detail", "CLASSIFY")

        self.assertFalse(did_cast)
        self.assertEqual(len(game.projectiles), 0)
        self.assertEqual(controller.gesture_logger.events, [])
        self.assertEqual(len(captured), 1)
        event, track_index = captured[0]
        self.assertEqual(track_index, 0)
        self.assertEqual(event["intended_spell"], "glacius")
        self.assertEqual(event["primary"]["spell"], "incendio")
        self.assertTrue(event["training_mode"])
        self.assertEqual(event["shadow"]["method"], "normalized_heuristic_shadow")
        self.assertEqual(event["shadow"]["scale_source"], "trajectory_span_fallback")
        self.assertTrue(event["agreement"])
        self.assertEqual(track.debug_state, "REVIEW")
        self.assertEqual(track.state, CastState.WAIT)
        self.assertGreater(len(track.points), 0)

    def test_gesture_event_carries_available_v2_capture_metadata(self):
        from cv.controller import CVGestureController
        from cv.gesture_pipeline import ClassificationResult
        from models.cv_track import CVTrack

        controller = object.__new__(CVGestureController)
        controller.gesture_attempt_id = 0
        controller.input_mode = "wand"
        controller.intended_spell = "circle"
        controller.frame_width = 1280
        controller.frame_height = 720
        controller.fps_estimate = 59.5
        track = CVTrack()
        track.palm_scale = 123.25

        event = controller._gesture_log_event(
            now=10.0,
            side="left",
            points=[[0, 0], [10, 10]],
            result=ClassificationResult("stupefy", 0.9, "fused", "test"),
            cast_attempted=False,
            cast_success=False,
            debug_state="REVIEW",
            training_mode=True,
            track=track,
        )

        self.assertEqual(event["frame_width"], 1280)
        self.assertEqual(event["frame_height"], 720)
        self.assertEqual(event["fps_estimate"], 59.5)
        self.assertEqual(event["palm_scale"], 123.25)

    def test_describe_tracking_uses_short_hint_for_small_paths(self):
        import numpy as np
        from models.cv_track import CVTrack
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        for x in range(5):
            track.points.append(np.array([float(x), 300.0], dtype=np.float32))
        track.path_length = 24.0

        detail = controller.describe_tracking(track, None, 0.0, "smooth")

        self.assertIn("SHORT", detail)

    def test_describe_tracking_uses_direction_hint_for_no_match(self):
        import numpy as np
        from models.cv_track import CVTrack
        from cv.controller import CVGestureController

        controller = object.__new__(CVGestureController)
        track = CVTrack()
        for i in range(16):
            track.points.append(np.array([100.0 + i * 10.0, 300.0 + i * 10.0], dtype=np.float32))
        track.path_length = 220.0

        detail = controller.describe_tracking(track, None, 0.0, "smooth")

        self.assertIn("DIR/TURNS", detail)


if __name__ == "__main__":
    unittest.main()
