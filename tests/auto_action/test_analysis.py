"""
Regression tests for src/engine/analysis/analysis.py

Covers:
  - _is_dark_frame()         : dark frame detection
  - _FACE_PRIORITY_H_RATIO   : shared constant (regression TALL_FACTOR 0.80→1.30)
  - _compute_auto_crop_margins with dark scenes + short videos
  - _smart_auto_crop_decision : face_priority synced with _FACE_PRIORITY_H_RATIO
  - detect_person() used in scan (not detect_motion avec cap.set)
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.analysis.analysis import (
    _clamp,
    _is_dark_frame,
    _FACE_PRIORITY_H_RATIO,
    _compute_auto_crop_margins,
    _smart_auto_crop_decision,
    _FloorEstimator,
)
from src.plugins.scorers.dmd_scorers import DMDVisibilityScore, SceneChangeScore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_frame(brightness: int = 128, h: int = 100, w: int = 200) -> np.ndarray:
    """Return a BGR frame filled with a uniform brightness value."""
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def _make_cap(total_frames: int = 60, fps: float = 30.0, frame_brightness: int = 128):
    """Return a mock cv2.VideoCapture that yields bright/dark frames."""
    cap = MagicMock()
    cap.get.side_effect = lambda prop: {
        0: 0.0,          # CAP_PROP_POS_FRAMES
        5: fps,          # CAP_PROP_FPS
        7: float(total_frames),  # CAP_PROP_FRAME_COUNT
    }.get(prop, 0.0)

    frame = _make_frame(brightness=frame_brightness)
    cap.read.return_value = (True, frame)
    return cap


def _make_cfg(target_w: int = 128, target_h: int = 32,
              detector: str = "person",
              smart_auto_crop: bool = True,
              auto_strength: bool = False,
              auto_smoothness: bool = False,
              auto_pillarbox_crop: bool = False):
    cfg = MagicMock()
    cfg.target_width = target_w
    cfg.target_height = target_h
    cfg.detector = detector
    cfg.smart_auto_crop = smart_auto_crop
    cfg.auto_strength = auto_strength
    cfg.auto_smoothness = auto_smoothness
    cfg.auto_pillarbox_crop = auto_pillarbox_crop
    return cfg


# ── _clamp ────────────────────────────────────────────────────────────────────

class TestClamp(unittest.TestCase):
    def test_within_range(self):
        self.assertAlmostEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_below_lo(self):
        self.assertAlmostEqual(_clamp(-0.1, 0.0, 1.0), 0.0)

    def test_above_hi(self):
        self.assertAlmostEqual(_clamp(1.5, 0.0, 1.0), 1.0)


# ── _is_dark_frame ────────────────────────────────────────────────────────────

class TestIsDarkFrame(unittest.TestCase):
    """Régression: les frames sombres doivent être ignorées dans le scan."""

    def test_bright_frame_not_dark(self):
        self.assertFalse(_is_dark_frame(_make_frame(128)))

    def test_very_dark_frame_is_dark(self):
        self.assertTrue(_is_dark_frame(_make_frame(10)))

    def test_threshold_boundary_below(self):
        # brightness=39 → mean BGR = 39 → dark
        self.assertTrue(_is_dark_frame(_make_frame(39), threshold=40.0))

    def test_threshold_boundary_above(self):
        # brightness=41 → mean BGR = 41 → not dark
        self.assertFalse(_is_dark_frame(_make_frame(41), threshold=40.0))

    def test_custom_threshold(self):
        self.assertTrue(_is_dark_frame(_make_frame(60), threshold=80.0))
        self.assertFalse(_is_dark_frame(_make_frame(100), threshold=80.0))


# ── _FACE_PRIORITY_H_RATIO ────────────────────────────────────────────────────

class TestFacePriorityRatio(unittest.TestCase):
    """
    Régression directe: TALL_FACTOR a été accidentellement augmenté à 1.30
    dans le commit 2921a4d, ce qui empêchait face_priority de se déclencher
    pour les gros plans normaux. La valeur correcte est 0.80.
    """

    def test_ratio_is_080(self):
        self.assertAlmostEqual(
            _FACE_PRIORITY_H_RATIO, 0.80,
            msg="TALL_FACTOR/DMD_CROP_H_FACTOR doit être 0.80 (régression 2921a4d)"
        )

    def test_ratio_below_one(self):
        """La valeur doit être < 1.0 pour déclencher sur des gros plans normaux."""
        self.assertLess(
            _FACE_PRIORITY_H_RATIO, 1.0,
            msg="Un TALL_FACTOR >= 1.0 empêcherait la détection de gros plans normaux"
        )


# ── _FloorEstimator ───────────────────────────────────────────────────────────

class TestFloorEstimator(unittest.TestCase):
    def test_first_detection_snaps(self):
        fe = _FloorEstimator(frame_h=100)
        result = fe.update(80.0)
        self.assertAlmostEqual(result, 80.0)

    def test_no_detection_defaults_to_80pct(self):
        fe = _FloorEstimator(frame_h=100)
        result = fe.update(None)
        self.assertAlmostEqual(result, 80.0)

    def test_attack_is_faster_than_release(self):
        fe = _FloorEstimator(frame_h=100)
        fe.update(50.0)   # init
        fe.update(90.0)   # attack (floor goes down = attack)
        after_attack = fe.floor_y

        fe2 = _FloorEstimator(frame_h=100)
        fe2.update(90.0)  # init
        fe2.update(50.0)  # release (floor goes up = release)
        after_release = abs(fe2.floor_y - 90.0)

        # attack delta should be larger than release delta
        self.assertGreater(abs(after_attack - 50.0), after_release)


# ── _compute_auto_crop_margins ────────────────────────────────────────────────

class TestComputeAutoCropMargins(unittest.TestCase):
    """Vérifie que le scan ignore les frames sombres et utilise detect_person."""

    def _make_detector(self, roi=(10, 10, 80, 200)):
        """Detector qui retourne toujours le même ROI."""
        det = MagicMock()
        det.detect_person.return_value = roi
        det.detect.return_value = roi
        return det

    def test_no_detections_returns_zeros(self):
        cap = _make_cap(total_frames=60, fps=30.0)
        cfg = _make_cfg()
        det = MagicMock()
        det.detect_person.return_value = None
        det.detect.return_value = None

        top, bot, fp = _compute_auto_crop_margins(cap, det, cfg, 400, 1080)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bot, 0.0)
        self.assertFalse(fp)

    def test_dark_frames_are_skipped(self):
        """Régression: frames sombres ne doivent pas être soumises au détecteur."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=10)  # dark!
        cfg = _make_cfg()
        det = self._make_detector()

        top, bot, fp = _compute_auto_crop_margins(cap, det, cfg, 400, 1080)
        # Toutes les frames sont sombres → aucune ne passe → pas de ROI
        det.detect_person.assert_not_called()
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bot, 0.0)

    def test_bright_frames_call_detect_person_not_detect(self):
        """Régression: le scan doit utiliser detect_person (pas detect avec motion fallback)."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()
        det = self._make_detector(roi=(10, 50, 80, 500))

        _compute_auto_crop_margins(cap, det, cfg, 400, 1080)

        self.assertTrue(det.detect_person.called,
                        "detect_person doit être appelé dans le scan (pas detect)")

    def test_face_priority_triggers_with_tall_roi(self):
        """
        Régression: avec TALL_FACTOR = 1.30 (bug), face_priority ne se déclenchait jamais.
        Avec TALL_FACTOR = 0.80 (fix), un ROI de 420px > 0.80 * (400/4=100) → face_priority.

        frame_w=400, target=128x32 → dmd_crop_h = 400/4 = 100px
        ROI height = 420px > 100 * 0.80 = 80px → face_priority doit se déclencher
        """
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()
        # ROI très tall: ry=10, rh=420 → rh > dmd_crop_h * 0.80
        det = self._make_detector(roi=(10, 10, 80, 420))

        _, _, fp = _compute_auto_crop_margins(cap, det, cfg, frame_w=400, frame_h=1080)
        self.assertTrue(fp, "face_priority doit se déclencher pour un ROI tall (régression TALL_FACTOR)")

    def test_face_priority_does_not_trigger_with_small_roi(self):
        """Un ROI petit ne doit pas déclencher face_priority."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()
        # ROI petit: rh=20px, dmd_crop_h=100px → rh < 80px → pas face_priority
        det = self._make_detector(roi=(10, 10, 80, 20))

        _, _, fp = _compute_auto_crop_margins(cap, det, cfg, frame_w=400, frame_h=1080)
        self.assertFalse(fp, "Un ROI petit ne doit pas déclencher face_priority")


