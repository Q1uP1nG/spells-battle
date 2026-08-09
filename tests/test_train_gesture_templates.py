from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TrainGestureTemplatesTests(unittest.TestCase):
    def _record(self, spell, points):
        return {
            "intended_spell": spell,
            "points": points,
            "primary": {"spell": None, "confidence": 0.0},
            "cast_success": False,
        }

    def test_training_script_writes_data_template_model(self):
        from tools.train_gesture_templates import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "session.jsonl"
            output_path = root / "gesture_templates.json"
            entries = [
                self._record("incendio", [[0, 0], [70, 0], [140, 0], [210, 0]]),
                self._record("incendio", [[0, 2], [70, 2], [140, 2], [210, 2]]),
                self._record("glacius", [[0, 0], [0, 70], [0, 140], [0, 210]]),
                self._record("glacius", [[2, 0], [2, 70], [2, 140], [2, 210]]),
            ]
            log_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            exit_code = main([
                "--logs", str(log_path),
                "--output", str(output_path),
                "--min-samples", "2",
                "--k", "2",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["version"], 1)
        self.assertIn("incendio", payload["prototypes"])
        self.assertIn("glacius", payload["thresholds"])
        self.assertEqual(payload["source_samples"]["incendio"], 2)

    def test_training_script_can_train_from_template_bank(self):
        from game.cv_training import GestureTemplateBank
        from tools.train_gesture_templates import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "gesture_template_bank.json"
            output_path = root / "gesture_templates.json"
            bank = GestureTemplateBank(path=bank_path, migrate_from_logs=False)
            for index in range(2):
                bank.set_slot(
                    "overload",
                    index,
                    self._record("overload", [[0, 0], [20, 30], [40, 0], [60, 30], [80, 0]]),
                )

            exit_code = main([
                "--bank", str(bank_path),
                "--logs", str(root / "missing_*.jsonl"),
                "--output", str(output_path),
                "--min-samples", "2",
                "--k", "2",
            ])
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("overload", payload["prototypes"])
        self.assertEqual(payload["source_samples"]["overload"], 2)

    def test_training_script_can_train_from_reviewed_samples(self):
        from tools.train_gesture_templates import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_path = root / "gesture_reviewed_samples.jsonl"
            output_path = root / "gesture_templates.json"
            entries = [
                {
                    "review_status": "accepted",
                    "sample_id": "lumos-1",
                    "label": "lumos",
                    "points": [[0, 200], [0, 130], [0, 60], [0, -10]],
                },
                {
                    "review_status": "accepted",
                    "sample_id": "lumos-2",
                    "label": "lumos",
                    "points": [[5, 200], [5, 130], [5, 60], [5, -10]],
                },
                {
                    "review_status": "accepted",
                    "sample_id": "stale-lumos",
                    "label": "lumos",
                    "points": [[10, 200], [10, 130], [10, 60], [10, -10]],
                },
                {
                    "review_status": "discarded",
                    "sample_id": "stale-lumos",
                    "label": "lumos",
                    "points": [[10, 200], [10, 130], [10, 60], [10, -10]],
                },
                {
                    "review_status": "discarded",
                    "label": "glacius",
                    "points": [[0, 0], [0, 70], [0, 140], [0, 210]],
                },
            ]
            reviewed_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            exit_code = main([
                "--logs", str(root / "missing_*.jsonl"),
                "--bank", str(root / "missing_bank.json"),
                "--reviewed", str(reviewed_path),
                "--output", str(output_path),
                "--min-samples", "2",
                "--k", "2",
            ])
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("lumos", payload["prototypes"])
        self.assertNotIn("glacius", payload["prototypes"])
        self.assertEqual(payload["source_samples"]["lumos"], 2)


if __name__ == "__main__":
    unittest.main()
