"""
Unit tests for 2D platformer vertical framing, stance-aware floor estimation,
character headroom/footroom guards, and anti-thick-ground-scroll detection.
"""

from unittest.mock import MagicMock
import numpy as np
import pytest

from src.engine.analysis.analysis import _FloorEstimator
from src.engine.auto_action.camera import _build_camera_rect
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import _FrameDetector


def _platformer_cfg(**overrides) -> AutoActionConfig:
    params = dict(
        target_width=128,
        target_height=32,
        platformer_mode=True,
        auto_vertical_bias=True,
        smoothness=0.0,
        look_ahead_enabled=False,
        look_ahead_factor=0.0,
    )
    params.update(overrides)
    return AutoActionConfig(**params)


class TestPlatformerFloorRatioAndThickGroundFraming:
    """Verify 0.90 floor ratio and framing on thick ground slabs."""

    def test_default_platformer_floor_ratio_is_090(self):
        cfg = AutoActionConfig()
        assert cfg.platformer_floor_ratio == pytest.approx(0.90)

    def test_thick_ground_shows_few_dmd_pixels_below_feet_without_clipping(self):
        """
        Scenario (a): On a 304x224 frame where thick ground spans y=145..224 and
        the player stands with feet at y=145 (sprite y=109..145, h=36):
        - Camera shows ~3 DMD pixels of ground below y=145 on a 128x32 DMD.
        - Character head has ample headroom (zero top clipping).
        - Camera is NOT dragged down to y=224.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32)
        roi = (120, 109, 24, 36)  # feet at y_bottom = 145

        cx, cy, cw, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Ground visible below y=145 in DMD pixels (~3.2 px on 32px DMD)
        ground_src_px = cam_bottom - 145.0
        ground_dmd_px = ground_src_px * (32.0 / ch)
        assert 2.0 <= ground_dmd_px <= 4.5

        # Full character visibility with comfortable headroom
        assert cam_top < roi[1] - 4.0
        assert cam_bottom >= roi[1] + roi[3]
        assert cam_bottom < 165.0  # nowhere near frame bottom y=224

    def test_thick_ground_64px_dmd_shows_proportional_ground_strip(self):
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=64)
        roi = (120, 95, 28, 50)  # feet at y_bottom = 145

        _, cy, _, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0
        ground_dmd_px = (cam_bottom - 145.0) * (64.0 / ch)

        assert 5.0 <= ground_dmd_px <= 7.5
        assert cam_top < roi[1]

    def test_lagging_low_floor_estimate_never_clips_character_head_on_thick_ground(self):
        """
        Even if floor_y_est temporarily lags deep inside a thick ground slab (e.g. 210),
        the headroom guard must keep the character's head inside the DMD frame.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        roi = (120, 109, 24, 36)  # feet at 145, head at 109

        _, cy, _, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=210.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        assert cam_top <= roi[1] - (ch * 0.06 - 1e-4)


