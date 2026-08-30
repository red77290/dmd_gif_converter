import pytest
import numpy as np
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.auto_action.camera import _build_camera_rect, _smooth, _compute_base_crop_dimensions
from src.engine.analysis.analyzer import VideoAnalyzer
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
