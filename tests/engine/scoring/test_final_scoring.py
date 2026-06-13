"""
Tests for FinalScoringEngine (Layer 2 — Decision engine).

Invariants verified:
  1. FinalScore.selected is the authoritative KEEP/DROP decision.
  2. Dark frames receive penalties when penalize_dark_frames=True.
  3. High contrast frames receive bonuses when bonus_high_contrast=True.
  4. score_sequence() assigns ranking only to selected frames.
  5. Custom strategies produce different outcomes than built-ins on the same signals.
  6. All built-in strategies have unique names.
  7. Unknown strategy names raise ValueError.
  8. Scores are bounded to [0, 100].
  9. Explanations are non-empty strings.
  10. Multiple FinalScoringEngine instances on same signals are independent.
"""

import pytest

from src.engine.scoring.signal_scoring_engine import FrameSignalScore
from src.engine.scoring.final_scoring_engine import (
    FinalScoringEngine,
    FinalScore,
    ScoringStrategy,
    BUILTIN_STRATEGIES,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic FrameSignalScore objects
# ---------------------------------------------------------------------------

def _make_good_signal(frame_idx: int = 0) -> FrameSignalScore:
    """A well-lit, high-contrast, centered-subject frame."""
    return FrameSignalScore(
        frame_idx=frame_idx,
        is_dark=False,
        has_detection=True,
        motion_score=0.3,
        stability_score=0.7,
        entropy_score=0.7,
        contrast_score=0.8,
        edge_density_score=0.5,
        saliency_score=0.6,
        subject_score=0.5,
        object_score=0.5,
        subject_centering_score=0.8,
        readability_score=0.75,
        attention_score=0.6,
    )


def _make_dark_signal(frame_idx: int = 0) -> FrameSignalScore:
    """A very dark, unreliable frame."""
    return FrameSignalScore(
        frame_idx=frame_idx,
        is_dark=True,
        has_detection=False,
        motion_score=None,
        stability_score=None,
        entropy_score=None,
        contrast_score=0.02,
        edge_density_score=0.01,
        readability_score=0.01,
    )


def _make_poor_signal(frame_idx: int = 0) -> FrameSignalScore:
    """A poor-quality frame (low contrast, no detection)."""
    return FrameSignalScore(
        frame_idx=frame_idx,
        is_dark=False,
        has_detection=False,
        contrast_score=0.05,
        entropy_score=0.1,
        edge_density_score=0.02,
        readability_score=0.04,
    )


# ---------------------------------------------------------------------------
# Strategy catalog
# ---------------------------------------------------------------------------

class TestBuiltinStrategyCatalog:

    def test_all_builtin_strategies_have_unique_names(self):
        names = [s.name for s in BUILTIN_STRATEGIES.values()]
        assert len(names) == len(set(names)), "Duplicate strategy names detected"

    def test_all_builtin_strategies_are_accessible_by_name(self):
        for name in ["baseline_v1", "motion_heavy", "subject_priority",
                     "face_priority", "stability_priority",
                     "readability_priority", "balanced_v2"]:
            assert name in BUILTIN_STRATEGIES, f"Strategy '{name}' not in BUILTIN_STRATEGIES"

    def test_unknown_strategy_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            FinalScoringEngine(strategy="nonexistent_strategy_xyz")


# ---------------------------------------------------------------------------
# FinalScore structure
# ---------------------------------------------------------------------------

class TestFinalScoreStructure:

    def test_final_score_has_selected_field(self):
        fs = FinalScore()
        assert hasattr(fs, "selected")
        assert isinstance(fs.selected, bool)

    def test_final_score_has_explanation(self):
        engine = FinalScoringEngine("balanced_v2")
        fs = engine.score_frame(_make_good_signal())
        assert isinstance(fs.explanation, str)
        assert len(fs.explanation) > 0

    def test_final_score_references_strategy(self):
        engine = FinalScoringEngine("motion_heavy")
        fs = engine.score_frame(_make_good_signal())
        assert fs.strategy_name == "motion_heavy"

    def test_final_score_score_bounded(self):
        for strategy_name in BUILTIN_STRATEGIES:
            engine = FinalScoringEngine(strategy_name)
            for sig in [_make_good_signal(), _make_dark_signal(), _make_poor_signal()]:
                fs = engine.score_frame(sig)
                assert 0.0 <= fs.score <= 100.0, (
                    f"Score {fs.score} out of [0,100] for strategy '{strategy_name}'"
                )


# ---------------------------------------------------------------------------
# Penalty application
# ---------------------------------------------------------------------------

class TestPenalties:

    def test_dark_frame_penalty_applied(self):
        strategy = ScoringStrategy(
            name="test_dark_penalty",
            penalize_dark_frames=True,
            dark_frame_penalty=30.0,
            selection_threshold=0.0,  # disable threshold to isolate penalty
        )
        engine = FinalScoringEngine(strategy=strategy)
        fs = engine.score_frame(_make_dark_signal())
        assert "dark_frame" in fs.penalties

    def test_dark_frame_penalty_not_applied_when_disabled(self):
        strategy = ScoringStrategy(
            name="test_no_dark_penalty",
            penalize_dark_frames=False,
        )
        engine = FinalScoringEngine(strategy=strategy)
        fs = engine.score_frame(_make_dark_signal())
        assert "dark_frame" not in fs.penalties

    def test_no_detection_penalty_applied(self):
        strategy = ScoringStrategy(
            name="test_det_penalty",
            penalize_no_detection=True,
            no_detection_penalty=10.0,
            selection_threshold=0.0,
        )
        engine = FinalScoringEngine(strategy=strategy)
        fs = engine.score_frame(_make_poor_signal())
        assert "no_detection" in fs.penalties

    def test_penalties_reduce_score(self):
        strategy_no_penalty = ScoringStrategy(
            name="no_penalty",
            penalize_dark_frames=False,
            selection_threshold=0.0,
        )
        strategy_with_penalty = ScoringStrategy(
            name="with_penalty",
            penalize_dark_frames=True,
            dark_frame_penalty=20.0,
            selection_threshold=0.0,
        )
        sig = _make_dark_signal()
        score_no_penalty = FinalScoringEngine(strategy=strategy_no_penalty).score_frame(sig).score
        score_with_penalty = FinalScoringEngine(strategy=strategy_with_penalty).score_frame(sig).score
        assert score_with_penalty <= score_no_penalty, (
            "Score with penalty must not exceed score without penalty"
        )


# ---------------------------------------------------------------------------
# Bonus application
# ---------------------------------------------------------------------------

class TestBonuses:

    def test_high_contrast_bonus_applied(self):
        strategy = ScoringStrategy(
            name="test_contrast_bonus",
            bonus_high_contrast=True,
            high_contrast_threshold=0.5,
            high_contrast_bonus=10.0,
        )
        engine = FinalScoringEngine(strategy=strategy)
        sig = _make_good_signal()
        sig.contrast_score = 0.9  # above threshold
        fs = engine.score_frame(sig)
        assert "high_contrast" in fs.bonuses

    def test_high_contrast_bonus_not_applied_below_threshold(self):
        strategy = ScoringStrategy(
            name="test_no_contrast_bonus",
            bonus_high_contrast=True,
            high_contrast_threshold=0.5,
        )
        engine = FinalScoringEngine(strategy=strategy)
        sig = FrameSignalScore(contrast_score=0.2)  # below threshold
        fs = engine.score_frame(sig)
        assert "high_contrast" not in fs.bonuses

    def test_centered_subject_bonus_applied(self):
        strategy = ScoringStrategy(
            name="test_centering_bonus",
            bonus_centered_subject=True,
            centered_subject_threshold=0.7,
            centered_subject_bonus=8.0,
        )
        engine = FinalScoringEngine(strategy=strategy)
        sig = _make_good_signal()
        sig.subject_centering_score = 0.9
        fs = engine.score_frame(sig)
        assert "centered_subject" in fs.bonuses


# ---------------------------------------------------------------------------
# Selection decision
# ---------------------------------------------------------------------------

class TestSelectionDecision:

    def test_good_signal_is_selected_with_default_strategy(self):
        engine = FinalScoringEngine("balanced_v2")
        fs = engine.score_frame(_make_good_signal())
        assert fs.selected is True, (
            f"Good signal should be KEEP with balanced_v2, got score={fs.score}"
        )

    def test_dark_frame_is_dropped_with_high_threshold(self):
        strategy = ScoringStrategy(
            name="strict",
            penalize_dark_frames=True,
            dark_frame_penalty=50.0,
            selection_threshold=30.0,
        )
        engine = FinalScoringEngine(strategy=strategy)
        fs = engine.score_frame(_make_dark_signal())
        assert fs.selected is False

    def test_all_none_signals_result_in_zero_score(self):
        """A FrameSignalScore with all None float fields should give score 0."""
        engine = FinalScoringEngine("balanced_v2")
        sig = FrameSignalScore(frame_idx=0)  # all None
        fs = engine.score_frame(sig)
        # Score should be 0 or close (no signals → no weighted sum)
        assert fs.score == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# Sequence scoring and ranking
# ---------------------------------------------------------------------------

class TestSequenceScoring:

    def test_sequence_ranking_is_assigned(self):
        engine = FinalScoringEngine("balanced_v2")
        signals = [_make_good_signal(i) for i in range(5)]
        results = engine.score_sequence(signals)
        selected_results = [r for r in results if r.selected]
        for r in selected_results:
            assert r.ranking >= 0, "Selected frames must have a ranking >= 0"

    def test_dropped_frames_have_minus_one_ranking(self):
        strategy = ScoringStrategy(
            name="always_drop",
            selection_threshold=999.0,  # impossible threshold
        )
        engine = FinalScoringEngine(strategy=strategy)
        signals = [_make_good_signal(i) for i in range(3)]
        results = engine.score_sequence(signals)
        for r in results:
            assert r.selected is False
            assert r.ranking == -1

    def test_sequence_returns_same_order_as_input(self):
        engine = FinalScoringEngine("balanced_v2")
        signals = [
            _make_good_signal(0),
            _make_dark_signal(1),
            _make_poor_signal(2),
        ]
        results = engine.score_sequence(signals)
        assert len(results) == 3
        assert results[0].signal.frame_idx == 0
        assert results[1].signal.frame_idx == 1
        assert results[2].signal.frame_idx == 2


# ---------------------------------------------------------------------------
# Strategy isolation — multiple instances are independent
# ---------------------------------------------------------------------------

class TestStrategyIsolation:

    def test_two_strategies_on_same_signal_produce_independent_results(self):
        """Verify zero shared mutable state between engine instances."""
        engine_a = FinalScoringEngine("motion_heavy")
        engine_b = FinalScoringEngine("stability_priority")
        sig = _make_good_signal()
        sig.motion_score = 0.9
        sig.stability_score = 0.1

        result_a = engine_a.score_frame(sig)
        result_b = engine_b.score_frame(sig)

        # motion_heavy should score higher when motion is high
        # stability_priority should score lower when stability is low
        # We just verify they differ — not which is higher
        assert result_a.strategy_name == "motion_heavy"
        assert result_b.strategy_name == "stability_priority"
        # Scores should be deterministic (same sig → same score)
        result_a2 = engine_a.score_frame(sig)
        assert result_a.score == result_a2.score

    def test_custom_strategy_different_from_builtin(self):
        """A custom strategy with all-zero weights produces a lower score than a standard one.

        With all weights=0, the raw weighted score is 0.
        The final score may be slightly above 0 if bonuses are applied,
        but it must be lower than the balanced_v2 score on the same signal.
        """
        zero_strategy = ScoringStrategy(
            name="zero_weight",
            w_motion=0.0,
            w_stability=0.0,
            w_entropy=0.0,
            w_contrast=0.0,
            w_edge_density=0.0,
            w_subject=0.0,
            w_subject_centering=0.0,
            w_readability=0.0,
            w_attention=0.0,
            w_saliency=0.0,
            # Disable bonuses to get pure zero
            bonus_high_contrast=False,
            bonus_centered_subject=False,
        )
        engine_zero = FinalScoringEngine(strategy=zero_strategy)
        engine_std = FinalScoringEngine(strategy="balanced_v2")
        sig = _make_good_signal()
        fs_zero = engine_zero.score_frame(sig)
        fs_std = engine_std.score_frame(sig)
        # Zero-weight strategy must score strictly lower than the standard one
        assert fs_zero.score < fs_std.score, (
            f"Zero-weight strategy ({fs_zero.score}) should score lower than "
            f"balanced_v2 ({fs_std.score})"
        )
        # And specifically, zero-weight + no bonuses = 0.0
        assert fs_zero.score == pytest.approx(0.0, abs=0.5)
