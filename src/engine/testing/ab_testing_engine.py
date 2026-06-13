"""
A/B Testing Engine — Compare multiple scoring strategies on the same video.

PURPOSE
-------
Run multiple FinalScoringEngine strategies on identical input and measure
the outcomes objectively. This enables data-driven strategy selection and
makes scoring experiments reproducible.

DESIGN PRINCIPLES
-----------------
1. Each strategy runs in complete isolation — no shared mutable state.
2. The video is decoded once; the same frame signals are fed to all strategies.
3. The pipeline (detection, signal extraction) is identical across strategies.
   ONLY the scoring strategy configuration differs.
4. Results are fully serializable (JSON-friendly dataclasses).
5. Thread-safe by design: each strategy has its own FinalScoringEngine instance.

INTEGRATION
-----------
Purely additive. Does NOT modify any existing pipeline, converter, or UI code.
Normal conversion must remain efficient — A/B testing is explicitly an
opt-in, slower operation.

STRATEGIES AVAILABLE
--------------------
All BUILTIN_STRATEGIES from final_scoring_engine are available by name,
plus any custom ScoringStrategy instance you provide.

Default strategies:
  baseline_v1          — mirrors existing evaluate_gif_quality() behavior
  motion_heavy         — prioritizes action frames
  subject_priority     — maximizes subject size/centering
  face_priority        — extreme centering (close-up shots)
  stability_priority   — favors stable/static frames
  readability_priority — maximizes DMD readability prediction
  balanced_v2          — recommended default

USAGE EXAMPLE
-------------
    engine = ABTestingEngine(video_path="my_video.mp4")
    report = engine.run(strategy_names=["baseline_v1", "balanced_v2", "motion_heavy"])
    report.export_json("ab_results.json")
    winner = report.best_strategy
    print(f"Winner: {winner} (readability={report.results[winner].avg_readability:.1f})")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import numpy as np

from ..scoring.signal_scoring_engine import SignalScoringEngine, FrameSignalScore
from ..scoring.final_scoring_engine import (
    FinalScoringEngine, FinalScore, ScoringStrategy, BUILTIN_STRATEGIES
)
from ..scoring.dmd_readability_engine import DmdReadabilityEngine
from ..scoring.quality_evaluator import QualityEvaluator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output objects
# ---------------------------------------------------------------------------

@dataclass
class ABTestResult:
    """
    Result of running one scoring strategy on a video.

    All scores are in [0.0, 100.0].
    """
    strategy_name: str

    # Selection summary
    total_frames: int = 0
    selected_frames: int = 0
    selection_rate: float = 0.0

    # Score distribution
    avg_score: float = 0.0
    """Mean FinalScore across all selected frames."""

    score_p25: float = 0.0
    score_p50: float = 0.0
    score_p75: float = 0.0

    # Quality metrics
    avg_readability: float = 0.0
    """Mean DmdReadabilityEngine.overall across all frames."""

    temporal_stability: float = 0.0
    """From QualityEvaluator.evaluate_from_signals()."""

    jitter_score: float = 0.0
    motion_smoothness: float = 0.0
    subject_continuity: float = 0.0

    # Top frame indices (by FinalScore.score)
    top_frame_indices: List[int] = field(default_factory=list)
    """Indices of the top 10 selected frames, sorted by descending score."""

    # Timing
    elapsed_seconds: float = 0.0
    """Time taken to score all frames with this strategy."""


@dataclass
class ABTestReport:
    """
    Complete A/B test report for all strategies run on a single video.
    """
    video_path: str = ""
    total_frames_analyzed: int = 0
    strategies_run: List[str] = field(default_factory=list)

    results: Dict[str, ABTestResult] = field(default_factory=dict)
    """Strategy name → ABTestResult."""

    best_strategy: Optional[str] = None
    """Name of the strategy with the highest composite quality score."""

    composite_scores: Dict[str, float] = field(default_factory=dict)
    """Strategy name → composite quality score (for ranking)."""

    elapsed_total: float = 0.0
    """Total elapsed time for all strategies."""

    def export_json(self, path: str) -> None:
        """Serialize the report to a JSON file."""
        try:
            def _to_dict(obj):
                if isinstance(obj, ABTestResult):
                    return {
                        "strategy_name": obj.strategy_name,
                        "total_frames": obj.total_frames,
                        "selected_frames": obj.selected_frames,
                        "selection_rate": round(obj.selection_rate, 4),
                        "avg_score": round(obj.avg_score, 2),
                        "score_p25": round(obj.score_p25, 2),
                        "score_p50": round(obj.score_p50, 2),
                        "score_p75": round(obj.score_p75, 2),
                        "avg_readability": round(obj.avg_readability, 2),
                        "temporal_stability": round(obj.temporal_stability, 2),
                        "jitter_score": round(obj.jitter_score, 2),
                        "motion_smoothness": round(obj.motion_smoothness, 2),
                        "subject_continuity": round(obj.subject_continuity, 2),
                        "top_frame_indices": obj.top_frame_indices,
                        "elapsed_seconds": round(obj.elapsed_seconds, 3),
                    }
                return obj

            data = {
                "video_path": self.video_path,
                "total_frames_analyzed": self.total_frames_analyzed,
                "strategies_run": self.strategies_run,
                "best_strategy": self.best_strategy,
                "composite_scores": {k: round(v, 2) for k, v in self.composite_scores.items()},
                "elapsed_total": round(self.elapsed_total, 3),
                "results": {
                    name: _to_dict(result)
                    for name, result in self.results.items()
                },
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("ABTestReport saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export ABTestReport: %s", exc)

    def print_leaderboard(self) -> None:
        """Log a human-readable leaderboard to the logger."""
        logger.info("=" * 60)
        logger.info("A/B TEST LEADERBOARD — %s", self.video_path)
        logger.info("=" * 60)
        ranked = sorted(
            self.composite_scores.items(), key=lambda x: x[1], reverse=True
        )
        for rank, (name, score) in enumerate(ranked, 1):
            r = self.results.get(name)
            marker = " ← WINNER" if name == self.best_strategy else ""
            logger.info(
                "%d. %-25s composite=%.1f | readability=%.1f | stability=%.1f | "
                "selection=%.0f%%%s",
                rank, name, score,
                r.avg_readability if r else 0.0,
                r.temporal_stability if r else 0.0,
                r.selection_rate * 100 if r else 0.0,
                marker,
            )
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ABTestingEngine:
    """
    Runs multiple scoring strategies on the same video and compares outcomes.

    The engine performs a single pass through the video to extract signals,
    then runs each strategy on those cached signals — ensuring fair comparison.

    Parameters
    ----------
    video_path : str
        Path to the source video file.
    sample_fps : float
        Frames per second to analyze (subsampling). Default: 5.0.
        Higher = more accurate but slower. Full-rate = use 0.
    target_w : int
        DMD target width for readability simulation. Default: 128.
    target_h : int
        DMD target height. Default: 32.
    detector : IDetector, optional
        Detector for subject signals. If None, subject signals are None.
    use_optical_flow : bool
        Enable optical flow computation (slower). Default: False.
    """

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy_names: Optional[List[str]] = None,
        custom_strategies: Optional[List[ScoringStrategy]] = None,
    ) -> ABTestReport:
        """
        Run A/B testing for the specified strategies.

        Parameters
        ----------
        strategy_names : List[str], optional
            Names of built-in strategies to test. If None, all built-in
            strategies are tested.
        custom_strategies : List[ScoringStrategy], optional
            Additional custom strategies to include.

        Returns
        -------
        ABTestReport
            Complete comparison report.
        """
        t_start = time.monotonic()

        # ── Resolve strategies ────────────────────────────────────────────
        strategies: Dict[str, ScoringStrategy] = {}

        if strategy_names is None:
            strategies.update(BUILTIN_STRATEGIES)
        else:
            for name in strategy_names:
                if name not in BUILTIN_STRATEGIES:
                    logger.warning("Unknown strategy '%s' — skipping.", name)
                    continue
                strategies[name] = BUILTIN_STRATEGIES[name]

        if custom_strategies:
            for cs in custom_strategies:
                strategies[cs.name] = cs

        if not strategies:
            logger.error("No valid strategies to test.")
            return ABTestReport(
                video_path=self._video_path,
                strategies_run=[],
            )

        # ── Step 1: Extract signals (single pass, shared across strategies) ─
        logger.info(
            "ABTestingEngine: Extracting signals from '%s' at %.1f FPS...",
            self._video_path, self._sample_fps
        )
        signals, readability_scores, frame_rois = self._extract_signals()

        if not signals:
            logger.error("No signals extracted from video '%s'.", self._video_path)
            return ABTestReport(
                video_path=self._video_path,
                strategies_run=list(strategies.keys()),
            )

        logger.info("ABTestingEngine: %d frames analyzed. Running %d strategies...",
                    len(signals), len(strategies))

        # ── Step 2: Run each strategy on cached signals ───────────────────
        results: Dict[str, ABTestResult] = {}
        for name, strategy_cfg in strategies.items():
            result = self._run_strategy(
                name, strategy_cfg, signals, readability_scores
            )
            results[name] = result
            logger.info(
                "  [%s] composite=%.1f readability=%.1f stability=%.1f sel=%.0f%%",
                name,
                self._composite_score(result),
                result.avg_readability,
                result.temporal_stability,
                result.selection_rate * 100,
            )

        # ── Step 3: Compose report ────────────────────────────────────────
        composite_scores = {name: self._composite_score(r) for name, r in results.items()}
        best = max(composite_scores, key=lambda k: composite_scores[k]) if composite_scores else None

        report = ABTestReport(
            video_path=self._video_path,
            total_frames_analyzed=len(signals),
            strategies_run=list(strategies.keys()),
            results=results,
            best_strategy=best,
            composite_scores=composite_scores,
            elapsed_total=time.monotonic() - t_start,
        )

        report.print_leaderboard()
        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_signals(self):
        """
        Decode the video and extract signals for all frames.

        Returns (signals, readability_scores, rois).
        signals            : List[FrameSignalScore]
        readability_scores : List[float]  (overall readability per frame)
        rois               : List[Optional[BoundingBox]]
        """
        try:
            import cv2
        except ImportError:
            logger.error("OpenCV not available — cannot extract signals.")
            return [], [], []

        signals: List[FrameSignalScore] = []
        readability_scores: List[float] = []
        rois = []

        try:
            cap = cv2.VideoCapture(self._video_path)
        except Exception as exc:
            logger.error("Cannot open video: %s", exc)
            return [], [], []

        if not cap.isOpened():
            logger.error("VideoCapture could not open '%s'.", self._video_path)
            return [], [], []

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

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

                # Readability — simulate DMD conversion
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
        """
        Apply a single strategy to the cached signals and return ABTestResult.
        Thread-safe: creates a new FinalScoringEngine instance per strategy.
        """
        t_start = time.monotonic()

        # Create isolated engine — ZERO shared state
        final_engine = FinalScoringEngine(strategy=strategy_cfg)
        final_scores: List[FinalScore] = final_engine.score_sequence(signals)

        total = len(final_scores)
        selected = [fs for fs in final_scores if fs.selected]
        n_selected = len(selected)

        # Score distribution
        if selected:
            score_vals = [fs.score for fs in selected]
            avg_score = float(np.mean(score_vals))
            p25 = float(np.percentile(score_vals, 25))
            p50 = float(np.percentile(score_vals, 50))
            p75 = float(np.percentile(score_vals, 75))
        else:
            avg_score = p25 = p50 = p75 = 0.0

        # Readability average across all frames
        avg_readability = float(np.mean(readability_scores)) if readability_scores else 0.0

        # Temporal quality from signals
        temporal_report = self._quality_evaluator.evaluate_from_signals(signals)

        # Top selected frames by score
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
        """
        Weighted composite quality score for strategy ranking.

        Weights:
          - avg_readability (40%) — DMD-specific quality
          - temporal_stability (25%) — smooth output
          - avg_score (20%) — raw scoring performance
          - jitter_score (15%) — absence of visual noise
        """
        return (
            result.avg_readability * 0.40
            + result.temporal_stability * 0.25
            + result.avg_score * 0.20
            + result.jitter_score * 0.15
        )
