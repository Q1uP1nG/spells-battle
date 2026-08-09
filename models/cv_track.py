from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Optional

import numpy as np


class CastState(Enum):
    IDLE = "IDLE"
    READY = "READY"
    RECORDING = "RECORDING"
    CLASSIFY = "CLASSIFY"
    CASTING = "CASTING"
    COOLDOWN = "COOLDOWN"
    WAIT = "WAIT"
    LOST = "LOST"


@dataclass
class CVTrack:
    points: Deque[np.ndarray] = field(default_factory=lambda: deque(maxlen=48))
    last_seen: float = 0.0
    smoothed_point: Optional[np.ndarray] = None
    last_valid_point: Optional[np.ndarray] = None
    last_valid_time: float = 0.0
    velocity: Optional[np.ndarray] = None
    missed_frames: int = 0
    idle_anchor: Optional[np.ndarray] = None
    last_motion_time: float = 0.0
    open_palm_since: float = 0.0
    last_cast_label: str = "-"
    last_cast_confidence: float = 0.0
    last_cast_until: float = 0.0
    last_prediction: str = "-"
    last_confidence: float = 0.0
    last_shadow_prediction: str = "-"
    last_shadow_confidence: float = 0.0
    last_pipeline_version: str = ""
    path_length: float = 0.0
    palm_scale: Optional[float] = None
    debug_state: str = "NO HAND"
    debug_detail: str = "show hand"
    state: CastState = CastState.IDLE
    state_detail: str = "show hand"
    last_debug_message: str = ""
    last_gesture_debug: object = None
    wand_roi: Optional[tuple] = None
    wand_raw_point: Optional[np.ndarray] = None
    wand_tracker_point: Optional[np.ndarray] = None
    wand_tracker_velocity: Optional[np.ndarray] = None
    wand_tracker_time: float = 0.0
    wand_tracker_coast_started: float = 0.0
    wand_tracker_state: str = "UNLOCKED"
    wand_tracker_confidence: float = 0.0
    wand_tracker_source: str = "none"
    wand_lost_since: float = 0.0
    wand_lk_tracker: object = None
    wand_filter: object = None
    wand_tracker_debug: object = None
    wand_debug_last_signature: object = None
    wand_debug_last_time: float = 0.0
    wand_candidate_history: object = None
    wand_hue: object = None
    wand_sat_min: float = 70.0
    wand_val_min: float = 70.0
    wand_color_bgr: object = None

    @property
    def wand_color_calibrated(self) -> bool:
        return self.wand_hue is not None

    @property
    def recording(self) -> bool:
        return self.state == CastState.RECORDING
