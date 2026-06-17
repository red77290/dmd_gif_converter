import pytest
from unittest.mock import patch, MagicMock
from src.ui.preview.preview_player import PreviewPlayer
import customtkinter as ctk

def _make_player():
    with patch.object(ctk.CTkScrollableFrame, "__init__", return_value=None), \
         patch.object(PreviewPlayer, "_build_preview_area", return_value=None), \
         patch.object(PreviewPlayer, "grid_columnconfigure", return_value=None), \
         patch.object(PreviewPlayer, "grid_rowconfigure", return_value=None), \
         patch.object(PreviewPlayer, "bind", return_value=None):
        player = PreviewPlayer(MagicMock(), MagicMock())
        player._canvas = MagicMock()
        return player

def test_preview_player_instantiation():
    player = _make_player()
    assert player is not None
