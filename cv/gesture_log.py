from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from cv.gesture_pipeline import GESTURE_PIPELINE_VERSION


DEFAULT_LOG_DIR = "logs/cv_sessions"
GESTURE_LOG_SCHEMA_VERSION = 2
USER_LABEL_ENV = "SPELLS_CV_USER_ID"
DEVICE_LABEL_ENV = "SPELLS_CV_DEVICE_ID"


class GestureLogger:

    def __init__(
        self,
        log_dir: str = DEFAULT_LOG_DIR,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        classifier_version: str = GESTURE_PIPELINE_VERSION,
    ):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._session_id = self._clean_label(session_id) or f"session_{ts}_{uuid.uuid4().hex[:8]}"
        self._path = self._log_dir / f"{self._session_id}.jsonl"
        self._user_id = self._clean_label(user_id or os.environ.get(USER_LABEL_ENV))
        self._device_id = self._clean_label(device_id or os.environ.get(DEVICE_LABEL_ENV))
        self._classifier_version = str(classifier_version or GESTURE_PIPELINE_VERSION)
        self._event_sequence = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def session_id(self) -> str:
        return self._session_id

    def log_gesture(self, event: Dict[str, Any]) -> None:
        try:
            prepared = self.prepare_event(event)
            line = json.dumps(prepared, ensure_ascii=False, default=self._json_default)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def prepare_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrade a legacy/internal gesture event to the append-only v2 schema."""
        prepared = dict(event)
        prepared["schema"] = GESTURE_LOG_SCHEMA_VERSION
        prepared.setdefault("session_id", self._session_id)
        if not prepared.get("sample_id"):
            self._event_sequence += 1
            attempt_id = prepared.get("attempt_id")
            sample_suffix = attempt_id if attempt_id is not None else self._event_sequence
            prepared["sample_id"] = f"{self._session_id}:{sample_suffix}"
        prepared.setdefault("input_mode", prepared.get("mode") or "unknown")
        prepared.setdefault("classifier_version", self._classifier_version)
        prepared.setdefault("dataset_partition", "development")
        prepared.setdefault(
            "review_status",
            "accepted" if prepared.get("training_status") == "accepted" else "unreviewed",
        )
        if self._user_id:
            prepared.setdefault("user_id", self._user_id)
        if self._device_id:
            prepared.setdefault("device_id", self._device_id)
        return prepared

    @staticmethod
    def _clean_label(value) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned[:64] or None

    @staticmethod
    def _json_default(obj):
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return str(obj)
