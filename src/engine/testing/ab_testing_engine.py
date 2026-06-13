"""
A/B Testing Engine — Compare multiple scoring strategies on the same video.
Augmented with FULL integration of AutoAction, DmdGifConverter, and AiMoments.
"""

from __future__ import annotations

import os
import json
import logging
import time
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import numpy as np

from ..scoring.signal_scoring_engine import SignalScoringEngine, FrameSignalScore
from ..scoring.final_scoring_engine import (
    FinalScoringEngine, FinalScore, ScoringStrategy, BUILTIN_STRATEGIES
)
from ..scoring.dmd_readability_engine import DmdReadabilityEngine
from ..scoring.quality_evaluator import QualityEvaluator
from ..auto_action.pipeline import preprocess_video_for_dmd
from ..auto_action import AutoActionConfig
from ..conversion.core import process_file
from ..conversion.quality import evaluate_gif_quality
from src.plugins.scorers.ai_moments_v1 import AiMomentsEngine as AiMomentsEngineV1
from src.plugins.scorers.ai_moments import AiMomentsEngine as AiMomentsEngineV2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output objects
# ---------------------------------------------------------------------------

@dataclass
class ABTestResult:
    strategy_name: str
    total_frames: int = 0
    selected_frames: int = 0
    selection_rate: float = 0.0
    avg_score: float = 0.0
    score_p25: float = 0.0
    score_p50: float = 0.0
    score_p75: float = 0.0
    avg_readability: float = 0.0
    temporal_stability: float = 0.0
    jitter_score: float = 0.0
    motion_smoothness: float = 0.0
    subject_continuity: float = 0.0
    top_frame_indices: List[int] = field(default_factory=list)
    elapsed_seconds: float = 0.0

