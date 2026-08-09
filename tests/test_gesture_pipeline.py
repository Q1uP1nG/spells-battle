from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GesturePipelineTests(unittest.TestCase):

    def _make_upward_points(self):
        return [[640, 400 - i * 8] for i in range(20)]

    def _make_horizontal_points(self):
        return [[100 + i * 15, 300] for i in range(20)]

    def test_classification_result_fields(self):
        from cv.gesture_pipeline import ClassificationResult

        r = ClassificationResult(spell="incendio", confidence=0.85,
                                 method="heuristic", reason="fast horizontal")
        self.assertEqual(r.spell, "incendio")
        self.assertEqual(r.confidence, 0.85)
        self.assertEqual(r.method, "heuristic")

    def test_heuristic_wrapper_matches_classify_cv_gesture(self):
        from cv.gesture_classifier import classify_cv_gesture
        from cv.gesture_pipeline import HeuristicGestureClassifier

        points = self._make_upward_points()
        spell, conf = classify_cv_gesture(points, "left")
        wrapper = HeuristicGestureClassifier()
        result = wrapper.classify(points, "left")

        self.assertEqual(result.spell, spell)
        self.assertEqual(result.confidence, conf)
        self.assertEqual(result.method, "heuristic")

    def test_heuristic_wrapper_returns_none_for_no_match(self):
        from cv.gesture_pipeline import HeuristicGestureClassifier

        points = [[100, 200], [105, 200], [110, 200]]
        wrapper = HeuristicGestureClassifier()
        result = wrapper.classify(points, "left")

        self.assertIsNone(result.spell)
        self.assertEqual(result.confidence, 0.0)

    def test_pipeline_classify_returns_final_result(self):
        from cv.gesture_pipeline import ClassificationResult, GesturePipeline

        pipeline = GesturePipeline()
        points = self._make_upward_points()
        result = pipeline.classify(points, "left")

        self.assertIsInstance(result, ClassificationResult)
        self.assertEqual(result.method, "heuristic")

    def test_primary_controls_gameplay_result(self):
        from cv.gesture_pipeline import GesturePipeline, ClassificationResult

        class FakeClassifier:
            def classify(self, points, side):
                return ClassificationResult(
                    spell="glacius", confidence=0.9,
                    method="fake", reason="fake",
                )

        pipeline = GesturePipeline(primary=FakeClassifier())
        result = pipeline.classify([[100, 200]], "left")
        self.assertEqual(result.spell, "glacius")

    def test_pipeline_has_no_shadow_api(self):
        from cv.gesture_pipeline import GesturePipeline

        pipeline = GesturePipeline()
        self.assertFalse(hasattr(pipeline, "classify_shadow"))
        self.assertFalse(hasattr(pipeline, "classify_both"))

    def test_fused_boosts_when_heuristic_and_template_agree(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.82, "heuristic", "zigzag")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.80, "data_template", "distance 0.1")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "stupefy")
        self.assertEqual(result.method, "fused")
        self.assertGreater(result.confidence, 0.82)
        self.assertIn("agree", result.reason)

    def test_fused_lets_template_win_when_more_confident(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult("glacius", 0.90, "heuristic", "fast downward")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.92, "data_template", "distance 0.1")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "stupefy")
        self.assertIn("template wins", result.reason)

    def test_fused_lets_heuristic_win_when_clearly_more_confident(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult("glacius", 0.95, "heuristic", "fast downward")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.72, "data_template", "distance 0.1")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "glacius")
        self.assertIn("conflict", result.reason)

    def test_fused_rescues_when_heuristic_has_no_spell(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult(None, 0.0, "heuristic", "no match")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("incendio", 0.86, "data_template", "distance 0.1")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "incendio")
        self.assertIn("template rescue", result.reason)

    def test_fused_keeps_heuristic_when_template_below_override_min(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult("lumos", 0.70, "heuristic", "shape upward")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.65, "data_template", "distance 0.2")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "lumos")
        self.assertIn("conflict", result.reason)

    def test_fused_lets_template_override_when_confidence_close(self):
        from cv.gesture_pipeline import ClassificationResult, FusedGestureClassifier

        class Heuristic:
            def classify(self, _points, _side):
                return ClassificationResult("lumos", 0.85, "heuristic", "shape upward")

        class Template:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 0.82, "data_template", "distance 0.1")

        result = FusedGestureClassifier(Heuristic(), Template()).classify([], "left")

        self.assertEqual(result.spell, "stupefy")
        self.assertIn("template wins", result.reason)


if __name__ == "__main__":
    unittest.main()
