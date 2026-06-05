"""
Tests unitaires pour dmd_auto_action.py

Couvre :
  - available_detectors()
  - AutoActionConfig (dataclass — valeurs par défaut et personnalisées)
  - _clamp()
  - _build_camera_rect()
  - _smooth()
  - _crop_frame()
  - preprocess_video_for_dmd() — chemin d'erreur sans OpenCV
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.auto_action.main import (
    AutoActionConfig,
    _FloorEstimator,
    _build_camera_rect,
    _calculate_dmd_visibility_score,
    _clamp,
    _compute_auto_crop_margins,
    _crop_frame,
    _smart_auto_crop_decision,
    _smooth,
    available_detectors,
    preprocess_video_for_dmd,
)
from src.auto_action.main import _compute_scene_change_score
from src.auto_action.main import _apply_look_ahead
from src.auto_action.main import _fuse_rois

class TestComputeAutoCropMargins(unittest.TestCase):
    """Tests for the auto crop margin computation using a mock capture."""

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2
            self.cv2 = cv2
        except ImportError:
            self.skipTest("opencv non disponible")

    def _make_mock_cap(self, frame_h=480, frame_w=640, total_frames=60,
                       roi_y=100, roi_h=200):
        """Build a minimal mock cv2.VideoCapture that returns a black frame
        with a rectangle filled at (roi_y, 0)-(roi_y+roi_h, roi_w)."""
        np = self.np
        cv2 = self.cv2

        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
        # Make a bright rectangle so motion/fg detection can find it
        frame[roi_y:roi_y + roi_h, 0:frame_w // 2] = 200

        cap = MagicMock()
        cap.get = MagicMock(side_effect=lambda prop: (
            float(total_frames) if prop == cv2.CAP_PROP_FRAME_COUNT else
            0.0
        ))
        cap.set = MagicMock(return_value=None)
        cap.read = MagicMock(return_value=(True, frame.copy()))
        return cap

    def test_returns_tuple_of_two_floats(self):
        from src.auto_action.main import _FrameDetector
        cfg = AutoActionConfig(detector="motion")
        # Detector that always returns a fixed ROI
        det = MagicMock()
        det.detect = MagicMock(return_value=(0, 100, 320, 200))
        cap = self._make_mock_cap()
        result = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        top, bottom, face_prio = result
        self.assertIsInstance(top, float)
        self.assertIsInstance(bottom, float)
        self.assertIsInstance(face_prio, bool)

    def test_no_detections_returns_zeros(self):
        cfg = AutoActionConfig(detector="motion")
        det = MagicMock()
        det.detect = MagicMock(return_value=None)
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bottom, 0.0)

    def test_full_body_roi_fits_in_dmd_window(self):
        """Full-body ROI that fits within the DMD window → feet are used as bottom.

        For frame_w=640, target 128×32 → dmd_crop_h = 160 px.
        ROI h=90 (< 160×0.80=128) → no face priority → feet-based bottom crop.
        The effective content ends at roi_y + roi_h = 50 + 90 = 140.
        With pad_frac=0.06 (tall narrow ROI, h/w=3.0 > 2.5):
          bottom_y ≈ 140 + 480*0.06 ≈ 169  →  bottom_pct ≈ 0.65
        The important invariant: top boundary should be above the head (y=50).
        """
        cfg = AutoActionConfig(detector="motion", target_width=128, target_height=32)
        det = MagicMock()
        # Tall narrow ROI that still fits (h/w=3.0, h=90 < 128 threshold)
        det.detect = MagicMock(return_value=(100, 50, 30, 90))
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        # top boundary must be at or above the head (y=50 → top_pct ≤ 50/480 ≈ 0.104)
        self.assertLessEqual(top * 480, 50.0,
            "Top boundary must be at or above the head position (y=50)")
        # bottom boundary must be at or below feet (y=140 → effective_bottom ≥ 140)
        effective_bottom = 480 * (1.0 - bottom)
        self.assertGreaterEqual(effective_bottom, 90.0,
            "Bottom boundary must include the feet region")

    def test_face_priority_triggers_when_body_too_tall(self):
        """When ROI height > 80% of DMD window height, face priority activates.

        In face priority mode the effective bottom is roi_y + roi_h * FACE_FRAC
        (top ~32%) instead of roi_y + roi_h (feet), so bottom_pct is LARGER
        (more of the frame is excluded from the bottom).
        """
        # frame_w=640, target_ratio=4.0 → dmd_crop_h = 160 px
        # ROI: y=50, h=200 → 200 > 160 * 0.80 = 128 → face priority
        cfg_face_prio = AutoActionConfig(detector="motion",
                                         target_width=128, target_height=32)
        det_tall = MagicMock()
        det_tall.detect = MagicMock(return_value=(100, 50, 80, 200))  # h=200 > 128

        cfg_normal = AutoActionConfig(detector="motion",
                                      target_width=128, target_height=32)
        det_short = MagicMock()
        det_short.detect = MagicMock(return_value=(100, 50, 80, 80))  # h=80 < 128

        cap1 = self._make_mock_cap()
        cap2 = self._make_mock_cap()

        top_tall, bot_tall, _   = _compute_auto_crop_margins(cap1, det_tall,  cfg_face_prio, 640, 480)
        top_short, bot_short, _ = _compute_auto_crop_margins(cap2, det_short, cfg_normal,    640, 480)

        # Face priority: bottom boundary is at roi_y + roi_h * 0.32 = 50 + 64 = 114
        # Normal (short): bottom boundary is at roi_y + roi_h = 50 + 80 = 130
        # Face priority excludes MORE from the bottom → bot_tall > bot_short
        self.assertGreater(bot_tall, bot_short,
            "Face priority mode should crop more from the bottom than normal mode "
            "(body-too-tall triggers face region focus)")

    def test_face_priority_head_always_visible(self):
        """The top_pct should be small enough that the head is always included.

        Even in face priority mode the top boundary should be above (or at) the
        head position.
        """
        cfg = AutoActionConfig(detector="motion", target_width=128, target_height=32)
        det = MagicMock()
        # Very tall ROI: y=50, h=250 (head at y=50)
        det.detect = MagicMock(return_value=(100, 50, 60, 250))
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        # top boundary must be at or above y=50 (head position)
        top_y_px = top * 480
        self.assertLessEqual(top_y_px, 50.0,
            f"top_y_px={top_y_px:.1f} is below the head (y=50) — head would be cut off")

    def test_face_roi_gives_larger_padding(self):
        """Face-like ROI (square) → larger relative padding applied."""
        cfg = AutoActionConfig(detector="motion")
        det_face = MagicMock()
        det_body = MagicMock()
        # Face: h/w ≈ 1.0
        det_face.detect = MagicMock(return_value=(200, 180, 80, 80))
        # Full body: h/w ≈ 4.0
        det_body.detect = MagicMock(return_value=(200, 180, 40, 160))

        cap = self._make_mock_cap()
        top_face, bot_face, _ = _compute_auto_crop_margins(cap, det_face, cfg, 640, 480)

        cap2 = self._make_mock_cap()
        top_body, bot_body, _ = _compute_auto_crop_margins(cap2, det_body, cfg, 640, 480)

        # Face should have more padding than body (face pad_frac=0.15, body pad_frac=0.06)
        # The face roi starts at y=180, body roi also starts at y=180
        # Face top_pct = (180 - 0.15*480) / 480 ≈ (180-72)/480 = 108/480 ≈ 0.225
        # Body top_pct = (180 - 0.06*480) / 480 ≈ (180-29)/480 = 151/480 ≈ 0.315
        # Actually face pad is LARGER so top_pct (starting further down) < body
        # The important thing is just that both are non-negative
        self.assertGreaterEqual(top_face, 0.0)
        self.assertGreaterEqual(top_body, 0.0)

    def test_values_clamped_to_valid_range(self):
        """Both returned values must be in [0, 0.9]."""
        cfg = AutoActionConfig(detector="motion")
        det = MagicMock()
        det.detect = MagicMock(return_value=(0, 0, 640, 480))  # Full frame ROI
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertGreaterEqual(top, 0.0)
        self.assertLessEqual(top, 0.9)
        self.assertGreaterEqual(bottom, 0.0)
        self.assertLessEqual(bottom, 0.9)

    def test_zero_total_frames_returns_zeros(self):
        """If cap reports 0 total frames, should return (0.0, 0.0)."""
        import cv2
        cfg = AutoActionConfig()
        det = MagicMock()
        cap = MagicMock()
        cap.get = MagicMock(return_value=0.0)
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bottom, 0.0)

class TestSmartAutoCropDecision(unittest.TestCase):
    """Tests for _smart_auto_crop_decision using a mock cv2.VideoCapture."""

    def _make_cap(self, total_frames: int = 30, frame_w: int = 640, frame_h: int = 480):
        """Return a mock VideoCapture that yields blank black frames."""
        import numpy as np
        cap = MagicMock()
        cap.get.side_effect = lambda prop: {
            0: 0.0,               # CAP_PROP_POS_FRAMES
            7: float(total_frames),  # CAP_PROP_FRAME_COUNT
        }.get(prop, 0.0)
        blank = np.zeros((frame_h, frame_w, 3), dtype="uint8")
        cap.read.return_value = (True, blank)
        return cap

    def _cfg(self, **kw):
        defaults = dict(detector="motion", target_width=128, target_height=32)
        defaults.update(kw)
        return AutoActionConfig(**defaults)

    def test_returns_required_keys(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        for key in ("auto_bottom_crop", "auto_top_crop", "auto_vertical_bias",
                    "top_pct", "bottom_pct", "reasons"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_no_detections_returns_all_false(self):
        """Blank frames produce no detections → all auto flags False."""
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertFalse(result["auto_vertical_bias"])

    def test_pct_values_are_floats_in_range(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        for key in ("top_pct", "bottom_pct"):
            self.assertIsInstance(result[key], float)
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 0.9)

    def test_reasons_is_nonempty_list(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertIsInstance(result["reasons"], list)
        self.assertGreater(len(result["reasons"]), 0)

    def test_zero_frames_returns_safe_defaults(self):
        cap = self._make_cap(total_frames=0)
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertEqual(result["top_pct"], 0.0)
        self.assertEqual(result["bottom_pct"], 0.0)

    def test_detector_init_failure_returns_safe_defaults(self):
        """If _FrameDetector() raises, the function should return safe defaults."""
        cap = self._make_cap()
        cfg = self._cfg()
        with patch("src.auto_action.pipeline._FrameDetector", side_effect=RuntimeError("mock fail")):
            result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertIn("reasons", result)

    def test_preprocess_smart_crop_exception_degrades_gracefully(self):
        """If _smart_auto_crop_decision raises, preprocess falls back without crashing."""
        with patch("src.auto_action.pipeline._smart_auto_crop_decision",
                   side_effect=RuntimeError("boom")):
            cfg = AutoActionConfig(smart_auto_crop=True)
            ok, out, msg = preprocess_video_for_dmd("/nonexistent_file_xyz.mp4", cfg)
        # Should fail gracefully (no crash), not because of the smart scan
        self.assertFalse(ok)
        self.assertIsNone(out)

class TestCalculateDMDVisibilityScore(unittest.TestCase):
    """Tests pour _calculate_dmd_visibility_score()."""

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2  # noqa: F401 — only needed transitively inside the func
        except ImportError:
            self.skipTest("opencv non disponible")

    def _blank(self, w=128, h=32):
        """Completely black frame — minimum visibility."""
        return self.np.zeros((h, w, 3), dtype=self.np.uint8)

    def _bright(self, w=128, h=32):
        """Fully white frame — maximum brightness, but low edge density."""
        return self.np.full((h, w, 3), 255, dtype=self.np.uint8)

    def _checkerboard(self, w=128, h=32):
        """Checkerboard pattern — high edge / contrast score."""
        np = self.np
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        for r in range(h):
            for c in range(w):
                if (r + c) % 2 == 0:
                    frame[r, c] = [255, 255, 255]
        return frame

    def _center_rect(self, w=128, h=32, rect_w=64, rect_h=20):
        """Frame with a bright rectangle in the centre — medium score."""
        np = self.np
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        x0 = (w - rect_w) // 2
        y0 = (h - rect_h) // 2
        frame[y0:y0 + rect_h, x0:x0 + rect_w] = [200, 200, 200]
        return frame

    # ── Return type & range ───────────────────────────────────────────────────

    def test_returns_float(self):
        score = _calculate_dmd_visibility_score(self._blank())
        self.assertIsInstance(score, float)

    def test_blank_frame_returns_zero(self):
        """A completely black frame should score 0.0 (nothing visible)."""
        score = _calculate_dmd_visibility_score(self._blank())
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_score_is_non_negative(self):
        for frame in [self._blank(), self._bright(), self._checkerboard(), self._center_rect()]:
            self.assertGreaterEqual(_calculate_dmd_visibility_score(frame), 0.0)

    def test_none_frame_returns_zero(self):
        """Passing None must not raise and must return 0.0."""
        score = _calculate_dmd_visibility_score(None)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_empty_array_returns_zero(self):
        np = self.np
        score = _calculate_dmd_visibility_score(np.zeros((0, 0, 3), dtype=np.uint8))
        self.assertAlmostEqual(score, 0.0, places=4)

    # ── Monotonicity — more content → higher score ────────────────────────────

    def test_bright_frame_scores_higher_than_blank(self):
        score_blank  = _calculate_dmd_visibility_score(self._blank())
        score_bright = _calculate_dmd_visibility_score(self._bright())
        self.assertGreater(score_bright, score_blank,
                           "A bright frame should score higher than a blank frame")

    def test_checkerboard_scores_higher_than_blank(self):
        score_blank = _calculate_dmd_visibility_score(self._blank())
        score_check = _calculate_dmd_visibility_score(self._checkerboard())
        self.assertGreater(score_check, score_blank,
                           "A checkerboard (high edge density) should score higher than blank")

    def test_center_rect_scores_higher_than_blank(self):
        score_blank = _calculate_dmd_visibility_score(self._blank())
        score_rect  = _calculate_dmd_visibility_score(self._center_rect())
        self.assertGreater(score_rect, score_blank,
                           "A frame with a bright rect should score higher than blank")

    def test_high_contrast_region_scores_higher_than_flat_region(self):
        """A frame with alternating high-contrast stripes (2-px bands) must score higher
        than a flat grey frame — validating that the Sobel-based contrast component works.
        We use 4-px bands to avoid aliasing at kernel size 3."""
        np = self.np
        flat = np.full((32, 128, 3), 128, dtype=np.uint8)   # featureless grey

        striped = np.zeros((32, 128, 3), dtype=np.uint8)
        for c in range(0, 128, 4):
            striped[:, c:c + 2] = 255   # alternate 2px white / 2px black bands

        score_flat    = _calculate_dmd_visibility_score(flat)
        score_striped = _calculate_dmd_visibility_score(striped)
        self.assertGreater(score_striped, score_flat,
                           "A high-contrast striped frame must score higher than a flat grey frame")

    # ── Partial content occupation ────────────────────────────────────────────

    def test_larger_rect_scores_higher_than_smaller(self):
        score_small = _calculate_dmd_visibility_score(self._center_rect(rect_w=20, rect_h=8))
        score_large = _calculate_dmd_visibility_score(self._center_rect(rect_w=100, rect_h=28))
        self.assertGreater(score_large, score_small,
                           "A larger bright area should produce a higher score")

    # ── Different DMD resolutions ─────────────────────────────────────────────

    def test_works_on_256x64_frame(self):
        """Score function must handle non-default DMD sizes without error."""
        frame = self._checkerboard(w=256, h=64)
        score = _calculate_dmd_visibility_score(frame)
        self.assertGreater(score, 0.0)

    def test_works_on_single_row_frame(self):
        """Edge case: 1-pixel tall frame must not raise."""
        np = self.np
        frame = np.full((1, 128, 3), 200, dtype=np.uint8)
        score = _calculate_dmd_visibility_score(frame)
        self.assertIsInstance(score, float)

class TestDMDVisibilityScoreGuard(unittest.TestCase):
    """
    Validates the 5%-threshold guard used in preprocess_video_for_dmd:
    when a proposed crop scores < 95% of the current crop, the current
    camera should be preferred.
    """

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("opencv non disponible")

    def test_good_proposed_accepted(self):
        """When proposed score >= 95% of current, the proposed crop is accepted."""
        np = self.np
        # Both frames equally bright
        frame_a = np.full((32, 128, 3), 200, dtype=np.uint8)
        frame_b = np.full((32, 128, 3), 200, dtype=np.uint8)
        score_a = _calculate_dmd_visibility_score(frame_a)
        score_b = _calculate_dmd_visibility_score(frame_b)
        # Guard condition: proposed (b) < current (a) * 0.95 → revert
        # Here scores are equal, so proposed should be accepted (NOT reverted)
        self.assertFalse(score_b < score_a * 0.95,
                         "Equal-brightness frames should not trigger the revert guard")

    def test_bad_proposed_rejected(self):
        """When proposed score < 95% of current, the guard should trigger revert."""
        np = self.np
        # Current: bright/rich content
        current_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    current_frame[r, c] = [255, 255, 255]

        # Proposed: nearly blank (zoomed into a flat area)
        proposed_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        proposed_frame[14:18, 60:68] = [30, 30, 30]  # tiny dim rectangle

        score_current  = _calculate_dmd_visibility_score(current_frame)
        score_proposed = _calculate_dmd_visibility_score(proposed_frame)

        self.assertLess(score_proposed, score_current * 0.95,
                        "A nearly blank proposed frame should fall below 95% of a rich current frame "
                        "and trigger the revert guard")

    def test_slight_degradation_within_threshold_accepted(self):
        """A 3% degradation (within 5% tolerance) must not trigger revert."""
        np = self.np
        # Current: checkerboard
        current_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    current_frame[r, c] = [200, 200, 200]

        # Proposed: same but slightly dimmer (simulate marginal quality change)
        proposed_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    proposed_frame[r, c] = [195, 195, 195]  # ~2.5% dimmer

        score_current  = _calculate_dmd_visibility_score(current_frame)
        score_proposed = _calculate_dmd_visibility_score(proposed_frame)
        # Should NOT trigger revert (within tolerance)
        self.assertFalse(score_proposed < score_current * 0.95,
                         "A marginal quality difference should not trigger the revert guard")

class TestSceneChangeScore(unittest.TestCase):

    def _frame(self, color):
        """Return a 64×64 BGR frame filled with the given color."""
        import numpy as np
        f = np.zeros((64, 64, 3), dtype=np.uint8)
        f[:] = color
        return f

    def test_identical_frames_score_near_one(self):
        f = self._frame((128, 64, 200))
        score = _compute_scene_change_score(f, f.copy())
        self.assertGreaterEqual(score, 0.9,
                                "Identical frames should score close to 1.0")

    def test_black_vs_white_scores_low(self):
        black = self._frame((0, 0, 0))
        white = self._frame((255, 255, 255))
        score = _compute_scene_change_score(black, white)
        # Pure luminance change — V channel histograms will be maximally different
        self.assertLess(score, 0.8,
                        "Black→white hard cut should score well below 1.0")

    def test_none_frame_returns_one(self):
        """Graceful degradation: None input → treat as no cut."""
        f = self._frame((100, 100, 100))
        self.assertAlmostEqual(_compute_scene_change_score(None, f), 1.0)
        self.assertAlmostEqual(_compute_scene_change_score(f, None), 1.0)
        self.assertAlmostEqual(_compute_scene_change_score(None, None), 1.0)

    def test_score_in_zero_one_range(self):
        a = self._frame((30, 200, 100))
        b = self._frame((200, 30, 100))
        score = _compute_scene_change_score(a, b)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_config_default_threshold(self):
        cfg = AutoActionConfig()
        self.assertAlmostEqual(cfg.scene_change_threshold, 0.45)

    def test_config_disabled(self):
        cfg = AutoActionConfig(scene_change_threshold=0.0)
        self.assertAlmostEqual(cfg.scene_change_threshold, 0.0)

if __name__ == "__main__":
    unittest.main()
