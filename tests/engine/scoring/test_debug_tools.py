"""
Tests for debug tooling: ScoreTimeline, SignalTimeline,
ROIOverlayRenderer, DecisionLogger.

Key invariants:
  1. ScoreTimeline.as_list() length matches number of records.
  2. SignalTimeline exports correct field names.
  3. ROIOverlayRenderer returns same frame count as input, no crash.
  4. DecisionLogger counts selected/dropped correctly.
  5. JSON exports are valid JSON.
  6. Timeline export produces correct frame indices.
"""

import json
import os
import tempfile

import numpy as np
import pytest

from src.engine.scoring.signal_scoring_engine import FrameSignalScore
from src.engine.scoring.final_scoring_engine import FinalScore
from src.engine.scoring.debug_tools import (
    ScoreTimeline,
    SignalTimeline,
    ROIOverlayRenderer,
    DecisionLogger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(idx: int = 0, has_detection: bool = True) -> FrameSignalScore:
    return FrameSignalScore(
        frame_idx=idx,
        is_dark=False,
        has_detection=has_detection,
        contrast_score=0.7,
        readability_score=0.6,
        motion_score=0.2,
        stability_score=0.8,
    )


def _make_final(idx: int = 0, selected: bool = True, score: float = 65.0) -> FinalScore:
    sig = _make_signal(idx)
    return FinalScore(
        score=score,
        selected=selected,
        explanation=f"[{'KEEP' if selected else 'DROP'}] score={score:.1f} strategy=test",
        penalties=[] if selected else ["dark_frame"],
        bonuses=["high_contrast"] if selected else [],
        ranking=0 if selected else -1,
        signal=sig,
        strategy_name="test",
    )


def _make_frame(h=32, w=128, fill=100) -> np.ndarray:
    return np.full((h, w, 3), fill, dtype=np.uint8)


# ---------------------------------------------------------------------------
# ScoreTimeline
# ---------------------------------------------------------------------------

class TestScoreTimeline:

    def test_record_and_length(self):
        tl = ScoreTimeline()
        for i in range(5):
            tl.record(i, _make_final(i))
        assert len(tl.as_list()) == 5

    def test_records_have_correct_indices(self):
        tl = ScoreTimeline()
        tl.record(42, _make_final(42))
        records = tl.as_list()
        assert records[0]["frame_idx"] == 42

    def test_records_have_score(self):
        tl = ScoreTimeline()
        tl.record(0, _make_final(score=77.5))
        assert tl.as_list()[0]["score"] == pytest.approx(77.5, abs=0.1)

    def test_export_json_produces_valid_json(self):
        tl = ScoreTimeline()
        for i in range(3):
            tl.record(i, _make_final(i, selected=(i % 2 == 0)))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            tl.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 3
        finally:
            os.unlink(path)

    def test_export_csv_does_not_crash(self):
        tl = ScoreTimeline()
        tl.record(0, _make_final(0))
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            tl.export_csv(path)
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_empty_timeline_csv_does_not_crash(self):
        tl = ScoreTimeline()
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            tl.export_csv(path)  # should not crash
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# SignalTimeline
# ---------------------------------------------------------------------------

class TestSignalTimeline:

    def test_record_and_length(self):
        tl = SignalTimeline()
        for i in range(4):
            tl.record(_make_signal(i))
        assert len(tl.as_list()) == 4

    def test_records_have_correct_frame_idx(self):
        tl = SignalTimeline()
        tl.record(_make_signal(7))
        assert tl.as_list()[0]["frame_idx"] == 7

    def test_export_json_valid(self):
        tl = SignalTimeline()
        tl.record(_make_signal(0))
        tl.record(_make_signal(1))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            tl.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 2
            assert "frame_idx" in data[0]
            assert "contrast_score" in data[0]
        finally:
            os.unlink(path)

    def test_get_field_series_length_matches(self):
        tl = SignalTimeline()
        for i in range(5):
            tl.record(_make_signal(i))
        series = tl.get_field_series("contrast_score")
        assert len(series) == 5

    def test_get_field_series_values(self):
        tl = SignalTimeline()
        sig = _make_signal(0)
        sig.contrast_score = 0.42
        tl.record(sig)
        series = tl.get_field_series("contrast_score")
        assert series[0] == pytest.approx(0.42, abs=0.01)

    def test_get_nonexistent_field_returns_none_list(self):
        tl = SignalTimeline()
        tl.record(_make_signal(0))
        series = tl.get_field_series("nonexistent_field_xyz")
        assert series[0] is None


# ---------------------------------------------------------------------------
# ROIOverlayRenderer
# ---------------------------------------------------------------------------

class TestROIOverlayRenderer:

    def test_render_frame_returns_array(self):
        renderer = ROIOverlayRenderer()
        frame = _make_frame()
        result = renderer.render_frame(frame)
        assert isinstance(result, np.ndarray)
        assert result.shape == frame.shape

    def test_render_frame_does_not_modify_original(self):
        renderer = ROIOverlayRenderer()
        frame = _make_frame(fill=42)
        original_sum = frame.sum()
        renderer.render_frame(frame, detected_roi=(0, 0, 20, 20))
        assert frame.sum() == original_sum, "render_frame must not modify original frame"

    def test_render_frame_with_all_annotations(self):
        renderer = ROIOverlayRenderer()
        frame = _make_frame(h=64, w=128, fill=100)
        result = renderer.render_frame(
            frame,
            detected_roi=(10, 5, 30, 20),
            tracked_roi=(12, 6, 28, 18),
            camera_rect=(64.0, 32.0, 80.0, 32.0),
            frame_score=75.3,
            frame_idx=42,
        )
        assert result.shape == frame.shape

    def test_render_frame_none_input_returns_zeros(self):
        renderer = ROIOverlayRenderer()
        result = renderer.render_frame(None)
        assert isinstance(result, np.ndarray)

    def test_render_sequence_length_matches(self):
        renderer = ROIOverlayRenderer()
        frames = [_make_frame() for _ in range(5)]
        results = renderer.render_sequence(frames)
        assert len(results) == 5

    def test_render_sequence_with_rois(self):
        renderer = ROIOverlayRenderer()
        frames = [_make_frame() for _ in range(3)]
        rois = [(0, 0, 10, 10), None, (5, 5, 20, 20)]
        results = renderer.render_sequence(frames, detected_rois=rois)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# DecisionLogger
# ---------------------------------------------------------------------------

class TestDecisionLogger:

    def test_selected_count(self):
        logger = DecisionLogger()
        logger.record(0, _make_signal(0), _make_final(0, selected=True))
        logger.record(1, _make_signal(1), _make_final(1, selected=True))
        logger.record(2, _make_signal(2), _make_final(2, selected=False))
        assert logger.selected_count == 2
        assert logger.dropped_count == 1
        assert logger.total_count == 3

    def test_selection_rate_correct(self):
        logger = DecisionLogger()
        for i in range(10):
            logger.record(i, _make_signal(i), _make_final(i, selected=(i < 6)))
        assert logger.selected_count == 6
        assert logger.dropped_count == 4

    def test_export_json_valid(self):
        logger = DecisionLogger()
        logger.record(0, _make_signal(0), _make_final(0, selected=True))
        logger.record(1, _make_signal(1), _make_final(1, selected=False))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            logger.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert "summary" in data
            assert "decisions" in data
            assert data["summary"]["total"] == 2
            assert data["summary"]["selected"] == 1
            assert len(data["decisions"]) == 2
        finally:
            os.unlink(path)

    def test_export_json_decisions_contain_explanation(self):
        logger = DecisionLogger()
        final = _make_final(0, selected=True)
        final.explanation = "test explanation"
        logger.record(0, _make_signal(0), final)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            logger.export_json(path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["decisions"][0]["explanation"] == "test explanation"
        finally:
            os.unlink(path)

    def test_print_summary_does_not_crash(self):
        logger = DecisionLogger()
        logger.record(0, _make_signal(0), _make_final(0))
        logger.print_summary()  # should not raise
