import os
import contextlib
import cv2
import numpy as np
import time
import logging
from dataclasses import dataclass
from typing import Callable, List, Dict, Any, Optional

from src.engine.auto_action.reader import _quiet_c_stderr
from src.engine.scoring.signal_scoring_engine import SignalScoringEngine
from src.engine.scoring.final_scoring_engine import FinalScoringEngine
from src.engine.scoring.quality_evaluator import QualityEvaluator

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
        
        # Initialize Scoring V2 components
        try:
            from src.plugins.detectors.detector import _FrameDetector
            detector = _FrameDetector()
        except Exception:
            detector = None
            
        use_optical_flow = self.options.get("crit_action", False)
        self.signal_engine = SignalScoringEngine(detector=detector, optical_flow=use_optical_flow)
        
        # Determine strategy from options (default: balanced_v2)
        strategy_name = self.options.get("scoring_strategy", "balanced_v2")
        self.final_engine = FinalScoringEngine(strategy_name)
        
        self.quality_evaluator = QualityEvaluator()

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
        if analyze_fps <= 0:
            analyze_fps = 5.0
        frame_step = max(1, int(fps / analyze_fps))
        
        # Determine sliding window sizes from min to max duration
        dur_min = float(self.options.get("dur_min", 2.0))
        dur_max = float(self.options.get("dur_max", 5.0))
        if dur_min > dur_max:
            dur_min, dur_max = dur_max, dur_min
            
        window_durations = np.arange(dur_min, dur_max + 0.1, 0.5).tolist()
        if not window_durations:
            window_durations = [dur_min]
            
        window_frames_list = [max(1, int(wd * analyze_fps)) for wd in window_durations]
        
        # 1. Extract Signals
        self.progress_cb("Signal Extraction", 0.0)
        
        signals = []
        idx = 0
        while not self._cancel:
            ret, frame = cap.read()
            if not ret:
                break
            
            if idx % frame_step == 0:
                # Downscale for performance during analysis
                small = cv2.resize(frame, (320, 180))
                
                # Use Layer 1 pure measurement
                sig = self.signal_engine.score_frame(small, frame_idx=idx)
                
                # We store the time manually for moment creation
                sig_with_time = (sig, idx / fps)
                signals.append(sig_with_time)
                
            idx += 1
            # Update progress every 1 second of video instead of every 5 seconds
            if idx % int(fps) == 0:
                self.progress_cb("Signal Extraction", 0.4 * (idx / total_frames))
                
        cap.release()
        
        if not signals or self._cancel:
            return []
            
        self.progress_cb("Scoring Windows", 0.5)
        
        # 2. Score sliding windows
        moments = []
        step = max(1, int(analyze_fps * 1.0)) # 1 second slide
        
        total_windows = (len(signals) // step) * len(window_frames_list)
        windows_processed = 0

        for start_i in range(0, len(signals), step):
            for wf in window_frames_list:
                end_i = start_i + wf
                if end_i > len(signals):
                    continue
                    
                window = signals[start_i:end_i]
                window_sigs = [s[0] for s in window]
                
                # Evaluate individual frames with Layer 2
                final_scores = self.final_engine.score_sequence(window_sigs)
                
                # Average the frame scores (ignoring dropped frames, or penalizing them)
                # If a frame is dropped (selected=False), its score is low anyway.
                avg_frame_score = np.mean([fs.score for fs in final_scores])
                
                # Evaluate temporal sequence quality (Layer 3)
                report = self.quality_evaluator.evaluate_from_signals(window_sigs)
                
                # Combine scores
                temporal_bonus = (report.overall_temporal or 50.0) * 0.2
                overall = min(100.0, avg_frame_score + temporal_bonus)
                
                moments.append(AiMoment(
                    start_time=window[0][1],
                    end_time=window[-1][1],
                    start_frame=window[0][0].frame_idx,
                    end_frame=window[-1][0].frame_idx,
                    scores={
                        "Frame Avg": avg_frame_score,
                        "Stability": report.temporal_stability or 0.0,
                        "Jitter": report.jitter_score or 0.0,
                        "Continuity": report.subject_continuity or 0.0,
                        "Temporal Bonus": temporal_bonus
                    },
                    overall_score=overall
                ))
                
                windows_processed += 1
                if windows_processed % 10 == 0:
                    self.progress_cb("Scoring Windows", 0.5 + 0.4 * (windows_processed / max(1, total_windows)))

        self.progress_cb("Ranking Moments", 0.95)
            
        # 3. Non-maximum suppression and Clustering Prevention
        moments.sort(key=lambda x: x.overall_score, reverse=True)
        final_results = []
        
        for r in moments:
            overlap = False
            for fr in final_results:
                # if there is overlap of more than 1 second
                if not (r.end_time < fr.start_time + 1.0 or r.start_time > fr.end_time - 1.0):
                    overlap = True
                    break
            if not overlap:
                final_results.append(r)
                
        # Limit to requested amount
        limit = int(self.options.get("count", 5))
        final_results = final_results[:limit]
        
        # Sort chronologically for display
        final_results.sort(key=lambda x: x.start_time)
        
        self.progress_cb("Done", 1.0)
        return final_results
