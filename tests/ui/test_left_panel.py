import pytest
from unittest.mock import patch, MagicMock
from src.ui.panels.left_panel import LeftPanel
from src.ui.models.application_state import ApplicationState

def _make_panel():
    import customtkinter as ctk
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
         patch.object(LeftPanel, "_build_ui", return_value=None, create=True), \
         patch.object(LeftPanel, "_style_treeview", return_value=None):
        panel = LeftPanel(MagicMock(), ApplicationState())
        panel._tree = MagicMock()
        panel._btn_add_files = MagicMock()
        panel._btn_add_folder = MagicMock()
        panel._btn_clear = MagicMock()
        return panel

def test_left_panel_instantiation():
    panel = _make_panel()
    assert panel is not None

@patch('src.ui.panels.left_panel.filedialog.askopenfilenames')
def test_left_panel_add_files(mock_askfiles):
    mock_askfiles.return_value = ("/test/file1.mp4", "/test/file2.gif")
    panel = _make_panel()
    with patch.object(panel, '_batch_insert') as mock_add:
        panel.add_files()
        assert mock_add.call_count == 1
