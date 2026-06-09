import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk
from src.ui.models.application_state import ApplicationState

class MockVar:
    def __init__(self, value=None):
        self._val = value
    def get(self):
        return self._val
    def set(self, val):
        self._val = val
    def trace_add(self, *args, **kwargs):
        pass  # no-op: trace callbacks not needed in unit tests

class TestApplicationState(unittest.TestCase):
    @patch("tkinter.BooleanVar", side_effect=lambda value=False: MockVar(value))
    @patch("tkinter.IntVar", side_effect=lambda value=0: MockVar(value))
    @patch("tkinter.DoubleVar", side_effect=lambda value=0.0: MockVar(value))
    @patch("tkinter.StringVar", side_effect=lambda value="": MockVar(value))
    def setUp(self, mock_str, mock_dbl, mock_int, mock_bool):
        # By patching the tk vars before init, ApplicationState uses MockVar
        self.app_state = ApplicationState()

    def test_tk_vars_creation(self):
        """Test that Tkinter variables are created for all config fields."""
        self.assertTrue(hasattr(self.app_state, "v_text_overlay_enabled"))
        self.assertIsInstance(self.app_state.v_text_overlay_enabled, MockVar)
        
        self.assertTrue(hasattr(self.app_state, "v_target_width"))
        self.assertIsInstance(self.app_state.v_target_width, MockVar)

        self.assertTrue(hasattr(self.app_state, "v_contrast"))
        self.assertIsInstance(self.app_state.v_contrast, MockVar)

        self.assertTrue(hasattr(self.app_state, "v_mode"))
        self.assertIsInstance(self.app_state.v_mode, MockVar)

    def test_get_set(self):
        """Test getting and setting values via the abstraction layer."""
        self.app_state.set("v_mode", "cinema")
        self.assertEqual(self.app_state.get("v_mode"), "cinema")
        
        self.app_state.set("v_contrast", 2.0)
        self.assertAlmostEqual(self.app_state.get("v_contrast"), 2.0)

        # Setting non-existent key
        self.app_state.set("non_existent", "test")
        self.assertEqual(self.app_state.get("non_existent"), "test")

    def test_snapshot_restore(self):
        """Test that we can snapshot the state and restore it perfectly."""
        # Modify state
        self.app_state.set("v_mode", "anime")
        self.app_state.set("v_text_overlay_enabled", True)
        self.app_state.set("v_target_width", 256)

        # Take snapshot
        snap = self.app_state.snapshot()
        self.assertEqual(snap["v_mode"], "anime")
        self.assertTrue(snap["v_text_overlay_enabled"])
        self.assertEqual(snap["v_target_width"], 256)

        # Modify state again
        self.app_state.set("v_mode", "pixel_art")
        self.app_state.set("v_text_overlay_enabled", False)
        self.app_state.set("v_target_width", 128)

        # Restore
        self.app_state.restore(snap)
        self.assertEqual(self.app_state.get("v_mode"), "anime")
        self.assertTrue(self.app_state.get("v_text_overlay_enabled"))
        self.assertEqual(self.app_state.get("v_target_width"), 256)

    def test_build_params(self):
        """Test building params dictionary strips the prefixes."""
        self.app_state.set("v_mode", "cinema")
        self.app_state.set("v_action_detector", "motion")
        
        params = self.app_state.build_params()
        self.assertIn("mode", params)
        self.assertEqual(params["mode"], "cinema")
        
        self.assertIn("detector", params)
        self.assertEqual(params["detector"], "motion")

if __name__ == "__main__":
    unittest.main()
