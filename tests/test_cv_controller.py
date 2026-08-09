import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CVControllerPalmGateTests(unittest.TestCase):
    def test_cast_cv_spell_submits_through_bound_session(self):
        from game.commands import CastIntent, CastSubmission
        from models.cv_track import CVTrack

        class FakeSession:
            def __init__(self, game):
                self.game = game
                self.calls = []

            def request_cast(self, **kwargs):
                self.calls.append(kwargs)
                intent = CastIntent(
                    spell=kwargs["spell"],
                    sequence=1,
                    client_time_ms=int(kwargs["now"] * 1000),
                    source=kwargs["source"],
                )
                return CastSubmission(intent=intent, accepted=True)

        class FakeGame:
            players = [SimpleNamespace(side="left", last_message="")]

            def cast_spell(self, *_args):
                raise AssertionError("CV must not call BattleGame.cast_spell directly")

        game = FakeGame()
        session = FakeSession(game)
        controller = self.make_controller()
        controller.allow_casting = True
        controller.battle_session = session
        track = CVTrack()

        did_cast = controller.cast_cv_spell(
            game, 0, track, "incendio", confidence=0.95, now=12.0,
        )

        self.assertTrue(did_cast)
        self.assertEqual(session.calls, [{
            "player_index": 0,
            "spell": "incendio",
            "now": 12.0,
            "source": "cv",
        }])

    def make_controller(self):
        from cv.controller import CVGestureController

        return object.__new__(CVGestureController)

    def make_track(self):
        from models.cv_track import CVTrack

        track = CVTrack()
        track.last_valid_point = np.array([100.0, 100.0], dtype=np.float32)
        track.last_valid_time = 10.0
        return track

    def test_fast_open_palm_does_not_consume_motion_gesture(self):
        controller = self.make_controller()
        track = self.make_track()
        moving_point = np.array([100.0, 260.0], dtype=np.float32)

        consume, detail = controller.should_consume_open_palm(track, 0.95, moving_point, 10.16)

        self.assertFalse(consume)
        self.assertEqual(track.open_palm_since, 0.0)
        self.assertIn("moving", detail)

    def test_stable_open_palm_consumes_for_protego_hold(self):
        controller = self.make_controller()
        track = self.make_track()
        stable_point = np.array([104.0, 103.0], dtype=np.float32)

        consume, detail = controller.should_consume_open_palm(track, 0.95, stable_point, 10.16)

        self.assertTrue(consume)
        self.assertIn("stable", detail)

    def test_wand_overlay_hint_explains_uncalibrated_center_circle(self):
        controller = self.make_controller()

        class FakeWand:
            is_calibrated = False

        controller.wand_detector = FakeWand()

        self.assertIn("CENTER", controller.wand_overlay_hint())
        self.assertIn("C", controller.wand_overlay_hint())

    def test_wand_overlay_hint_explains_p1_locked_when_calibrated(self):
        controller = self.make_controller()

        class FakeTrack:
            wand_color_calibrated = True
            wand_color_bgr = (0, 255, 255)

        controller.tracks = [FakeTrack(), FakeTrack()]

        self.assertIn("P1", controller.wand_overlay_hint())

    def test_toggle_cycles_only_finger_and_bright_wand(self):
        controller = self.make_controller()

        controller.available = True
        controller.wand_detector = type("Fake", (), {"is_calibrated": False})()
        controller.input_mode = "finger"
        self.assertEqual(controller.toggle_input_mode(), "wand")
        self.assertEqual(controller.toggle_input_mode(), "finger")

    def test_plain_wand_is_not_a_public_input_mode(self):
        from cv.controller import INPUT_MODES

        self.assertEqual(INPUT_MODES, ("finger", "wand"))
        self.assertNotIn("plain_wand", INPUT_MODES)

    def test_default_gesture_pipeline_falls_back_without_template_model(self):
        from cv.controller import create_default_gesture_pipeline
        from cv.gesture_pipeline import FusedGestureClassifier, HeuristicGestureClassifier
        from cv.hybrid_classifier import HybridTemplateGestureClassifier

        pipeline = create_default_gesture_pipeline(data_template_path="missing-template-file.json")

        self.assertNotIsInstance(pipeline.primary, HybridTemplateGestureClassifier)
        self.assertIsInstance(pipeline.primary, (FusedGestureClassifier, HeuristicGestureClassifier))

    def test_default_gesture_pipeline_uses_fused_primary_when_template_model_exists(self):
        from cv.controller import create_default_gesture_pipeline
        from cv.gesture_pipeline import FusedGestureClassifier
        from cv.template_classifier import _normalize_trajectory

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            points = [[100, 300], [180, 300], [260, 300], [340, 300]]
            payload = {
                "version": 1,
                "target_point_count": 32,
                "prototypes": {"incendio": [_normalize_trajectory(points).tolist()]},
                "thresholds": {"incendio": 0.25},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

            pipeline = create_default_gesture_pipeline(data_template_path=template_path)

        self.assertIsInstance(pipeline.primary, FusedGestureClassifier)
        self.assertIn("cyclic_template", pipeline.shadows)
        self.assertTrue(pipeline.shadows["cyclic_template"].enable_cyclic_stupefy)

    def test_preview_and_final_use_same_pipeline_and_version(self):
        from cv.gesture_pipeline import ClassificationResult, PipelineClassification
        from models.cv_track import CVTrack

        class RecordingPipeline:
            version = "shared-test-pipeline"

            def __init__(self):
                self.calls = []

            def classify_both(self, points, side, context):
                self.calls.append((list(points), side, context.purpose))
                return PipelineClassification(
                    primary=ClassificationResult("lumos", 0.9, "shared", "same"),
                    shadows={},
                    pipeline_version=self.version,
                    purpose=context.purpose,
                )

        controller = self.make_controller()
        controller.gesture_pipeline = RecordingPipeline()
        controller.input_mode = "finger"
        controller.frame_width = 1280
        controller.frame_height = 720
        controller.fps_estimate = 60.0
        track = CVTrack()
        points = [[0, 100], [0, 0]]

        preview = controller._run_gesture_pipeline(points, "left", track, "preview")
        final = controller._run_gesture_pipeline(points, "left", track, "final")

        self.assertEqual(preview.pipeline_version, final.pipeline_version)
        self.assertEqual(preview.primary, final.primary)
        self.assertEqual([call[2] for call in controller.gesture_pipeline.calls], ["preview", "final"])

    def test_cyclic_primary_requires_explicit_promotion_switch(self):
        from cv.controller import create_default_gesture_pipeline
        from cv.gesture_pipeline import StupefyCyclicOverlayClassifier
        from cv.template_classifier import _normalize_trajectory

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            points = [[100, 300], [180, 300], [260, 300], [340, 300]]
            payload = {
                "version": 2,
                "target_point_count": 32,
                "prototypes": {
                    "incendio": [{
                        "prototype_id": "inc-1",
                        "points": _normalize_trajectory(points).tolist(),
                    }],
                },
                "thresholds": {"incendio": 0.25},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            baseline = create_default_gesture_pipeline(
                data_template_path=template_path,
                use_cyclic_stupefy_primary=False,
            )
            promoted = create_default_gesture_pipeline(
                data_template_path=template_path,
                use_cyclic_stupefy_primary=True,
            )

        self.assertNotIsInstance(baseline.primary.template, StupefyCyclicOverlayClassifier)
        self.assertIsInstance(promoted.primary.template, StupefyCyclicOverlayClassifier)

    def test_legacy_plain_wand_status_falls_back_to_finger(self):
        controller = self.make_controller()
        controller.available = True
        controller.wand_detector = type("Fake", (), {"is_calibrated": False})()
        controller.input_mode = "plain_wand"
        controller.refresh_status()

        self.assertEqual(controller.input_mode, "finger")
        self.assertIn("FINGER", controller.status)

    def test_wand_mode_open_palm_casts_protego_before_wand_detection(self):
        from config import CV_PALM_HOLD_TIME
        from cv.controller import CVGestureController
        from models.cv_track import CVTrack

        class WandDetectorShouldNotRun:
            def detect_tip(self, *_args):
                raise AssertionError("wand detector should not run while open palm is consumed")

        class FakeGame:
            def __init__(self):
                self.players = [
                    SimpleNamespace(
                        side="left",
                        last_message="",
                        silenced_until=0.0,
                        spell_cooldown_until={"protego": 0.0},
                    )
                ]
                self.cast_spells = []

            def can_cast(self, _player_index, spell, _now):
                self.checked_spell = spell
                return True, "OK"

            def cast_spell(self, _player_index, spell, _now):
                self.cast_spells.append(spell)
                return True

        coords = [
            (0.50, 0.72),
            (0.47, 0.66), (0.45, 0.60), (0.43, 0.54), (0.41, 0.48),
            (0.44, 0.62), (0.37, 0.52), (0.31, 0.41), (0.25, 0.29),
            (0.50, 0.58), (0.50, 0.47), (0.50, 0.35), (0.50, 0.23),
            (0.56, 0.62), (0.63, 0.52), (0.69, 0.41), (0.75, 0.29),
            (0.61, 0.66), (0.70, 0.58), (0.79, 0.50), (0.88, 0.42),
        ]
        hand_landmarks = [SimpleNamespace(x=x, y=y) for x, y in coords]

        controller = self.make_controller()
        controller.input_mode = "wand"
        controller.wand_detector = WandDetectorShouldNotRun()
        track = CVTrack()
        now = 10.0
        track.open_palm_since = now - CV_PALM_HOLD_TIME - 0.01
        game = FakeGame()

        controller._process_hand_landmarks(
            hand_landmarks,
            track=track,
            game=game,
            player_index=0,
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            now=now,
            w=320,
            h=240,
        )

        self.assertEqual(game.cast_spells, ["protego"])
        self.assertEqual(track.debug_state, "CAST")

    def test_wand_point_gate_rejects_coasting_prediction(self):
        from models.cv_track import CVTrack

        controller = self.make_controller()
        track = CVTrack()
        track.wand_tracker_state = "COASTING"
        track.wand_tracker_source = "prediction"
        track.wand_tracker_confidence = 0.32

        point, detail = controller._gate_wand_point(
            track,
            np.array([120.0, 80.0], dtype=np.float32),
            "wand coasting conf 0.32",
        )

        self.assertIsNone(point)
        self.assertIn("weak point gate", detail)

    def test_wand_point_gate_allows_coasting_to_continue_active_track(self):
        from models.cv_track import CVTrack, CastState

        controller = self.make_controller()
        track = CVTrack()
        track.state = CastState.RECORDING
        track.points.append(np.array([95.0, 80.0], dtype=np.float32))
        track.wand_tracker_state = "COASTING"
        track.wand_tracker_source = "prediction"
        track.wand_tracker_confidence = 0.32

        point, detail = controller._gate_wand_point(
            track,
            np.array([120.0, 80.0], dtype=np.float32),
            "wand coasting conf 0.32",
        )

        self.assertIsNotNone(point)
        self.assertNotIn("weak point gate", detail)

    def test_wand_hold_missing_point_uses_longer_bridge_than_finger(self):
        from config import CV_LOST_HOLD_TIME
        from models.cv_track import CVTrack

        controller = self.make_controller()
        track = CVTrack()
        track.points.append(np.array([95.0, 80.0], dtype=np.float32))
        track.last_valid_point = np.array([95.0, 80.0], dtype=np.float32)
        track.last_valid_time = 10.0

        controller.input_mode = "finger"
        self.assertFalse(
            controller.hold_missing_point(
                track, 10.0 + CV_LOST_HOLD_TIME + 0.06, "no tip", 320, 240,
            )
        )

        track.missed_frames = 0
        controller.input_mode = "wand"
        self.assertTrue(
            controller.hold_missing_point(
                track, 10.0 + CV_LOST_HOLD_TIME + 0.06, "no wand", 320, 240,
            )
        )

    def test_wand_missing_point_holds_without_immediate_classification(self):
        from config import WAND_LOST_HOLD_TIME
        from models.cv_track import CVTrack

        class FakeGame:
            def __init__(self):
                self.players = [SimpleNamespace(side="left", last_message="")]
                self.winner = None
                self.cast_spells = []

            def cast_spell(self, _player_index, spell, _now):
                self.cast_spells.append(spell)
                return True

        class FakeMissingWand:
            def detect_tip(self, _frame, _hand_landmarks, _track, _now, _w, _h):
                return None, "lost marker"

        controller = self.make_controller()
        controller.input_mode = "wand"
        controller.verbose_debug = False
        controller.wand_detector = FakeMissingWand()
        controller.gesture_pipeline = SimpleNamespace(
            classify=lambda _points, _side: SimpleNamespace(
                spell="incendio",
                confidence=0.99,
                method="test",
                reason="test",
                features=None,
            )
        )
        track = CVTrack()
        track.points.append(np.array([95.0, 80.0], dtype=np.float32))
        track.points.append(np.array([130.0, 80.0], dtype=np.float32))
        track.last_valid_point = np.array([130.0, 80.0], dtype=np.float32)
        track.last_valid_time = 10.0
        game = FakeGame()
        hand_landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]

        controller._process_hand_landmarks(
            hand_landmarks,
            track=track,
            game=game,
            player_index=0,
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            now=10.10,
            w=320,
            h=240,
        )

        self.assertEqual(game.cast_spells, [])
        self.assertEqual(track.debug_state, "LOST HOLD")

        controller._process_hand_landmarks(
            hand_landmarks,
            track=track,
            game=game,
            player_index=0,
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            now=10.0 + WAND_LOST_HOLD_TIME + 0.01,
            w=320,
            h=240,
        )

        self.assertEqual(game.cast_spells, ["incendio"])

    def test_wand_mode_logs_rejected_coasting_without_recording_point(self):
        from models.cv_track import CVTrack

        class FakeCoastingWand:
            def detect_tip(self, _frame, _hand_landmarks, track, _now, _w, _h):
                track.wand_tracker_state = "COASTING"
                track.wand_tracker_source = "prediction"
                track.wand_tracker_confidence = 0.32
                track.wand_tracker_debug = {
                    "state": "COASTING",
                    "source": "prediction",
                    "confidence": 0.32,
                    "reject_reason": "",
                    "point": [120.0, 80.0],
                }
                return np.array([120.0, 80.0], dtype=np.float32), "wand coasting conf 0.32"

        class CapturingWandDebugLogger:
            def __init__(self):
                self.events = []

            def log_event(self, event):
                self.events.append(event)

        controller = self.make_controller()
        controller.input_mode = "wand"
        controller.wand_detector = FakeCoastingWand()
        controller.wand_debug_logger = CapturingWandDebugLogger()
        track = CVTrack()
        game = SimpleNamespace(players=[SimpleNamespace(side="left")], winner=None)
        hand_landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(21)]

        controller._process_hand_landmarks(
            hand_landmarks,
            track=track,
            game=game,
            player_index=0,
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            now=10.0,
            w=320,
            h=240,
        )

        self.assertEqual(len(track.points), 0)
        self.assertEqual(track.debug_state, "NO WAND")
        self.assertEqual(len(controller.wand_debug_logger.events), 1)
        event = controller.wand_debug_logger.events[0]
        self.assertFalse(event["accepted_for_track"])
        self.assertEqual(event["state"], "COASTING")
        self.assertEqual(event["source"], "prediction")

    def test_wand_debug_logger_records_jump_bucket_changes_inside_interval(self):
        from models.cv_track import CVTrack

        class CapturingWandDebugLogger:
            def __init__(self):
                self.events = []

            def log_event(self, event):
                self.events.append(event)

        controller = self.make_controller()
        controller.wand_debug_logger = CapturingWandDebugLogger()
        track = CVTrack()
        track.wand_tracker_state = "LOST"
        track.wand_tracker_source = "none"
        track.wand_tracker_confidence = 0.0

        track.wand_tracker_debug = {
            "state": "LOST",
            "source": "none",
            "confidence": 0.0,
            "reject_reason": "jump",
            "observation_jump": 110.0,
        }
        controller._log_wand_debug_sample(
            track, 10.00, 0, None, "NO WAND: jump 110 > limit 90", False,
        )

        track.wand_tracker_debug = {
            "state": "LOST",
            "source": "none",
            "confidence": 0.0,
            "reject_reason": "jump",
            "observation_jump": 285.0,
        }
        controller._log_wand_debug_sample(
            track, 10.05, 0, None, "NO WAND: jump 285 > limit 90", False,
        )

        self.assertEqual(len(controller.wand_debug_logger.events), 2)

    def test_duel_wand_assignment_keeps_same_color_markers_distinct(self):
        import cv2

        from cv.wand_detector import WandDetector
        from models.cv_track import CVTrack

        def bgr_from_hsv(hue, saturation=255, value=255):
            hsv = np.uint8([[[hue, saturation, value]]])
            return tuple(int(c) for c in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])

        def shifted_hand(dx):
            coords = [
                (0.50, 0.50), (0.48, 0.45), (0.47, 0.42), (0.47, 0.39), (0.46, 0.36),
                (0.45, 0.46), (0.43, 0.41), (0.42, 0.36), (0.41, 0.31),
                (0.53, 0.43), (0.54, 0.38), (0.55, 0.33), (0.56, 0.28),
                (0.57, 0.45), (0.58, 0.40), (0.59, 0.35), (0.60, 0.30),
                (0.61, 0.48), (0.62, 0.43), (0.63, 0.38), (0.64, 0.33),
            ]
            return [SimpleNamespace(x=x + dx, y=y) for x, y in coords]

        width, height = 640, 360
        marker_color = bgr_from_hsv(30)
        detector = WandDetector()
        calibration = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.circle(calibration, (width // 2, height // 2), 10, marker_color, -1)
        self.assertTrue(detector.calibrate(calibration)[0])

        frame = np.zeros((height, width, 3), dtype=np.uint8)
        left_marker = np.array([280.0, 120.0], dtype=np.float32)
        right_marker = np.array([360.0, 120.0], dtype=np.float32)
        cv2.circle(frame, tuple(left_marker.astype(int)), 8, marker_color, -1)
        cv2.circle(frame, tuple(right_marker.astype(int)), 13, marker_color, -1)

        controller = self.make_controller()
        controller.input_mode = "wand"
        controller.wand_detector = detector
        controller.tracks = [CVTrack(), CVTrack()]
        hand_entries = [
            {"player_index": 0, "hand_landmarks": shifted_hand(-0.06), "track": controller.tracks[0]},
            {"player_index": 1, "hand_landmarks": shifted_hand(0.06), "track": controller.tracks[1]},
        ]

        assignments = controller._assign_wand_preferred_points(frame, hand_entries, 10.0, width, height)

        self.assertIn(0, assignments)
        self.assertIn(1, assignments)
        self.assertLess(np.linalg.norm(assignments[0] - left_marker), 12.0)
        self.assertLess(np.linalg.norm(assignments[1] - right_marker), 12.0)
        self.assertGreater(np.linalg.norm(assignments[0] - assignments[1]), 40.0)

    def test_wand_assignment_gives_moderate_weight_to_player_half(self):
        controller = self.make_controller()
        context = {
            "ok": True,
            "player_index": 0,
            "palm_center": np.array([320.0, 180.0], dtype=np.float32),
            "palm_scale": 80.0,
            "predicted": None,
        }
        left_half_candidate = {
            "point": [250.0, 140.0],
            "score": 0.70,
        }
        right_half_candidate = {
            "point": [390.0, 140.0],
            "score": 0.79,
        }

        left_score = controller._score_wand_assignment(context, left_half_candidate, [context], 640)
        right_score = controller._score_wand_assignment(context, right_half_candidate, [context], 640)

        self.assertGreater(left_score, right_score)

    def test_no_wand_reset_preserves_candidate_history_for_stable_relock(self):
        from cv.wand_tracking import WandCandidateHistory
        from models.cv_track import CVTrack

        controller = self.make_controller()
        track = CVTrack()
        history = WandCandidateHistory(maxlen=5)
        history.add(np.array([760.0, 520.0], dtype=np.float32), 0.57, 360.0, "blob", 10.0)
        track.wand_candidate_history = history

        controller.reset_cv_track(track, "NO WAND", "unstable")

        self.assertIs(track.wand_candidate_history, history)
        self.assertEqual(len(track.wand_candidate_history.samples), 1)

    def test_allow_casting_false_blocks_cv_spell_without_calling_game(self):
        from models.cv_track import CVTrack

        class FakeGame:
            def __init__(self):
                self.players = [SimpleNamespace(side="left", last_message="")]
                self.cast_spells = []

            def cast_spell(self, _player_index, spell, _now):
                self.cast_spells.append(spell)
                return True

        controller = self.make_controller()
        controller.allow_casting = False
        track = CVTrack()
        game = FakeGame()

        did_cast = controller.cast_cv_spell(game, 0, track, "incendio", 0.9, 10.0)

        self.assertFalse(did_cast)
        self.assertEqual(game.cast_spells, [])
        self.assertEqual(track.debug_state, "PAUSED")
        self.assertEqual(track.last_prediction, "INC")


class CVControllerDuelSplitTests(unittest.TestCase):
    def make_controller(self):
        from cv.controller import CVGestureController

        return object.__new__(CVGestureController)

    def hands(self, *xs):
        return [[SimpleNamespace(x=x, y=0.5)] for x in xs]

    def test_forced_player_index_overrides_position(self):
        controller = self.make_controller()
        indices = controller._resolve_player_indices(self.hands(0.1, 0.9), w=1000, force_player_index=0)
        self.assertEqual(indices, [0, 0])

    def test_single_hand_uses_screen_half(self):
        controller = self.make_controller()
        self.assertEqual(controller._resolve_player_indices(self.hands(0.2), 1000, None), [0])
        self.assertEqual(controller._resolve_player_indices(self.hands(0.8), 1000, None), [1])

    def test_two_hands_on_same_half_are_split_across_players(self):
        controller = self.make_controller()
        # Both wrists sit on the left half but are far apart -> force the split.
        indices = controller._resolve_player_indices(self.hands(0.15, 0.45), 1000, None)
        self.assertEqual(indices, [0, 1])

    def test_two_close_hands_are_not_split(self):
        controller = self.make_controller()
        # Two fingers of one person sitting close together stay on the same half.
        indices = controller._resolve_player_indices(self.hands(0.18, 0.22), 1000, None)
        self.assertEqual(indices, [0, 0])

    def test_split_respects_left_right_order_not_detection_order(self):
        controller = self.make_controller()
        indices = controller._resolve_player_indices(self.hands(0.9, 0.1), 1000, None)
        self.assertEqual(indices, [1, 0])

    def test_owns_side_keeps_hand_deeper_in_its_half(self):
        controller = self.make_controller()
        # Player 0 owns the left half: smaller x is more owned.
        self.assertTrue(controller._hand_owns_side_better(100, 300, 0, 1000))
        self.assertFalse(controller._hand_owns_side_better(300, 100, 0, 1000))
        # Player 1 owns the right half: larger x wins.
        self.assertTrue(controller._hand_owns_side_better(900, 600, 1, 1000))
        self.assertFalse(controller._hand_owns_side_better(600, 900, 1, 1000))


if __name__ == "__main__":
    unittest.main()
