from src.ui.widgets import _InfoBadge
from src.ui.constants import *
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMD GIF Converter — Graphical Interface  v3.0.0
Cross-platform UI (macOS · Windows · Linux) to convert any video/GIF
to 128×32 LED DMD format.

New in v2.1:
  • Triple real-time preview (SOURCE + AUTO ACTION + DMD)
  • Auto/DMD preview auto-refreshes ~2 s after any parameter change
  • 🔧 Advanced Settings panel (collapsed by default):
      – Manual positioning: disable auto-scroll, set zoom / X / Y manually
      – Visual effects: hue shift, noise reduction, film grain, vignette

New in v2.4.0:
  • 💬 Text Overlay — burn pixel-font text on the 128×32 output GIF
      – 4 rendering styles: outline (default), bold, shadow, none
      – Optional semi-transparent background box
      – Dual backend: ffmpeg drawtext when available, Pillow fallback otherwise
  • 🖼️ Multi-Dalle / Tiling — configurable output resolution presets
  • 🎨 Background subtraction warmup fix (no more black-flash artefacts)
  • Structured logging — no more print() in production code

New in v3.0.0:
  • 🔍 GIF Search — search & download GIFs from DuckDuckGo directly in the UI
      – Keyword search bar + configurable quantity (1–50)
      – Downloads to a managed temp folder, auto-populates the file list
      – Real-time progress via the main progress bar + log
      – Cancel button, per-file error handling, graceful fallback if deps missing

Usage:
    python dmd_gif_converter_ui.py
