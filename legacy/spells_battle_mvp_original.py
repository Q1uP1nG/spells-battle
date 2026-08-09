import math
import os
import random
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


WIDTH = 1280
HEIGHT = 720
FPS_FALLBACK = 60
MAX_HP = 100.0
MAX_MANA = 100.0
MANA_REGEN_PER_SEC = 12.0
CV_TRACK_TIMEOUT = 0.45
CV_LOST_HOLD_TIME = 0.24
CV_PREDICT_HOLD_TIME = 0.14
CV_MAX_MISSED_FRAMES = 3
CV_PALM_CONFIDENCE = 0.78
CV_PALM_HOLD_TIME = 0.08
WAND_MIN_SATURATION = 70
WAND_MIN_VALUE = 70
WAND_MIN_AREA = 8
WAND_MAX_AREA = 900
WAND_HUE_TOLERANCE = 12
WAND_CALIBRATION_RADIUS = 18
WAND_MIN_CALIBRATION_PIXELS = 18
HAND_MODEL_PATH = "hand_landmarker.task"
HAND_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"


SPELLS = {
    "incendio": {
        "label": "INC",
        "full": "Incendio",
        "mana": 25,
        "cooldown": 3.0,
        "damage": 22,
        "speed": 760,
        "radius": 28,
        "color": (40, 130, 255),
        "kind": "projectile",
    },
    "stupefy": {
        "label": "STU",
        "full": "Stupefy",
        "mana": 35,
        "cooldown": 5.0,
        "damage": 16,
        "speed": 620,
        "radius": 22,
        "color": (70, 70, 255),
        "kind": "projectile",
        "silence": 1.0,
    },
    "glacius": {
        "label": "GLA",
        "full": "Glacius",
        "mana": 30,
        "cooldown": 4.6,
        "damage": 10,
        "speed": 500,
        "radius": 34,
        "color": (255, 210, 70),
        "kind": "projectile",
        "frozen": 2.0,
    },
    "protego": {
        "label": "PRO",
        "full": "Protego",
        "mana": 30,
        "cooldown": 6.0,
        "shield_value": 35,
        "duration": 3.0,
        "color": (255, 210, 120),
        "kind": "shield",
    },
    "lumos": {
        "label": "LUM",
        "full": "Lumos",
        "mana": 40,
        "cooldown": 8.0,
        "heal": 18,
        "channel": 1.2,
        "color": (230, 255, 255),
        "kind": "heal",
    },
}


P1_KEYS = {
    ord("q"): "incendio",
    ord("w"): "stupefy",
    ord("e"): "glacius",
    ord("r"): "protego",
    ord("t"): "lumos",
}

P2_KEYS = {
    ord("u"): "incendio",
    ord("i"): "stupefy",
    ord("o"): "glacius",
    ord("p"): "protego",
    ord("l"): "lumos",
}


@dataclass
class Player:
    pid: int
    name: str
    side: str
    hp: float = MAX_HP
    mana: float = MAX_MANA
    spell_cooldown_until: dict = field(
        default_factory=lambda: {name: 0.0 for name in SPELLS}
    )
    shield_value: float = 0.0
    shield_until: float = 0.0
    silenced_until: float = 0.0
    frozen_until: float = 0.0
    healing_until: float = 0.0
    pending_heal: float = 0.0
    last_spell: str = "-"
    last_message: str = ""
    message_until: float = 0.0

    def center(self):
        if self.side == "left":
            return np.array([WIDTH * 0.23, HEIGHT * 0.55], dtype=np.float32)
        return np.array([WIDTH * 0.77, HEIGHT * 0.55], dtype=np.float32)

    def wand_pos(self):
        base = self.center()
        return base + np.array([70 if self.side == "left" else -70, -40], dtype=np.float32)

    def target_body_rect(self):
        c = self.center()
        return (
            int(c[0] - 85),
            int(c[1] - 130),
            int(c[0] + 85),
            int(c[1] + 120),
        )

    def alive(self):
        return self.hp > 0

    def has_shield(self, now):
        return self.shield_value > 0 and now < self.shield_until

    def is_healing(self, now):
        return self.pending_heal > 0 and now < self.healing_until


@dataclass
class Projectile:
    owner: int
    spell: str
    pos: np.ndarray
    vel: np.ndarray
    radius: float
    damage: float
    color: tuple
    life: float = 2.4
    active: bool = True


@dataclass
class Particle:
    pos: np.ndarray
    vel: np.ndarray
    color: tuple
    radius: float
    life: float
    max_life: float
    kind: str = "dot"


@dataclass
class CVTrack:
    points: deque = field(default_factory=lambda: deque(maxlen=48))
    last_seen: float = 0.0
    smoothed_point: object = None
    last_valid_point: object = None
    last_valid_time: float = 0.0
    velocity: object = None
    missed_frames: int = 0
    recording: bool = False
    idle_anchor: object = None
    last_motion_time: float = 0.0
    open_palm_since: float = 0.0
    last_cast_label: str = "-"
    last_cast_confidence: float = 0.0
    last_cast_until: float = 0.0
    last_prediction: str = "-"
    last_confidence: float = 0.0
    path_length: float = 0.0
    debug_state: str = "NO HAND"
    debug_detail: str = "show hand"
    wand_roi: object = None
    wand_raw_point: object = None