@dataclass
class ABTestReport:
    video_path: str = ""
    total_frames_analyzed: int = 0
    v1_gif_score: float = 0.0
    v1_gif_reasons: List[str] = field(default_factory=list)
    strategies_run: List[str] = field(default_factory=list)
    results: Dict[str, ABTestResult] = field(default_factory=dict)
    best_strategy: Optional[str] = None
    composite_scores: Dict[str, float] = field(default_factory=dict)
    elapsed_total: float = 0.0

    def print_leaderboard(self) -> None:
        logger.info("=" * 60)
        logger.info("A/B TEST LEADERBOARD — %s", self.video_path)
        logger.info("V1 BASELINE SCORE (GIF): %.1f/100", self.v1_gif_score)
        logger.info("=" * 60)
        ranked = sorted(self.composite_scores.items(), key=lambda x: x[1], reverse=True)
        for rank, (name, score) in enumerate(ranked, 1):
            r = self.results.get(name)
            v1_diff = r.avg_score - self.v1_gif_score if r else 0.0
            marker = " ← WINNER" if name == self.best_strategy else ""
            logger.info(
                "%d. %-20s V2_AVG=%.1f (Diff=%.1f) | readability=%.1f | stability=%.1f %s",
                rank, name,
                r.avg_score if r else 0.0,
                v1_diff,
                r.avg_readability if r else 0.0,
                r.temporal_stability if r else 0.0,
                marker,
            )
        logger.info("=" * 60)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ABTestingEngine:
    def __init__(
        self,
        video_path: str,
        sample_fps: float = 5.0,
        target_w: int = 128,
        target_h: int = 32,
        detector=None,
        use_optical_flow: bool = False,
    ) -> None:
        self._video_path = video_path
        self._sample_fps = sample_fps
        self._target_w = target_w
        self._target_h = target_h
        self._detector = detector
        self._use_optical_flow = use_optical_flow

        self._signal_engine = SignalScoringEngine(
            detector=detector,
            optical_flow=use_optical_flow,
        )
        self._readability_engine = DmdReadabilityEngine(target_w, target_h)
        self._quality_evaluator = QualityEvaluator(target_w, target_h)

    def run_conversion_ab_test(
        self,
        strategy_names: Optional[List[str]] = None,
        params: Optional[Dict] = None,
    ) -> ABTestReport:
        """
        Runs exhaustive comparison:
        1. AutoAction Preprocessing (zoom, crop, scene)
        2. V1 Conversion + evaluate_gif_quality
        3. V2 Signal + FinalScoringEngine on the preprocessed frames.
        """
        t_start = time.monotonic()
        params = params or {"let_me_handle_it": True, "auto_action_enabled": True}
        
        logger.info("=== STARTING EXHAUSTIVE A/B TEST: %s ===", self._video_path)
        
        # 1. Preprocess Video (AutoAction)
        logger.info("Step 1/3: Running AutoAction Preprocessing...")
        cfg = AutoActionConfig.from_params(params)
        ok_pre, pre_src, pre_msg = preprocess_video_for_dmd(self._video_path, cfg)
        
        if not ok_pre or not pre_src:
            logger.error("AutoAction failed: %s", pre_msg)
            return ABTestReport(video_path=self._video_path)

        # 2. V1 Conversion & Scoring
        logger.info("Step 2/3: Generating V1 GIF and extracting V1 Score...")
        out_gif = pre_src + "_v1.gif"
        p_no_action = {**params, "auto_action_enabled": False} # Already preprocessed
        ok_conv, conv_msg = process_file(pre_src, out_gif, params=p_no_action)
        
        v1_score = 0.0
        v1_reasons = []
        if ok_conv and os.path.exists(out_gif):
            q_result = evaluate_gif_quality(out_gif)
            v1_score = q_result["score"]
            v1_reasons = q_result.get("reasons", [])
            logger.info("=> V1 GIF Score: %.1f/100", v1_score)
        else:
            logger.warning("Conversion failed: %s", conv_msg)

        # 3. V2 Analysis on the preprocessed source
        logger.info("Step 3/3: Running V2 Strategy Engines on cropped frames...")
        # Temporarily redirect video_path to the preprocessed file
        original_video = self._video_path
        self._video_path = pre_src
        
        strategies: Dict[str, ScoringStrategy] = {}
        if strategy_names is None:
            strategies.update(BUILTIN_STRATEGIES)
        else:
            for name in strategy_names:
                if name in BUILTIN_STRATEGIES:
                    strategies[name] = BUILTIN_STRATEGIES[name]

        signals, readability_scores, frame_rois = self._extract_signals()
        
        results: Dict[str, ABTestResult] = {}
        for name, strategy_cfg in strategies.items():
            result = self._run_strategy(name, strategy_cfg, signals, readability_scores)
            results[name] = result

        composite_scores = {name: self._composite_score(r) for name, r in results.items()}
        best = max(composite_scores, key=lambda k: composite_scores[k]) if composite_scores else None

        # Clean up temporary files
        try:
            if os.path.exists(out_gif):
                os.remove(out_gif)
            temp_dir = os.path.dirname(pre_src)
            if os.path.isdir(temp_dir) and "dmd_temp" in temp_dir.lower():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        self._video_path = original_video # restore

        report = ABTestReport(
            video_path=self._video_path,
            total_frames_analyzed=len(signals),
            v1_gif_score=v1_score,
            v1_gif_reasons=v1_reasons,
            strategies_run=list(strategies.keys()),
            results=results,
            best_strategy=best,
            composite_scores=composite_scores,
            elapsed_total=time.monotonic() - t_start,
        )
        report.print_leaderboard()
        return report

    def run_ai_moments_ab_test(self, options: dict) -> None:
        """
        Runs exhaustive comparison of AiMoments V1 vs V2.
        """
        logger.info("=== COMPARE AI MOMENTS (V1 vs V2) ===")
        logger.info("Video: %s", self._video_path)
        
        def progress(task, pct): pass
        
        # V1
        logger.info("Extracting V1 Moments...")
        engine_v1 = AiMomentsEngineV1(self._video_path, options, progress)
        res_v1 = engine_v1.run()
        
        # V2
        logger.info("Extracting V2 Moments...")
        engine_v2 = AiMomentsEngineV2(self._video_path, options, progress)
        res_v2 = engine_v2.run()
        
        logger.info("--------------------------------------------------")
        logger.info("V1 Extracted: %d moments", len(res_v1))
        for i, m in enumerate(res_v1):
            logger.info("  V1 M%d: [%.1fs - %.1fs] Score: %.1f", i+1, m.start_time, m.end_time, m.overall_score)
            
        logger.info("--------------------------------------------------")
        logger.info("V2 Extracted: %d moments", len(res_v2))
        for i, m in enumerate(res_v2):
            logger.info("  V2 M%d: [%.1fs - %.1fs] Score: %.1f", i+1, m.start_time, m.end_time, m.overall_score)
            
        logger.info("--------------------------------------------------")
        # Compute match percentage
        matches = 0
        for m1 in res_v1:
            for m2 in res_v2:
                if abs(m1.start_time - m2.start_time) < 1.0 and abs(m1.end_time - m2.end_time) < 1.0:
                    matches += 1
                    break
        
        logger.info("Moments Matching V1 vs V2 (±1.0s overlap): %d / %d", matches, len(res_v1))
        logger.info("==================================================")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_signals(self):
        try:
            import cv2
        except ImportError:
            return [], [], []

        signals: List[FrameSignalScore] = []
        readability_scores: List[float] = []
        rois = []

        try:
            cap = cv2.VideoCapture(self._video_path)
        except Exception:
            return [], [], []

        if not cap.isOpened():
            return [], [], []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if self._sample_fps <= 0 or self._sample_fps >= fps:
            frame_step = 1
        else:
            frame_step = max(1, int(fps / self._sample_fps))

        self._signal_engine.reset()
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_step == 0:
                signal = self._signal_engine.score_frame(frame, frame_idx=frame_idx)
                signals.append(signal)
                roi = signal.roi
                r_score = self._readability_engine.evaluate(frame, roi=roi)
                readability_scores.append(r_score.overall)
                rois.append(roi)

            frame_idx += 1

        cap.release()
        return signals, readability_scores, rois

    def _run_strategy(
        self,
        name: str,
        strategy_cfg: ScoringStrategy,
        signals: List[FrameSignalScore],
        readability_scores: List[float],
    ) -> ABTestResult:
        t_start = time.monotonic()
        final_engine = FinalScoringEngine(strategy=strategy_cfg)
        final_scores: List[FinalScore] = final_engine.score_sequence(signals)

        total = len(final_scores)
        selected = [fs for fs in final_scores if fs.selected]
        n_selected = len(selected)

        if selected:
            score_vals = [fs.score for fs in selected]
            avg_score = float(np.mean(score_vals))
            p25 = float(np.percentile(score_vals, 25))
            p50 = float(np.percentile(score_vals, 50))
            p75 = float(np.percentile(score_vals, 75))
        else:
            avg_score = p25 = p50 = p75 = 0.0

        avg_readability = float(np.mean(readability_scores)) if readability_scores else 0.0
        temporal_report = self._quality_evaluator.evaluate_from_signals(signals)

        sorted_selected = sorted(
            [(fs.score, fs.signal.frame_idx if fs.signal else -1) for fs in selected],
            reverse=True,
        )
        top_indices = [idx for _, idx in sorted_selected[:10]]

        return ABTestResult(
            strategy_name=name,
            total_frames=total,
            selected_frames=n_selected,
            selection_rate=n_selected / max(1, total),
            avg_score=avg_score,
            score_p25=p25,
            score_p50=p50,
            score_p75=p75,
            avg_readability=avg_readability,
            temporal_stability=temporal_report.temporal_stability or 0.0,
            jitter_score=temporal_report.jitter_score or 0.0,
            motion_smoothness=temporal_report.motion_smoothness or 0.0,
            subject_continuity=temporal_report.subject_continuity or 0.0,
            top_frame_indices=top_indices,
            elapsed_seconds=time.monotonic() - t_start,
        )

    @staticmethod
    def _composite_score(result: ABTestResult) -> float:
        return (
            result.avg_readability * 0.40
            + result.temporal_stability * 0.25
            + result.avg_score * 0.20
            + result.jitter_score * 0.15
        )
