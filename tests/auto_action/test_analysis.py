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

def patch_analysis_funcs(func):
    def wrapper(*args, **kwargs):
        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mock_meta:
            with patch('src.engine.auto_action.reader.FFmpegPipeReader') as mock_reader:
                kwargs['mock_meta'] = mock_meta
                kwargs['mock_reader'] = mock_reader
                return func(*args, **kwargs)
    return wrapper

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.plugins.detectors.detector
from src.engine.analysis.analysis import (
    _clamp,
    _is_dark_frame,
    _FACE_PRIORITY_H_RATIO,
    _compute_auto_crop_margins,
    _smart_auto_crop_decision,
    _FloorEstimator,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_frame(brightness: int = 128, h: int = 100, w: int = 200) -> np.ndarray:
    """Return a BGR frame filled with a uniform brightness value."""
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def _make_cap(total_frames: int = 60, fps: float = 30.0, frame_brightness: int = 128):
    """Return a mock FFmpegPipeReader that yields bright/dark frames."""
    cap = MagicMock()
    frame = _make_frame(brightness=frame_brightness)
    
    cap.read.return_value = (True, frame)
    cap.open.return_value = (True, "")
    
    def iter_frames():
        for _ in range(total_frames):
            yield frame
    cap.__iter__.return_value = iter_frames()
    
    cap._test_duration = float(total_frames) / fps if fps > 0 else 0
    cap._test_fps = fps
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

        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:

            mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)

            mr.return_value = cap

            top, bot, fp  = _compute_auto_crop_margins('dummy.mp4', det, cfg, 400, 1080)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bot, 0.0)
        self.assertFalse(fp)

    def test_dark_frames_are_skipped(self):
        """Régression: frames sombres ne doivent pas être soumises au détecteur."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=10)  # dark!
        cfg = _make_cfg()
        det = self._make_detector()

        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:

            mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)

            mr.return_value = cap

            top, bot, fp  = _compute_auto_crop_margins('dummy.mp4', det, cfg, 400, 1080)
        # Toutes les frames sont sombres → aucune ne passe → pas de ROI
        det.detect_person.assert_not_called()
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bot, 0.0)

    def test_bright_frames_call_detect_person_not_detect(self):
        """Régression: le scan doit utiliser detect_person (pas detect avec motion fallback)."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()
        det = self._make_detector(roi=(10, 50, 80, 500))

        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:

            mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)

            mr.return_value = cap

            _compute_auto_crop_margins('dummy.mp4', det, cfg, 400, 1080)

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

        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:

            mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)

            mr.return_value = cap

            _, _, fp  = _compute_auto_crop_margins('dummy.mp4', det, cfg, frame_w=400, frame_h=1080)
        self.assertTrue(fp, "face_priority doit se déclencher pour un ROI tall (régression TALL_FACTOR)")

    def test_face_priority_does_not_trigger_with_small_roi(self):
        """Un ROI petit ne doit pas déclencher face_priority."""
        cap = _make_cap(total_frames=60, fps=30.0, frame_brightness=128)
        cfg = _make_cfg()
        # ROI petit: rh=20px, dmd_crop_h=100px → rh < 80px → pas face_priority
        det = self._make_detector(roi=(10, 10, 80, 20))

        with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:

            mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)

            mr.return_value = cap

            _, _, fp  = _compute_auto_crop_margins('dummy.mp4', det, cfg, frame_w=400, frame_h=1080)
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
            with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:
                mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)
                mr.return_value = cap
                result = _smart_auto_crop_decision('dummy.mp4', cfg, 400, 1080)

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
            with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:
                mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)
                mr.return_value = cap
                result = _smart_auto_crop_decision('dummy.mp4', cfg, 400, 1080)

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
            with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:
                mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)
                mr.return_value = cap
                result = _smart_auto_crop_decision('dummy.mp4', cfg, frame_w=400, frame_h=1080)

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
            with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:
                mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)
                mr.return_value = cap
                result = _smart_auto_crop_decision('dummy.mp4', cfg, frame_w=400, frame_h=1080)

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
            with patch('src.engine.conversion.ffmpeg_utils.get_metadata') as mm, patch('src.engine.auto_action.reader.FFmpegPipeReader') as mr:
                mm.return_value = (400, 1080, cap._test_fps, cap._test_duration)
                mr.return_value = cap
                result = _smart_auto_crop_decision('dummy.mp4', cfg, frame_w=400, frame_h=1080)

        self.assertTrue(result["face_priority"],
                        "Les vidéos courtes doivent aussi déclencher face_priority")