class CVGestureController:
    def __init__(self):
        self.available = False
        self.input_mode = "finger"
        self.base_status = "MediaPipe Tasks"
        self.status = "CV OFF"
        self.detail_status = "CV OFF"
        self.tracks = [CVTrack(), CVTrack()]
        self.backend = None
        self.mp = None
        self.detector = None
        self.hands = None
        self.wand_hue = None
        self.wand_sat_min = WAND_MIN_SATURATION
        self.wand_val_min = WAND_MIN_VALUE
        self.wand_color_bgr = None

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
            base_status = getattr(self, "base_status", "MediaPipe Tasks")
            if self.input_mode == "wand":
                lock = "LOCKED" if self.wand_hue is not None else "PRESS C"
                self.status = f"CV WAND {lock}: {base_status}"
            else:
                self.status = f"CV FINGER: {base_status}"

    def toggle_input_mode(self):
        self.input_mode = "wand" if self.input_mode == "finger" else "finger"
        self.tracks = [CVTrack(), CVTrack()]
        self.refresh_status()
        return self.input_mode

    def calibrate_wand_color(self, frame):
        if frame is None or frame.size == 0:
            return False, "CALIB FAILED: no frame"

        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        r = WAND_CALIBRATION_RADIUS
        x1 = max(0, cx - r)
        y1 = max(0, cy - r)
        x2 = min(w, cx + r + 1)
        y2 = min(h, cy + r + 1)
        patch = frame[y1:y2, x1:x2]
        if patch.size == 0:
            return False, "CALIB FAILED: empty center"

        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        mask = (sat >= WAND_MIN_SATURATION) & (val >= WAND_MIN_VALUE)
        if int(np.count_nonzero(mask)) < WAND_MIN_CALIBRATION_PIXELS:
            return False, "CALIB FAILED: center needs bright colored tip"

        hues = hsv[:, :, 0][mask].astype(np.float32)
        selected_sat = sat[mask].astype(np.float32)
        selected_val = val[mask].astype(np.float32)
        self.wand_hue = self.circular_mean_hue(hues)
        self.wand_sat_min = max(WAND_MIN_SATURATION, float(np.percentile(selected_sat, 20)) * 0.70)
        self.wand_val_min = max(WAND_MIN_VALUE, float(np.percentile(selected_val, 20)) * 0.60)
        bgr_pixels = patch[mask]
        self.wand_color_bgr = tuple(int(v) for v in np.mean(bgr_pixels, axis=0))
        self.tracks = [CVTrack(), CVTrack()]
        self.refresh_status()
        return True, f"CV WAND LOCKED H{self.wand_hue:0.0f}"

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

    def update(self, frame, game, now, force_player_index=None):
        if not self.available:
            return

        mp_frame = cv2.convertScaleAbs(frame, alpha=1.35, beta=28)
        rgb = cv2.cvtColor(mp_frame, cv2.COLOR_BGR2RGB)
        results = self._detect(rgb, now)
        seen_players = set()
        hand_list = get_hand_landmark_list(results)
        h, w = frame.shape[:2]
        if hand_list:
            for hand_landmarks in hand_list:
                wrist = hand_landmarks[0]
                if force_player_index is None:
                    player_index = 0 if wrist.x * w < w / 2 else 1
                else:
                    player_index = force_player_index
                seen_players.add(player_index)

                track = self.tracks[player_index]
                track.last_seen = now

                palm_confidence, palm_detail = self.detect_open_palm(hand_landmarks, w, h)
                point, point_detail = self.get_fingertip_point(hand_landmarks, w, h)
                if palm_confidence >= CV_PALM_CONFIDENCE:
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
                    track.debug_state = "PALM"
                    track.debug_detail = f"{palm_track_detail}; {palm_detail}; hold {hold_time:0.2f}s"
                    if hold_time >= CV_PALM_HOLD_TIME:
                        protego_block = self.emergency_protego_block_reason(game, player_index, now)
                        if protego_block:
                            track.debug_state = "PALM WAIT"
                            track.debug_detail = f"{palm_detail}; {protego_block}"
                        else:
                            self.cast_cv_spell(
                                game,
                                player_index,
                                track,
                                "protego",
                                palm_confidence,
                                now,
                                emergency=True,
                            )
                    continue
                track.open_palm_since = 0.0

                if self.input_mode == "wand":
                    point, point_detail = self.get_wand_tip_point(frame, hand_landmarks, track, now, w, h)

                if point is None:
                    if self.hold_missing_point(track, now, point_detail, w, h):
                        self.evaluate_track_for_spell(
                            game,
                            player_index,
                            track,
                            now,
                            track.debug_detail,
                            "LOST HOLD",
                        )
                    else:
                        state = "NO WAND" if self.input_mode == "wand" else "NO TIP"
                        self.reset_cv_track(track, state, point_detail)
                    continue

                point, smooth_detail = self.filter_track_point(track, point, now)
                if point is None:
                    track.last_prediction = "WAIT"
                    track.last_confidence = 0.0
                    track.debug_state = "FILTER"
                    track.debug_detail = smooth_detail
                    continue

                block_reason = self.record_block_reason(game, player_index, track, now)
                if block_reason:
                    self.clear_gesture_buffer(track)
                    track.last_prediction = "WAIT"
                    track.last_confidence = 0.0
                    track.debug_state = "WAIT"
                    track.debug_detail = f"{smooth_detail}; tracked; {block_reason}"
                    continue

                recording, gate_detail = self.update_motion_gate(track, point, now)
                if not recording:
                    track.last_prediction = "READY"
                    track.last_confidence = 0.0
                    track.path_length = cv_path_length(track.points)
                    track.debug_state = "READY"
                    track.debug_detail = f"{smooth_detail}; {gate_detail}"
                    continue

                appended = self.append_track_point(track, point)
                if not appended:
                    track.last_prediction = "-"
                    track.last_confidence = 0.0
                    track.path_length = cv_path_length(track.points)
                    track.debug_state = "RECORDING"
                    track.debug_detail = f"{smooth_detail}; tiny move"
                    continue
                self.evaluate_track_for_spell(
                    game,
                    player_index,
                    track,
                    now,
                    f"{smooth_detail}; {gate_detail}",
                    "TRACKING",
                )

        for index, track in enumerate(self.tracks):
            if index not in seen_players:
                if self.hold_missing_point(track, now, "hand lost", w, h):
                    self.evaluate_track_for_spell(
                        game,
                        index,
                        track,
                        now,
                        track.debug_detail,
                        "LOST HOLD",
                    )
                    continue
                if now - track.last_seen > CV_TRACK_TIMEOUT:
                    self.reset_cv_track(track, "NO HAND", "show hand")

    def _detect(self, rgb, now):
        if self.backend == "tasks":
            mp_image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            return self.detector.detect_for_video(mp_image, int(now * 1000))
        return None

    def reset_cv_track(self, track, state, detail):
        track.points.clear()
        track.smoothed_point = None
        track.last_valid_point = None
        track.last_valid_time = 0.0
        track.velocity = None
        track.missed_frames = 0
        track.recording = False
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

    def clear_gesture_buffer(self, track):
        track.points.clear()
        track.path_length = 0.0
        track.recording = False
        track.last_motion_time = 0.0
        track.missed_frames = 0
        track.open_palm_since = 0.0
        if track.last_valid_point is not None:
            track.idle_anchor = track.last_valid_point.copy()

    def hold_missing_point(self, track, now, reason, w, h):
        if len(track.points) == 0 or track.last_valid_point is None or track.last_valid_time <= 0:
            return False

        age = now - track.last_valid_time
        if age > CV_LOST_HOLD_TIME:
            return False

        track.missed_frames += 1
        track.path_length = cv_path_length(track.points)
        track.debug_detail = f"{reason}; hold {age:0.2f}s"
        track.last_prediction = "HOLD"
        track.last_confidence = 0.0
        track.debug_state = "LOST HOLD"
        return True

    def predict_track_point(self, track, now, w, h):
        if track.velocity is None or track.missed_frames > CV_MAX_MISSED_FRAMES:
            return None
        dt = now - track.last_valid_time
        if dt <= 0 or dt > CV_PREDICT_HOLD_TIME:
            return None
        speed = float(np.linalg.norm(track.velocity))
        if speed < 80 or speed > 2400:
            return None
        predicted = track.last_valid_point + track.velocity * dt
        predicted[0] = np.clip(predicted[0], 0, w - 1)
        predicted[1] = np.clip(predicted[1], 0, h - 1)
        return predicted.astype(np.float32)

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

    def update_motion_gate(self, track, point, now):
        speed = float(np.linalg.norm(track.velocity)) if track.velocity is not None else 0.0
        if track.idle_anchor is None:
            track.idle_anchor = point.copy()

        drift = float(np.linalg.norm(point - track.idle_anchor))
        if not track.recording:
            if drift < 18 and speed < 180:
                track.idle_anchor = track.idle_anchor * 0.90 + point * 0.10
                track.points.clear()
                track.path_length = 0.0
                return False, f"idle drift {drift:0.0f}px speed {speed:0.0f}"

            track.recording = True
            track.points.clear()
            track.path_length = 0.0
            track.last_motion_time = now
            track.points.append(track.idle_anchor.astype(np.float32))
            return True, f"start drift {drift:0.0f}px speed {speed:0.0f}"

        if speed > 75 or drift > 26:
            track.last_motion_time = now

        if track.last_motion_time > 0 and now - track.last_motion_time > 0.42:
            track.recording = False
            track.points.clear()
            track.path_length = 0.0
            track.idle_anchor = point.copy()
            return False, "gesture ended"

        return True, f"record speed {speed:0.0f}"

    def evaluate_track_for_spell(self, game, player_index, track, now, detail, state):
        track.path_length = cv_path_length(track.points)
        spell, confidence = classify_cv_gesture(
            list(track.points),
            game.players[player_index].side,
        )
        track.last_prediction = SPELLS[spell]["label"] if spell else ("HOLD" if state == "LOST HOLD" else "-")
        track.last_confidence = confidence
        track.debug_state = state
        track.debug_detail = self.describe_tracking(track, spell, confidence, detail)
        if not spell or confidence < 0.78:
            return False

        return self.cast_cv_spell(game, player_index, track, spell, confidence, now)

    def cast_cv_spell(self, game, player_index, track, spell, confidence, now, emergency=False):
        did_cast = game.cast_spell(player_index, spell, now)
        label = SPELLS[spell]["label"]
        if did_cast:
            self.clear_gesture_buffer(track)
            track.last_prediction = label
            track.last_confidence = confidence
            track.last_cast_label = label
            track.last_cast_confidence = confidence
            track.last_cast_until = now + 1.0
            track.debug_state = "CAST"
            track.debug_detail = f"{label}{' emergency' if emergency else ''}"
        else:
            self.clear_gesture_buffer(track)
            track.last_prediction = label
            track.last_confidence = confidence
            track.last_cast_label = label
            track.last_cast_confidence = confidence
            track.last_cast_until = now + 0.6
            track.debug_state = "BLOCKED"
            track.debug_detail = game.players[player_index].last_message
        return did_cast

    def record_block_reason(self, game, player_index, track, now):
        player = game.players[player_index]
        if game.winner is not None or not player.alive():
            return "round over"
        if now < player.silenced_until:
            return f"silenced {player.silenced_until - now:0.1f}s"
        return ""

    def emergency_protego_block_reason(self, game, player_index, now):
        player = game.players[player_index]
        spell = SPELLS["protego"]
        if game.winner is not None or not player.alive():
            return "round over"
        if now < player.silenced_until:
            return f"silenced {player.silenced_until - now:0.1f}s"
        if now < player.spell_cooldown_until["protego"]:
            return f"PRO cd {player.spell_cooldown_until['protego'] - now:0.1f}s"
        if player.mana < spell["mana"]:
            return "NO MANA"
        return ""

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

    def get_wand_tip_point(self, frame, hand_landmarks, track, now, w, h):
        pts = np.array(
            [[lm.x * w, lm.y * h] for lm in hand_landmarks],
            dtype=np.float32,
        )
        x1, y1, x2, y2, palm_center, palm_scale = self.compute_wand_roi(pts, w, h)
        track.wand_roi = (x1, y1, x2, y2)
        track.wand_raw_point = None
        if x2 <= x1 or y2 <= y1:
            return None, "wand roi empty"

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return None, "wand roi empty"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        if self.wand_hue is None:
            return None, "press C to lock wand tip color"

        hue = hsv[:, :, 0].astype(np.float32)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        hue_distance = self.hue_distance(hue, self.wand_hue)
        mask = np.zeros(sat.shape, dtype=np.uint8)
        mask[
            (hue_distance <= WAND_HUE_TOLERANCE)
            & (sat >= self.wand_sat_min)
            & (val >= self.wand_val_min)
        ] = 255
        mask = cv2.medianBlur(mask, 5)
        kernel = np.ones((3, 3), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        predicted = self.predict_track_point(track, now, w, h)
        if (
            predicted is None
            and track.last_valid_point is not None
            and 0 <= now - track.last_valid_time <= CV_LOST_HOLD_TIME
        ):
            predicted = track.last_valid_point.copy()

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        useful_count = 0
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < WAND_MIN_AREA or area > WAND_MAX_AREA:
                continue

            bx, by, bw, bh = cv2.boundingRect(contour)
            if bw < 2 or bh < 2 or max(bw, bh) > 95:
                continue

            moments = cv2.moments(contour)
            if moments["m00"] <= 0:
                continue

            local_center = np.array(
                [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
                dtype=np.float32,
            )
            center = local_center + np.array([x1, y1], dtype=np.float32)
            distance_from_palm = float(np.linalg.norm(center - palm_center))
            if distance_from_palm < palm_scale * 0.45:
                continue
            if distance_from_palm > palm_scale * 4.0:
                continue

            contour_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour], -1, 255, -1)
            mean_hsv = cv2.mean(hsv, mask=contour_mask)
            contour_pixels = contour_mask > 0
            mean_hue = self.circular_mean_hue(hsv[:, :, 0][contour_pixels].astype(np.float32))
            mean_hue_distance = self.hue_distance(mean_hue, self.wand_hue)
            mean_sat = float(mean_hsv[1])
            mean_val = float(mean_hsv[2])
            if (
                mean_hue_distance > WAND_HUE_TOLERANCE
                or mean_sat < self.wand_sat_min
                or mean_val < self.wand_val_min
            ):
                continue

            compactness = area / max(float(bw * bh), 1.0)
            score = mean_sat * 0.45 + mean_val * 0.18
            score += (WAND_HUE_TOLERANCE - mean_hue_distance) * 16.0
            score += max(0.0, 420.0 - abs(area - 220.0)) * 0.05
            score += compactness * 45.0
            if predicted is not None:
                distance_from_prediction = float(np.linalg.norm(center - predicted))
                score += max(0.0, 220.0 - distance_from_prediction) * 0.85

            useful_count += 1
            if best is None or score > best[0]:
                best = (score, center, area, mean_sat, mean_val)

        if best is not None:
            _, center, area, mean_sat, mean_val = best
            track.wand_raw_point = center.copy()
            return center.astype(np.float32), (
                f"wand locked area {area:0.0f} sat {mean_sat:0.0f} val {mean_val:0.0f} cand {useful_count}"
            )

        if predicted is not None and self.point_in_roi(predicted, (x1, y1, x2, y2)):
            track.wand_raw_point = predicted.copy()
            return predicted.astype(np.float32), "wand predicted"

        return None, f"no bright tip in hand roi {x2 - x1}x{y2 - y1}"

    def compute_wand_roi(self, pts, w, h):
        palm_points = pts[[0, 5, 9, 13, 17]]
        palm_center = palm_points.mean(axis=0)
        palm_scale = max(
            float(np.linalg.norm(pts[9] - pts[0])),
            float(np.linalg.norm(pts[5] - pts[0])),
            35.0,
        )
        margin = int(np.clip(palm_scale * 3.2, 140, 340))
        min_xy = pts.min(axis=0)
        max_xy = pts.max(axis=0)
        x1 = int(max(0, math.floor(min_xy[0] - margin)))
        y1 = int(max(0, math.floor(min_xy[1] - margin)))
        x2 = int(min(w, math.ceil(max_xy[0] + margin)))
        y2 = int(min(h, math.ceil(max_xy[1] + margin)))
        return x1, y1, x2, y2, palm_center.astype(np.float32), palm_scale

    def point_in_roi(self, point, roi):
        x1, y1, x2, y2 = roi
        return x1 <= float(point[0]) < x2 and y1 <= float(point[1]) < y2

    def hue_distance(self, hue, target):
        distance = np.abs(np.asarray(hue, dtype=np.float32) - float(target))
        return np.minimum(distance, 180.0 - distance)

    def circular_mean_hue(self, hues):
        hue_values = np.asarray(hues, dtype=np.float32).reshape(-1)
        if len(hue_values) == 0:
            return 0.0
        angles = hue_values * (2.0 * math.pi / 180.0)
        mean_angle = math.atan2(float(np.sin(angles).mean()), float(np.cos(angles).mean()))
        if mean_angle < 0:
            mean_angle += 2.0 * math.pi
        return float(mean_angle * 180.0 / (2.0 * math.pi))

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
            return f"{point_detail}; need fast pts {points_count}/6"
        if track.path_length < 55:
            return f"{point_detail}; need fast len {track.path_length:0.0f}/55"
        if not spell:
            if points_count < 14:
                return f"{point_detail}; fast no match, shape pts {points_count}/14"
            if track.path_length < 125:
                return f"{point_detail}; shape len {track.path_length:0.0f}/125"
            return f"{point_detail}; no shape match"
        if confidence < 0.78:
            return f"{point_detail}; low conf {confidence:0.2f}/0.78"
        return f"{point_detail}; ready"

    def draw(self, frame, now):
        colors = [(90, 235, 255), (255, 175, 90)]
        if self.input_mode == "wand":
            self.draw_wand_calibration_target(frame)

        for index, track in enumerate(self.tracks):
            points = list(track.points)
            if self.input_mode == "wand" and track.wand_roi is not None:
                x1, y1, x2, y2 = track.wand_roi
                cv2.rectangle(frame, (x1, y1), (x2, y2), colors[index], 1, cv2.LINE_AA)
            if self.input_mode == "wand" and track.wand_raw_point is not None:
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
            cv2.putText(
                frame,
                text,
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                colors[index],
                1,
                cv2.LINE_AA,
            )

            self.draw_debug_panel(frame, index, track, colors[index], now)

    def draw_wand_calibration_target(self, frame):
        center = (WIDTH // 2, HEIGHT // 2)
        color = self.wand_color_bgr if self.wand_color_bgr is not None else (0, 255, 255)
        cv2.circle(frame, center, WAND_CALIBRATION_RADIUS, color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0] - 28, center[1]), (center[0] - 8, center[1]), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0] + 8, center[1]), (center[0] + 28, center[1]), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0], center[1] - 28), (center[0], center[1] - 8), color, 1, cv2.LINE_AA)
        cv2.line(frame, (center[0], center[1] + 8), (center[0], center[1] + 28), color, 1, cv2.LINE_AA)

    def draw_debug_panel(self, frame, index, track, color, now):
        x = 24 if index == 0 else WIDTH - 324
        y = HEIGHT - 148
        w = 300
        h = 74
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

        cv2.putText(frame, f"CV {index + 1} {self.input_mode.upper()} DEBUG", (x + 10, y + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        cv2.putText(frame, f"PTS {len(track.points):02d} F6/S14   LEN {track.path_length:04.0f}", (x + 10, y + 39), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 232, 238), 1, cv2.LINE_AA)
        cv2.putText(frame, f"PRED {display_prediction}   CONF {display_confidence:0.2f}/0.78", (x + 10, y + 56), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 232, 238), 1, cv2.LINE_AA)
        cv2.putText(frame, detail, (x + 10, y + 71), cv2.FONT_HERSHEY_SIMPLEX, 0.38, state_color, 1, cv2.LINE_AA)

