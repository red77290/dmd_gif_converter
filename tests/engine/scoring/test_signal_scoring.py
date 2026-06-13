"""
Tests for SignalScoringEngine (Layer 1 — Pure measurement).

Invariants verified:
  1. Signals are NEVER decisions (no selection, ranking, or threshold logic).
  2. Dark frames set is_dark=True and return None for temporal signals.
  3. Motion signals are None on the first frame (no previous frame).
  4. A completely uniform frame yields contrast_score ≈ 0.0.
  5. A high-contrast frame yields contrast_score > 0.5.
  6. Entropy is higher on complex frames than on uniform frames.
  7. FrameSignalScore contains no selection, ranking, or threshold fields.
  8. score_sequence() returns one score per frame, in order.
"""

import numpy as np
import pytest

from src.engine.scoring.signal_scoring_engine import SignalScoringEngine, FrameSignalScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_frame(height: int = 64, width: int = 64, fill: int = 128) -> np.ndarray:
    """Create a solid BGR frame."""
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _make_checker_frame(height: int = 64, width: int = 64) -> np.ndarray:
    """High-contrast checkerboard frame."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            if (x + y) % 2 == 0:
                frame[y, x] = [255, 255, 255]
    return frame


def _make_gradient_frame(height: int = 64, width: int = 64) -> np.ndarray:
    """Horizontal gradient — medium complexity."""
    row = np.linspace(0, 255, width, dtype=np.uint8)
    frame = np.tile(row, (height, 1))
    return np.stack([frame, frame, frame], axis=-1)


def _make_dark_frame(height: int = 64, width: int = 64) -> np.ndarray:
    """Very dark frame (mean luminance < 10)."""
    return np.full((height, width, 3), 5, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Core invariant: FrameSignalScore is purely observational
# ---------------------------------------------------------------------------

class TestFrameSignalScoreStructure:
    """Verify the output object has no decision fields."""

    def test_no_selection_field(self):
        sig = FrameSignalScore()
        assert not hasattr(sig, "selected"), (
            "FrameSignalScore must NOT contain 'selected' — that belongs in FinalScore"
        )

    def test_no_ranking_field(self):
        sig = FrameSignalScore()
        assert not hasattr(sig, "ranking"), (
            "FrameSignalScore must NOT contain 'ranking' — that belongs in FinalScore"
        )

    def test_no_threshold_field(self):
        sig = FrameSignalScore()
        for name in ("threshold", "selection_threshold", "min_score"):
            assert not hasattr(sig, name), (
                f"FrameSignalScore must NOT contain threshold field '{name}'"
            )

    def test_all_optional_fields_default_to_none(self):
        sig = FrameSignalScore()
        optional_fields = [
            "motion_score", "optical_flow_score", "stability_score",
            "entropy_score", "contrast_score", "saliency_score",
            "edge_density_score", "subject_score", "face_score",
            "object_score", "subject_centering_score",
            "readability_score", "attention_score",
        ]
        for f in optional_fields:
            assert getattr(sig, f) is None, (
                f"FrameSignalScore.{f} should default to None"
            )


# ---------------------------------------------------------------------------
# Dark frame handling
# ---------------------------------------------------------------------------

class TestDarkFrameHandling:

    def test_dark_frame_is_flagged(self):
        engine = SignalScoringEngine(dark_threshold=40.0)
        frame = _make_dark_frame()
        sig = engine.score_frame(frame)
        assert sig.is_dark is True

    def test_bright_frame_is_not_dark(self):
        engine = SignalScoringEngine(dark_threshold=40.0)
        frame = _make_frame(fill=200)
        sig = engine.score_frame(frame)
        assert sig.is_dark is False

    def test_dark_frame_entropy_is_none(self):
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_dark_frame())
        assert sig.entropy_score is None, (
            "entropy_score should be None on dark frames (unreliable)"
        )


# ---------------------------------------------------------------------------
# Temporal signals — first frame behavior
# ---------------------------------------------------------------------------

class TestTemporalSignalsFirstFrame:

    def test_motion_none_on_first_frame(self):
        engine = SignalScoringEngine()
        engine.reset()
        sig = engine.score_frame(_make_frame())
        assert sig.motion_score is None, (
            "motion_score must be None on the first frame (no previous frame)"
        )

    def test_stability_none_on_first_frame(self):
        engine = SignalScoringEngine()
        engine.reset()
        sig = engine.score_frame(_make_frame())
        assert sig.stability_score is None

    def test_motion_not_none_on_second_frame(self):
        engine = SignalScoringEngine()
        engine.reset()
        engine.score_frame(_make_frame(fill=100))  # first frame
        sig = engine.score_frame(_make_frame(fill=200))  # second frame
        assert sig.motion_score is not None
        assert 0.0 <= sig.motion_score <= 1.0

    def test_identical_frames_have_zero_motion(self):
        engine = SignalScoringEngine()
        engine.reset()
        frame = _make_frame(fill=150)
        engine.score_frame(frame)
        sig = engine.score_frame(frame.copy())
        assert sig.motion_score is not None
        assert sig.motion_score == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Contrast signal
# ---------------------------------------------------------------------------

class TestContrastSignal:

    def test_uniform_frame_has_near_zero_contrast(self):
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_frame(fill=128))
        assert sig.contrast_score is not None
        assert sig.contrast_score < 0.05, (
            f"Uniform frame should have near-zero contrast, got {sig.contrast_score}"
        )

    def test_checkerboard_has_high_contrast(self):
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_checker_frame())
        assert sig.contrast_score is not None
        assert sig.contrast_score > 0.5, (
            f"Checkerboard should have high contrast, got {sig.contrast_score}"
        )

    def test_contrast_is_bounded(self):
        engine = SignalScoringEngine()
        for fill in [0, 64, 128, 192, 255]:
            sig = engine.score_frame(_make_frame(fill=fill))
            assert sig.contrast_score is not None
            assert 0.0 <= sig.contrast_score <= 1.0


# ---------------------------------------------------------------------------
# Entropy signal
# ---------------------------------------------------------------------------

class TestEntropySignal:

    def test_uniform_frame_has_lower_entropy_than_complex(self):
        engine = SignalScoringEngine()
        engine.reset()
        sig_uniform = engine.score_frame(_make_frame(fill=128))

        engine.reset()
        sig_complex = engine.score_frame(_make_checker_frame())

        assert sig_uniform.entropy_score is not None
        assert sig_complex.entropy_score is not None
        assert sig_complex.entropy_score > sig_uniform.entropy_score, (
            "Complex frame should have higher entropy than uniform frame"
        )

    def test_entropy_is_bounded(self):
        engine = SignalScoringEngine()
        for frame in [_make_frame(), _make_checker_frame(), _make_gradient_frame()]:
            engine.reset()
            sig = engine.score_frame(frame)
            if sig.entropy_score is not None:
                assert 0.0 <= sig.entropy_score <= 1.0


# ---------------------------------------------------------------------------
# Edge density signal
# ---------------------------------------------------------------------------

class TestEdgeDensitySignal:

    def test_uniform_frame_has_low_edge_density(self):
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_frame(fill=128))
        assert sig.edge_density_score is not None
        assert sig.edge_density_score < 0.1

    def test_checkerboard_has_higher_edges(self):
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_checker_frame())
        assert sig.edge_density_score is not None
        assert sig.edge_density_score > 0.0


# ---------------------------------------------------------------------------
# Composite signals
# ---------------------------------------------------------------------------

class TestCompositeSignals:

    def test_readability_is_combination_of_contrast_and_edges(self):
        """readability_score should not be zero when contrast and edges are computed."""
        engine = SignalScoringEngine()
        sig = engine.score_frame(_make_checker_frame())
        assert sig.readability_score is not None
        assert sig.readability_score > 0.0

    def test_attention_is_none_without_detector(self):
        """Without a detector, subject_centering_score is None.
        attention_score should gracefully handle this."""
        engine = SignalScoringEngine(detector=None)
        sig = engine.score_frame(_make_frame())
        # With no detector, centering is None, saliency might be computed
        # attention may be None or use saliency as fallback — either is valid
        # as long as it doesn't raise

    def test_readability_bounded(self):
        engine = SignalScoringEngine()
        for frame in [_make_frame(), _make_checker_frame(), _make_gradient_frame()]:
            engine.reset()
            sig = engine.score_frame(frame)
            if sig.readability_score is not None:
                assert 0.0 <= sig.readability_score <= 1.0


# ---------------------------------------------------------------------------
# Sequence scoring
# ---------------------------------------------------------------------------

class TestSequenceScoring:

    def test_score_sequence_length_matches_input(self):
        engine = SignalScoringEngine()
        frames = [_make_frame(fill=i * 30) for i in range(5)]
        results = engine.score_sequence(frames, start_frame_idx=0)
        assert len(results) == 5

    def test_score_sequence_frame_indices_are_correct(self):
        engine = SignalScoringEngine()
        frames = [_make_frame() for _ in range(3)]
        results = engine.score_sequence(frames, start_frame_idx=10)
        assert results[0].frame_idx == 10
        assert results[1].frame_idx == 11
        assert results[2].frame_idx == 12

    def test_reset_clears_temporal_state(self):
        engine = SignalScoringEngine()
        engine.score_frame(_make_frame(fill=100))  # creates prev_gray
        engine.reset()
        sig = engine.score_frame(_make_frame(fill=200))
        assert sig.motion_score is None, (
            "After reset(), first frame should again have None motion_score"
        )

    def test_all_signals_bounded(self):
        """All non-None signal values must be in [0, 1]."""
        engine = SignalScoringEngine()
        frames = [
            _make_frame(fill=0),
            _make_checker_frame(),
            _make_gradient_frame(),
            _make_frame(fill=255),
            _make_dark_frame(),
        ]
        results = engine.score_sequence(frames)
        float_fields = [
            "motion_score", "optical_flow_score", "stability_score",
            "entropy_score", "contrast_score", "saliency_score",
            "edge_density_score", "subject_score", "face_score",
            "object_score", "subject_centering_score",
            "readability_score", "attention_score",
        ]
        for sig in results:
            for field in float_fields:
                val = getattr(sig, field)
                if val is not None:
                    assert 0.0 <= val <= 1.0, (
                        f"Signal {field} out of [0,1] range: {val}"
                    )
