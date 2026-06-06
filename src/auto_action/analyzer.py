from typing import Optional, Tuple, List, Dict, Any
from .config import AutoActionConfig
from .detector import _FrameDetector
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
        self.face_priority_mode: bool = False
        self.smart_reasons: List[str] = []
        
    def analyze(self, cap) -> None:
        """Runs smart/auto crop analysis and updates configuration variables."""
        _auto_bc = getattr(self.cfg, "auto_bottom_crop", False)
        _auto_tc = getattr(self.cfg, "auto_top_crop", False)
        
        _smart_crop_margins: Optional[Tuple[float, float]] = None
        _smart_face_priority: bool = False
        
        if getattr(self.cfg, "smart_auto_crop", False):
            try:
                _decision = _smart_auto_crop_decision(cap, self.cfg, self.frame_w, self.frame_h)
                _auto_bc                  = _decision["auto_bottom_crop"]
                _auto_tc                  = _decision["auto_top_crop"]
                self.cfg.auto_vertical_bias    = _decision["auto_vertical_bias"]
                self.smart_reasons        = _decision["reasons"]
                _smart_crop_margins  = (_decision["top_pct"], _decision["bottom_pct"])
                _smart_face_priority = _decision.get("face_priority", False)
            except Exception as _e:
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
        self.effective_frame_h   = max(self.cfg.target_height, int(self.frame_h * (1.0 - self.bcp)))
