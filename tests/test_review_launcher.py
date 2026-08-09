from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReviewLauncherTests(unittest.TestCase):
    def test_batch_launcher_starts_review_tool(self):
        launcher = ROOT / "start_gesture_review.bat"

        content = launcher.read_text(encoding="utf-8")
        lowered = content.lower()

        self.assertIn("cd /d \"%~dp0\"", lowered)
        self.assertIn("tools\\review_gesture_samples.py", lowered)
        self.assertIn("set port=8791", lowered)
        self.assertIn("set url=http://127.0.0.1:%port%/", lowered)
        self.assertIn("browser url: %url%", lowered)
        self.assertIn("pending", lowered)
        self.assertIn("retrain", lowered)
        self.assertIn("--port %port%", lowered)
        self.assertIn("python", lowered)
        self.assertIn("py -3", lowered)
        self.assertIn("pause", lowered)

    def test_batch_launcher_retrains_gesture_templates(self):
        launcher = ROOT / "retrain_gesture_templates.bat"

        content = launcher.read_text(encoding="utf-8")
        lowered = content.lower()

        self.assertIn("cd /d \"%~dp0\"", lowered)
        self.assertIn("tools\\retrain_gesture_templates.py", lowered)
        self.assertIn("set reviewed=models\\gesture_reviewed_samples.jsonl", lowered)
        self.assertIn("set output=models\\gesture_templates.json", lowered)
        self.assertIn("--reviewed %reviewed%", lowered)
        self.assertIn("--output %output%", lowered)
        self.assertIn("python", lowered)
        self.assertIn("py -3", lowered)
        self.assertIn("pause", lowered)


if __name__ == "__main__":
    unittest.main()
