import sys
import unittest
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class WandTrackingHelperTests(unittest.TestCase):
    def test_alpha_beta_filter_updates_velocity_and_coasts(self):
        from cv.wand_tracking import AlphaBetaFilter2D

        filt = AlphaBetaFilter2D()

        first = filt.update(np.array([20.0, 30.0], dtype=np.float32), 1.00, 1.0)
        second = filt.update(np.array([32.0, 30.0], dtype=np.float32), 1.10, 1.0)
        coasted = filt.coast(1.16)

        self.assertLess(np.linalg.norm(first - np.array([20.0, 30.0], dtype=np.float32)), 0.01)
        self.assertGreater(float(np.linalg.norm(filt.v)), 1.0)
        self.assertGreater(second[0], first[0])
        self.assertGreater(coasted[0], second[0])

        filt.reset()
        self.assertIsNone(filt.predict(1.20))

    def test_alpha_beta_filter_follows_fast_start_with_limited_lag(self):
        from cv.wand_tracking import AlphaBetaFilter2D

        filt = AlphaBetaFilter2D()

        filt.update(np.array([100.0, 100.0], dtype=np.float32), 10.00, 1.0)
        point = filt.update(np.array([230.0, 100.0], dtype=np.float32), 10.06, 1.0)

        self.assertGreater(point[0], 200.0)

    def test_alpha_beta_filter_follows_sharp_turn_with_limited_lag(self):
        from cv.wand_tracking import AlphaBetaFilter2D

        filt = AlphaBetaFilter2D()

        filt.update(np.array([100.0, 100.0], dtype=np.float32), 10.00, 1.0)
        filt.update(np.array([170.0, 100.0], dtype=np.float32), 10.06, 1.0)
        point = filt.update(np.array([170.0, 30.0], dtype=np.float32), 10.12, 1.0)

        self.assertLess(point[1], 48.0)

    def test_sparse_lk_tracker_tracks_shifted_marker(self):
        from cv.wand_tracking import SparseLKTracker

        frame1 = np.zeros((120, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((120, 160, 3), dtype=np.uint8)
        cv2.rectangle(frame1, (45, 45), (65, 65), (255, 255, 255), -1)
        cv2.rectangle(frame2, (57, 51), (77, 71), (255, 255, 255), -1)

        tracker = SparseLKTracker()
        tracker.initialize(frame1, np.array([55.0, 55.0], dtype=np.float32), (45, 45, 65, 65))
        result = tracker.update(frame2)

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["valid_points"], 3)
        self.assertGreaterEqual(result["confidence"], 0.45)
        self.assertLess(np.linalg.norm(result["point"] - np.array([67.0, 61.0], dtype=np.float32)), 3.0)

    def test_sparse_lk_tracker_returns_none_without_features(self):
        from cv.wand_tracking import SparseLKTracker

        frame1 = np.zeros((120, 160, 3), dtype=np.uint8)
        frame2 = np.zeros((120, 160, 3), dtype=np.uint8)

        tracker = SparseLKTracker()
        tracker.initialize(frame1, np.array([55.0, 55.0], dtype=np.float32), (45, 45, 65, 65))

        self.assertIsNone(tracker.update(frame2))

    def test_roi_helpers_clip_and_union_rois(self):
        from cv.wand_tracking import roi_around_point, union_rois

        roi = roi_around_point(np.array([8.0, 9.0], dtype=np.float32), (100, 120, 3), 20)
        self.assertEqual(roi, (0, 0, 28, 29))

        merged = union_rois([(5, 8, 20, 20), (18, 2, 30, 10)], (100, 120, 3))
        self.assertEqual(merged, (5, 2, 30, 20))

    def test_choose_wand_search_roi_expands_with_tracker_state(self):
        from cv.wand_tracking import choose_wand_search_roi

        frame_shape = (240, 320, 3)
        hand_roi = (120, 70, 240, 180)
        predicted = np.array([250.0, 90.0], dtype=np.float32)

        locked = choose_wand_search_roi("LOCKED", frame_shape, predicted, hand_roi, 0.0)
        flow = choose_wand_search_roi("FLOW", frame_shape, predicted, hand_roi, 0.05)
        lost = choose_wand_search_roi("LOST", frame_shape, predicted, hand_roi, 0.2)

        self.assertLessEqual(locked[0], 120)
        self.assertGreaterEqual(locked[2], 300)
        self.assertLessEqual(flow[0], locked[0])
        self.assertGreaterEqual(flow[3] - flow[1], locked[3] - locked[1])
        self.assertLessEqual(lost[0], hand_roi[0])
        self.assertGreaterEqual(lost[2], predicted[0])
        self.assertGreaterEqual(lost[2] - lost[0], hand_roi[2] - hand_roi[0])

    def test_candidate_history_detects_stable_nearby_candidates(self):
        from cv.wand_tracking import WandCandidateHistory

        history = WandCandidateHistory(maxlen=5)
        history.add(np.array([100.0, 100.0]), 0.58, 80.0, "blob", 1.0)
        history.add(np.array([102.0, 99.0]), 0.57, 82.0, "blob", 1.05)

        self.assertTrue(history.stable_near(np.array([101.0, 100.0]), now=1.06))

    def test_candidate_history_rejects_far_or_old_candidates(self):
        from cv.wand_tracking import WandCandidateHistory

        history = WandCandidateHistory(maxlen=5)
        history.add(np.array([100.0, 100.0]), 0.58, 80.0, "blob", 1.0)
        history.add(np.array([102.0, 99.0]), 0.57, 82.0, "blob", 1.05)

        self.assertFalse(history.stable_near(np.array([300.0, 300.0]), now=1.06))
        self.assertFalse(history.stable_near(np.array([101.0, 100.0]), now=1.35))

    def test_candidate_history_reset_clears_samples(self):
        from cv.wand_tracking import WandCandidateHistory

        history = WandCandidateHistory(maxlen=5)
        history.add(np.array([100.0, 100.0]), 0.58, 80.0, "blob", 1.0)
        history.reset()

        self.assertFalse(history.stable_near(np.array([100.0, 100.0]), now=1.05))

    def test_dynamic_jump_limit_is_higher_for_fast_motion(self):
        from cv.wand_tracking import dynamic_jump_limit

        slow = dynamic_jump_limit(0.0, 0.05, 0.0, 0.55)
        fast = dynamic_jump_limit(1200.0, 0.05, 0.0, 0.55)
        self.assertLess(slow, fast)
        self.assertAlmostEqual(slow, 90.0, places=1)

    def test_dynamic_jump_limit_increases_with_lost_duration_and_score(self):
        from cv.wand_tracking import dynamic_jump_limit

        base = dynamic_jump_limit(0.0, 0.05, 0.0, 0.55)
        lost = dynamic_jump_limit(0.0, 0.05, 0.2, 0.55)
        strong = dynamic_jump_limit(0.0, 0.05, 0.0, 0.70)
        self.assertGreater(lost, base)
        self.assertGreater(strong, base)
        self.assertLessEqual(dynamic_jump_limit(10000.0, 1.0, 1.0, 1.0), 260.0)


if __name__ == "__main__":
    unittest.main()