# ── _smart_auto_crop_decision ─────────────────────────────────────────────────

class TestSmartAutoCropDecision(unittest.TestCase):

    def _make_cap_with_roi(self, roi, total_frames=90, fps=30.0, brightness=128):
        cap = _make_cap(total_frames=total_frames, fps=fps, frame_brightness=brightness)
        return cap

    # Patch target: _FrameDetector is imported lazily inside _smart_auto_crop_decision
    _DETECTOR_PATCH = "src.plugins.detectors.detector._FrameDetector"

    def test_disabled_config_returns_empty(self):
        cap = _make_cap()
        cfg = _make_cfg(smart_auto_crop=False, auto_strength=False,
                        auto_smoothness=False, auto_pillarbox_crop=False)

        with patch(self._DETECTOR_PATCH):
            result = _smart_auto_crop_decision(cap, cfg, 400, 1080)

        self.assertFalse(result["face_priority"])
        self.assertFalse(result["auto_bottom_crop"])

    def test_no_detections_all_dark(self):
        """Toutes les frames sombres → aucune détection → face_priority False."""
        cap = _make_cap(total_frames=90, fps=30.0, frame_brightness=5)  # très sombre
        cfg = _make_cfg()

        mock_det = MagicMock()
        mock_det.detect_person.return_value = None
        mock_det.detect.return_value = None

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            result = _smart_auto_crop_decision(cap, cfg, 400, 1080)

        self.assertFalse(result["face_priority"])
        self.assertIn("no detections", result["reasons"][0])

    def test_face_priority_with_tall_roi_regression(self):
        """
        Régression 2921a4d: TALL_FACTOR 1.30 empêchait face_priority sur gros plans.
        frame_w=400 → dmd_crop_h=100 → rh=420 → tall_ratio=4.2 > 0.80 → face_priority.
        """
        cap = _make_cap(total_frames=90, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()

        mock_det = MagicMock()
        # ROI tall: ry=0, rh=420 (>> 0.80 * dmd_crop_h=80)
        rois = [(10 + (i * 17 % 200), 0, 80, 420) for i in range(90)]
        mock_det.detect_person.side_effect = rois
        mock_det.detect.side_effect = rois

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            result = _smart_auto_crop_decision(cap, cfg, frame_w=400, frame_h=1080)

        self.assertTrue(result["face_priority"],
                        "face_priority doit se déclencher (TALL_FACTOR régression)")

    def test_tall_factor_uses_face_priority_ratio_constant(self):
        """
        Check that the internal threshold triggers FULL_BODY_TALL correctly.
        With the new continuous scoring matrix, we need tall_ratio >= 0.70
        and body_aspect > 1.4.
        frame_w=400 -> dmd_crop_h=100. Let rh=82 (tall_ratio=0.82) and rw=50 (aspect=1.64).
        """
        cap = _make_cap(total_frames=90, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()

        mock_det = MagicMock()
        rois = [(10 + (i * 17 % 200), 0, 50, 82) for i in range(90)]
        mock_det.detect_person.side_effect = rois  # 82 > 70, aspect 1.64 > 1.4
        mock_det.detect.side_effect = rois

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            result = _smart_auto_crop_decision(cap, cfg, frame_w=400, frame_h=1080)

        self.assertTrue(result["face_priority"],
                        f"With rh=82 and rw=50, FULL_BODY_TALL should trigger face_priority.")

    def test_short_video_still_detects_face_priority(self):
        """
        Régression: les vidéos courtes (<10s) avec des gros plans doivent
        toujours déclencher face_priority.
        """
        # 3 secondes à 30fps = 90 frames
        cap = _make_cap(total_frames=90, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()

        mock_det = MagicMock()
        rois = [(0 + (i * 17 % 200), 0, 400, 420) for i in range(90)]
        mock_det.detect_person.side_effect = rois  # très tall
        mock_det.detect.side_effect = rois

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            result = _smart_auto_crop_decision(cap, cfg, frame_w=400, frame_h=1080)

        self.assertTrue(result["face_priority"],
                        "Les vidéos courtes doivent aussi déclencher face_priority")


if __name__ == "__main__":
    unittest.main()