class TestCharacterHeadroomAndFootroomGuards:
    """Verify strict character visibility envelope in _build_camera_rect."""

    def test_high_jump_never_clips_head_above_cam_rect(self):
        """
        Scenario (b): Character jumps high near the top of the screen while
        floor_y_est remains anchored on the ground below.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        jumping_roi = (130, 18, 24, 36)  # head at y=18, feet at y=54

        _, cy, _, ch = _build_camera_rect(
            fw, fh, jumping_roi, cfg, floor_y_est=180.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        assert cam_top <= jumping_roi[1]
        assert cam_bottom >= jumping_roi[1] + jumping_roi[3]

    def test_dropping_below_floor_estimate_never_clips_feet(self):
        """When dropping from a high platform before floor_y_est catches up, feet stay visible."""
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        falling_roi = (130, 152, 24, 36)  # feet at y=188 while floor_y_est is still 105

        _, cy, _, ch = _build_camera_rect(
            fw, fh, falling_roi, cfg, floor_y_est=105.0, face_priority_mode=False
        )
        cam_bottom = cy + ch / 2.0
        assert cam_bottom >= falling_roi[1] + falling_roi[3]

    def test_sprite_taller_than_crop_h_anchors_on_upper_body_without_head_clip(self):
        """Tall character/boss sprite exceeding crop_h=76 keeps head visible."""
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        tall_character = (120, 80, 44, 92)  # h=92 > crop_h=76

        _, cy, _, ch = _build_camera_rect(
            fw, fh, tall_character, cfg, floor_y_est=172.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        assert cam_top <= tall_character[1]


class TestBidirectionalFloorEstimator:
    """Verify stance-aware bidirectional platform tracking and spike rejection."""

    def test_bidirectional_platform_climb_and_drop(self):
        """
        Scenario (c): Character starts at y_bottom=185 on a 224p frame, climbs onto
        an upper platform at y_bottom=105 (stays >= 8 frames), then drops back to 185.
        """
        fe = _FloorEstimator(frame_h=224)
        for _ in range(5):
            fe.update(185.0)
        assert fe.floor_y == pytest.approx(185.0, abs=0.5)

        # Climb onto upper platform at y_bottom = 105 and hold for 8 frames
        for _ in range(8):
            fe.update(105.0)
        # After 8 frames, floor estimate must have climbed the vast majority of the way
        # (vs old _ALPHA_RELEASE=0.02 which stayed stuck at ~173!)
        assert fe.floor_y < 126.0

        # Settling a few more frames converges tightly onto ~105
        for _ in range(8):
            fe.update(105.0)
        assert fe.floor_y == pytest.approx(105.0, abs=3.0)

        # Drop back down to lower platform y_bottom = 185
        for _ in range(12):
            fe.update(185.0)
        assert fe.floor_y == pytest.approx(185.0, abs=3.5)

    def test_isolated_bottom_border_spike_is_rejected_until_corroborated(self):
        fe = _FloorEstimator(frame_h=224)
        fe.update(145.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Single-frame ground-scroll noise touching extreme bottom (222 >= 0.96 * 224)
        fe.update(222.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Next frame returns to normal sprite feet -> spike streak resets cleanly
        fe.update(145.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Two consecutive corroborated bottom detections are accepted smoothly
        fe.update(220.0)
        assert fe.floor_y == pytest.approx(145.0)
        fe.update(220.0)
        assert fe.floor_y > 160.0

    def test_transient_jump_arc_keeps_floor_calm(self):
        fe = _FloorEstimator(frame_h=224)
        for _ in range(6):
            fe.update(185.0)

        # Parabolic 6-frame jump arc on the same platform (high spread -> jump, not stance)
        for y_jump in (162.0, 136.0, 118.0, 118.0, 136.0, 162.0):
            fe.update(y_jump)

        assert fe.floor_y > 173.0  # stays calm near 185 instead of snapping to jump apex

    def test_first_real_detection_after_none_snaps_immediately(self):
        """TrackingEngine calls update(None) at init; first real sprite detection must snap."""
        fe = _FloorEstimator(frame_h=224)
        default_y = fe.update(None)
        assert default_y == pytest.approx(224 * 0.80)

        snapped_y = fe.update(145.0)
        assert snapped_y == pytest.approx(145.0)


class TestAntiThickGroundScrollDetector:
    """Verify motion and YOLO detectors ignore thick scrolling ground slabs."""

    def test_detect_motion_selects_player_sprite_over_wide_scrolling_ground_slab(self):
        """
        Scenario (d): Wide scrolling ground-slab motion noise at y=160..224, w=180
        vs compact player sprite motion at y=120..156, w=24 -> selects player sprite.
        """
        det = _FrameDetector()
        fw, fh = 304, 224

        # Warm up background model on static dark background
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        frame_a = bg.copy()
        # Initial positions before horizontal scroll step
        frame_a[160:224, 50:230] = (90, 90, 90)
        frame_a[120:156, 96:120] = (220, 220, 220)
        det.detect_motion(frame_a, platformer_mode=True)

        frame_b = bg.copy()
        # Frame B: wide ground band shifts producing 180px-wide motion at y=160..224,
        # while compact player sprite moves at y=120..156, w=24.
        frame_b[160:224, 60:240] = (255, 255, 255)
        frame_b[120:156, 124:148] = (255, 255, 255)

        roi = det.detect_motion(frame_b, platformer_mode=True)
        assert roi is not None
        rx, ry, rw, rh = roi
        # Must lock onto the compact player sprite near x=124..148, y=120..156 (NOT ground y=160..224)
        assert rw < 60
        assert 110 <= ry <= 130
        assert 145 <= (ry + rh) <= 166

    def test_detect_motion_tracks_upper_platform_sprite_with_expected_floor(self):
        det = _FrameDetector()
        fw, fh = 304, 224
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True, expected_floor_y=185.0)

        frame_b = bg.copy()
        # Wide scrolling ground slab at bottom + compact sprite on upper platform y=69..105
        frame_b[170:224, 40:220] = (255, 255, 255)
        frame_b[69:105, 140:164] = (255, 255, 255)

        roi = det.detect_motion(frame_b, platformer_mode=True, expected_floor_y=185.0)
        assert roi is not None
        _, ry, rw, rh = roi
        assert rw < 60
        assert 60 <= ry <= 80
        assert 95 <= (ry + rh) <= 115

    def test_detect_yolo_platformer_prefers_playfield_sprite_over_bottom_border_noise(self):
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Build synthetic YOLOv8 output tensor of shape (1, 5, 2):
        # Box 0: bottom-border tile pareidolia (cy=615, bh=48 -> bottom=639/640 = 0.998, conf=0.60)
        # Box 1: player sprite on thick ground (cy=363, bh=102 -> bottom=414/640 = 0.647, conf=0.65)
        pred = np.zeros((1, 5, 2), dtype=np.float32)
        pred[0, :, 0] = [320.0, 615.0, 80.0, 48.0, 0.60]
        pred[0, :, 1] = [260.0, 363.0, 50.0, 102.0, 0.65]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi = det._detect_yolo(frame, platformer_mode=True, expected_floor_y=None)
        assert roi is not None
        _, ry, _, rh = roi
        # Box 1 maps to y_bottom ≈ 145 on 224p (NOT Box 0 at y_bottom ≈ 224)
        assert 138 <= (ry + rh) <= 152

    def test_detect_motion_separates_sprite_directly_touching_scrolling_ground_slab(self):
        """Even with zero vertical gap (feet at y=160 touching ground y=160..224), extracts the sprite."""
        det = _FrameDetector()
        fw, fh = 304, 224
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        frame_b = bg.copy()
        frame_b[160:224, 40:230] = (240, 240, 240)
        frame_b[124:160, 130:154] = (240, 240, 240)

        roi = det.detect_motion(frame_b, platformer_mode=True)
        assert roi is not None
        _, ry, rw, rh = roi
        assert rw < 60
        assert 115 <= ry <= 132
        assert 150 <= (ry + rh) <= 165

