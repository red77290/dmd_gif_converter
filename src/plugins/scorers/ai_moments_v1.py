import os
import contextlib
import cv2
import numpy as np
import time
import logging
from dataclasses import dataclass
from typing import Callable, List, Dict, Any, Optional

# Suppress [mp3float @ ...] / Header missing messages before any VideoCapture
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

from src.engine.auto_action.reader import _quiet_c_stderr

logger = logging.getLogger(__name__)

@dataclass
class AiMoment:
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    scores: Dict[str, float]
    overall_score: float

class AiMomentsEngine:
    def __init__(self, video_path: str, options: dict, progress_cb: Callable[[str, float], None]):
        self.video_path = video_path
        self.options = options
        self.progress_cb = progress_cb
        self._cancel = False
        
        # Detector for Character feature
        self.detector = None
        if self.options.get("crit_character", False):
            try:
                from src.engine.auto_action.detector import DetectorFactory
                self.detector = DetectorFactory.create()
            except ImportError:
                logger.warning("YOLO detector not available, Character criteria will be skipped.")

    def cancel(self):
        self._cancel = True

    def run(self) -> List[AiMoment]:
        try:
            return self._run_analysis()
        except Exception as exc:
            logger.error(f"AiMomentsEngine failed: {exc}", exc_info=True)
            return []

    def _run_analysis(self) -> List[AiMoment]:
        with _quiet_c_stderr():
            cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.error("Could not open video.")
            return []

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        
        # Subsample for speed (configurable)
        analyze_fps = float(self.options.get("analyze_fps", 5.0))
        frame_step = max(1, int(fps / analyze_fps))
        
        # Determine sliding window sizes from min to max duration
        dur_min = float(self.options.get("dur_min", 2.0))
        dur_max = float(self.options.get("dur_max", 5.0))
        if dur_min > dur_max:
            dur_min, dur_max = dur_max, dur_min
            
        # Evaluate multiple window durations between min and max (step 0.5s)
        window_durations = np.arange(dur_min, dur_max + 0.1, 0.5).tolist()
        if not window_durations:
            window_durations = [dur_min]
            
        window_frames_list = [max(1, int(wd * analyze_fps)) for wd in window_durations]
        
        # Extract features frame by frame
        # We will collect metrics for each analyzed frame
        metrics = []
        
        # Progress mapping
        # 0-50% : Reading & frame-level extraction
        # 50-70% : Window aggregation (Motion, Subject)
        # 70-90% : DMD Simulation / Loopable
        # 90-100% : Ranking
        
        self.progress_cb("Scene Detection", 0.0)
        
        prev_gray = None
        prev_hist = None
        
        # Read frames
        idx = 0
        while not self._cancel:
            ret, frame = cap.read()
            if not ret:
                break
            
            if idx % frame_step == 0:
                # Downscale for performance
                small = cv2.resize(frame, (320, 180))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                
                # 1. Action (Optical Flow)
                flow_mag = 0.0
                if prev_gray is not None and self.options.get("crit_action", False):
                    # Simplified motion: absolute difference for speed, or Farneback
                    diff = cv2.absdiff(gray, prev_gray)
                    flow_mag = np.mean(diff)
                
                # 2. Epic (Brightness variance / Scene cut)
                epic_val = 0.0
                if prev_gray is not None and self.options.get("crit_epic", False):
                    hist = cv2.calcHist([gray], [0], None, [16], [0, 256])
                    if prev_hist is not None:
                        # Bhattacharyya distance for scene cut
                        epic_val = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                    prev_hist = hist
                else:
                    if self.options.get("crit_epic", False):
                        prev_hist = cv2.calcHist([gray], [0], None, [16], [0, 256])

                # 3. Character (YOLO boxes area)
                char_val = 0.0
                if self.detector is not None and self.options.get("crit_character", False):
                    # For performance, maybe run YOLO on even smaller frame or every N frames
                    try:
                        box = self.detector.detect_person(small, multi_fusion=True)
                        if box is not None:
                            char_val = (box.w * box.h) / (320 * 180) # normalize by frame area
                    except Exception:
                        pass
                        
                metrics.append({
                    "frame_idx": idx,
                    "time": idx / fps,
                    "action": flow_mag,
                    "epic": epic_val,
                    "char": char_val,
                    "gray_frame": gray # store for loop/dmd later
                })
                
                prev_gray = gray
                
            idx += 1
            if idx % (fps * 5) == 0:
                self.progress_cb("Scene Detection", 0.5 * (idx / total_frames))
                
        cap.release()
        
        if not metrics or self._cancel:
            return []
            
        self.progress_cb("Subject Detection", 0.5)
        self.progress_cb("Motion Analysis", 0.6)
        
        # Aggregate into sliding windows of varying durations
        moments = []
        step = max(1, int(analyze_fps * 1.0)) # 1 second slide
        
        for start_i in range(0, len(metrics), step):
            for wf in window_frames_list:
                end_i = start_i + wf
                if end_i > len(metrics):
                    continue
                    
                window = metrics[start_i:end_i]
                
                w_action = np.mean([m["action"] for m in window])
                w_epic = np.max([m["epic"] for m in window]) # Scene cut usually spikes
                w_char = np.mean([m["char"] for m in window])
                
                # 4. Loopable (MSE between first and last frame of window)
                w_loop = 0.0
                if self.options.get("crit_loopable", False):
                    f1 = window[0]["gray_frame"]
                    f2 = window[-1]["gray_frame"]
                    mse = np.mean((f1 - f2) ** 2)
                    # Lower MSE is better, invert it (max expected ~ 10000)
                    w_loop = max(0, 1.0 - (mse / 5000.0))
                    
                # 5. DMD (Contrast of the center area as a proxy for LED readability)
                w_dmd = 0.0
                if self.options.get("crit_dmd", False):
                    # Just sample middle frame
                    mid_frame = window[len(window)//2]["gray_frame"]
                    # high contrast -> std dev
                    w_dmd = np.std(mid_frame)
                    
                moments.append({
                    "start_idx": window[0]["frame_idx"],
                    "end_idx": window[-1]["frame_idx"],
                    "start_time": window[0]["time"],
                    "end_time": window[-1]["time"],
                    "action": w_action,
                    "epic": w_epic,
                    "char": w_char,
                    "loop": w_loop,
                    "dmd": w_dmd
                })
            
        self.progress_cb("DMD Analysis", 0.8)
            
        # Normalize and Rank
        if not moments:
            return []
            
        def normalize(key):
            vals = [m[key] for m in moments]
            mmin, mmax = min(vals), max(vals)
            if mmax > mmin:
                for m in moments:
                    m[key] = (m[key] - mmin) / (mmax - mmin) * 100.0
            else:
                for m in moments:
                    m[key] = 0.0
                    
        normalize("action")
        normalize("epic")
        normalize("char")
        normalize("loop") # loop is already 0-1 but we map to 0-100
        normalize("dmd")
        
        self.progress_cb("Ranking Moments", 0.9)
        
        # Apply weights based on Strategy
        w_act = self.options.get("w_action", 70)
        w_epi = self.options.get("w_epic", 100)
        w_cha = self.options.get("w_character", 40)
        w_loo = self.options.get("w_loopable", 70)
        w_dmd = self.options.get("w_dmd", 100)
        
        strategy = self.options.get("strategy", "Balanced")
        if strategy == "Maximum Action":
            w_act, w_epi, w_cha, w_loo, w_dmd = 100, 50, 0, 0, 20
        elif strategy == "Maximum DMD Visibility":
            w_act, w_epi, w_cha, w_loo, w_dmd = 20, 0, 50, 0, 100
        elif strategy == "Loop Priority":
            w_act, w_epi, w_cha, w_loo, w_dmd = 0, 0, 0, 100, 20
        elif strategy == "Custom":
            pass # keep provided
        else: # Balanced
            w_act, w_epi, w_cha, w_loo, w_dmd = 70, 70, 50, 50, 70

        # Create final AiMoment objects
        results = []
        for m in moments:
            overall = (
                m["action"] * w_act +
                m["epic"] * w_epi +
                m["char"] * w_cha +
                m["loop"] * w_loo +
                m["dmd"] * w_dmd
            ) / max(1, (w_act + w_epi + w_cha + w_loo + w_dmd))
            
            results.append(AiMoment(
                start_time=m["start_time"],
                end_time=m["end_time"],
                start_frame=m["start_idx"],
                end_frame=m["end_idx"],
                scores={
                    "Action": m["action"],
                    "Epic": m["epic"],
                    "Character": m["char"],
                    "Loopable": m["loop"],
                    "DMD Visibility": m["dmd"]
                },
                overall_score=overall
            ))
            
        # Non-maximum suppression (prevent overlapping moments)
        results.sort(key=lambda x: x.overall_score, reverse=True)
        final_results = []
        for r in results:
            overlap = False
            for fr in final_results:
                # if there is overlap of more than 1 second
                if not (r.end_time < fr.start_time + 1.0 or r.start_time > fr.end_time - 1.0):
                    overlap = True
                    break
            if not overlap:
                final_results.append(r)
                
        # Limit to requested amount
        count = int(self.options.get("moments_count", 10))
        final_results = final_results[:count]
        
        self.progress_cb("Ranking Moments", 1.0)
        return final_results
