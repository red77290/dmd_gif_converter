from typing import Optional, Tuple
import numpy as np

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class _FloorEstimator:
    """Asymmetric exponential moving average for floor/ground level estimation."""

    # α ∈ (0, 1] — higher = faster response
    _ALPHA_ATTACK  = 0.28   # fast: character lands lower / new lower platform
    _ALPHA_RELEASE = 0.02   # very slow: character in the air / moving upward

    def __init__(self, frame_h: int) -> None:
        self._frame_h: float = float(frame_h)
        self._floor_y: Optional[float] = None

    def update(self, roi_bottom: Optional[float]) -> float:
        """Feed the latest roi_bottom and return the current floor estimate."""
        if roi_bottom is None:
            # No detection: keep last known floor (camera stays anchored).
            if self._floor_y is None:
                # Very first frame with no ROI → default to 80 % of frame.
                self._floor_y = self._frame_h * 0.80
            return self._floor_y

        rb = float(roi_bottom)
        if self._floor_y is None:
            self._floor_y = rb          # first detection: snap immediately
            return self._floor_y

        # Asymmetric update
        alpha = self._ALPHA_ATTACK if rb >= self._floor_y else self._ALPHA_RELEASE
        self._floor_y += alpha * (rb - self._floor_y)
        return self._floor_y

    @property
    def floor_y(self) -> Optional[float]:
        return self._floor_y


def _is_dark_frame(frame, threshold: float = 40.0) -> bool:
    """Return True if the frame is too dark to produce reliable detections."""
    try:
        import cv2 as _cv2
        gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < threshold
    except Exception:
        return False


# Shared face-priority height ratio: ROI height relative to the DMD crop window
# height that triggers face-priority mode. Must be consistent across all scan
# functions so both _compute_auto_crop_margins and _smart_auto_crop_decision
# agree on when a subject is "large enough" to be treated as a close-up.
_FACE_PRIORITY_H_RATIO: float = 0.80


