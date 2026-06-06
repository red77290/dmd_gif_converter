"""
AppState — implements IModel.

The single source of truth for all application settings.
Wraps the Tkinter variables and provides a clean get/set/snapshot/restore
interface that can be used by any controller or service without importing Tkinter.
"""
import logging
from copy import deepcopy
from typing import Any, Dict, Optional
import tkinter as tk

from ..interfaces import IModel
from src.converter.core import DEFAULT_PARAMS

logger = logging.getLogger(__name__)

APP_VERSION = "5.0.0"


class AppState(IModel):
    """
    Holds all Tkinter variables and application state.
    Acts as the Model in the MVC architecture.

    Controllers read/write values through get()/set().
    The View binds directly to the Tkinter vars for reactive updates.
    """

    def __init__(self):
        # ── Standard conversion parameters ────────────────────────────────────
        self.v_output_dir    = tk.StringVar(value="")
        self.v_mode          = tk.StringVar(value="pixel_art")
        self.v_workers       = tk.IntVar(value=2)
        self.v_scroll        = tk.DoubleVar(value=24.0)
        self.v_bottom_crop   = tk.DoubleVar(value=0.15)
        self.v_top_crop      = tk.DoubleVar(value=0.0)
        self.v_scroll_cycles = tk.DoubleVar(value=1.5)
        self.v_fps_min       = tk.DoubleVar(value=10.0)
        self.v_fps_max       = tk.DoubleVar(value=25.0)
        self.v_contrast      = tk.DoubleVar(value=1.6)
        self.v_saturation    = tk.DoubleVar(value=2.2)
        self.v_brightness    = tk.DoubleVar(value=-0.03)
        self.v_gamma         = tk.DoubleVar(value=0.85)
        self.v_sharpen_lum   = tk.DoubleVar(value=1.8)
        self.v_sharpen_chr   = tk.DoubleVar(value=0.5)
        self.v_dither        = tk.StringVar(value="none")
        self.v_trim_start    = tk.DoubleVar(value=0.0)
        self.v_trim_end      = tk.DoubleVar(value=0.0)

        # ── Advanced parameters ────────────────────────────────────────────────
        self.v_scroll_enabled  = tk.BooleanVar(value=True)
        self.v_zoom            = tk.DoubleVar(value=1.0)
        self.v_manual_x        = tk.IntVar(value=0)
        self.v_manual_y        = tk.IntVar(value=0)
        self.v_hue_shift       = tk.DoubleVar(value=0.0)
        self.v_noise_reduction = tk.DoubleVar(value=0.0)
        self.v_film_grain      = tk.IntVar(value=0)
        self.v_vignette        = tk.BooleanVar(value=False)

        # ── Auto Action parameters ─────────────────────────────────────────────
        self.v_auto_action_enabled       = tk.BooleanVar(value=False)
        self.v_action_detector           = tk.StringVar(value="person")
        self.v_action_strength           = tk.DoubleVar(value=0.65)
        self.v_action_smoothness         = tk.DoubleVar(value=0.98)
        self.v_action_zoom_max           = tk.DoubleVar(value=2.0)
        self.v_action_padding            = tk.DoubleVar(value=0.20)
        self.v_action_intro              = tk.DoubleVar(value=1.5)
        self.v_action_bottom_crop        = tk.DoubleVar(value=0.0)
        self.v_action_auto_bottom_crop   = tk.BooleanVar(value=False)
        self.v_action_top_crop           = tk.DoubleVar(value=0.0)
        self.v_action_auto_top_crop      = tk.BooleanVar(value=False)
        self.v_action_vertical_bias      = tk.DoubleVar(value=0.0)
        self.v_action_auto_vertical_bias = tk.BooleanVar(value=False)
        self.v_action_smart_auto_crop    = tk.BooleanVar(value=False)
        self.v_bg_sub_enable             = tk.BooleanVar(value=False)
        self.v_dmd_visibility_score_enabled  = tk.BooleanVar(value=False)
        self.v_dmd_readability_score_enabled = tk.BooleanVar(value=True)

        # ── Multi-dalle / Tiling ───────────────────────────────────────────────
        self.v_target_width  = tk.IntVar(value=DEFAULT_PARAMS["target_width"])
        self.v_target_height = tk.IntVar(value=DEFAULT_PARAMS["target_height"])
        self.v_target_preset = tk.StringVar(value="128x32 (1x1)")

        # ── Text Overlay ──────────────────────────────────────────────────────
        self.v_text_overlay_enabled = tk.BooleanVar(value=False)
        self.v_text_content         = tk.StringVar(value="")
        self.v_text_font_size       = tk.IntVar(value=8)
        self.v_text_color           = tk.StringVar(value="white")
        self.v_text_position        = tk.StringVar(value="bottom_center")
        self.v_text_font_file       = tk.StringVar(value="HelvetiPixel.ttf")
        self.v_text_style           = tk.StringVar(value="outline")
        self.v_text_bg              = tk.BooleanVar(value=False)
        self.v_text_bg_opacity      = tk.IntVar(value=60)

        # ── Duration cap ──────────────────────────────────────────────────────
        self.v_max_dur_enabled = tk.BooleanVar(value=True)
        self.v_max_duration    = tk.DoubleVar(value=120.0)

        # ── Auto-colorimetry ──────────────────────────────────────────────────
        self.v_auto_color_enabled = tk.BooleanVar(value=False)

        # ── Let me handle it ──────────────────────────────────────────────────
        self.v_let_me_handle_it = tk.BooleanVar(value=True)

        # ── Per-GIF config ────────────────────────────────────────────────────
        self.v_per_gif_config = tk.BooleanVar(value=False)

        # ── GIF Search ────────────────────────────────────────────────────────
        self.v_search_keyword = tk.StringVar(value="")
        self.v_search_qty     = tk.IntVar(value=10)

        # ── LED pixel simulation ──────────────────────────────────────────────
        self.v_led_sim = tk.BooleanVar(value=True)

        # ── Private non-var state ─────────────────────────────────────────────
        self._file_data:    Dict = {}
        self._file_paths:   set  = set()
        self._converted_data:  Dict = {}
        self._converted_paths: set  = set()
        self._per_gif_configs: Dict = {}
        self._per_gif_global_snapshot: Dict = {}
        self._gif_tmpdirs: list = []

        # ── Map of string keys → tkinter vars (for generic get/set) ──────────
        self._var_map: Dict[str, Any] = {k: v for k, v in self.__dict__.items()
                                          if isinstance(v, (tk.Variable,))}

    # ── IModel implementation ─────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        var = self._var_map.get(key)
        if var is not None:
            try:
                return var.get()
            except Exception:
                return default
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        var = self._var_map.get(key)
        if var is not None:
            try:
                var.set(value)
                return
            except Exception:
                pass
        setattr(self, key, value)

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow dict copy of all var values."""
        return {k: v.get() for k, v in self._var_map.items()}

    def restore(self, state: Dict[str, Any]) -> None:
        """Restore var values from a snapshot."""
        for k, val in state.items():
            var = self._var_map.get(k)
            if var is not None:
                try:
                    var.set(val)
                except Exception:
                    pass

    # ── Helper: build params dict for converter ───────────────────────────────

    def build_params(self) -> Dict[str, Any]:
        """Build a converter-compatible params dict from current state."""
        s = self
        return {
            **DEFAULT_PARAMS,
            "max_workers":         s.v_workers.get(),
            "scroll_speed":        s.v_scroll.get(),
            "bottom_crop_pct":     s.v_bottom_crop.get(),
            "top_crop_pct":        s.v_top_crop.get(),
            "scroll_cycles":       s.v_scroll_cycles.get(),
            "fps_min":             s.v_fps_min.get(),
            "fps_max":             s.v_fps_max.get(),
            "mode":                s.v_mode.get(),
            "contrast":            s.v_contrast.get(),
            "saturation":          s.v_saturation.get(),
            "brightness":          s.v_brightness.get(),
            "gamma":               s.v_gamma.get(),
            "sharpen_lum":         s.v_sharpen_lum.get(),
            "sharpen_chr":         s.v_sharpen_chr.get(),
            "dither":              s.v_dither.get(),
            "scroll_enabled":      s.v_scroll_enabled.get(),
            "zoom":                s.v_zoom.get(),
            "manual_x":            s.v_manual_x.get(),
            "manual_y":            s.v_manual_y.get(),
            "hue_shift":           s.v_hue_shift.get(),
            "noise_reduction":     s.v_noise_reduction.get(),
            "film_grain":          s.v_film_grain.get(),
            "vignette":            s.v_vignette.get(),
            "auto_action_enabled": s.v_auto_action_enabled.get(),
            "action_detector":     s.v_action_detector.get(),
            "action_strength":     s.v_action_strength.get(),
            "action_smoothness":   s.v_action_smoothness.get(),
            "action_zoom_max":     s.v_action_zoom_max.get(),
            "action_padding":      s.v_action_padding.get(),
            "action_intro":        s.v_action_intro.get(),
            "action_bottom_crop":  s.v_action_bottom_crop.get(),
            "action_auto_bottom_crop": s.v_action_auto_bottom_crop.get(),
            "action_top_crop":     s.v_action_top_crop.get(),
            "action_auto_top_crop": s.v_action_auto_top_crop.get(),
            "action_vertical_bias": s.v_action_vertical_bias.get(),
            "action_auto_vertical_bias": s.v_action_auto_vertical_bias.get(),
            "action_smart_auto_crop": s.v_action_smart_auto_crop.get(),
            "bg_sub_enable":       s.v_bg_sub_enable.get(),
            "dmd_visibility_score_enabled": s.v_dmd_visibility_score_enabled.get(),
            "dmd_readability_score_enabled": s.v_dmd_readability_score_enabled.get(),
            "target_width":        s.v_target_width.get(),
            "target_height":       s.v_target_height.get(),
            "text_overlay_enabled": s.v_text_overlay_enabled.get(),
            "text_content":        s.v_text_content.get(),
            "text_font_size":      s.v_text_font_size.get(),
            "text_color":          s.v_text_color.get(),
            "text_position":       s.v_text_position.get(),
            "text_font_file":      s.v_text_font_file.get(),
            "text_style":          s.v_text_style.get(),
            "text_bg":             s.v_text_bg.get(),
            "text_bg_opacity":     s.v_text_bg_opacity.get(),
            "max_duration":        s.v_max_duration.get() if s.v_max_dur_enabled.get() else 0.0,
        }
