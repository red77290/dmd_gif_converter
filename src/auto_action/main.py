from src.auto_action import AutoActionConfig, available_detectors, preprocess_video_for_dmd

# For testing backwards compatibility
from src.auto_action.detector import _FrameDetector, _fuse_rois, _ensure_yolo_model
from src.auto_action.camera import _build_camera_rect, _smooth, _crop_frame, _apply_look_ahead
from src.auto_action.analysis import _clamp, _FloorEstimator, _compute_auto_crop_margins, _smart_auto_crop_decision, _calculate_dmd_visibility_score, _compute_scene_change_score

__all__ = [
    "AutoActionConfig",
    "available_detectors",
    "preprocess_video_for_dmd",
]
