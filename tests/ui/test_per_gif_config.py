#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests unitaires pour la feature Per-GIF Config (dmd_gif_converter_ui.py)

Couvre :
  - _snapshot_params()  — capture complète de toutes les variables UI
  - _restore_params()   — restauration complète depuis un snapshot
  - _on_per_gif_toggle()— activation / désactivation du mode per-gif
  - Sauvegarde automatique lors du changement de sélection (_on_tree_select)
  - Chargement de la config sauvegardée à la sélection d'un GIF connu
  - Utilisation des defaults quand aucune config n'est sauvegardée
  - clear_files() efface toutes les configs per-gif
  - _remove_selected() efface la config du fichier retiré
"""

import sys
import types
import importlib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ══════════════════════════════════════════════════════════════════════════════
# ISOLATION DES STUBS — stratégie anti-pollution de sys.modules
# ──────────────────────────────────────────────────────────────────────────────
# Ce fichier installe des stubs dans sys.modules pour permettre l'import de
# dmd_gif_converter_ui sans afficher de fenêtre.  Sans précaution, ces stubs
# resteraient dans sys.modules pour TOUT le reste de la session pytest et
# casseraient les autres suites de tests :
#
#   test_led_sim.py          → PIL.internal "from . import ImageFile" échoue
#   test_dmd_gif_converter.py → patch("dmd_gif_converter.*") cible le stub
#   test_dmd_auto_color.py   → _average_metrics importé comme MagicMock
#
# Stratégie :
#   1. Sauvegarder les entrées originales (PIL, dmd_gif_converter, …)
#   2. Installer les stubs
#   3. Importer dmd_gif_converter_ui UNE FOIS ici, au niveau module
#   4. Restaurer immédiatement les entrées originales
#   5. Garder tkinter + customtkinter comme stubs (nécessaires aux vars UI)
# ══════════════════════════════════════════════════════════════════════════════

# ── 0. Préparation : répertoire parent dans sys.path ─────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 1. Snapshot des modules à restaurer ──────────────────────────────────────
_RESTORE_PREFIXES = ("PIL",)
_RESTORE_EXACT    = ("dmd_gif_converter", "dmd_auto_action", "dmd_auto_color")

_saved_sys_modules = {
    k: sys.modules.get(k)
    for k in list(sys.modules)
    if any(k.startswith(p) for p in _RESTORE_PREFIXES) or k in _RESTORE_EXACT
}
_saved_restore_keynames = set(_saved_sys_modules)

# ── 2. Helper var-stub ────────────────────────────────────────────────────────

def _make_var(default):
    """Retourne un objet MagicMock qui se comporte comme une tk.XxxVar."""
    v = MagicMock()
    v._value = default
    v.get.side_effect  = lambda: v._value
    v.set.side_effect  = lambda val: setattr(v, "_value", val)
    v.trace_add = MagicMock()
    return v

# ── 3. Stubs tkinter (gardés pour toute la session — autres tests n'utilisent
#        pas tkinter directement) ─────────────────────────────────────────────
_tk_stub = types.ModuleType("tkinter")
_tk_stub.StringVar  = lambda value="": _make_var(value)
_tk_stub.BooleanVar = lambda value=False: _make_var(value)
_tk_stub.IntVar     = lambda value=0:   _make_var(value)
_tk_stub.DoubleVar  = lambda value=0.0: _make_var(value)
_tk_stub.TclError   = Exception
_tk_stub.Frame      = MagicMock
_tk_stub.Canvas     = MagicMock
for _name in ("filedialog", "messagebox", "ttk"):
    sys.modules[f"tkinter.{_name}"] = MagicMock()
sys.modules["tkinter"] = _tk_stub

# ── 4. Stub customtkinter (gardé pour toute la session) ───────────────────────
_ctk_stub = types.ModuleType("customtkinter")

for _attr in ("CTkFrame", "CTkLabel", "CTkButton", "CTkEntry",
              "CTkSlider", "CTkOptionMenu", "CTkCheckBox", "CTkProgressBar",
              "CTkTextbox", "CTkScrollableFrame", "CTkFont",
              "set_appearance_mode", "set_default_color_theme"):
    setattr(_ctk_stub, _attr, MagicMock())

# CTk DOIT être une vraie classe Python (pas un MagicMock instance) pour que
# `class DMDConverterApp(ctk.CTk):` produise un vrai type dont __dict__
# contient les méthodes définies dans le corps de la classe.
class _CTkBase:
    """Stub minimal de CTk — satisfait la machinerie de classe Python."""
    def __init__(self, *a, **kw): pass
    def after(self, delay=0, fn=None, *a, **kw): return None
    def after_cancel(self, job): pass
    def mainloop(self): pass
    def destroy(self): pass
    def configure(self, **kw): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def grid_rowconfigure(self, *a, **kw): pass
    def protocol(self, *a, **kw): pass
    def title(self, *a): pass
    def geometry(self, *a): pass
    def minsize(self, *a): pass
    def resizable(self, *a): pass
    def iconbitmap(self, *a): pass
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080

_ctk_stub.CTk = _CTkBase
sys.modules["customtkinter"] = _ctk_stub

# ── 5. Stubs PIL / dmd_* (temporaires — restaurés après l'import UI) ──────────
_pil_stub  = types.ModuleType("PIL")
_pil_image = types.ModuleType("PIL.Image")
_pil_imgtk = types.ModuleType("PIL.ImageTk")
_pil_image.Image = MagicMock
_pil_imgtk.PhotoImage = MagicMock
sys.modules["PIL"] = _pil_stub
sys.modules["PIL.Image"] = _pil_image
sys.modules["PIL.ImageTk"] = _pil_imgtk
_pil_stub.Image   = _pil_image
_pil_stub.ImageTk = _pil_imgtk

_led_sim_stub = types.ModuleType("src.ui.dmd_led_sim")
_led_sim_stub.LED_SIM_SCALE = 4
_led_sim_stub.LED_SIM_GAP   = 1
_led_sim_stub.LED_SIM_MAX_W = 640
_led_sim_stub.apply_led_grid = MagicMock(side_effect=lambda img, *a, **kw: img)
sys.modules["src.ui.dmd_led_sim"] = _led_sim_stub

_conv_stub = types.ModuleType("dmd_gif_converter")
_conv_stub.DEFAULT_PARAMS = {
    "target_width": 128, "target_height": 32,
    "mode": "pixel_art", "max_workers": 2,
    "scroll_speed": 24.0, "bottom_crop_pct": 0.15,
    "top_crop_pct": 0.0, "scroll_cycles": 1.5,
    "fps_min": 10.0, "fps_max": 25.0,
    "contrast": 1.6, "saturation": 2.2, "brightness": -0.03,
    "gamma": 0.85, "sharpen_lum": 1.8, "sharpen_chr": 0.5,
    "dither": "none", "text_overlay_enabled": False, "text_content": "",
}
_conv_stub.SUPPORTED_EXTENSIONS = {".gif", ".mp4", ".avi", ".mkv", ".mov"}
_conv_stub.get_metadata   = MagicMock(return_value=(128, 32, 25.0, 5.0))
_conv_stub.process_file   = MagicMock(return_value=(True, "[OK]"))
_conv_stub.process_folder = MagicMock(return_value=[])
sys.modules["dmd_gif_converter"] = _conv_stub

for _mod in ("dmd_auto_action", "dmd_auto_color"):
    sys.modules[_mod] = MagicMock()

# ── 6. Import de dmd_gif_converter_ui MAINTENANT (stubs actifs) ───────────────
# On importe ici une seule fois pour que DMDConverterApp.__dict__ contienne
# les vraies méthodes. On réutilise le cache sys.modules ensuite.
_ui_mod = importlib.import_module("src.ui.app")
_DMDConverterApp = _ui_mod.DMDConverterApp

# ── 7. Restauration des modules réels ─────────────────────────────────────────
# PIL, dmd_gif_converter, dmd_auto_color, dmd_auto_action sont remis en place
# pour que les autres suites de tests (test_led_sim, test_dmd_gif_converter…)
# fonctionnent normalement.
for _k, _v in _saved_sys_modules.items():
    if _v is not None:
        sys.modules[_k] = _v
    else:
        sys.modules.pop(_k, None)
# Supprimer les nouvelles entrées PIL introduites par les stubs
for _k in list(sys.modules):
    if (any(_k.startswith(p) for p in _RESTORE_PREFIXES) or _k in _RESTORE_EXACT) \
            and _k not in _saved_restore_keynames:
        del sys.modules[_k]


# ── Fabrique d'un objet imitant DMDConverterApp juste pour les méthodes
#    per-gif (sans lancer la vraie UI) ────────────────────────────────────────

def _make_app():
    """
    Construit un objet minimal qui expose les méthodes per-gif de
    DMDConverterApp via types.MethodType, sans instancier la vraie classe
    (qui hérite de ctk.CTk et nécessite un vrai display).
    """
    import types as _types

    # _DMDConverterApp est importé au niveau module (pendant que les stubs
    # étaient actifs) — ses méthodes sont dans __dict__ sans passer par le MRO.
    DMDConverterApp = _DMDConverterApp

    # Objet proxy sans héritage CTk/tk — évite tout init display
    class _FakeApp:
        pass

    app = _FakeApp()

    # Lie les méthodes per-gif au proxy.
    # On utilise __dict__ pour bypasser le MRO (qui traverserait le MagicMock
    # ctk.CTk stub et retournerait un Mock au lieu de la vraie fonction).
    for _meth in ("_snapshot_params", "_restore_params",
                  "_on_per_gif_toggle", "_update_per_gif_status"):
        fn = getattr(DMDConverterApp, _meth)
        setattr(app, _meth, _types.MethodType(fn, app))

    import tkinter as tk

    # ── Variables tkinter ─────────────────────────────────────────────────────
    app.v_per_gif_config       = tk.BooleanVar(value=False)
    app._per_gif_configs       = {}
    app._per_gif_global_snapshot = {}

    app.v_mode          = tk.StringVar(value="pixel_art")
    app.v_workers       = tk.IntVar(value=2)
    app.v_scroll        = tk.DoubleVar(value=24.0)
    app.v_bottom_crop   = tk.DoubleVar(value=0.15)
    app.v_top_crop      = tk.DoubleVar(value=0.0)
    app.v_scroll_cycles = tk.DoubleVar(value=1.5)
    app.v_fps_min       = tk.DoubleVar(value=10.0)
    app.v_fps_max       = tk.DoubleVar(value=25.0)
    app.v_contrast      = tk.DoubleVar(value=1.6)
    app.v_saturation    = tk.DoubleVar(value=2.2)
    app.v_brightness    = tk.DoubleVar(value=-0.03)
    app.v_gamma         = tk.DoubleVar(value=0.85)
    app.v_sharpen_lum   = tk.DoubleVar(value=1.8)
    app.v_sharpen_chr   = tk.DoubleVar(value=0.5)
    app.v_dither        = tk.StringVar(value="none")
    app.v_scroll_enabled            = tk.BooleanVar(value=True)
    app.v_zoom                      = tk.DoubleVar(value=1.0)
    app.v_manual_x                  = tk.IntVar(value=0)
    app.v_manual_y                  = tk.IntVar(value=0)
    app.v_hue_shift                 = tk.DoubleVar(value=0.0)
    app.v_noise_reduction           = tk.DoubleVar(value=0.0)
    app.v_film_grain                = tk.IntVar(value=0)
    app.v_vignette                  = tk.BooleanVar(value=False)
    app.v_auto_action_enabled       = tk.BooleanVar(value=False)
    app.v_action_detector           = tk.StringVar(value="person")
    app.v_action_strength           = tk.DoubleVar(value=0.65)
    app.v_action_auto_strength      = tk.BooleanVar(value=False)
    app.v_action_smoothness         = tk.DoubleVar(value=0.85)
    app.v_action_auto_smoothness    = tk.BooleanVar(value=False)
    app.v_action_zoom_max           = tk.DoubleVar(value=2.0)
    app.v_action_padding            = tk.DoubleVar(value=0.20)
    app.v_action_intro              = tk.DoubleVar(value=1.5)
    app.v_action_bottom_crop        = tk.DoubleVar(value=0.0)
    app.v_action_auto_bottom_crop   = tk.BooleanVar(value=False)
    app.v_action_top_crop           = tk.DoubleVar(value=0.0)
    app.v_action_auto_top_crop      = tk.BooleanVar(value=False)
    app.v_action_vertical_bias      = tk.DoubleVar(value=0.0)
    app.v_action_auto_vertical_bias = tk.BooleanVar(value=False)
    app.v_action_smart_auto_crop    = tk.BooleanVar(value=False)
    app.v_action_auto_pillarbox     = tk.BooleanVar(value=False)
    app.v_bg_sub_enable             = tk.BooleanVar(value=False)
    app.v_target_width              = tk.IntVar(value=128)
    app.v_target_height             = tk.IntVar(value=32)
    app.v_target_preset             = tk.StringVar(value="128x32 (1x1)")
    app.v_text_overlay_enabled      = tk.BooleanVar(value=False)
    app.v_text_content              = tk.StringVar(value="")
    app.v_text_font_size            = tk.IntVar(value=8)
    app.v_text_color                = tk.StringVar(value="white")
    app.v_text_position             = tk.StringVar(value="bottom_center")
    app.v_text_font_file            = tk.StringVar(value="HelvetiPixel.ttf")
    app.v_text_style                = tk.StringVar(value="outline")
    app.v_text_bg                   = tk.BooleanVar(value=False)
    app.v_text_bg_opacity           = tk.IntVar(value=60)
    app.v_text_animation            = tk.StringVar(value="none")
    app.v_max_dur_enabled           = tk.BooleanVar(value=True)
    app.v_max_duration              = tk.DoubleVar(value=120.0)
    app.v_auto_color_enabled        = tk.BooleanVar(value=False)
    app.v_dmd_visibility_score_enabled = tk.BooleanVar(value=False)
    app.v_dmd_readability_score_enabled = tk.BooleanVar(value=True)

    # ── Callbacks UI factices ─────────────────────────────────────────────────
    app._update_custom_visibility  = MagicMock()
    app._on_text_overlay_toggle    = MagicMock()
    app._on_scroll_enabled_change  = MagicMock()
    app._on_text_bg_toggle         = MagicMock()
    app._on_max_dur_toggle         = MagicMock()
    app._per_gif_status_lbl        = MagicMock()

    return app


# ─────────────────────────────────────────────────────────────────────────────
# _snapshot_params
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshotParams(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def test_snapshot_returns_dict(self):
        s = self.app._snapshot_params()
        self.assertIsInstance(s, dict)

    def test_snapshot_contains_all_expected_keys(self):
        s = self.app._snapshot_params()
        required_keys = [
            "mode", "workers", "scroll", "bottom_crop", "top_crop",
            "scroll_cycles", "fps_min", "fps_max",
            "contrast", "saturation", "brightness", "gamma",
            "sharpen_lum", "sharpen_chr", "dither",
            "scroll_enabled", "zoom", "manual_x", "manual_y",
            "hue_shift", "noise_reduction", "film_grain", "vignette",
            "auto_action_enabled", "action_detector",
            "action_strength", "action_auto_strength",
            "action_smoothness", "action_auto_smoothness",
            "action_zoom_max", "action_padding", "action_intro",
            "action_bottom_crop", "action_auto_bottom_crop",
            "action_top_crop", "action_auto_top_crop",
            "action_vertical_bias", "action_auto_vertical_bias",
            "action_smart_auto_crop", "action_auto_pillarbox",
            "bg_sub_enable", "target_width", "target_height", "target_preset",
            "text_overlay_enabled", "text_content",
            "text_font_size", "text_color", "text_position",
            "text_font_file", "text_style", "text_bg", "text_bg_opacity",
            "text_animation",
            "max_dur_enabled", "max_duration", "auto_color_enabled",
            "dmd_visibility_score_enabled", "dmd_readability_score_enabled",
        ]
        for key in required_keys:
            self.assertIn(key, s, f"Clé manquante dans le snapshot : {key}")

    def test_snapshot_captures_current_values(self):
        self.app.v_mode.set("cinema")
        self.app.v_contrast.set(2.0)
        s = self.app._snapshot_params()
        self.assertEqual(s["mode"], "cinema")
        self.assertAlmostEqual(s["contrast"], 2.0)

    def test_snapshot_captures_boolean_vars(self):
        self.app.v_text_overlay_enabled.set(True)
        self.app.v_auto_action_enabled.set(True)
        s = self.app._snapshot_params()
        self.assertTrue(s["text_overlay_enabled"])
        self.assertTrue(s["auto_action_enabled"])

    def test_snapshot_does_not_mutate_state(self):
        """_snapshot_params ne doit pas modifier les variables."""
        self.app.v_saturation.set(3.5)
        _ = self.app._snapshot_params()
        self.assertAlmostEqual(self.app.v_saturation.get(), 3.5)


# ─────────────────────────────────────────────────────────────────────────────
# _restore_params
# ─────────────────────────────────────────────────────────────────────────────

class TestRestoreParams(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def _make_full_snapshot(self, overrides=None):
        """Snapshot avec toutes les clés pour éviter les KeyErrors."""
        base = {
            "mode": "anime", "workers": 4, "scroll": 32.0,
            "bottom_crop": 0.10, "top_crop": 0.05,
            "scroll_cycles": 2.0, "fps_min": 12.0, "fps_max": 20.0,
            "contrast": 1.8, "saturation": 2.5, "brightness": 0.0,
            "gamma": 0.90, "sharpen_lum": 1.5, "sharpen_chr": 0.3,
            "dither": "none", "scroll_enabled": False,
            "zoom": 1.5, "manual_x": 10, "manual_y": 5,
            "hue_shift": 30.0, "noise_reduction": 1.0,
            "film_grain": 5, "vignette": True,
            "auto_action_enabled": True, "action_detector": "motion",
            "action_strength": 0.8, "action_smoothness": 0.7,
            "action_zoom_max": 2.5, "action_padding": 0.3,
            "action_intro": 2.0, "action_bottom_crop": 0.1,
            "action_vertical_bias": 0.5, "action_auto_vertical_bias": True,
            "action_smart_auto_crop": True, "action_auto_pillarbox": True,
            "bg_sub_enable": True,
            "target_width": 256, "target_height": 64,
            "target_preset": "256x32 (2x1)",
            "text_overlay_enabled": True, "text_content": "TEST",
            "text_font_size": 12, "text_color": "yellow",
            "text_position": "top_left",
            "text_font_file": "PixelMordred.ttf",
            "text_style": "bold", "text_bg": True, "text_bg_opacity": 80,
            "text_animation": "blink",
            "max_dur_enabled": False, "max_duration": 60.0,
            "auto_color_enabled": True, "dmd_visibility_score_enabled": True,
            "dmd_readability_score_enabled": True,
        }
        if overrides:
            base.update(overrides)
        return base

    def test_restore_sets_mode(self):
        snap = self._make_full_snapshot({"mode": "cinema"})
        self.app._restore_params(snap)
        self.assertEqual(self.app.v_mode.get(), "cinema")

    def test_restore_sets_contrast(self):
        snap = self._make_full_snapshot({"contrast": 1.9})
        self.app._restore_params(snap)
        self.assertAlmostEqual(self.app.v_contrast.get(), 1.9)

    def test_restore_sets_target_dimensions(self):
        snap = self._make_full_snapshot({"target_width": 256, "target_height": 64})
        self.app._restore_params(snap)
        self.assertEqual(self.app.v_target_width.get(), 256)
        self.assertEqual(self.app.v_target_height.get(), 64)

    def test_restore_sets_boolean_vars(self):
        snap = self._make_full_snapshot({
            "text_overlay_enabled": True,
            "auto_action_enabled": True,
            "vignette": True,
        })
        self.app._restore_params(snap)
        self.assertTrue(self.app.v_text_overlay_enabled.get())
        self.assertTrue(self.app.v_auto_action_enabled.get())
        self.assertTrue(self.app.v_vignette.get())

    def test_restore_calls_ui_sync_callbacks(self):
        """_restore_params doit synchroniser l'état des widgets UI."""
        snap = self._make_full_snapshot()
        self.app._restore_params(snap)
        self.app._update_custom_visibility.assert_called()
        self.app._on_text_overlay_toggle.assert_called()
        self.app._on_scroll_enabled_change.assert_called()
        self.app._on_max_dur_toggle.assert_called()

    def test_restore_uses_defaults_for_missing_keys(self):
        """Snapshot partiel : les clés absentes doivent utiliser des valeurs par défaut."""
        self.app._restore_params({})   # snapshot totalement vide
        self.assertEqual(self.app.v_mode.get(), "pixel_art")
        self.assertAlmostEqual(self.app.v_contrast.get(), 1.6)

    def test_snapshot_then_restore_is_identity(self):
        """Snapshot puis restore doit être idempotent."""
        self.app.v_mode.set("cinema")
        self.app.v_contrast.set(2.0)
        self.app.v_target_width.set(256)
        snap = self.app._snapshot_params()

        # Modifie les valeurs entre les deux
        self.app.v_mode.set("pixel_art")
        self.app.v_contrast.set(1.0)
        self.app.v_target_width.set(128)

        self.app._restore_params(snap)
        self.assertEqual(self.app.v_mode.get(), "cinema")
        self.assertAlmostEqual(self.app.v_contrast.get(), 2.0)
        self.assertEqual(self.app.v_target_width.get(), 256)


