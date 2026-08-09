import math
from collections import namedtuple

import cv2
import numpy as np

from config import (
    CV_LOST_HOLD_TIME,
    CV_PALM_CONFIDENCE,
    CV_PALM_HOLD_TIME,
    CV_PALM_MAX_CAST_SPEED,
    CV_TRACK_TIMEOUT,
    DUEL_FORCE_SPLIT,
    DUEL_SPLIT_MIN_SEPARATION_FRAC,
    HEIGHT,
    SPELLS,
    WAND_CALIBRATION_RADIUS,
    WAND_LOST_HOLD_TIME,
    WIDTH,
)
from cv.gesture_classifier import classify_cv_gesture, cv_path_length, diagnose_cv_gesture
from cv.gesture_log import GestureLogger
from cv.gesture_pipeline import FusedGestureClassifier, GesturePipeline, HeuristicGestureClassifier
from cv.hand_tracker import ensure_hand_model, get_hand_landmark_list
from cv.hybrid_classifier import RuntimeTemplateClassifier
from cv.template_classifier import DataTemplateClassifier
from cv.wand_debug_log import WandDebugLogger
from cv.wand_detector import WandDetector
from game.cv_training import TRAINING_LABELS
from game.session import LocalBattleSession
from models.cv_track import CVTrack, CastState
from renderer.text import draw_cv_text

# Transition result from motion-gate / classification steps
CVTransition = namedtuple("CVTransition", ["state", "should_record", "should_classify", "reason"])

INPUT_MODES = ("finger", "wand")
WAND_DEBUG_LOG_INTERVAL = 0.25
USE_ZZJ_FUSED_PRIMARY = True
WAND_TRACK_ACCEPT_CONFIDENCE = {
    "LOCKED": 0.50,
    "FLOW": 0.20,
    "COASTING": 0.30,
}
WAND_ASSIGNMENT_DUPLICATE_RADIUS = 30.0
WAND_HALF_FIELD_BIAS_SCALE = 56.0
WAND_HALF_FIELD_BIAS_LIMIT = 28.0


def _set_track_state(track, state, debug_state, detail):
    """Centralised setter for CVTrack state fields."""
    track.state = state
    track.state_detail = detail
    track.debug_state = debug_state
    track.debug_detail = detail


def create_default_gesture_pipeline(data_template_path=None, use_fused_primary=USE_ZZJ_FUSED_PRIMARY):
    primary = HeuristicGestureClassifier()
    if use_fused_primary:
        template = DataTemplateClassifier(template_path=data_template_path)
        if not template.loaded:
            template = RuntimeTemplateClassifier()
        if template.loaded:
            primary = FusedGestureClassifier(template=template)
        else:
            primary = HeuristicGestureClassifier()
    return GesturePipeline(primary=primary)


