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
    signature: Optional[np.ndarray] = None

class AiMomentsEngine:
    def __init__(self, video_path: str, options: dict, progress_cb: Callable[[str, float], None]):
        self.video_path = video_path
        self.options = options
        self.progress_cb = progress_cb
        self._cancel = False
        
        # Initialize Scoring V2 components
        detector = None
        # Always try to load the detector for AI Moments, even if w_character is 0,
        # so we can PENALIZE frames with no subjects (like text/credits) if needed!
        try:
            from src.plugins.detectors.detector import _FrameDetector
            detector = _FrameDetector()
        except Exception as e:
            logger.warning(f"Failed to load detector: {e}")
            
        # Build dynamic strategy based on user checkboxes and sliders
        w_act = self.options.get("w_action", 70.0) / 100.0
        w_char = self.options.get("w_character", 40.0) / 100.0
        w_ep = self.options.get("w_epic", 100.0) / 100.0
        w_emo = self.options.get("w_emotion", 80.0) / 100.0
        w_dm = self.options.get("w_dmd", 100.0) / 100.0
        self._loop_weight = self.options.get("w_loopable", 70.0) / 100.0
        
        # Prepare Signal Engine
        use_optical_flow = w_act > 0.0 or w_ep > 0.0
        use_detector = detector if (w_char > 0.0 or w_emo > 0.0) else None
        self.signal_engine = SignalScoringEngine(detector=use_detector, optical_flow=use_optical_flow)

        from src.engine.scoring.final_scoring_engine import ScoringStrategy
        strategy = ScoringStrategy(
            name="ai_moments_dynamic",
            w_motion=0.8 * w_act,
            w_stability=0.2 * w_emo, # Emotion often implies stable/static closeups
            w_entropy=0.1,
            w_contrast=0.1 + 0.2 * w_ep, # Epic gets some contrast bonus
            w_edge_density=0.4 * w_dm if w_dm > 0 else 0.1,
            w_subject=0.8 * w_char + 0.4 * w_emo, # Emotion requires a subject
            w_subject_centering=0.5 * w_char + 0.8 * w_emo, # Emotion strongly prefers centered faces
            w_readability=0.6 * w_dm if w_dm > 0 else 0.0,
            w_attention=0.6 * w_ep + 0.2 * w_emo, # Epic = high attention areas
            w_saliency=0.4 * w_ep + 0.4 * w_emo,  # Epic = visual pop
            selection_threshold=20.0,
            penalize_dark_frames=True,
            penalize_no_detection=(w_char > 0.0 or w_emo > 0.0),
            no_detection_penalty=30.0 * max(w_char, w_emo),
        )
        self.final_engine = FinalScoringEngine(strategy)
        
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
            
        # Use FFmpegPipeReader with target_fps for massive performance boost
        from src.engine.auto_action.reader import FFmpegPipeReader
        reader = FFmpegPipeReader(self.video_path)
        ok, msg = reader.open(target_fps=analyze_fps)
        if not ok:
            logger.error(f"[AI MOMENT] Could not open video: {msg}")
            return []

        fps = reader.fps
        total_frames = reader.total_frames
        duration = total_frames / fps if fps > 0 else 0
        frame_step = 1 # We already requested target_fps from FFmpeg
        
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
        logger.info(f"[AI MOMENT] Signal Extraction started (Target FPS: {analyze_fps:.1f})")
        self.progress_cb("Signal Extraction", 0.0)
        
        signals = []
        idx = 0
        last_log_pct = 0.0
        while not self._cancel:
            ret, frame = reader.read()
            if not ret:
                break
            
            # Downscale for performance during analysis
            small = cv2.resize(frame, (320, 180))
            
            # Use Layer 1 pure measurement
            sig = self.signal_engine.score_frame(small, frame_idx=idx)
            
            # We store the time manually for moment creation
            sig_with_time = (sig, idx / fps)
            signals.append(sig_with_time)
                
            idx += 1
            if idx % int(fps) == 0:
                self.progress_cb("Signal Extraction", 0.4 * (idx / max(1, total_frames)))
                
            pct = (idx / max(1, total_frames)) * 100
            if pct - last_log_pct >= 5.0 or idx == total_frames:
                bar_len = 30
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "-" * (bar_len - filled)
                logger.info(f"[AI MOMENT] Signal Extraction: [{bar}] {pct:.1f}% ({idx}/{total_frames})")
                last_log_pct = pct
                
        reader.release()
        
        if not signals or self._cancel:
            logger.info("[AI MOMENT] Cancelled or no signals extracted.")
            return []
            
        logger.info(f"[AI MOMENT] Signal Extraction complete. Found {len(signals)} signal points.")
        self.progress_cb("Scoring Windows", 0.5)
        
        # 2. Score sliding windows
        moments = []
        step = max(1, int(analyze_fps * 1.0)) # 1 second slide
        
        total_windows = max(1, (len(signals) // step) * len(window_frames_list))
        windows_processed = 0

        logger.info(f"[AI MOMENT] Scoring {total_windows} sliding windows...")

        for start_i in range(0, len(signals), step):
            for wf in window_frames_list:
                end_i = start_i + wf
                if end_i > len(signals):
                    continue
                    
                window = signals[start_i:end_i]
                window_sigs = [s[0] for s in window]
                
                # Evaluate individual frames with Layer 2
                final_scores = self.final_engine.score_sequence(window_sigs)
                
                avg_frame_score = np.mean([fs.score for fs in final_scores])
                
                # Evaluate temporal sequence quality (Layer 3)
                report = self.quality_evaluator.evaluate_from_signals(window_sigs)
                
                # Combine scores
                temporal_bonus = (report.overall_temporal or 50.0) * (0.2 * self._loop_weight)
                overall = min(100.0, avg_frame_score + temporal_bonus)
                
                # Compute visual signature for scene similarity detection
                sig_features = []
                for s in window_sigs:
                    sig_features.append([
                        s.edge_density_score or 0.0,
                        s.contrast_score or 0.0,
                        s.subject_score or 0.0,
                        s.subject_centering_score or 0.0,
                        s.entropy_score or 0.0
                    ])
                signature = np.mean(sig_features, axis=0) if sig_features else np.zeros(5)
                
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
                    overall_score=overall,
                    signature=signature
                ))
                
                windows_processed += 1
                if windows_processed % 10 == 0:
                    self.progress_cb("Scoring Windows", 0.5 + 0.4 * (windows_processed / total_windows))

        logger.info(f"[AI MOMENT] Window scoring complete. Suppressing overlaps...")
        self.progress_cb("Ranking Moments", 0.95)
            
        # 3. Non-maximum suppression and Clustering Prevention
        moments.sort(key=lambda x: x.overall_score, reverse=True)
        final_results = []
        
        # Enforce a minimum separation between moments to prevent clustering.
        min_separation = 1.5  # seconds
        
        for r in moments:
            overlap = False
            for fr in final_results:
                # Distance between two intervals (negative means they overlap)
                dist = max(r.start_time, fr.start_time) - min(r.end_time, fr.end_time)
                
                # If they overlap, or are closer than the minimum separation, reject
                if dist < min_separation:
                    overlap = True
                    break
                    
                # Scene Similarity Check (prevent extracting the exact same static scene multiple times)
                if r.signature is not None and fr.signature is not None:
                    sim_dist = np.linalg.norm(r.signature - fr.signature)
                    if sim_dist < 0.05:  # Very tight threshold for exact same scene
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
        
        # 4. Print Scoreboard
        logger.info("\n" + "="*80)
        logger.info(f" 🎯 AI MOMENTS SCOREBOARD (Top {len(final_results)})")
        logger.info("="*80)
        logger.info(f"{'Time':<15} | {'Score':<8} | {'Frame Avg':<10} | {'Stability':<10} | {'Jitter':<8} | {'Cont.':<8}")
        logger.info("-" * 80)
        for i, r in enumerate(final_results, 1):
            t_str = f"[{r.start_time:.1f}s - {r.end_time:.1f}s]"
            logger.info(f"{t_str:<15} | {r.overall_score:>7.1f}% | {r.scores.get('Frame Avg', 0):>9.1f}% | {r.scores.get('Stability', 0):>9.1f}% | {r.scores.get('Jitter', 0):>7.1f}% | {r.scores.get('Continuity', 0):>7.1f}%")
        logger.info("="*80 + "\n")
        
        return final_results