def _compute_auto_crop_margins(  # noqa: C901
    cap,
    detector,
    cfg,
    frame_w: int,
    frame_h: int,
    sample_count: int = 80,
) -> Tuple[float, float, bool]:
    import cv2  # already guaranteed imported by caller
    try:
        import numpy as np
    except ImportError:
        return 0.0, 0.0, False

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        return 0.0, 0.0, False

    # VNext Priority 7: Smart Auto Crop Optimizer
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    duration_s = total_frames / max(1.0, float(fps))
    if duration_s < 10.0:
        sample_count = min(total_frames, int(duration_s * 5))
    elif duration_s < 60.0:
        sample_count = min(total_frames, int(duration_s * 2))
    else:
        sample_count = min(total_frames, int(duration_s * 1))
    sample_count = max(20, min(sample_count, 150))

    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio

    FACE_FRAC: float = 0.28

    step = max(1, total_frames // sample_count)
    roi_tops: list[float]    = []
    roi_bottoms: list[float] = []
    roi_heights: list[float] = []
    roi_widths: list[float]  = []
    face_priority_count: int = 0

    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

    # Use total_frames (not total_frames-1) so that 1-frame GIFs are also sampled.
    for i in range(0, min(total_frames, sample_count * step), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        # Skip frames that are too dark for reliable detection (e.g. fade-in)
        if _is_dark_frame(frame):
            continue
        # Use person detection only (no motion fallback): detect_motion relies on
        # sequential frames via MOG2, which is meaningless when using cap.set() jumps.
        roi = detector.detect_person(frame) if hasattr(detector, "detect_person") else detector.detect(frame, cfg.detector)
        if roi is not None:
            rx, ry, rw, rh = roi
            roi_tops.append(float(ry))
            roi_heights.append(float(rh))
            roi_widths.append(float(rw))

            roi_bottoms.append(float(ry + rh))
            if rh > dmd_crop_h * _FACE_PRIORITY_H_RATIO:
                face_priority_count += 1

    cap.set(cv2.CAP_PROP_POS_FRAMES, saved_pos)

    if not roi_tops:
        return 0.0, 0.0, False

    face_priority = face_priority_count > len(roi_tops) * 0.5
    median_h = float(np.median(roi_heights))
    median_w = float(np.median(roi_widths)) if roi_widths else max(1.0, median_h)
    aspect   = median_h / max(1.0, median_w)

    if face_priority:
        pad_top_px    = frame_h * 0.15
        pad_bottom_px = frame_h * 0.10
    else:
        if aspect < 1.3:
            pad_frac = 0.15
        elif aspect < 2.5:
            pad_frac = 0.10
        else:
            pad_frac = 0.06
        pad_top_px    = frame_h * pad_frac
        pad_bottom_px = frame_h * pad_frac

    top_y    = float(np.percentile(roi_tops,    5)) - pad_top_px
    bottom_y = float(np.percentile(roi_bottoms, 95)) + pad_bottom_px

    top_y    = max(0.0, top_y)
    bottom_y = min(float(frame_h), bottom_y)

    top_pct    = _clamp(top_y / frame_h, 0.0, 0.9)
    bottom_pct = _clamp((frame_h - bottom_y) / frame_h, 0.0, 0.9)

    return top_pct, bottom_pct, face_priority


def _smart_auto_crop_decision(cap, cfg, frame_w: int, frame_h: int, sample_count: int = 80) -> dict:
    from src.plugins.detectors.detector import _FrameDetector
    try:
        detector = _FrameDetector()
    except Exception as e:
        return {
            "auto_bottom_crop":   False,
            "auto_top_crop":      False,
            "auto_vertical_bias": False,
            "top_pct":            0.0,
            "bottom_pct":         0.0,
            "face_priority":      False,
            "reasons":            [f"detector init failed: {e!r}"],
        }
    import cv2
    _EMPTY = {
        "auto_bottom_crop":   False,
        "auto_top_crop":      False,
        "auto_vertical_bias": False,
        "top_pct":            0.0,
        "bottom_pct":         0.0,
        "face_priority":      False,
        "reasons":            [],
    }
    if not (cfg.smart_auto_crop or getattr(cfg, "auto_strength", False) or getattr(cfg, "auto_smoothness", False) or getattr(cfg, "auto_pillarbox_crop", False)):
        return {**_EMPTY, "reasons": ["smart features disabled in config"]}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        return {**_EMPTY, "reasons": ["could not determine frame count"]}

    # VNext Priority 7: Smart Auto Crop Optimizer
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    duration_s = total_frames / max(1.0, float(fps))
    if duration_s < 10.0:
        sample_count = min(total_frames, int(duration_s * 5))
    elif duration_s < 60.0:
        sample_count = min(total_frames, int(duration_s * 2))
    else:
        sample_count = min(total_frames, int(duration_s * 1))
    sample_count = max(20, min(sample_count, 150))

    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio
    DMD_CROP_H_FACTOR = _FACE_PRIORITY_H_RATIO  # synchronized with _compute_auto_crop_margins
    FACE_FRAC = 0.28

    step = max(1, total_frames // sample_count)
    check_pillarbox = getattr(cfg, "auto_pillarbox_crop", False)
    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

    def _run_scan(det_type: str):
        _roi_tops: list[float]         = []
        _roi_bottoms_feet: list[float] = []
        _roi_bottoms_fp: list[float]   = []
        _roi_heights: list[float]      = []
        _roi_widths: list[float]       = []
        _x_centers: list[float]        = []
        _y_centers: list[float]        = []
        _fill_ratios: list[float]      = []
        _frame_lefts: list[float]      = []
        _frame_rights: list[float]     = []
        
        for i in range(0, min(total_frames, sample_count * step), step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
            ok, frame = cap.read()
            if not ok or frame is None: continue
            if _is_dark_frame(frame):
                continue
            
            # For "person", we use the specialized detect_person. For fallback "hybrid", we use detect()
            if det_type == "person" and hasattr(detector, "detect_person"):
                roi = detector.detect_person(frame)
            else:
                roi = detector.detect(frame, det_type)
                
            if roi is not None:
                rx, ry, rw, rh = roi
                _roi_tops.append(float(ry))
                _roi_bottoms_feet.append(float(ry + rh))
                _roi_heights.append(float(rh))
                _roi_widths.append(float(rw))
                _x_centers.append(float(rx + rw / 2.0))
                _y_centers.append(float(ry + rh / 2.0))
                _fill_ratios.append(float(rh) / max(1.0, float(frame_h)))
                _roi_bottoms_fp.append(float(ry + rh))
                    
            if check_pillarbox:
                small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
                coords = np.argwhere(thresh > 0)
                if coords.size > 0:
                    y_min, x_min = coords.min(axis=0)
                    y_max, x_max = coords.max(axis=0)
                    _frame_lefts.append(x_min / 128.0)
                    _frame_rights.append(x_max / 128.0)
                    
        return _roi_tops, _roi_bottoms_feet, _roi_bottoms_fp, _roi_heights, _roi_widths, _x_centers, _y_centers, _fill_ratios, _frame_lefts, _frame_rights

    best_detector = cfg.detector
    (roi_tops, roi_bottoms_feet, roi_bottoms_fp, roi_heights, roi_widths, 
     x_centers, y_centers, fill_ratios, frame_lefts, frame_rights) = _run_scan(best_detector)
     
    if not roi_tops and getattr(cfg, "auto_detector_fallback", False) and best_detector == "person":
        best_detector = "hybrid"
        (roi_tops, roi_bottoms_feet, roi_bottoms_fp, roi_heights, roi_widths, 
         x_centers, y_centers, fill_ratios, frame_lefts, frame_rights) = _run_scan(best_detector)

    cap.set(cv2.CAP_PROP_POS_FRAMES, saved_pos)

    if not roi_tops:
        return {**_EMPTY, "best_detector": best_detector, "reasons": ["no detections in scan — all manual"]}

    arr_tops       = np.array(roi_tops)
    arr_btm_feet   = np.array(roi_bottoms_feet)
    arr_btm_fp     = np.array(roi_bottoms_fp)
    arr_heights    = np.array(roi_heights)
    arr_widths     = np.array(roi_widths) if roi_widths else arr_heights

    median_top    = float(np.median(arr_tops))
    median_bottom = float(np.median(arr_btm_feet))
    median_height = float(np.median(arr_heights))
    std_bottom    = float(np.std(arr_btm_feet))

    TOP_SPACE_THRESH  = 0.08
    BOTTOM_GAP_THRESH = 0.08
    # face_priority triggers when the median ROI height exceeds this fraction of the
    # DMD crop window height.  MUST stay in sync with _FACE_PRIORITY_H_RATIO above so
    # that _smart_auto_crop_decision and _compute_auto_crop_margins agree.
    # History: was accidentally raised to 1.30 in fix/2921a4d, which caused regression
    # where face-priority never triggered for normal close-up shots.
    TALL_FACTOR       = _FACE_PRIORITY_H_RATIO  # 0.80 — restored to match DMD_CROP_H_FACTOR
    FLOOR_LOWER       = 0.50
    FLOOR_VAR_MAX     = 0.25

    top_space       = median_top    / frame_h
    bottom_gap      = (frame_h - median_bottom) / frame_h
    tall_ratio      = median_height / max(1.0, dmd_crop_h)
    floor_in_lower  = (median_bottom / frame_h) > FLOOR_LOWER
    floor_var_score = std_bottom / frame_h

    # Additional signals for scene classification
    median_w       = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
    body_aspect    = median_height / max(1.0, median_w)
    median_fill    = float(np.median(fill_ratios)) if fill_ratios else 0.0
    x_var          = float(np.var(x_centers)) / max(1.0, float(frame_w) ** 2) if x_centers else 0.0
    y_var          = float(np.var(y_centers)) / max(1.0, float(frame_h) ** 2) if y_centers else 0.0

    # ── Scene classification (auto_scene_type or smart_auto_crop) ────────────
    scene_profile = None
    scene_scores = {}
    scene_signals = {
        "tall_ratio":      tall_ratio,
        "fill_ratio":      median_fill,
        "body_aspect":     body_aspect,
        "floor_in_lower":  floor_in_lower,
        "floor_var_score": floor_var_score,
        "x_variance":      x_var,
        "y_variance":      y_var,
    }
    
    _auto_scene = getattr(cfg, "auto_scene_type", False)
    if _auto_scene:
        from src.engine.analysis.scene_types import classify_scene
        scene_profile, scoreboard_lines, scene_scores = classify_scene(scene_signals)
    else:
        scoreboard_lines = []

    reasons = []
    auto_bottom = False
    auto_top    = False
    auto_floor  = False

    decision_codes = {}
    
    if scene_profile is not None:
        # Scene profile drives crop/tracking decisions
        auto_floor  = scene_profile.auto_vertical_bias
        auto_top    = scene_profile.face_priority  # narrow to head when face-aware
        auto_bottom = scene_profile.face_priority or (bottom_gap > BOTTOM_GAP_THRESH)
        if scene_profile.platformer_mode:
            auto_top    = False
            auto_bottom = bottom_gap > BOTTOM_GAP_THRESH
        suggested_strength   = scene_profile.suggested_strength
        suggested_smoothness = scene_profile.suggested_smoothness
        reasons.append(f"SCENE={scene_profile.scene_type} → face_clip={scene_profile.face_clip_mode} floor={scene_profile.auto_vertical_bias}")
        decision_codes["driver"] = "scene_profile"
        
    elif tall_ratio > TALL_FACTOR:
        auto_bottom = True
        auto_floor  = False
        auto_top    = True
        suggested_strength = 0.55
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 1 — tall-char {tall_ratio*100:.0f}% of DMD window → bottom-crop+face-priority ✓ / top-crop ✓ (narrows to head) / floor-track ✗ (contradictory)")
        decision_codes["driver"] = "tall_subject"
        
    elif floor_in_lower and floor_var_score <= FLOOR_VAR_MAX:
        auto_floor  = True
        auto_top    = False
        auto_bottom = bottom_gap > BOTTOM_GAP_THRESH
        stability   = "stable" if floor_var_score < 0.10 else "dynamic"
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 2 — floor@{median_bottom/frame_h*100:.0f}% var={floor_var_score*100:.0f}% ({stability}) → floor-tracking ✓ / top-crop ✗ (redundant)")
        decision_codes["driver"] = "floor_tracking"
        
    else:
        auto_floor  = False
        auto_top    = top_space > TOP_SPACE_THRESH
        auto_bottom = (bottom_gap > BOTTOM_GAP_THRESH) or auto_top
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 3 — no trackable floor")
        decision_codes["driver"] = "fallback"

    face_priority = scene_profile.face_priority if scene_profile is not None else (tall_ratio > TALL_FACTOR)
    aspect        = body_aspect
    if face_priority:
        # Increase top padding heavily for face priority to protect tall hair (like Goku)
        pad_top_px    = frame_h * 0.35
        pad_bottom_px = frame_h * 0.10
    else:
        if aspect < 1.3:
            pad_frac = 0.15
        elif aspect < 2.5:
            pad_frac = 0.10
        else:
            pad_frac = 0.06
        pad_top_px    = frame_h * pad_frac
        pad_bottom_px = frame_h * pad_frac

    top_y    = float(np.percentile(arr_tops,    5))  - pad_top_px
    bottom_y = float(np.percentile(arr_btm_feet, 95))  + pad_bottom_px
    top_y    = max(0.0,          top_y)
    bottom_y = min(float(frame_h), bottom_y)

    pre_top_pct    = _clamp(top_y    / frame_h,              0.0, 0.9)
    pre_bottom_pct = _clamp((frame_h - bottom_y) / frame_h,  0.0, 0.9)

    left_pct = 0.0
    right_pct = 0.0
    if check_pillarbox and frame_lefts:
        # We use the median (50th percentile) to find the typical edge of the black bar,
        # ignoring extreme dark scenes (which would be 95th) and extreme shakes (which would be 5th/10th).
        # To completely hide any jitter, we add an aggressive 2.5% padding (about 20 pixels).
        raw_left = float(np.median(frame_lefts))
        raw_right = float(np.median(frame_rights))
        
        if raw_left > 0.05:
            left_pct = _clamp(raw_left + 0.025, 0.0, 0.4)
            decision_codes["pillarbox"] = "detected"
        elif raw_right < 0.95:
            right_pct = _clamp((1.0 - raw_right) + 0.025, 0.0, 0.4)
            decision_codes["pillarbox"] = "detected"
        else:
            decision_codes["pillarbox"] = "none"
    else:
        decision_codes["pillarbox"] = "disabled"

    return {
        "best_detector":      best_detector,
        "auto_bottom_crop":   auto_bottom,
        "auto_top_crop":      auto_top,
        "auto_vertical_bias": auto_floor,
        "top_pct":            pre_top_pct,
        "bottom_pct":         pre_bottom_pct,
        "left_pct":           left_pct,
        "right_pct":          right_pct,
        "face_priority":      face_priority,
        "reasons":            reasons,
        "decision_codes":     decision_codes,
        "suggested_strength": suggested_strength,
        "suggested_smoothness": suggested_smoothness,
        "scene_profile":      scene_profile,
        "scene_scores":       scene_scores,
        "scene_signals":      scene_signals,
        "scoreboard_lines":   scoreboard_lines,
    }



