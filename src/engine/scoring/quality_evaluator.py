"""
Quality Evaluator — Sequence-level quality assessment.

PURPOSE
-------
Evaluate complete generated output sequences, not individual frames.

This component addresses a gap in the existing quality system:
evaluate_gif_quality() (src/engine/conversion/quality.py) evaluates
frames independently and averages them. It cannot detect temporal
problems like jitter, subject discontinuity, or motion instability.

This evaluator adds temporal quality metrics that require observing
multiple frames in sequence.

OUTPUT
------
SequenceQualityReport — extends the existing score format with temporal fields.

BACKWARD COMPATIBILITY
----------------------
The existing evaluate_gif_quality() function is NOT modified.
This evaluator can be used alongside it:
  - Use evaluate_gif_quality() for post-conversion output scoring (existing)
  - Use QualityEvaluator for temporal sequence analysis (new)

The SequenceQualityReport dict output is a strict superset of the
existing evaluate_gif_quality() dict format.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output object
# ---------------------------------------------------------------------------

@dataclass
class SequenceQualityReport:
    """
    Temporal quality assessment of a complete frame sequence or GIF.

    All scores are in range [0.0, 100.0] unless stated otherwise.
    Higher = better quality.
    """

    # ── Temporal stability metrics ────────────────────────────────────────
    temporal_stability: Optional[float] = None
    """Mean stability across consecutive frames.
    High → smooth/stable animation. Low → jittery. Range [0, 100]."""

    jitter_score: Optional[float] = None
    """Inverse of frame-to-frame variance. High → no jitter. Range [0, 100].
    Complementary to temporal_stability."""

    motion_smoothness: Optional[float] = None
    """Consistency of motion magnitude over time.
    High → steady motion. Low → erratic speed changes. Range [0, 100]."""

    # ── Subject continuity ────────────────────────────────────────────────
    subject_continuity: Optional[float] = None
    """How consistently the detected subject appears across frames.
    100 = subject detected in every frame. 0 = subject never detected.
    Range [0, 100]."""

    subject_size_consistency: Optional[float] = None
    """Variance of subject ROI size over time.
    High score → stable framing. Low → erratic zooming. Range [0, 100]."""

    # ── Visual consistency ────────────────────────────────────────────────
    visual_consistency: Optional[float] = None
    """Mean structural similarity across consecutive frames.
    Penalizes sudden scene changes within a clip. Range [0, 100]."""

    contrast_consistency: Optional[float] = None
    """Consistency of contrast levels across the sequence.
    High → stable exposure. Low → flickering. Range [0, 100]."""

    # ── Overall ─────────────────────────────────────────────────────────
    overall_temporal: Optional[float] = None
    """Weighted combination of all temporal metrics. Range [0, 100]."""

    frame_count: int = 0
    """Number of frames analyzed."""

    observations: List[str] = field(default_factory=list)
    """Human-readable observations about the sequence quality."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class QualityEvaluator:
    """
    Evaluates the temporal quality of a frame sequence.

    Can be used on:
      - Raw frame sequences (List[np.ndarray])
      - Pre-scored signal sequences (List[FrameSignalScore]) — lighter weight

    Parameters
    ----------
    target_w : int
        Expected output width (used for SSIM normalization). Default: 128.
    target_h : int
        Expected output height. Default: 32.
    """

    def __init__(
        self,
        target_w: int = 128,
        target_h: int = 32,
    ) -> None:
        self._target_w = target_w
        self._target_h = target_h

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_frames(
        self,
        frames: List[np.ndarray],
        rois: Optional[List[Optional[Tuple[int, int, int, int]]]] = None,
    ) -> SequenceQualityReport:
        """
        Evaluate temporal quality from a list of BGR frames.

        Parameters
        ----------
        frames : List[np.ndarray]
            Sequence of frames in chronological order.
        rois : List[Optional[Tuple]], optional
            Per-frame detected ROI (x, y, w, h). Used for subject continuity.
            If None, subject continuity metrics are skipped.

        Returns
        -------
        SequenceQualityReport
        """
        if not frames:
            return SequenceQualityReport(observations=["No frames provided"])

        try:
            import cv2
        except ImportError:
            return SequenceQualityReport(
                frame_count=len(frames),
                observations=["OpenCV not available"],
            )

        report = SequenceQualityReport(frame_count=len(frames))

        # Convert frames to grayscale thumbnails for efficiency
        thumbnails = self._to_grayscale_thumbnails(frames, cv2)

        if rois is None:
            rois = [None] * len(frames)

        # ── Temporal stability and jitter ─────────────────────────────────
        if len(thumbnails) >= 2:
            report.temporal_stability, report.jitter_score = (
                self._compute_temporal_stability(thumbnails)
            )
            report.motion_smoothness = self._compute_motion_smoothness(thumbnails)
            report.visual_consistency = self._compute_visual_consistency(thumbnails, cv2)
            report.contrast_consistency = self._compute_contrast_consistency(thumbnails)

        # ── Subject continuity ────────────────────────────────────────────
        valid_rois = [r for r in rois if r is not None]
        if valid_rois:
            report.subject_continuity = (
                len(valid_rois) / len(frames) * 100.0
            )
            report.subject_size_consistency = self._compute_size_consistency(rois, frames)

        # ── Overall ──────────────────────────────────────────────────────
        report.overall_temporal = self._compose_overall(report)

        # ── Observations ──────────────────────────────────────────────────
        report.observations = self._generate_observations(report)

        return report

    def evaluate_from_signals(
        self,
        signals: "List[FrameSignalScore]",
    ) -> SequenceQualityReport:
        """
        Evaluate temporal quality from pre-computed FrameSignalScores.

        More efficient than evaluate_frames() when signals are already computed.

        Parameters
        ----------
        signals : List[FrameSignalScore]
            Signal scores from SignalScoringEngine.
        """
        from .signal_scoring_engine import FrameSignalScore

        if not signals:
            return SequenceQualityReport(observations=["No signals provided"])

        report = SequenceQualityReport(frame_count=len(signals))

        # ── Motion smoothness from motion_score ───────────────────────────
        motion_vals = [
            s.motion_score for s in signals
            if s.motion_score is not None
        ]
        if len(motion_vals) >= 2:
            motion_variance = float(np.var(motion_vals))
            # Low variance → smooth motion. Normalize: variance of 0.1 → score 50
            report.motion_smoothness = max(0.0, min(100.0, (1.0 - motion_variance * 10.0) * 100.0))

            mean_stability = float(np.mean([s.stability_score or 0.0 for s in signals]))
            report.temporal_stability = mean_stability * 100.0
            report.jitter_score = max(0.0, 100.0 - motion_variance * 500.0)

        # ── Contrast consistency from contrast_score ──────────────────────
        contrast_vals = [
            s.contrast_score for s in signals
            if s.contrast_score is not None
        ]
        if len(contrast_vals) >= 2:
            cv = float(np.std(contrast_vals)) / max(0.01, float(np.mean(contrast_vals)))
            report.contrast_consistency = max(0.0, min(100.0, (1.0 - cv) * 100.0))

        # ── Subject continuity from has_detection ─────────────────────────
        detection_rate = float(np.mean([float(s.has_detection) for s in signals]))
        report.subject_continuity = detection_rate * 100.0

        # ── Subject size consistency ───────────────────────────────────────
        size_vals = [
            s.subject_score for s in signals
            if s.subject_score is not None
        ]
        if len(size_vals) >= 2:
            size_cv = float(np.std(size_vals)) / max(0.01, float(np.mean(size_vals)))
            report.subject_size_consistency = max(0.0, min(100.0, (1.0 - size_cv) * 100.0))

        # ── Overall ──────────────────────────────────────────────────────
        report.overall_temporal = self._compose_overall(report)
        report.observations = self._generate_observations(report)

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _to_grayscale_thumbnails(
        self,
        frames: List[np.ndarray],
        cv2,
    ) -> List[np.ndarray]:
        """Resize all frames to target dimensions and convert to grayscale."""
        result = []
        for f in frames:
            if f is None or f.size == 0:
                result.append(np.zeros((self._target_h, self._target_w), dtype=np.uint8))
                continue
            try:
                small = cv2.resize(f, (self._target_w, self._target_h),
                                   interpolation=cv2.INTER_AREA)
                if len(small.shape) == 3:
                    small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                result.append(small)
            except Exception:
                result.append(np.zeros((self._target_h, self._target_w), dtype=np.uint8))
        return result

    @staticmethod
    def _compute_temporal_stability(
        thumbnails: List[np.ndarray],
    ) -> Tuple[float, float]:
        """
        Compute frame-to-frame stability and jitter.

        Returns (temporal_stability_score, jitter_score) in [0, 100].
        """
        diffs = []
        for i in range(1, len(thumbnails)):
            diff = float(np.mean(np.abs(thumbnails[i].astype(float) - thumbnails[i - 1].astype(float))))
            diffs.append(diff / 255.0)

        if not diffs:
            return 100.0, 100.0

        mean_diff = float(np.mean(diffs))
        var_diff = float(np.var(diffs))

        stability = max(0.0, min(100.0, (1.0 - mean_diff) * 100.0))
        jitter = max(0.0, min(100.0, (1.0 - var_diff * 10.0) * 100.0))

        return stability, jitter

    @staticmethod
    def _compute_motion_smoothness(thumbnails: List[np.ndarray]) -> float:
        """
        Consistency of motion speed over time.
        Low variance in per-frame motion = smooth motion.
        """
        diffs = []
        for i in range(1, len(thumbnails)):
            diff = float(np.mean(np.abs(
                thumbnails[i].astype(float) - thumbnails[i - 1].astype(float)
            ))) / 255.0
            diffs.append(diff)

        if len(diffs) < 2:
            return 100.0

        variance = float(np.var(diffs))
        return max(0.0, min(100.0, (1.0 - variance * 20.0) * 100.0))

    @staticmethod
    def _compute_visual_consistency(thumbnails: List[np.ndarray], cv2) -> float:
        """
        Structural similarity between consecutive frames.
        Penalizes abrupt scene changes within the clip.
        """
        similarities = []
        for i in range(1, len(thumbnails)):
            a = thumbnails[i - 1].astype(float)
            b = thumbnails[i].astype(float)
            mu_a, mu_b = np.mean(a), np.mean(b)
            sig_a, sig_b = np.std(a), np.std(b)
            cov = np.mean((a - mu_a) * (b - mu_b))
            # Simple SSIM-like measure without full SSIM complexity
            c1, c2 = 6.5025, 58.5225
            num = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
            den = (mu_a ** 2 + mu_b ** 2 + c1) * (sig_a ** 2 + sig_b ** 2 + c2)
            sim = float(num / max(den, 1e-10))
            similarities.append(max(0.0, min(1.0, sim)))

        if not similarities:
            return 100.0

        return float(np.mean(similarities)) * 100.0

    @staticmethod
    def _compute_contrast_consistency(thumbnails: List[np.ndarray]) -> float:
        """Consistency of contrast (std dev) across frames."""
        stds = [float(np.std(t)) for t in thumbnails]
        if len(stds) < 2:
            return 100.0
        cv = float(np.std(stds)) / max(1.0, float(np.mean(stds)))
        return max(0.0, min(100.0, (1.0 - cv) * 100.0))

    @staticmethod
    def _compute_size_consistency(
        rois: List[Optional[Tuple[int, int, int, int]]],
        frames: List[np.ndarray],
    ) -> float:
        """Consistency of subject ROI size (normalized by frame area)."""
        norm_sizes = []
        for roi, frame in zip(rois, frames):
            if roi is None or frame is None or frame.size == 0:
                continue
            _, _, w, h = roi
            frame_area = frame.shape[0] * frame.shape[1]
            if frame_area > 0:
                norm_sizes.append(w * h / frame_area)

        if len(norm_sizes) < 2:
            return 100.0

        cv = float(np.std(norm_sizes)) / max(0.001, float(np.mean(norm_sizes)))
        return max(0.0, min(100.0, (1.0 - cv) * 100.0))

    @staticmethod
    def _compose_overall(report: SequenceQualityReport) -> float:
        """Weighted combination of temporal metrics → overall score [0, 100]."""
        pairs = [
            (report.temporal_stability, 1.0),
            (report.jitter_score, 0.8),
            (report.motion_smoothness, 0.7),
            (report.visual_consistency, 0.6),
            (report.contrast_consistency, 0.5),
            (report.subject_continuity, 0.4),
            (report.subject_size_consistency, 0.4),
        ]
        total_w = 0.0
        total_s = 0.0
        for value, weight in pairs:
            if value is not None:
                total_s += value * weight
                total_w += weight
        if total_w == 0.0:
            return 0.0
        return min(100.0, total_s / total_w)

    @staticmethod
    def _generate_observations(report: SequenceQualityReport) -> List[str]:
        """Pure observations — no decisions."""
        obs = []
        if report.temporal_stability is not None and report.temporal_stability < 40:
            obs.append("High instability between frames (lots of motion)")
        if report.jitter_score is not None and report.jitter_score < 40:
            obs.append("Significant jitter detected in sequence")
        if report.motion_smoothness is not None and report.motion_smoothness < 40:
            obs.append("Erratic motion speed changes (uneven pacing)")
        if report.subject_continuity is not None and report.subject_continuity < 50:
            obs.append("Subject not consistently detected across sequence")
        if report.visual_consistency is not None and report.visual_consistency < 50:
            obs.append("Scene cuts or sudden changes detected within clip")
        if report.contrast_consistency is not None and report.contrast_consistency < 50:
            obs.append("Contrast/exposure flickering detected")
        if report.overall_temporal is not None:
            if report.overall_temporal > 75:
                obs.append("Sequence has good temporal quality")
            elif report.overall_temporal < 30:
                obs.append("Sequence has poor temporal quality")
        return obs
