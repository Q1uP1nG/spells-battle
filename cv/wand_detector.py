import math
from dataclasses import dataclass

import cv2
import numpy as np

from cv.wand_tracking import (
    AlphaBetaFilter2D,
    DetectionResult,
    SparseLKTracker,
    WandCandidateHistory,
    choose_wand_search_roi,
    clamp01,
    dynamic_jump_limit,
)
from config import (
    CV_LOST_HOLD_TIME,
    CV_MAX_MISSED_FRAMES,
    CV_PREDICT_HOLD_TIME,
    WAND_CALIBRATION_RADIUS,
    WAND_HUE_TOLERANCE,
    WAND_MAX_AREA,
    WAND_MIN_AREA,
    WAND_MIN_CALIBRATION_PIXELS,
    WAND_MIN_SATURATION,
    WAND_MIN_VALUE,
)


CALIBRATION_PERCENTILE = 20
CALIBRATION_SATURATION_MULTIPLIER = 0.70
CALIBRATION_VALUE_MULTIPLIER = 0.60

MASK_MEDIAN_BLUR_SIZE = 5
MASK_KERNEL_SIZE = 3
MASK_OPEN_ITERATIONS = 1
MASK_CLOSE_ITERATIONS = 1

MIN_CONTOUR_BOUNDING_SIDE = 2
MAX_CONTOUR_BOUNDING_SIDE = 95
MIN_DISTANCE_FROM_PALM_SCALE = 0.45
MAX_DISTANCE_FROM_PALM_SCALE = 4.0

SATURATION_SCORE_WEIGHT = 0.45
VALUE_SCORE_WEIGHT = 0.18
HUE_SCORE_WEIGHT = 16.0
AREA_SCORE_WINDOW = 420.0
PREFERRED_MARKER_AREA = 220.0
AREA_SCORE_WEIGHT = 0.05
COMPACTNESS_SCORE_WEIGHT = 45.0
PREDICTION_SCORE_WINDOW = 220.0
PREDICTION_SCORE_WEIGHT = 0.85

PALM_LANDMARK_INDICES = [0, 5, 9, 13, 17]
MIN_PALM_SCALE = 35.0
ROI_MARGIN_SCALE = 3.2
ROI_MIN_MARGIN = 140
ROI_MAX_MARGIN = 340

MIN_PREDICT_SPEED = 80.0
MAX_PREDICT_SPEED = 2400.0

WAND_DETECT_LOCK_CONFIDENCE = 0.55
WAND_DETECT_STABLE_RELOCK_MIN_CONFIDENCE = 0.50
WAND_DETECT_RELOCK_CONFIDENCE = 0.65
WAND_LK_MIN_CONFIDENCE = 0.45
WAND_LK_MEASUREMENT_SCALE = 0.55
WAND_LK_COLOR_PATCH_RADIUS = 10
WAND_LK_COLOR_HUE_TOLERANCE_MULTIPLIER = 1.8
WAND_LK_COLOR_SATURATION_MULTIPLIER = 0.45
WAND_LK_COLOR_VALUE_MULTIPLIER = 0.35
WAND_LK_MIN_COLOR_PIXELS = 3
WAND_LK_MIN_COLOR_RATIO = 0.015
WAND_TRACK_COAST_TIME = 0.16
WAND_COAST_OUTPUT_CONFIDENCE = 0.32
WAND_TRACK_REACQUIRE_RESET_TIME = 0.35
WAND_TRACK_VELOCITY_BLEND = 0.68
WAND_TRACK_MAX_SPEED = 3200.0
WAND_TRACK_MAX_STEP = 130.0
WAND_OBSERVATION_JUMP_DISTANCE = 90.0
WAND_OBSERVATION_RELOCK_CONFIDENCE = 0.78
COMPACT_MARKER_ASPECT_MAX = 2.2

OPENCV_HUE_RANGE = 180.0
PREFERRED_CANDIDATE_MATCH_RADIUS = 28.0

# Endpoint detection thresholds
ELONGATION_RATIO_MIN = 2.5      # λ₁/λ₂ must exceed this to treat as elongated
MIN_CONTOUR_POINTS_FOR_PCA = 8  # needed for meaningful eigen-decomposition
ENDPOINT_AREA_MIN = 30
ENDPOINT_AREA_MAX = 2000


@dataclass
class WandCandidate:
    """A single wand-tip candidate from any detection strategy."""

    point: np.ndarray
    kind: str           # "blob" or "endpoint"
    score: float
    area: float
    hue_distance: float
    distance_from_palm: float
    detail: str


@dataclass
class WandDetectionDetail:
    """Structured info about the latest wand detection attempt."""

    status: str                    # "ok" | "uncalibrated" | "no_roi" | "no_candidate"
    message: str                   # UI-safe string (same as detect_tip returns)
    mask_pixels: int = 0
    contour_count: int = 0
    candidate_count: int = 0
    rejected_small: int = 0
    rejected_large: int = 0
    rejected_near_palm: int = 0
    rejected_far_hand: int = 0
    best_score: float = -1.0
    confidence: float = 0.0
    source: str = "none"
    reject_reason: str = ""
    debug: dict = None


