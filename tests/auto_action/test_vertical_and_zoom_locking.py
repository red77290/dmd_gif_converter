import pytest
import numpy as np
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.auto_action.camera import (
    _build_camera_rect,
    _smooth,
    _compute_base_crop_dimensions,
    _compute_detail_preserving_crop_dimensions,
)
from src.engine.analysis.analyzer import VideoAnalyzer
from src.engine.analysis.scene_types import SCENE_PROFILES, SceneType
from src.plugins.trackers.tracker import TrackingEngine

def test_compute_base_crop_dimensions_landscape():
    # 640x480 source, 128x32 target (4:1)
    w, h = _compute_base_crop_dimensions(640, 480, 4.0)
    assert w == 640.0
    assert h == 160.0
    assert w <= 640.0
    assert h <= 480.0

def test_compute_base_crop_dimensions_portrait():
    # 640x480 source, 64x256 target (1:4, ratio 0.25)
    w, h = _compute_base_crop_dimensions(640, 480, 0.25)
    assert h == 480.0
    assert w == 120.0
    assert w <= 640.0
    assert h <= 480.0

def test_compute_base_crop_dimensions_half_tate():
    # 640x480 source, 64x128 target (1:2, ratio 0.5)
    w, h = _compute_base_crop_dimensions(640, 480, 0.5)
    assert h == 480.0
    assert w == 240.0

def test_smooth_locks_crop_dimensions():
    from src.engine.auto_action.interfaces import CamRect
    prev = CamRect(100.0, 100.0, 120.0, 480.0)
    curr = CamRect(150.0, 120.0, 120.0, 480.0)
    
    smoothed = _smooth(prev, curr, 0.5)
    assert smoothed[0] == 125.0  # cx moved
    assert smoothed[1] == 110.0  # cy moved
    assert smoothed[2] == 120.0  # cw is strictly locked
    assert smoothed[3] == 480.0  # ch is strictly locked

def test_video_analyzer_vertical_dimensions():
    cfg = AutoActionConfig(target_width=64, target_height=256)
    analyzer = VideoAnalyzer(640, 480, cfg)
    assert analyzer.out_h == 480
    assert analyzer.out_w == 120
    assert analyzer.out_w <= 640
    assert analyzer.out_h <= 480

def test_video_analyzer_landscape_dimensions():
    cfg = AutoActionConfig(target_width=128, target_height=32)
    analyzer = VideoAnalyzer(640, 480, cfg)
    assert analyzer.out_w == 640
    assert analyzer.out_h == 160

def test_tracking_engine_locked_zoom():
    cfg = AutoActionConfig(target_width=64, target_height=256, strength=0.65)
    tracker = TrackingEngine(30.0, 640, 480, 0, 480, 0, 640, False, cfg, locked_crop_size=(100.0, 400.0))
    
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cam = tracker.process_frame(dummy_frame, tracker.cam_full_view, 0, 64, 256)
    
    assert cam[2] == 100.0
    assert cam[3] == 400.0


def test_detail_preserving_zoom_neogeo_platformer():
    # Neo-Geo 304x224 -> 128x32 (max_w=304, max_h=76), sprite median_h=35px
    cfg = AutoActionConfig(
        target_width=128,
        target_height=32,
        strength=0.65,
        zoom_max=1.45,
        platformer_mode=True,
        auto_vertical_bias=True,
    )
    cfg.scene_profile = SCENE_PROFILES[SceneType.PLATFORMER]
    cw, ch = _compute_detail_preserving_crop_dimensions(304.0, 224.0, cfg, median_h=35.0, median_w=24.0)
    # Must zoom in (~1.30x) while staying >= 1.75 * 128 = 224.0 px to preserve pixel-art detail
    assert 224.0 <= cw < 245.0
    assert 56.0 <= ch < 62.0
    assert abs((cw / ch) - 4.0) < 1e-4


def test_detail_preserving_zoom_snes_detail_floor_guard():
    # SNES 256x224 -> 128x32 (max_w=256, max_h=64): 1.75x detail floor caps cw >= 224.0 (max 1.14x zoom)
    cfg = AutoActionConfig(
        target_width=128,
        target_height=32,
        strength=1.0,
        zoom_max=2.0,
        platformer_mode=True,
        auto_vertical_bias=True,
    )
    cw, ch = _compute_detail_preserving_crop_dimensions(256.0, 224.0, cfg, median_h=28.0, median_w=20.0)
    assert cw >= 224.0
    assert ch >= 56.0


def test_detail_preserving_zoom_disabled_when_zoom_max_is_one():
    cfg = AutoActionConfig(target_width=128, target_height=32, strength=1.0, zoom_max=1.0, platformer_mode=True)
    cw, ch = _compute_detail_preserving_crop_dimensions(304.0, 224.0, cfg, median_h=35.0, median_w=24.0)
    assert cw == 304.0
    assert ch == 76.0

