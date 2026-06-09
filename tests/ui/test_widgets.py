"""
Tests unitaires pour src/ui/widgets.py
Vérifie notamment l'API de _InfoBadge pour prévenir les régressions
sur la signature de __init__ (TypeError sur keyword argument 'text').
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, patch


# ---------------------------------------------------------------------------
# Stub factories for Tkinter / CustomTkinter (headless tests)
# ---------------------------------------------------------------------------
def _make_ctk_stub():
    """Return a minimal stub for customtkinter."""
    ctk = types.ModuleType("customtkinter")

    class _Widget:
        def __init__(self, *a, **kw):
            pass
        def bind(self, *a, **kw):
            pass
        def pack(self, **kw):
            pass
        def configure(self, **kw):
            pass

    ctk.CTkLabel = _Widget
    ctk.CTkButton = _Widget
    ctk.CTkFrame = _Widget
    ctk.CTkEntry = _Widget
    ctk.CTkFont = lambda **kw: None
    ctk.set_appearance_mode = lambda *a: None
    ctk.set_default_color_theme = lambda *a: None
    return ctk


def _make_tk_stub():
    """Return a minimal stub for tkinter (only what _InfoBadge needs)."""
    tk = types.ModuleType("tkinter")
    tk.Toplevel = MagicMock
    tk.Label = MagicMock
    tk.Frame = MagicMock
    # Keep real Var classes so other tests that patch them still work
    return tk


# ---------------------------------------------------------------------------
# _BADGE_MODULES: modules to stub for the _InfoBadge import
# ---------------------------------------------------------------------------
_CTK_STUB = _make_ctk_stub()
_TK_STUB  = _make_tk_stub()

_BADGE_PATCHES = {
    "tkinter":       _TK_STUB,
    "customtkinter": _CTK_STUB,
    "src.ui.widgets":   None,  # force re-import with stubs
    "src.ui.constants": None,
}


class TestInfoBadgeAPI(unittest.TestCase):
    """_InfoBadge must NOT accept 'text' as a constructor keyword argument."""

    @classmethod
    def setUpClass(cls):
        # Inject stubs only for this test class; removed in tearDownClass
        cls._saved = {k: sys.modules.get(k) for k in _BADGE_PATCHES}
        for k, v in _BADGE_PATCHES.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        from src.ui.widgets import _InfoBadge
        cls._InfoBadge = _InfoBadge

    @classmethod
    def tearDownClass(cls):
        # Restore original modules
        for k, v in cls._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        # Also evict the stub-compiled widgets module so the next importer gets real one
        sys.modules.pop("src.ui.widgets", None)

    def _make_badge(self, **extra_kwargs):
        parent = MagicMock()
        return self._InfoBadge(parent, **extra_kwargs)

    def test_init_no_text_kwarg_raises_type_error(self):
        """Passing text= to __init__ must raise TypeError (regression guard)."""
        with self.assertRaises(TypeError):
            self._make_badge(text="some tooltip text")

    def test_init_accepts_width(self):
        badge = self._make_badge(width=60)
        self.assertIsNotNone(badge)

    def test_configure_sets_text(self):
        badge = self._make_badge()
        badge.configure(text="hello world")
        self.assertEqual(badge._text, "hello world")

    def test_configure_empty_text(self):
        badge = self._make_badge()
        badge.configure(text="filled")
        badge.configure(text="")
        self.assertEqual(badge._text, "")

    def test_correct_usage_pattern(self):
        parent = MagicMock()
        badge = self._InfoBadge(parent)
        badge.configure(text="When enabled, each GIF can have its own custom settings.")
        badge._lbl = MagicMock()
        badge.pack(side="left", padx=(0, 8))
        badge._lbl.pack.assert_called_once_with(side="left", padx=(0, 8))

    def test_pack_delegates_to_inner_label(self):
        badge = self._make_badge()
        badge._lbl = MagicMock()
        badge.pack(fill="x", pady=4)
        badge._lbl.pack.assert_called_once_with(fill="x", pady=4)


if __name__ == "__main__":
    unittest.main()
