from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


DEFAULT_WAND_DEBUG_LOG_DIR = "logs/wand_debug"


class WandDebugLogger:
    def __init__(self, log_dir: str = DEFAULT_WAND_DEBUG_LOG_DIR, max_sessions: int = 30):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._max_sessions = max(1, int(max_sessions))
        ts = time.strftime("%Y%m%d_%H%M%S")
        self._path = self._log_dir / f"session_{ts}.jsonl"
        self._prune_old_sessions(keep_slots=self._max_sessions - 1)

    @property
    def path(self) -> Path:
        return self._path

    def log_event(self, event: Dict[str, Any]) -> None:
        try:
            line = json.dumps(event, ensure_ascii=False, default=self._json_default)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._prune_old_sessions(keep_slots=self._max_sessions)
        except Exception:
            pass

    def _prune_old_sessions(self, keep_slots: int) -> None:
        sessions = sorted(
            self._log_dir.glob("session_*.jsonl"),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        extra = len(sessions) - max(0, keep_slots)
        if extra <= 0:
            return
        for path in sessions[:extra]:
            if path == self._path:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    @staticmethod
    def _json_default(obj):
        if hasattr(obj, "tolist"):
            return obj.tolist()
        return str(obj)