class TestPillarboxAndSideBorderLocking(unittest.TestCase):
    """Regression suite ensuring side black borders never survive or move during camera pans."""

    _DETECTOR_PATCH = "src.plugins.detectors.detector._FrameDetector"

    @staticmethod
    def _make_sequence_cap(frames, fps: float = 20.0):
        cap = MagicMock()
        cap.open.return_value = (True, "")
        idx = {"i": 0}

        def _read():
            if idx["i"] >= len(frames):
                return False, None
            fr = frames[idx["i"]]
            idx["i"] += 1
            return True, fr

        cap.read.side_effect = _read
        cap._test_fps = fps
        cap._test_duration = len(frames) / fps
        return cap

    def test_tv_range_pillarbox_with_corner_watermark_detected(self):
        import numpy as np
        from src.engine.analysis.analysis import _smart_auto_crop_decision

        w, h = 640, 360
        frames = []
        for i in range(30):
            fr = np.full((h, w, 3), 18, dtype=np.uint8)  # BT.709 limited-range black (18 > 15!)
            fr[:, 80:560] = (140, 110, 65)  # 4:3 active gameplay area
            fr[180:220, 120 + (i * 8) % 360 : 148 + (i * 8) % 360] = (40, 220, 250)
            fr[330:355, 585:632] = 245  # Bright channel watermark in bottom-right black bar
            frames.append(fr)

        cap = self._make_sequence_cap(frames)
        cfg = _make_cfg(auto_pillarbox_crop=True)
        cfg.auto_scene_type = True
        cfg.is_batch = False
        cfg.scene_type = ""
        cfg.platformer_mode = False
        cfg.auto_detector_fallback = False

        mock_det = MagicMock()
        rois = [(120 + (i * 8) % 360, 180, 28, 40) for i in range(35)]
        mock_det.detect_person.side_effect = rois
        mock_det.detect.side_effect = rois

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            with patch("src.engine.conversion.ffmpeg_utils.get_metadata") as mm, patch(
                "src.engine.auto_action.reader.FFmpegPipeReader", return_value=cap
            ):
                mm.return_value = (w, h, 20.0, 1.5)
                res = _smart_auto_crop_decision("tv_pillarbox.mp4", cfg, frame_w=w, frame_h=h)

        self.assertEqual(res["decision_codes"]["pillarbox"], "detected")
        self.assertGreater(res["left_pct"], 0.125)
        self.assertLess(res["left_pct"], 0.16)
        self.assertGreater(res["right_pct"], 0.125)
        self.assertLess(res["right_pct"], 0.16)

    def test_nes_8px_left_blanking_cropped_without_touching_deep_blue_water(self):
        import numpy as np
        from src.engine.analysis.analysis import _smart_auto_crop_decision

        w, h = 256, 240
        frames = []
        for i in range(30):
            # Deep royal-blue aquatic background (low grayscale luma ~17, high blue channel 96)
            fr = np.zeros((h, w, 3), dtype=np.uint8)
            fr[:, :] = (96, 12, 0)
            fr[:, :8] = (16, 16, 16)  # NES 8px left hardware blanking (3.125% < old 5% threshold!)
            sx = 20 + (i * 6) % 190
            fr[110:142, sx : sx + 22] = (50, 210, 250)
            frames.append(fr)

        cap = self._make_sequence_cap(frames)
        cfg = _make_cfg(auto_pillarbox_crop=True)
        cfg.auto_scene_type = True
        cfg.is_batch = False
        cfg.scene_type = ""
        cfg.platformer_mode = False
        cfg.auto_detector_fallback = False

        mock_det = MagicMock()
        rois = [(20 + (i * 6) % 190, 110, 22, 32) for i in range(35)]
        mock_det.detect_person.side_effect = rois
        mock_det.detect.side_effect = rois

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            with patch("src.engine.conversion.ffmpeg_utils.get_metadata") as mm, patch(
                "src.engine.auto_action.reader.FFmpegPipeReader", return_value=cap
            ):
                mm.return_value = (w, h, 20.0, 1.5)
                res = _smart_auto_crop_decision("nes_water.mp4", cfg, frame_w=w, frame_h=h)

        self.assertEqual(res["decision_codes"]["pillarbox"], "detected")
        self.assertGreater(res["left_pct"], 8.0 / 256.0)
        self.assertLess(res["left_pct"], 0.06)
        self.assertEqual(res["right_pct"], 0.0)

    def test_pillarbox_preserved_when_initial_scan_has_zero_detections(self):
        import numpy as np
        from src.engine.analysis.analysis import _smart_auto_crop_decision

        w, h = 640, 360
        frames = []
        for _ in range(25):
            fr = np.full((h, w, 3), 16, dtype=np.uint8)
            fr[:, 80:560] = (120, 90, 70)
            frames.append(fr)

        cap = self._make_sequence_cap(frames)
        cfg = _make_cfg(auto_pillarbox_crop=True)
        cfg.auto_scene_type = True
        cfg.is_batch = False
        cfg.scene_type = ""
        cfg.platformer_mode = False
        cfg.auto_detector_fallback = False

        mock_det = MagicMock()
        mock_det.detect_person.return_value = None
        mock_det.detect.return_value = None

        with patch(self._DETECTOR_PATCH, return_value=mock_det):
            with patch("src.engine.conversion.ffmpeg_utils.get_metadata") as mm, patch(
                "src.engine.auto_action.reader.FFmpegPipeReader", return_value=cap
            ):
                mm.return_value = (w, h, 20.0, 1.25)
                res = _smart_auto_crop_decision("no_roi_pillarbox.mp4", cfg, frame_w=w, frame_h=h)

        self.assertGreater(res["left_pct"], 0.125)
        self.assertGreater(res["right_pct"], 0.125)

    def test_camera_horizontal_pan_never_exposes_moving_side_borders(self):
        import math
        import numpy as np
        from src.engine.analysis.analysis import _measure_frame_pillarbox_bounds, _resolve_pillarbox_margins
        from src.engine.auto_action.camera import _compute_detail_preserving_crop_dimensions, _smooth_platformer_camera
        from src.engine.auto_action.interfaces import BoundingBox
        from src.engine.auto_action.renderer import Renderer
        from src.engine.config.auto_action_config import AutoActionConfig
        from src.plugins.trackers.tracker import TrackingEngine

        w, h = 640, 360
        frames = []
        rois = []
        # Sweep sprite aggressively from extreme left of 4:3 screen (x=84) to extreme right (x=532) and back
        xs = list(range(84, 532, 24)) + list(range(532, 84, -24))
        for sx in xs:
            fr = np.full((h, w, 3), 18, dtype=np.uint8)  # TV-range black pillarbox bars [0..80) and [560..640)
            fr[:, 80:560] = (150, 115, 80)  # Active 4:3 playfield
            fr[220:256, sx : sx + 24] = (30, 230, 255)
            frames.append(fr)
            rois.append(BoundingBox(sx, 220, 24, 36))

        bounds = [_measure_frame_pillarbox_bounds(f) for f in frames]
        left_pct, right_pct, code = _resolve_pillarbox_margins(
            [b[0] for b in bounds if b], [b[1] for b in bounds if b], w, enabled=True
        )
        self.assertEqual(code, "detected")
        eff_left = int(math.ceil(w * left_pct))
        eff_right = int(math.floor(w * (1.0 - right_pct)))
        eff_w = eff_right - eff_left

        cfg = AutoActionConfig(
            detector="hybrid",
            strength=0.65,
            smoothness=0.75,
            zoom_max=1.35,
            platformer_mode=True,
            auto_pillarbox_crop=True,
            look_ahead_enabled=True,
            target_width=128,
            target_height=32,
        )
        locked_size = _compute_detail_preserving_crop_dimensions(
            float(eff_w), float(h), cfg, median_h=36.0, median_w=24.0
        )
        self.assertLess(locked_size[0], float(eff_w))  # Zoomed in -> camera pans horizontally!

        tracker = TrackingEngine(
            fps=20.0,
            frame_w=w,
            frame_h=h,
            effective_frame_top=0,
            effective_frame_h=h,
            effective_frame_left=eff_left,
            effective_frame_w=eff_w,
            face_priority_mode=False,
            cfg=cfg,
            locked_crop_size=locked_size,
        )
        tracker.detector.detect = MagicMock(side_effect=rois)
        renderer = Renderer(w, h, 128, 32, bg_sub_enable=False)

        cam_prev = tracker.cam_full_view
        for idx, fr in enumerate(frames):
            cam_now = tracker.process_frame(fr, cam_prev, idx, 128, 32)
            cam = cam_now if idx == 0 else _smooth_platformer_camera(cam_prev, cam_now, 0.75)
            cam_prev = cam
            dmd_frame = renderer.render(fr, cam)
            # Neither outer column of the 128x32 DMD may ever show the dark pillarbox bar (BGR ~18)
            self.assertGreater(int(dmd_frame[:, 0].mean()), 80, f"Left pillarbox leaked at frame {idx}")
            self.assertGreater(int(dmd_frame[:, -1].mean()), 80, f"Right pillarbox leaked at frame {idx}")


if __name__ == "__main__":
    unittest.main()