class WandDetector:
    def __init__(self):
        self.wand_hue = None
        self.wand_sat_min = WAND_MIN_SATURATION
        self.wand_val_min = WAND_MIN_VALUE
        self.wand_color_bgr = None
        self.last_detail = WandDetectionDetail("uncalibrated", "press C to lock wand tip color")

    @property
    def is_calibrated(self):
        return self.wand_hue is not None

    def calibrate(self, frame, track=None):
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
        wand_hue = self.circular_mean_hue(hues)
        wand_sat_min = max(
            WAND_MIN_SATURATION,
            float(np.percentile(selected_sat, CALIBRATION_PERCENTILE)) * CALIBRATION_SATURATION_MULTIPLIER,
        )
        wand_val_min = max(
            WAND_MIN_VALUE,
            float(np.percentile(selected_val, CALIBRATION_PERCENTILE)) * CALIBRATION_VALUE_MULTIPLIER,
        )
        bgr_pixels = patch[mask]
        wand_color_bgr = tuple(int(v) for v in np.mean(bgr_pixels, axis=0))

        self.wand_hue = wand_hue
        self.wand_sat_min = wand_sat_min
        self.wand_val_min = wand_val_min
        self.wand_color_bgr = wand_color_bgr

        if track is not None:
            track.wand_hue = wand_hue
            track.wand_sat_min = wand_sat_min
            track.wand_val_min = wand_val_min
            track.wand_color_bgr = wand_color_bgr

        return True, f"CV WAND LOCKED H{wand_hue:0.0f}"

    def inspect_tip_candidates(self, frame, hand_landmarks, track, now, width, height):
        """Return wand candidates for ownership assignment without changing tracker state."""
        pts = np.array(
            [[lm.x * width, lm.y * height] for lm in hand_landmarks],
            dtype=np.float32,
        )
        x1, y1, x2, y2, palm_center, palm_scale = self.compute_wand_roi(pts, width, height)
        hand_roi = (x1, y1, x2, y2)
        context = {
            "ok": False,
            "hand_roi": hand_roi,
            "search_roi": hand_roi,
            "palm_center": palm_center,
            "palm_scale": palm_scale,
            "index_tip": pts[8].astype(np.float32),
            "predicted": None,
            "candidates": [],
            "message": "",
        }
        if x2 <= x1 or y2 <= y1:
            context["message"] = "wand roi empty"
            return context
        if not (track.wand_color_calibrated if hasattr(track, "wand_color_calibrated") else False) and self.wand_hue is None:
            context["message"] = "press C to lock wand tip color"
            return context

        filt = self._get_filter(track)
        predicted = filt.predict(now)
        if predicted is None:
            predicted = self.tracker_prediction_hint(track, now, width, height)

        state = getattr(track, "wand_tracker_state", "LOST")
        if state == "UNLOCKED":
            state = "LOST"
        lost_duration = self._lost_duration(track, now)
        search_roi = choose_wand_search_roi(state, frame.shape, predicted, hand_roi, lost_duration)
        detection = self._detect_marker_once(frame, search_roi, palm_center, palm_scale, predicted, track)
        context.update({
            "ok": True,
            "search_roi": search_roi,
            "predicted": predicted,
            "candidates": list((detection.debug or {}).get("candidates", [])),
            "detection": detection,
        })
        return context

    def detect_tip(self, frame, hand_landmarks, track, now, width, height, preferred_point=None):
        pts = np.array(
            [[lm.x * width, lm.y * height] for lm in hand_landmarks],
            dtype=np.float32,
        )
        x1, y1, x2, y2, palm_center, palm_scale = self.compute_wand_roi(pts, width, height)
        hand_roi = (x1, y1, x2, y2)
        track.wand_roi = hand_roi
        track.wand_raw_point = None
        if x2 <= x1 or y2 <= y1:
            self.last_detail = WandDetectionDetail("no_roi", "wand roi empty")
            return None, "wand roi empty"

        if not (track.wand_color_calibrated if hasattr(track, "wand_color_calibrated") else False) and self.wand_hue is None:
            self.last_detail = WandDetectionDetail("uncalibrated", "press C to lock wand tip color")
            return None, "press C to lock wand tip color"

        filt = self._get_filter(track)
        predicted = filt.predict(now)
        if predicted is None:
            predicted = self.tracker_prediction_hint(track, now, width, height)

        state = getattr(track, "wand_tracker_state", "LOST")
        if state == "UNLOCKED":
            state = "LOST"
        lost_duration = self._lost_duration(track, now)
        search_roi = choose_wand_search_roi(state, frame.shape, predicted, hand_roi, lost_duration)
        track.wand_roi = search_roi

        detection = self._detect_marker_once(
            frame, search_roi, palm_center, palm_scale, predicted, track,
        )
        if preferred_point is not None:
            detection = self._detection_from_preferred_candidate(detection, preferred_point)
        # Always record the best candidate for stability analysis.
        if detection.ok and detection.point is not None:
            area = float(detection.debug.get("area", 0.0))
            self._get_candidate_history(track).add(
                detection.point, detection.score, area, detection.source, now,
            )

        observation_gate = self._observation_gate(detection, predicted, track, now)

        if (
            detection.ok
            and observation_gate != "reject_jump"
            and self._accept_detection(detection, state, track, now)
        ):
            if state == "LOST" or observation_gate == "strong_relock":
                filt.reset()
            raw_point = detection.point.copy()
            point = filt.update(detection.point, now, detection.score)
            detection.debug["raw_filtered_delta"] = float(np.linalg.norm(point - raw_point))
            lk = self._get_lk_tracker(track)
            lk.initialize(frame, point, detection.bbox)
            if observation_gate == "strong_relock":
                msg = f"wand relock strong conf {detection.score:0.2f}"
            elif state == "LOST" and detection.score < WAND_DETECT_RELOCK_CONFIDENCE:
                msg = f"wand relock stable conf {detection.score:0.2f}"
            elif detection.source == "endpoint":
                msg = (
                    f"wand endpoint detector conf {detection.score:0.2f} "
                    f"area {detection.debug.get('area', 0):0.0f}"
                )
            else:
                msg = (
                    f"wand locked detector conf {detection.score:0.2f} "
                    f"area {detection.debug.get('area', 0):0.0f}"
                )
            self._mark_tracker_output(
                track, point, now, "LOCKED", "detector", detection.score, detection.debug,
            )
            track.wand_raw_point = detection.point.copy()
            self._set_last_detail_from_detection("ok", msg, detection)
            return point.astype(np.float32), msg

        lk_result = None
        if state in ("LOCKED", "FLOW", "COASTING"):
            lk_result = self._get_lk_tracker(track).update(frame)

        lk_color_ok = False
        lk_color_debug = {}
        if lk_result is not None:
            lk_color_ok, lk_color_debug = self._lk_color_support(frame, lk_result["point"], track)

        if (
            lk_result is not None
            and lk_result["confidence"] >= WAND_LK_MIN_CONFIDENCE
            and lk_color_ok
        ):
            confidence = clamp01(lk_result["confidence"] * WAND_LK_MEASUREMENT_SCALE)
            point = filt.update(lk_result["point"], now, confidence)
            debug = dict(detection.debug)
            debug.update({
                "lk_valid_points": lk_result["valid_points"],
                "lk_confidence": lk_result["confidence"],
                "fb_error_median": lk_result["fb_error_median"],
            })
            debug.update(lk_color_debug)
            msg = f"wand flow lk conf {confidence:0.2f}"
            self._mark_tracker_output(track, point, now, "FLOW", "lk", confidence, debug)
            track.wand_raw_point = point.copy()
            self._set_last_detail_from_detection("ok", msg, detection, confidence, "lk")
            return point.astype(np.float32), msg

        if lk_result is not None and not lk_color_ok:
            detection.debug.update(lk_color_debug)
            detection.debug["reject_reason"] = "lk_color"
            detection.reject_reason = "lk_color"

        # Decide whether coasting is still justified.
        pending_relock = (
            detection.ok
            and detection.score >= WAND_DETECT_LOCK_CONFIDENCE
            and observation_gate == "reject_jump"
        )
        if pending_relock:
            detection.debug["coast_policy"] = "candidate_pending_relock"

        if self._can_coast_wand(track, now):
            # If we have a promising candidate that was rejected by the jump gate,
            # coast at most one frame to avoid the yellow dot drifting forever.
            coast_started = getattr(track, "wand_tracker_coast_started", 0.0)
            if pending_relock and coast_started > 0 and now - coast_started > 0.0:
                self._mark_tracker_lost(track, now, detection)
                msg = (
                    f"NO WAND: jump {detection.debug.get('observation_jump', 0):0.0f} "
                    f"> limit {detection.debug.get('observation_jump_limit', 0):0.0f}"
                )
                self._set_last_detail_from_detection("lost", msg, detection, 0.0, "none")
                return None, msg

            point = filt.coast(now)
            if point is not None:
                debug = dict(detection.debug)
                debug["lk_valid_points"] = 0 if lk_result is None else lk_result.get("valid_points", 0)
                msg = (
                    f"wand coast pending relock conf {WAND_COAST_OUTPUT_CONFIDENCE:0.2f}"
                    if pending_relock
                    else f"wand coasting conf {WAND_COAST_OUTPUT_CONFIDENCE:0.2f}"
                )
                self._mark_tracker_output(
                    track, point, now, "COASTING", "prediction",
                    WAND_COAST_OUTPUT_CONFIDENCE, debug, good_observation=False,
                )
                track.wand_raw_point = point.copy()
                self._set_last_detail_from_detection(
                    "coasting", msg, detection, WAND_COAST_OUTPUT_CONFIDENCE, "prediction",
                )
                return point.astype(np.float32), msg

        had_previous_lock = getattr(track, "wand_tracker_time", 0.0) > 0
        self._mark_tracker_lost(track, now, detection)
        reason = detection.reject_reason or "lost"
        if had_previous_lock:
            if reason == "jump":
                msg = (
                    f"NO WAND: jump {detection.debug.get('observation_jump', 0):0.0f} "
                    f"> limit {detection.debug.get('observation_jump_limit', 0):0.0f}"
                )
            elif reason == "lk_color":
                msg = (
                    f"NO WAND: lk_color pixels "
                    f"{detection.debug.get('lk_color_pixels', 0)} < {WAND_LK_MIN_COLOR_PIXELS}"
                )
            elif reason == "low_score":
                msg = (
                    f"NO WAND: low_score {detection.debug.get('best_score', 0):0.2f} "
                    f"< relock {WAND_DETECT_RELOCK_CONFIDENCE}"
                )
            else:
                msg = f"NO WAND: lost; reject {reason}"
            detail_status = "lost"
        else:
            sx1, sy1, sx2, sy2 = search_roi
            msg = f"no bright tip in hand roi {sx2 - sx1}x{sy2 - sy1}"
            detail_status = "no_candidate"
        self._set_last_detail_from_detection(detail_status, msg, detection, 0.0, "none")
        return None, msg

    def _detection_from_preferred_candidate(self, detection, preferred_point):
        preferred = np.asarray(preferred_point, dtype=np.float32)
        candidates = list((detection.debug or {}).get("candidates", []))
        best_candidate = None
        best_distance = None

        for candidate in candidates:
            point = np.asarray(candidate.get("point"), dtype=np.float32)
            distance = float(np.linalg.norm(point - preferred))
            if distance > PREFERRED_CANDIDATE_MATCH_RADIUS:
                continue
            if best_distance is None or distance < best_distance:
                best_candidate = candidate
                best_distance = distance

        if best_candidate is None:
            if detection.debug is not None:
                detection.debug["assignment"] = "preferred_miss"
            return detection

        point = np.asarray(best_candidate["point"], dtype=np.float32)
        score = float(best_candidate.get("score", 0.0))
        source = str(best_candidate.get("source", detection.source or "blob"))
        debug = dict(detection.debug or {})
        debug.update({
            "assignment": "preferred",
            "assignment_distance": float(best_distance),
            "best_score": score,
            "area": float(best_candidate.get("area", debug.get("area", 0.0))),
            "hue_error": float(best_candidate.get("hue_distance", debug.get("hue_error", 0.0))),
            "source": source,
        })
        return DetectionResult(
            ok=True,
            point=point,
            bbox=None,
            score=score,
            source=source,
            debug=debug,
        )

    def _accept_detection(self, detection, state, track, now):
        """Decide whether a candidate observation can be accepted.

        In normal tracking we accept any candidate above the base lock threshold.
        After LOST we either need a strong single-frame candidate or a spatially
        stable lower-confidence candidate.
        """
        if not detection.ok or detection.point is None:
            return False
        score = detection.score
        if state != "LOST":
            if score < WAND_DETECT_LOCK_CONFIDENCE:
                detection.debug["reject_reason"] = "low_score"
                detection.reject_reason = "low_score"
            return score >= WAND_DETECT_LOCK_CONFIDENCE
        if score >= WAND_DETECT_RELOCK_CONFIDENCE:
            return True
        if score < WAND_DETECT_STABLE_RELOCK_MIN_CONFIDENCE:
            detection.debug["reject_reason"] = "low_score"
            detection.reject_reason = "low_score"
            return False
        # Stable low-confidence relock: score in [0.50, 0.65) with recent history.
        area = float(detection.debug.get("area", 0.0))
        if area < WAND_MIN_AREA:
            detection.debug["reject_reason"] = "area"
            detection.reject_reason = "area"
            return False
        if detection.source not in ("blob", "endpoint"):
            detection.debug["reject_reason"] = "source"
            detection.reject_reason = "source"
            return False
        history = self._get_candidate_history(track)
        stable = history.stable_near(detection.point, now, max_age=0.22, max_distance=48.0, min_count=2)
        if not stable:
            detection.debug["reject_reason"] = "unstable"
            detection.reject_reason = "unstable"
        return stable

    def _observation_gate(self, detection, predicted, track, now):
        debug = detection.debug
        debug.setdefault("observation_jump", 0.0)
        debug.setdefault("observation_gate", "accept")
        debug.setdefault("raw_filtered_delta", 0.0)
        if not detection.ok or detection.point is None or predicted is None:
            return "accept"

        velocity = getattr(track, "wand_tracker_velocity", None)
        speed = float(np.linalg.norm(velocity)) if velocity is not None else 0.0
        last_time = getattr(track, "wand_tracker_time", 0.0)
        dt = max(now - last_time, 0.0) if last_time > 0 else 0.0
        state = getattr(track, "wand_tracker_state", "LOST")
        lost_duration = self._lost_duration(track, now) if state == "LOST" else 0.0
        # In normal tracking, keep strong_relock behavior for big jumps.
        allow_score_bonus = state == "LOST"

        allowed_jump = dynamic_jump_limit(
            speed, dt, lost_duration, detection.score if allow_score_bonus else 0.0,
        )
        jump = float(np.linalg.norm(detection.point - predicted))
        debug["observation_jump"] = jump
        debug["observation_jump_limit"] = allowed_jump
        debug["observation_speed"] = speed
        debug["observation_dt"] = dt

        if (
            state == "LOST"
            and detection.score >= WAND_DETECT_STABLE_RELOCK_MIN_CONFIDENCE
            and self._get_candidate_history(track).stable_near(
                detection.point, now, max_age=0.22, max_distance=48.0, min_count=2,
            )
        ):
            debug["observation_gate"] = "stable_relock"
            return "stable_relock"

        if jump <= allowed_jump:
            debug["observation_gate"] = "accept"
            return "accept"
        if detection.score >= WAND_OBSERVATION_RELOCK_CONFIDENCE:
            debug["observation_gate"] = "strong_relock"
            return "strong_relock"

        debug["observation_gate"] = "reject_jump"
        debug["reject_reason"] = "jump"
        detection.reject_reason = "jump"
        return "reject_jump"

    def build_color_mask(self, hsv, track=None):
        wand_hue, wand_sat_min, wand_val_min = self._color_from_track(track)
        hue = hsv[:, :, 0].astype(np.float32)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        hue_distance = self.hue_distance(hue, wand_hue)
        mask = np.zeros(sat.shape, dtype=np.uint8)
        mask[
            (hue_distance <= WAND_HUE_TOLERANCE)
            & (sat >= wand_sat_min)
            & (val >= wand_val_min)
        ] = 255
        mask = cv2.medianBlur(mask, MASK_MEDIAN_BLUR_SIZE)
        kernel = np.ones((MASK_KERNEL_SIZE, MASK_KERNEL_SIZE), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=MASK_OPEN_ITERATIONS)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=MASK_CLOSE_ITERATIONS)

    def _detect_marker_once(self, frame, search_roi, palm_center, palm_scale, predicted, track=None):
        x1, y1, x2, y2 = search_roi
        debug = {
            "search_roi": search_roi,
            "predicted": None if predicted is None else [float(predicted[0]), float(predicted[1])],
            "mask_pixels": 0,
            "contour_count": 0,
            "candidate_count": 0,
            "best_score": 0.0,
            "reject_reason": "",
        }
        if x2 <= x1 or y2 <= y1:
            debug["reject_reason"] = "roi"
            return DetectionResult(False, reject_reason="roi", debug=debug)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            debug["reject_reason"] = "roi"
            return DetectionResult(False, reject_reason="roi", debug=debug)

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = self.build_color_mask(hsv, track)
        roi_offset = np.array([x1, y1], dtype=np.float32)

        best, blob_candidates = self.find_best_candidate(
            mask, hsv, palm_center, palm_scale, predicted, roi_offset, track,
        )
        detail = self.last_detail
        debug.update({
            "mask_pixels": int(detail.mask_pixels),
            "contour_count": int(detail.contour_count),
            "candidate_count": int(detail.candidate_count),
            "rejected_small": int(detail.rejected_small),
            "rejected_large": int(detail.rejected_large),
            "rejected_near_palm": int(detail.rejected_near_palm),
            "rejected_far_hand": int(detail.rejected_far_hand),
        })

        endpoint_candidates = self._detect_endpoint_candidates(
            mask, hsv, palm_center, palm_scale, predicted, roi_offset, track,
        )

        all_candidates = []
        for cand in blob_candidates:
            all_candidates.append({
                "point": [float(cand["point"][0]), float(cand["point"][1])],
                "score": float(cand["score"]),
                "area": float(cand["area"]),
                "source": cand["source"],
                "hue_distance": float(cand["hue_distance"]),
                "mean_sat": float(cand["mean_sat"]),
                "mean_val": float(cand["mean_val"]),
            })
        for ep in endpoint_candidates:
            ep_confidence = clamp01(max(0.65, ep.score / 450.0))
            all_candidates.append({
                "point": [float(ep.point[0]), float(ep.point[1])],
                "score": float(ep_confidence),
                "area": float(ep.area),
                "source": "endpoint",
                "hue_distance": float(ep.hue_distance),
                "mean_sat": 0.0,
                "mean_val": 0.0,
            })
        debug["candidates"] = all_candidates

        if best is not None and self._is_compact_marker_blob(best):
            return self._detection_from_blob(best, debug, endpoint_candidates)

        if endpoint_candidates:
            ep = endpoint_candidates[0]
            confidence = clamp01(max(0.65, ep.score / 450.0))
            debug.update({
                "candidate_count": int(debug["candidate_count"] + len(endpoint_candidates)),
                "best_score": confidence,
                "area": float(ep.area),
                "hue_error": float(ep.hue_distance),
                "source": "endpoint",
            })
            return DetectionResult(
                ok=True,
                point=ep.point.astype(np.float32),
                bbox=None,
                score=confidence,
                source="endpoint",
                debug=debug,
            )

        if best is not None:
            return self._detection_from_blob(best, debug, endpoint_candidates)

        reject_reason = self._reject_reason_from_detail(detail)
        debug["reject_reason"] = reject_reason
        return DetectionResult(False, reject_reason=reject_reason, debug=debug)

    def _is_compact_marker_blob(self, blob_candidate):
        _, _, _, _, _, bbox, _, _, confidence = blob_candidate
        x1, y1, x2, y2 = bbox
        bw = max(1.0, float(x2 - x1))
        bh = max(1.0, float(y2 - y1))
        aspect = max(bw, bh) / max(min(bw, bh), 1.0)
        return (
            aspect <= COMPACT_MARKER_ASPECT_MAX
            and confidence >= WAND_DETECT_LOCK_CONFIDENCE
        )

    def _detection_from_blob(self, blob_candidate, debug, endpoint_candidates):
        center, area, mean_sat, mean_val, useful_count, bbox, hue_dist, compactness, confidence = blob_candidate
        x1, y1, x2, y2 = bbox
        bw = max(1.0, float(x2 - x1))
        bh = max(1.0, float(y2 - y1))
        aspect = max(bw, bh) / max(min(bw, bh), 1.0)
        debug.update({
            "candidate_count": int(useful_count + len(endpoint_candidates)),
            "best_score": float(confidence),
            "area": float(area),
            "sat_mean": float(mean_sat),
            "val_mean": float(mean_val),
            "hue_error": float(hue_dist),
            "compactness": float(compactness),
            "blob_aspect": float(aspect),
            "source": "blob",
        })
        return DetectionResult(
            ok=True,
            point=center.astype(np.float32),
            bbox=bbox,
            score=float(confidence),
            source="blob",
            debug=debug,
        )

    def find_best_candidate(self, mask, hsv, palm_center, palm_scale, predicted, roi_offset, track=None):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        useful_count = 0
        rejected_small = 0
        rejected_large = 0
        rejected_near_palm = 0
        rejected_far_hand = 0
        candidates = []

        for contour in contours:
            candidate = self.score_contour(
                contour, mask, hsv, palm_center, palm_scale, predicted, roi_offset, track,
            )
            if candidate is None:
                # Determine rejection category from contour basics
                area = float(cv2.contourArea(contour))
                if area < WAND_MIN_AREA:
                    rejected_small += 1
                elif area > WAND_MAX_AREA:
                    rejected_large += 1
                else:
                    # Must be rejected for color or palm distance
                    dist = float(np.linalg.norm(
                        self._contour_center(contour) + roi_offset - palm_center))
                    if dist < palm_scale * MIN_DISTANCE_FROM_PALM_SCALE:
                        rejected_near_palm += 1
                    elif dist > palm_scale * MAX_DISTANCE_FROM_PALM_SCALE:
                        rejected_far_hand += 1
                    else:
                        rejected_small += 1  # catch-all: color/hue reject
                continue

            useful_count += 1
            score = candidate[0]
            if best is None or score > best[0]:
                best = candidate

            _, center, area, mean_sat, mean_val, bbox, hue_dist, compactness, confidence = candidate
            candidates.append({
                "point": center.astype(np.float32),
                "score": float(confidence),
                "area": float(area),
                "source": "blob",
                "hue_distance": float(hue_dist),
                "mean_sat": float(mean_sat),
                "mean_val": float(mean_val),
            })

        # Store structured diagnostics
        mask_pixels = int(np.count_nonzero(mask))
        best_score = best[0] if best is not None else -1.0
        self.last_detail = WandDetectionDetail(
            status="ok" if best is not None else "no_candidate",
            message="",
            mask_pixels=mask_pixels,
            contour_count=len(contours),
            candidate_count=useful_count,
            rejected_small=rejected_small,
            rejected_large=rejected_large,
            rejected_near_palm=rejected_near_palm,
            rejected_far_hand=rejected_far_hand,
            best_score=best_score,
        )

        if best is None:
            return None, candidates
        _, center, area, mean_sat, mean_val, bbox, hue_dist, compactness, confidence = best
        return (center, area, mean_sat, mean_val, useful_count, bbox, hue_dist, compactness, confidence), candidates

    @staticmethod
    def _contour_center(contour):
        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            return np.array([0.0, 0.0], dtype=np.float32)
        return np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
            dtype=np.float32,
        )

    def score_contour(self, contour, mask, hsv, palm_center, palm_scale, predicted, roi_offset, track=None):
        area = float(cv2.contourArea(contour))
        if area < WAND_MIN_AREA or area > WAND_MAX_AREA:
            return None

        bx, by, bw, bh = cv2.boundingRect(contour)
        if (
            bw < MIN_CONTOUR_BOUNDING_SIDE
            or bh < MIN_CONTOUR_BOUNDING_SIDE
            or max(bw, bh) > MAX_CONTOUR_BOUNDING_SIDE
        ):
            return None

        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            return None

        local_center = np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
            dtype=np.float32,
        )
        center = local_center + roi_offset
        distance_from_palm = float(np.linalg.norm(center - palm_center))
        if distance_from_palm < palm_scale * MIN_DISTANCE_FROM_PALM_SCALE:
            return None
        if distance_from_palm > palm_scale * MAX_DISTANCE_FROM_PALM_SCALE:
            return None

        wand_hue, wand_sat_min, wand_val_min = self._color_from_track(track)
        contour_mask = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(contour_mask, [contour], -1, 255, -1)
        mean_hsv = cv2.mean(hsv, mask=contour_mask)
        contour_pixels = contour_mask > 0
        mean_hue = self.circular_mean_hue(hsv[:, :, 0][contour_pixels].astype(np.float32))
        mean_hue_distance = self.hue_distance(mean_hue, wand_hue)
        mean_sat = float(mean_hsv[1])
        mean_val = float(mean_hsv[2])
        if (
            mean_hue_distance > WAND_HUE_TOLERANCE
            or mean_sat < wand_sat_min
            or mean_val < wand_val_min
        ):
            return None

        compactness = area / max(float(bw * bh), 1.0)
        score = mean_sat * SATURATION_SCORE_WEIGHT + mean_val * VALUE_SCORE_WEIGHT
        score += (WAND_HUE_TOLERANCE - mean_hue_distance) * HUE_SCORE_WEIGHT
        score += max(0.0, AREA_SCORE_WINDOW - abs(area - PREFERRED_MARKER_AREA)) * AREA_SCORE_WEIGHT
        score += compactness * COMPACTNESS_SCORE_WEIGHT
        if predicted is not None:
            distance_from_prediction = float(np.linalg.norm(center - predicted))
            score += max(0.0, PREDICTION_SCORE_WINDOW - distance_from_prediction) * PREDICTION_SCORE_WEIGHT

        bbox = (
            int(bx + roi_offset[0]),
            int(by + roi_offset[1]),
            int(bx + bw + roi_offset[0]),
            int(by + bh + roi_offset[1]),
        )
        confidence = self.normalized_candidate_confidence(
            area, mean_sat, mean_val, mean_hue_distance, compactness, center, predicted, track,
        )

        return score, center, area, mean_sat, mean_val, bbox, mean_hue_distance, compactness, confidence

    def normalized_candidate_confidence(
        self, area, mean_sat, mean_val, hue_distance, compactness, center, predicted, track=None,
    ):
        _, wand_sat_min, wand_val_min = self._color_from_track(track)
        hue_score = 1.0 - float(hue_distance) / max(float(WAND_HUE_TOLERANCE), 1.0)
        sat_score = (float(mean_sat) - float(wand_sat_min)) / max(255.0 - float(wand_sat_min), 1.0)
        val_score = (float(mean_val) - float(wand_val_min)) / max(255.0 - float(wand_val_min), 1.0)
        area_score = 1.0 - abs(float(area) - PREFERRED_MARKER_AREA) / AREA_SCORE_WINDOW
        compact_score = float(compactness)
        pred_score = 0.5
        if predicted is not None:
            dist = float(np.linalg.norm(np.asarray(center, dtype=np.float32) - predicted))
            pred_score = 1.0 - dist / PREDICTION_SCORE_WINDOW
        return clamp01(
            0.25 * clamp01(hue_score)
            + 0.20 * clamp01(sat_score)
            + 0.12 * clamp01(val_score)
            + 0.15 * clamp01(area_score)
            + 0.10 * clamp01(compact_score)
            + 0.18 * clamp01(pred_score)
        )

    @staticmethod
    def _reject_reason_from_detail(detail):
        if detail.mask_pixels <= 0:
            return "mask"
        if detail.rejected_near_palm > 0:
            return "near_palm"
        if detail.rejected_far_hand > 0:
            return "far_hand"
        if detail.rejected_small > 0:
            return "area"
        if detail.rejected_large > 0:
            return "area"
        if detail.contour_count > 0 and detail.candidate_count <= 0:
            return "low_score"
        return "no_candidate"

    # ------------------------------------------------------------------
    # Endpoint detection (colored elongated shapes)
    # ------------------------------------------------------------------

    def _detect_endpoint_candidates(self, mask, hsv, palm_center, palm_scale,
                                    predicted, roi_offset, track=None):
        """Find wand-tip candidates from elongated contours using PCA endpoint.

        Complements the blob-center strategy: when a colored marker is a strip
        or pen body rather than a dot, the farthest endpoint of the elongated
        shape is a better tip estimate.
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        candidates = []

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < ENDPOINT_AREA_MIN or area > ENDPOINT_AREA_MAX:
                continue

            bx, by, bw, bh = cv2.boundingRect(contour)
            if bw < 2 or bh < 2 or max(bw, bh) > 180:
                continue

            # Compute elongation via PCA eigenvalue ratio
            pts = contour.reshape(-1, 2).astype(np.float32)
            if len(pts) < MIN_CONTOUR_POINTS_FOR_PCA:
                continue

            center_pt = pts.mean(axis=0)
            global_center = center_pt + roi_offset
            dist_from_palm = float(np.linalg.norm(global_center - palm_center))
            if dist_from_palm < palm_scale * MIN_DISTANCE_FROM_PALM_SCALE:
                continue
            if dist_from_palm > palm_scale * MAX_DISTANCE_FROM_PALM_SCALE:
                continue

            # PCA
            centered = pts - center_pt
            cov = centered.T @ centered / len(pts)
            try:
                eigvals, eigvecs = np.linalg.eigh(cov)
            except np.linalg.LinAlgError:
                continue

            if len(eigvals) < 2:
                continue

            ratio = eigvals[-1] / max(eigvals[-2], 1e-6)
            if ratio < ELONGATION_RATIO_MIN:
                continue  # not elongated enough

            principal_axis = eigvecs[:, -1]
            projections = centered @ principal_axis
            min_idx = int(np.argmin(projections))
            max_idx = int(np.argmax(projections))
            ep1 = pts[min_idx] + roi_offset
            ep2 = pts[max_idx] + roi_offset

            # Pick the endpoint farther from palm
            d1 = float(np.linalg.norm(ep1 - palm_center))
            d2 = float(np.linalg.norm(ep2 - palm_center))
            tip = ep1 if d1 > d2 else ep2

            # Colour quality
            contour_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.drawContours(contour_mask, [contour.astype(np.int32)], -1, 255, -1)
            mean_hsv = cv2.mean(hsv, mask=contour_mask)
            hue_values = hsv[:, :, 0][contour_mask > 0].astype(np.float32)
            wand_hue, wand_sat_min, wand_val_min = self._color_from_track(track)
            mean_hue = self.circular_mean_hue(hue_values) if len(hue_values) > 0 else wand_hue or 0.0
            hue_dist = self.hue_distance(mean_hue, wand_hue or 0.0)
            mean_sat = float(mean_hsv[1])
            mean_val = float(mean_hsv[2])

            if (hue_dist > WAND_HUE_TOLERANCE
                    or mean_sat < wand_sat_min
                    or mean_val < wand_val_min):
                continue

            # Score
            score = (mean_sat * SATURATION_SCORE_WEIGHT
                     + mean_val * VALUE_SCORE_WEIGHT
                     + (WAND_HUE_TOLERANCE - hue_dist) * HUE_SCORE_WEIGHT
                     + ratio * 2.5)
            if predicted is not None:
                dist_pred = float(np.linalg.norm(tip - predicted))
                score += max(0.0, PREDICTION_SCORE_WINDOW - dist_pred) * PREDICTION_SCORE_WEIGHT

            candidates.append(WandCandidate(
                point=tip,
                kind="endpoint",
                score=score,
                area=area,
                hue_distance=hue_dist,
                distance_from_palm=dist_from_palm,
                detail=f"ratio={ratio:.1f} area={area:.0f}",
            ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    # ------------------------------------------------------------------
    # ROI & helpers
    # ------------------------------------------------------------------

    def _get_lk_tracker(self, track):
        if getattr(track, "wand_lk_tracker", None) is None:
            track.wand_lk_tracker = SparseLKTracker()
        return track.wand_lk_tracker

    def _get_filter(self, track):
        if getattr(track, "wand_filter", None) is None:
            track.wand_filter = AlphaBetaFilter2D(
                max_speed=WAND_TRACK_MAX_SPEED,
                max_step=WAND_TRACK_MAX_STEP,
            )
        return track.wand_filter

    def _get_candidate_history(self, track):
        if getattr(track, "wand_candidate_history", None) is None:
            track.wand_candidate_history = WandCandidateHistory(maxlen=5)
        return track.wand_candidate_history

    def _lost_duration(self, track, now):
        lost_since = getattr(track, "wand_lost_since", 0.0)
        if lost_since > 0:
            return max(0.0, now - lost_since)
        last_good = getattr(track, "wand_tracker_time", 0.0)
        if last_good > 0:
            return max(0.0, now - last_good)
        return 999.0

    def _can_coast_wand(self, track, now):
        last_good = getattr(track, "wand_tracker_time", 0.0)
        if last_good <= 0:
            return False
        lost_since = getattr(track, "wand_lost_since", 0.0)
        if lost_since <= 0:
            lost_since = last_good
            track.wand_lost_since = lost_since
        return 0 <= now - lost_since <= WAND_TRACK_COAST_TIME

    def _mark_tracker_output(
        self, track, point, now, state, source, confidence, debug, good_observation=True,
    ):
        point = np.asarray(point, dtype=np.float32)
        if good_observation:
            self.update_tip_tracker(track, point, now)
            track.wand_lost_since = 0.0
        else:
            track.wand_tracker_point = point.copy()
            if state == "COASTING" and getattr(track, "wand_tracker_coast_started", 0.0) <= 0:
                track.wand_tracker_coast_started = now
        track.wand_tracker_state = state
        track.wand_tracker_confidence = float(confidence)
        track.wand_tracker_source = source
        track.wand_tracker_debug = self._tracker_debug(
            state, source, confidence, point, debug, self._lost_duration(track, now),
        )

    def _mark_tracker_lost(self, track, now, detection):
        lk = getattr(track, "wand_lk_tracker", None)
        if lk is not None:
            lk.reset()
        lost_since = getattr(track, "wand_lost_since", 0.0)
        last_good = getattr(track, "wand_tracker_time", 0.0)
        if lost_since <= 0:
            track.wand_lost_since = last_good if last_good > 0 else now
        track.wand_tracker_state = "LOST"
        track.wand_tracker_confidence = 0.0
        track.wand_tracker_source = "none"
        track.wand_tracker_debug = self._tracker_debug(
            "LOST", "none", 0.0, None, detection.debug, self._lost_duration(track, now),
        )

    def _tracker_debug(self, state, source, confidence, point, debug, lost_duration):
        tracker_debug = dict(debug or {})
        tracker_debug.update({
            "state": state,
            "source": source,
            "confidence": float(confidence),
            "point": None if point is None else [float(point[0]), float(point[1])],
            "lost_duration": float(lost_duration),
        })
        tracker_debug.setdefault("lk_valid_points", 0)
        return tracker_debug

    def _set_last_detail_from_detection(
        self, status, message, detection, confidence=None, source=None,
    ):
        debug = dict(detection.debug or {})
        final_confidence = detection.score if confidence is None else confidence
        final_source = detection.source if source is None else source
        self.last_detail = WandDetectionDetail(
            status=status,
            message=message,
            mask_pixels=int(debug.get("mask_pixels", 0)),
            contour_count=int(debug.get("contour_count", 0)),
            candidate_count=int(debug.get("candidate_count", 0)),
            rejected_small=int(debug.get("rejected_small", 0)),
            rejected_large=int(debug.get("rejected_large", 0)),
            rejected_near_palm=int(debug.get("rejected_near_palm", 0)),
            rejected_far_hand=int(debug.get("rejected_far_hand", 0)),
            best_score=float(final_confidence),
            confidence=float(final_confidence),
            source=final_source,
            reject_reason=detection.reject_reason or debug.get("reject_reason", ""),
            debug=debug,
        )

    def _lk_color_support(self, frame, point, track=None):
        wand_hue, wand_sat_min, wand_val_min = self._color_from_track(track)
        point = np.asarray(point, dtype=np.float32)
        x = int(round(float(point[0])))
        y = int(round(float(point[1])))
        radius = WAND_LK_COLOR_PATCH_RADIUS
        x1 = max(0, x - radius)
        y1 = max(0, y - radius)
        x2 = min(frame.shape[1], x + radius + 1)
        y2 = min(frame.shape[0], y + radius + 1)
        debug = {
            "lk_color_pixels": 0,
            "lk_color_ratio": 0.0,
            "lk_color_sat_min": 0.0,
            "lk_color_val_min": 0.0,
            "lk_color_reject": "",
        }
        if x2 <= x1 or y2 <= y1:
            debug["lk_color_reject"] = "out_of_frame"
            return False, debug

        patch = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].astype(np.float32)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]

        hue_tol = max(
            WAND_HUE_TOLERANCE,
            WAND_HUE_TOLERANCE * WAND_LK_COLOR_HUE_TOLERANCE_MULTIPLIER,
        )
        sat_min = max(
            WAND_MIN_SATURATION,
            float(wand_sat_min) * WAND_LK_COLOR_SATURATION_MULTIPLIER,
        )
        val_min = max(
            WAND_MIN_VALUE,
            float(wand_val_min) * WAND_LK_COLOR_VALUE_MULTIPLIER,
        )
        support = (
            (self.hue_distance(hue, wand_hue) <= hue_tol)
            & (sat >= sat_min)
            & (val >= val_min)
        )
        pixels = int(np.count_nonzero(support))
        ratio = pixels / max(float(support.size), 1.0)
        debug.update({
            "lk_color_pixels": pixels,
            "lk_color_ratio": float(ratio),
            "lk_color_sat_min": float(sat_min),
            "lk_color_val_min": float(val_min),
        })
        if pixels < WAND_LK_MIN_COLOR_PIXELS:
            debug["lk_color_reject"] = "pixels"
            return False, debug
        if ratio < WAND_LK_MIN_COLOR_RATIO:
            debug["lk_color_reject"] = "ratio"
            return False, debug
        return True, debug

    def compute_wand_roi(self, pts, w, h):
        palm_points = pts[PALM_LANDMARK_INDICES]
        palm_center = palm_points.mean(axis=0)
        palm_scale = max(
            float(np.linalg.norm(pts[9] - pts[0])),
            float(np.linalg.norm(pts[5] - pts[0])),
            MIN_PALM_SCALE,
        )
        margin = int(np.clip(palm_scale * ROI_MARGIN_SCALE, ROI_MIN_MARGIN, ROI_MAX_MARGIN))
        min_xy = pts.min(axis=0)
        max_xy = pts.max(axis=0)
        x1 = int(max(0, math.floor(min_xy[0] - margin)))
        y1 = int(max(0, math.floor(min_xy[1] - margin)))
        x2 = int(min(w, math.ceil(max_xy[0] + margin)))
        y2 = int(min(h, math.ceil(max_xy[1] + margin)))
        return x1, y1, x2, y2, palm_center.astype(np.float32), palm_scale

    def predict_track_point(self, track, now, w, h):
        if track.velocity is None or track.missed_frames > CV_MAX_MISSED_FRAMES:
            return None
        dt = now - track.last_valid_time
        if dt <= 0 or dt > CV_PREDICT_HOLD_TIME:
            return None
        speed = float(np.linalg.norm(track.velocity))
        if speed < MIN_PREDICT_SPEED or speed > MAX_PREDICT_SPEED:
            return None
        predicted = track.last_valid_point + track.velocity * dt
        predicted[0] = np.clip(predicted[0], 0, w - 1)
        predicted[1] = np.clip(predicted[1], 0, h - 1)
        return predicted.astype(np.float32)

    def tracker_prediction_hint(self, track, now, w, h):
        point = getattr(track, "wand_tracker_point", None)
        last_time = getattr(track, "wand_tracker_time", 0.0)
        velocity = getattr(track, "wand_tracker_velocity", None)
        if point is not None and last_time > 0 and 0 <= now - last_time <= WAND_TRACK_COAST_TIME:
            dt = max(now - last_time, 0.0)
            if velocity is None:
                predicted = point.copy()
            else:
                predicted = point + velocity * dt
            predicted[0] = np.clip(predicted[0], 0, w - 1)
            predicted[1] = np.clip(predicted[1], 0, h - 1)
            return predicted.astype(np.float32)

        legacy = self.predict_track_point(track, now, w, h)
        if legacy is not None:
            return legacy
        if (
            track.last_valid_point is not None
            and 0 <= now - track.last_valid_time <= CV_LOST_HOLD_TIME
        ):
            return track.last_valid_point.copy()
        return None

    def update_tip_tracker(self, track, observed, now):
        observed = np.asarray(observed, dtype=np.float32)
        previous = getattr(track, "wand_tracker_point", None)
        previous_time = getattr(track, "wand_tracker_time", 0.0)
        previous_velocity = getattr(track, "wand_tracker_velocity", None)

        if (
            previous is None
            or previous_time <= 0
            or now <= previous_time
            or now - previous_time > WAND_TRACK_REACQUIRE_RESET_TIME
        ):
            velocity = np.zeros(2, dtype=np.float32)
        else:
            dt = max(now - previous_time, 1e-3)
            measured_velocity = (observed - previous) / dt
            if previous_velocity is None:
                velocity = measured_velocity
            else:
                velocity = (
                    previous_velocity * (1.0 - WAND_TRACK_VELOCITY_BLEND)
                    + measured_velocity * WAND_TRACK_VELOCITY_BLEND
                )
            speed = float(np.linalg.norm(velocity))
            if speed > WAND_TRACK_MAX_SPEED:
                velocity = velocity * (WAND_TRACK_MAX_SPEED / speed)

        track.wand_tracker_point = observed.copy()
        track.wand_tracker_velocity = velocity.astype(np.float32)
        track.wand_tracker_time = now
        track.wand_tracker_coast_started = 0.0
        track.wand_tracker_state = "LOCKED"

    def coast_tip_tracker(self, track, now, w, h):
        point = getattr(track, "wand_tracker_point", None)
        last_time = getattr(track, "wand_tracker_time", 0.0)
        if point is None or last_time <= 0:
            return None

        coast_started = getattr(track, "wand_tracker_coast_started", 0.0)
        if coast_started <= 0:
            coast_started = now
            track.wand_tracker_coast_started = coast_started
        if now - coast_started > WAND_TRACK_COAST_TIME:
            self.clear_tip_tracker(track)
            return None

        dt = now - last_time
        if dt < 0 or dt > WAND_TRACK_COAST_TIME:
            self.clear_tip_tracker(track)
            return None

        velocity = getattr(track, "wand_tracker_velocity", None)
        if velocity is None:
            predicted = point.copy()
        else:
            step = velocity * dt
            step_len = float(np.linalg.norm(step))
            if step_len > WAND_TRACK_MAX_STEP:
                step = step * (WAND_TRACK_MAX_STEP / step_len)
            predicted = point + step

        predicted[0] = np.clip(predicted[0], 0, w - 1)
        predicted[1] = np.clip(predicted[1], 0, h - 1)
        track.wand_tracker_point = predicted.astype(np.float32)
        track.wand_tracker_time = now
        track.wand_tracker_state = "COASTING"
        return track.wand_tracker_point.copy()

    def clear_tip_tracker_if_stale(self, track, now):
        last_time = getattr(track, "wand_tracker_time", 0.0)
        if last_time <= 0 or now - last_time > WAND_TRACK_COAST_TIME:
            self.clear_tip_tracker(track)

    @staticmethod
    def clear_tip_tracker(track):
        track.wand_tracker_point = None
        track.wand_tracker_velocity = None
        track.wand_tracker_time = 0.0
        track.wand_tracker_coast_started = 0.0
        track.wand_tracker_state = "LOST"
        track.wand_tracker_confidence = 0.0
        track.wand_tracker_source = "none"
        track.wand_lost_since = 0.0
        track.wand_tracker_debug = None
        if getattr(track, "wand_lk_tracker", None) is not None:
            track.wand_lk_tracker.reset()
        if getattr(track, "wand_filter", None) is not None:
            track.wand_filter.reset()
        if getattr(track, "wand_candidate_history", None) is not None:
            track.wand_candidate_history.reset()

    def point_in_roi(self, point, roi):
        x1, y1, x2, y2 = roi
        return x1 <= float(point[0]) < x2 and y1 <= float(point[1]) < y2

    def hue_distance(self, hue, target):
        distance = np.abs(np.asarray(hue, dtype=np.float32) - float(target))
        return np.minimum(distance, OPENCV_HUE_RANGE - distance)

    def circular_mean_hue(self, hues):
        hue_values = np.asarray(hues, dtype=np.float32).reshape(-1)
        if len(hue_values) == 0:
            return 0.0
        angles = hue_values * (2.0 * math.pi / OPENCV_HUE_RANGE)
        mean_angle = math.atan2(float(np.sin(angles).mean()), float(np.cos(angles).mean()))
        if mean_angle < 0:
            mean_angle += 2.0 * math.pi
        return float(mean_angle * OPENCV_HUE_RANGE / (2.0 * math.pi))

    def _color_from_track(self, track):
        """Return (wand_hue, wand_sat_min, wand_val_min) from track, falling
        back to the detector's own fields for single-player compatibility."""
        if track is not None and track.wand_color_calibrated:
            return track.wand_hue, track.wand_sat_min, track.wand_val_min
        return self.wand_hue, self.wand_sat_min, self.wand_val_min
