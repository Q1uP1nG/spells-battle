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

    def test_cyclic_overlay_forwards_context_to_both_classifiers(self):
        from cv.gesture_pipeline import (
            ClassificationResult,
            GestureClassificationContext,
            StupefyCyclicOverlayClassifier,
        )

        seen = {}

        class ContextAwareFake:
            supports_context = True

            def classify(self, points, side, context=None):
                seen.setdefault("baseline", context)
                return ClassificationResult(
                    spell="incendio", confidence=0.8,
                    method="fake", reason="fake",
                )

        class CyclicFake:
            def classify(self, points, side):
                seen.setdefault("cyclic", "no-context")
                return ClassificationResult(
                    spell=None, confidence=0.0,
                    method="cyclic_template_shadow", reason="gate rejected",
                )

        overlay = StupefyCyclicOverlayClassifier(ContextAwareFake(), CyclicFake())
        context = GestureClassificationContext(palm_scale=95.0, purpose="final")
        result = overlay.classify([[100.0, 200.0]], "left", context)

        self.assertIs(seen["baseline"], context)
        self.assertEqual(result.spell, "incendio")

    def test_pipeline_returns_primary_and_normalized_shadow_together(self):
        from cv.gesture_pipeline import GesturePipeline, GESTURE_PIPELINE_VERSION

        pipeline = GesturePipeline()
        evaluation = pipeline.classify_both(self._make_horizontal_points(), "left")

        self.assertEqual(evaluation.primary.method, "heuristic")
        self.assertEqual(evaluation.normalized_shadow.method, "normalized_heuristic_shadow")
        self.assertEqual(evaluation.pipeline_version, GESTURE_PIPELINE_VERSION)

    def test_palm_normalization_is_resolution_independent(self):
        from cv.gesture_pipeline import GestureClassificationContext, normalize_points_for_context

        small = np.asarray([[100, 200], [140, 180], [180, 160]], dtype=np.float32)
        large = small * 2.0
        small_points, small_meta = normalize_points_for_context(
            small,
            GestureClassificationContext(palm_scale=80, frame_width=640, frame_height=360),
        )
        large_points, large_meta = normalize_points_for_context(
            large,
            GestureClassificationContext(palm_scale=160, frame_width=1280, frame_height=720),
        )

        np.testing.assert_allclose(small_points, large_points, atol=1e-5)
        self.assertEqual(small_meta.scale_source, "palm_scale")
        self.assertEqual(large_meta.scale_source, "palm_scale")

    def test_normalization_fallback_is_explicit_and_preserves_direction(self):
        from cv.gesture_pipeline import GestureClassificationContext, normalize_points_for_context

        right = [[0, 0], [50, 0], [100, 0]]
        frame_points, frame_meta = normalize_points_for_context(
            right,
            GestureClassificationContext(frame_width=640, frame_height=360),
        )
        legacy_points, legacy_meta = normalize_points_for_context(right)

        self.assertEqual(frame_meta.scale_source, "frame_diagonal_fallback")
        self.assertEqual(legacy_meta.scale_source, "trajectory_span_fallback")
        self.assertGreater(frame_points[-1, 0] - frame_points[0, 0], 0)
        self.assertGreater(legacy_points[-1, 0] - legacy_points[0, 0], 0)

    def test_normalized_shadow_uses_real_fps_for_duration_metadata(self):
        from cv.gesture_pipeline import (
            GestureClassificationContext,
            NormalizedHeuristicGestureClassifier,
        )

        points = self._make_upward_points()
        result = NormalizedHeuristicGestureClassifier().classify(
            points,
            "left",
            GestureClassificationContext(palm_scale=100, fps_estimate=20),
        )

        self.assertAlmostEqual(result.features.duration_seconds, (len(points) - 1) / 20)
        self.assertIsNotNone(result.features.normalized_speed)

    def test_primary_result_is_unchanged_by_shadow_disagreement(self):
        from cv.gesture_pipeline import ClassificationResult, GesturePipeline

        class Primary:
            def classify(self, _points, _side):
                return ClassificationResult("glacius", 0.91, "primary", "baseline")

        class Shadow:
            def classify(self, _points, _side):
                return ClassificationResult("stupefy", 1.0, "shadow", "candidate")

        evaluation = GesturePipeline(
            primary=Primary(), shadows={"normalized_heuristic": Shadow()},
        ).classify_both([], "left")

        self.assertEqual(evaluation.primary.spell, "glacius")
        self.assertEqual(evaluation.normalized_shadow.spell, "stupefy")

    def test_cyclic_promotion_overlay_changes_only_stupefy_candidate(self):
        from cv.gesture_pipeline import ClassificationResult, StupefyCyclicOverlayClassifier

        class Baseline:
            loaded = True

            def classify(self, _points, _side):
                return ClassificationResult("overload", 0.9, "baseline", "baseline")

        class Candidate:
            def __init__(self, cyclic_used):
                self.cyclic_used = cyclic_used

            def classify(self, _points, _side):
                return ClassificationResult(
                    "stupefy" if self.cyclic_used else None,
                    0.88,
                    "cyclic",
                    "candidate",
                    cyclic_used=self.cyclic_used,
                )

        unchanged = StupefyCyclicOverlayClassifier(Baseline(), Candidate(False)).classify([], "left")
        promoted = StupefyCyclicOverlayClassifier(Baseline(), Candidate(True)).classify([], "left")

        self.assertEqual(unchanged.spell, "overload")
        self.assertEqual(promoted.spell, "stupefy")

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
