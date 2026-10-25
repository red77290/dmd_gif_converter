"""
Comprehensive unit tests for close-up face framing across wide DMD aspect
ratios (128x32 = 4:1, 128x64 = 2:1, 256x64 = 4:1).

Verifies that:
  1. Close-up face / portrait shots frame the expressive eye-to-mouth region
     (~[0.34*fh .. 0.80*fh], centred near 0.57*fh) rather than the hairline and
     forehead ([0.00 .. 0.30*fh]).
  2. Removing the upward headroom clamp in `_build_camera_rect` preserves mouth
     visibility even when the DMD strip height `crop_h` is smaller than `fh`.
  3. `classify_scene()` and `_clip_to_face_roi()` handle widescreen 16:9 close-up
     aspects (~0.60..1.40) without misapplying full-body head proportions, and
     self-heal if a scene cut occurs mid-clip.
  4. Non-`face_priority` close-ups (`auto_vertical_bias=True`) do not corrupt
     floor estimation with `ry + 0.25 * frame_h` (forehead-as-floor regression)
     and still frame the eye-to-mouth band.
  5. Full-body, wide-shot, and platformer floor-locked shots remain intact.
"""
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from src.engine.analysis.scene_types import SCENE_PROFILES, SceneType, classify_scene
from src.engine.auto_action.camera import _build_camera_rect
from src.engine.auto_action.interfaces import BoundingBox
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.trackers.tracker import TrackingEngine


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _make_engine(
    frame_w: int = 640,
    frame_h: int = 480,
    target_w: int = 128,
    target_h: int = 32,
    face_priority: bool = True,
    scene_type: str | None = SceneType.TALKING_CLOSEUP,
    auto_vertical_bias: bool = False,
    platformer_mode: bool = False,
    dynamic_scene_detection: bool = False,
) -> TrackingEngine:
    profile = SCENE_PROFILES[scene_type] if scene_type else None
    cfg = AutoActionConfig(
        target_width=target_w,
        target_height=target_h,
        detector="person",
        smart_auto_crop=True,
        smoothness=0.0,
        zoom_max=1.0,
        min_roi_area_ratio=0.0,
        min_subject_dmd_px=0,
        roi_history_window_s=0.0,
        dmd_visibility_score_enabled=False,
        dmd_readability_score_enabled=False,
        look_ahead_enabled=False,
        auto_vertical_bias=profile.auto_vertical_bias if profile else auto_vertical_bias,
        platformer_mode=profile.platformer_mode if profile else platformer_mode,
        dynamic_scene_detection=dynamic_scene_detection,
    )
    if profile is not None:
        cfg.scene_type = profile.scene_type
        cfg.scene_profile = profile
        cfg.face_clip_mode = profile.face_clip_mode

    with patch("src.plugins.detectors.detector.DetectorFactory.create") as mock_factory, \
         patch("src.plugins.detectors.detector._ensure_yolo_model", return_value=None):
        mock_factory.return_value = MagicMock()
        engine = TrackingEngine(
            fps=25.0,
            frame_w=frame_w,
            frame_h=frame_h,
            effective_frame_top=0,
            effective_frame_h=frame_h,
            effective_frame_left=0,
            effective_frame_w=frame_w,
            face_priority_mode=face_priority,
            cfg=cfg,
        )
    return engine