def cv_path_length(points):
    if len(points) < 2:
        return 0.0
    pts = np.array(points, dtype=np.float32)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def classify_cv_gesture(points, side):
    if len(points) < 6:
        return None, 0.0

    pts = np.array(points[-40:], dtype=np.float32)
    deltas = np.diff(pts, axis=0)
    path_len = float(np.linalg.norm(deltas, axis=1).sum())
    if path_len < 55:
        return None, 0.0

    start = pts[0]
    end = pts[-1]
    dx = float(end[0] - start[0])
    dy = float(end[1] - start[1])
    x_span = float(pts[:, 0].max() - pts[:, 0].min())
    y_span = float(pts[:, 1].max() - pts[:, 1].min())
    straightness = float(np.linalg.norm(end - start) / max(path_len, 1.0))
    opponent_dx = dx if side == "left" else -dx
    turn_count = count_direction_turns(pts)
    area = abs(signed_polyline_area(pts))

    if dy < -72 and abs(dx) < 175 and y_span > 58 and path_len > 78:
        return "lumos", min(1.0, 0.79 + (-dy - 72) / 210)

    if opponent_dx > 92 and y_span < 115 and straightness > 0.68 and path_len > 88:
        return "incendio", min(1.0, 0.79 + (opponent_dx - 92) / 260)

    if dy > 92 and abs(dx) < 175 and y_span > 72 and path_len > 90 and straightness > 0.48:
        return "glacius", min(1.0, 0.79 + (dy - 92) / 230)

    if len(points) < 14 or path_len < 125:
        return None, 0.0

    if dy < -125 and abs(dx) < 160 and y_span > 105 and path_len > 145:
        return "lumos", min(1.0, 0.78 + (-dy - 125) / 260)

    if opponent_dx > 150 and y_span < 105 and straightness > 0.82 and path_len > 155:
        return "incendio", min(1.0, 0.80 + (opponent_dx - 150) / 300)

    if looks_like_downward_slash(dx, dy, x_span, y_span, path_len, straightness):
        return "glacius", min(1.0, 0.80 + (dy - 125) / 260)

    if turn_count >= 4 and path_len > 230 and x_span > 100 and y_span > 70:
        return "stupefy", min(1.0, 0.78 + turn_count * 0.045)

    return None, 0.0


