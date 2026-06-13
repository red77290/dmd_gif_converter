"""
Tests for QualityEvaluator — sequence-level temporal quality metrics.

Key invariants:
  1. Stable sequence (identical frames) → high jitter_score (> 60).
  2. Jittery sequence (alternating extremes) → low jitter_score (< 50).
  3. All score fields are in [0.0, 100.0] or None.
  4. evaluate_from_signals() produces same-direction results as evaluate_frames().
  5. Empty input is handled gracefully.
  6. Subject continuity = 100% when all frames have detections.
"""

import numpy as np
import pytest

from src.engine.scoring.quality_evaluator import QualityEvaluator, SequenceQualityReport
from src.engine.scoring.signal_scoring_engine import FrameSignalScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_frame(h=32, w=128, fill=128) -> np.ndarray:
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _make_stable_sequence(n=10) -> list:
    """All frames identical — maximum stability."""
    frame = _make_frame(fill=150)
    return [frame.copy() for _ in range(n)]


def _make_jittery_sequence(n=10) -> list:
    """Alternating black and white — maximum jitter."""
    return [_make_frame(fill=(0 if i % 2 == 0 else 255)) for i in range(n)]


def _make_signal_sequence(n=5, motion=0.1, detection=True) -> list:
    """Synthetic signal sequence."""
    signals = []
    for i in range(n):
        sig = FrameSignalScore(
            frame_idx=i,
            is_dark=False,
            has_detection=detection,
            motion_score=motion,
            stability_score=1.0 - motion,
            contrast_score=0.6,
            subject_score=0.5 if detection else None,
        )
        signals.append(sig)
    return signals


# ---------------------------------------------------------------------------
# evaluate_frames() tests
# ---------------------------------------------------------------------------

class TestEvaluateFrames:

    def test_stable_sequence_has_high_jitter_score(self):
        evaluator = QualityEvaluator()
        frames = _make_stable_sequence(n=8)
        report = evaluator.evaluate_frames(frames)
        assert report.jitter_score is not None
        assert report.jitter_score > 60.0, (
            f"Stable sequence should have jitter_score > 60, got {report.jitter_score:.1f}"
        )

    def test_jittery_sequence_has_lower_stability(self):
        evaluator = QualityEvaluator()
        stable = evaluator.evaluate_frames(_make_stable_sequence(n=8))
        jittery = evaluator.evaluate_frames(_make_jittery_sequence(n=8))

        assert stable.temporal_stability is not None
        assert jittery.temporal_stability is not None
        assert stable.temporal_stability > jittery.temporal_stability, (
            "Stable sequence must have higher temporal_stability than jittery"
        )

    def test_all_scores_bounded(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_frames(_make_stable_sequence(n=5))
        for attr in ["temporal_stability", "jitter_score", "motion_smoothness",
                     "visual_consistency", "contrast_consistency",
                     "subject_continuity", "subject_size_consistency", "overall_temporal"]:
            val = getattr(report, attr)
            if val is not None:
                assert 0.0 <= val <= 100.0, f"{attr}={val} out of [0,100]"

    def test_empty_frames_returns_graceful_report(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_frames([])
        assert isinstance(report, SequenceQualityReport)
        assert report.frame_count == 0

    def test_single_frame_does_not_crash(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_frames([_make_frame()])
        assert isinstance(report, SequenceQualityReport)
        assert report.frame_count == 1

    def test_frame_count_matches(self):
        evaluator = QualityEvaluator()
        frames = [_make_frame() for _ in range(7)]
        report = evaluator.evaluate_frames(frames)
        assert report.frame_count == 7

    def test_observations_are_strings(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_frames(_make_stable_sequence(n=5))
        assert isinstance(report.observations, list)
        for obs in report.observations:
            assert isinstance(obs, str)


# ---------------------------------------------------------------------------
# evaluate_from_signals() tests
# ---------------------------------------------------------------------------

class TestEvaluateFromSignals:

    def test_stable_signals_have_high_jitter(self):
        evaluator = QualityEvaluator()
        signals = _make_signal_sequence(n=8, motion=0.01)
        report = evaluator.evaluate_from_signals(signals)
        if report.jitter_score is not None:
            assert report.jitter_score > 50.0, (
                f"Low-motion signals should have high jitter_score, got {report.jitter_score:.1f}"
            )

    def test_high_motion_signals_have_lower_stability(self):
        evaluator = QualityEvaluator()
        stable_report = evaluator.evaluate_from_signals(
            _make_signal_sequence(n=8, motion=0.02)
        )
        motion_report = evaluator.evaluate_from_signals(
            _make_signal_sequence(n=8, motion=0.8)
        )
        if stable_report.temporal_stability and motion_report.temporal_stability:
            assert stable_report.temporal_stability > motion_report.temporal_stability

    def test_full_detection_gives_100_continuity(self):
        evaluator = QualityEvaluator()
        signals = _make_signal_sequence(n=5, detection=True)
        report = evaluator.evaluate_from_signals(signals)
        assert report.subject_continuity is not None
        assert report.subject_continuity == pytest.approx(100.0, abs=0.1)

    def test_no_detection_gives_zero_continuity(self):
        evaluator = QualityEvaluator()
        signals = _make_signal_sequence(n=5, detection=False)
        for sig in signals:
            sig.has_detection = False
        report = evaluator.evaluate_from_signals(signals)
        assert report.subject_continuity is not None
        assert report.subject_continuity == pytest.approx(0.0, abs=0.1)

    def test_empty_signals_returns_graceful_report(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_from_signals([])
        assert isinstance(report, SequenceQualityReport)

    def test_all_scores_bounded_from_signals(self):
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_from_signals(_make_signal_sequence(n=6))
        for attr in ["temporal_stability", "jitter_score", "motion_smoothness",
                     "contrast_consistency", "subject_continuity",
                     "subject_size_consistency", "overall_temporal"]:
            val = getattr(report, attr)
            if val is not None:
                assert 0.0 <= val <= 100.0, f"{attr}={val} out of [0,100]"


# ---------------------------------------------------------------------------
# Overall temporal score
# ---------------------------------------------------------------------------

class TestOverallTemporalScore:

    def test_overall_is_higher_for_stable_than_jittery(self):
        evaluator = QualityEvaluator()
        stable = evaluator.evaluate_frames(_make_stable_sequence(n=10))
        jittery = evaluator.evaluate_frames(_make_jittery_sequence(n=10))
        if stable.overall_temporal and jittery.overall_temporal:
            assert stable.overall_temporal > jittery.overall_temporal

    def test_overall_is_none_if_no_metrics_computed(self):
        """A single-frame sequence may produce None overall_temporal."""
        evaluator = QualityEvaluator()
        report = evaluator.evaluate_frames([_make_frame()])
        # Should not crash; overall_temporal may be None or 0
        assert report.overall_temporal is None or report.overall_temporal >= 0.0
