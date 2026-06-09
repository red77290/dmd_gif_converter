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

    DMD_CROP_H_FACTOR: float = 0.80
    FACE_FRAC: float = 0.28

    step = max(1, total_frames // sample_count)
    roi_tops: list[float]    = []
    roi_bottoms: list[float] = []
    roi_heights: list[float] = []
    roi_widths: list[float]  = []
    face_priority_count: int = 0

    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

    for i in range(0, min(total_frames - 1, sample_count * step), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        roi = detector.detect(frame, cfg.detector)
        if roi is not None:
            rx, ry, rw, rh = roi
            roi_tops.append(float(ry))
            roi_heights.append(float(rh))
            roi_widths.append(float(rw))

            if rh > dmd_crop_h * DMD_CROP_H_FACTOR:
                roi_bottoms.append(float(ry + rh * FACE_FRAC))
                face_priority_count += 1
            else:
                roi_bottoms.append(float(ry + rh))

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
    DMD_CROP_H_FACTOR = 0.80
    FACE_FRAC = 0.28

    step = max(1, total_frames // sample_count)
    roi_tops: list[float]         = []
    roi_bottoms_feet: list[float] = []
    roi_bottoms_fp: list[float]   = []
    roi_heights: list[float]      = []
    roi_widths: list[float]       = []

    frame_lefts: list[float]      = []
    frame_rights: list[float]     = []
    check_pillarbox = getattr(cfg, "auto_pillarbox_crop", False)

    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)
    for i in range(0, min(total_frames - 1, sample_count * step), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok or frame is None: continue
        roi = detector.detect(frame, cfg.detector)
        if roi is not None:
            rx, ry, rw, rh = roi
            roi_tops.append(float(ry))
            roi_bottoms_feet.append(float(ry + rh))
            roi_heights.append(float(rh))
            roi_widths.append(float(rw))
            if rh > dmd_crop_h * DMD_CROP_H_FACTOR:
                roi_bottoms_fp.append(float(ry + rh * FACE_FRAC))
            else:
                roi_bottoms_fp.append(float(ry + rh))
                
        if check_pillarbox:
            # Downsample for speed
            small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
            coords = np.argwhere(thresh > 0)
            if coords.size > 0:
                y_min, x_min = coords.min(axis=0)
                y_max, x_max = coords.max(axis=0)
                frame_lefts.append(x_min / 128.0)
                frame_rights.append(x_max / 128.0)

    cap.set(cv2.CAP_PROP_POS_FRAMES, saved_pos)

    if not roi_tops:
        return {**_EMPTY, "reasons": ["no detections in scan — all manual"]}

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
    TALL_FACTOR       = 1.30
    FLOOR_LOWER       = 0.50
    FLOOR_VAR_MAX     = 0.25

    top_space       = median_top    / frame_h
    bottom_gap      = (frame_h - median_bottom) / frame_h
    tall_ratio      = median_height / max(1.0, dmd_crop_h)
    floor_in_lower  = (median_bottom / frame_h) > FLOOR_LOWER
    floor_var_score = std_bottom / frame_h

    reasons = []
    auto_bottom = False
    auto_top    = False
    auto_floor  = False

    if tall_ratio > TALL_FACTOR:
        auto_bottom = True
        auto_floor  = False
        auto_top    = True
        # Anime / Movies: large sprites, cinematic feel. 
        # Less strength (looser framing), more smoothness (slower panning).
        suggested_strength = 0.55
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 1 — tall-char {tall_ratio*100:.0f}% of DMD window → bottom-crop+face-priority ✓ / top-crop ✓ (narrows to head) / floor-track ✗ (contradictory)")
    elif floor_in_lower and floor_var_score <= FLOOR_VAR_MAX:
        auto_floor  = True
        auto_top    = False
        auto_bottom = bottom_gap > BOTTOM_GAP_THRESH
        stability   = "stable" if floor_var_score < 0.10 else "dynamic"
        # Video games (Platformers): fast movement, but user prefers slower/smoother tracking
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 2 — floor@{median_bottom/frame_h*100:.0f}% var={floor_var_score*100:.0f}% ({stability}) → floor-tracking ✓ / top-crop ✗ (redundant)")
    else:
        auto_floor  = False
        auto_top    = top_space > TOP_SPACE_THRESH
        auto_bottom = (bottom_gap > BOTTOM_GAP_THRESH) or auto_top
        # Video games (Top-down, RPGs, generic action): fast movement, but user prefers slower/smoother tracking
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 3 — no trackable floor")

    median_w      = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
    aspect        = median_height / max(1.0, median_w)
    face_priority = tall_ratio > TALL_FACTOR
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
    bottom_y = float(np.percentile(arr_btm_fp, 95))  + pad_bottom_px
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
        
        # Only apply if it's a significant black bar (e.g., > 5% of screen width)
        # We ADD a small margin (e.g. 2.5%) to the crop to "bite" slightly into the active image
        # and ensure absolutely no black edge (or its compression artifacts) remains visible.
        if raw_left > 0.05:
            left_pct = _clamp(raw_left + 0.025, 0.0, 0.4)
        if raw_right < 0.95:
            right_pct = _clamp((1.0 - raw_right) + 0.025, 0.0, 0.4)

    return {
        "auto_bottom_crop":   auto_bottom,
        "auto_top_crop":      auto_top,
        "auto_vertical_bias": auto_floor,
        "top_pct":            pre_top_pct,
        "bottom_pct":         pre_bottom_pct,
        "left_pct":           left_pct,
        "right_pct":          right_pct,
        "face_priority":      face_priority,
        "reasons":            reasons,
        "suggested_strength": suggested_strength,
        "suggested_smoothness": suggested_smoothness,
    }