def count_direction_turns(points):
    if len(points) < 5:
        return 0
    deltas = np.diff(points, axis=0)
    useful = deltas[np.linalg.norm(deltas, axis=1) > 7]
    if len(useful) < 4:
        return 0
    return max(count_axis_turns(useful[:, 0]), count_axis_turns(useful[:, 1]))


def count_axis_turns(values):
    signs = np.sign(values)
    signs = signs[signs != 0]
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] * signs[:-1] < 0))


def looks_like_downward_slash(dx, dy, x_span, y_span, path_len, straightness):
    return (
        dy > 135
        and abs(dx) < 165
        and y_span > 120
        and x_span < 190
        and path_len > 150
        and straightness > 0.55
    )


def looks_like_z_shape(points, side):
    if len(points) < 18:
        return False
    x_span = float(points[:, 0].max() - points[:, 0].min())
    y_span = float(points[:, 1].max() - points[:, 1].min())
    if x_span < 125 or y_span < 80:
        return False

    thirds = np.array_split(points, 3)
    if any(len(part) < 3 for part in thirds):
        return False

    segs = [part[-1] - part[0] for part in thirds]
    first_dx, first_dy = float(segs[0][0]), float(segs[0][1])
    second_dx, second_dy = float(segs[1][0]), float(segs[1][1])
    third_dx, third_dy = float(segs[2][0]), float(segs[2][1])

    first_horizontal = abs(first_dx) > 45 and abs(first_dy) < 80
    middle_diagonal = abs(second_dx) > 45 and abs(second_dy) > 45
    third_horizontal = abs(third_dx) > 45 and abs(third_dy) < 90
    descends = points[-1][1] - points[0][1] > 55

    return first_horizontal and middle_diagonal and third_horizontal and descends


