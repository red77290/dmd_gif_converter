import unittest
from unittest.mock import MagicMock, patch
import customtkinter as ctk
from src.ui.panels.ai_moments_panel import AiMomentsPanel


class MockVar:
    def __init__(self, v=0.0): self._v = v
    def set(self, v): self._v = v
    def get(self): return self._v


def _make():
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
         patch.object(AiMomentsPanel, "_build_ai_moments_panel", return_value=None):
        app_state = MagicMock()
        panel = AiMomentsPanel(MagicMock(), app_state)
    panel.app_state = app_state
    panel.app_state.v_playhead = MockVar(0.0)
    panel.app_state.v_manual_start = MockVar(0.0)
    panel.app_state.v_manual_end = MockVar(5.0)
    panel._lbl_selection = MagicMock()
    panel.after = MagicMock()
    return panel


class TestSetInPoint(unittest.TestCase):
    def test_sets_start(self):
        p = _make()
        p.app_state.v_playhead.set(2.0)
        p._set_in_point()
        self.assertEqual(p.app_state.v_manual_start.get(), 2.0)
        p._lbl_selection.configure.assert_called()

    def test_pushes_end(self):
        p = _make()
        p.app_state.v_playhead.set(6.0)
        p.app_state.v_manual_end.set(5.0)
        p._set_in_point()
        self.assertEqual(p.app_state.v_manual_end.get(), 7.0)

    def test_end_unchanged_when_in_before(self):
        p = _make()
        p.app_state.v_playhead.set(1.0)
        p.app_state.v_manual_end.set(5.0)
        p._set_in_point()
        self.assertEqual(p.app_state.v_manual_end.get(), 5.0)


class TestSetOutPoint(unittest.TestCase):
    def test_sets_end(self):
        p = _make()
        p.app_state.v_playhead.set(4.0)
        p.app_state.v_manual_start.set(2.0)
        p._set_out_point()
        self.assertEqual(p.app_state.v_manual_end.get(), 4.0)
        self.assertEqual(p.app_state.v_manual_start.get(), 2.0)

    def test_pushes_start(self):
        p = _make()
        p.app_state.v_playhead.set(1.0)
        p.app_state.v_manual_start.set(3.0)
        p._set_out_point()
        self.assertEqual(p.app_state.v_manual_end.get(), 1.0)
        self.assertEqual(p.app_state.v_manual_start.get(), 0.0)


class TestTogglePlaySelection(unittest.TestCase):
    def test_starts_play(self):
        p = _make()
        p._ai_preview_cap = MagicMock()
        p._ai_preview_cap.get.return_value = 30.0
        p._is_playing_selection = False
        p._btn_play_selection = MagicMock()
        p._on_playhead_change = MagicMock()
        p._toggle_play_selection()
        self.assertTrue(p._is_playing_selection)
        p.after.assert_called()

    def test_stops_play(self):
        p = _make()
        p._ai_preview_cap = MagicMock()
        p._is_playing_selection = True
        p._btn_play_selection = MagicMock()
        p._toggle_play_selection()
        self.assertFalse(p._is_playing_selection)

    def test_no_cap_noop(self):
        p = _make()
        p._ai_preview_cap = None
        p._is_playing_selection = False
        p._toggle_play_selection()
        p.after.assert_not_called()


class TestOnAiAnalysisComplete(unittest.TestCase):
    def test_enables_report_button(self):
        p = _make()
        p._btn_ai_show_report = MagicMock()
        p._ai_results = []
        p._add_moments_to_queue = MagicMock()
        p._show_ai_report_popup = MagicMock()
        p._populate_results = MagicMock()
        result = [MagicMock()]
        p._on_ai_analysis_complete(result)
        p._btn_ai_show_report.configure.assert_called_with(state="normal")
        self.assertEqual(p._ai_results, result)

    def test_no_results_noop_queue(self):
        p = _make()
        p._btn_ai_show_report = MagicMock()
        p._add_moments_to_queue = MagicMock()
        p._show_ai_report_popup = MagicMock()
        p._populate_results = MagicMock()
        p._on_ai_analysis_complete([])
        p._add_moments_to_queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
