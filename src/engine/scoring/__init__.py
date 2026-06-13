"""
src.engine.scoring — DMD GIF Converter Scoring V2

This package provides a clean separation between:
  - Signal extraction (measurement only, no decisions)
  - Final scoring (decisions, ranking, selection)
  - DMD readability prediction (pre-conversion quality estimate)
  - Sequence quality evaluation (temporal quality metrics)
  - Debug tooling (timeline export, ROI overlays, decision logging)

No existing interfaces (IScorer, IQualityScorer, etc.) are modified.
All components in this package are purely additive.
"""
from .signal_scoring_engine import SignalScoringEngine, FrameSignalScore
from .final_scoring_engine import FinalScoringEngine, FinalScore, ScoringStrategy
from .dmd_readability_engine import DmdReadabilityEngine, ReadabilityScore
from .quality_evaluator import QualityEvaluator, SequenceQualityReport

__all__ = [
    "SignalScoringEngine",
    "FrameSignalScore",
    "FinalScoringEngine",
    "FinalScore",
    "ScoringStrategy",
    "DmdReadabilityEngine",
    "ReadabilityScore",
    "QualityEvaluator",
    "SequenceQualityReport",
]