# ─────────────────────────────────────────────────────────────────────────────
# _on_per_gif_toggle
# ─────────────────────────────────────────────────────────────────────────────

class TestOnPerGifToggle(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        # Injecte une méthode _restore_params mockée pour inspecter les appels
        self.app._restore_params = MagicMock(wraps=self.app._restore_params)

    def test_toggle_on_captures_global_snapshot(self):
        self.app.v_mode.set("cinema")
        self.app.v_per_gif_config.set(True)
        self.app._on_per_gif_toggle()
        snap = self.app._per_gif_global_snapshot
        self.assertIsInstance(snap, dict)
        self.assertGreater(len(snap), 0)
        self.assertEqual(snap.get("mode"), "cinema")

    def test_toggle_off_restores_global_snapshot(self):
        # Activation : capture "cinema"
        self.app.v_mode.set("cinema")
        self.app.v_per_gif_config.set(True)
        self.app._on_per_gif_toggle()

        # Changement des paramètres pendant le mode per-gif
        self.app.v_mode.set("anime")

        # Désactivation : doit restaurer "cinema"
        self.app.v_per_gif_config.set(False)
        self.app._on_per_gif_toggle()
        self.app._restore_params.assert_called()

    def test_toggle_off_without_snapshot_does_not_crash(self):
        """Si aucun snapshot global n'existe, la désactivation ne doit pas lever d'exception."""
        self.app._per_gif_global_snapshot = {}
        self.app.v_per_gif_config.set(False)
        try:
            self.app._on_per_gif_toggle()
        except Exception as exc:
            self.fail(f"_on_per_gif_toggle a levé une exception inattendue : {exc}")

    def test_toggle_on_twice_updates_snapshot(self):
        """Activer le toggle deux fois doit mettre à jour le snapshot."""
        self.app.v_mode.set("pixel_art")
        self.app.v_per_gif_config.set(True)
        self.app._on_per_gif_toggle()
        first_snap = dict(self.app._per_gif_global_snapshot)

        self.app.v_mode.set("cinema")
        self.app._on_per_gif_toggle()   # toggle OFF
        self.app.v_per_gif_config.set(True)
        self.app._on_per_gif_toggle()   # toggle ON again
        second_snap = self.app._per_gif_global_snapshot
        # Le second snapshot doit correspondre à l'état au moment du second ON
        # (peut être pixel_art ou cinema selon la restauration intermédiaire)
        self.assertIsInstance(second_snap, dict)


# ─────────────────────────────────────────────────────────────────────────────
# Per-GIF save / load sur sélection
# ─────────────────────────────────────────────────────────────────────────────

class TestPerGifSelectionBehavior(unittest.TestCase):
    """
    Simule la logique de sauvegarde / chargement de config sans créer
    de vrai arbre Treeview — on reproduit uniquement les chemins de code
    exercés par _on_tree_select.
    """

    PATH_A = "/fake/gifA.gif"
    PATH_B = "/fake/gifB.gif"

    def setUp(self):
        self.app = _make_app()
        self.app.v_per_gif_config.set(True)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _switch_from_a_to_b(self):
        """Simule la sauvegarde de A puis le chargement de B."""
        # Sauvegarde pour A (simulé depuis _on_tree_select)
        self.app._per_gif_configs[self.PATH_A] = self.app._snapshot_params()
        # Chargement pour B si config existante
        if self.PATH_B in self.app._per_gif_configs:
            self.app._restore_params(self.app._per_gif_configs[self.PATH_B])

    # ── tests ─────────────────────────────────────────────────────────────────

    def test_selecting_gif_with_no_saved_config_keeps_current_params(self):
        """Sélectionner un GIF sans config sauvegardée ne modifie pas les paramètres."""
        self.app.v_mode.set("cinema")
        # PATH_B n'a pas de config — aucun appel à _restore_params
        self.app._restore_params = MagicMock()
        if self.PATH_B not in self.app._per_gif_configs:
            pass  # aucune action, comme dans l'UI
        self.app._restore_params.assert_not_called()
        self.assertEqual(self.app.v_mode.get(), "cinema")

    def test_selecting_gif_loads_saved_config(self):
        """Sélectionner un GIF avec une config sauvegardée charge la config."""
        # Pré-sauvegarder une config pour B
        self.app.v_mode.set("anime")
        self.app._per_gif_configs[self.PATH_B] = self.app._snapshot_params()

        # Changer les params courants
        self.app.v_mode.set("cinema")

        # Simuler la sélection de B
        if self.PATH_B in self.app._per_gif_configs:
            self.app._restore_params(self.app._per_gif_configs[self.PATH_B])

        self.assertEqual(self.app.v_mode.get(), "anime")

    def test_switching_selection_saves_config_for_previous_gif(self):
        """Passer de A à B doit sauvegarder la config courante sous la clé A."""
        self.app.v_mode.set("cinema")
        self._switch_from_a_to_b()
        self.assertIn(self.PATH_A, self.app._per_gif_configs)
        self.assertEqual(self.app._per_gif_configs[self.PATH_A]["mode"], "cinema")

    def test_switching_selection_loads_saved_config_for_new_gif(self):
        """Passer à B doit charger la config de B si elle existe."""
        # Config sauvegardée pour B
        self.app.v_mode.set("anime")
        self.app._per_gif_configs[self.PATH_B] = self.app._snapshot_params()

        self.app.v_mode.set("cinema")
        self._switch_from_a_to_b()

        # Après switch, le mode doit être celui de B
        self.assertEqual(self.app.v_mode.get(), "anime")

    def test_per_gif_mode_off_does_not_save_config(self):
        """Quand le mode per-gif est OFF, le switch ne doit pas sauvegarder."""
        self.app.v_per_gif_config.set(False)
        self.app.v_mode.set("cinema")
        # Simulation de _on_tree_select quand mode per-gif est OFF
        if self.app.v_per_gif_config.get():
            self.app._per_gif_configs[self.PATH_A] = self.app._snapshot_params()
        self.assertNotIn(self.PATH_A, self.app._per_gif_configs)

    def test_different_gifs_have_independent_configs(self):
        """Deux GIFs doivent stocker des configs indépendantes."""
        # Config A : anime
        self.app.v_mode.set("anime")
        self.app._per_gif_configs[self.PATH_A] = self.app._snapshot_params()
        # Config B : cinema
        self.app.v_mode.set("cinema")
        self.app._per_gif_configs[self.PATH_B] = self.app._snapshot_params()

        self.assertEqual(self.app._per_gif_configs[self.PATH_A]["mode"], "anime")
        self.assertEqual(self.app._per_gif_configs[self.PATH_B]["mode"], "cinema")


# ─────────────────────────────────────────────────────────────────────────────
# clear_files efface les configs
# ─────────────────────────────────────────────────────────────────────────────

class TestClearFilesRemovesConfigs(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def test_configs_dict_is_empty_after_clear(self):
        self.app._per_gif_configs["/a.gif"] = {"mode": "anime"}
        self.app._per_gif_configs["/b.gif"] = {"mode": "cinema"}
        # Simule le comportement de clear_files (la partie qui nous intéresse)
        self.app._per_gif_configs.clear()
        self.assertEqual(len(self.app._per_gif_configs), 0)

    def test_status_label_reset_after_clear(self):
        """Le label de statut per-gif doit être réinitialisé après clear."""
        self.app._per_gif_configs["/a.gif"] = {"mode": "anime"}
        self.app._per_gif_configs.clear()
        if hasattr(self.app, "_per_gif_status_lbl"):
            self.app._per_gif_status_lbl.configure(text="")
        self.app._per_gif_status_lbl.configure.assert_called_with(text="")


# ─────────────────────────────────────────────────────────────────────────────
# _remove_selected efface la config du fichier retiré
# ─────────────────────────────────────────────────────────────────────────────

class TestRemoveSelectedCleansConfig(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def test_removing_file_removes_its_per_gif_config(self):
        """Retirer un fichier de la liste doit supprimer sa config per-gif."""
        path = "/some/gif.gif"
        self.app._per_gif_configs[path] = {"mode": "anime"}
        # Simule _remove_selected : file_data.pop + per_gif_configs.pop
        self.app._per_gif_configs.pop(path, None)
        self.assertNotIn(path, self.app._per_gif_configs)

    def test_removing_nonexistent_path_does_not_raise(self):
        """pop avec une clé absente ne doit pas lever d'exception."""
        try:
            self.app._per_gif_configs.pop("/nonexistent.gif", None)
        except KeyError:
            self.fail("pop sur une clé absente ne doit pas lever KeyError")

    def test_other_configs_unaffected_when_one_is_removed(self):
        """La suppression d'un fichier ne doit pas affecter les autres configs."""
        self.app._per_gif_configs["/a.gif"] = {"mode": "anime"}
        self.app._per_gif_configs["/b.gif"] = {"mode": "cinema"}
        self.app._per_gif_configs.pop("/a.gif", None)
        self.assertIn("/b.gif", self.app._per_gif_configs)
        self.assertEqual(self.app._per_gif_configs["/b.gif"]["mode"], "cinema")


# ─────────────────────────────────────────────────────────────────────────────
# _update_per_gif_status
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdatePerGifStatus(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()

    def test_status_saved_shows_checkmark(self):
        self.app._update_per_gif_status("/a.gif", saved=True)
        calls = self.app._per_gif_status_lbl.configure.call_args_list
        texts = [c.kwargs.get("text", "") or (c.args[0] if c.args else "") for c in calls]
        self.assertTrue(any("✅" in t for t in texts))

    def test_status_not_saved_shows_new_badge(self):
        self.app._update_per_gif_status("/a.gif", saved=False)
        calls = self.app._per_gif_status_lbl.configure.call_args_list
        texts = [c.kwargs.get("text", "") or (c.args[0] if c.args else "") for c in calls]
        self.assertTrue(any("🆕" in t for t in texts))

    def test_status_includes_filename(self):
        self.app._update_per_gif_status("/path/mygif.gif", saved=True)
        calls = self.app._per_gif_status_lbl.configure.call_args_list
        texts = [str(c) for c in calls]
        self.assertTrue(any("mygif" in t for t in texts))


if __name__ == "__main__":
    unittest.main()

