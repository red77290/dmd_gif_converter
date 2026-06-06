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
    from .detector import _FrameDetector
    detector = _FrameDetector()
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
    if not cfg.smart_auto_crop:
        return {**_EMPTY, "reasons": ["smart_auto_crop disabled in config"]}

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
    TALL_FACTOR       = 0.80
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
        reasons.append(f"GROUP 1 — tall-char {tall_ratio*100:.0f}% of DMD window → bottom-crop+face-priority ✓ / top-crop ✓ (narrows to head) / floor-track ✗ (contradictory)")
    elif floor_in_lower and floor_var_score <= FLOOR_VAR_MAX:
        auto_floor  = True
        auto_top    = False
        auto_bottom = bottom_gap > BOTTOM_GAP_THRESH
        stability   = "stable" if floor_var_score < 0.10 else "dynamic"
        reasons.append(f"GROUP 2 — floor@{median_bottom/frame_h*100:.0f}% var={floor_var_score*100:.0f}% ({stability}) → floor-tracking ✓ / top-crop ✗ (redundant)")
    else:
        auto_floor  = False
        auto_top    = top_space > TOP_SPACE_THRESH
        auto_bottom = (bottom_gap > BOTTOM_GAP_THRESH) or auto_top
        reasons.append(f"GROUP 3 — no trackable floor")

    median_w      = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
    aspect        = median_height / max(1.0, median_w)
    face_priority = tall_ratio > TALL_FACTOR
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

    top_y    = float(np.percentile(arr_tops,    5))  - pad_top_px
    bottom_y = float(np.percentile(arr_btm_fp, 95))  + pad_bottom_px
    top_y    = max(0.0,          top_y)
    bottom_y = min(float(frame_h), bottom_y)

    pre_top_pct    = _clamp(top_y    / frame_h,              0.0, 0.9)
    pre_bottom_pct = _clamp((frame_h - bottom_y) / frame_h,  0.0, 0.9)

    return {
        "auto_bottom_crop":   auto_bottom,
        "auto_top_crop":      auto_top,
        "auto_vertical_bias": auto_floor,
        "top_pct":            pre_top_pct,
        "bottom_pct":         pre_bottom_pct,
        "face_priority":      face_priority,
        "reasons":            reasons,
    }


def _calculate_dmd_visibility_score(dmd_frame: np.ndarray, subject_dmd_rect: Optional[Tuple[int, int, int, int]] = None) -> float:
    import cv2
    import numpy as np

    if dmd_frame is None or dmd_frame.size == 0:
        return 0.0

    gray_dmd = cv2.cvtColor(dmd_frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_dmd, 10, 255, cv2.THRESH_BINARY)
    non_black_pixels = np.sum(thresh > 0)
    total_pixels = dmd_frame.shape[0] * dmd_frame.shape[1]
    non_black_ratio = non_black_pixels / total_pixels if total_pixels > 0 else 0.0

    sobelx = cv2.Sobel(gray_dmd, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray_dmd, cv2.CV_64F, 0, 1, ksize=3)
    gradient_magnitude = np.sqrt(sobelx**2 + sobely**2)
    mean_gradient = np.mean(gradient_magnitude)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_length = sum(cv2.arcLength(c, True) for c in contours)
    frame_perimeter = 2 * (dmd_frame.shape[0] + dmd_frame.shape[1])
    contour_density = contour_length / frame_perimeter if frame_perimeter > 0 else 0.0

    coords = np.argwhere(thresh > 0)
    if coords.size > 0:
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        occupied_width = x_max - x_min + 1
        occupied_height = y_max - y_min + 1
        h_occupation = occupied_width / dmd_frame.shape[1]
        v_occupation = occupied_height / dmd_frame.shape[0]
    else:
        h_occupation = 0.0
        v_occupation = 0.0

    w_non_black = 0.3
    w_contrast = 0.4
    w_contour_density = 0.2
    w_occupation = 0.1

    base_score = (
        w_non_black * non_black_ratio +
        w_contrast * (mean_gradient / 255.0) +
        w_contour_density * contour_density +
        w_occupation * ((h_occupation + v_occupation) / 2.0)
    )

    # VNext Priority 2: DMD Visibility Score v2 (subject_visibility_bonus)
    subject_visibility_bonus = 0.0
    if subject_dmd_rect is not None:
        sx, sy, sw, sh = subject_dmd_rect
        # Bonus for good size (ideal is occupying ~30-90% of height)
        sub_h_ratio = sh / dmd_frame.shape[0] if dmd_frame.shape[0] > 0 else 0
        sub_w_ratio = sw / dmd_frame.shape[1] if dmd_frame.shape[1] > 0 else 0
        
        if 0.3 < sub_h_ratio < 0.9:
            subject_visibility_bonus += 0.2
        if 0.1 < sub_w_ratio < 0.6:
            subject_visibility_bonus += 0.1
            
        # Optional: Verify contrast inside the subject rect
        if sx >= 0 and sy >= 0 and sx+sw <= dmd_frame.shape[1] and sy+sh <= dmd_frame.shape[0]:
            sub_grad = gradient_magnitude[sy:sy+sh, sx:sx+sw]
            if sub_grad.size > 0:
                sub_mean_grad = float(np.mean(sub_grad))
                if sub_mean_grad > mean_gradient * 1.2:
                    subject_visibility_bonus += 0.1

    return min(1.0, float(base_score + subject_visibility_bonus))


