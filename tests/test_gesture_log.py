from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_logger_upgrades_legacy_event_to_schema_v2_with_anonymous_labels(self):
        from cv.gesture_log import GestureLogger

        with patch.dict(
            "os.environ",
            {"SPELLS_CV_USER_ID": "player-a", "SPELLS_CV_DEVICE_ID": "laptop-a"},
            clear=False,
        ):
            logger = GestureLogger(
                log_dir=str(self._log_dir),
                session_id="session-test",
                classifier_version="classifier-test",
            )
        logger.log_gesture({
            "schema": 1,
            "attempt_id": 7,
            "mode": "wand",
            "training_status": "accepted",
            "intended_spell": "circle",
            "points": [[0, 0], [1, 1]],
        })

        parsed = json.loads(logger.path.read_text(encoding="utf-8").strip())

        self.assertEqual(parsed["schema"], 2)
        self.assertEqual(parsed["session_id"], "session-test")
        self.assertEqual(parsed["sample_id"], "session-test:7")
        self.assertEqual(parsed["input_mode"], "wand")
        self.assertEqual(parsed["user_id"], "player-a")
        self.assertEqual(parsed["device_id"], "laptop-a")
        self.assertEqual(parsed["classifier_version"], "classifier-test")
        self.assertEqual(parsed["review_status"], "accepted")
        self.assertEqual(parsed["dataset_partition"], "development")

    def test_logger_does_not_invent_user_or_device_identity(self):
        from cv.gesture_log import GestureLogger

        with patch.dict(
            "os.environ",
            {"SPELLS_CV_USER_ID": "", "SPELLS_CV_DEVICE_ID": ""},
            clear=False,
        ):
            logger = GestureLogger(log_dir=str(self._log_dir), session_id="session-private")
        prepared = logger.prepare_event({"attempt_id": 1, "mode": "finger"})

        self.assertNotIn("user_id", prepared)
        self.assertNotIn("device_id", prepared)
        self.assertNotIn("hardware_serial", prepared)

    def test_schema_upgrade_is_idempotent_before_bank_and_disk_writes(self):
        from cv.gesture_log import GestureLogger

        logger = GestureLogger(log_dir=str(self._log_dir), session_id="session-idempotent")
        first = logger.prepare_event({"attempt_id": 3, "mode": "finger"})
        second = logger.prepare_event(first)
        next_event = logger.prepare_event({"attempt_id": 4, "mode": "finger"})

        self.assertEqual(first["sample_id"], "session-idempotent:3")
        self.assertEqual(second["sample_id"], first["sample_id"])
        self.assertEqual(second["session_id"], first["session_id"])
        self.assertEqual(next_event["sample_id"], "session-idempotent:4")

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
