from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import available_detectors
from src.engine.auto_action.pipeline import preprocess_video_for_dmd

# For testing backwards compatibility
from src.plugins.detectors.detector import _FrameDetector, _fuse_rois, _ensure_yolo_model
from src.engine.auto_action.camera import _build_camera_rect, _smooth, _crop_frame, _apply_look_ahead
from src.engine.analysis.analysis import _clamp, _FloorEstimator, _compute_auto_crop_margins, _smart_auto_crop_decision

__all__ = [
    "AutoActionConfig",
    "available_detectors",
    "preprocess_video_for_dmd",
]
