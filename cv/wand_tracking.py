from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


@dataclass
class DetectionResult:
    ok: bool
    point: Optional[np.ndarray] = None
    bbox: Optional[tuple] = None
    score: float = 0.0
    source: str = "none"
    reject_reason: str = ""
    debug: dict = field(default_factory=dict)


@dataclass
class TrackerOutput:
    ok: bool
    point: Optional[np.ndarray]
    confidence: float
    state: str
    source: str
    message: str
    debug: dict = field(default_factory=dict)


@dataclass
class WandCandidateSample:
    point: np.ndarray
    score: float
    area: float
    source: str
    timestamp: float


class WandCandidateHistory:
    """Keep recent low-confidence candidates to judge spatial stability."""

    def __init__(self, maxlen: int = 5):
        self.samples: deque[WandCandidateSample] = deque(maxlen=maxlen)

    def reset(self):
        self.samples.clear()

    def add(self, point, score: float, area: float, source: str, timestamp: float) -> None:
        self.samples.append(
            WandCandidateSample(
                point=np.asarray(point, dtype=np.float32),
                score=float(score),
                area=float(area),
                source=str(source),
                timestamp=float(timestamp),
            )
        )

    def stable_near(
        self,
        point,
        now: float,
        max_age: float = 0.22,
        max_distance: float = 48.0,
        min_count: int = 2,
    ) -> bool:
        point = np.asarray(point, dtype=np.float32)
        hits = [
            sample
            for sample in self.samples
            if now - sample.timestamp <= max_age
            and float(np.linalg.norm(sample.point - point)) <= max_distance
        ]
        return len(hits) >= min_count


def clamp01(value):
    return float(max(0.0, min(1.0, value)))


def dynamic_jump_limit(speed, dt, lost_duration, score):
    """Return an adaptive jump distance limit based on motion context."""
    base = 90.0
    speed_bonus = min(120.0, max(0.0, float(speed)) * max(float(dt), 0.0) * 0.75)
    lost_bonus = min(70.0, max(0.0, float(lost_duration)) * 260.0)
    score_bonus = 40.0 if float(score) >= 0.65 else 0.0
    return min(260.0, base + speed_bonus + lost_bonus + score_bonus)


def clip_roi(x1, y1, x2, y2, frame_shape):
    height, width = frame_shape[:2]
    left = int(max(0, min(width, round(x1))))
    top = int(max(0, min(height, round(y1))))
    right = int(max(0, min(width, round(x2))))
    bottom = int(max(0, min(height, round(y2))))
    if right < left:
        right = left
    if bottom < top:
        bottom = top
    return left, top, right, bottom


def roi_around_point(point, frame_shape, radius):
    center = np.asarray(point, dtype=np.float32)
    return clip_roi(
        center[0] - radius,
        center[1] - radius,
        center[0] + radius,
        center[1] + radius,
        frame_shape,
    )


def union_rois(rois, frame_shape):
    valid = [roi for roi in rois if roi is not None and roi[2] > roi[0] and roi[3] > roi[1]]
    if not valid:
        height, width = frame_shape[:2]
        return 0, 0, width, height
    x1 = min(roi[0] for roi in valid)
    y1 = min(roi[1] for roi in valid)
    x2 = max(roi[2] for roi in valid)
    y2 = max(roi[3] for roi in valid)
    return clip_roi(x1, y1, x2, y2, frame_shape)


def choose_wand_search_roi(state, frame_shape, predicted_point=None, hand_roi=None, lost_duration=0.0):
    if predicted_point is not None and state == "LOCKED":
        return union_rois([roi_around_point(predicted_point, frame_shape, 90), hand_roi], frame_shape)
    if predicted_point is not None and state == "FLOW":
        return union_rois([roi_around_point(predicted_point, frame_shape, 140), hand_roi], frame_shape)
    if predicted_point is not None and state == "COASTING":
        return union_rois([roi_around_point(predicted_point, frame_shape, 170), hand_roi], frame_shape)
    if state == "LOST":
        if predicted_point is not None:
            radius = 220 if lost_duration < 0.5 else 260
            return union_rois([roi_around_point(predicted_point, frame_shape, radius), hand_roi], frame_shape)
        if lost_duration < 0.5 and hand_roi is not None:
            return hand_roi
        return union_rois([hand_roi], frame_shape)
    if hand_roi is not None:
        return hand_roi
    height, width = frame_shape[:2]
    return 0, 0, width, height