def looks_like_shield_arc(points):
    if len(points) < 16:
        return False
    x_span = float(points[:, 0].max() - points[:, 0].min())
    y_span = float(points[:, 1].max() - points[:, 1].min())
    if x_span < 130 or y_span < 85:
        return False

    aspect = x_span / max(y_span, 1.0)
    if aspect < 0.85 or aspect > 3.2:
        return False

    path_len = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
    area = abs(signed_polyline_area(points))
    start_end = float(np.linalg.norm(points[-1] - points[0]))
    turn_count = count_direction_turns(points)
    smoothness = start_end / max(path_len, 1.0)
    curvature_area = area / max(x_span * y_span, 1.0)
    endpoints_same_height = abs(float(points[-1][1] - points[0][1])) < y_span * 0.55
    has_middle_bulge = abs(float(points[:, 1].mean() - (points[0][1] + points[-1][1]) / 2)) > y_span * 0.18

    enough_curve = curvature_area > 0.24
    not_closed_circle_required = start_end > max(x_span, y_span) * 0.35
    not_too_straight = smoothness < 0.76
    not_zigzag = turn_count <= 1
    enough_motion = path_len > 210

    return (
        enough_curve
        and not_closed_circle_required
        and not_too_straight
        and not_zigzag
        and enough_motion
        and endpoints_same_height
        and has_middle_bulge
    )


def signed_polyline_area(points):
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def ensure_hand_model():
    if os.path.exists(HAND_MODEL_PATH):
        return HAND_MODEL_PATH

    print("Downloading MediaPipe hand landmarker model...")
    urllib.request.urlretrieve(HAND_MODEL_URL, HAND_MODEL_PATH)
    return HAND_MODEL_PATH


def get_hand_landmark_list(results):
    if results is None:
        return []
    if hasattr(results, "hand_landmarks") and results.hand_landmarks:
        return results.hand_landmarks
    return []


class BattleGame:
    def __init__(self):
        self.players = [
            Player(0, "P1", "left"),
            Player(1, "P2", "right"),
        ]
        self.projectiles = []
        self.particles = []
        self.flash_messages = []
        self.winner = None
        self.round_start = time.monotonic()

    def reset(self):
        self.__init__()

    def cast_spell(self, player_index, spell_name, now):
        player = self.players[player_index]
        spell = SPELLS[spell_name]

        if self.winner is not None or not player.alive():
            return False
        if now < player.silenced_until:
            player.last_message = "SILENCED"
            player.message_until = now + 0.6
            return False
        if now < player.spell_cooldown_until[spell_name]:
            player.last_message = "SPELL CD"
            player.message_until = now + 0.6
            return False
        if player.mana < spell["mana"]:
            player.last_message = "NO MANA"
            player.message_until = now + 0.6
            return False

        player.mana -= spell["mana"]
        player.spell_cooldown_until[spell_name] = now + spell["cooldown"]
        player.last_spell = spell["full"]
        player.last_message = "CAST " + spell["label"]
        player.message_until = now + 0.9

        if spell["kind"] == "projectile":
            start = player.wand_pos()
            direction = np.array([1.0, 0.0], dtype=np.float32)
            if player.side == "right":
                direction = np.array([-1.0, 0.0], dtype=np.float32)
            if now < player.frozen_until:
                speed = spell["speed"] * 0.6
            else:
                speed = spell["speed"]
            proj = Projectile(
                owner=player_index,
                spell=spell_name,
                pos=start.copy(),
                vel=direction * speed,
                radius=spell["radius"],
                damage=spell["damage"],
                color=spell["color"],
            )
            self.projectiles.append(proj)
            self.spawn_burst(start, spell["color"], 18, 90)

        elif spell["kind"] == "shield":
            player.shield_value = spell["shield_value"]
            player.shield_until = now + spell["duration"]
            self.spawn_burst(player.center(), spell["color"], 26, 120)

        elif spell["kind"] == "heal":
            player.healing_until = now + spell["channel"]
            player.pending_heal = spell["heal"]
            self.spawn_burst(player.center(), spell["color"], 30, 80)

        return True

    def update(self, dt, now):
        for player in self.players:
            if player.alive():
                player.mana = min(MAX_MANA, player.mana + MANA_REGEN_PER_SEC * dt)

            if player.pending_heal > 0 and now >= player.healing_until:
                player.hp = min(MAX_HP, player.hp + player.pending_heal)
                player.pending_heal = 0
                player.last_message = "HEALED"
                player.message_until = now + 0.8
                self.spawn_burst(player.center(), SPELLS["lumos"]["color"], 45, 150)
            elif player.is_healing(now):
                self.spawn_lumos_channel(player, now)

            if now >= player.shield_until:
                player.shield_value = 0

        for proj in self.projectiles:
            if not proj.active:
                continue
            proj.pos += proj.vel * dt
            proj.life -= dt
            if proj.life <= 0 or proj.pos[0] < -80 or proj.pos[0] > WIDTH + 80:
                proj.active = False
                continue

            self.spawn_trail(proj)

        self.resolve_projectile_collisions(now)
        self.resolve_hits(now)
        self.projectiles = [p for p in self.projectiles if p.active]

        for particle in self.particles:
            particle.pos += particle.vel * dt
            particle.vel *= 0.96
            particle.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]

        for player in self.players:
            if player.hp <= 0 and self.winner is None:
                self.winner = 1 - player.pid
                self.spawn_burst(player.center(), (255, 255, 255), 80, 260)

    def resolve_projectile_collisions(self, now):
        for i, a in enumerate(self.projectiles):
            if not a.active:
                continue
            for b in self.projectiles[i + 1 :]:
                if not b.active or a.owner == b.owner:
                    continue
                dist = np.linalg.norm(a.pos - b.pos)
                if dist > a.radius + b.radius:
                    continue

                pair = {a.spell, b.spell}
                mid = (a.pos + b.pos) / 2
                if pair == {"incendio", "stupefy"}:
                    fire = a if a.spell == "incendio" else b
                    stun = b if fire is a else a
                    stun.active = False
                    fire.damage *= 0.75
                    fire.radius *= 0.9
                    self.spawn_burst(mid, (70, 165, 255), 42, 190)
                elif pair == {"stupefy", "glacius"}:
                    stun = a if a.spell == "stupefy" else b
                    ice = b if stun is a else a
                    ice.active = False
                    stun.damage *= 0.75
                    stun.vel *= 0.85
                    self.spawn_burst(mid, (220, 130, 255), 42, 180)
                elif pair == {"incendio", "glacius"}:
                    ice = a if a.spell == "glacius" else b
                    fire = b if ice is a else a
                    fire.active = False
                    ice.damage *= 0.8
                    ice.vel *= 0.9
                    self.spawn_burst(mid, (210, 230, 240), 52, 210)
                else:
                    a.active = False
                    b.active = False
                    color = (170, 210, 255)
                    if pair == {"incendio"}:
                        color = (80, 170, 255)
                    elif pair == {"glacius"}:
                        color = (255, 230, 130)
                    self.spawn_burst(mid, color, 55, 210)

    def resolve_hits(self, now):
        for proj in self.projectiles:
            if not proj.active:
                continue
            target = self.players[1 - proj.owner]
            if not target.alive():
                continue

            if target.has_shield(now) and self.projectile_touches_shield(proj, target):
                self.apply_shield_hit(target, proj, now)
                proj.active = False
                continue

            if circle_hits_rect(proj.pos, proj.radius, target.target_body_rect()):
                self.apply_player_hit(target, proj, now)
                proj.active = False

    def apply_shield_hit(self, target, proj, now):
        if proj.spell == "glacius":
            target.shield_value -= 20
            target.shield_until = max(now, target.shield_until - 1.5)
            self.spawn_burst(proj.pos, SPELLS["glacius"]["color"], 42, 190)
        elif proj.spell == "stupefy":
            target.shield_value -= 20
            self.spawn_burst(proj.pos, SPELLS["stupefy"]["color"], 36, 160)
        else:
            target.shield_value -= proj.damage
            self.spawn_burst(proj.pos, proj.color, 36, 170)

        target.last_message = "SHIELD HIT"
        target.message_until = now + 0.7
        if target.shield_value <= 0:
            target.shield_value = 0
            target.shield_until = 0
            self.spawn_burst(target.center(), (255, 255, 255), 45, 220)

    def apply_player_hit(self, target, proj, now):
        damage = proj.damage
        if target.is_healing(now) and proj.spell in ("incendio", "stupefy"):
            target.pending_heal = 0
            target.healing_until = 0
            if proj.spell == "incendio":
                damage += 6
            target.last_message = "HEAL INTERRUPTED"
        else:
            target.last_message = "HIT " + SPELLS[proj.spell]["label"]

        target.hp = max(0.0, target.hp - damage)
        target.message_until = now + 0.9

        if proj.spell == "stupefy":
            target.silenced_until = max(target.silenced_until, now + SPELLS["stupefy"]["silence"])
        elif proj.spell == "glacius":
            target.frozen_until = max(target.frozen_until, now + SPELLS["glacius"]["frozen"])
            target.last_message = "CHILLED"

        self.spawn_burst(proj.pos, proj.color, 55, 240)

    def projectile_touches_shield(self, proj, target):
        center = target.center()
        shield_x = center[0] + (105 if target.side == "left" else -105)
        shield_center = np.array([shield_x, center[1] - 15], dtype=np.float32)
        return np.linalg.norm(proj.pos - shield_center) < 115 + proj.radius

    def spawn_trail(self, proj):
        color = proj.color
        for _ in range(2):
            jitter = np.array(
                [random.uniform(-8, 8), random.uniform(-8, 8)], dtype=np.float32
            )
            vel = -proj.vel * 0.06 + np.array(
                [random.uniform(-35, 35), random.uniform(-35, 35)], dtype=np.float32
            )
            self.particles.append(
                Particle(
                    pos=proj.pos + jitter,
                    vel=vel,
                    color=color,
                    radius=random.uniform(2, 6),
                    life=random.uniform(0.25, 0.55),
                    max_life=0.55,
                )
            )

    def spawn_lumos_channel(self, player, now):
        center = player.center()
        for _ in range(3):
            ang = random.uniform(0, math.tau)
            radius = random.uniform(50, 105)
            pos = center + np.array(
                [math.cos(ang) * radius, math.sin(ang) * radius],
                dtype=np.float32,
            )
            outward = pos - center
            norm = max(np.linalg.norm(outward), 1)
            vel = outward / norm * random.uniform(18, 55)
            self.particles.append(
                Particle(
                    pos=pos,
                    vel=vel,
                    color=SPELLS["lumos"]["color"],
                    radius=random.uniform(2, 7),
                    life=random.uniform(0.35, 0.75),
                    max_life=0.75,
                )
            )

    def spawn_burst(self, pos, color, count, speed):
        for _ in range(count):
            ang = random.uniform(0, math.tau)
            mag = random.uniform(speed * 0.25, speed)
            vel = np.array([math.cos(ang) * mag, math.sin(ang) * mag], dtype=np.float32)
            self.particles.append(
                Particle(
                    pos=np.array(pos, dtype=np.float32),
                    vel=vel,
                    color=color,
                    radius=random.uniform(2, 8),
                    life=random.uniform(0.35, 0.9),
                    max_life=0.9,
                )
            )


