from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_LOG_DIR = "logs/cv_sessions"


class GestureLogger:

    def __init__(self, log_dir: str = DEFAULT_LOG_DIR):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._path = self._log_dir / f"session_{ts}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def log_gesture(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False, default=self._json_default)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    @staticmethod
    def _json_default(obj):
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return str(obj)