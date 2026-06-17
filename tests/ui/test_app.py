import pytest
from unittest.mock import patch, MagicMock
from src.ui.app import DMDConverterApp

def _make_app():
    import customtkinter as ctk
    with patch.object(ctk.CTk, "__init__", return_value=None), \
         patch.object(DMDConverterApp, "title", return_value=None), \
         patch.object(DMDConverterApp, "geometry", return_value=None), \
         patch.object(DMDConverterApp, "minsize", return_value=None), \
         patch.object(DMDConverterApp, "protocol", return_value=None), \
         patch.object(DMDConverterApp, "_build_ui", return_value=None), \
         patch.object(DMDConverterApp, "_poll_logs", return_value=None):
        app = DMDConverterApp()
        return app

def test_app_instantiation():
    app = _make_app()
    assert app is not None
