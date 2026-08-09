import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class WandDebugLoggerTests(unittest.TestCase):
    def test_logger_writes_jsonl_with_numpy_safe_values(self):
        from cv.wand_debug_log import WandDebugLogger

        with tempfile.TemporaryDirectory() as temp_dir:
            logger = WandDebugLogger(log_dir=temp_dir)
            logger.log_event({
                "timestamp": 12.3,
                "state": "LOCKED",
                "point": np.array([101.5, 202.25], dtype=np.float32),
            })

            self.assertTrue(logger.path.exists())
            line = logger.path.read_text(encoding="utf-8").strip()
            parsed = json.loads(line)
            self.assertEqual(parsed["state"], "LOCKED")
            self.assertEqual(parsed["point"], [101.5, 202.25])

    def test_logger_prunes_old_sessions_when_limit_is_reached(self):
        from cv.wand_debug_log import WandDebugLogger

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            for index in range(5):
                path = log_dir / f"session_20200101_00000{index}.jsonl"
                path.write_text("{}\n", encoding="utf-8")
                old_time = time.time() - 1000 + index
                path.touch()
                import os
                os.utime(path, (old_time, old_time))

            logger = WandDebugLogger(log_dir=temp_dir, max_sessions=3)
            logger.log_event({"state": "LOCKED"})

            sessions = sorted(log_dir.glob("session_*.jsonl"))
            self.assertLessEqual(len(sessions), 3)
            self.assertIn(logger.path, sessions)


if __name__ == "__main__":
    unittest.main()
