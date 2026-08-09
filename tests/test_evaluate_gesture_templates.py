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
        self.assertEqual(summary["current_heuristic"]["latency_ms"]["count"], 4)
        self.assertIsNotNone(summary["fused"]["latency_ms"]["p95"])
        self.assertIn("margin", summary["real_template"])
        self.assertEqual(
            summary["current_heuristic"]["breakdowns"]["input_mode"]["unknown"]["total"],
            4,
        )

    def test_evaluation_reports_normalized_shadow_and_fallback_source(self):
        from tools.evaluate_gesture_templates import build_samples, evaluate_samples

        entries = [
            {
                "label": "incendio",
                "points": [[0, 0], [70, 0], [140, 0], [210, 0], [280, 0], [350, 0]],
                "palm_scale": 100.0,
                "frame_width": 1280,
                "frame_height": 720,
                "fps_estimate": 60.0,
            },
            {
                "label": "lumos",
                "points": [[0, 350], [0, 280], [0, 210], [0, 140], [0, 70], [0, 0]],
            },
        ]

        summary = evaluate_samples(build_samples(entries))
        metric = summary["normalized_heuristic_shadow"]

        self.assertEqual(metric["total"], 2)
        self.assertEqual(metric["normalization_sources"]["palm_scale"], 1)
        self.assertEqual(metric["normalization_sources"]["trajectory_span_fallback"], 1)
        self.assertIn("latency_ms", metric)

    def test_evaluation_reports_cyclic_shadow_diagnostics(self):
        import numpy as np
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory
        from tools.evaluate_gesture_templates import build_samples, evaluate_samples

        angles = np.linspace(0, 2 * np.pi, 33)
        circle = np.column_stack([400 + 70 * np.cos(angles), 300 + 70 * np.sin(angles)]).tolist()
        shifted = circle[8:-1] + circle[:9]
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "pack.json"
            payload = {
                "version": 2,
                "target_point_count": 32,
                "prototypes": {
                    "stupefy": [{
                        "prototype_id": "stupefy:medoid:c1",
                        "points": _normalize_trajectory(circle).tolist(),
                    }],
                },
                "thresholds": {"stupefy": 0.5},
                "margin_thresholds": {"stupefy": 0.0},
                "cyclic_dtw": {"allow_reverse": False},
            }
            template_path.write_text(json.dumps(payload), encoding="utf-8")
            classifier = DataTemplateClassifier(
                template_path=template_path,
                enable_cyclic_stupefy=True,
                reject_ambiguous=True,
            )
            summary = evaluate_samples(
                build_samples([{"label": "circle", "points": shifted}]),
                data_template_classifier=classifier,
                cyclic_template_classifier=classifier,
            )

        metric = summary["cyclic_template_shadow"]
        self.assertEqual(metric["correct"], 1)
        self.assertEqual(metric["diagnostics"]["closure_gate_passed"], 1)
        self.assertEqual(metric["diagnostics"]["cyclic_top1"], 1)

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
        self.assertEqual(summary["error_acceptance_rate"], 0.0)

    def test_error_acceptance_rate_excludes_rejections(self):
        from tools.evaluate_gesture_templates import summarize_predictions

        summary = summarize_predictions([
            ("incendio", "glacius"),
            ("glacius", None),
            ("lumos", "lumos"),
        ])

        self.assertAlmostEqual(summary["error_acceptance_rate"], 1 / 3)
        self.assertAlmostEqual(summary["rejection_rate"], 1 / 3)

    def test_baseline_comparison_supports_legacy_metrics_without_error_acceptance(self):
        from tools.evaluate_gesture_templates import compare_to_baseline, summarize_predictions

        current_method = summarize_predictions([
            ("incendio", "incendio"),
            ("glacius", "incendio"),
        ])
        baseline_method = summarize_predictions([
            ("incendio", "incendio"),
            ("glacius", None),
        ])
        baseline_method.pop("error_acceptance_rate")

        comparison = compare_to_baseline(
            {"methods": {"candidate": current_method}},
            {"methods": {"candidate": baseline_method}},
        )

        self.assertAlmostEqual(comparison["candidate"]["error_acceptance_rate_delta"], 0.5)

    def test_deterministic_metrics_version_ignores_runtime_latency_noise(self):
        from tools.evaluate_gesture_templates import (
            _deterministic_metrics_version,
            summarize_predictions,
        )

        method = summarize_predictions([("incendio", "incendio")])
        method["latency_ms"] = {"count": 1, "p50": 1.0, "p95": 1.0}
        summary = {
            "total": 1,
            "dataset_partition": "development",
            "split": None,
            "methods": {"candidate": method},
        }
        first = _deterministic_metrics_version(summary)
        method["latency_ms"]["p95"] = 999.0

        self.assertEqual(first, _deterministic_metrics_version(summary))

    def test_session_grouped_folds_have_no_group_or_sample_leakage(self):
        from tools.evaluate_gesture_templates import build_grouped_folds, build_samples

        entries = []
        for session_index in range(4):
            for sample_index in range(2):
                entries.append({
                    **self._sample(
                        "incendio",
                        [[0, sample_index], [70, sample_index], [140, sample_index]],
                        attempt=sample_index,
                    ),
                    "sample_id": f"s{session_index}-{sample_index}",
                    "session_id": f"session-{session_index}",
                })
        samples = build_samples(entries)

        folds = build_grouped_folds(samples, "session_grouped_cv", fold_count=3)

        seen_test_indices = set()
        seen_test_sessions = set()
        for fold in folds:
            train_sessions = {samples[index].session_id for index in fold["train_indices"]}
            test_sessions = {samples[index].session_id for index in fold["test_indices"]}
            self.assertFalse(train_sessions.intersection(test_sessions))
            self.assertFalse(seen_test_indices.intersection(fold["test_indices"]))
            self.assertFalse(seen_test_sessions.intersection(test_sessions))
            seen_test_indices.update(fold["test_indices"])
            seen_test_sessions.update(test_sessions)
        self.assertEqual(seen_test_indices, set(range(len(samples))))
        self.assertTrue(all("train_indices" in fold for fold in folds))

    def test_user_grouped_folds_fail_when_anonymous_user_metadata_is_missing(self):
        from tools.evaluate_gesture_templates import (
            EvaluationDataError,
            build_grouped_folds,
            build_samples,
        )

        samples = build_samples([
            {**self._sample("incendio", [[0, 0], [70, 0], [140, 0]]), "session_id": "a"},
            {**self._sample("incendio", [[0, 1], [70, 1], [140, 1]]), "session_id": "b"},
        ])

        with self.assertRaisesRegex(EvaluationDataError, "lacks user_id"):
            build_grouped_folds(samples, "user_grouped_cv")

    def test_user_and_device_grouped_folds_keep_identity_out_of_training_fold(self):
        from tools.evaluate_gesture_templates import build_grouped_folds, build_samples

        entries = []
        for index, (user_id, device_id) in enumerate(
            (("u1", "d1"), ("u1", "d2"), ("u2", "d1"), ("u2", "d2"))
        ):
            entries.append({
                **self._sample("incendio", [[0, index], [70, index], [140, index]]),
                "sample_id": f"identity-{index}",
                "session_id": f"session-{index}",
                "user_id": user_id,
                "device_id": device_id,
            })
        samples = build_samples(entries)

        for mode, field in (
            ("user_grouped_cv", "user_id"),
            ("device_grouped_cv", "device_id"),
        ):
            folds = build_grouped_folds(samples, mode, fold_count=2)
            for fold in folds:
                train_ids = {getattr(samples[index], field) for index in fold["train_indices"]}
                test_ids = {getattr(samples[index], field) for index in fold["test_indices"]}
                self.assertFalse(train_ids.intersection(test_ids))

    def test_derived_sample_stays_in_parent_fold(self):
        from tools.evaluate_gesture_templates import build_grouped_folds, build_samples

        samples = build_samples([
            {
                **self._sample("circle", [[0, 0], [10, 10], [0, 20], [0, 0]]),
                "sample_id": "circle-original",
                "session_id": "circle-session",
            },
            {
                **self._sample("circle", [[10, 10], [0, 20], [0, 0], [10, 10]]),
                "sample_id": "circle-derived",
                "derived_from_sample_id": "circle-original",
                "session_id": "circle-session",
            },
            {
                **self._sample("incendio", [[0, 0], [70, 0], [140, 0]]),
                "sample_id": "other",
                "session_id": "other-session",
            },
        ])

        folds = build_grouped_folds(samples, "session_grouped_cv", fold_count=2)
        memberships = {
            sample_index: fold["fold"]
            for fold in folds
            for sample_index in fold["test_indices"]
        }

        self.assertEqual(memberships[0], memberships[1])

    def test_canonical_evaluation_can_isolate_locked_partition(self):
        from tools.evaluate_gesture_templates import build_samples_from_corpus
        from tools.gesture_corpus import CanonicalCorpus, CanonicalGestureSample

        corpus = CanonicalCorpus(
            samples=[
                CanonicalGestureSample(
                    sample_id="dev",
                    label="incendio",
                    points=[[0, 0], [70, 0], [140, 0]],
                    dataset_partition="development",
                ),
                CanonicalGestureSample(
                    sample_id="locked",
                    label="glacius",
                    points=[[0, 0], [0, 70], [0, 140]],
                    dataset_partition="locked",
                ),
            ],
            audit={},
            source_files=[],
        )

        locked = build_samples_from_corpus(corpus, dataset_partition="locked")

        self.assertEqual([sample.sample_id for sample in locked], ["locked"])

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
                    "session_id": "session-1",
                    "review_status": "accepted",
                    "label": "incendio",
                    "points": [[0, 0], [70, 0], [140, 0], [210, 0]],
                },
                {
                    "sample_id": "incendio-2",
                    "session_id": "session-2",
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
