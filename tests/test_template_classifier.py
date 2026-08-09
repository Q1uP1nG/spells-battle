from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TemplateClassifierTests(unittest.TestCase):

    def _upward(self, n=30):
        return [[640, 400 - i * 8] for i in range(n)]

    def _downward(self, n=30):
        return [[640, 200 + i * 8] for i in range(n)]

    def _horizontal_right(self, n=30):
        return [[100 + i * 8, 300] for i in range(n)]

    def _horizontal_left(self, n=30):
        return [[600 - i * 8, 300] for i in range(n)]

    def _zigzag(self):
        # A centered zigzag that sweeps left and right as it moves upward.
        # This matches the overload requirements used by gesture classifiers.
        points = [[300.0, 200.0]]
        x, y = 300.0, 200.0
        segments = [(110, 25), (-220, 25), (220, 25), (-220, 25),
                    (220, 25), (-220, 25)]
        for dx, dy in segments:
            for i in range(6):
                x += dx / 6
                y += dy / 6
                points.append([x, y])
        return points

    def _circle(self, center=(400.0, 300.0), radius=70.0, count=48):
        cx, cy = center
        points = []
        for i in range(count + 1):
            angle = 2 * np.pi * i / count
            points.append([cx + np.cos(angle) * radius, cy + np.sin(angle) * radius])
        return points

    def _jitter(self, n=20):
        rng = np.random.RandomState(42)
        return [[640 + rng.uniform(-5, 5), 360 + rng.uniform(-5, 5)]
                for _ in range(n)]

    # ---- Normalization -----------------------------------------------------

    def test_normalize_resamples_to_32(self):
        from cv.template_classifier import _normalize_trajectory

        result = _normalize_trajectory(self._upward())
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (32, 2))

    def test_normalize_too_few_points_returns_none(self):
        from cv.template_classifier import _normalize_trajectory

        self.assertIsNone(_normalize_trajectory([[0, 0]]))
        self.assertIsNone(_normalize_trajectory([]))

    def test_normalize_translates_to_origin(self):
        from cv.template_classifier import _normalize_trajectory

        points = [[100, 200], [200, 200], [300, 200]]
        result = _normalize_trajectory(points)
        self.assertIsNotNone(result)
        np.testing.assert_almost_equal(result[0], [0.0, 0.0], decimal=4)

    def test_normalize_scales_to_unit(self):
        from cv.template_classifier import _normalize_trajectory

        points = [[0, 0], [100, 0], [200, 0]]
        result = _normalize_trajectory(points)
        self.assertIsNotNone(result)
        max_span = max(
            float(np.max(np.abs(result[:, 0]))),
            float(np.max(np.abs(result[:, 1]))),
        )
        self.assertAlmostEqual(max_span, 1.0, delta=0.01)

    # ---- DTW -----------------------------------------------------------------

    def test_dtw_identical_trajectories_zero(self):
        from cv.template_classifier import _dtw_distance

        a = np.linspace(0, 1, 32, dtype=np.float32).reshape(-1, 1)
        a = np.column_stack([a, np.zeros(32, dtype=np.float32)])
        d = _dtw_distance(a, a)
        self.assertAlmostEqual(d, 0.0, delta=0.001)

    def test_dtw_different_trajectories_positive(self):
        from cv.template_classifier import _dtw_distance

        a = np.column_stack([
            np.linspace(0, 1, 32, dtype=np.float32),
            np.zeros(32, dtype=np.float32),
        ])
        b = np.column_stack([
            np.zeros(32, dtype=np.float32),
            np.linspace(0, 1, 32, dtype=np.float32),
        ])
        d = _dtw_distance(a, b)
        self.assertGreater(d, 0.3)

    def test_batched_dtw_matches_reference_recurrence(self):
        from cv.template_classifier import _batch_dtw_distances

        rng = np.random.RandomState(7)
        query = rng.normal(size=(11, 2)).astype(np.float32)
        templates = rng.normal(size=(4, 9, 2)).astype(np.float32)

        def reference(a, b):
            n, m = len(a), len(b)
            table = np.full((n + 1, m + 1), float("inf"), dtype=np.float32)
            table[0, 0] = 0.0
            for i in range(1, n + 1):
                for j in range(1, m + 1):
                    table[i, j] = np.linalg.norm(a[i - 1] - b[j - 1]) + min(
                        table[i - 1, j], table[i, j - 1], table[i - 1, j - 1],
                    )
            return float(table[n, m]) / (n + m)

        expected = [reference(query, template) for template in templates]
        actual = _batch_dtw_distances(query, templates)
        np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)

    def test_incendio_flipped_template_exists(self):
        from cv.template_classifier import TEMPLATES

        self.assertIn("incendio_flipped", TEMPLATES)
        flipped = TEMPLATES["incendio_flipped"]
        self.assertEqual(flipped.shape, (32, 2))
        self.assertLess(float(np.mean(flipped[:, 0])), -0.1)

    def test_data_template_missing_file_returns_no_match(self):
        from cv.template_classifier import DataTemplateClassifier

        classifier = DataTemplateClassifier(template_path="missing-template-file.json")
        result = classifier.classify(self._horizontal_right(), "left")

        self.assertIsNone(result.spell)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.method, "data_template")
        self.assertIn("missing", result.reason)

    def test_data_template_loads_json_and_matches_spell(self):
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            payload = {
                "version": 1,
                "target_point_count": 32,
                "prototypes": {
                    "incendio": [_normalize_trajectory(self._horizontal_right()).tolist()],
                    "glacius": [_normalize_trajectory(self._downward()).tolist()],
                },
                "thresholds": {"incendio": 0.25, "glacius": 0.25},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

            classifier = DataTemplateClassifier(template_path=template_path)
            result = classifier.classify(self._horizontal_right(), "left")

        self.assertEqual(result.spell, "incendio")
        self.assertGreater(result.confidence, 0.8)
        self.assertIn("distance", result.reason)
        self.assertIsNotNone(result.best_distance)
        self.assertEqual(result.second_spell, "glacius")
        self.assertIsNotNone(result.second_distance)
        self.assertIsNotNone(result.margin)
        self.assertEqual(result.matched_prototype_id, "incendio:legacy:0")
        self.assertEqual(result.algorithm_version, "data-template-dtw-v2-structured")

    def test_cyclic_stupefy_is_insensitive_to_circle_start_point(self):
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory

        template_circle = self._circle(count=32)
        query_circle = template_circle[8:-1] + template_circle[:9]
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            payload = {
                "version": 1,
                "target_point_count": 32,
                "prototypes": {
                    "stupefy": [_normalize_trajectory(template_circle).tolist()],
                    "incendio": [_normalize_trajectory(self._horizontal_right()).tolist()],
                },
                "thresholds": {"stupefy": 0.5, "incendio": 0.5},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            ordinary = DataTemplateClassifier(template_path=template_path).classify(query_circle, "left")
            cyclic = DataTemplateClassifier(
                template_path=template_path,
                enable_cyclic_stupefy=True,
            ).classify(query_circle, "left")

        self.assertEqual(cyclic.spell, "stupefy")
        self.assertTrue(cyclic.cyclic_used)
        self.assertGreater(cyclic.best_shift, 0)
        self.assertLess(cyclic.best_distance, ordinary.best_distance)
        self.assertTrue(cyclic.features["closure_gate"]["passed"])

    def test_open_directional_gesture_never_uses_cyclic_dtw(self):
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            payload = {
                "version": 1,
                "target_point_count": 32,
                "prototypes": {"glacius": [_normalize_trajectory(self._downward()).tolist()]},
                "thresholds": {"glacius": 0.5},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            classifier = DataTemplateClassifier(
                template_path=template_path,
                enable_cyclic_stupefy=True,
            )
            with patch("cv.template_classifier._cyclic_dtw_best") as cyclic_dtw:
                result = classifier.classify(self._downward(), "left")

        cyclic_dtw.assert_not_called()
        self.assertEqual(result.spell, "glacius")
        self.assertFalse(result.cyclic_used)

    def test_reverse_matching_requires_explicit_flag(self):
        from cv.template_classifier import _cyclic_dtw_best, _normalize_trajectory

        angles = np.linspace(0, 2 * np.pi, 33)
        radii = 65 + 14 * np.sin(angles * 3) + 8 * np.cos(angles * 2)
        loop = np.column_stack([400 + radii * np.cos(angles), 300 + radii * np.sin(angles)])
        prototype = _normalize_trajectory(loop.tolist())
        reversed_query = _normalize_trajectory(loop[::-1].tolist())

        forward_distance, _, _ = _cyclic_dtw_best(
            reversed_query, np.asarray([prototype]), allow_reverse=False,
        )
        reverse_distance, _, reversed_flags = _cyclic_dtw_best(
            reversed_query, np.asarray([prototype]), allow_reverse=True,
        )

        self.assertLess(reverse_distance[0], forward_distance[0])
        self.assertTrue(reversed_flags[0])

    def test_ambiguous_top_two_can_be_rejected_without_reason_parsing(self):
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory

        horizontal = _normalize_trajectory(self._horizontal_right()).tolist()
        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            payload = {
                "version": 2,
                "target_point_count": 32,
                "prototypes": {
                    "incendio": [{"prototype_id": "inc-1", "points": horizontal}],
                    "lumos": [{"prototype_id": "lum-1", "points": horizontal}],
                },
                "thresholds": {"incendio": 0.5, "lumos": 0.5},
                "margin_thresholds": {"incendio": 0.1, "lumos": 0.1},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            result = DataTemplateClassifier(
                template_path=template_path,
                reject_ambiguous=True,
            ).classify(self._horizontal_right(), "left")

        self.assertIsNone(result.spell)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.margin, 0.0)
        self.assertEqual(result.matched_prototype_id, "inc-1")
        self.assertIn(result.second_spell, {"incendio", "lumos"})

    def test_data_template_rejects_when_distance_exceeds_threshold(self):
        from cv.template_classifier import DataTemplateClassifier, _normalize_trajectory

        with tempfile.TemporaryDirectory() as tmp:
            template_path = Path(tmp) / "gesture_templates.json"
            payload = {
                "version": 1,
                "target_point_count": 32,
                "prototypes": {
                    "incendio": [_normalize_trajectory(self._horizontal_right()).tolist()],
                },
                "thresholds": {"incendio": 0.001},
            }
            template_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

            classifier = DataTemplateClassifier(template_path=template_path)
            result = classifier.classify(self._downward(), "left")

        self.assertIsNone(result.spell)
        self.assertLessEqual(result.confidence, 0.01)
        self.assertIn(">", result.reason)


if __name__ == "__main__":
    unittest.main()
