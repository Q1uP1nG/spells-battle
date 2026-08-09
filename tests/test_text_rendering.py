import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TextRenderingTests(unittest.TestCase):
    def test_visible_frontend_uses_serif_text_helper_instead_of_raw_cv2_puttext(self):
        frontend_files = [
            ROOT / "main.py",
            ROOT / "cv" / "controller.py",
            ROOT / "renderer" / "effects.py",
            ROOT / "renderer" / "hud.py",
            ROOT / "renderer" / "menu.py",
            ROOT / "renderer" / "player.py",
            ROOT / "renderer" / "projectile.py",
        ]

        offenders = []
        for path in frontend_files:
            text = path.read_text(encoding="utf-8")
            if "cv2.putText" in text:
                offenders.append(path.relative_to(ROOT).as_posix())

        self.assertEqual(offenders, [])

    def test_measure_text_returns_positive_size(self):
        from renderer.text import measure_text

        width, height = measure_text("SPELLS", size=32, face="title")

        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    def test_draw_text_changes_frame_pixels(self):
        from renderer.text import draw_text

        frame = np.zeros((120, 320, 3), dtype=np.uint8)

        draw_text(frame, "SPELLS", (20, 60), size=32, color=(255, 255, 255), face="title")

        self.assertGreater(int(np.count_nonzero(frame)), 0)

    def test_draw_centered_text_uses_center_anchor(self):
        from renderer.text import draw_centered_text

        frame = np.zeros((120, 320, 3), dtype=np.uint8)

        draw_centered_text(frame, "READY", x=160, y=60, size=28, color=(255, 255, 255))

        self.assertGreater(int(np.count_nonzero(frame[:, 120:200])), 0)

    def test_draw_cv_text_uses_opencv_baseline_coordinates(self):
        from renderer.text import draw_cv_text

        frame = np.zeros((120, 320, 3), dtype=np.uint8)

        draw_cv_text(frame, "BASE", (20, 70), scale=0.8, color=(255, 255, 255), face="title")

        self.assertGreater(int(np.count_nonzero(frame[20:75, 20:120])), 0)

    def test_draw_text_reuses_cached_serif_bitmap(self):
        import renderer.text as text_renderer

        if not text_renderer.PIL_AVAILABLE:
            self.skipTest("PIL text cache only applies when Pillow is available")
        if hasattr(text_renderer, "clear_text_cache"):
            text_renderer.clear_text_cache()

        frame = np.zeros((120, 320, 3), dtype=np.uint8)

        with patch.object(
            text_renderer.ImageDraw,
            "Draw",
            wraps=text_renderer.ImageDraw.Draw,
        ) as draw_factory:
            text_renderer.draw_text(
                frame,
                "SPELLS",
                (20, 60),
                size=32,
                color=(255, 255, 255),
                face="title",
            )
            text_renderer.draw_text(
                frame,
                "SPELLS",
                (100, 60),
                size=32,
                color=(255, 255, 255),
                face="title",
            )

        self.assertEqual(draw_factory.call_count, 1)


if __name__ == "__main__":
    unittest.main()