"""

import os
import sys

# Fix for macOS CoreFoundation fork safety issue with multithreading + subprocess + ONNX
# MUST BE SET BEFORE tkinter or any framework is loaded
if sys.platform == "darwin":
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

import threading
import tkinter as tk

import re
import platform
import glob
import logging
import shutil
import tempfile
import subprocess
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import json

# ── Module-level logger ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] [UI] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ── Dependency check ──────────────────────────────────────────────────────────
_missing = []
try:
    import customtkinter as ctk
except ImportError:
    _missing.append("customtkinter")
try:
    from PIL import Image, ImageTk
except ImportError:
    _missing.append("Pillow")

if _missing:
    logger.critical(
        "Missing dependencies: %s — install with:  pip install %s",
        ", ".join(_missing), " ".join(_missing),
    )
    sys.exit(1)

# ── Import converter engine ───────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from src.converter.core import (
        get_metadata, process_file, process_folder,
        DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
    )
except ImportError as exc:
    logger.critical("Could not import dmd_gif_converter: %s", exc)
    sys.exit(1)

try:
    from src.auto_action.main import AutoActionConfig, preprocess_video_for_dmd
except ImportError:
    AutoActionConfig = None
    preprocess_video_for_dmd = None

try:
    from src.converter.colorimetry import analyze_and_compensate as _ui_analyze_color
except ImportError:
    _ui_analyze_color = None

# ─────────────────────────────────────────────────────────────────────────────
#  DMDConverterApp — main window
# ─────────────────────────────────────────────────────────────────────────────
from .panels.left import LeftPanelMixin
from .panels.middle import MiddlePanelMixin
from .panels.preview import PreviewPanelMixin
from .panels.settings import SettingsPanelMixin
from .panels.actions import ActionsPanelMixin
from .panels.ai_moments import AiMomentsPanelMixin
class DMDConverterApp(ctk.CTk, LeftPanelMixin, MiddlePanelMixin, PreviewPanelMixin, SettingsPanelMixin, ActionsPanelMixin, AiMomentsPanelMixin):

    def __init__(self):
        super().__init__()
        self.title(f"🎞️  DMD GIF Converter  v{APP_VERSION}")
        self.geometry("1300x880")
        self.minsize(980, 680)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── State ─────────────────────────────────────────────────────────────
        self._file_data:    dict = {}   # Pending files mapping (iid -> path)
        self._file_paths:   set  = set()
        
        self._converted_data: dict = {} # Converted files mapping (iid -> path)
        self._converted_paths: set = set()
        
        self._selected_iid: str  = ""
        self._selected_converted_iid: str = ""
        self._busy                  = False
        self._source_duration       = 0.0

        # Source preview state
        self._src_pil_frames: list = []  # raw PIL Images (thread-safe storage)
        self._src_frames: list  = []     # cached ImageTk.PhotoImage (lazy, main thread only)
        self._src_delays: list  = []
        self._src_idx           = 0
        self._src_job           = None
        self._src_tmpdir        = None

        # DMD preview state (independent animation loop)
        self._dmd_pil_frames: list = []   # raw PIL Images (thread-safe storage)
        self._dmd_frames: list  = []      # cached ImageTk.PhotoImage (lazy, main thread only)
        self._dmd_delays: list  = []
        self._dmd_idx           = 0
        self._dmd_job           = None
        self._dmd_tmpdir        = None
        self._dmd_rendering     = False

        # Auto-action preview state (intermediate pre-ffmpeg stage)
        self._auto_pil_frames: list = []  # raw PIL Images (thread-safe storage)
        self._auto_frames: list = []      # cached ImageTk.PhotoImage (lazy, main thread only)
        self._auto_delays: list = []
        self._auto_idx          = 0
        self._auto_job          = None
        self._auto_tmpdir       = None
        self._auto_rendering    = False

        # Auto-refresh debounce job
        self._adv_refresh_job   = None

        # Guard flag: suppresses pipeline-refresh debounce during _restore_params
        # to prevent a debounce storm from ~40 simultaneous var.set() calls.
        self._restoring_params: bool = False

        # Pending preview requests (queued while a render is in-flight)
        self._dmd_pending_src  = None   # src to render after current DMD render finishes
        self._auto_pending_src = None   # src to render after current Auto render finishes

        # Advanced panel expansion state
        self._adv_expanded      = False

        # ── Tkinter vars — standard parameters (unchanged from v2.0) ──────────
        self.v_output_dir    = tk.StringVar(value="")
        self.v_mode          = tk.StringVar(value="pixel_art")
        self.v_workers       = tk.IntVar   (value=2)
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

        # ── Tkinter vars — advanced parameters (new in v2.1) ──────────────────
        self.v_scroll_enabled  = tk.BooleanVar(value=True)
        self.v_zoom            = tk.DoubleVar(value=1.0)
        self.v_manual_x        = tk.IntVar   (value=0)
        self.v_manual_y        = tk.IntVar   (value=0)
        self.v_hue_shift       = tk.DoubleVar(value=0.0)
        self.v_noise_reduction = tk.DoubleVar(value=0.0)
        self.v_film_grain      = tk.IntVar   (value=0)
        self.v_vignette        = tk.BooleanVar(value=False)
        self.v_auto_action_enabled = tk.BooleanVar(value=False)
        self.v_action_detector     = tk.StringVar(value="person")
        self.v_action_strength     = tk.DoubleVar(value=0.65)
        self.v_action_auto_strength = tk.BooleanVar(value=False)
        self.v_action_smoothness   = tk.DoubleVar(value=0.65)
        self.v_action_auto_smoothness = tk.BooleanVar(value=False)
        self.v_action_zoom_max     = tk.DoubleVar(value=2.0)
        self.v_action_padding      = tk.DoubleVar(value=0.20)
        self.v_action_intro        = tk.DoubleVar(value=1.5)
        self.v_action_bottom_crop  = tk.DoubleVar(value=0.0)
        self.v_action_auto_bottom_crop = tk.BooleanVar(value=False)
        self.v_action_top_crop     = tk.DoubleVar(value=0.0)
        self.v_action_auto_top_crop = tk.BooleanVar(value=False)
        self.v_action_vertical_bias = tk.DoubleVar(value=0.0)
        self.v_action_auto_vertical_bias = tk.BooleanVar(value=False)
        self.v_action_smart_auto_crop    = tk.BooleanVar(value=False)
        self.v_action_auto_pillarbox     = tk.BooleanVar(value=False)
        self.v_bg_sub_enable       = tk.BooleanVar(value=False) # New background subtraction checkbox
        self.v_dmd_visibility_score_enabled = tk.BooleanVar(value=False) # NEW: Enable DMD Visibility Score
        self.v_dmd_readability_score_enabled = tk.BooleanVar(value=True) # NEW: Enable DMD Readability Score

        # ── Tkinter vars — Multi-dalle / Tiling ───────────────────────────────
        self.v_target_width  = tk.IntVar(value=DEFAULT_PARAMS["target_width"])
        self.v_target_height = tk.IntVar(value=DEFAULT_PARAMS["target_height"])
        self.v_target_preset = tk.StringVar(value="128x32 (1x1)")

        # ── Tkinter vars — Text Overlay ───────────────────────────────────────
        self.v_text_overlay_enabled = tk.BooleanVar(value=False)
        self.v_text_content         = tk.StringVar(value="")
        self.v_text_font_size       = tk.IntVar(value=8)
        self.v_text_color           = tk.StringVar(value="white")
        self.v_text_position        = tk.StringVar(value="bottom_center")
        self.v_text_font_file       = tk.StringVar(value="HelvetiPixel.ttf")
        self.v_text_style           = tk.StringVar(value="outline")
        self.v_text_bg              = tk.BooleanVar(value=False)
        self.v_text_bg_opacity      = tk.IntVar(value=60)
        self.v_text_animation       = tk.StringVar(value="none")

        # ── Tkinter vars — max duration cap ───────────────────────────────────
        self.v_max_dur_enabled = tk.BooleanVar(value=True)    # ON by default (2 min cap)
        self.v_max_duration    = tk.DoubleVar(value=120.0)    # 2 minutes

        # ── Tkinter vars — auto-colorimetry ───────────────────────────────────
        self.v_auto_color_enabled = tk.BooleanVar(value=False)

        # Smart Color Boost — save/restore state when toggling
        self._auto_color_analyzing: bool = False
        self._pre_auto_color_values: dict = {}  # saved custom-mode slider values

        # ── Tkinter vars — "Let me handle it" ─────────────────────────────────
        self.v_let_me_handle_it = tk.BooleanVar(value=True)
        self._lmh_widgets: list = []          # widgets to gray in LMH mode
        self._lmh_saved_state: dict = {}      # saved 4-flag state before LMH

        # ── Folder refresh state ──────────────────────────────────────────────
        self._last_source_folder: str = ""

        # ── Per-GIF config state ──────────────────────────────────────────────
        self.v_per_gif_config          = tk.BooleanVar(value=False)
        self._per_gif_configs:  dict   = {}   # path → snapshot dict
        self._per_gif_global_snapshot: dict = {}  # global params when mode is enabled

        # ── GIF Search state ──────────────────────────────────────────────────
        self._download_active:  bool = False
        self._download_cancel:  bool = False
        self._gif_tmpdirs:      list = []  # list of temp dirs to clean up on close

        # ── Tkinter vars — GIF Search ─────────────────────────────────────────
        self.v_search_keyword = tk.StringVar(value="")
        self.v_search_qty     = tk.StringVar(value="10")
        self.v_search_engine  = tk.StringVar(value="DuckDuckGo")
        self.v_search_min_w   = tk.StringVar(value="")
        self.v_search_min_h   = tk.StringVar(value="")
        self.v_search_ratio   = tk.StringVar(value="All")
        self.v_tenor_api_key  = tk.StringVar(value="")
        self.v_giphy_api_key  = tk.StringVar(value="")

        # ── Tkinter vars — LED pixel simulation ───────────────────────────────
        self.v_led_sim = tk.BooleanVar(value=True)   # ON by default

        # ── Global Cancellation Event ─────────────────────────────────────────
        self._cancel_event = threading.Event()

        # ── Params that affect the full pipeline (auto-action + DMD) ─────────
        _watch = [
            self.v_mode, self.v_scroll, self.v_bottom_crop, self.v_top_crop, self.v_scroll_cycles,
            self.v_fps_min, self.v_fps_max,
            self.v_dither, self.v_scroll_enabled, self.v_zoom,
            self.v_manual_x, self.v_manual_y,
            self.v_auto_action_enabled, self.v_action_detector,
            self.v_action_strength, self.v_action_auto_strength,
            self.v_action_smoothness, self.v_action_auto_smoothness,
            self.v_action_zoom_max, self.v_action_padding,
            self.v_action_intro, self.v_action_bottom_crop, self.v_action_auto_bottom_crop,
            self.v_action_top_crop, self.v_action_auto_top_crop,
            self.v_action_vertical_bias,
            self.v_action_auto_vertical_bias, self.v_action_smart_auto_crop,
            self.v_bg_sub_enable, self.v_dmd_visibility_score_enabled, self.v_dmd_readability_score_enabled,
            self.v_target_width, self.v_target_height, self.v_target_preset,
            self.v_trim_start, self.v_trim_end,
            self.v_max_dur_enabled, self.v_max_duration,
        ]
        for var in _watch:
            var.trace_add("write", self._schedule_pipeline_refresh)

        # ── Params that ONLY affect DMD output (no auto-action re-run needed) ─
        # Text overlay, colorimetry, and animation are applied post-framing,
        # so changing them must not trigger the expensive OpenCV preprocessing.
        _watch_dmd_only = [
            self.v_contrast, self.v_saturation, self.v_brightness, self.v_gamma,
            self.v_sharpen_lum, self.v_sharpen_chr,
            self.v_hue_shift, self.v_noise_reduction, self.v_film_grain, self.v_vignette,
            self.v_auto_color_enabled,
            self.v_text_overlay_enabled, self.v_text_content,
            self.v_text_font_size, self.v_text_color, self.v_text_position,
            self.v_text_font_file, self.v_text_style, self.v_text_bg, self.v_text_bg_opacity,
            self.v_text_animation,
        ]
        for var in _watch_dmd_only:
            var.trace_add("write", self._schedule_dmd_only_refresh)

        self._build_ui()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0) # Log panel

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=(0, 5))

        self.tab_conversion = self.tabview.add("Conversion")
        self.tab_ai_moments = self.tabview.add("Moments")

        # ── Setup Conversion Tab ──────────────────────────────────────────────
        self.tab_conversion.grid_columnconfigure(2, weight=1)
        self.tab_conversion.grid_rowconfigure(0, weight=1)

        self._build_left_panel(self.tab_conversion)    # Column 0
        self._build_middle_panel(self.tab_conversion)  # Column 1
        self._build_right_panel(self.tab_conversion)   # Column 2
        
        # ── Setup AI Moments Tab ──────────────────────────────────────────────
        if hasattr(self, '_build_ai_moments_panel'):
            self._build_ai_moments_panel(self.tab_ai_moments)

        self._build_global_log_panel()
        
        self._load_api_keys()
        self.v_tenor_api_key.trace_add("write", lambda *_: self._save_api_keys())
        self.v_giphy_api_key.trace_add("write", lambda *_: self._save_api_keys())
        
        # Initialize default state for 'Let me handle it'
        self.after(50, lambda: self._on_let_me_handle_toggle() if hasattr(self, '_on_let_me_handle_toggle') else None)

    def _build_global_log_panel(self):
        self._log_panel = ctk.CTkFrame(self, fg_color="#1a1a2e", corner_radius=0)
        # Hidden by default
        self._log_panel.grid_columnconfigure(0, weight=1)
        
        top_bar = ctk.CTkFrame(self._log_panel, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(4, 2))
        
        ctk.CTkLabel(
            top_bar, text="📋  Conversion log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(side="left")
        
        self.v_log_level = tk.StringVar(value="INFO")
        self._opt_log_level = ctk.CTkOptionMenu(
            top_bar, variable=self.v_log_level,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            width=90, height=24, font=ctk.CTkFont(size=11),
            fg_color="#3a3a4a", button_color="#50506b", button_hover_color="#6a6a8b",
            command=self._on_log_level_change
        )
        self._opt_log_level.pack(side="right")
        
        self._log_box = ctk.CTkTextbox(
            self._log_panel, font=ctk.CTkFont(size=11, family="Courier"), wrap="word", height=120
        )
        self._log_box.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._log_box.configure(state="disabled")
        
        self._log_visible = False
        self._all_logs = []

    def _on_log_level_change(self, val):
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        current_lvl = levels.get(val, 20)
        
        if hasattr(self, "_log_box"):
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            
            for msg_lvl, msg in getattr(self, "_all_logs", []):
                if msg_lvl >= current_lvl:
                    self._log_box.insert("end", msg + "\n")
                    
            self._log_box.configure(state="disabled")
            self._log_box.see("end")

    def toggle_log_panel(self):
        if self._log_visible:
            self._log_panel.grid_remove()
        else:
            self._log_panel.grid(row=1, column=0, columnspan=3, sticky="ew")
            # Automatically enable detailed logs when unfolded
            if hasattr(self, "v_log_level") and self.v_log_level.get() == "WARNING":
                self.v_log_level.set("DEBUG")
                if hasattr(self, "_on_log_level_change"):
                    self._on_log_level_change("DEBUG")
        self._log_visible = not self._log_visible

    # ── Left panel : file list ────────────────────────────────────────────────
    def _on_close(self):
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        # Cancel any active download and clean up temp dirs
        self._download_cancel = True
        for td in self._gif_tmpdirs:
            if td and os.path.isdir(td):
                shutil.rmtree(td, ignore_errors=True)
        # Clear per-gif configs on close
        self._per_gif_configs.clear()
        self.destroy()

    def _load_api_keys(self):
        conf = Path("dmd_api_keys.json")
        if conf.exists():
            try:
                data = json.loads(conf.read_text())
                self.v_tenor_api_key.set(data.get("tenor", ""))
                self.v_giphy_api_key.set(data.get("giphy", ""))
            except Exception as exc:
                logger.warning("Could not read dmd_api_keys.json: %s", exc)

    def _save_api_keys(self):
        try:
            data = {
                "tenor": self.v_tenor_api_key.get(),
                "giphy": self.v_giphy_api_key.get()
            }
            Path("dmd_api_keys.json").write_text(json.dumps(data, indent=4))
        except Exception as exc:
            logger.warning("Failed to save dmd_api_keys.json: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # Prevent known hard crash on macOS when using Apple CommandLineTools Python + Tk 8.5.
    if platform.system() == "Darwin":
        try:
            import tkinter as _tk
            tk_ver = float(_tk.TkVersion)
        except Exception:
            tk_ver = 0.0

        if (
            "CommandLineTools" in sys.executable
            and tk_ver > 0.0
            and tk_ver < 8.6
        ):
            logger.critical(
                "Incompatible Python/Tk detected: Python=%s  Tk=%.1f\n"
                "This macOS build uses Tk 8.5 and crashes with this UI.\n"
                "Use the launcher script:  ./launch_ui.sh\n"
                "Or install Homebrew Python:  brew install python@3.13",
                sys.executable, tk_ver,
            )
            sys.exit(1)

    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        msg = (
            "ffmpeg not found or not responding.\n"
            "Please install ffmpeg from your system's package manager or official website.\n\n"
            "macOS :  brew install ffmpeg\n"
            "Windows: winget install Gyan.FFmpeg\n"
            "Linux :  sudo apt install ffmpeg"
        )
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("ffmpeg missing", msg)
            root.destroy()
        except Exception:
            logger.critical("ffmpeg not found or not responding:\n%s", msg)
        sys.exit(1)

    app = DMDConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()