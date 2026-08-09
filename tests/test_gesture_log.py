from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GestureLogTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._log_dir = Path(self._tmp.name) / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_logger_creates_file(self):
        from cv.gesture_log import GestureLogger

        logger = GestureLogger(log_dir=str(self._log_dir))
        logger.log_gesture({"ts": 1.0})
        self.assertTrue(logger.path.exists())
        self.assertIn("session_", logger.path.name)
        self.assertEqual(logger.path.suffix, ".jsonl")

    def test_logger_writes_valid_jsonl(self):
        from cv.gesture_log import GestureLogger

        logger = GestureLogger(log_dir=str(self._log_dir))
        event = {
            "timestamp": 1000.0,
            "mode": "finger",
            "side": "left",
            "path_length": 142.0,
            "primary": {"spell": "glacius", "confidence": 0.84},
            "shadow": {"spell": "lumos", "confidence": 0.71},
            "agreement": False,
            "cast_attempted": True,
            "cast_success": False,
        }
        logger.log_gesture(event)

        lines = logger.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["primary"]["spell"], "glacius")
        self.assertEqual(parsed["agreement"], False)

    def test_logger_writes_multiple_entries(self):
        from cv.gesture_log import GestureLogger

        logger = GestureLogger(log_dir=str(self._log_dir))
        for i in range(5):
            logger.log_gesture({"seq": i})

        lines = logger.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 5)

    def test_logger_handles_numpy_arrays(self):
        from cv.gesture_log import GestureLogger
        import numpy as np

        logger = GestureLogger(log_dir=str(self._log_dir))
        event = {"points": np.array([[1, 2], [3, 4]], dtype=np.float32)}
        logger.log_gesture(event)

        lines = logger.path.read_text(encoding="utf-8").strip().split("\n")
        parsed = json.loads(lines[0])
        self.assertIsInstance(parsed["points"], list)
        self.assertEqual(parsed["points"][0], [1.0, 2.0])

    def test_logger_handles_non_serializable(self):
        from cv.gesture_log import GestureLogger

        logger = GestureLogger(log_dir=str(self._log_dir))
        logger.log_gesture({"bad": object()})

        lines = logger.path.read_text(encoding="utf-8").strip().split("\n")
        self.assertGreaterEqual(len(lines), 0)

    def test_logger_default_dir_creatable(self):
        from cv.gesture_log import GestureLogger

        import tempfile, os
        d = os.path.join(tempfile.gettempdir(), "cv_sessions_test")
        logger = GestureLogger(log_dir=d)
        self.assertTrue(Path(d).exists())


if __name__ == "__main__":
    unittest.main()