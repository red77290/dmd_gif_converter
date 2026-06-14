"""
Unit tests for tracker.py face-detection clip logic (v6.1.0+).

Regression coverage:
  - face_priority_mode + face/head close-up (bbox aspect <= 1.4): tracker must
    skip hair (top 25 %) and keep eye region (35 %).
  - face_priority_mode + full-body shot (bbox aspect > 1.4): tracker must
    extract 1 head height (~18 % of body bbox) with hair-skip (25 %) and keep
    eye zone (40 % of head). Previously, a tall body bbox that exceeded the
    old 40%-of-frame-height threshold incorrectly applied face-close-up
    proportions, centering the camera on the waist/chest instead of the eyes.
  - Non-face_priority_mode: roi is passed through without modification.
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np


def _make_tracker(frame_h=480, face_priority=True):
    """Return a minimal TrackingEngine without real detector/ONNX loading.

    Size/area filters (min_roi_area_ratio, min_subject_dmd_px) are disabled so
    that the face-clipping unit tests are not affected by them — those filters
    are tested separately and should not interfere with clip-logic assertions.
    """
    from src.engine.config.auto_action_config import AutoActionConfig
    cfg = AutoActionConfig(
        target_width=128, target_height=32,
        detector="person",
        smart_auto_crop=True,
        smoothness=0.0,
        zoom_max=2.0,
        min_roi_area_ratio=0.0,   # disable: don't filter small clipped rois
        min_subject_dmd_px=0,     # disable: don't filter small clipped rois
    )
    with patch("src.plugins.detectors.detector.DetectorFactory.create") as mock_factory, \
         patch("src.plugins.detectors.detector._ensure_yolo_model", return_value=None):
        mock_factory.return_value = MagicMock()
        from src.plugins.trackers.tracker import TrackingEngine
        tracker = TrackingEngine(
            fps=25.0,
            frame_w=640, frame_h=frame_h,
            effective_frame_top=0,
            effective_frame_h=frame_h,
            effective_frame_left=0,
            effective_frame_w=640,
            face_priority_mode=face_priority,
            cfg=cfg,
        )
    return tracker


class TestTrackerCloseUpClip(unittest.TestCase):
    """
    Regression (v6.1.0+): in face_priority_mode, the roi clip must adapt to
    the bbox type (face close-up vs full-body shot) using the aspect ratio
    (rh/rw) instead of an absolute frame-height ratio.

    - aspect <= 1.4 (square-ish): face/head close-up → skip hair (25 %),
      keep eye region (35 %).
    - aspect  > 1.4 (tall/narrow): full-body bbox → extract head zone (~18 %
      of body height) with hair-skip (25 %) and eye zone (40 % of head).
    """

    def _get_processed_roi(self, original_roi, frame_h=480,
                           face_priority=True, is_closeup_expected=True):
        """
        Run one frame through the tracker with a mocked detector that always
        returns original_roi, and capture the roi that is passed to
        _build_camera_rect.
        """
        captured = {}

        tracker = _make_tracker(frame_h=frame_h, face_priority=face_priority)
        # Mock detector always returns our roi
        tracker.detector.detect = MagicMock(return_value=original_roi)

        frame = np.zeros((frame_h, 640, 3), dtype=np.uint8)
        cam_prev = tracker.cam_full_view

        def capture_roi(fw, fh, roi, cfg, *args, **kwargs):
            captured["roi"] = roi
            from src.engine.auto_action.camera import _build_camera_rect as real
            return real(fw, fh, roi, cfg, *args, **kwargs)

        with patch("src.plugins.trackers.tracker._build_camera_rect",
                   side_effect=capture_roi):
            tracker.process_frame(frame, cam_prev, src_idx=0,
                                  out_w=128, out_h=32)

        return captured.get("roi")

    def test_closeup_clips_to_eye_region(self):
        """
        Face close-up: bbox (rw=540, rh=460) → aspect 0.85 <= 1.4.
        Clip skips hair (top 25 %) and keeps eye region (35 %).
        Expected: ry_new = 0 + 161, rh_new = 138.
        """
        original = (50, 0, 540, 460)   # wide face bbox, aspect ≈ 0.85
        result = self._get_processed_roi(original, frame_h=480)

        self.assertIsNotNone(result, "roi should not be None")
        rx, ry, rw, rh = result
        orig_rh = 460

        # Check hair was skipped
        expected_skip = int(orig_rh * 0.25)
        expected_h    = max(8, int(orig_rh * 0.35))

        self.assertEqual(ry, 0 + expected_skip,
                         f"ry should skip top 25 % of original bbox. "
                         f"Got {ry}, expected {0 + expected_skip}")
        self.assertEqual(rh, expected_h,
                         f"rh should be 35 % of original bbox. "
                         f"Got {rh}, expected {expected_h}")

    def test_closeup_is_not_top_28_percent(self):
        """Face close-up (aspect <= 1.4) must NOT use the old top-28 % formula (= hair)."""
        original = (50, 0, 540, 460)
        result = self._get_processed_roi(original, frame_h=480)
        rx, ry, rh_clip = result[0], result[1], result[3]

        old_clip_h = max(8, int(460 * 0.28))  # old formula: 128 px (hair)
        new_clip_h = max(8, int(460 * 0.35))  # new formula: 161 px (eyes)

        # The clipped height should match the face-close-up formula
        self.assertEqual(rh_clip, new_clip_h,
                         "Face close-up should use 35 % clip height, not 28 %")
        # And ry must be shifted down (hair skipped)
        self.assertGreater(ry, 0,
                           "ry must be > 0 (hair at top should be skipped)")

    def test_full_body_shot_clips_to_head_eye_region(self):
        """
        Full-body shot: bbox (rw=80, rh=300) → aspect 3.75 > 1.4.
        Tracker must extract the eye zone adaptively based on aspect ratio.
        For aspect 3.75, eye_target_pct is ~0.08, roi_h is 10% of body (30px).
        """
        original = (100, 50, 80, 300)   # tall/narrow = full-body, aspect ≈ 3.75
        result = self._get_processed_roi(original, frame_h=480)

        self.assertIsNotNone(result, "roi should not be None")
        rx, ry, rw, rh = result

        # New adaptive formula:
        aspect = 300 / 80.0
        eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
        expected_h = max(8, int(300 * 0.10))
        roi_top = max(0, int(300 * eye_target_pct - expected_h / 2.0))

        self.assertEqual(ry, 50 + roi_top,
                         f"Full-body: ry should adaptively target eyes. "
                         f"Got {ry}, expected {50 + roi_top}")
        self.assertEqual(rh, expected_h,
                         f"Full-body: rh should be 10% of body_h. "
                         f"Got {rh}, expected {expected_h}")

        eye_cy_in_body = (ry - 50) + rh / 2.0   # relative to original ry
        self.assertLess(eye_cy_in_body, 300 * 0.15,
                        f"Eye centre ({eye_cy_in_body:.1f} px) must be in top 15 % of body "
                        f"bbox ({300 * 0.15:.1f} px).")

    def test_no_face_priority_roi_unchanged(self):
        """Without face_priority_mode the roi must not be clipped at all."""
        original = (50, 0, 540, 460)   # same large roi
        result = self._get_processed_roi(original, frame_h=480,
                                         face_priority=False)
        rx, ry, rw, rh = result
        # The effective_frame_top correction (top=0) leaves roi unchanged
        self.assertEqual(ry, 0)
        self.assertEqual(rh, 460)

    def test_none_roi_propagates(self):
        """If detector returns None, process_frame must not crash."""
        tracker = _make_tracker(frame_h=480, face_priority=True)
        tracker.detector.detect = MagicMock(return_value=None)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cam = tracker.process_frame(frame, tracker.cam_full_view, 0, 128, 32)
        self.assertIsNotNone(cam)
        self.assertEqual(len(cam), 4)


class TestTrackerCloseUpThreshold(unittest.TestCase):
    """Edge cases around the aspect-ratio 1.4 threshold (rh/rw)."""

    def _get_roi(self, roi_tuple, frame_h=480):
        tracker = _make_tracker(frame_h=frame_h, face_priority=True)
        tracker.detector.detect = MagicMock(return_value=roi_tuple)
        frame = np.zeros((frame_h, 640, 3), dtype=np.uint8)
        captured = {}

        def cap(fw, fh, roi, cfg, *a, **kw):
            captured["roi"] = roi
            from src.engine.auto_action.camera import _build_camera_rect as r
            return r(fw, fh, roi, cfg, *a, **kw)

        with patch("src.plugins.trackers.tracker._build_camera_rect",
                   side_effect=cap):
            tracker.process_frame(frame, tracker.cam_full_view, 0, 128, 32)

        return captured.get("roi")

    def test_square_bbox_uses_face_closeup_clip(self):
        """
        Square bbox (rw=200, rh=200) → aspect 1.0 <= 1.4 → face close-up path.
        Must use hair-skip (25 %) + eye region (35 %).
        """
        result = self._get_roi((50, 0, 200, 200), frame_h=480)
        self.assertIsNotNone(result)
        expected_skip = int(200 * 0.25)   # 50
        expected_h    = max(8, int(200 * 0.35))  # 70
        self.assertEqual(result[1], expected_skip, "ry should be hair-skip for square bbox")
        self.assertEqual(result[3], expected_h,    "rh should be eye region for square bbox")

    def test_tall_bbox_uses_fullbody_head_clip(self):
        """
        Tall bbox (rw=60, rh=300) → aspect 5.0 > 1.4 → full-body path.
        Must use adaptive eye targeting.
        """
        result = self._get_roi((50, 0, 60, 300), frame_h=480)
        self.assertIsNotNone(result)

        aspect = 300 / 60.0
        eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
        expected_h = max(8, int(300 * 0.10))
        roi_top = max(0, int(300 * eye_target_pct - expected_h / 2.0))

        self.assertEqual(result[1], roi_top, "ry: full-body adaptive eye target")
        self.assertEqual(result[3], expected_h,    "rh: full-body eye zone")

    def test_borderline_aspect_just_below_threshold_uses_face_clip(self):
        """bbox aspect = 1.4 (border) → aspect <= 1.4 → face close-up path."""
        # rw=100, rh=140 → aspect exactly 1.4
        result = self._get_roi((50, 0, 100, 140), frame_h=480)
        self.assertIsNotNone(result)
        expected_skip = int(140 * 0.25)
        expected_h    = max(8, int(140 * 0.35))
        self.assertEqual(result[1], expected_skip)
        self.assertEqual(result[3], expected_h)

    def test_borderline_aspect_just_above_threshold_uses_body_clip(self):
        """bbox aspect = 1.5 → aspect > 1.4 → full-body path."""
        # rw=100, rh=150 → aspect 1.5
        result = self._get_roi((50, 0, 100, 150), frame_h=480)
        self.assertIsNotNone(result)

        aspect = 150 / 100.0
        eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
        expected_h = max(8, int(150 * 0.10))
        roi_top = max(0, int(150 * eye_target_pct - expected_h / 2.0))

        self.assertEqual(result[1], roi_top)
        self.assertEqual(result[3], expected_h)


if __name__ == "__main__":
    unittest.main()
