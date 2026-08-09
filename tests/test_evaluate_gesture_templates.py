import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class EvaluateGestureTemplatesTests(unittest.TestCase):
    def _sample(self, label, points, primary=None, shadow=None, attempt=1):
        return {
            "intended_spell": label,
            "training_attempt": attempt,
            "points": points,
            "primary": {"spell": primary},
            "shadow": {"spell": shadow},
        }

    def test_leave_one_out_template_does_not_match_sample_to_itself(self):
        from tools.evaluate_gesture_templates import build_samples, classify_real_template

        entries = [
            self._sample("incendio", [[0, 0], [60, 0], [120, 0]], attempt=1),
            self._sample("incendio", [[0, 3], [62, 3], [124, 3]], attempt=2),
            self._sample("glacius", [[0, 0], [0, 60], [0, 120]], attempt=1),
            self._sample("glacius", [[4, 0], [4, 62], [4, 124]], attempt=2),
        ]
        samples = build_samples(entries)

        result = classify_real_template(samples, 0)

        self.assertEqual(result["spell"], "incendio")
        self.assertEqual(result["nearest_sample_index"], 1)
        self.assertGreaterEqual(result["margin"], 0.0)

    def test_evaluate_samples_reports_current_classifier_and_template_accuracy(self):
        from tools.evaluate_gesture_templates import build_samples, evaluate_samples

        entries = [
            self._sample("incendio", [[0, 0], [70, 0], [140, 0], [210, 0]], primary="incendio", shadow="incendio"),
            self._sample("incendio", [[0, 5], [70, 5], [140, 5], [210, 5]], primary="incendio", shadow="incendio"),
            self._sample("lumos", [[0, 200], [0, 130], [0, 60], [0, -10]], primary="lumos", shadow="glacius"),
            self._sample("lumos", [[5, 200], [5, 130], [5, 60], [5, -10]], primary="lumos", shadow="glacius"),
        ]
        samples = build_samples(entries)

        summary = evaluate_samples(samples)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["logged_primary"]["correct"], 4)
        self.assertEqual(summary["logged_shadow"]["correct"], 2)
        self.assertEqual(summary["real_template"]["correct"], 4)
        self.assertEqual(summary["current_heuristic"]["total"], 4)

    def test_evaluate_samples_reports_data_template_and_fused_accuracy(self):
        from cv.gesture_pipeline import ClassificationResult
        from tools.evaluate_gesture_templates import build_samples, evaluate_samples

        class FakeDataTemplate:
            def classify(self, points, _side):
                spell = "incendio" if points[-1][0] > points[0][0] else "lumos"
                return ClassificationResult(spell, 0.90, "data_template", "fake")

        entries = [
            self._sample("incendio", [[0, 0], [70, 0], [140, 0], [210, 0]], primary="incendio", shadow="incendio"),
            self._sample("lumos", [[0, 200], [0, 130], [0, 60], [0, -10]], primary="lumos", shadow="lumos"),
        ]
        samples = build_samples(entries)

        summary = evaluate_samples(samples, data_template_classifier=FakeDataTemplate())

        self.assertIn("data_template", summary["methods"])
        self.assertIn("fused", summary["methods"])
        self.assertEqual(summary["data_template"]["total"], 2)
        self.assertEqual(summary["fused"]["total"], 2)

    def test_evaluation_reuses_each_pairwise_dtw_distance(self):
        from cv.gesture_pipeline import ClassificationResult
        import tools.evaluate_gesture_templates as evaluator

        class FakeDataTemplate:
            def classify(self, _points, _side):
                return ClassificationResult(None, 0.0, "data_template", "fake")

        samples = evaluator.build_samples([
            self._sample("incendio", [[0, 0], [70, 0], [140, 0]], attempt=1),
            self._sample("incendio", [[0, 2], [70, 2], [140, 2]], attempt=2),
            self._sample("glacius", [[0, 0], [0, 70], [0, 140]], attempt=3),
            self._sample("glacius", [[2, 0], [2, 70], [2, 140]], attempt=4),
        ])
        original_distance = evaluator._dtw_distance

        with patch.object(
            evaluator,
            "_dtw_distance",
            side_effect=original_distance,
        ) as distance:
            evaluator.evaluate_samples(samples, data_template_classifier=FakeDataTemplate())

        self.assertEqual(distance.call_count, 6)

    def test_circle_training_label_is_scored_against_stupefy_spell(self):
        from tools.evaluate_gesture_templates import summarize_predictions

        summary = summarize_predictions([
            ("circle", "stupefy"),
            ("overload", "overload"),
        ])

        self.assertEqual(summary["correct"], 2)
        self.assertEqual(summary["by_label"]["circle"]["correct"], 1)
        self.assertEqual(summary["by_label"]["overload"]["correct"], 1)

    def test_review_label_is_loaded_and_discarded_review_is_skipped(self):
        from tools.evaluate_gesture_templates import build_samples

        samples = build_samples([
            {
                "sample_id": "accepted-circle",
                "review_status": "accepted",
                "label": "circle",
                "points": [[0, 0], [20, 20], [0, 40], [-20, 20], [0, 0]],
            },
            {
                "sample_id": "discarded-circle",
                "review_status": "discarded",
                "label": "circle",
                "points": [[0, 0], [30, 30], [0, 60], [-30, 30], [0, 0]],
            },
        ])

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].sample_id, "accepted-circle")
        self.assertEqual(samples[0].label, "circle")

    def test_canonical_cli_writes_reproducible_artifact_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_path = root / "reviewed.jsonl"
            output_path = root / "evaluation"
            entries = [
                {
                    "sample_id": "incendio-1",
                    "review_status": "accepted",
                    "label": "incendio",
                    "points": [[0, 0], [70, 0], [140, 0], [210, 0]],
                },
                {
                    "sample_id": "incendio-2",
                    "review_status": "accepted",
                    "label": "incendio",
                    "points": [[0, 2], [70, 2], [140, 2], [210, 2]],
                },
                {
                    "sample_id": "discarded",
                    "review_status": "discarded",
                    "label": "glacius",
                    "points": [[0, 0], [0, 70], [0, 140], [0, 210]],
                },
            ]
            reviewed_path.write_text(
                "\n".join(json.dumps(entry) for entry in entries), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "tools/evaluate_gesture_templates.py",
                    "--reviewed",
                    str(reviewed_path),
                    "--output-dir",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=15,
            )

            artifact_names = {
                "manifest.json",
                "metrics.json",
                "report.md",
                "confusion_matrix.csv",
                "misses.jsonl",
            }
            written_artifacts = {path.name for path in output_path.iterdir()}
            metrics = json.loads((output_path / "metrics.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_path / "manifest.json").read_text(encoding="utf-8"))
            report = (output_path / "report.md").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(written_artifacts, artifact_names)
        self.assertEqual(metrics["total"], 2)
        self.assertIn("macro", metrics["methods"]["fused"])
        self.assertIn("per_spell", metrics["methods"]["fused"])
        self.assertEqual(manifest["corpus_audit"]["canonical_samples"], 2)
        self.assertEqual(manifest["corpus_audit"]["discarded_reviews"], 1)
        self.assertEqual(manifest["corpus_version"], manifest["corpus_audit"]["corpus_version"])
        self.assertIn("classifier_versions", manifest)
        self.assertIn("template_pack", manifest)
        self.assertIn("not evidence of cross-user or cross-device generalization", report)

    def test_format_summary_highlights_circle_and_overload_labels(self):
        from tools.evaluate_gesture_templates import format_summary, summarize_predictions

        base = summarize_predictions([
            ("circle", "stupefy"),
            ("overload", "glacius"),
        ])
        summary = {
            "total": 2,
            "misses": [],
            "real_template": base,
        }
        for method in [
            "logged_primary",
            "current_heuristic",
            "logged_shadow",
            "data_template",
            "fused",
            "hybrid_1_0_0_2",
        ]:
            summary[method] = base

        text = format_summary(summary)

        self.assertIn("Circle/Overload focus:", text)
        self.assertIn("circle -> stupefy:", text)
        self.assertIn("overload -> overload:", text)

    def test_cli_runs_from_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "session.jsonl"
            entries = [
                self._sample("incendio", [[0, 0], [70, 0], [140, 0], [210, 0]], primary="incendio", shadow="incendio"),
                self._sample("incendio", [[0, 5], [70, 5], [140, 5], [210, 5]], primary="incendio", shadow="incendio"),
            ]
            log_path.write_text("\n".join(__import__("json").dumps(e) for e in entries), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "tools/evaluate_gesture_templates.py", str(log_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Total labeled samples: 2", result.stdout)

    def test_hybrid_uses_template_when_heuristic_has_no_candidate(self):
        from tools.evaluate_gesture_templates import build_samples, classify_hybrid

        entries = [
            self._sample("incendio", [[0, 0], [30, 0], [60, 0]], primary=None, shadow="incendio"),
            self._sample("incendio", [[0, 2], [32, 2], [64, 2]], primary=None, shadow="incendio"),
            self._sample("glacius", [[0, 0], [0, 40], [0, 80]], primary=None, shadow="glacius"),
            self._sample("glacius", [[2, 0], [2, 42], [2, 84]], primary=None, shadow="glacius"),
        ]
        samples = build_samples(entries)

        result = classify_hybrid(samples, 0, heuristic_weight=1.0, template_weight=0.5)

        self.assertEqual(result["spell"], "incendio")
        self.assertGreater(result["scores"]["incendio"], result["scores"]["glacius"])

    def test_grid_search_hybrid_weights_reports_best_setting(self):
        from tools.evaluate_gesture_templates import build_samples, search_hybrid_weights

        entries = [
            self._sample("incendio", [[0, 0], [30, 0], [60, 0]], primary=None, shadow="incendio"),
            self._sample("incendio", [[0, 2], [32, 2], [64, 2]], primary=None, shadow="incendio"),
            self._sample("lumos", [[0, 90], [0, 40], [0, -10]], primary="lumos", shadow="lumos"),
            self._sample("lumos", [[2, 90], [2, 40], [2, -10]], primary="lumos", shadow="lumos"),
        ]
        samples = build_samples(entries)

        results = search_hybrid_weights(
            samples,
            heuristic_weights=(0.0, 1.0),
            template_weights=(0.0, 0.5),
        )

        self.assertEqual(results[0]["correct"], 4)
        self.assertEqual(results[0]["heuristic_weight"], 1.0)
        self.assertEqual(results[0]["template_weight"], 0.5)


if __name__ == "__main__":
    unittest.main()
