import cv2
import numpy as np
import os
import json

def evaluate_gif_quality(gif_path: str) -> dict:
    """
    Evaluates the quality of a converted DMD GIF.
    Returns a dict with score (0-100), rating, and reasons.
    """
    if not os.path.exists(gif_path):
        return _fallback_result("File not found")

    cap = cv2.VideoCapture(gif_path)
    if not cap.isOpened():
        return _fallback_result("Could not open GIF")

    scores = []
    reasons_set = set()
    
    # Evaluate up to 10 frames sampled evenly
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 10)
    step = max(1, total_frames // 10)
    
    for i in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ret, frame = cap.read()
        if not ret or frame is None:
            break
            
        score_info = _evaluate_dmd_frame(frame)
        scores.append(score_info["score"])
        for r in score_info["reasons"]:
            reasons_set.add(r)
            
    cap.release()
    
    if not scores:
        return _fallback_result("No readable frames")
        
    final_score = int(np.mean(scores) * 100.0)
    
    # Evaluate GIF duration and frame count to penalize unreadable/too fast GIFs
    try:
        from PIL import Image
        with Image.open(gif_path) as img:
            real_frames = getattr(img, "n_frames", 1)
            duration_ms = 0
            for i in range(real_frames):
                img.seek(i)
                duration_ms += img.info.get("duration", 100)
    except Exception:
        real_frames = total_frames
        duration_ms = real_frames * 100
        
    if real_frames <= 2:
        final_score = int(final_score * 0.2)
        reasons_set.add("Not enough frames")
    elif duration_ms < 400:
        final_score = int(final_score * 0.4)
        reasons_set.add("Animation too short/fast")

    final_score = max(0, min(100, final_score))
    
    rating, color = _get_rating(final_score)
    
    reasons = list(reasons_set)
    if not reasons:
        reasons.append("Average conversion")
        
    result = {
        "score": final_score,
        "rating": rating,
        "color": color,
        "reasons": reasons
    }
    
    # Save to sidecar
    _save_score_sidecar(gif_path, result)
    
    return result

def _evaluate_dmd_frame(dmd_frame: np.ndarray) -> dict:
    if dmd_frame is None or dmd_frame.size == 0:
        return {"score": 0.0, "reasons": ["Empty frame"]}

    gray_dmd = cv2.cvtColor(dmd_frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_dmd, 10, 255, cv2.THRESH_BINARY)
    
    total_pixels = dmd_frame.shape[0] * dmd_frame.shape[1]
    non_black_pixels = np.sum(thresh > 0)
    non_black_ratio = non_black_pixels / total_pixels if total_pixels > 0 else 0.0

    sobelx = cv2.Sobel(gray_dmd, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray_dmd, cv2.CV_64F, 0, 1, ksize=3)
    gradient_magnitude = np.sqrt(sobelx**2 + sobely**2)
    mean_gradient = np.mean(gradient_magnitude)

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

    reasons = []
    
    if non_black_ratio < 0.05:
        reasons.append("Screen mostly empty")
    elif non_black_ratio > 0.8:
        reasons.append("Screen too cluttered")
        
    occupancy = (h_occupation + v_occupation) / 2.0
    if occupancy > 0.7:
        reasons.append("Excellent occupancy")
    elif occupancy < 0.3:
        reasons.append("Poor DMD occupancy")
        
    if mean_gradient > 60:
        reasons.append("Strong contrast")
    elif mean_gradient < 20:
        reasons.append("Low contrast")

    w_non_black = 0.3
    w_contrast = 0.5
    w_occupation = 0.2

    # Ideal non-black ratio is around 0.3 to 0.5 (for pixel art)
    ratio_score = 1.0 - abs(non_black_ratio - 0.4) * 2.0
    ratio_score = max(0.0, ratio_score)

    base_score = (
        w_non_black * ratio_score +
        w_contrast * min(1.0, mean_gradient / 80.0) +
        w_occupation * occupancy
    )
    
    return {
        "score": base_score,
        "reasons": reasons
    }

def _get_rating(score: int) -> tuple:
    if score <= 30:
        return "Bad", "🔴"
    elif score <= 50:
        return "Poor", "🟠"
    elif score <= 70:
        return "Acceptable", "🟡"
    elif score <= 85:
        return "Good", "🟢"
    else:
        return "Excellent", "🌟"

def _fallback_result(reason: str) -> dict:
    return {
        "score": 0,
        "rating": "Unknown",
        "color": "⚪",
        "reasons": [reason]
    }

def _save_score_sidecar(gif_path: str, result: dict):
    sidecar_path = gif_path + ".scores.json"
    try:
        with open(sidecar_path, "w") as f:
            json.dump(result, f)
    except Exception:
        pass

def load_score_sidecar(gif_path: str) -> dict:
    sidecar_path = gif_path + ".scores.json"
    if os.path.exists(sidecar_path):
        try:
            with open(sidecar_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None
