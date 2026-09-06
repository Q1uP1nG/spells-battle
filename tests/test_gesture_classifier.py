import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GestureClassifierTests(unittest.TestCase):
    """Tests for the refactored gesture classifier."""

    # -- Helper to build trajectories ------------------------------------------

    @staticmethod
    def _make_rightward_line(length=30, step=8):
        """P1 rightward push → Incendio."""
        return [[i * step, 360] for i in range(length)]

    @staticmethod
    def _make_leftward_line(length=30, step=8):
        """P2 leftward push → Incendio (opponent_dx is positive for P2)."""
        return [[640 - i * step, 360] for i in range(length)]

    @staticmethod
    def _make_upward_flick(length=20, step=8):
        """Upward flick → Lumos."""
        return [[640, 400 - i * step] for i in range(length)]

    @staticmethod
    def _make_downward_slash(length=20, step=8):
        """Downward slash → Glacius."""
        return [[640, 200 + i * step] for i in range(length)]

    @staticmethod
    def _make_zigzag(segments=8, seg_length=110, vert_step=30, interpolate=4):
        """Multi-zigzag lightning -> Overload.

        Moves consistently downward while oscillating horizontally.
        Downward motion avoids lumos (requires upward dy).
        Low straightness from zigzag avoids glacius.
        Zero net dx avoids incendio.
        """
        vertices = []
        x, y = 400.0, 200.0
        vertices.append([x, y])
        for i in range(segments):
            dx = seg_length if i % 2 == 0 else -seg_length
            x += dx
            y += vert_step  # always downward
            vertices.append([x, y])

        # Interpolate between vertices for sufficient point count
        points = []
        for k in range(len(vertices) - 1):
            ax, ay = vertices[k]
            bx, by = vertices[k + 1]
            for t in range(interpolate):
                frac = t / interpolate
                points.append([ax + (bx - ax) * frac, ay + (by - ay) * frac])
        points.append(vertices[-1])
        return points

    @staticmethod
    def _make_circle(center=(400.0, 300.0), radius=70.0, count=48):
        cx, cy = center
        points = []
        for i in range(count + 1):
            angle = 2 * np.pi * i / count
            points.append([cx + np.cos(angle) * radius, cy + np.sin(angle) * radius])
        return points

    @staticmethod
    def _make_upward_zigzag(segments=7, seg_length=120, vert_step=32, interpolate=5):
        """A zigzag whose net movement is upward; Overload should own the turns."""
        vertices = []
        x, y = 400.0, 500.0
        vertices.append([x, y])
        for i in range(segments):
            dx = seg_length if i % 2 == 0 else -seg_length
            x += dx
            y -= vert_step
            vertices.append([x, y])
        points = []
        for k in range(len(vertices) - 1):
            ax, ay = vertices[k]
            bx, by = vertices[k + 1]
            for t in range(interpolate):
                frac = t / interpolate
                points.append([ax + (bx - ax) * frac, ay + (by - ay) * frac])
        points.append(vertices[-1])
        return points

    @staticmethod
    def _make_stationary_broad_zigzag(cycles=3, interpolate=6):
        """Large back-and-forth strokes with turns but no overall advance."""
        vertices = [[400.0, 300.0]]
        for _ in range(cycles):
            vertices.extend([[520.0, 340.0], [280.0, 260.0]])
        vertices.append([400.0, 300.0])

        points = []
        for k in range(len(vertices) - 1):
            ax, ay = vertices[k]
            bx, by = vertices[k + 1]
            for t in range(interpolate):
                frac = t / interpolate
                points.append([ax + (bx - ax) * frac, ay + (by - ay) * frac])
        points.append(vertices[-1])
        return points

    @staticmethod
    def _make_jitter(count=20, radius=5):
        """Low-amplitude jitter → None."""
        rng = np.random.RandomState(42)
        points = []
        cx, cy = 640, 360
        for _ in range(count):
            points.append([cx + rng.uniform(-radius, radius),
                           cy + rng.uniform(-radius, radius)])
        return points

    # -- Integration tests (classify_cv_gesture) --------------------------------

    def test_p1_rightward_hits_incendio(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_rightward_line()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "incendio")
        self.assertGreater(conf, 0.78)

    def test_p2_leftward_hits_incendio(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_leftward_line()
        spell, conf = classify_cv_gesture(points, "right")
        self.assertEqual(spell, "incendio")
        self.assertGreater(conf, 0.78)

    def test_upward_hits_lumos(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_upward_flick()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "lumos")
        self.assertGreater(conf, 0.78)

    def test_downward_hits_glacius(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_downward_slash()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "glacius")
        self.assertGreater(conf, 0.78)

    def test_circle_hits_stupefy(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_circle()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "stupefy")
        self.assertGreater(conf, 0.78)

    def test_zigzag_hits_overload(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_zigzag()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "overload")
        self.assertGreater(conf, 0.78)

    def test_slow_long_circle_still_hits_stupefy(self):
        from cv.gesture_classifier import classify_cv_gesture
        # A deliberately slow circle produces far more samples than the
        # feature cap; the whole draw must be seen, not just its trailing
        # window, or the arc no longer closes and the circle is rejected.
        points = self._make_circle(count=200)
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "stupefy")
        self.assertGreater(conf, 0.78)

    def test_long_zigzag_keeps_turns_across_resampling(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_zigzag(segments=10, interpolate=15)
        self.assertGreater(len(points), 80)
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "overload")
        self.assertGreater(conf, 0.78)

    def test_select_feature_points_preserves_full_gesture_span(self):
        from cv.gesture_classifier import MAX_FEATURE_POINTS, select_feature_points
        points = self._make_circle(count=200)

        selected = select_feature_points(points)

        self.assertLessEqual(len(selected), MAX_FEATURE_POINTS)
        self.assertTrue(np.allclose(selected[0], points[0]))
        self.assertTrue(np.allclose(selected[-1], points[-1]))

    def test_select_feature_points_keeps_short_input_unchanged(self):
        from cv.gesture_classifier import select_feature_points
        points = [[float(i), float(i * 2)] for i in range(20)]

        selected = select_feature_points(points)

        self.assertEqual(len(selected), 20)
        self.assertTrue(np.allclose(selected, np.asarray(points, dtype=np.float32)))

    def test_upward_zigzag_prefers_overload_over_lumos(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_upward_zigzag()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "overload")
        self.assertGreater(conf, 0.78)

    def test_three_turn_broad_zigzag_hits_overload(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_zigzag(segments=4, seg_length=120, vert_step=40, interpolate=8)
        spell, conf = classify_cv_gesture(points, "left")
        self.assertEqual(spell, "overload")
        self.assertGreater(conf, 0.78)

    def test_stationary_broad_zigzag_does_not_hit_overload(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_stationary_broad_zigzag()
        spell, _ = classify_cv_gesture(points, "left")
        self.assertIsNone(spell)

    def test_explain_upward_zigzag_reports_overload(self):
        from cv.gesture_classifier import explain_cv_gesture
        points = self._make_upward_zigzag()
        match = explain_cv_gesture(points, "left")
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "overload")
        self.assertIn("zigzag", match.reason)

    def test_short_trajectory_returns_none(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = [[100, 200], [110, 200], [120, 200]]
        spell, conf = classify_cv_gesture(points, "left")
        self.assertIsNone(spell)
        self.assertEqual(conf, 0.0)

    def test_low_amplitude_jitter_returns_none(self):
        from cv.gesture_classifier import classify_cv_gesture
        points = self._make_jitter()
        spell, conf = classify_cv_gesture(points, "left")
        self.assertIsNone(spell)

    # -- Unit tests (extract_gesture_features) ----------------------------------

    def test_extract_features_returns_none_for_short_input(self):
        from cv.gesture_classifier import extract_gesture_features
        points = [[0, 0], [1, 1], [2, 2], [3, 3]]
        self.assertIsNone(extract_gesture_features(points, "left"))

    def test_extract_features_computes_opponent_dx(self):
        from cv.gesture_classifier import extract_gesture_features
        points = self._make_rightward_line()
        features = extract_gesture_features(points, "left")
        self.assertIsNotNone(features)
        self.assertGreater(features.opponent_dx, 0)

    def test_extract_features_flips_dx_for_right_side(self):
        from cv.gesture_classifier import extract_gesture_features
        points = self._make_rightward_line()
        features_left = extract_gesture_features(points, "left")
        features_right = extract_gesture_features(points, "right")
        self.assertEqual(features_left.opponent_dx, -features_right.opponent_dx)

    # -- Unit tests (individual matchers) ---------------------------------------

    def test_match_lumos_accepts_upward(self):
        from cv.gesture_classifier import GestureFeatures, match_lumos
        features = GestureFeatures(
            points=np.zeros((10, 2), dtype=np.float32),
            dx=10.0, dy=-120.0, x_span=15.0, y_span=80.0,
            path_len=100.0, straightness=0.8, opponent_dx=10.0,
            turn_count=0, area=100.0, raw_count=20,
        )
        match = match_lumos(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "lumos")

    def test_match_lumos_rejects_horizontal(self):
        from cv.gesture_classifier import GestureFeatures, match_lumos
        features = GestureFeatures(
            points=np.zeros((10, 2), dtype=np.float32),
            dx=150.0, dy=-5.0, x_span=160.0, y_span=20.0,
            path_len=160.0, straightness=0.9, opponent_dx=150.0,
            turn_count=0, area=100.0, raw_count=20,
        )
        match = match_lumos(features)
        self.assertIsNone(match)

    def test_match_incendio_accepts_horizontal(self):
        from cv.gesture_classifier import GestureFeatures, match_incendio
        features = GestureFeatures(
            points=np.zeros((10, 2), dtype=np.float32),
            dx=120.0, dy=5.0, x_span=130.0, y_span=20.0,
            path_len=130.0, straightness=0.85, opponent_dx=120.0,
            turn_count=0, area=100.0, raw_count=20,
        )
        match = match_incendio(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "incendio")

    def test_match_stupefy_accepts_circle(self):
        from cv.gesture_classifier import extract_gesture_features, match_stupefy
        features = extract_gesture_features(self._make_circle(), "left")
        self.assertIsNotNone(features)
        match = match_stupefy(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "stupefy")

    def test_match_overload_accepts_zigzag(self):
        from cv.gesture_classifier import GestureFeatures, match_overload
        features = GestureFeatures(
            points=np.zeros((20, 2), dtype=np.float32),
            dx=80.0, dy=30.0, x_span=150.0, y_span=90.0,
            path_len=280.0, straightness=0.3, opponent_dx=80.0,
            turn_count=5, area=500.0, raw_count=20,
        )
        match = match_overload(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "overload")

    # -- Unit test (explain_cv_gesture) -----------------------------------------

    def test_explain_returns_reason(self):
        from cv.gesture_classifier import explain_cv_gesture
        points = self._make_upward_flick()
        match = explain_cv_gesture(points, "left")
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "lumos")
        self.assertTrue(match.reason)

    def test_explain_short_path_returns_reason(self):
        from cv.gesture_classifier import explain_cv_gesture
        points = [[100, 200], [110, 200]]
        match = explain_cv_gesture(points, "left")
        self.assertIsNone(match)

    # -- Phase D: near-miss / edge-case trajectories -------------------------

    def test_wide_horizontal_drift_does_not_trigger_glacius(self):
        """Wide horizontal movement should not match Glacius (|dx| too large)."""
        from cv.gesture_classifier import classify_cv_gesture
        # Move mostly right with slight down: dx large, dy small
        points = []
        for i in range(20):
            points.append([100 + i * 15, 300 + i * 2])
        spell, _ = classify_cv_gesture(points, "left")
        # Should NOT be glacius because |dx| exceeds threshold
        self.assertNotEqual(spell, "glacius")

    def test_small_upward_jitter_does_not_trigger_lumos(self):
        """Tiny upward wiggle should not hit Lumos (y_span too small)."""
        from cv.gesture_classifier import classify_cv_gesture
        points = [[400, 300], [402, 295], [398, 290], [401, 288],
                  [399, 285], [400, 292], [402, 295], [398, 298]]
        spell, _ = classify_cv_gesture(points, "left")
        self.assertNotEqual(spell, "lumos")

    def test_short_drift_does_not_trigger_incendio(self):
        """Barely moving horizontally should not match Incendio (path too short)."""
        from cv.gesture_classifier import classify_cv_gesture
        points = [[100, 200], [105, 201], [110, 200], [115, 201]]
        spell, _ = classify_cv_gesture(points, "left")
        self.assertIsNone(spell)

    def test_diagnose_returns_rejection_reasons(self):
        from cv.gesture_classifier import diagnose_cv_gesture
        points = [[100, 200], [105, 201], [110, 200]]  # way too short
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        self.assertIsNone(result.prediction)
        self.assertTrue(len(result.rejected_reasons) > 0 or "short" in result.message)

    # -- Near-miss boundary diagnosis tests ------------------------------------

    def test_diagnose_incendio_near_miss_just_short(self):
        """Horizontal push that is slightly too short for Incendio."""
        from cv.gesture_classifier import diagnose_cv_gesture, INCENDIO_FAST_OPPONENT_DX_MIN
        points = []
        total_dx = INCENDIO_FAST_OPPONENT_DX_MIN - 5
        step_dx = 9.0
        steps = max(6, int(total_dx / step_dx))
        for i in range(steps):
            points.append([100 + i * step_dx, 300])
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        if result.prediction is None:
            inc_reasons = [r for r in result.rejected_reasons if r.startswith("Incendio")]
            self.assertTrue(len(inc_reasons) > 0, "Expected Incendio rejection reason")

    def test_diagnose_lumos_near_miss_just_too_horizontal(self):
        """Upward flick that drifts too much horizontally."""
        from cv.gesture_classifier import diagnose_cv_gesture
        points = []
        for i in range(20):
            points.append([400 + i * 12, 400 - i * 4])
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        if result.prediction is None:
            lumos_reasons = [r for r in result.rejected_reasons if r.startswith("Lumos")]
            self.assertTrue(len(lumos_reasons) > 0, "Expected Lumos rejection reason")

    def test_diagnose_glacius_near_miss_just_too_horizontal(self):
        """Downward slash that drifts too much horizontally for Glacius."""
        from cv.gesture_classifier import diagnose_cv_gesture
        points = []
        for i in range(20):
            points.append([400 + i * 15, 200 + i * 5])
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        if result.prediction is None:
            glacius_reasons = [r for r in result.rejected_reasons if r.startswith("Glacius")]
            self.assertTrue(len(glacius_reasons) > 0, "Expected Glacius rejection reason")

    def test_diagnose_overload_near_miss_too_few_turns(self):
        """Zigzag with only 2 direction changes (needs 3 for Overload)."""
        from cv.gesture_classifier import diagnose_cv_gesture
        x, y = 200.0, 100.0
        points = [[x, y]]
        segments = [(80, 25), (-80, 25)]
        for dx, dy in segments:
            for t in range(8):
                x += dx / 8
                y += dy / 8
                points.append([x, y])
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        if result.prediction is None:
            overload_reasons = [r for r in result.rejected_reasons if r.startswith("Overload")]
            self.assertTrue(len(overload_reasons) > 0, "Expected Overload rejection reason")

    def test_diagnose_reports_feature_values(self):
        """Diagnose should populate features with usable numeric values."""
        from cv.gesture_classifier import diagnose_cv_gesture
        points = self._make_rightward_line()
        result = diagnose_cv_gesture(points, "left")
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.features)
        f = result.features
        self.assertGreater(f.path_len, 0)
        self.assertNotEqual(f.dx, 0)
        self.assertGreater(f.raw_count, 0)

    def test_match_glacius_accepts_downward(self):
        """Unit test: Glacius fast-path accepts a steep downward feature set."""
        from cv.gesture_classifier import GestureFeatures, match_glacius
        features = GestureFeatures(
            points=np.zeros((10, 2), dtype=np.float32),
            dx=5.0, dy=140.0, x_span=20.0, y_span=150.0,
            path_len=155.0, straightness=0.75, opponent_dx=5.0,
            turn_count=0, area=100.0, raw_count=15,
        )
        match = match_glacius(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "glacius")

    def test_match_glacius_shape_accepts_long_downward(self):
        """Unit test: Glacius shape-path accepts a long downward trajectory."""
        from cv.gesture_classifier import GestureFeatures, match_glacius
        features = GestureFeatures(
            points=np.zeros((20, 2), dtype=np.float32),
            dx=10.0, dy=180.0, x_span=30.0, y_span=190.0,
            path_len=200.0, straightness=0.80, opponent_dx=10.0,
            turn_count=1, area=200.0, raw_count=20,
        )
        match = match_glacius(features)
        self.assertIsNotNone(match)
        self.assertEqual(match.spell, "glacius")


if __name__ == "__main__":
    unittest.main()