class CVGestureController:
    def __init__(self, gesture_logger=None, wand_debug_logger=None, battle_session=None):
        self.available = False
        self.input_mode = "finger"
        self.verbose_debug = False
        self.base_status = "MediaPipe Tasks"
        self.status = "CV OFF"
        self.detail_status = "CV OFF"
        self.tracks = [CVTrack(), CVTrack()]
        self.backend = None
        self.mp = None
        self.detector = None
        self.hands = None
        self.wand_detector = WandDetector()
        self.wand_debug_logger = (
            wand_debug_logger if wand_debug_logger is not None else WandDebugLogger()
        )
        self.gesture_pipeline = create_default_gesture_pipeline()
        self.gesture_logger = gesture_logger if gesture_logger is not None else GestureLogger()
        self.battle_session = battle_session
        self.intended_spell = None
        self.gesture_attempt_id = 0
        self.training_capture_enabled = False
        self.training_review_callback = None
        self.allow_casting = True

        try:
            import mediapipe as mp

            self.mp = mp
            self._init_tasks_hand_landmarker(mp)
            self.available = True
            self.refresh_status()
            self.detail_status = self.status
        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:90]
            if exc.__class__.__name__ == "ModuleNotFoundError" and "mediapipe" in detail:
                self.status = "CV OFF: install mediapipe"
            else:
                self.status = "CV OFF: " + exc.__class__.__name__
            self.detail_status = f"{self.status} | {detail}"

    def refresh_status(self):
        if self.available:
            if self.input_mode not in INPUT_MODES:
                self.input_mode = "finger"
            base_status = getattr(self, "base_status", "MediaPipe Tasks")
            if self.input_mode == "wand":
                p0 = self.tracks[0].wand_color_calibrated if len(self.tracks) > 0 else False
                p1 = self.tracks[1].wand_color_calibrated if len(self.tracks) > 1 else False
                if p0 and p1:
                    lock = "P1+P2 LOCKED"
                elif p0:
                    lock = "P1 LOCKED"
                else:
                    lock = "PRESS C"
                self.status = f"CV WAND {lock}: {base_status}"
            else:
                self.status = f"CV FINGER: {base_status}"

    def toggle_input_mode(self):
        index = INPUT_MODES.index(self.input_mode)
        self.input_mode = INPUT_MODES[(index + 1) % len(INPUT_MODES)]
        self.tracks = [CVTrack(), CVTrack()]
        self.refresh_status()
        return self.input_mode

    def calibrate_wand_color(self, frame, player_index=0):
        track = self.tracks[player_index] if player_index < len(self.tracks) else None
        ok, message = self.wand_detector.calibrate(frame, track=track)
        if ok:
            if player_index == 0:
                self.tracks = [CVTrack(), CVTrack()]
                self.tracks[0].wand_hue = self.wand_detector.wand_hue
                self.tracks[0].wand_sat_min = self.wand_detector.wand_sat_min
                self.tracks[0].wand_val_min = self.wand_detector.wand_val_min
                self.tracks[0].wand_color_bgr = self.wand_detector.wand_color_bgr
            self.refresh_status()
        return ok, message

    def set_intended_spell(self, spell):
        if spell is not None and spell not in SPELLS and spell not in TRAINING_LABELS:
            raise ValueError(f"Unknown spell intent: {spell}")
        self.intended_spell = spell
        return self.intended_spell

    def begin_training_capture(self, target_spell, review_callback):
        self.set_intended_spell(target_spell)
        self.training_capture_enabled = True
        self.training_review_callback = review_callback

    def end_training_capture(self):
        self.training_capture_enabled = False
        self.training_review_callback = None
        self.intended_spell = None

    def _next_gesture_attempt_id(self):
        attempt_id = getattr(self, "gesture_attempt_id", 0) + 1
        self.gesture_attempt_id = attempt_id
        return attempt_id

    def _gesture_log_event(self, now, side, points, result, cast_attempted,
                           cast_success, debug_state, block_reason="", training_mode=False):
        return {
            "schema": 1,
            "attempt_id": self._next_gesture_attempt_id(),
            "timestamp": now,
            "mode": getattr(self, "input_mode", "unknown"),
            "intended_spell": getattr(self, "intended_spell", None),
            "training_mode": training_mode,
            "side": side,
            "points": points,
            "path_length": cv_path_length(points),
            "primary": {"spell": result.spell,
                        "confidence": result.confidence,
                        "method": result.method,
                        "reason": result.reason},
            "cast_attempted": cast_attempted,
            "cast_success": cast_success,
            "block_reason": block_reason,
            "debug_state": debug_state,
        }

    def _log_gesture_event(self, event):
        try:
            self.gesture_logger.log_gesture(event)
        except Exception:
            pass

    def log_gesture_event(self, event):
        self._log_gesture_event(event)

    def _init_tasks_hand_landmarker(self, mp):
        model_path = ensure_hand_model()
        BaseOptions = mp.tasks.BaseOptions
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.65,
            min_tracking_confidence=0.65,
        )
        self.detector = HandLandmarker.create_from_options(options)
        self.backend = "tasks"

    def update(self, frame, game, now, force_player_index=None, allow_casting=True):
        self.allow_casting = allow_casting
        if not self.available:
            return

        mp_frame = cv2.convertScaleAbs(frame, alpha=1.35, beta=28)
        rgb = cv2.cvtColor(mp_frame, cv2.COLOR_BGR2RGB)
        results = self._detect(rgb, now)
        seen_players = set()
        hand_list = get_hand_landmark_list(results)
        h, w = frame.shape[:2]
        if hand_list:
            player_indices = self._resolve_player_indices(hand_list, w, force_player_index)
            # At most one hand per player: each track is a single player's
            # gesture trail.  When two hands resolve to the same player (e.g. one
            # person showing two fingers) keep only the one most clearly inside
            # that player's half so the trail never gets silently overwritten.
            entries_by_player = {}
            for hand_landmarks, player_index in zip(hand_list, player_indices):
                wrist_x = hand_landmarks[0].x * w
                candidate = {
                    "hand_landmarks": hand_landmarks,
                    "track": self.tracks[player_index],
                    "player_index": player_index,
                    "wrist_x": wrist_x,
                }
                existing = entries_by_player.get(player_index)
                if existing is None or self._hand_owns_side_better(
                    candidate["wrist_x"], existing["wrist_x"], player_index, w,
                ):
                    entries_by_player[player_index] = candidate

            hand_entries = list(entries_by_player.values())
            for entry in hand_entries:
                seen_players.add(entry["player_index"])

            wand_assignments = {}
            if self.input_mode == "wand" and force_player_index is None and len(hand_entries) > 1:
                wand_assignments = self._assign_wand_preferred_points(
                    frame, hand_entries, now, w, h,
                )

            for entry in hand_entries:
                player_index = entry["player_index"]
                self._process_hand_landmarks(
                    entry["hand_landmarks"], track=entry["track"],
                    game=game, player_index=player_index,
                    frame=frame, now=now, w=w, h=h,
                    wand_preferred_point=wand_assignments.get(player_index),
                )

        for index, track in enumerate(self.tracks):
            if index not in seen_players:
                self._process_unseen_player(index, track, game, now, w, h)

    def _process_hand_landmarks(
        self,
        hand_landmarks,
        track,
        game,
        player_index,
        frame,
        now,
        w,
        h,
        wand_preferred_point=None,
    ):
        track.last_seen = now

        palm_confidence, palm_detail = self.detect_open_palm(hand_landmarks, w, h)
        point, point_detail = self.get_fingertip_point(hand_landmarks, w, h)
        consume_open_palm, palm_gate_detail = self.should_consume_open_palm(
            track, palm_confidence, point, now,
        )
        if consume_open_palm:
            self._handle_palm_gesture(
                track, game, player_index, palm_confidence,
                palm_detail, palm_gate_detail, point, point_detail, now,
            )
            track.open_palm_since = track.open_palm_since if track.open_palm_since > 0 else now
            return

        track.open_palm_since = 0.0

        if self.input_mode == "wand":
            if wand_preferred_point is None:
                point, point_detail = self.wand_detector.detect_tip(frame, hand_landmarks, track, now, w, h)
            else:
                point, point_detail = self.wand_detector.detect_tip(
                    frame, hand_landmarks, track, now, w, h,
                    preferred_point=wand_preferred_point,
                )
            accepted_for_track = self._wand_point_is_trackable(track, point)
            self._log_wand_debug_sample(
                track, now, player_index, point, point_detail, accepted_for_track,
            )
            point, point_detail = self._gate_wand_point(track, point, point_detail)

        if point is None:
            if self.hold_missing_point(track, now, point_detail, w, h):
                if self.input_mode != "wand":
                    self.evaluate_track_for_spell(
                        game, player_index, track, now, track.debug_detail, "LOST HOLD",
                    )
                return
            if self._wand_missing_track_ready_to_classify(track, now):
                did_cast = self.evaluate_track_for_spell(
                    game, player_index, track, now, track.debug_detail, "LOST HOLD",
                )
                if not did_cast and track.state != CastState.WAIT:
                    finished_detail = track.debug_detail
                    self.clear_gesture_buffer(track)
                    _set_track_state(track, CastState.READY, "READY", finished_detail)
            else:
                if self.input_mode == "wand":
                    self.reset_cv_track(track, "NO WAND", point_detail)
                else:
                    self.reset_cv_track(track, "NO TIP", point_detail)
            return

        point, smooth_detail = self.filter_track_point(track, point, now)
        if point is None:
            track.last_prediction = "WAIT"
            track.last_confidence = 0.0
            _set_track_state(track, CastState.WAIT, "FILTER", smooth_detail)
            return

        self._process_tracked_point(track, game, player_index, point, smooth_detail, now)

    def _handle_palm_gesture(self, track, game, player_index, palm_confidence,
                             palm_detail, palm_gate_detail, point, point_detail, now):
        palm_started = track.open_palm_since if track.open_palm_since > 0 else now
        track.open_palm_since = palm_started
        hold_time = now - palm_started
        palm_track_detail = point_detail
        if point is not None:
            filtered_point, smooth_detail = self.filter_track_point(track, point, now)
            if filtered_point is not None:
                palm_track_detail = smooth_detail
            else:
                palm_track_detail = f"{point_detail}; {smooth_detail}"

        self.clear_gesture_buffer(track)
        track.open_palm_since = palm_started
        track.last_prediction = SPELLS["protego"]["label"]
        track.last_confidence = palm_confidence
        _set_track_state(track, CastState.RECORDING, "PALM",
                         f"{palm_track_detail}; {palm_detail}; {palm_gate_detail}; hold {hold_time:0.2f}s")
        if hold_time >= CV_PALM_HOLD_TIME:
            protego_block = self.emergency_protego_block_reason(game, player_index, now)
            if protego_block:
                _set_track_state(track, CastState.WAIT, "PALM WAIT",
                                 f"{palm_detail}; {protego_block}")
            else:
                self.cast_cv_spell(
                    game, player_index, track, "protego", palm_confidence, now, emergency=True,
                )

    def _process_tracked_point(self, track, game, player_index, point, smooth_detail, now):
        block_reason = self.record_block_reason(game, player_index, track, now)
        if block_reason:
            self.clear_gesture_buffer(track)
            track.last_prediction = "WAIT"
            track.last_confidence = 0.0
            _set_track_state(track, CastState.WAIT, "WAIT",
                             f"{smooth_detail}; tracked; {block_reason}")
            return

        transition = self.update_motion_gate(track, point, now)
        if transition.should_classify:
            did_cast = self.evaluate_track_for_spell(
                game, player_index, track, now,
                f"{smooth_detail}; {transition.reason}", "CLASSIFY",
            )
            if not did_cast and track.state != CastState.WAIT:
                finished_detail = track.debug_detail
                self.clear_gesture_buffer(track)
                _set_track_state(track, CastState.READY, "READY", finished_detail)
            return

        if not transition.should_record:
            _set_track_state(track, transition.state, "READY",
                             f"{smooth_detail}; {transition.reason}")
            track.last_prediction = "READY"
            track.last_confidence = 0.0
            track.path_length = cv_path_length(track.points)
            return

        _set_track_state(track, CastState.RECORDING, "RECORDING",
                         f"{smooth_detail}; {transition.reason}")
        appended = self.append_track_point(track, point)
        if not appended:
            track.last_prediction = "-"
            track.last_confidence = 0.0
            track.path_length = cv_path_length(track.points)
            _set_track_state(track, CastState.RECORDING, "RECORDING",
                             f"{smooth_detail}; tiny move")
            return
        self.preview_track_for_spell(
            game, player_index, track,
            f"{smooth_detail}; {transition.reason}",
        )

    def _process_unseen_player(self, index, track, game, now, w, h):
        if self.hold_missing_point(track, now, "hand lost", w, h):
            if self.input_mode != "wand":
                self.evaluate_track_for_spell(
                    game, index, track, now, track.debug_detail, "LOST HOLD",
                )
            return
        if self._wand_missing_track_ready_to_classify(track, now):
            did_cast = self.evaluate_track_for_spell(
                game, index, track, now, track.debug_detail, "LOST HOLD",
            )
            if not did_cast and track.state != CastState.WAIT:
                finished_detail = track.debug_detail
                self.clear_gesture_buffer(track)
                _set_track_state(track, CastState.READY, "READY", finished_detail)
            return
        if now - track.last_seen > CV_TRACK_TIMEOUT:
            self.reset_cv_track(track, "NO HAND", "show hand")

    def _detect(self, rgb, now):
        if self.backend == "tasks":
            mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            return self.detector.detect_for_video(mp_image, int(now * 1000))
        return None

    _STRING_TO_CASTSTATE = {
        "CAST": CastState.CASTING,
        "WAIT": CastState.WAIT,
        "NO TIP": CastState.IDLE,
        "NO WAND": CastState.IDLE,
        "BLOCKED": CastState.WAIT,
        "NO HAND": CastState.IDLE,
        "LOST HOLD": CastState.LOST,
    }

    def reset_cv_track(self, track, state, detail):
        track.points.clear()
        track.smoothed_point = None
        track.last_valid_point = None
        track.last_valid_time = 0.0
        track.velocity = None
        track.missed_frames = 0
        track.idle_anchor = None
        track.last_motion_time = 0.0
        track.open_palm_since = 0.0
        if state == "CAST":
            track.last_prediction = detail
        elif state in ("WAIT", "NO TIP", "BLOCKED"):
            track.last_prediction = "WAIT"
        else:
            track.last_prediction = "-"
        track.last_confidence = 0.0
        track.path_length = 0.0
        track.debug_state = state
        track.debug_detail = detail
        if state == "NO HAND":
            track.wand_roi = None
        track.wand_raw_point = None
        track.wand_tracker_point = None
        track.wand_tracker_velocity = None
        track.wand_tracker_time = 0.0
        track.wand_tracker_coast_started = 0.0
        track.wand_tracker_state = "UNLOCKED"
        track.wand_tracker_confidence = 0.0
        track.wand_tracker_source = "none"
        track.wand_lost_since = 0.0
        track.wand_tracker_debug = None
        track.wand_debug_last_signature = None
        track.wand_debug_last_time = 0.0
        if getattr(track, "wand_lk_tracker", None) is not None:
            track.wand_lk_tracker.reset()
        if getattr(track, "wand_filter", None) is not None:
            track.wand_filter.reset()
        if state != "NO WAND" and getattr(track, "wand_candidate_history", None) is not None:
            track.wand_candidate_history.reset()

        cast_state = self._STRING_TO_CASTSTATE.get(state, CastState.IDLE)
        _set_track_state(track, cast_state, state, detail)

    def clear_gesture_buffer(self, track):
        track.points.clear()
        track.path_length = 0.0
        track.last_motion_time = 0.0
        track.missed_frames = 0
        track.open_palm_since = 0.0
        if track.last_valid_point is not None:
            track.idle_anchor = track.last_valid_point.copy()

    def hold_missing_point(self, track, now, reason, w, h):
        if len(track.points) == 0 or track.last_valid_point is None or track.last_valid_time <= 0:
            return False

        age = now - track.last_valid_time
        hold_time = WAND_LOST_HOLD_TIME if self.input_mode == "wand" else CV_LOST_HOLD_TIME
        if age > hold_time:
            return False

        track.missed_frames += 1
        track.path_length = cv_path_length(track.points)
        track.last_prediction = "HOLD"
        track.last_confidence = 0.0
        _set_track_state(track, CastState.LOST, "LOST HOLD",
                         f"{reason}; hold {age:0.2f}s")
        return True

    def _wand_missing_track_ready_to_classify(self, track, now):
        if self.input_mode != "wand":
            return False
        if len(track.points) == 0 or track.last_valid_time <= 0:
            return False
        age = now - track.last_valid_time
        return age > WAND_LOST_HOLD_TIME

    def append_track_point(self, track, point):
        point = point.astype(np.float32)
        if len(track.points) == 0:
            track.points.append(point)
            return True

        prev = np.array(track.points[-1], dtype=np.float32)
        gap = float(np.linalg.norm(point - prev))
        if gap < 7:
            return False
        if gap < 42:
            track.points.append(point)
            return True

        steps = int(min(4, max(2, math.ceil(gap / 58))))
        for step in range(1, steps + 1):
            t = step / steps
            track.points.append((prev * (1.0 - t) + point * t).astype(np.float32))
        return True

    def _resolve_player_indices(self, hand_list, w, force_player_index):
        """Map each detected hand to a player index.

        In single-player modes every hand belongs to the forced player.  In duel
        mode each player owns one half of the screen, but MediaPipe gives us no
        notion of *which* person a hand belongs to.  The raw "left half / right
        half" rule fails when two hands land on the same half (people standing
        near the centre, or one prominent person whose two hands are both
        detected) -- both hands then drive a single track and the other player
        goes dead.  When two hands are detected and are separated by at least the
        configured fraction of the frame width we force the leftmost onto player
        1 and the rightmost onto player 2 so both players always get a trail.
        """
        wrists_x = [hand_landmarks[0].x * w for hand_landmarks in hand_list]
        if force_player_index is not None:
            return [force_player_index] * len(hand_list)

        center = w / 2.0
        by_half = [0 if x < center else 1 for x in wrists_x]
        if not DUEL_FORCE_SPLIT or len(hand_list) < 2:
            return by_half

        order = sorted(range(len(wrists_x)), key=lambda i: wrists_x[i])
        left_i, right_i = order[0], order[-1]
        separation = wrists_x[right_i] - wrists_x[left_i]
        if separation < DUEL_SPLIT_MIN_SEPARATION_FRAC * w:
            # Hands are too close to be confident they belong to two people;
            # fall back to the raw halves and let the per-player de-dup keep the
            # better-placed hand.
            return by_half

        indices = list(by_half)
        indices[left_i] = 0
        indices[right_i] = 1
        return indices

    @staticmethod
    def _hand_owns_side_better(candidate_x, existing_x, player_index, w):
        """True if ``candidate_x`` sits more clearly inside the player's half.

        Player 0 owns the left half, so a smaller x is more "owned"; player 1
        owns the right half, so a larger x wins.
        """
        if player_index == 0:
            return candidate_x < existing_x
        return candidate_x > existing_x

    def _assign_wand_preferred_points(self, frame, hand_entries, now, w, h):
        contexts = []
        for entry in hand_entries:
            detector_context = self.wand_detector.inspect_tip_candidates(
                frame,
                entry["hand_landmarks"],
                entry["track"],
                now,
                w,
                h,
            )
            detector_context["player_index"] = entry["player_index"]
            contexts.append(detector_context)

        choices_by_context = []
        for context in contexts:
            choices = [None]
            for candidate in context.get("candidates", []):
                score = self._score_wand_assignment(context, candidate, contexts, w)
                if score is None:
                    continue
                choices.append({
                    "point": np.asarray(candidate["point"], dtype=np.float32),
                    "score": score,
                })
            choices_by_context.append(choices)

        best_score = None
        best_choices = []

        def search(index, selected, total_score):
            nonlocal best_score, best_choices
            if index >= len(contexts):
                if best_score is None or total_score > best_score:
                    best_score = total_score
                    best_choices = list(selected)
                return

            for choice in choices_by_context[index]:
                if choice is not None and self._wand_choice_already_claimed(choice, selected):
                    continue
                selected.append(choice)
                search(index + 1, selected, total_score + (0.0 if choice is None else choice["score"]))
                selected.pop()

        search(0, [], 0.0)

        assignments = {}
        for context, choice in zip(contexts, best_choices):
            if choice is None:
                continue
            assignments[context["player_index"]] = choice["point"]
        return assignments

    def _score_wand_assignment(self, context, candidate, all_contexts, frame_width):
        if not context.get("ok", False):
            return None
        point = np.asarray(candidate.get("point"), dtype=np.float32)
        candidate_score = float(candidate.get("score", 0.0))
        palm_center = np.asarray(context["palm_center"], dtype=np.float32)
        palm_scale = max(float(context.get("palm_scale", 1.0)), 1.0)
        own_distance = float(np.linalg.norm(point - palm_center))

        other_distance = None
        for other in all_contexts:
            if other is context or not other.get("ok", False):
                continue
            other_palm = np.asarray(other["palm_center"], dtype=np.float32)
            distance = float(np.linalg.norm(point - other_palm))
            if other_distance is None or distance < other_distance:
                other_distance = distance

        score = candidate_score * 100.0
        if other_distance is not None:
            ownership_margin = (other_distance - own_distance) / palm_scale
            score += float(np.clip(ownership_margin, -2.0, 2.0)) * 45.0

        predicted = context.get("predicted")
        if predicted is not None:
            prediction_distance = float(np.linalg.norm(point - np.asarray(predicted, dtype=np.float32)))
            score += max(0.0, 1.0 - prediction_distance / 180.0) * 70.0

        player_index = context.get("player_index")
        if player_index == 0:
            score += self._wand_half_field_bias(frame_width / 2.0 - point[0], frame_width)
        elif player_index == 1:
            score += self._wand_half_field_bias(point[0] - frame_width / 2.0, frame_width)
        return score

    def _wand_half_field_bias(self, signed_distance_from_center, frame_width):
        raw_bias = float(signed_distance_from_center) / max(float(frame_width), 1.0)
        raw_bias *= WAND_HALF_FIELD_BIAS_SCALE
        return max(-WAND_HALF_FIELD_BIAS_LIMIT, min(WAND_HALF_FIELD_BIAS_LIMIT, raw_bias))

    def _wand_choice_already_claimed(self, choice, selected):
        point = choice["point"]
        for selected_choice in selected:
            if selected_choice is None:
                continue
            if float(np.linalg.norm(point - selected_choice["point"])) <= WAND_ASSIGNMENT_DUPLICATE_RADIUS:
                return True
        return False

    def _wand_point_is_trackable(self, track, point):
        if point is None:
            return False
        state = getattr(track, "wand_tracker_state", "")
        confidence = float(getattr(track, "wand_tracker_confidence", 0.0))
        minimum = WAND_TRACK_ACCEPT_CONFIDENCE.get(state)
        if minimum is None:
            return False
        if state == "COASTING" and track.state != CastState.RECORDING and len(track.points) == 0:
            return False
        return confidence >= minimum

    def _gate_wand_point(self, track, point, detail):
        if point is None:
            return None, detail
        if self._wand_point_is_trackable(track, point):
            return point, detail

        state = getattr(track, "wand_tracker_state", "UNKNOWN")
        source = getattr(track, "wand_tracker_source", "none")
        confidence = float(getattr(track, "wand_tracker_confidence", 0.0))
        gated_detail = (
            f"{detail}; weak point gate {state} {source} {confidence:0.2f}"
        )
        return None, gated_detail

    def _log_wand_debug_sample(self, track, now, player_index, point, detail, accepted_for_track):
        logger = getattr(self, "wand_debug_logger", None)
        if logger is None:
            return

        debug = getattr(track, "wand_tracker_debug", None) or {}
        state = str(debug.get("state") or getattr(track, "wand_tracker_state", "UNKNOWN"))
        source = str(debug.get("source") or getattr(track, "wand_tracker_source", "none"))
        confidence = float(debug.get("confidence", getattr(track, "wand_tracker_confidence", 0.0)))
        reject_reason = (
            debug.get("reject_reason")
            or debug.get("lk_color_reject")
            or ""
        )
        try:
            jump_bucket = int(float(debug.get("observation_jump", 0.0)) / 50.0)
        except (TypeError, ValueError):
            jump_bucket = 0
        signature = (
            state,
            source,
            bool(accepted_for_track),
            str(reject_reason),
            jump_bucket,
        )
        last_signature = getattr(track, "wand_debug_last_signature", None)
        last_time = float(getattr(track, "wand_debug_last_time", 0.0))
        if signature == last_signature and now - last_time < WAND_DEBUG_LOG_INTERVAL:
            return

        event = {
            "schema": 1,
            "timestamp": now,
            "mode": "wand",
            "track_index": player_index,
            "state": state,
            "source": source,
            "confidence": confidence,
            "accepted_for_track": bool(accepted_for_track),
            "point": None if point is None else np.asarray(point, dtype=np.float32).tolist(),
            "detail": detail,
            "reject_reason": str(reject_reason),
            "debug": debug,
        }
        try:
            logger.log_event(event)
            track.wand_debug_last_signature = signature
            track.wand_debug_last_time = now
        except Exception:
            pass

    def update_motion_gate(self, track, point, now):
        speed = float(np.linalg.norm(track.velocity)) if track.velocity is not None else 0.0
        if track.idle_anchor is None:
            track.idle_anchor = point.copy()

        drift = float(np.linalg.norm(point - track.idle_anchor))
        # LOST HOLD is a short tracking gap inside the same gesture.  Treat it
        # as recording when points remain, otherwise reacquire would clear the
        # trail and reconnect from the idle anchor to the current point.
        currently_recording = (
            track.state == CastState.RECORDING
            or (track.state == CastState.LOST and len(track.points) > 0)
        )

        if not currently_recording:
            if drift < 18 and speed < 180:
                track.idle_anchor = track.idle_anchor * 0.90 + point * 0.10
                track.points.clear()
                track.path_length = 0.0
                return CVTransition(CastState.READY, False, False,
                                    f"idle drift {drift:0.0f}px speed {speed:0.0f}")

            track.points.clear()
            track.path_length = 0.0
            track.last_motion_time = now
            track.points.append(track.idle_anchor.astype(np.float32))
            return CVTransition(CastState.RECORDING, True, False,
                                f"start drift {drift:0.0f}px speed {speed:0.0f}")

        if speed > 75:
            track.last_motion_time = now
        elif track.points:
            # Even if smoothed speed is low, meaningful displacement from the
            # last recorded point means the user is still drawing.  This stops
            # slow gestures (e.g. a deliberate zigzag) from being cut off early.
            displacement = float(np.linalg.norm(point - track.points[-1]))
            if displacement > 12:
                track.last_motion_time = now

        if track.last_motion_time > 0 and now - track.last_motion_time > CV_TRACK_TIMEOUT:
            track.idle_anchor = point.copy()
            return CVTransition(CastState.CLASSIFY, False, True, "gesture ended")

        return CVTransition(CastState.RECORDING, True, False,
                            f"record speed {speed:0.0f}")

    def evaluate_track_for_spell(self, game, player_index, track, now, detail, state):
        track.path_length = cv_path_length(track.points)
        was_recording = track.state == CastState.RECORDING or state == "TRACKING"
        track.state = CastState.CLASSIFY
        side = game.players[player_index].side
        points = list(track.points)

        result = self.gesture_pipeline.classify(points, side)
        spell = result.spell
        confidence = result.confidence

        if self.verbose_debug:
            diag = diagnose_cv_gesture(points, side)
            track.last_gesture_debug = diag
            if diag is not None:
                track.last_debug_message = diag.message
                if diag.rejected_reasons:
                    track.last_debug_message += " | " + diag.rejected_reasons[0]

        track.last_prediction = SPELLS[spell]["label"] if spell else ("HOLD" if state == "LOST HOLD" else "-")
        track.last_confidence = confidence
        debug_detail = self.describe_tracking(track, spell, confidence, detail)
        track.debug_state = state
        track.debug_detail = debug_detail

        if getattr(self, "training_capture_enabled", False):
            event = self._gesture_log_event(
                now=now,
                side=side,
                points=points,
                result=result,
                cast_attempted=False,
                cast_success=False,
                debug_state="REVIEW",
                training_mode=True,
            )
            track.debug_state = "REVIEW"
            track.debug_detail = debug_detail
            _set_track_state(track, CastState.WAIT, "REVIEW", debug_detail)
            callback = getattr(self, "training_review_callback", None)
            if callback is not None:
                callback(event, self._track_index(track, player_index))
            return False

        cast_attempted = spell is not None and confidence >= 0.78
        if not cast_attempted:
            self._log_gesture_event(self._gesture_log_event(
                now=now,
                side=side,
                points=points,
                result=result,
                cast_attempted=False,
                cast_success=False,
                debug_state=state,
            ))

            if state == "LOST HOLD":
                fallback_state = CastState.LOST
            elif was_recording:
                fallback_state = CastState.RECORDING
            else:
                fallback_state = CastState.READY
            _set_track_state(track, fallback_state, state, debug_detail)
            return False

        return self.cast_cv_spell(game, player_index, track, spell, confidence, now, result=result)

    def _track_index(self, track, fallback):
        for index, candidate in enumerate(getattr(self, "tracks", [])):
            if candidate is track:
                return index
        return fallback

    def cast_cv_spell(self, game, player_index, track, spell, confidence, now, emergency=False, result=None):
        label = SPELLS[spell]["label"]
        if not getattr(self, "allow_casting", True):
            self.clear_gesture_buffer(track)
            track.last_prediction = label
            track.last_confidence = confidence
            track.last_cast_label = label
            track.last_cast_confidence = confidence
            track.last_cast_until = now + 0.3
            _set_track_state(track, CastState.WAIT, "PAUSED",
                             f"{label} paused")
            return False

        session = getattr(self, "battle_session", None)
        if session is None or getattr(session, "game", game) is not game:
            session = LocalBattleSession(game)
            self.battle_session = session
        submission = session.request_cast(
            player_index=player_index,
            spell=spell,
            now=now,
            source="cv",
        )
        did_cast = submission.accepted is True

        if result is not None:
            side = game.players[player_index].side
            self._log_gesture_event(self._gesture_log_event(
                now=now,
                side=side,
                points=list(track.points),
                result=result,
                cast_attempted=True,
                cast_success=did_cast,
                debug_state="CAST" if did_cast else "BLOCKED",
                block_reason=(submission.reason or game.players[player_index].last_message)
                if not did_cast else "",
            ))

        if did_cast:
            self.clear_gesture_buffer(track)
            track.last_prediction = label
            track.last_confidence = confidence
            track.last_cast_label = label
            track.last_cast_confidence = confidence
            track.last_cast_until = now + 1.0
            _set_track_state(track, CastState.CASTING, "CAST",
                             f"{label}{' emergency' if emergency else ''}")
        else:
            self.clear_gesture_buffer(track)
            track.last_prediction = label
            track.last_confidence = confidence
            track.last_cast_label = label
            track.last_cast_confidence = confidence
            track.last_cast_until = now + 0.6
            _set_track_state(
                track,
                CastState.WAIT,
                "BLOCKED",
                submission.reason or game.players[player_index].last_message,
            )
        return did_cast

    def preview_track_for_spell(self, game, player_index, track, detail):
        track.path_length = cv_path_length(track.points)
        side = game.players[player_index].side
        spell, confidence = classify_cv_gesture(list(track.points), side)
        if self.verbose_debug:
            diag = diagnose_cv_gesture(list(track.points), side)
            track.last_gesture_debug = diag
            if diag is not None:
                track.last_debug_message = diag.message
                if diag.rejected_reasons:
                    track.last_debug_message += " | " + diag.rejected_reasons[0]

        track.last_prediction = SPELLS[spell]["label"] if spell else "-"
        track.last_confidence = confidence
        debug_detail = self.describe_tracking(track, spell, confidence, detail)
        if spell and confidence >= 0.78:
            label = SPELLS[spell]["label"]
            debug_detail = f"{detail}; CAND {label}; stop to cast"
        _set_track_state(track, CastState.RECORDING, "RECORDING", debug_detail)

    def record_block_reason(self, game, player_index, track, now):
        player = game.players[player_index]
        if game.winner is not None or not player.alive():
            return "ROUND OVER"
        if now < player.silenced_until:
            return f"SILENCE {player.silenced_until - now:0.1f}s"
        if now < player.global_cooldown_until:
            return f"GCD {player.global_cooldown_until - now:0.1f}s"
        return ""

    def emergency_protego_block_reason(self, game, player_index, now):
        allowed, reason = game.can_cast(player_index, "protego", now)
        if not allowed:
            if reason in ("ROUND OVER", "DEAD"):
                return "ROUND OVER"
            if reason == "SILENCED":
                player = game.players[player_index]
                return f"SILENCE {player.silenced_until - now:0.1f}s"
            if reason == "SPELL CD":
                player = game.players[player_index]
                return f"PRO cd {player.spell_cooldown_until['protego'] - now:0.1f}s"
            if reason == "NO MANA":
                return "NO MANA"
        return ""

    def should_consume_open_palm(self, track, palm_confidence, point, now):
        if palm_confidence < CV_PALM_CONFIDENCE:
            track.open_palm_since = 0.0
            return False, f"open palm conf {palm_confidence:0.2f}/{CV_PALM_CONFIDENCE:0.2f}"

        if point is None or track.last_valid_point is None or track.last_valid_time <= 0:
            return True, "open palm stable"

        dt = now - track.last_valid_time
        if dt <= 0 or dt > CV_LOST_HOLD_TIME:
            return True, "open palm stable"

        speed = float(np.linalg.norm(point - track.last_valid_point) / max(dt, 1e-3))
        if speed > CV_PALM_MAX_CAST_SPEED:
            track.open_palm_since = 0.0
            return False, f"open palm moving {speed:0.0f}px/s"

        return True, f"open palm stable {speed:0.0f}px/s"

    def detect_open_palm(self, hand_landmarks, w, h):
        pts = [
            np.array([lm.x * w, lm.y * h], dtype=np.float32)
            for lm in hand_landmarks
        ]
        wrist = pts[0]
        middle_mcp = pts[9]
        palm_scale = max(np.linalg.norm(middle_mcp - wrist), 35.0)

        finger_specs = [
            (8, 6, "index"),
            (12, 10, "middle"),
            (16, 14, "ring"),
            (20, 18, "pinky"),
        ]
        extended = 0
        for tip_idx, pip_idx, _name in finger_specs:
            tip_dist = np.linalg.norm(pts[tip_idx] - wrist)
            pip_dist = np.linalg.norm(pts[pip_idx] - wrist)
            if tip_dist > pip_dist + palm_scale * 0.12:
                extended += 1

        fingertips = np.array([pts[i] for i in (8, 12, 16, 20)], dtype=np.float32)
        spread_x = float(fingertips[:, 0].max() - fingertips[:, 0].min())
        spread_y = float(fingertips[:, 1].max() - fingertips[:, 1].min())
        spread = max(spread_x, spread_y)
        spread_score = min(1.0, spread / max(palm_scale * 1.45, 1.0))
        confidence = min(1.0, extended / 4.0 * 0.78 + spread_score * 0.22)

        if extended < 4:
            return confidence, f"open palm fingers {extended}/4"
        if spread < palm_scale * 0.72:
            return confidence, f"open palm spread {spread:0.0f}"
        return confidence, f"open palm {extended}/4"

    def get_fingertip_point(self, hand_landmarks, w, h):
        pts = [
            np.array([lm.x * w, lm.y * h], dtype=np.float32)
            for lm in hand_landmarks
        ]
        wrist = pts[0]
        index_mcp = pts[5]
        index_pip = pts[6]
        index_dip = pts[7]
        index_tip = pts[8]
        middle_mcp = pts[9]

        if not (0 <= index_tip[0] < w and 0 <= index_tip[1] < h):
            return None, "tip out of frame"

        palm_scale = max(
            np.linalg.norm(middle_mcp - wrist),
            np.linalg.norm(index_mcp - wrist),
            1.0,
        )
        tip_from_wrist = np.linalg.norm(index_tip - wrist)
        dip_from_wrist = np.linalg.norm(index_dip - wrist)
        tip_segment = np.linalg.norm(index_tip - index_pip)
        v1 = index_pip - index_mcp
        v2 = index_tip - index_pip
        alignment = float(np.dot(v1, v2) / max(np.linalg.norm(v1) * np.linalg.norm(v2), 1.0))

        if tip_segment < max(10.0, palm_scale * 0.16):
            return None, "tip too close"
        if tip_from_wrist < dip_from_wrist + max(8.0, palm_scale * 0.08):
            return None, "index folded"
        if alignment < -0.15:
            return None, "finger bent"
        return index_tip, "finger tip ok"

    def filter_track_point(self, track, point, now):
        if track.smoothed_point is None:
            track.smoothed_point = point.copy()
            track.last_valid_point = track.smoothed_point.copy()
            track.last_valid_time = now
            track.velocity = None
            track.missed_frames = 0
            return track.smoothed_point.copy(), "smooth start"

        jump = float(np.linalg.norm(point - track.smoothed_point))
        if jump > 320 and len(track.points) > 0:
            return None, f"jump reject {jump:0.0f}px"

        alpha = 0.35
        if jump > 120:
            alpha = 0.78
        elif jump > 90:
            alpha = 0.68
        elif jump > 35:
            alpha = 0.48
        previous = track.last_valid_point.copy() if track.last_valid_point is not None else track.smoothed_point.copy()
        previous_time = track.last_valid_time
        track.smoothed_point = track.smoothed_point * (1.0 - alpha) + point * alpha
        if previous_time > 0 and now > previous_time:
            dt = max(now - previous_time, 1e-3)
            velocity = (track.smoothed_point - previous) / dt
            if track.velocity is None:
                track.velocity = velocity
            else:
                track.velocity = track.velocity * 0.45 + velocity * 0.55
        track.last_valid_point = track.smoothed_point.copy()
        track.last_valid_time = now
        track.missed_frames = 0
        return track.smoothed_point.copy(), f"smooth {jump:0.0f}px"

    def describe_tracking(self, track, spell, confidence, point_detail):
        points_count = len(track.points)
        if points_count < 6:
            return f"{point_detail}; SHORT pts {points_count}/6"
        if track.path_length < 55:
            return f"{point_detail}; SHORT len {track.path_length:0.0f}/55"
        if not spell:
            if points_count < 14:
                return f"{point_detail}; DIR no fast match; shape pts {points_count}/14"
            if track.path_length < 125:
                return f"{point_detail}; SHORT shape len {track.path_length:0.0f}/125"
            return f"{point_detail}; DIR/TURNS no shape match"
        if confidence < 0.78:
            return f"{point_detail}; LOW CONF {confidence:0.2f}/0.78"
        return f"{point_detail}; ready"

    def draw(self, frame, now, show_debug=False):
        colors = [(90, 235, 255), (255, 175, 90)]
        if self.input_mode == "wand":
            self.draw_wand_calibration_target(frame)

        for index, track in enumerate(self.tracks):
            points = list(track.points)
            if track.wand_roi is not None:
                x1, y1, x2, y2 = track.wand_roi
                cv2.rectangle(frame, (x1, y1), (x2, y2), colors[index], 1, cv2.LINE_AA)
            if track.wand_raw_point is not None:
                cv2.circle(frame, tuple(np.int32(track.wand_raw_point)), 12, (70, 255, 255), 1, cv2.LINE_AA)

            if len(points) >= 2:
                for i in range(1, len(points)):
                    t = i / max(1, len(points) - 1)
                    thickness = int(1 + 5 * t)
                    cv2.line(
                        frame,
                        tuple(np.int32(points[i - 1])),
                        tuple(np.int32(points[i])),
                        colors[index],
                        thickness,
                        cv2.LINE_AA,
                    )
                cv2.circle(frame, tuple(np.int32(points[-1])), 10, colors[index], -1, cv2.LINE_AA)

            if track.smoothed_point is not None:
                cv2.circle(frame, tuple(np.int32(track.smoothed_point)), 7, colors[index], 2, cv2.LINE_AA)
                cv2.circle(frame, tuple(np.int32(track.smoothed_point)), 2, (255, 255, 255), -1, cv2.LINE_AA)

            display_prediction = track.last_prediction
            display_confidence = track.last_confidence
            if now < track.last_cast_until:
                display_prediction = track.last_cast_label
                display_confidence = track.last_cast_confidence

            label_x = 28 if index == 0 else WIDTH - 240
            label_y = HEIGHT - 92
            text = f"CV {index + 1} {self.input_mode.upper()}: {display_prediction} {display_confidence:0.2f}"
            if show_debug or len(points) >= 2 or now < track.last_cast_until:
                draw_cv_text(frame, text, (label_x, label_y), 0.5, colors[index])

            if show_debug:
                self.draw_debug_panel(frame, index, track, colors[index], now)

    def draw_wand_calibration_target(self, frame):
        center = (WIDTH // 2, HEIGHT // 2)
        track0 = self.tracks[0] if len(self.tracks) > 0 else None
        color = (track0.wand_color_bgr if track0 and track0.wand_color_bgr is not None
                 else self.wand_detector.wand_color_bgr if self.wand_detector.wand_color_bgr is not None
                 else (0, 255, 255))
        cv2.circle(frame, center, WAND_CALIBRATION_RADIUS, color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0] - 28, center[1]), (center[0] - 8, center[1]), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0] + 8, center[1]), (center[0] + 28, center[1]), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0], center[1] - 28), (center[0], center[1] - 8), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0], center[1] + 8), (center[0], center[1] + 28), color, 1, cv2.LINE_AA)
        draw_cv_text(frame, self.wand_overlay_hint(), (center[0] - 138, center[1] + 48), 0.44, color)

    def wand_overlay_hint(self):
        tracks = getattr(self, "tracks", [])
        p0 = tracks[0].wand_color_calibrated if len(tracks) > 0 else False
        p1 = tracks[1].wand_color_calibrated if len(tracks) > 1 else False
        if p0 and p1:
            return "P1 C | P2 SHIFT+C | RELOCK"
        if p0:
            return "P1 LOCKED | P2 SHIFT+C TO LOCK"
        return "CENTER MARKER + C(P1) / SHIFT+C(P2) TO LOCK"

    def draw_debug_panel(self, frame, index, track, color, now):
        verbose = self.verbose_debug
        h = 110 if verbose else 74
        x = 24 if index == 0 else WIDTH - 324
        y = HEIGHT - 148 - (36 if verbose else 0)
        w = 300
        overlay = frame.copy()
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (12, 14, 22), -1)
        cv2.addWeighted(overlay, 0.62, frame, 0.38, 0, frame)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 1, cv2.LINE_AA)

        state_color = color
        if track.debug_state in ("WAIT", "BLOCKED", "FILTER", "LOST HOLD", "PALM WAIT"):
            state_color = (70, 170, 255)
        elif track.debug_state in ("NO HAND", "NO TIP", "NO WAND"):
            state_color = (150, 150, 160)
        elif track.debug_state == "CAST":
            state_color = (100, 230, 130)

        detail = f"{track.debug_state}: {track.debug_detail}"
        if len(detail) > 46:
            detail = detail[:43] + "..."
        display_prediction = track.last_prediction
        display_confidence = track.last_confidence
        if now < track.last_cast_until:
            display_prediction = track.last_cast_label
            display_confidence = track.last_cast_confidence

        draw_cv_text(frame, f"CV {index + 1} {self.input_mode.upper()} DEBUG", (x + 10, y + 19), 0.48, color)
        draw_cv_text(frame, f"PTS {len(track.points):02d} F6/S14   LEN {track.path_length:04.0f}", (x + 10, y + 39), 0.43, (230, 232, 238))
        draw_cv_text(frame, f"PRED {display_prediction}   CONF {display_confidence:0.2f}/0.78", (x + 10, y + 56), 0.43, (230, 232, 238))
        draw_cv_text(frame, detail, (x + 10, y + 71), 0.38, state_color)

        if verbose:
            diag = track.last_gesture_debug
            if diag is not None and diag.features is not None:
                f = diag.features
                draw_cv_text(frame,
                             f"DX={f.dx:+.0f} DY={f.dy:+.0f} SPN={f.x_span:.0f}x{f.y_span:.0f}",
                             (x + 10, y + 87),
                             0.37, (210, 240, 255))
                draw_cv_text(frame,
                             f"STRAIGHT={f.straightness:.2f} TURNS={f.turn_count} PATH={f.path_len:.0f}",
                             (x + 10, y + 101),
                             0.37, (210, 240, 255))
                # Match / reject reason
                if track.last_debug_message:
                    match_str = track.last_debug_message
                elif diag.prediction:
                    match_str = f"MATCH={diag.prediction} CONF={diag.confidence:.2f}"
                elif diag.rejected_reasons:
                    r = diag.rejected_reasons[0]
                    match_str = f"REJ: {r}" if len(r) <= 50 else f"REJ: {r[:47]}..."
                else:
                    match_str = diag.message
                if len(match_str) > 55:
                    match_str = match_str[:52] + "..."
                draw_cv_text(frame, match_str, (x + 10, y + 115), 0.37, (210, 255, 210))
            else:
                draw_cv_text(frame, track.last_debug_message, (x + 10, y + 87), 0.37, (210, 240, 255))