def _compute_scene_change_score(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    try:
        import cv2
        import numpy as np

        if frame_a is None or frame_b is None:
            return 1.0

        small_a = cv2.resize(frame_a, (64, 32), interpolation=cv2.INTER_AREA)
        small_b = cv2.resize(frame_b, (64, 32), interpolation=cv2.INTER_AREA)

        hsv_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2HSV)
        hsv_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2HSV)

        scores = []
        for ch in (0, 2):   # H, V
            hist_a = cv2.calcHist([hsv_a], [ch], None, [32], [0, 256])
            hist_b = cv2.calcHist([hsv_b], [ch], None, [32], [0, 256])
            cv2.normalize(hist_a, hist_a)
            cv2.normalize(hist_b, hist_b)
            corr = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
            scores.append(float(corr))

        # VNext Priority 3: Scene Change Detection v2
        gray_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_a, gray_b)
        mean_diff = float(np.mean(diff)) / 255.0
        struct_sim = max(0.0, 1.0 - mean_diff * 2.0)
        
        hist_sim = max(0.0, float(np.mean(scores)))

        return 0.5 * hist_sim + 0.5 * struct_sim
    except Exception:
        return 1.0

def _calculate_dmd_readability_score(dmd_frame: np.ndarray) -> float:
    # VNext Priority 9 — DMD Readability Predictor
    import cv2
    import numpy as np

    if dmd_frame is None or dmd_frame.size == 0:
        return 0.0

    gray_dmd = cv2.cvtColor(dmd_frame, cv2.COLOR_BGR2GRAY)
    
    # 1. Local Contrast (Standard Deviation)
    std_dev = float(np.std(gray_dmd))
    contrast_score = min(1.0, std_dev / 80.0) 
    
    # 2. Separation of shapes
    _, thresh = cv2.threshold(gray_dmd, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    
    if num_labels > 1:
        valid_shapes = sum(1 for stat in stats[1:] if stat[cv2.CC_STAT_AREA] > 5)
        if valid_shapes == 0:
            shape_score = 0.2
        elif valid_shapes < 5:
            shape_score = 1.0
        elif valid_shapes < 15:
            shape_score = 0.6
        else:
            shape_score = 0.3
    else:
        shape_score = 0.1
        
    readability_score = 0.6 * contrast_score + 0.4 * shape_score
    return min(1.0, readability_score)