class AlphaBetaFilter2D:
    def __init__(self, alpha=0.82, beta=0.26, max_speed=3200.0, max_step=130.0):
        self.alpha = alpha
        self.beta = beta
        self.max_speed = max_speed
        self.max_step = max_step
        self.x = None
        self.v = np.zeros(2, dtype=np.float32)
        self.t = None

    def reset(self):
        self.x = None
        self.v = np.zeros(2, dtype=np.float32)
        self.t = None

    def predict(self, timestamp):
        if self.x is None or self.t is None:
            return None
        dt = max(float(timestamp - self.t), 1e-3)
        step = self._limited_step(self.v * dt)
        return (self.x + step).astype(np.float32)

    def update(self, measured_point, timestamp, measurement_confidence=1.0):
        confidence = clamp01(measurement_confidence)
        measured = np.asarray(measured_point, dtype=np.float32)
        if self.x is None or self.t is None:
            self.x = measured.copy()
            self.v = np.zeros(2, dtype=np.float32)
            self.t = timestamp
            return self.x.copy()

        dt = max(float(timestamp - self.t), 1e-3)
        predicted = self.x + self._limited_step(self.v * dt)
        residual = measured - predicted
        self.x = predicted + (self.alpha * confidence) * residual
        self.v = self.v + (self.beta * confidence) * residual / dt
        speed = float(np.linalg.norm(self.v))
        if speed > self.max_speed:
            self.v = self.v * (self.max_speed / speed)
        self.t = timestamp
        return self.x.copy()

    def coast(self, timestamp):
        predicted = self.predict(timestamp)
        if predicted is None:
            return None
        self.x = predicted.copy()
        self.t = timestamp
        return self.x.copy()

    def _limited_step(self, step):
        step = np.asarray(step, dtype=np.float32)
        length = float(np.linalg.norm(step))
        if length > self.max_step:
            return step * (self.max_step / length)
        return step


class SparseLKTracker:
    def __init__(self):
        self.prev_gray = None
        self.prev_pts = None
        self.prev_center = None

    def reset(self):
        self.prev_gray = None
        self.prev_pts = None
        self.prev_center = None

    def initialize(self, frame_bgr, center, bbox=None):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        center = np.asarray(center, dtype=np.float32)
        if bbox is not None:
            x1, y1, x2, y2 = bbox
            pad = 16
            x1, y1, x2, y2 = clip_roi(x1 - pad, y1 - pad, x2 + pad, y2 + pad, gray.shape)
        else:
            x1, y1, x2, y2 = roi_around_point(center, gray.shape, 18)

        mask = np.zeros((height, width), dtype=np.uint8)
        mask[y1:y2, x1:x2] = 255
        pts = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=20,
            qualityLevel=0.01,
            minDistance=3,
            blockSize=5,
            mask=mask,
        )

        self.prev_gray = gray
        self.prev_pts = pts
        self.prev_center = center.copy()

    def update(self, frame_bgr):
        if self.prev_gray is None or self.prev_pts is None or len(self.prev_pts) < 3:
            return None

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self.prev_gray,
            gray,
            self.prev_pts,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03),
        )
        if next_pts is None or status is None:
            return None

        back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(
            gray,
            self.prev_gray,
            next_pts,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03),
        )
        if back_pts is None or back_status is None:
            return None

        prev = self.prev_pts.reshape(-1, 2)
        nxt = next_pts.reshape(-1, 2)
        back = back_pts.reshape(-1, 2)
        valid = status.reshape(-1).astype(bool) & back_status.reshape(-1).astype(bool)
        fb_error = np.linalg.norm(prev - back, axis=1)
        valid = valid & (fb_error < 2.5)
        valid_count = int(np.count_nonzero(valid))
        if valid_count < 3:
            return None

        flow = nxt[valid] - prev[valid]
        median_flow = np.median(flow, axis=0).astype(np.float32)
        new_center = self.prev_center + median_flow
        median_error = float(np.median(fb_error[valid]))
        confidence = clamp01((valid_count / 6.0) * float(np.exp(-median_error / 4.0)))

        self.prev_gray = gray
        self.prev_pts = nxt[valid].reshape(-1, 1, 2).astype(np.float32)
        self.prev_center = new_center.astype(np.float32)

        return {
            "point": self.prev_center.copy(),
            "confidence": confidence,
            "valid_points": valid_count,
            "median_flow": median_flow.copy(),
            "fb_error_median": median_error,
        }
