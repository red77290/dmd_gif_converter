from typing import Optional, Tuple, List, Dict, Any
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import _FrameDetector
from .analysis import _clamp, _smart_auto_crop_decision, _compute_auto_crop_margins

class VideoAnalyzer:
    """Handles static pre-processing decisions before the main loop starts."""
    
    def __init__(self, frame_w: int, frame_h: int, cfg: AutoActionConfig):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.cfg = cfg
        
        # Output dimensions
        self.out_w = frame_w
        target_aspect_ratio = float(cfg.target_width) / cfg.target_height
        self.out_h = max(8, int(round(frame_w / target_aspect_ratio / 2)) * 2)
        
        # Crop percentages
        self.bcp = _clamp(getattr(cfg, "bottom_crop_pct", 0.0), 0.0, 0.9)
        self.tcp = _clamp(getattr(cfg, "top_crop_pct", 0.0), 0.0, 0.9)
        
        # State populated by analyze()
        self.effective_frame_top: int = 0
        self.effective_frame_h: int = 0
        self.effective_frame_left: int = 0
        self.effective_frame_w: int = frame_w
        self.face_priority_mode: bool = False
        self.scene_profile = None   # populated by analyze() when scene classification is active
        self.smart_reasons: List[str] = []
        self.scoreboard: List[str] = []
        
    def analyze(self, cap) -> None:
        """Runs smart/auto crop analysis and updates configuration variables."""
        _auto_bc = getattr(self.cfg, "auto_bottom_crop", False)
        _auto_tc = getattr(self.cfg, "auto_top_crop", False)
        
        _smart_crop_margins: Optional[Tuple[float, float]] = None
        _smart_face_priority: bool = False
        
        _auto_str = getattr(self.cfg, "auto_strength", False)
        _auto_sm = getattr(self.cfg, "auto_smoothness", False)
        _smart = getattr(self.cfg, "smart_auto_crop", False)
        _auto_pillarbox = getattr(self.cfg, "auto_pillarbox_crop", False)
        
        if _smart or _auto_str or _auto_sm or _auto_pillarbox:
            try:
                _decision = _smart_auto_crop_decision(cap, self.cfg, self.frame_w, self.frame_h)
                
                if _smart:
                    _auto_bc                  = _decision["auto_bottom_crop"]
                    _auto_tc                  = _decision["auto_top_crop"]
                    self.cfg.auto_vertical_bias    = _decision["auto_vertical_bias"]
                    self.smart_reasons        = _decision["reasons"]
                    self.scoreboard           = _decision.get("scoreboard_lines", [])
                    _smart_crop_margins  = (_decision["top_pct"], _decision["bottom_pct"])
                    _smart_face_priority = _decision.get("face_priority", False)
                    
                if _auto_pillarbox and "left_pct" in _decision and "right_pct" in _decision:
                    self.effective_frame_left = int(self.frame_w * _decision["left_pct"])
                    self.effective_frame_w = int(self.frame_w * (1.0 - _decision["right_pct"])) - self.effective_frame_left
                
                # Apply dynamic strength and smoothness based on content type analysis
                if _auto_str and "suggested_strength" in _decision:
                    self.cfg.strength = _decision["suggested_strength"]
                if _auto_sm and "suggested_smoothness" in _decision:
                    self.cfg.smoothness = _decision["suggested_smoothness"]

                # Apply scene profile to cfg when auto_scene_type is active
                _sp = _decision.get("scene_profile")
                if _sp is not None:
                    self.scene_profile = _sp
                    self.cfg.scene_type = _sp.scene_type
                    self.cfg.scene_profile = _sp
                    self.cfg.face_clip_mode = _sp.face_clip_mode
                    if _sp.platformer_mode:
                        self.cfg.platformer_mode = True

            except Exception as _e:
                if _smart:
                    self.smart_reasons = [f"smart scan error ({_e!r}) → all manual"]

        self.face_priority_mode = False
        if _auto_bc or _auto_tc:
            try:
                if _smart_crop_margins is not None:
                    computed_top, computed_bottom = _smart_crop_margins
                    self.face_priority_mode = _smart_face_priority
                else:
                    detector_for_scan = _FrameDetector()
                    computed_top, computed_bottom, self.face_priority_mode = \
                        _compute_auto_crop_margins(
                            cap, detector_for_scan, self.cfg, self.frame_w, self.frame_h
                        )
                if _auto_tc:
                    self.tcp = computed_top
                if _auto_bc:
                    self.bcp = computed_bottom
            except Exception:
                pass

        self.effective_frame_top = int(self.frame_h * self.tcp)
        self.effective_frame_h   = max(self.cfg.target_height, int(self.frame_h * (1.0 - self.bcp))) - self.effective_frame_top
