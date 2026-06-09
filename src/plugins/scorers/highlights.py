import cv2
import logging
from typing import List, Tuple

from src.engine.config.auto_action_config import get_auto_action_config
from src.plugins.detectors.detector import DetectorFactory

logger = logging.getLogger(__name__)

def extract_highlights(
    video_path: str, 
    top_n: int = 5, 
    window_sec: float = 5.0, 
    sample_fps: float = 2.0
) -> List[Tuple[float, float]]:
    """
    Fast-pass scanner that extracts the Top N best non-overlapping highlight windows.
    
    Reads the video at `sample_fps`. For each frame, it uses the YOLO multi-box 
    detector to score the frame based on density (number of targets) and size.
    Then it slides a window of `window_sec` across the timeline to find the best 
    contiguous blocks of action.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video for highlights: {video_path}")
        return []

    # Get video properties
    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if orig_fps <= 0:
        orig_fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / orig_fps

    # If the video is shorter than the window, just return the whole thing as 1 highlight
    if duration_sec <= window_sec:
        cap.release()
        return [(0.0, duration_sec)]

    # Instantiate the detector with default config to ensure we get YOLO multi-box if available
    cfg = get_auto_action_config()
    detector = DetectorFactory.create(cfg)

    frame_scores = []
    frame_times = []

    frame_skip = max(1, int(orig_fps / sample_fps))
    
    logger.info(f"[CUTTER] Fast-scanning {video_path} (Dur: {duration_sec:.1f}s) at {sample_fps} FPS...")
    
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if idx % frame_skip == 0:
            current_sec = idx / orig_fps
            
            # Use multi-box detection to get all targets
            # Since detector doesn't expose multi directly in public API easily without
            # calling private methods, let's just use _detect_yolo_multi if it's available.
            score = 0.0
            if hasattr(detector, "_detect_yolo_multi"):
                boxes = detector._detect_yolo_multi(frame)
                if boxes:
                    # Score = number of targets + size bonus
                    # Larger boxes mean closer action
                    for b in boxes:
                        area = b.w * b.h
                        # Normalize area by frame size to get a 0-1 bonus
                        area_norm = area / (frame.shape[0] * frame.shape[1])
                        score += 1.0 + (area_norm * 5.0)
            else:
                # Fallback to single box fallback
                box = detector.detect_person(frame)
                if box:
                    area = box.w * box.h
                    area_norm = area / (frame.shape[0] * frame.shape[1])
                    score = 1.0 + (area_norm * 5.0)
                    
            frame_scores.append(score)
            frame_times.append(current_sec)
            
        idx += 1

    cap.release()
    
    if not frame_scores:
        return []

    # Now we have discrete frame scores. We want to find the best `window_sec` windows.
    # We can do this by moving a sliding window of size N over the frame_scores array.
    window_size_frames = int(window_sec * sample_fps)
    if window_size_frames < 1:
        window_size_frames = 1
        
    window_scores = []
    for i in range(len(frame_scores) - window_size_frames + 1):
        window_chunk = frame_scores[i:i + window_size_frames]
        w_score = sum(window_chunk)
        # Average time of the window
        start_time = frame_times[i]
        end_time = frame_times[i + window_size_frames - 1]
        # We store (score, start_time, end_time)
        # If end_time - start_time is less than window_sec, we pad it to exactly window_sec
        # so all output highlights are exactly window_sec long.
        if end_time - start_time < window_sec:
            end_time = min(duration_sec, start_time + window_sec)
            
        window_scores.append((w_score, start_time, end_time))
        
    # Sort windows by score descending
    window_scores.sort(key=lambda x: x[0], reverse=True)
    
    # Extract top N non-overlapping windows
    highlights = []
    for w in window_scores:
        score, start_time, end_time = w
        # Ignore windows with 0 score
        if score <= 0.1:
            continue
            
        # Check overlap
        overlap = False
        for h in highlights:
            h_start, h_end = h
            # If the two intervals intersect
            if not (end_time <= h_start or start_time >= h_end):
                overlap = True
                break
        
        if not overlap:
            highlights.append((start_time, end_time))
            if len(highlights) >= top_n:
                break
                
    # Sort chronologically
    highlights.sort(key=lambda x: x[0])
    
    logger.info(f"[CUTTER] Found {len(highlights)} highlights.")
    return highlights
