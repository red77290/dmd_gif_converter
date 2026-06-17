import pytest
from unittest.mock import patch, MagicMock
import customtkinter as ctk
import tkinter as tk

tk.BooleanVar = MagicMock
tk.StringVar = MagicMock
tk.IntVar = MagicMock
tk.DoubleVar = MagicMock

from src.ui.panels.ai_moments_panel import AiMomentsPanel
from src.ui.models.application_state import ApplicationState

@pytest.fixture
def app_state():
    return ApplicationState()

def _make_panel():
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
         patch.object(AiMomentsPanel, "_build_ai_moments_panel", return_value=None), \
         patch.object(AiMomentsPanel, "_build_ai_video_selection", return_value=None), \
         patch.object(AiMomentsPanel, "_build_ai_detection_settings", return_value=None):
        panel = AiMomentsPanel(MagicMock(), ApplicationState())
        panel._btn_play_selection = MagicMock()
        panel._btn_add_queue = MagicMock()
        panel._btn_analyze = MagicMock()
        panel._in_point_label = MagicMock()
        panel._out_point_label = MagicMock()
        panel._duration_label = MagicMock()
        panel._quality_label = MagicMock()
        panel._tree = MagicMock()
        panel.after = MagicMock()
        return panel

def test_ai_moments_panel_initialization():
    panel = _make_panel()
    assert panel is not None

@patch('src.ui.panels.ai_moments_panel.filedialog.askopenfilename')
def test_ai_moments_panel_select_video(mock_askfile):
    mock_askfile.return_value = "/dummy/path.mp4"
    panel = _make_panel()
    with patch.object(panel, '_ai_set_video') as mock_set:
        panel._ai_select_video()
        mock_set.assert_called_once_with("/dummy/path.mp4")

@patch('tkinter.messagebox.showwarning')
def test_ai_moments_panel_use_current(mock_show):
    panel = _make_panel()
    panel._selected_iid = "item1"
    panel._file_data = {"item1": "/some/file.mp4"}
    with patch.object(panel, '_ai_set_video') as mock_set:
        panel._ai_use_current_video()
        mock_set.assert_called_once_with("/some/file.mp4")
    
    panel._selected_iid = None
    panel._ai_use_current_video()
    mock_show.assert_called_once()