class TestCloseUpEyesAndMouthFraming(unittest.TestCase):
    """End-to-end vertical crop verification on 128x32, 128x64, and 256x64 DMDs."""

    def test_widescreen_closeup_covers_eyes_and_mouth_across_dmd_ratios(self):
        """
        16:9 close-up portrait (496x278, face bbox [140, 12, 240, 190]):
          - Forehead: [12 .. 69]   (0.00 .. 0.30 * fh)
          - Eyes:     [80 .. 105]  (0.36 .. 0.49 * fh)
          - Mouth:    [141 .. 164] (0.68 .. 0.80 * fh)
        On 128x32 (4:1), 256x64 (4:1), and 128x64 (2:1), the camera strip must
        include both eyes and mouth rather than focusing on the forehead.
        """
        fw, fh_frame = 496, 278
        fx, fy, fw_box, fh_box = 140, 12, 240, 190
        forehead_band = (fy, fy + 0.30 * fh_box)
        eyes_band = (fy + 0.36 * fh_box, fy + 0.49 * fh_box)
        mouth_band = (fy + 0.68 * fh_box, fy + 0.80 * fh_box)
        expressive_band = (fy + 0.35 * fh_box, fy + 0.80 * fh_box)

        for target_w, target_h in [(128, 32), (256, 64), (128, 64)]:
            with self.subTest(dmd=f"{target_w}x{target_h}"):
                engine = _make_engine(
                    frame_w=fw,
                    frame_h=fh_frame,
                    target_w=target_w,
                    target_h=target_h,
                    face_priority=True,
                    scene_type=SceneType.TALKING_CLOSEUP,
                )
                engine.detector.detect = MagicMock(return_value=BoundingBox(fx, fy, fw_box, fh_box))
                frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

                _, cy, _, ch = engine.process_frame(
                    frame, engine.cam_full_view, src_idx=0, out_w=target_w, out_h=target_h
                )
                cam_top = cy - ch / 2.0
                cam_bottom = cy + ch / 2.0

                # Both eyes and mouth must sit comfortably inside the selected DMD strip
                self.assertLessEqual(
                    cam_top, eyes_band[0],
                    f"{target_w}x{target_h}: cam_top={cam_top:.1f} cut into eyes={eyes_band}",
                )
                self.assertGreaterEqual(
                    cam_bottom, mouth_band[1],
                    f"{target_w}x{target_h}: cam_bottom={cam_bottom:.1f} cut off mouth={mouth_band}",
                )

                # Expressive eye-to-mouth coverage must cover nearly 100% of [0.35..0.80]
                # and strictly exceed forehead coverage ([0.00..0.30]). On 4:1 strips
                # (ch < fh_box), forehead overlap is nearly zero (> 2.5x ratio).
                forehead_cov = _overlap_1d(cam_top, cam_bottom, *forehead_band)
                expressive_cov = _overlap_1d(cam_top, cam_bottom, *expressive_band)
                expressive_span = expressive_band[1] - expressive_band[0]
                self.assertGreaterEqual(
                    expressive_cov / expressive_span, 0.95,
                    f"{target_w}x{target_h}: expected >=95% of eye-to-mouth band covered",
                )
                min_ratio = 2.5 if ch < fh_box else 1.4
                self.assertGreater(
                    expressive_cov, forehead_cov * min_ratio,
                    f"{target_w}x{target_h}: too much forehead ({forehead_cov:.1f}px) vs "
                    f"eyes+mouth ({expressive_cov:.1f}px)",
                )

    def test_extreme_fullscreen_closeup_excludes_upper_forehead_on_4_to_1_dmd(self):
        """
        Extreme close-up filling almost the entire 640x480 frame (face bbox [40, 0, 560, 460]):
        On 128x32 (crop_h = 160 px < fh = 460 px), the 160 px strip cannot span the
        entire head, so it MUST skip the forehead ([0 .. 138 px]) and centre on the
        eye-to-mouth bridge (~0.57 * fh = 262 px -> [182 .. 342 px]).
        """
        fw, fh_frame = 640, 480
        face_box = BoundingBox(40, 0, 560, 460)
        engine = _make_engine(
            frame_w=fw,
            frame_h=fh_frame,
            target_w=128,
            target_h=32,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        engine.detector.detect = MagicMock(return_value=face_box)
        frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Upper 30% forehead ([0 .. 138]) must be completely outside the 128x32 strip
        self.assertGreater(
            cam_top, 0.30 * 460,
            f"Extreme close-up cam_top={cam_top:.1f} still includes forehead ([0..138])",
        )
        # Camera centre must sit in the eye-to-mouth zone [0.50*fh .. 0.65*fh]
        self.assertGreaterEqual(cy, 0.50 * 460)
        self.assertLessEqual(cy, 0.65 * 460)
        # Lower mouth region (~0.72*fh = 331 px) must be visible inside cam_bottom
        self.assertGreaterEqual(cam_bottom, 0.72 * 460)

    def test_extreme_closeup_on_128x64_captures_full_eyes_and_mouth(self):
        """On 128x64 (2:1, crop_h = 320 px), an extreme 460 px face captures both eyes and mouth."""
        fw, fh_frame = 640, 480
        face_box = BoundingBox(40, 0, 560, 460)
        engine = _make_engine(
            frame_w=fw,
            frame_h=fh_frame,
            target_w=128,
            target_h=64,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        engine.detector.detect = MagicMock(return_value=face_box)
        frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=64)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Eyes (~0.38*fh = 175 px) and mouth (~0.76*fh = 350 px) both inside [cam_top, cam_bottom]
        self.assertLessEqual(cam_top, 0.38 * 460)
        self.assertGreaterEqual(cam_bottom, 0.78 * 460)


class TestSceneClassificationAndSelfHealing(unittest.TestCase):
    """Scene classification and _clip_to_face_roi self-healing guards."""

    def test_widescreen_closeup_portrait_classifies_as_talking_closeup(self):
        """
        A 16:9 close-up face often has body_aspect ~0.75..0.82 (< 0.85) with
        fill_ratio ~0.65. It must classify as TALKING_CLOSEUP, not TALKING_MEDIUM
        or ACTION_HORIZONTAL.
        """
        profile, _, _ = classify_scene({
            "tall_ratio": 1.55,
            "fill_ratio": 0.67,
            "body_aspect": 0.78,
            "floor_in_lower": True,
            "floor_var_score": 0.05,
            "x_variance": 0.001,
            "y_variance": 0.001,
        })
        self.assertEqual(profile.scene_type, SceneType.TALKING_CLOSEUP)
        self.assertTrue(profile.face_priority)
        self.assertEqual(profile.face_clip_mode, "closeup")

    def test_standing_tall_character_classifies_as_full_body_tall_not_closeup(self):
        """
        A full-body character filling 85% of frame height with body_aspect = 2.65
        must classify as FULL_BODY_TALL rather than TALKING_CLOSEUP.
        """
        profile, _, _ = classify_scene({
            "tall_ratio": 3.50,
            "fill_ratio": 0.85,
            "body_aspect": 2.65,
            "floor_in_lower": True,
            "floor_var_score": 0.02,
            "x_variance": 0.001,
            "y_variance": 0.001,
        })
        self.assertEqual(profile.scene_type, SceneType.FULL_BODY_TALL)
        self.assertEqual(profile.face_clip_mode, "full_body_head")

    def test_full_body_profile_self_heals_when_given_compact_closeup_roi(self):
        """
        Even if FULL_BODY_TALL is active, a compact close-up ROI (aspect <= 1.4)
        must promote to 'closeup' eye-to-mouth clipping instead of taking the top
        10-20% forehead slice.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            face_priority=True,
            scene_type=SceneType.FULL_BODY_TALL,
        )
        clipped = engine._clip_to_face_roi(BoundingBox(140, 10, 240, 187))
        self.assertIsNotNone(clipped)
        self.assertEqual(clipped.y, 10 + int(187 * 0.34))
        self.assertEqual(clipped.h, int(187 * 0.46))

    def test_closeup_profile_self_heals_when_given_tall_standing_roi(self):
        """
        Conversely, if TALKING_CLOSEUP is active and a scene cut reveals a standing
        character (aspect = 2.6 > 1.65), _clip_to_face_roi must target the head
        rather than the abdomen.
        """
        engine = _make_engine(
            frame_w=500,
            frame_h=500,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        clipped = engine._clip_to_face_roi(BoundingBox(150, 20, 170, 440))
        self.assertIsNotNone(clipped)
        head_center_rel = (clipped.y - 20) + clipped.h / 2.0
        self.assertLess(head_center_rel, 440 * 0.25)


class TestNonFacePriorityCloseUpAndNonRegression(unittest.TestCase):
    """Protects mid-trailer close-up cuts and preserves wide/platformer framing."""

    def test_non_face_priority_closeup_does_not_treat_forehead_as_floor(self):
        """
        Regression test for FloorEstimationStage + _build_camera_rect:
        Previously, when face_priority_mode=False and auto_vertical_bias=True
        (e.g., ACTION_MOVING cutting to a close-up), FloorEstimationStage set
        roi_bottom = ry + 0.25 * frame_h (= forehead!) and _apply_auto_floor
        pinned cam_bottom to the forehead. Now it must frame eyes + mouth.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.ACTION_MOVING,
        )
        # Close-up face box [140, 12, 240, 190]
        engine.detector.detect = MagicMock(return_value=BoundingBox(140, 12, 240, 190))
        frame = np.zeros((278, 496, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Must cover eyes (~85 px) and mouth (~155 px), NOT clamp cam_bottom to forehead (~81 px)
        self.assertLessEqual(cam_top, 85.0)
        self.assertGreaterEqual(cam_bottom, 165.0)

    def test_wide_shot_small_character_still_tracks_ground_feet(self):
        """Wide/medium shot with a small walking character keeps feet anchored near floor."""
        cfg = AutoActionConfig(
            target_width=128,
            target_height=32,
            auto_vertical_bias=True,
            platformer_mode=False,
            smoothness=0.0,
        )
        cfg.scene_profile = SCENE_PROFILES[SceneType.WIDE_SHOT]
        # Small character (w=50, h=90) standing with feet at y=410 in 640x480
        roi = BoundingBox(280, 320, 50, 90)
        _, cy, _, ch = _build_camera_rect(
            640, 480, roi, cfg, floor_y_est=410.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0
        self.assertLessEqual(cam_top, 320.0, "Character head should remain inside wide-shot crop")
        self.assertGreaterEqual(cam_bottom, 410.0, "Character feet should remain inside wide-shot crop")

    def test_platformer_floor_lock_unbroken(self):
        """Platformer mode stays strictly locked to floor_y_est even on wide jumping ROIs."""
        engine = _make_engine(
            frame_w=304,
            frame_h=224,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.PLATFORMER,
        )
        # Feed ground-standing sprite first, then wide explosion/jump ROI
        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        engine.detector.detect = MagicMock(return_value=BoundingBox(120, 140, 32, 44))
        cam1 = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)

        engine.detector.detect = MagicMock(return_value=BoundingBox(40, 20, 220, 150))
        cam2 = engine.process_frame(frame, cam1, src_idx=1, out_w=128, out_h=32)

        self.assertAlmostEqual(cam1[1], cam2[1], delta=2.0)


    def test_dynamic_scene_cut_to_closeup_syncs_clip_mode_and_frames_eyes_mouth(self):
        """
        When dynamic_scene_detection=True detects a cut from ACTION_MOVING
        (face_clip_mode='none', auto_vertical_bias=True) into a close-up face,
        SceneClassificationStage must sync face_clip_mode and re-clip face_roi
        on the cut evaluation frame.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.ACTION_MOVING,
            dynamic_scene_detection=True,
        )
        engine.roi_history_enabled = True
        engine.roi_history_max_len = 5
        for _ in range(4):
            engine.roi_history.append((1.0, BoundingBox(140, 12, 240, 190)))
        engine.frames_since_scene_change = 4  # SceneChangeStage increments to 5 == wait_frames

        engine.detector.detect = MagicMock(return_value=BoundingBox(140, 12, 240, 190))
        frame = np.zeros((278, 496, 3), dtype=np.uint8)
        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=5, out_w=128, out_h=32)

        self.assertEqual(engine.cfg.scene_type, SceneType.TALKING_CLOSEUP)
        self.assertEqual(engine.cfg.face_clip_mode, "closeup")
        self.assertFalse(engine.cfg.auto_vertical_bias)
        self.assertLessEqual(cy - ch / 2.0, 85.0)
        self.assertGreaterEqual(cy + ch / 2.0, 165.0)


if __name__ == "__main__":
    unittest.main()
