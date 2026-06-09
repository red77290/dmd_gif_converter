import unittest
from unittest.mock import MagicMock

class MockVar:
    def __init__(self, value=0.0):
        self._val = value
        self.set = MagicMock(side_effect=self._internal_set)
        self.get = MagicMock(side_effect=self._internal_get)
    def _internal_set(self, val):
        self._val = val
    def _internal_get(self):
        return self._val

class TestAiMomentsPanelLogic(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        
        # Mock variables
        self.app.v_playhead = MockVar(0.0)
        self.app.v_manual_start = MockVar(0.0)
        self.app.v_manual_end = MockVar(5.0)
        
        self.app._lbl_selection = MagicMock()
        
        # We need to extract the methods from the mixin to test them independently
        from src.ui.panels.ai_moments import AiMomentsPanelMixin
        self.set_in_point = AiMomentsPanelMixin._set_in_point.__get__(self.app)
        self.set_out_point = AiMomentsPanelMixin._set_out_point.__get__(self.app)
        self.toggle_play_selection = AiMomentsPanelMixin._toggle_play_selection.__get__(self.app)

    def test_set_in_point_normal(self):
        self.app.v_playhead.set(2.0)
        
        self.set_in_point()
        
        self.app.v_manual_start.set.assert_called_with(2.0)
        self.app.v_manual_end.set.assert_not_called()
        self.app._lbl_selection.configure.assert_called()

    def test_set_in_point_pushes_end_point(self):
        self.app.v_playhead.set(6.0)
        
        self.set_in_point()
        
        self.app.v_manual_end.set.assert_called_with(7.0)
        self.app.v_manual_start.set.assert_called_with(6.0)

    def test_set_out_point_normal(self):
        self.app.v_playhead.set(4.0)
        self.app.v_manual_start.set(2.0)
        
        self.set_out_point()
        
        self.app.v_manual_end.set.assert_called_with(4.0)
        # 1 call from setUp, no new calls from method
        self.assertEqual(self.app.v_manual_start.set.call_count, 1)

    def test_set_out_point_pushes_start_point(self):
        self.app.v_playhead.set(2.0)
        self.app.v_manual_start.set(5.0)
        
        self.set_out_point()
        
        self.app.v_manual_start.set.assert_called_with(1.0)
        self.app.v_manual_end.set.assert_called_with(2.0)

    def test_toggle_play_selection_starts_play(self):
        self.app._ai_preview_cap = MagicMock()
        self.app._ai_preview_cap.get.return_value = 30.0
        self.app._is_playing_selection = False
        self.app._btn_play_selection = MagicMock()
        
        self.toggle_play_selection()
        
        self.assertTrue(self.app._is_playing_selection)
        self.app.after.assert_called()

    def test_toggle_play_selection_stops_play(self):
        self.app._ai_preview_cap = MagicMock()
        self.app._is_playing_selection = True
        self.app._btn_play_selection = MagicMock()
        
        self.toggle_play_selection()
        
        self.assertFalse(self.app._is_playing_selection)

if __name__ == "__main__":
    unittest.main()
