import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeTrack:
    def __init__(self):
        self.wand_roi = None
        self.wand_raw_point = None
        self.last_valid_point = None
        self.last_valid_time = 0.0
        self.velocity = None
        self.missed_frames = 0
        self.wand_hue = None
        self.wand_sat_min = 70
        self.wand_val_min = 70
        self.wand_color_bgr = None

    @property
    def wand_color_calibrated(self):
        return self.wand_hue is not None


def fake_hand_landmarks():
    coords = [
        (0.50, 0.50),  # wrist
        (0.48, 0.45),
        (0.47, 0.42),
        (0.47, 0.39),
        (0.46, 0.36),
        (0.45, 0.46),
        (0.43, 0.41),
        (0.42, 0.36),
        (0.41, 0.31),
        (0.53, 0.43),  # middle MCP
        (0.54, 0.38),
        (0.55, 0.33),
        (0.56, 0.28),
        (0.57, 0.45),
        (0.58, 0.40),
        (0.59, 0.35),
        (0.60, 0.30),
        (0.61, 0.48),
        (0.62, 0.43),
        (0.63, 0.38),
        (0.64, 0.33),
    ]
    return [SimpleNamespace(x=x, y=y) for x, y in coords]


def bgr_from_hsv(hue, saturation, value):
    hsv = np.uint8([[[hue, saturation, value]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return tuple(int(channel) for channel in bgr)


class WandDetectorTests(unittest.TestCase):
    def test_calibrate_locks_bright_center_marker(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()

        ok, message = detector.calibrate(frame)

        self.assertTrue(ok)
        self.assertIn("CV WAND LOCKED", message)
        self.assertIsNotNone(detector.wand_hue)
        self.assertIsNotNone(detector.wand_color_bgr)

    def test_detect_tip_reports_clear_message_when_uncalibrated(self):
        from cv.wand_detector import WandDetector

        detector = WandDetector()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNone(point)
        self.assertIn("press C", detail)

    def test_detect_tip_finds_bright_marker_inside_hand_roi(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 11, (0, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNotNone(point, detail)
        self.assertLess(np.linalg.norm(point - np.array([235, 95], dtype=np.float32)), 3.0)
        self.assertIsNotNone(track.wand_roi)
        self.assertIsNotNone(track.wand_raw_point)

    def test_detect_tip_honors_preferred_candidate_when_same_color_markers_overlap(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (210, 95), 8, (0, 255, 255), -1)
        cv2.circle(frame, (250, 95), 13, (0, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(
            frame,
            fake_hand_landmarks(),
            track,
            10.0,
            320,
            240,
            preferred_point=np.array([250.0, 95.0], dtype=np.float32),
        )

        self.assertIsNotNone(point, detail)
        self.assertLess(np.linalg.norm(point - np.array([250.0, 95.0], dtype=np.float32)), 8.0)
        self.assertEqual(track.wand_tracker_debug["assignment"], "preferred")

    def test_detect_tip_rejects_low_saturation_background(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 12, (180, 180, 180), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNone(point)
        self.assertIn("no bright tip", detail)

    def test_short_marker_loss_coasts_from_wand_tracker(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        track = FakeTrack()

        frame[:, :] = 0
        cv2.circle(frame, (220, 95), 10, (0, 255, 255), -1)
        point1, _ = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.00, 320, 240)
        self.assertIsNotNone(point1)

        frame[:, :] = 0
        cv2.circle(frame, (244, 95), 10, (0, 255, 255), -1)
        point2, _ = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.08, 320, 240)
        self.assertIsNotNone(point2)

        frame[:, :] = 0
        point3, detail3 = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.13, 320, 240)

        self.assertIsNotNone(point3, detail3)
        self.assertIn("coasting", detail3)
        self.assertGreater(point3[0], point2[0])

    def test_wand_tracker_stops_coasting_after_timeout(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        track = FakeTrack()

        frame[:, :] = 0
        cv2.circle(frame, (220, 95), 10, (0, 255, 255), -1)
        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.00, 320, 240)

        frame[:, :] = 0
        cv2.circle(frame, (244, 95), 10, (0, 255, 255), -1)
        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.08, 320, 240)

        frame[:, :] = 0
        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.70, 320, 240)

        self.assertIsNone(point)
        self.assertEqual(track.wand_tracker_state, "LOST")
        self.assertIn("lost", detail.lower())

    def test_detector_success_sets_locked_confidence_and_debug(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 11, (0, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNotNone(point, detail)
        self.assertEqual(track.wand_tracker_state, "LOCKED")
        self.assertEqual(track.wand_tracker_source, "detector")
        self.assertGreaterEqual(track.wand_tracker_confidence, 0.55)
        self.assertIn("conf", detail)
        self.assertEqual(track.wand_tracker_debug["state"], "LOCKED")
        self.assertEqual(track.wand_tracker_debug["source"], "detector")
        self.assertGreaterEqual(detector.last_detail.best_score, 0.55)

    def test_detector_uses_lk_flow_when_color_mask_weakens_but_color_support_remains(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        track = FakeTrack()

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (225, 95), 11, (0, 255, 255), -1)
        point1, detail1 = detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.00, 320, 240)
        self.assertIsNotNone(point1, detail1)

        # Same shape in pale yellow: strong HSV detector can fail, but weak color support remains.
        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (247, 96), 11, (120, 255, 255), -1)
        point2, detail2 = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.06, 320, 240)

        self.assertIsNotNone(point2, detail2)
        self.assertIn("flow", detail2.lower())
        self.assertEqual(track.wand_tracker_state, "FLOW")
        self.assertEqual(track.wand_tracker_source, "lk")
        self.assertGreater(point2[0], point1[0] + 5.0)

    def test_lk_does_not_flow_to_white_light_without_color_support(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        track = FakeTrack()

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (225, 95), 11, (0, 255, 255), -1)
        point1, detail1 = detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.00, 320, 240)
        self.assertIsNotNone(point1, detail1)

        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (247, 96), 13, (255, 255, 255), -1)
        point2, detail2 = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.06, 320, 240)

        self.assertIsNotNone(point2, detail2)
        self.assertNotIn("flow", detail2.lower())
        self.assertNotEqual(track.wand_tracker_source, "lk")
        self.assertLess(np.linalg.norm(point2 - np.array([247, 96], dtype=np.float32)), 35.0)
        self.assertLess(point2[0], 240.0)

    def test_weak_far_detector_candidate_does_not_pull_tracker(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)
        track = FakeTrack()

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (200, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        point1, detail1 = detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.00, 320, 240)
        self.assertIsNotNone(point1, detail1)

        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (300, 95), 6, bgr_from_hsv(30, 200, 180), -1)
        point2, detail2 = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.06, 320, 240)

        self.assertIsNotNone(point2, detail2)
        self.assertNotEqual(track.wand_tracker_source, "detector")
        self.assertEqual(track.wand_tracker_debug["observation_gate"], "reject_jump")
        self.assertGreater(track.wand_tracker_debug["observation_jump"], 90.0)

    def test_strong_far_detector_candidate_relocks_filter(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)
        track = FakeTrack()

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (200, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.00, 320, 240)

        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (300, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        point2, detail2 = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.06, 320, 240)

        self.assertIsNotNone(point2, detail2)
        self.assertEqual(track.wand_tracker_state, "LOCKED")
        self.assertEqual(track.wand_tracker_source, "detector")
        self.assertLess(np.linalg.norm(point2 - np.array([300, 95], dtype=np.float32)), 8.0)
        self.assertEqual(track.wand_tracker_debug["observation_gate"], "strong_relock")
        self.assertIn("raw_filtered_delta", track.wand_tracker_debug)

    def test_fast_continuous_marker_motion_stays_accepted(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)
        track = FakeTrack()

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (200, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        point1, _ = detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.00, 320, 240)

        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (248, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        point2, detail2 = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.06, 320, 240)

        self.assertIsNotNone(point2, detail2)
        self.assertEqual(track.wand_tracker_state, "LOCKED")
        self.assertEqual(track.wand_tracker_debug["observation_gate"], "accept")
        self.assertIn("observation_jump", track.wand_tracker_debug)
        self.assertGreater(point2[0], point1[0] + 20.0)

    def test_wand_tracker_enters_lost_after_short_coast_timeout(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        track = FakeTrack()

        frame[:, :] = 0
        cv2.circle(frame, (220, 95), 10, (0, 255, 255), -1)
        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.00, 320, 240)

        frame[:, :] = 0
        cv2.circle(frame, (244, 95), 10, (0, 255, 255), -1)
        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.08, 320, 240)

        frame[:, :] = 0
        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.32, 320, 240)

        self.assertIsNone(point)
        self.assertEqual(track.wand_tracker_state, "LOST")
        self.assertIn("lost", detail.lower())

    # -- Phase B: structured detail & rejection counters ----------------------

    def test_last_detail_populated_on_success(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 11, (0, 255, 255), -1)
        track = FakeTrack()

        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        detail = detector.last_detail
        self.assertEqual(detail.status, "ok")
        self.assertGreater(detail.mask_pixels, 0)
        self.assertGreater(detail.contour_count, 0)
        self.assertGreater(detail.candidate_count, 0)

    def test_last_detail_populated_on_uncalibrated(self):
        from cv.wand_detector import WandDetector

        detector = WandDetector()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        track = FakeTrack()

        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertEqual(detector.last_detail.status, "uncalibrated")

    def test_last_detail_on_no_candidate(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        # frame with no bright marker near the hand ROI
        frame[:, :] = 0
        track = FakeTrack()
        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertEqual(detector.last_detail.status, "no_candidate")

    def test_two_blobs_picks_better_scored_one(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        # Two blobs: one good, one smaller/dimmer near hand ROI area
        frame[:, :] = 0
        cv2.circle(frame, (242, 88), 10, (0, 255, 255), -1)   # good candidate
        cv2.circle(frame, (220, 100), 3, (0, 200, 200), -1)    # weaker
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertIsNotNone(point, detail)
        self.assertGreater(detector.last_detail.candidate_count, 0)

    def test_compact_marker_beats_elongated_endpoint_candidate(self):
        from cv.wand_detector import WandDetector

        marker_color = bgr_from_hsv(105, 255, 255)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, marker_color, -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (245, 90), 9, marker_color, -1)
        cv2.rectangle(frame, (205, 120), (265, 132), marker_color, -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNotNone(point, detail)
        self.assertEqual(track.wand_tracker_source, "detector")
        self.assertEqual(detector.last_detail.source, "blob")
        self.assertLess(np.linalg.norm(point - np.array([245, 90], dtype=np.float32)), 8.0)

    def test_marker_near_palm_is_rejected(self):
        from cv.wand_detector import WandDetector
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        # Place marker very close to the palm center (~160,120) — should be rejected
        frame[:, :] = 0
        # hand landmarks put palm near (160,120); draw marker at (165,125)
        cv2.circle(frame, (170, 111), 8, (0, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertIsNone(point, detail)
        self.assertGreater(detector.last_detail.rejected_near_palm, 0)

    def test_low_saturation_is_rejected_with_detail(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        ok, _ = detector.calibrate(frame)
        self.assertTrue(ok)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 12, (180, 180, 180), -1)
        track = FakeTrack()

        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertEqual(detector.last_detail.status, "no_candidate")

    # -- Phase C: endpoint detection via PCA ---------------------------------

    def test_endpoint_candidates_finds_long_rectangle(self):
        """A colored elongated rectangle should produce endpoint candidates."""
        from cv.wand_detector import WandDetector

        # Calibrate on a yellow dot
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        # Now draw a long yellow rectangle far enough from palm center
        frame[:, :] = 0
        # Rectangle: 50x12 px at (210, 85) → bottom-right at (260, 97)
        cv2.rectangle(frame, (210, 85), (260, 97), (0, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertIsNotNone(point, detail)
        # The detected tip should be near the rectangle, not at the palm center
        self.assertIn("endpoint", detail)
        self.assertGreater(point[0], 252.0)

    def test_endpoint_candidates_rejects_short_blob(self):
        """A small dot should still work via blob (not forced into endpoint mode)."""
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        # Draw a small dot far from palm — blob mode should handle it
        frame[:, :] = 0
        cv2.circle(frame, (240, 90), 8, (0, 255, 255), -1)  # 8px radius circle
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertIsNotNone(point, detail)
        self.assertNotIn("endpoint", detail)
        # The detected tip should be near the circle center
        self.assertLess(abs(point[0] - 240), 6.0)
        self.assertLess(abs(point[1] - 90), 6.0)

    def test_endpoint_candidates_empty_on_low_saturation_shape(self):
        """A long gray rectangle (low saturation) produces no endpoint candidates."""
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, (0, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        # Draw a long gray rectangle — hue and sat should fail
        frame[:, :] = 0
        cv2.rectangle(frame, (210, 85), (260, 97), (150, 150, 150), -1)
        track = FakeTrack()

        detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertEqual(detector.last_detail.status, "no_candidate")

    def test_debug_includes_candidate_list(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        frame[:, :] = 0
        cv2.circle(frame, (235, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        track = FakeTrack()

        point, detail = detector.detect_tip(frame, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertIsNotNone(point)
        self.assertIn("candidates", track.wand_tracker_debug)
        self.assertGreaterEqual(len(track.wand_tracker_debug["candidates"]), 1)
        self.assertEqual(track.wand_tracker_debug["candidate_count"], len(track.wand_tracker_debug["candidates"]))

    def _go_lost(self, detector, track, start_time, no_marker_duration=0.25):
        """Helper: leave the detector in LOST state."""
        frame_blank = np.zeros((240, 320, 3), dtype=np.uint8)
        detector.detect_tip(frame_blank, fake_hand_landmarks(), track, start_time + no_marker_duration, 320, 240)
        self.assertEqual(track.wand_tracker_state, "LOST")

    def test_single_low_score_frame_does_not_relock(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (200, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        track = FakeTrack()
        detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.0, 320, 240)
        self.assertEqual(track.wand_tracker_state, "LOCKED")

        self._go_lost(detector, track, 10.0)

        # Too small to lock (radius 3, low sat/val → score ~0.52 < 0.55)
        frame2 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame2, (260, 95), 3, bgr_from_hsv(30, 185, 160), -1)
        point, _detail = detector.detect_tip(frame2, fake_hand_landmarks(), track, 10.30, 320, 240)
        self.assertIsNone(point)

    def test_candidate_history_initialized_in_detect_tip(self):
        from cv.wand_detector import WandDetector

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame, (160, 120), 10, bgr_from_hsv(30, 255, 255), -1)
        detector = WandDetector()
        detector.calibrate(frame)

        frame1 = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.circle(frame1, (200, 95), 11, bgr_from_hsv(30, 255, 255), -1)
        track = FakeTrack()
        detector.detect_tip(frame1, fake_hand_landmarks(), track, 10.0, 320, 240)

        self.assertIsNotNone(track.wand_candidate_history)
        self.assertGreaterEqual(len(track.wand_candidate_history.samples), 1)

    def test_best_detector_candidate_populates_history(self):
        from cv.wand_detector import WandDetector
        from cv.wand_tracking import WandCandidateHistory

        history = WandCandidateHistory(maxlen=3)
        history.add(np.array([200.0, 95.0]), 0.72, 140.0, "blob", 10.0)
        history.add(np.array([202.0, 95.0]), 0.70, 138.0, "blob", 10.06)

        self.assertTrue(history.stable_near(np.array([201.0, 95.0]), now=10.12))

    def test_detection_rejects_unstable_low_score_in_lost(self):
        from cv.wand_detector import WandDetector
        from cv.wand_tracking import WandCandidateHistory

        history = WandCandidateHistory(maxlen=3)
        history.add(np.array([200.0, 95.0]), 0.72, 140.0, "blob", 10.0)

        self.assertFalse(history.stable_near(np.array([210.0, 95.0]), now=10.06, min_count=2))

    def test_low_score_candidate_relocks_when_history_is_stable(self):
        from cv.wand_detector import WandDetector
        from cv.wand_tracking import DetectionResult

        detector = WandDetector()
        track = FakeTrack()
        history = detector._get_candidate_history(track)
        history.add(np.array([200.0, 95.0], dtype=np.float32), 0.58, 140.0, "blob", 10.00)
        history.add(np.array([203.0, 96.0], dtype=np.float32), 0.58, 142.0, "blob", 10.06)
        detection = DetectionResult(
            ok=True,
            point=np.array([203.0, 96.0], dtype=np.float32),
            score=0.58,
            source="blob",
            debug={"area": 142.0},
        )

        self.assertTrue(detector._accept_detection(detection, "LOST", track, 10.06))

    def test_borderline_score_candidate_relocks_only_when_history_is_stable(self):
        from cv.wand_detector import WandDetector
        from cv.wand_tracking import DetectionResult

        detector = WandDetector()
        track = FakeTrack()
        history = detector._get_candidate_history(track)
        history.add(np.array([760.0, 520.0], dtype=np.float32), 0.52, 360.0, "blob", 10.00)
        history.add(np.array([763.0, 521.0], dtype=np.float32), 0.52, 365.0, "blob", 10.06)
        detection = DetectionResult(
            ok=True,
            point=np.array([763.0, 521.0], dtype=np.float32),
            score=0.52,
            source="blob",
            debug={"area": 365.0},
        )

        self.assertTrue(detector._accept_detection(detection, "LOST", track, 10.06))

    def test_stable_lost_candidate_is_not_blocked_by_stale_prediction_jump(self):
        from cv.wand_detector import WandDetector
        from cv.wand_tracking import DetectionResult

        detector = WandDetector()
        track = FakeTrack()
        track.wand_tracker_state = "LOST"
        track.wand_lost_since = 10.00
        track.wand_tracker_time = 10.00
        history = detector._get_candidate_history(track)
        history.add(np.array([760.0, 520.0], dtype=np.float32), 0.53, 360.0, "blob", 10.02)
        history.add(np.array([763.0, 521.0], dtype=np.float32), 0.53, 365.0, "blob", 10.08)
        detection = DetectionResult(
            ok=True,
            point=np.array([763.0, 521.0], dtype=np.float32),
            score=0.53,
            source="blob",
            debug={"area": 365.0},
        )

        gate = detector._observation_gate(
            detection,
            np.array([420.0, 300.0], dtype=np.float32),
            track,
            10.08,
        )

        self.assertNotEqual(gate, "reject_jump")
        self.assertTrue(detector._accept_detection(detection, "LOST", track, 10.08))

    def test_coasting_output_starts_coast_timer(self):
        from cv.wand_detector import WandDetector

        detector = WandDetector()
        track = FakeTrack()
        track.wand_tracker_time = 10.0
        track.wand_tracker_coast_started = 0.0

        detector._mark_tracker_output(
            track,
            np.array([120.0, 80.0], dtype=np.float32),
            10.06,
            "COASTING",
            "prediction",
            0.32,
            {"reject_reason": "jump"},
            good_observation=False,
        )

        self.assertEqual(track.wand_tracker_state, "COASTING")
        self.assertAlmostEqual(track.wand_tracker_coast_started, 10.06)


if __name__ == "__main__":
    unittest.main()
