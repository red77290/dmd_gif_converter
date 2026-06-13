"""
Unit tests for camera.py — _build_camera_rect(), _smooth(), _apply_look_ahead().

Regression coverage for v6.1.0 bug-fixes:
  - face_priority_mode close-up: camera must centre on eye region, not hair.
  - face_priority_mode full body: camera still frames head at top (unchanged).
  - _smooth(): blends prev→curr with the given smoothness coefficient.
  - _apply_look_ahead(): offsets cx/cy in the direction of scroll velocity.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.engine.auto_action.camera import _build_camera_rect, _smooth, _apply_look_ahead
from src.engine.config.auto_action_config import AutoActionConfig


def _default_cfg(**kwargs) -> AutoActionConfig:
    base = dict(
        target_width=128, target_height=32,
        padding=0.1, strength=1.0, zoom_max=2.0,
        smoothness=0.0,
        auto_vertical_bias=False, platformer_mode=False,
        look_ahead_enabled=False, look_ahead_factor=0.0,
    )
    base.update(kwargs)
    return AutoActionConfig(**base)


FRAME_W, FRAME_H = 640, 480


class TestBuildCameraRectNoRoi(unittest.TestCase):
    """roi=None → full-frame centred view."""

    def test_no_roi_returns_full_frame(self):
        cfg = _default_cfg()
        cx, cy, cw, ch = _build_camera_rect(FRAME_W, FRAME_H, None, cfg)
        self.assertAlmostEqual(cx, FRAME_W / 2, places=1)
        self.assertAlmostEqual(cy, FRAME_H / 2, places=1)
        self.assertAlmostEqual(cw, FRAME_W, places=1)

    def test_no_roi_bias_up_pushes_cy_toward_top(self):
        cfg = _default_cfg(auto_vertical_bias=True)
        _, cy, _, ch = _build_camera_rect(FRAME_W, FRAME_H, None, cfg,
                                          frame_top=0.0)
        cam_top = cy - ch / 2
        # With auto_vertical_bias + no floor → bias=-1 → camera pushed up
        self.assertLessEqual(cam_top, 0.1)


class TestBuildCameraRectFacePriorityCloseUp(unittest.TestCase):
    """
    Regression tests for v6.1.0 fix:
    In face_priority_mode the camera must centre on y + h/2 (roi centre)
    instead of the old formula ideal_top + crop_h/2 which pushed cy far
    below the face in close-up shots.
    """

    def _run(self, roi, face_priority=True, frame_h=FRAME_H):
        cfg = _default_cfg()
        cx, cy, cw, ch = _build_camera_rect(
            FRAME_W, frame_h, roi, cfg,
            face_priority_mode=face_priority,
        )
        return cx, cy, cw, ch

    def test_face_priority_closeup_camera_includes_eye_region(self):
        """
        Close-up: tracker clips roi to eye region (after hair skip).
        Camera cy must be near y + h/2 of the clipped roi.
        Old buggy formula (ideal_top + crop_h/2) would place cy ~300 px
        below the roi when crop_h ≈ frame_h.
        """
        # Simulates tracker output for a close-up after hair-skip clip:
        # original body bbox ≈ (50, 0, 540, 450);
        # after close-up clip:  skip 25 % (112 px), keep 35 % (157 px)
        roi = (50, 112, 540, 157)
        cx, cy, cw, ch = self._run(roi)

        roi_centre = roi[1] + roi[3] / 2.0   # 112 + 78.5 = 190.5
        cam_top    = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Camera centre must be within one roi-height of the roi centre
        self.assertAlmostEqual(cy, roi_centre, delta=roi[3] * 0.6,
                               msg="cy should be near the roi centre (eye level)")
        # Camera window must overlap the roi
        self.assertLess(cam_top, roi[1] + roi[3],
                        "Camera top is below the entire roi — face cropped out")
        self.assertGreater(cam_bottom, roi[1],
                           "Camera bottom is above the roi — face cropped out")

    def test_old_formula_would_place_cy_below_face(self):
        """
        Documents the v6.0 regression: old formula placed cy ≈ ideal_top +
        crop_h/2 ≈ 112 + 240 = 352, far below the roi bottom (112+157=269).
        The new formula should be significantly closer to the roi centre.
        """
        roi = (50, 112, 540, 157)
        cx, cy, cw, ch = self._run(roi)

        roi_centre = roi[1] + roi[3] / 2.0
        old_cy_approx = roi[1] + ch / 2.0     # ideal_top ≈ roi[1], crop_h ≈ ch

        new_dist = abs(cy - roi_centre)
        old_dist = abs(old_cy_approx - roi_centre)

        if old_dist > roi[3]:
            # Old formula was clearly worse — new one must be better
            self.assertLess(new_dist, old_dist,
                            "New formula must place cy closer to eye level than old formula")

    def test_face_priority_normal_shot_includes_head(self):
        """
        Normal non-close-up in face_priority_mode: roi is the head clip
        (top 28 % of body).  Camera must still include the head.
        """
        roi = (100, 30, 200, 112)   # head region of a normal-size person
        cx, cy, cw, ch = self._run(roi, frame_h=480)

        cam_top    = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0
        self.assertLess(cam_top, roi[1] + roi[3],
                        "Camera should not be entirely below the head roi")
        self.assertGreater(cam_bottom, roi[1],
                           "Camera should not be entirely above the head roi")

    def test_face_priority_false_centres_on_roi(self):
        """Without face_priority_mode the else-branch applies bias (default=0)."""
        roi = (100, 50, 200, 100)
        cx, cy, cw, ch = self._run(roi, face_priority=False)
        roi_cy = roi[1] + roi[3] / 2.0
        self.assertAlmostEqual(cy, roi_cy, delta=roi[3],
                               msg="Without face_priority cy should be near roi centre")


class TestBuildCameraRectClamping(unittest.TestCase):
    """cy is always clamped to [cy_min, cy_max]."""

    def test_cy_never_below_cy_min(self):
        roi = (10, 0, 100, 5)
        cfg = _default_cfg()
        _, cy, _, ch = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg)
        self.assertGreaterEqual(cy, ch / 2.0)

    def test_cy_never_above_cy_max(self):
        roi = (10, FRAME_H - 5, 100, 5)
        cfg = _default_cfg()
        _, cy, _, ch = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg)
        self.assertLessEqual(cy, FRAME_H - ch / 2.0)

    def test_cx_clamped_horizontally(self):
        roi = (0, 100, FRAME_W, 100)
        cfg = _default_cfg()
        cx, _, cw, _ = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg)
        self.assertGreaterEqual(cx, cw / 2.0)
        self.assertLessEqual(cx, FRAME_W - cw / 2.0)


class TestBuildCameraRectZoomMax(unittest.TestCase):
    """zoom_max limits how tightly the crop frames the subject."""

    def test_zoom_max_1_no_zoom(self):
        cfg = _default_cfg(zoom_max=1.0, strength=1.0)
        roi = (100, 100, 50, 50)
        _, _, cw, _ = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg)
        self.assertAlmostEqual(cw, FRAME_W, delta=2.0)

    def test_zoom_max_2_allows_tighter_crop(self):
        cfg_nozoom = _default_cfg(zoom_max=1.0, strength=1.0)
        cfg_zoom   = _default_cfg(zoom_max=2.0, strength=1.0)
        roi = (200, 100, 100, 100)
        _, _, cw_nz, _ = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg_nozoom)
        _, _, cw_z,  _ = _build_camera_rect(FRAME_W, FRAME_H, roi, cfg_zoom)
        self.assertLessEqual(cw_z, cw_nz + 1.0)


class TestSmooth(unittest.TestCase):
    """_smooth() blends prev → curr with smoothness coefficient."""

    def test_zero_smoothness_returns_curr(self):
        result = _smooth((10, 20, 30, 40), (1, 2, 3, 4), 0.0)
        self.assertEqual(result, (1, 2, 3, 4))

    def test_full_smoothness_nearly_prev(self):
        result = _smooth((10, 20, 30, 40), (1, 2, 3, 4), 0.98)
        for r, p in zip(result, (10, 20, 30, 40)):
            self.assertAlmostEqual(r, p, delta=1.0)  # 0.98*p + 0.02*c ≈ p ±1

    def test_half_smoothness_midpoint(self):
        result = _smooth((0.0, 0.0, 0.0, 0.0), (10.0, 10.0, 10.0, 10.0), 0.5)
        for v in result:
            self.assertAlmostEqual(v, 5.0, places=5)

    def test_none_prev_returns_curr(self):
        result = _smooth(None, (1, 2, 3, 4), 0.8)
        self.assertEqual(result, (1, 2, 3, 4))

    def test_smoothness_clamped_at_0_98(self):
        result_098 = _smooth((0.0,), (10.0,), 0.98)
        result_100 = _smooth((0.0,), (10.0,), 1.00)
        self.assertAlmostEqual(result_098[0], result_100[0], places=3)


class TestApplyLookAhead(unittest.TestCase):
    """_apply_look_ahead() shifts cx/cy in the direction of scroll velocity."""

    def test_no_velocity_no_change(self):
        cam = (320.0, 240.0, 640.0, 480.0)
        result = _apply_look_ahead(cam, 0.0, 0.0, 640, 480, 0.5)
        self.assertEqual(result, cam)

    def test_positive_vx_shifts_cx_right(self):
        cam = (320.0, 240.0, 400.0, 300.0)
        result = _apply_look_ahead(cam, 5.0, 0.0, 640, 480, 0.5)
        self.assertGreater(result[0], cam[0])

    def test_negative_vy_shifts_cy_up(self):
        cam = (320.0, 240.0, 400.0, 300.0)
        result = _apply_look_ahead(cam, 0.0, -5.0, 640, 480, 0.5)
        self.assertLess(result[1], cam[1])

    def test_offset_capped_at_25_percent_crop(self):
        cam = (320.0, 240.0, 400.0, 300.0)
        result = _apply_look_ahead(cam, 1000.0, 0.0, 640, 480, 1.0)
        max_offset = cam[2] * 0.25
        self.assertLessEqual(abs(result[0] - cam[0]), max_offset + 1.0)


if __name__ == "__main__":
    unittest.main()