def circle_hits_rect(pos, radius, rect):
    x1, y1, x2, y2 = rect
    cx = min(max(pos[0], x1), x2)
    cy = min(max(pos[1], y1), y2)
    return (pos[0] - cx) ** 2 + (pos[1] - cy) ** 2 <= radius**2


def draw_glow_circle(frame, center, radius, color, alpha=0.35, layers=4):
    overlay = frame.copy()
    for i in range(layers, 0, -1):
        r = int(radius * i / layers)
        cv2.circle(overlay, tuple(np.int32(center)), r, color, -1, lineType=cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def draw_bar(frame, x, y, w, h, value, max_value, color, label):
    cv2.rectangle(frame, (x, y), (x + w, y + h), (35, 35, 42), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (115, 115, 125), 1)
    fill = int(w * max(0, min(1, value / max_value)))
    if fill > 0:
        cv2.rectangle(frame, (x, y), (x + fill, y + h), color, -1)
    cv2.putText(
        frame,
        f"{label} {int(value):03d}",
        (x + 8, y + h - 6),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )


def draw_player(frame, player, now):
    center = player.center()
    body_color = (210, 210, 220) if player.alive() else (70, 70, 80)
    x1, y1, x2, y2 = player.target_body_rect()
    cv2.ellipse(frame, tuple(np.int32(center)), (58, 110), 0, 0, 360, body_color, 2, cv2.LINE_AA)
    cv2.circle(frame, (int(center[0]), int(center[1] - 145)), 34, body_color, 2, cv2.LINE_AA)

    wand = player.wand_pos()
    hand = center + np.array([35 if player.side == "left" else -35, -35], dtype=np.float32)
    cv2.line(frame, tuple(np.int32(hand)), tuple(np.int32(wand)), (230, 230, 235), 4, cv2.LINE_AA)
    cv2.circle(frame, tuple(np.int32(wand)), 8, (255, 255, 255), -1, cv2.LINE_AA)

    if player.is_healing(now):
        phase = 0.5 + 0.5 * math.sin(now * 10)
        lumos_color = SPELLS["lumos"]["color"]
        draw_glow_circle(frame, center, 115 + 24 * phase, lumos_color, 0.38, 6)
        draw_glow_circle(frame, wand, 48 + 10 * phase, lumos_color, 0.45, 4)
        cv2.circle(frame, tuple(np.int32(center)), int(86 + 16 * phase), lumos_color, 2, cv2.LINE_AA)
        cv2.circle(frame, tuple(np.int32(center)), int(122 + 20 * (1 - phase)), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, tuple(np.int32(wand)), tuple(np.int32(center)), lumos_color, 2, cv2.LINE_AA)
        cv2.putText(
            frame,
            "CHANNELING",
            (int(center[0] - 70), int(center[1] + 155)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (240, 255, 255),
            1,
            cv2.LINE_AA,
        )

    if now < player.frozen_until:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 225, 130), 2, cv2.LINE_AA)
        cv2.putText(frame, "FROZEN", (x1 + 15, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 225, 130), 2, cv2.LINE_AA)

    if now < player.silenced_until:
        cv2.putText(frame, "SILENCED", (x1 + 5, y2 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 80, 255), 2, cv2.LINE_AA)


