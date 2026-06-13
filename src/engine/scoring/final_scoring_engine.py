"""
Final Scoring Engine — Layer 2 of the Scoring V2 architecture.

PURPOSE
-------
Decide. Rank. Filter. Select. Reject.

This layer CONSUMES FrameSignalScore (Layer 1).
It NEVER analyzes raw video frames directly.

The FinalScoringEngine applies:
  - Weights (how much each signal matters for a given strategy)
  - Business rules (DMD-specific frame constraints)
  - Penalties (reduce score for bad properties)
  - Bonuses (increase score for desirable properties)
  - Selection threshold (KEEP or DROP)

STRATEGIES
----------
Multiple predefined strategies are provided. A strategy is a named
configuration of weights and rules. Adding a new strategy never modifies
existing ones.

OUTPUT
------
FinalScore — a fully typed dataclass containing the decision, explanation,
penalties applied, and bonuses applied.

INTEGRATION
-----------
This module is purely additive. It does NOT modify any existing interface.
The existing IScorer, evaluate_gif_quality(), DMDVisibilityScore, and
DMDReadabilityScore continue to function exactly as before.

The FinalScoringEngine operates as an optional, parallel decision layer
that can be evaluated alongside the existing system without replacing it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .signal_scoring_engine import FrameSignalScore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

@dataclass
class ScoringStrategy:
    """
    A named configuration of signal weights and decision rules.

    Weights are relative (they are normalized internally).
    Values must be >= 0.0. Higher = more influence on the final score.

    Selection threshold: frames scoring above it are selected (KEEP).
    Below it → rejected (DROP).
    """
    name: str

    # Signal weights
    w_motion: float = 0.5
    w_stability: float = 0.5
    w_entropy: float = 0.3
    w_contrast: float = 0.8
    w_edge_density: float = 0.4
    w_subject: float = 0.6
    w_subject_centering: float = 0.5
    w_readability: float = 1.0
    w_attention: float = 0.6
    w_saliency: float = 0.3

    # Selection threshold (0–100)
    selection_threshold: float = 30.0

    # Penalty rules (applied when condition is met)
    penalize_dark_frames: bool = True
    penalize_no_detection: bool = False
    dark_frame_penalty: float = 30.0   # points subtracted from score
    no_detection_penalty: float = 10.0

    # Bonus rules
    bonus_high_contrast: bool = True
    bonus_centered_subject: bool = True
    high_contrast_bonus: float = 10.0
    centered_subject_bonus: float = 8.0

    # Thresholds for bonus/penalty triggers
    high_contrast_threshold: float = 0.5   # contrast_score above this = bonus
    centered_subject_threshold: float = 0.7  # centering above this = bonus


def _builtin_strategies() -> Dict[str, ScoringStrategy]:
    """
    Factory for the built-in scoring strategies.

    baseline_v1      — Mirrors the existing evaluate_gif_quality() behavior:
                       contrast-heavy, no detection requirement.
    motion_heavy     — Prioritizes frames with significant motion.
    subject_priority — Maximizes subject size and centering.
    face_priority    — Extreme centering + subject weight (for close-ups).
    stability_priority — Favors stable, low-motion frames (menus, cutscenes).
    readability_priority — Maximizes DMD readability prediction.
    balanced_v2      — Default recommended strategy.
    """
    return {
        "baseline_v1": ScoringStrategy(
            name="baseline_v1",
            w_motion=0.0,
            w_stability=0.0,
            w_entropy=0.2,
            w_contrast=1.0,
            w_edge_density=0.5,
            w_subject=0.0,
            w_subject_centering=0.0,
            w_readability=0.8,
            w_attention=0.0,
            w_saliency=0.2,
            selection_threshold=25.0,
            penalize_dark_frames=True,
            penalize_no_detection=False,
            bonus_high_contrast=True,
            bonus_centered_subject=False,
        ),
        "motion_heavy": ScoringStrategy(
            name="motion_heavy",
            w_motion=1.0,
            w_stability=0.0,
            w_entropy=0.5,
            w_contrast=0.5,
            w_edge_density=0.3,
            w_subject=0.4,
            w_subject_centering=0.3,
            w_readability=0.3,
            w_attention=0.4,
            w_saliency=0.3,
            selection_threshold=20.0,
            penalize_dark_frames=True,
            penalize_no_detection=False,
        ),
        "subject_priority": ScoringStrategy(
            name="subject_priority",
            w_motion=0.2,
            w_stability=0.3,
            w_entropy=0.2,
            w_contrast=0.6,
            w_edge_density=0.3,
            w_subject=1.0,
            w_subject_centering=0.8,
            w_readability=0.6,
            w_attention=0.8,
            w_saliency=0.3,
            selection_threshold=30.0,
            penalize_dark_frames=True,
            penalize_no_detection=True,
            no_detection_penalty=15.0,
            bonus_centered_subject=True,
            centered_subject_bonus=12.0,
        ),
        "face_priority": ScoringStrategy(
            name="face_priority",
            w_motion=0.1,
            w_stability=0.5,
            w_entropy=0.1,
            w_contrast=0.5,
            w_edge_density=0.2,
            w_subject=0.8,
            w_subject_centering=1.0,
            w_readability=0.5,
            w_attention=1.0,
            w_saliency=0.4,
            selection_threshold=35.0,
            penalize_dark_frames=True,
            penalize_no_detection=True,
            no_detection_penalty=20.0,
            bonus_centered_subject=True,
            centered_subject_threshold=0.8,
            centered_subject_bonus=15.0,
        ),
        "stability_priority": ScoringStrategy(
            name="stability_priority",
            w_motion=0.0,
            w_stability=1.0,
            w_entropy=0.3,
            w_contrast=0.7,
            w_edge_density=0.4,
            w_subject=0.2,
            w_subject_centering=0.2,
            w_readability=0.8,
            w_attention=0.2,
            w_saliency=0.2,
            selection_threshold=20.0,
            penalize_dark_frames=True,
            penalize_no_detection=False,
        ),
        "readability_priority": ScoringStrategy(
            name="readability_priority",
            w_motion=0.1,
            w_stability=0.3,
            w_entropy=0.5,
            w_contrast=1.0,
            w_edge_density=0.8,
            w_subject=0.3,
            w_subject_centering=0.3,
            w_readability=1.0,
            w_attention=0.3,
            w_saliency=0.4,
            selection_threshold=30.0,
            penalize_dark_frames=True,
            penalize_no_detection=False,
            bonus_high_contrast=True,
            high_contrast_threshold=0.4,
            high_contrast_bonus=12.0,
        ),
        "balanced_v2": ScoringStrategy(
            name="balanced_v2",
            w_motion=0.0,
            w_stability=0.0,
            w_entropy=0.3,
            w_contrast=0.5,
            w_edge_density=0.0,
            w_subject=0.1,
            w_subject_centering=0.1,
            w_readability=0.0,
            w_attention=0.0,
            w_saliency=0.0,
            selection_threshold=50.0,
            penalize_dark_frames=False,
            penalize_no_detection=False,
            bonus_high_contrast=False,
            bonus_centered_subject=False,
        ),
    }


BUILTIN_STRATEGIES: Dict[str, ScoringStrategy] = _builtin_strategies()


# ---------------------------------------------------------------------------
# Output object — Layer 2
# ---------------------------------------------------------------------------

@dataclass
class FinalScore:
    """
    Decision result for a single frame.

    The 'selected' field is the authoritative KEEP / DROP decision.
    'score' is the raw computed value before penalty/bonus application —
    it may be used for relative ranking even when 'selected' is False.
    'ranking' is set by the engine after all frames have been scored (0-based).
    """
    # Core output
    score: float = 0.0
    """Weighted combination of signal scores, expressed on a 0–100 scale."""

    selected: bool = False
    """True = KEEP, False = DROP."""

    # Explainability
    explanation: str = ""
    """Human-readable one-line summary of why this frame was selected/rejected."""

    penalties: List[str] = field(default_factory=list)
    """List of penalty labels applied (e.g., 'dark_frame', 'no_detection')."""

    bonuses: List[str] = field(default_factory=list)
    """List of bonus labels applied (e.g., 'high_contrast', 'centered_subject')."""

    # For sequence-level sorting (set after batch scoring)
    ranking: int = -1
    """Position in the ranked sequence (0 = best). -1 = not ranked yet."""

    # Reference to the source signal score for inspection
    signal: Optional[FrameSignalScore] = None
    """The FrameSignalScore that produced this FinalScore, for debugging."""

    # Strategy that produced this score
    strategy_name: str = "unknown"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FinalScoringEngine:
    """
    Converts FrameSignalScore → FinalScore using a ScoringStrategy.

    This class is stateless per-frame. Batch methods handle ranking.

    Parameters
    ----------
    strategy : ScoringStrategy or str
        The scoring strategy to apply. Pass a string to use a built-in
        strategy by name (see BUILTIN_STRATEGIES). Pass a ScoringStrategy
        instance for custom configuration.
    """

    def __init__(self, strategy: "str | ScoringStrategy" = "balanced_v2") -> None:
        if isinstance(strategy, str):
            if strategy not in BUILTIN_STRATEGIES:
                raise ValueError(
                    f"Unknown strategy '{strategy}'. "
                    f"Available: {list(BUILTIN_STRATEGIES.keys())}"
                )
            self._strategy = BUILTIN_STRATEGIES[strategy]
        else:
            self._strategy = strategy

    @property
    def strategy(self) -> ScoringStrategy:
        return self._strategy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_frame(self, signal: FrameSignalScore) -> FinalScore:
        """
        Compute FinalScore for a single FrameSignalScore.

        Parameters
        ----------
        signal : FrameSignalScore
            Output from SignalScoringEngine.score_frame().

        Returns
        -------
        FinalScore
            Decision, score, explanation, penalties, and bonuses.
        """
        s = self._strategy
        penalties: List[str] = []
        bonuses: List[str] = []

        # ── Weighted score computation ────────────────────────────────────
        raw_score = self._compute_weighted_score(signal)

        # ── Penalties ────────────────────────────────────────────────────
        penalty_total = 0.0
        if s.penalize_dark_frames and signal.is_dark:
            penalty_total += s.dark_frame_penalty
            penalties.append("dark_frame")

        if s.penalize_no_detection and not signal.has_detection:
            penalty_total += s.no_detection_penalty
            penalties.append("no_detection")

        # ── Bonuses ──────────────────────────────────────────────────────
        bonus_total = 0.0
        if s.bonus_high_contrast and signal.contrast_score is not None:
            if signal.contrast_score >= s.high_contrast_threshold:
                bonus_total += s.high_contrast_bonus
                bonuses.append("high_contrast")

        if s.bonus_centered_subject and signal.subject_centering_score is not None:
            if signal.subject_centering_score >= s.centered_subject_threshold:
                bonus_total += s.centered_subject_bonus
                bonuses.append("centered_subject")

        # ── Final score ───────────────────────────────────────────────────
        final_score = max(0.0, min(100.0, raw_score + bonus_total - penalty_total))

        # ── Selection decision ────────────────────────────────────────────
        selected = final_score >= s.selection_threshold

        # ── Explanation ───────────────────────────────────────────────────
        explanation = self._build_explanation(
            signal, final_score, selected, penalties, bonuses, s
        )

        return FinalScore(
            score=round(final_score, 2),
            selected=selected,
            explanation=explanation,
            penalties=penalties,
            bonuses=bonuses,
            signal=signal,
            strategy_name=s.name,
        )

    def score_sequence(
        self,
        signals: List[FrameSignalScore],
    ) -> List[FinalScore]:
        """
        Score a sequence of frames and populate 'ranking' fields.

        The returned list is in the same order as the input.
        'ranking' is set on each FinalScore based on descending score
        among selected frames.

        Parameters
        ----------
        signals : List[FrameSignalScore]
            All signals for a video, in chronological order.

        Returns
        -------
        List[FinalScore]
            Same order as input, with ranking set.
        """
        results = [self.score_frame(sig) for sig in signals]

        # Rank selected frames by descending score
        selected_indices = sorted(
            [i for i, r in enumerate(results) if r.selected],
            key=lambda i: results[i].score,
            reverse=True,
        )
        for rank, idx in enumerate(selected_indices):
            results[idx].ranking = rank

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_weighted_score(self, signal: FrameSignalScore) -> float:
        """
        Compute normalized weighted sum of available signals.

        Returns 0.0 if no signals are available.
        Signals set to None are excluded from both numerator and denominator
        (no implicit penalization for unavailability).
        """
        s = self._strategy

        # (signal_value, weight) pairs — only non-None values participate
        candidates = [
            (signal.motion_score,           s.w_motion),
            (signal.stability_score,        s.w_stability),
            (signal.entropy_score,          s.w_entropy),
            (signal.contrast_score,         s.w_contrast),
            (signal.edge_density_score,     s.w_edge_density),
            (signal.subject_score,          s.w_subject),
            (signal.subject_centering_score, s.w_subject_centering),
            (signal.readability_score,      s.w_readability),
            (signal.attention_score,        s.w_attention),
            (signal.saliency_score,         s.w_saliency),
        ]

        total_weight = 0.0
        weighted_sum = 0.0
        for value, weight in candidates:
            if value is not None and weight > 0.0:
                weighted_sum += float(value) * weight
                total_weight += weight

        if total_weight == 0.0:
            return 0.0

        # Normalize to [0, 100]
        return (weighted_sum / total_weight) * 100.0

    @staticmethod
    def _build_explanation(
        signal: FrameSignalScore,
        score: float,
        selected: bool,
        penalties: List[str],
        bonuses: List[str],
        strategy: ScoringStrategy,
    ) -> str:
        """Build a concise human-readable explanation string."""
        verdict = "KEEP" if selected else "DROP"
        parts = [f"[{verdict}] score={score:.1f} strategy={strategy.name}"]

        if penalties:
            parts.append(f"penalties=[{', '.join(penalties)}]")
        if bonuses:
            parts.append(f"bonuses=[{', '.join(bonuses)}]")

        # Key signal values for context
        key_vals = []
        if signal.contrast_score is not None:
            key_vals.append(f"contrast={signal.contrast_score:.2f}")
        if signal.readability_score is not None:
            key_vals.append(f"readability={signal.readability_score:.2f}")
        if signal.subject_score is not None:
            key_vals.append(f"subject={signal.subject_score:.2f}")
        if signal.motion_score is not None:
            key_vals.append(f"motion={signal.motion_score:.2f}")
        if key_vals:
            parts.append(f"signals=[{', '.join(key_vals)}]")

        return " | ".join(parts)
