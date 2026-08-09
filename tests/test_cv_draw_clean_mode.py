import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CVDrawCleanModeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _controller(self):
        from cv.controller import CVGestureController
        from cv.gesture_log import GestureLogger
        from cv.wand_debug_log import WandDebugLogger

        root = Path(self._tmp.name)
        return CVGestureController(
            gesture_logger=GestureLogger(log_dir=str(root / "cv_sessions")),
            wand_debug_logger=WandDebugLogger(log_dir=str(root / "wand_debug")),
        )

    def test_draw_keeps_trails_but_hides_debug_panel_by_default(self):
        from config import HEIGHT, WIDTH

        controller = self._controller()
        track = controller.tracks[0]
        track.points.append(np.array([100.0, 100.0], dtype=np.float32))
        track.points.append(np.array([130.0, 115.0], dtype=np.float32))
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from cv.controller import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("cv.controller.draw_cv_text", side_effect=capture_draw_cv_text):
            controller.draw(frame, now=10.0)

        self.assertGreater(int(np.count_nonzero(frame)), 0)
        self.assertFalse(any("DEBUG" in text for text in drawn_text))

    def test_draw_debug_panel_when_requested(self):
        from config import HEIGHT, WIDTH

        controller = self._controller()
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        drawn_text = []
        from cv.controller import draw_cv_text as original_draw_cv_text

        def capture_draw_cv_text(*args, **kwargs):
            drawn_text.append(str(args[1]))
            return original_draw_cv_text(*args, **kwargs)

        with patch("cv.controller.draw_cv_text", side_effect=capture_draw_cv_text):
            controller.draw(frame, now=10.0, show_debug=True)

        self.assertTrue(any("DEBUG" in text for text in drawn_text))


if __name__ == "__main__":
    unittest.main()