def draw_shield(frame, player, now):
    if not player.has_shield(now):
        return
    center = player.center()
    shield_x = center[0] + (105 if player.side == "left" else -105)
    shield_center = (int(shield_x), int(center[1] - 15))
    start, end = (-65, 65) if player.side == "left" else (115, 245)
    alpha = 0.35 + 0.12 * math.sin(now * 12)
    overlay = frame.copy()
    cv2.ellipse(
        overlay,
        shield_center,
        (95, 150),
        0,
        start,
        end,
        SPELLS["protego"]["color"],
        18,
        cv2.LINE_AA,
    )
    cv2.ellipse(
        overlay,
        shield_center,
        (70, 120),
        0,
        start,
        end,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.putText(
        frame,
        f"SHIELD {int(player.shield_value)}",
        (shield_center[0] - 55, shield_center[1] - 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (245, 245, 255),
        1,
        cv2.LINE_AA,
    )


def draw_projectile(frame, proj, now):
    c = tuple(np.int32(proj.pos))
    color = proj.color
    if proj.spell == "incendio":
        draw_glow_circle(frame, proj.pos, proj.radius * 2.2, color, 0.24, 4)
        cv2.circle(frame, c, int(proj.radius), (70, 220, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.45), (255, 255, 255), -1, cv2.LINE_AA)
    elif proj.spell == "stupefy":
        end = proj.pos - proj.vel / max(np.linalg.norm(proj.vel), 1) * 80
        cv2.line(frame, tuple(np.int32(end)), c, color, 10, cv2.LINE_AA)
        for _ in range(3):
            jitter = np.array([random.uniform(-15, 15), random.uniform(-15, 15)])
            cv2.line(frame, tuple(np.int32(end + jitter)), c, (180, 180, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.75), (255, 255, 255), -1, cv2.LINE_AA)
    elif proj.spell == "glacius":
        draw_glow_circle(frame, proj.pos, proj.radius * 2.0, color, 0.18, 4)
        points = []
        for k in range(8):
            ang = now * 4 + k * math.tau / 8
            points.append(
                (
                    int(proj.pos[0] + math.cos(ang) * proj.radius),
                    int(proj.pos[1] + math.sin(ang) * proj.radius),
                )
            )
        cv2.polylines(frame, [np.array(points, dtype=np.int32)], True, color, 3, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.45), (255, 255, 255), -1, cv2.LINE_AA)


def draw_particles(frame, particles):
    overlay = frame.copy()
    for particle in particles:
        t = max(0.0, min(1.0, particle.life / particle.max_life))
        radius = max(1, int(particle.radius * t))
        color = tuple(int(c * t + 20 * (1 - t)) for c in particle.color)
        cv2.circle(overlay, tuple(np.int32(particle.pos)), radius, color, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)


def draw_menu(frame, cv_status, fps, tick):
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), (10, 10, 18), -1)
    cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)

    pulse = 0.5 + 0.5 * math.sin(tick * 0.04)
    center = np.array([WIDTH // 2, HEIGHT // 2 - 95], dtype=np.float32)
    draw_glow_circle(frame, center, 130 + 18 * pulse, (90, 170, 255), 0.18, 5)
    cv2.putText(frame, "SPELLS", (WIDTH // 2 - 145, 165), cv2.FONT_HERSHEY_DUPLEX, 2.0, (245, 245, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "Vision-Based Magic Casting System", (WIDTH // 2 - 255, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (220, 225, 235), 1, cv2.LINE_AA)

    draw_menu_option(frame, 285, 300, "1", "Solo Spell Showcase", "Practice and demonstrate every spell with CV or keyboard.")
    draw_menu_option(frame, 285, 415, "2", "Duel Battle Mode", "Two players cast spells, collide projectiles, use HP, Mana, shield and cooldowns.")

    cv2.putText(frame, "ESC quit", (36, HEIGHT - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (225, 225, 235), 1, cv2.LINE_AA)
    cv2.putText(frame, f"{cv_status}   FPS {fps:04.1f}", (WIDTH - 360, HEIGHT - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (205, 225, 240), 1, cv2.LINE_AA)


def draw_menu_option(frame, x, y, key, title, subtitle):
    cv2.rectangle(frame, (x, y), (x + 710, y + 82), (26, 28, 38), -1)
    cv2.rectangle(frame, (x, y), (x + 710, y + 82), (120, 125, 145), 1)
    cv2.circle(frame, (x + 45, y + 41), 26, (70, 120, 210), -1, cv2.LINE_AA)
    cv2.putText(frame, key, (x + 35, y + 51), cv2.FONT_HERSHEY_DUPLEX, 0.95, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, title, (x + 92, y + 34), cv2.FONT_HERSHEY_DUPLEX, 0.82, (245, 245, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, subtitle, (x + 92, y + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (205, 210, 220), 1, cv2.LINE_AA)


def draw_solo_overlay(frame, game, now, cv_status):
    cv2.putText(frame, "Training Dummy", (int(game.players[1].center()[0] - 92), int(game.players[1].center()[1] + 155)), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 230), 1, cv2.LINE_AA)
    draw_spell_guide(frame, game.players[0], now)


def draw_spell_guide(frame, player, now):
    x = 28
    y = 250
    w = 350
    h = 240
    cv2.rectangle(frame, (x, y), (x + w, y + h), (18, 20, 28), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (105, 110, 130), 1)
    cv2.putText(frame, "Spell Guide", (x + 14, y + 28), cv2.FONT_HERSHEY_DUPLEX, 0.68, (245, 245, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, "Finger or colored wand-tip spells + open palm shield", (x + 14, y + 52), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (190, 205, 220), 1, cv2.LINE_AA)

    rows = [
        ("INC", "Incendio", "push toward opponent"),
        ("STU", "Stupefy", "multi-zigzag lightning"),
        ("GLA", "Glacius", "downward ice slash"),
        ("PRO", "Protego", "open palm hold"),
        ("LUM", "Lumos", "quick upward flick"),
    ]
    for idx, (label, name, gesture) in enumerate(rows):
        spell_key = {
            "INC": "incendio",
            "STU": "stupefy",
            "GLA": "glacius",
            "PRO": "protego",
            "LUM": "lumos",
        }[label]
        yy = y + 82 + idx * 30
        cd = max(0.0, player.spell_cooldown_until[spell_key] - now)
        enough_mana = player.mana >= SPELLS[spell_key]["mana"]
        ready = cd <= 0 and enough_mana
        color = (80, 165, 95) if ready else (85, 85, 96)
        cv2.rectangle(frame, (x + 14, yy - 18), (x + 58, yy + 5), color, -1)
        cv2.putText(frame, label, (x + 21, yy - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (245, 245, 245), 1, cv2.LINE_AA)
        cd_text = "READY" if ready else (f"CD {cd:0.1f}" if cd > 0 else "NO MP")
        cv2.putText(frame, f"{name}: {gesture}", (x + 70, yy - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 232, 238), 1, cv2.LINE_AA)
        cv2.putText(frame, cd_text, (x + 270, yy - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (210, 225, 235), 1, cv2.LINE_AA)


def draw_hud(frame, game, now, fps, cv_status="CV OFF", title="SPELLS BATTLE MVP", footer_left=None, footer_right=None):
    cv2.line(frame, (WIDTH // 2, 0), (WIDTH // 2, HEIGHT), (230, 230, 240), 2, cv2.LINE_AA)
    cv2.putText(frame, title, (WIDTH // 2 - 155, 36), cv2.FONT_HERSHEY_DUPLEX, 0.85, (245, 245, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"FPS {fps:04.1f}", (WIDTH // 2 - 45, HEIGHT - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 210, 220), 1, cv2.LINE_AA)
    cv2.putText(frame, cv_status, (WIDTH // 2 - 120, HEIGHT - 44), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 230, 245), 1, cv2.LINE_AA)

    for player in game.players:
        if player.side == "left":
            x = 28
            align_right = False
        else:
            x = WIDTH - 348
            align_right = True
        y = 24
        cv2.putText(frame, player.name, (x, y + 18), cv2.FONT_HERSHEY_DUPLEX, 0.75, (245, 245, 255), 1, cv2.LINE_AA)
        draw_bar(frame, x, y + 32, 320, 24, player.hp, MAX_HP, (65, 65, 235), "HP")
        draw_bar(frame, x, y + 62, 320, 20, player.mana, MAX_MANA, (235, 185, 70), "MANA")
        shield_max = SPELLS["protego"]["shield_value"]
        shield_value = player.shield_value if player.has_shield(now) else 0
        draw_bar(frame, x, y + 88, 320, 16, shield_value, shield_max, SPELLS["protego"]["color"], "SH")

        silence = max(0.0, player.silenced_until - now)
        cv2.putText(frame, f"Silence {silence:0.1f}s", (x, y + 126), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 235), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Last: {player.last_spell}", (x, y + 150), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 235), 1, cv2.LINE_AA)

        sx = x
        sy = y + 168
        for idx, spell_name in enumerate(["incendio", "stupefy", "glacius", "protego", "lumos"]):
            spell = SPELLS[spell_name]
            cd = max(0.0, player.spell_cooldown_until[spell_name] - now)
            enough_mana = player.mana >= spell["mana"]
            ready = cd <= 0 and enough_mana and now >= player.silenced_until
            color = (70, 150, 85) if ready else (65, 65, 72)
            if not enough_mana:
                color = (55, 55, 90)
            bx = sx + idx * 63
            cv2.rectangle(frame, (bx, sy), (bx + 58, sy + 42), color, -1)
            cv2.rectangle(frame, (bx, sy), (bx + 58, sy + 42), (150, 150, 160), 1)
            cv2.putText(frame, spell["label"], (bx + 7, sy + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (245, 245, 245), 1, cv2.LINE_AA)
            text = "RDY" if cd <= 0 else f"{cd:0.1f}"
            cv2.putText(frame, text, (bx + 7, sy + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (245, 245, 245), 1, cv2.LINE_AA)

        if now < player.message_until:
            msg_x = int(player.center()[0] - 80)
            msg_y = int(player.center()[1] - 190)
            cv2.putText(frame, player.last_message, (msg_x, msg_y), cv2.FONT_HERSHEY_DUPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)

    if footer_left is None:
        footer_left = "P1 Q/W/E/R/T = INC/STU/GLA/PRO/LUM   V finger/wand   C lock wand color"
    if footer_right is None:
        footer_right = "P2 U/I/O/P/L = INC/STU/GLA/PRO/LUM   SPACE reset   M menu   ESC quit"
    cv2.putText(frame, footer_left, (26, HEIGHT - 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 235), 1, cv2.LINE_AA)
    cv2.putText(frame, footer_right, (WIDTH - 650, HEIGHT - 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 235), 1, cv2.LINE_AA)

    if game.winner is not None:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), (15, 15, 22), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        text = f"{game.players[game.winner].name} WINS"
        cv2.putText(frame, text, (WIDTH // 2 - 150, HEIGHT // 2), cv2.FONT_HERSHEY_DUPLEX, 1.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, "Press SPACE to restart", (WIDTH // 2 - 150, HEIGHT // 2 + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (230, 230, 235), 1, cv2.LINE_AA)


def prepare_frame(cap, tick):
    ret, frame = cap.read() if cap is not None else (False, None)
    if ret:
        frame = cv2.flip(frame, 1)
        frame = cv2.resize(frame, (WIDTH, HEIGHT))
    else:
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        x = np.linspace(0, 1, WIDTH, dtype=np.float32)
        y = np.linspace(0, 1, HEIGHT, dtype=np.float32)[:, None]
        frame[:, :, 0] = (24 + 18 * y).astype(np.uint8)
        frame[:, :, 1] = (18 + 24 * x).astype(np.uint8)
        frame[:, :, 2] = (28 + 12 * np.sin(tick * 0.03)).astype(np.uint8)

    dark = np.zeros_like(frame)
    dark[:, :, :] = (18, 16, 24)
    frame = cv2.addWeighted(frame, 0.62, dark, 0.38, 0)
    return frame


def print_controls():
    print("Spells")
    print("Menu: 1 Solo Showcase | 2 Duel Battle | M Menu")
    print("P1: Q Incendio | W Stupefy | E Glacius | R Protego | T Lumos")
    print("P2: U Incendio | I Stupefy | O Glacius | P Protego | L Lumos")
    print("CV: MediaPipe Hands auto-enable. V toggles finger tracking / colored wand-tip tracking.")
    print("Wand mode: put a bright yellow/green/cyan/pink marker on the tip, center it, then press C to lock its color.")
    print("SPACE reset | ESC/Quit window to exit")


def main():
    print_controls()
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    else:
        cap.release()
        cap = None
        print("Camera not available; using generated arena background.")

    game = BattleGame()
    cv_controller = CVGestureController()
    print(cv_controller.detail_status)
    mode = "menu"
    last = time.monotonic()
    fps = FPS_FALLBACK
    tick = 0
    cv_mode_notice = ""
    cv_mode_notice_until = 0.0

    while True:
        now = time.monotonic()
        dt = min(0.05, now - last)
        last = now
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1

        frame = prepare_frame(cap, tick)
        calibration_frame = frame.copy()
        tick += 1

        if mode == "menu":
            draw_menu(frame, cv_controller.status, fps, tick)
        else:
            if mode == "solo":
                cv_controller.update(frame, game, now, force_player_index=0)
            else:
                cv_controller.update(frame, game, now)

            game.update(dt, now)
            if mode == "solo":
                game.winner = None
                game.players[1].hp = MAX_HP
                game.players[1].mana = MAX_MANA

            for player in game.players:
                draw_player(frame, player, now)
            for player in game.players:
                draw_shield(frame, player, now)
            for proj in game.projectiles:
                draw_projectile(frame, proj, now)
            draw_particles(frame, game.particles)
            cv_controller.draw(frame, now)
            if mode == "solo":
                draw_hud(
                    frame,
                    game,
                    now,
                    fps,
                    cv_controller.status,
                    title="SOLO SHOWCASE",
                    footer_left="Solo: Q/W/E/R/T or CV gestures = INC/STU/GLA/PRO/LUM   V finger/wand   C lock wand color",
                    footer_right="SPACE reset   M menu   ESC quit",
                )
                draw_solo_overlay(frame, game, now, cv_controller.status)
            else:
                draw_hud(frame, game, now, fps, cv_controller.status, title="DUEL BATTLE")

        if now < cv_mode_notice_until:
            cv2.putText(frame, cv_mode_notice, (WIDTH // 2 - 150, HEIGHT // 2 + 210), cv2.FONT_HERSHEY_DUPLEX, 0.8, (90, 245, 255), 1, cv2.LINE_AA)

        cv2.imshow("Spells Battle MVP", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:
            break
        if key == ord("m"):
            mode = "menu"
            game.reset()
            cv_controller.tracks = [CVTrack(), CVTrack()]
            continue
        if key in (ord("v"), ord("V")):
            input_mode = cv_controller.toggle_input_mode()
            cv_mode_notice = f"CV MODE: {input_mode.upper()}"
            cv_mode_notice_until = now + 1.0
            print(cv_mode_notice)
            continue
        if key in (ord("c"), ord("C")) and cv_controller.input_mode == "wand":
            ok, message = cv_controller.calibrate_wand_color(calibration_frame)
            cv_mode_notice = message
            cv_mode_notice_until = now + 1.4
            print(message)
            continue
        if mode == "menu":
            if key == ord("1"):
                mode = "solo"
                game.reset()
                cv_controller.tracks = [CVTrack(), CVTrack()]
            elif key == ord("2"):
                mode = "battle"
                game.reset()
                cv_controller.tracks = [CVTrack(), CVTrack()]
            continue
        if key == ord(" "):
            game.reset()
            continue
        if key in P1_KEYS:
            spell_name = P1_KEYS[key]
            game.cast_spell(0, spell_name, now)
        elif mode == "battle" and key in P2_KEYS:
            spell_name = P2_KEYS[key]
            game.cast_spell(1, spell_name, now)

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
