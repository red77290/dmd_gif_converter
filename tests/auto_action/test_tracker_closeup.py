"""
Unit tests for tracker.py close-up face detection logic (v6.1.0).

Regression coverage:
  - face_priority_mode + close-up (roi_h > 40 % of frame_h): tracker must
    skip hair (top 25 %) and keep eye region (35 %), not just top 28 %.
  - face_priority_mode + normal shot: top 28 % clip is preserved.
  - Non-face_priority_mode: roi is passed through without modification.
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np


def _make_tracker(frame_h=480, face_priority=True):
    """Return a minimal TrackingEngine without real detector/ONNX loading."""
    from src.engine.config.auto_action_config import AutoActionConfig
    cfg = AutoActionConfig(
        target_width=128, target_height=32,
        detector="person",
        smart_auto_crop=True,
        smoothness=0.0,
        zoom_max=2.0,
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
    Regression (v6.1.0): in face_priority_mode with a close-up, the roi must
    be clipped to the eye region (skip 25 %, keep 35 %) instead of top 28 %.
    Previously top-28 % on a close-up face bbox == only hair/forehead.
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
        Close-up (roi_h = 460 on a 480 px frame → 96 % > 40 %): clip skips
        hair (top 25 %) and keeps eye region (next 35 %).
        Expected: ry_new = 0 + 115, rh_new = 161.
        """
        original = (50, 0, 540, 460)   # face fills the frame
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
        """Close-up must NOT use the old top-28 % formula (which = hair)."""
        original = (50, 0, 540, 460)
        result = self._get_processed_roi(original, frame_h=480)
        rx, ry, rh_clip = result[0], result[1], result[3]

        old_clip_h = max(8, int(460 * 0.28))  # old formula: 128 px (hair)
        new_clip_h = max(8, int(460 * 0.35))  # new formula: 161 px (eyes)

        # The clipped height should match the new formula
        self.assertEqual(rh_clip, new_clip_h,
                         "Close-up should use 35 % clip height, not 28 %")
        # And ry must be shifted down (hair skipped)
        self.assertGreater(ry, 0,
                           "ry must be > 0 (hair at top should be skipped)")

    def test_normal_shot_uses_top_28_percent(self):
        """
        Normal shot (roi_h = 120 on 480 px frame → 25 % < 40 %):
        clip should still use top 28 % from ry (not the eye-skip logic).
        """
        original = (100, 50, 200, 120)   # small person, not a close-up
        result = self._get_processed_roi(original, frame_h=480)

        rx, ry, rw, rh = result
        expected_h = max(8, int(120 * 0.28))   # 33 px

        self.assertEqual(ry, 50, "Normal shot: ry should not be shifted")
        self.assertEqual(rh, expected_h,
                         f"Normal shot: rh should be 28 % clip. "
                         f"Got {rh}, expected {expected_h}")

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
    """Edge cases around the 40 % close-up threshold."""

    def _get_roi_h(self, rh_original, frame_h=480):
        tracker = _make_tracker(frame_h=frame_h, face_priority=True)
        tracker.detector.detect = MagicMock(
            return_value=(50, 0, 200, rh_original))
        frame = np.zeros((frame_h, 640, 3), dtype=np.uint8)
        captured = {}

        def cap(fw, fh, roi, cfg, *a, **kw):
            captured["roi"] = roi
            from src.engine.auto_action.camera import _build_camera_rect as r
            return r(fw, fh, roi, cfg, *a, **kw)

        with patch("src.plugins.trackers.tracker._build_camera_rect",
                   side_effect=cap):
            tracker.process_frame(frame, tracker.cam_full_view, 0, 128, 32)

        return captured["roi"][3] if captured.get("roi") else None

    def test_just_above_threshold_uses_eye_clip(self):
        """roi_h = 195 on 480 px frame → 40.6 % > 40 % → eye clip."""
        rh = self._get_roi_h(195, frame_h=480)
        self.assertEqual(rh, max(8, int(195 * 0.35)))

    def test_just_below_threshold_uses_normal_clip(self):
        """roi_h = 190 on 480 px frame → 39.6 % < 40 % → normal clip."""
        rh = self._get_roi_h(190, frame_h=480)
        self.assertEqual(rh, max(8, int(190 * 0.28)))


if __name__ == "__main__":
    unittest.main()

