import pytest
from unittest.mock import patch, MagicMock
from src.ui.preview.preview_panel import PreviewPanel
from src.ui.models.application_state import ApplicationState
import customtkinter as ctk

def _make_panel():
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
         patch.object(PreviewPanel, "_collect_params", return_value=None, create=True), \
         patch.object(PreviewPanel, "grid_columnconfigure", return_value=None), \
         patch.object(PreviewPanel, "grid_rowconfigure", return_value=None), \
         patch.object(PreviewPanel, "bind", return_value=None), \
         patch('src.ui.preview.preview_controls.PreviewControls.build_top_bar', return_value=MagicMock()), \
         patch('src.ui.preview.preview_controls.PreviewControls.build_bottom_bar', return_value=MagicMock()), \
         patch('src.ui.preview.preview_player.PreviewPlayer', return_value=MagicMock()):
        panel = PreviewPanel(MagicMock(), ApplicationState())
        panel._preview_player = MagicMock()
        return panel

def test_preview_panel_instantiation():
    panel = _make_panel()
    assert panel is not None
