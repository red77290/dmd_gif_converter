#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMD GIF Converter — Graphical Interface  v2.4.0
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

Usage:
    python dmd_gif_converter_ui.py
"""

import os
import sys
import platform
import glob
import logging
import shutil
import threading
import tempfile
import subprocess
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox

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
    from dmd_gif_converter import (
        get_metadata, process_file, process_folder,
        DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
    )
except ImportError as exc:
    logger.critical("Could not import dmd_gif_converter: %s", exc)
    sys.exit(1)

try:
    from dmd_auto_action import AutoActionConfig, preprocess_video_for_dmd
except ImportError:
    AutoActionConfig = None
    preprocess_video_for_dmd = None

try:
    from dmd_auto_color import analyze_and_compensate as _ui_analyze_color
except ImportError:
    _ui_analyze_color = None

# ── Constants ─────────────────────────────────────────────────────────────────
# Three preview canvases
SRC_CANVAS_W  = 300
SRC_CANVAS_H  = 170
AUTO_CANVAS_W = 300
AUTO_CANVAS_H = 170

# DMD output is still displayed at 128×32 scaled ×2.34
DMD_DISPLAY_SCALE_FACTOR = 2.34375 # 300/128 = 75/32

BG_CANVAS     = "#0d0d1a"
APP_VERSION   = "2.4.0"

# Auto-refresh debounce: ms to wait after last param change before rebuilding DMD
DMD_REFRESH_DELAY_MS = 1800

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_STATUS_COLOR = {
    "idle":       "#666688",
    "converting": "#f39c12",
    "done":       "#2ecc71",
    "error":      "#e74c3c",
}
_MODE_DESC = {
    "pixel_art": "Retro sprites, arcade, consoles — default ★",
    "anime":     "Anime / cartoon (softer rendering)",
    "cinema":    "Live-action films, real footage",
    "custom":    "Manual control of every parameter",
}


# ─────────────────────────────────────────────────────────────────────────────
#  DMDConverterApp — main window
# ─────────────────────────────────────────────────────────────────────────────
class DMDConverterApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title(f"🎞️  DMD GIF Converter  v{APP_VERSION}")
        self.geometry("1300x880")
        self.minsize(980, 680)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── State ─────────────────────────────────────────────────────────────
        self._file_data:    dict = {}
        self._file_paths:   set  = set()
        self._selected_iid: str  = ""
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
        self.v_action_smoothness   = tk.DoubleVar(value=0.85)
        self.v_action_zoom_max     = tk.DoubleVar(value=2.0)
        self.v_action_padding      = tk.DoubleVar(value=0.20)
        self.v_action_intro        = tk.DoubleVar(value=1.5)
        self.v_bg_sub_enable       = tk.BooleanVar(value=False) # New background subtraction checkbox

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

        # ── Tkinter vars — max duration cap ───────────────────────────────────
        self.v_max_dur_enabled = tk.BooleanVar(value=True)    # ON by default (2 min cap)
        self.v_max_duration    = tk.DoubleVar(value=120.0)    # 2 minutes

        # ── Tkinter vars — auto-colorimetry ───────────────────────────────────
        self.v_auto_color_enabled = tk.BooleanVar(value=False)

        # Smart Color Boost — save/restore state when toggling
        self._auto_color_analyzing: bool = False
        self._pre_auto_color_values: dict = {}  # saved custom-mode slider values

        # ── Attach auto-refresh debounce to every param that affects DMD ──────
        _watch = [
            self.v_mode, self.v_scroll, self.v_bottom_crop, self.v_scroll_cycles,
            self.v_fps_min, self.v_fps_max, self.v_contrast, self.v_saturation,
            self.v_brightness, self.v_gamma, self.v_sharpen_lum, self.v_sharpen_chr,
            self.v_dither, self.v_scroll_enabled, self.v_zoom,
            self.v_manual_x, self.v_manual_y, self.v_hue_shift,
            self.v_noise_reduction, self.v_film_grain, self.v_vignette,
            self.v_auto_action_enabled, self.v_action_detector,
            self.v_action_strength, self.v_action_smoothness,
            self.v_action_zoom_max, self.v_action_padding,
            self.v_action_intro, self.v_bg_sub_enable,
            self.v_target_width, self.v_target_height, self.v_target_preset,
            self.v_text_overlay_enabled, self.v_text_content, # Added text overlay vars
            self.v_text_font_size, self.v_text_color, self.v_text_position, # Added text overlay vars
            self.v_text_font_file,  # font selector
            self.v_text_style, self.v_text_bg, self.v_text_bg_opacity,  # style / bg
            self.v_trim_start, self.v_trim_end,
            self.v_max_dur_enabled, self.v_max_duration,
            self.v_auto_color_enabled,
        ]
        for var in _watch:
            var.trace_add("write", self._schedule_pipeline_refresh)

        self._build_ui()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left_panel()
        self._build_right_panel()

    # ── Left panel : file list ────────────────────────────────────────────────
    def _build_left_panel(self):
        lp = ctk.CTkFrame(self, width=295, corner_radius=0)
        lp.grid(row=0, column=0, sticky="nsew")
        lp.grid_propagate(False)
        lp.grid_rowconfigure(2, weight=1)
        lp.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(lp, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=10, pady=(12, 4), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="📁  Source files",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self._count_lbl = ctk.CTkLabel(
            hdr, text="empty", text_color="#666688", font=ctk.CTkFont(size=11)
        )
        self._count_lbl.grid(row=0, column=1, sticky="e")

        br = ctk.CTkFrame(lp, fg_color="transparent")
        br.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="ew")
        br.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(br, text="➕ File(s)", command=self.add_files, height=30).grid(
            row=0, column=0, padx=2, sticky="ew")
        ctk.CTkButton(br, text="📂 Folder",  command=self.add_folder, height=30).grid(
            row=0, column=1, padx=2, sticky="ew")
        ctk.CTkButton(br, text="✕ Remove",   command=self._remove_selected,
                      height=30, fg_color="#3a3a4a", hover_color="#7b241c").grid(
            row=0, column=2, padx=2, sticky="ew")

        self._style_treeview()
        tree_host = tk.Frame(lp, bg="#12121f")
        tree_host.grid(row=2, column=0, padx=6, pady=4, sticky="nsew")
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_host, style="File.Treeview",
            show="tree", selectmode="browse"
        )
        sb = ttk.Scrollbar(tree_host, orient="vertical",
                           command=self._tree.yview, style="File.Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("idle",       foreground="#aaaacc")
        self._tree.tag_configure("converting", foreground="#f39c12")
        self._tree.tag_configure("done",       foreground="#2ecc71")
        self._tree.tag_configure("error",      foreground="#e74c3c")

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Delete>",           lambda _e: self._remove_selected())
        self._tree.bind("<BackSpace>",        lambda _e: self._remove_selected())

        ctk.CTkLabel(lp, text="👆 Click a row to select · Del to remove",
                     text_color="#444466", font=ctk.CTkFont(size=10)
                     ).grid(row=3, column=0, padx=8, pady=(0, 2), sticky="w")

        bot = ctk.CTkFrame(lp, fg_color="transparent")
        bot.grid(row=4, column=0, padx=6, pady=6, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bot, text="📤 Output folder", font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, columnspan=2, padx=4, pady=(6, 1), sticky="w"
        )
        of = ctk.CTkFrame(bot, fg_color="transparent")
        of.grid(row=1, column=0, columnspan=2, sticky="ew")
        of.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            of, textvariable=self.v_output_dir,
            placeholder_text="(same folder as source)", height=28
        ).grid(row=0, column=0, padx=(4, 2), sticky="ew")
        ctk.CTkButton(
            of, text="…", width=28, height=28, command=self.browse_output
        ).grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(
            bot, text="🗑  Clear list", command=self.clear_files,
            fg_color="#3a3a4a", hover_color="#7b241c", height=28
        ).grid(row=2, column=0, columnspan=2, padx=4, pady=(8, 2), sticky="ew")

    def _style_treeview(self):
        s = ttk.Style()
        s.theme_use("default")
        s.configure("File.Treeview",
                    background="#12121f", foreground="#aaaacc",
                    fieldbackground="#12121f", borderwidth=0,
                    rowheight=26, font=("Helvetica", 12))
        s.map("File.Treeview",
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", "#ffffff")])
        s.layout("File.Treeview", [("File.Treeview.treearea", {"sticky": "nswe"})])
        s.configure("File.Vertical.TScrollbar",
                    background="#2a2a3e", troughcolor="#12121f",
                    arrowcolor="#555577", relief="flat")

    def _update_count(self):
        n = len(self._file_data)
        self._count_lbl.configure(
            text=f"{n} file{'s' if n != 1 else ''}" if n else "empty"
        )

    # ── Right panel ───────────────────────────────────────────────────────────
    def _build_right_panel(self):
        rp = ctk.CTkFrame(self, fg_color="transparent")
        rp.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        rp.grid_rowconfigure(1, weight=1)
        rp.grid_columnconfigure(0, weight=1)
        self._build_preview_area(rp)
        self._build_bottom_area(rp)

    # ── Dual Preview ──────────────────────────────────────────────────────────
    def _build_preview_area(self, parent):
        pf = ctk.CTkFrame(parent)
        pf.grid(row=0, column=0, padx=4, pady=(4, 2), sticky="ew")
        pf.grid_columnconfigure(0, weight=1)

        # Title row
        tr = ctk.CTkFrame(pf, fg_color="transparent")
        tr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        tr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            tr, text="🖥️  Preview  —  SOURCE → AUTO ACTION → DMD",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        pb = ctk.CTkFrame(tr, fg_color="transparent")
        pb.grid(row=0, column=1, sticky="e")
        self._btn_all_prev = ctk.CTkButton(
            pb, text="🔄 Refresh All", width=120, height=28,
            command=self.refresh_all_previews
        )
        self._btn_all_prev.pack(side="left", padx=3)
        self._btn_src = ctk.CTkButton(
            pb, text="▶ Source", width=92, height=28,
            command=self.show_source_preview
        )
        self._btn_src.pack(side="left", padx=3)
        self._btn_auto = ctk.CTkButton(
            pb, text="🎯 Auto", width=92, height=28,
            fg_color="#2b4b8a", hover_color="#234073",
            command=self.show_auto_preview
        )
        self._btn_auto.pack(side="left", padx=3)
        self._btn_dmd = ctk.CTkButton(
            pb, text="🔬 DMD", width=92, height=28,
            fg_color="#1e6a3c", hover_color="#155230",
            command=self.show_dmd_preview
        )
        self._btn_dmd.pack(side="left", padx=3)

        # Dual canvas row
        dc = ctk.CTkFrame(pf, fg_color="transparent")
        dc.grid(row=1, column=0, padx=6, pady=4)

        # Source canvas (left)
        src_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        src_wrap.pack(side="left", padx=(0, 4))
        ctk.CTkLabel(
            src_wrap, text="SOURCE",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#556677"
        ).pack(pady=(4, 0))
        self._src_canvas = tk.Canvas(
            src_wrap, width=SRC_CANVAS_W, height=SRC_CANVAS_H,
            bg=BG_CANVAS, highlightthickness=0
        )
        self._src_canvas.pack(padx=2, pady=(2, 2))
        self._src_info = ctk.CTkLabel(
            src_wrap, text="", text_color="#888899", font=ctk.CTkFont(size=10)
        )
        self._src_info.pack(pady=(0, 4))

        # Auto-action canvas (middle)
        auto_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        auto_wrap.pack(side="left", padx=4)
        ctk.CTkLabel(
            auto_wrap, text="AUTO ACTION",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#4f7bd9"
        ).pack(pady=(4, 0))
        self._auto_canvas = tk.Canvas(
            auto_wrap, width=AUTO_CANVAS_W, height=AUTO_CANVAS_H,
            bg=BG_CANVAS, highlightthickness=0
        )
        self._auto_canvas.pack(padx=2, pady=(2, 2))
        self._auto_info = ctk.CTkLabel(
            auto_wrap, text="", text_color="#888899", font=ctk.CTkFont(size=10)
        )
        self._auto_info.pack(pady=(0, 4))

        # DMD canvas (right)
        dmd_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        dmd_wrap.pack(side="left", padx=(4, 0))
        self._dmd_title_label = ctk.CTkLabel(
            dmd_wrap,
            text=f"DMD OUTPUT {DEFAULT_PARAMS['target_width']}×{DEFAULT_PARAMS['target_height']}",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#2e7a4a"
        )
        self._dmd_title_label.pack(pady=(4, 0))
        # Initialize with default dimensions, will be updated dynamically
        self._dmd_canvas = tk.Canvas(
            dmd_wrap, width=int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR),
            height=int(DEFAULT_PARAMS["target_height"] * DMD_DISPLAY_SCALE_FACTOR),
            bg=BG_CANVAS, highlightthickness=0
        )
        self._dmd_canvas.pack(padx=2, pady=(2, 2))
        self._dmd_info = ctk.CTkLabel(
            dmd_wrap, text="", text_color="#888899", font=ctk.CTkFont(size=10)
        )
        self._dmd_info.pack(pady=(0, 4))

        # Backward-compat aliases
        self._canvas       = self._src_canvas
        self._preview_info = self._src_info

        # Keep canvas size + title label in sync with dimension vars (including Custom mode)
        self.v_target_width.trace_add("write",  self._update_dmd_canvas_size)
        self.v_target_height.trace_add("write", self._update_dmd_canvas_size)

        self._draw_canvas_idle()
        self._draw_auto_canvas_idle()
        self._draw_dmd_canvas_idle()

        # Trim controls
        self._trim_frame = ctk.CTkFrame(pf, fg_color="#16213e")
        self._trim_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._trim_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._trim_frame, text="✂️  Trim  (single-file conversion only)",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#7ec8e3"
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(self._trim_frame, text="Start", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=(10, 4), pady=2)
        self._sl_start = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_start,
            command=self._on_start_drag
        )
        self._sl_start.grid(row=1, column=1, padx=4, sticky="ew")
        self._lbl_start = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                        font=ctk.CTkFont(size=11))
        self._lbl_start.grid(row=1, column=2, padx=4)

        ctk.CTkLabel(self._trim_frame, text="End", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=2, column=0, padx=(10, 4), pady=2)
        self._sl_end = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_end,
            command=self._on_end_drag
        )
        self._sl_end.grid(row=2, column=1, padx=4, sticky="ew", pady=(2, 8))
        self._lbl_end = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                      font=ctk.CTkFont(size=11))
        self._lbl_end.grid(row=2, column=2, padx=4)

        ctk.CTkButton(
            self._trim_frame, text="↺ Reset", command=self._reset_trim,
            width=70, height=24, fg_color="transparent", border_width=1
        ).grid(row=1, column=3, rowspan=2, padx=(4, 10))

        self._trim_frame.grid_remove()

    # ── Bottom : params + actions ─────────────────────────────────────────────
    def _build_bottom_area(self, parent):
        bot = ctk.CTkFrame(parent, fg_color="transparent")
        bot.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        bot.grid_columnconfigure(0, weight=1)
        bot.grid_columnconfigure(1, weight=0)
        bot.grid_rowconfigure(0, weight=1)

        self._params_scroll = ctk.CTkScrollableFrame(bot, label_text="⚙️  Parameters")
        self._params_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._params_scroll.grid_columnconfigure(0, weight=1)
        self._build_params_panel(self._params_scroll)

        ar = ctk.CTkFrame(bot, width=310)
        ar.grid(row=0, column=1, sticky="nsew")
        ar.grid_propagate(False)
        ar.grid_columnconfigure(0, weight=1)
        ar.grid_rowconfigure(3, weight=1)
        self._build_actions_panel(ar)

    # ── Params panel ──────────────────────────────────────────────────────────
    def _build_params_panel(self, parent):

        def section(text):
            ctk.CTkLabel(
                parent, text=text, font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#7ec8e3"
            ).pack(fill="x", padx=8, pady=(12, 2), anchor="w")

        def slider_row(label, var, from_, to, fmt="{:.1f}", suffix="", steps=None):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=label, width=135, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
            kw = dict(from_=from_, to=to, variable=var)
            if steps is not None:
                kw["number_of_steps"] = steps
            sl = ctk.CTkSlider(f, **kw)
            sl.grid(row=0, column=1, sticky="ew", padx=4)
            lbl = ctk.CTkLabel(f, text=fmt.format(var.get()) + suffix,
                               width=72, anchor="e", font=ctk.CTkFont(size=11))
            lbl.grid(row=0, column=2, padx=(4, 4))
            var.trace_add("write", lambda *_: lbl.configure(text=fmt.format(var.get()) + suffix))
            return sl

        # Mode
        section("🎨  Content mode")
        mr = ctk.CTkFrame(parent, fg_color="transparent")
        mr.pack(fill="x", padx=8, pady=2)
        mr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mr, text="Mode", width=135, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._mode_menu = ctk.CTkOptionMenu(
            mr, variable=self.v_mode,
            values=["pixel_art", "anime", "cinema", "custom"],
            command=self._on_mode_change, width=180
        )
        self._mode_menu.grid(row=0, column=1, padx=4, sticky="w")

        self._mode_desc_lbl = ctk.CTkLabel(
            parent, text=_MODE_DESC["pixel_art"],
            text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._mode_desc_lbl.pack(padx=12, pady=(0, 2), anchor="w")

        # ── Smart Color Boost (auto-colorimetry) ──────────────────────────────
        ac_row = ctk.CTkFrame(parent, fg_color="#0f1a0f", corner_radius=6)
        ac_row.pack(fill="x", padx=8, pady=(4, 6))
        self._auto_color_cb = ctk.CTkCheckBox(
            ac_row,
            text="🎨  Smart Color Boost  —  IA auto-colorimetry",
            variable=self.v_auto_color_enabled,
            command=self._on_auto_color_toggle,
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#88dd88",
        )
        self._auto_color_cb.pack(side="left", padx=12, pady=8)
        self._auto_color_info = ctk.CTkLabel(
            ac_row, text="",
            text_color="#557755", font=ctk.CTkFont(size=10)
        )
        self._auto_color_info.pack(side="left", padx=(0, 8))

        # Parallelism
        section("⚡  Parallelism")
        slider_row("Workers (CPU)", self.v_workers, 1, 16, "{:.0f}", " workers", steps=15)

        # Scroll
        section("📜  Scroll")
        slider_row("Scroll speed",    self.v_scroll,        4.0, 80.0, "{:.0f}", " px/s")
        slider_row("Bottom crop (%)", self.v_bottom_crop,   0.0,  0.5, "{:.0%}")
        slider_row("Scroll cycles",   self.v_scroll_cycles, 0.0,  5.0, "{:.2f}", " cyc")

        # FPS
        section("🎬  Render FPS")
        slider_row("FPS minimum", self.v_fps_min, 5.0,  30.0, "{:.1f}", " fps")
        slider_row("FPS maximum", self.v_fps_max, 10.0, 60.0, "{:.1f}", " fps")

        # ── Max Duration ──────────────────────────────────────────────────────
        section("⏱  Max Duration")

        def _fmt_dur(s):
            s = int(round(s))
            return f"{s // 60}:{s % 60:02d} min"

        dur_toggle = ctk.CTkFrame(parent, fg_color="transparent")
        dur_toggle.pack(fill="x", padx=8, pady=(2, 0))
        self._max_dur_cb = ctk.CTkCheckBox(
            dur_toggle,
            text="Limit clip length  (0 = no limit)",
            variable=self.v_max_dur_enabled,
            command=self._on_max_dur_toggle,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._max_dur_cb.pack(side="left")

        dur_row = ctk.CTkFrame(parent, fg_color="transparent")
        dur_row.pack(fill="x", padx=8, pady=2)
        dur_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(dur_row, text="Max length", width=135, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._max_dur_slider = ctk.CTkSlider(
            dur_row, from_=10, to=600, variable=self.v_max_duration,
            number_of_steps=118,
        )
        self._max_dur_slider.grid(row=0, column=1, sticky="ew", padx=4)
        self._max_dur_lbl = ctk.CTkLabel(
            dur_row, text=_fmt_dur(self.v_max_duration.get()),
            width=72, anchor="e", font=ctk.CTkFont(size=11)
        )
        self._max_dur_lbl.grid(row=0, column=2, padx=(4, 4))
        self.v_max_duration.trace_add(
            "write",
            lambda *_: (
                self._max_dur_lbl.configure(text=_fmt_dur(self.v_max_duration.get())),
                self._apply_max_duration(),
            )
        )

        ctk.CTkLabel(
            parent,
            text="  ↳ Move trim Start slider to place the window anywhere in the video.",
            text_color="#667788", font=ctk.CTkFont(size=10),
        ).pack(padx=8, pady=(0, 6), anchor="w")

        self._on_max_dur_toggle()   # set initial state

        # Colorimetry (custom mode only)
        self._custom_header = ctk.CTkLabel(
            parent, text="🎛️  Colorimetry  (custom mode only)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        )
        self._custom_header.pack(fill="x", padx=8, pady=(12, 2), anchor="w")

        self._custom_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._custom_frame.pack(fill="x")
        self._custom_frame.grid_columnconfigure(0, weight=1)

        # Collect slider references so _on_auto_color_toggle can disable them.
        self._colorimetry_widgets: list = []

        def cslider(label, var, from_, to, fmt="{:.2f}", suffix=""):
            f = ctk.CTkFrame(self._custom_frame, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=label, width=135, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
            sl = ctk.CTkSlider(f, from_=from_, to=to, variable=var)
            sl.grid(row=0, column=1, sticky="ew", padx=4)
            lbl = ctk.CTkLabel(f, text=fmt.format(var.get()) + suffix,
                               width=72, anchor="e", font=ctk.CTkFont(size=11))
            lbl.grid(row=0, column=2, padx=(4, 4))
            var.trace_add("write", lambda *_: lbl.configure(text=fmt.format(var.get()) + suffix))
            self._colorimetry_widgets.append(sl)

        cslider("Contrast",    self.v_contrast,    0.5,  2.5)
        cslider("Saturation",  self.v_saturation,  0.0,  4.0)
        cslider("Brightness",  self.v_brightness, -0.5,  0.5, "{:.3f}")
        cslider("Gamma",       self.v_gamma,       0.1,  2.5)
        cslider("Sharpen Lum", self.v_sharpen_lum, 0.0,  3.0)
        cslider("Sharpen Chr", self.v_sharpen_chr, 0.0,  2.0)

        dr = ctk.CTkFrame(self._custom_frame, fg_color="transparent")
        dr.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(dr, text="Dithering", width=135, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(4, 6))
        self._dither_menu = ctk.CTkOptionMenu(
            dr, variable=self.v_dither,
            values=["none", "bayer:bayer_scale=1", "bayer:bayer_scale=2", "sierra2_4a"],
            width=200
        )
        self._dither_menu.pack(side="left")
        self._colorimetry_widgets.append(self._dither_menu)

        self._update_custom_visibility()

        # Advanced panel (collapsible) — ALWAYS at the bottom
        self._build_advanced_panel(parent)

    # ── Advanced panel ────────────────────────────────────────────────────────
    def _build_advanced_panel(self, parent):
        self._adv_toggle_btn = ctk.CTkButton(
            parent,
            text="🔧  Advanced Settings  ▼",
            command=self._toggle_advanced,
            fg_color="#1a1a2e", hover_color="#2a2a3e",
            anchor="w", height=34, border_width=1,
            border_color="#3a3a5a",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#aaaadd",
        )
        self._adv_toggle_btn.pack(fill="x", padx=8, pady=(14, 0))

        self._adv_frame = ctk.CTkFrame(parent, fg_color="#0f0f20", corner_radius=6)
        # Not packed yet — shown only when expanded
        self._build_advanced_content(self._adv_frame)

    def _toggle_advanced(self):
        self._adv_expanded = not self._adv_expanded
        if self._adv_expanded:
            self._adv_frame.pack(fill="x", padx=8, pady=(0, 8))
            self._adv_toggle_btn.configure(text="🔧  Advanced Settings  ▲")
        else:
            self._adv_frame.pack_forget()
            self._adv_toggle_btn.configure(text="🔧  Advanced Settings  ▼")

    def _build_advanced_content(self, parent):
        def adv_slider(par, label, var, from_, to, fmt="{:.2f}", suffix="",
                       steps=None, is_int=False):
            f = ctk.CTkFrame(par, fg_color="transparent")
            f.pack(fill="x", padx=10, pady=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=label, width=145, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
            kw = dict(from_=from_, to=to, variable=var)
            if steps is not None:
                kw["number_of_steps"] = steps
            sl = ctk.CTkSlider(f, **kw)
            sl.grid(row=0, column=1, sticky="ew", padx=4)
            lbl_txt = (lambda: fmt.format(int(var.get())) + suffix) if is_int \
                      else (lambda: fmt.format(var.get()) + suffix)
            lbl = ctk.CTkLabel(f, text=lbl_txt(), width=80, anchor="e",
                               font=ctk.CTkFont(size=11))
            lbl.grid(row=0, column=2, padx=(4, 4))
            var.trace_add("write", lambda *_: lbl.configure(text=lbl_txt()))
            return sl

        ctk.CTkLabel(
            parent,
            text="ℹ️  All settings here are hidden by default.\n"
                 "    Default values reproduce the standard v2.0 output unchanged.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=12, pady=(8, 4), anchor="w")

        # ── SECTION 0: AUTO ACTION FRAMING ───────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  🎯  Auto Action Framing (pre-ffmpeg)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        auto_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkCheckBox(
            auto_row,
            text="Enable cinematic auto-framing before ffmpeg (default OFF)",
            variable=self.v_auto_action_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        ).pack(side="left")

        mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=2)
        mode_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mode_row, text="Detection mode", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        ctk.CTkOptionMenu(
            mode_row,
            variable=self.v_action_detector,
            values=["person", "motion", "hybrid", "center"],
            width=200,
        ).grid(row=0, column=1, sticky="w", padx=4)

        ctk.CTkLabel(
            parent,
            text="Default mode is person. Change detection mode here if you prefer.\n"
                 "Processed output keeps 4:1 ratio before standard DMD conversion.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        adv_slider(parent, "Action strength", self.v_action_strength, 0.0, 1.0,
                   "{:.2f}", "", steps=100)
        adv_slider(parent, "Camera smooth", self.v_action_smoothness, 0.0, 0.98,
                   "{:.2f}", "", steps=98)
        adv_slider(parent, "Zoom max", self.v_action_zoom_max, 1.0, 3.0,
                   "{:.2f}", "×", steps=100)
        adv_slider(parent, "ROI padding", self.v_action_padding, 0.0, 0.6,
                   "{:.2f}", "", steps=60)
        adv_slider(parent, "Intro panoramic", self.v_action_intro, 0.0, 5.0,
                   "{:.1f}", " s", steps=50)
        ctk.CTkLabel(
            parent,
            text="    Intro: full-frame overview shown before zooming in on action.\n"
                 "    Set to 0 to disable (start immediately on action).",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # New: Background Subtraction Checkbox
        bg_sub_row = ctk.CTkFrame(parent, fg_color="transparent")
        bg_sub_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkCheckBox(
            bg_sub_row,
            text="Enable Background Subtraction (replaces background with black)",
            variable=self.v_bg_sub_enable,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        ).pack(side="left")
        ctk.CTkLabel(
            parent,
            text="    This will replace the detected background with black (0,0,0).\n"
                 "    Maximizes contrast and reduces LED power consumption.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # ── SECTION 1: MULTI-DALLE / TILING ───────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  🖼️  Multi-Dalle / Tiling",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        tiling_preset_row = ctk.CTkFrame(parent, fg_color="transparent")
        tiling_preset_row.pack(fill="x", padx=10, pady=2)
        tiling_preset_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tiling_preset_row, text="Dimensions Preset", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._target_preset_menu = ctk.CTkOptionMenu(
            tiling_preset_row,
            variable=self.v_target_preset,
            values=["128x32 (1x1)", "256x32 (2x1)", "128x64 (1x2)", "Custom"],
            command=self._on_target_preset_change,
            width=200,
        )
        self._target_preset_menu.grid(row=0, column=1, sticky="w", padx=4)

        self._custom_tiling_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._custom_tiling_frame.pack(fill="x", padx=10, pady=2)
        self._custom_tiling_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self._custom_tiling_frame, text="Custom Width", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._custom_width_entry = ctk.CTkEntry(
            self._custom_tiling_frame, textvariable=self.v_target_width, width=100
        )
        self._custom_width_entry.grid(row=0, column=1, sticky="w", padx=4)

        ctk.CTkLabel(self._custom_tiling_frame, text="Custom Height", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(4, 6))
        self._custom_height_entry = ctk.CTkEntry(
            self._custom_tiling_frame, textvariable=self.v_target_height, width=100
        )
        self._custom_height_entry.grid(row=1, column=1, sticky="w", padx=4)

        self._on_target_preset_change(self.v_target_preset.get()) # Set initial state

        # ── SECTION 2: TEXT OVERLAY ───────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  💬  Text Overlay",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        text_overlay_row = ctk.CTkFrame(parent, fg_color="transparent")
        text_overlay_row.pack(fill="x", padx=14, pady=(0, 4))
        self._text_overlay_checkbox = ctk.CTkCheckBox(
            text_overlay_row,
            text="Enable Text Overlay",
            variable=self.v_text_overlay_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
            command=self._on_text_overlay_toggle
        )
        self._text_overlay_checkbox.pack(side="left")

        self._text_overlay_frame = ctk.CTkFrame(parent, fg_color="#16213e", corner_radius=6)
        # This frame will be packed/unpacked based on v_text_overlay_enabled

        text_content_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        text_content_row.pack(fill="x", padx=10, pady=2)
        text_content_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_content_row, text="Text Content", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_content_entry = ctk.CTkEntry(
            text_content_row, textvariable=self.v_text_content, width=200
        )
        self._text_content_entry.grid(row=0, column=1, sticky="ew", padx=4)

        adv_slider(self._text_overlay_frame, "Font Size", self.v_text_font_size, 4, 32,
                   "{:.0f}", " px", steps=28, is_int=True)

        text_color_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        text_color_row.pack(fill="x", padx=10, pady=2)
        text_color_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_color_row, text="Text Color", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_color_menu = ctk.CTkOptionMenu(
            text_color_row,
            variable=self.v_text_color,
            values=["white", "yellow", "red", "green", "blue"],
            width=200,
        )
        self._text_color_menu.grid(row=0, column=1, sticky="w", padx=4)

        text_position_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        text_position_row.pack(fill="x", padx=10, pady=2)
        text_position_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_position_row, text="Text Position", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_position_menu = ctk.CTkOptionMenu(
            text_position_row,
            variable=self.v_text_position,
            values=["top_left", "top_center", "top_right", "middle_left", "middle_center", "middle_right", "bottom_left", "bottom_center", "bottom_right"],
            width=200,
        )
        self._text_position_menu.grid(row=0, column=1, sticky="w", padx=4)

        text_font_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        text_font_row.pack(fill="x", padx=10, pady=2)
        text_font_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_font_row, text="Font", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        _available_fonts = [
            "HelvetiPixel.ttf", "PixelMordred.ttf", "BitCasual.ttf",
            "CursivePixel.ttf", "justabit.ttf", "KarenBook.ttf",
            "OldWizard.ttf", "OrdinaryBasis.ttf", "Quintet.ttf", "TimesNewPixel.ttf",
        ]
        self._text_font_menu = ctk.CTkOptionMenu(
            text_font_row,
            variable=self.v_text_font_file,
            values=_available_fonts,
            width=200,
        )
        self._text_font_menu.grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkLabel(
            self._text_overlay_frame,
            text="    Fonts stored in media/fonts/ — pixel fonts optimised for 128×32 DMD panels.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # ── Text Style ────────────────────────────────────────────────────────
        text_style_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        text_style_row.pack(fill="x", padx=10, pady=2)
        text_style_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_style_row, text="Text Style", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_style_menu = ctk.CTkOptionMenu(
            text_style_row,
            variable=self.v_text_style,
            values=["outline", "bold", "shadow", "none"],
            width=200,
        )
        self._text_style_menu.grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkLabel(
            self._text_overlay_frame,
            text="    outline = black border (best on 128×32)  ·  bold = thicker glyph  ·  shadow = drop shadow",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 4), anchor="w")

        # ── Background box ────────────────────────────────────────────────────
        bg_row = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        bg_row.pack(fill="x", padx=10, pady=(4, 2))
        self._text_bg_cb = ctk.CTkCheckBox(
            bg_row,
            text="Background box  (dark box behind text)",
            variable=self.v_text_bg,
            command=self._on_text_bg_toggle,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._text_bg_cb.pack(side="left")

        # Opacity slider — shown only when bg is on
        self._text_bg_opacity_frame = ctk.CTkFrame(self._text_overlay_frame, fg_color="transparent")
        self._text_bg_opacity_frame.pack(fill="x", padx=10, pady=2)
        self._text_bg_opacity_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._text_bg_opacity_frame, text="Box opacity", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_bg_opacity_slider = ctk.CTkSlider(
            self._text_bg_opacity_frame,
            from_=10, to=100, number_of_steps=90,
            variable=self.v_text_bg_opacity,
        )
        self._text_bg_opacity_slider.grid(row=0, column=1, sticky="ew", padx=4)
        self._text_bg_opacity_lbl = ctk.CTkLabel(
            self._text_bg_opacity_frame,
            text="%d %%" % self.v_text_bg_opacity.get(),
            width=60, anchor="e", font=ctk.CTkFont(size=11),
        )
        self._text_bg_opacity_lbl.grid(row=0, column=2, padx=(4, 4))
        self.v_text_bg_opacity.trace_add(
            "write",
            lambda *_: self._text_bg_opacity_lbl.configure(
                text="%d %%" % self.v_text_bg_opacity.get()
            ),
        )
        self._on_text_bg_toggle()  # set initial visibility

        self._on_text_overlay_toggle() # Set initial state

        # ── SECTION 3: POSITIONING ────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  📍  Positioning",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        scroll_row = ctk.CTkFrame(parent, fg_color="transparent")
        scroll_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkCheckBox(
            scroll_row,
            text="Auto vertical scroll  (default — matches standard behaviour)",
            variable=self.v_scroll_enabled,
            command=self._on_scroll_enabled_change,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        ).pack(side="left")

        # Manual positioning frame (hidden when scroll is on)
        self._manual_frame = ctk.CTkFrame(parent, fg_color="#16213e", corner_radius=6)


        ctk.CTkLabel(
            self._manual_frame,
            text="✋  Manual frame — auto-scroll is OFF\n"
                 "    Zoom first, then adjust X / Y to choose the visible 128×32 window.\n"
                 "    DMD preview auto-refreshes ~2 s after you stop moving sliders.",
            text_color="#7799aa", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=12, pady=(8, 6), anchor="w")

        adv_slider(self._manual_frame, "Zoom",     self.v_zoom,     0.5, 4.0,
                   "{:.2f}", "×", steps=70)
        adv_slider(self._manual_frame, "X offset", self.v_manual_x, 0,  512,
                   "{:.0f}", " px", steps=512, is_int=True)
        adv_slider(self._manual_frame, "Y offset", self.v_manual_y, 0,  512,
                   "{:.0f}", " px", steps=512, is_int=True)

        self._on_scroll_enabled_change()   # set initial visibility

        # ── SECTION 4: VISUAL EFFECTS ─────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  ✨  Visual Effects",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(14, 4), anchor="w")

        ctk.CTkLabel(
            parent,
            text="All effects are OFF by default (values = 0 / unchecked).\n"
                 "Non-zero values add extra ffmpeg filter passes.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        adv_slider(parent, "Hue shift",       self.v_hue_shift,       -180.0, 180.0,
                   "{:.0f}", "°", steps=360)
        adv_slider(parent, "Noise reduction", self.v_noise_reduction,   0.0,   8.0,
                   "{:.1f}", "")
        adv_slider(parent, "Film grain",      self.v_film_grain,        0,    50,
                   "{:.0f}", "", steps=50, is_int=True)

        vig_row = ctk.CTkFrame(parent, fg_color="transparent")
        vig_row.pack(fill="x", padx=14, pady=(4, 8))
        ctk.CTkCheckBox(
            vig_row,
            text="Vignette  (darkens edges — default OFF)",
            variable=self.v_vignette, font=ctk.CTkFont(size=12),
        ).pack(side="left")

        ctk.CTkButton(
            parent, text="↺  Reset all advanced to default",
            command=self._reset_advanced,
            height=28, fg_color="transparent", border_width=1,
            border_color="#3a3a5a", text_color="#aaaacc",
            font=ctk.CTkFont(size=11),
        ).pack(padx=12, pady=(2, 10), anchor="w")

    def _on_scroll_enabled_change(self):
        if self.v_scroll_enabled.get():
            self._manual_frame.pack_forget()
        else:
            self._manual_frame.pack(fill="x", padx=10, pady=(4, 4))

    def _on_target_preset_change(self, preset):
        if preset == "Custom":
            self._custom_width_entry.configure(state="normal")
            self._custom_height_entry.configure(state="normal")
        else:
            width, height = map(int, preset.split(" ")[0].split("x"))
            self.v_target_width.set(width)
            self.v_target_height.set(height)
            self._custom_width_entry.configure(state="disabled")
            self._custom_height_entry.configure(state="disabled")
        # Update DMD canvas size immediately
        self._update_dmd_canvas_size()

    def _on_text_overlay_toggle(self):
        if self.v_text_overlay_enabled.get():
            self._text_overlay_frame.pack(fill="x", padx=10, pady=(4, 4))
        else:
            self._text_overlay_frame.pack_forget()

    def _on_text_bg_toggle(self):
        if self.v_text_bg.get():
            self._text_bg_opacity_frame.pack(fill="x", padx=10, pady=2)
        else:
            self._text_bg_opacity_frame.pack_forget()

    def _update_dmd_canvas_size(self, *_):
        w = self.v_target_width.get()
        h = self.v_target_height.get()
        new_width  = int(w * DMD_DISPLAY_SCALE_FACTOR)
        new_height = int(h * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.configure(width=new_width, height=new_height)
        # Update the title label to reflect the current output dimensions
        if hasattr(self, "_dmd_title_label"):
            self._dmd_title_label.configure(text=f"DMD OUTPUT {w}×{h}")
        # Re-center the idle text if it's showing
        if not self._dmd_frames and not self._dmd_rendering:
            self._draw_dmd_canvas_idle()


    def _reset_advanced(self):
        self.v_auto_action_enabled.set(False)
        self.v_action_detector.set("person")
        self.v_action_strength.set(0.65)
        self.v_action_smoothness.set(0.85)
        self.v_action_zoom_max.set(2.0)
        self.v_action_padding.set(0.20)
        self.v_action_intro.set(1.5)
        self.v_bg_sub_enable.set(False) # Reset background subtraction
        self.v_target_preset.set("128x32 (1x1)") # Reset tiling preset
        self.v_target_width.set(DEFAULT_PARAMS["target_width"])
        self.v_target_height.set(DEFAULT_PARAMS["target_height"])
        self._on_target_preset_change(self.v_target_preset.get()) # Apply preset reset
        self.v_text_overlay_enabled.set(False) # Reset text overlay
        self.v_text_content.set("")
        self.v_text_font_size.set(8)
        self.v_text_color.set("white")
        self.v_text_position.set("bottom_center")
        self.v_text_font_file.set("HelvetiPixel.ttf")
        self.v_text_style.set("outline")
        self.v_text_bg.set(False)
        self.v_text_bg_opacity.set(60)
        self._on_text_overlay_toggle() # Apply text overlay reset
        self.v_scroll_enabled.set(True)
        self.v_zoom.set(1.0)
        self.v_manual_x.set(0)
        self.v_manual_y.set(0)
        self.v_hue_shift.set(0.0)
        self.v_noise_reduction.set(0.0)
        self.v_film_grain.set(0)
        self.v_vignette.set(False)
        self._on_scroll_enabled_change()

    # ── Actions + log panel ───────────────────────────────────────────────────
    def _build_actions_panel(self, parent):
        ctk.CTkLabel(
            parent, text="🚀  Actions",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        af = ctk.CTkFrame(parent, fg_color="transparent")
        af.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        af.grid_columnconfigure(0, weight=1)

        self._btn_convert = ctk.CTkButton(
            af,
            text="▶  Convert selected file\n    (click a file in the list first)",
            command=self.convert_selected,
            height=52, fg_color="#1a4f7a", hover_color="#1a618d",
            font=ctk.CTkFont(size=13), state="disabled"
        )
        self._btn_convert.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self._btn_all = ctk.CTkButton(
            af, text="⚡  Convert all listed files",
            command=self.convert_all,
            height=36, fg_color="#5b2fa0", hover_color="#4a2585",
            font=ctk.CTkFont(size=12)
        )
        self._btn_all.grid(row=1, column=0, padx=4, pady=4, sticky="ew")

        self._btn_batch = ctk.CTkButton(
            af, text="📂  Batch — choose a folder",
            command=self.batch_folder,
            height=36, fg_color="#1e6a3c", hover_color="#155230",
            font=ctk.CTkFont(size=12)
        )
        self._btn_batch.grid(row=2, column=0, padx=4, pady=4, sticky="ew")

        self._progress = ctk.CTkProgressBar(af, height=8)
        self._progress.set(0)
        self._progress.grid(row=3, column=0, padx=4, pady=(10, 2), sticky="ew")

        self._status_lbl = ctk.CTkLabel(
            af, text="Ready", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._status_lbl.grid(row=4, column=0, padx=4, pady=2)

        ctk.CTkLabel(
            parent, text="📋  Conversion log",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, padx=12, pady=(10, 2), sticky="w")

        self._log_box = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(size=11, family="Courier"), wrap="word"
        )
        self._log_box.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._log_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  FILE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def add_files(self):
        ext_list = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Select video / GIF files",
            filetypes=[("Video / GIF", ext_list), ("All files", "*.*")]
        )
        if paths:
            self._batch_insert(list(paths), 0)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select source folder")
        if not folder:
            return
        threading.Thread(target=self._scan_folder, args=(folder,), daemon=True).start()

    def _scan_folder(self, folder):
        paths = sorted([
            os.path.join(folder, f) for f in os.listdir(folder)
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ])
        if not paths:
            self.after(0, lambda: messagebox.showinfo(
                "Info", "No supported files found in this folder."))
            return
        self.after(0, lambda: self._batch_insert(paths, 0, folder))

    def _batch_insert(self, paths, start, source_folder=None, batch_size=150):
        batch = paths[start:start + batch_size]
        for p in batch:
            self._add_file_raw(p)
        self._update_count()
        remaining = start + batch_size
        if remaining < len(paths):
            self.after(0, lambda: self._batch_insert(paths, remaining, source_folder, batch_size))
        else:
            folder_name = Path(source_folder).name if source_folder else ""
            if folder_name:
                self._log(f"📂  {len(paths)} file(s) added from '{folder_name}'")

    def _add_file_raw(self, path):
        if path in self._file_paths:
            return
        ext  = Path(path).suffix.lower()
        icon = "🎞" if ext == ".gif" else "🎬"
        name = Path(path).name
        disp = (name[:30] + "…") if len(name) > 32 else name
        iid  = self._tree.insert("", "end", text=f"  {icon}  {disp}", tags=("idle",))
        self._file_data[iid]  = path
        self._file_paths.add(path)

    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == self._selected_iid:
            return
        self._selected_iid = iid
        if hasattr(self, "_btn_convert") and not self._busy:
            self._btn_convert.configure(state="normal")
        path = self._file_data.get(iid)
        if path:
            self._load_preview(path)
            # If Smart Color Boost is active, refresh computed values for this file
            if self.v_auto_color_enabled.get():
                self._refresh_auto_color_values(path)

    def _remove_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if self._selected_iid == iid:
            self._stop_src_preview()
            self._stop_auto_preview()
            self._stop_dmd_preview()
            self._selected_iid = ""
            self._trim_frame.grid_remove()
            self._draw_canvas_idle()
            self._draw_auto_canvas_idle()
            self._draw_dmd_canvas_idle()
        path = self._file_data.pop(iid, None)
        if path:
            self._file_paths.discard(path)
        self._tree.delete(iid)
        self._update_count()

    def clear_files(self):
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        self._tree.delete(*self._tree.get_children())
        self._file_data.clear()
        self._file_paths.clear()
        self._selected_iid = ""
        self._trim_frame.grid_remove()
        self._draw_canvas_idle()
        self._draw_auto_canvas_idle()
        self._draw_dmd_canvas_idle()
        self._update_count()

    def _set_file_status(self, iid, status):
        try:
            self._tree.item(iid, tags=(status,))
        except tk.TclError:
            pass

    def browse_output(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.v_output_dir.set(folder)

    # ══════════════════════════════════════════════════════════════════════════
    #  SOURCE PREVIEW
    # ══════════════════════════════════════════════════════════════════════════

    def _draw_canvas_idle(self):
        self._src_canvas.delete("all")
        self._src_canvas.create_text(
            SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
            text="← Select a file to preview",
            fill="#445566", font=("Helvetica", 12)
        )
        if hasattr(self, "_src_info"):
            self._src_info.configure(text="")
        if hasattr(self, "_btn_convert"):
            self._btn_convert.configure(state="disabled")

    def _draw_dmd_canvas_idle(self):
        self._dmd_canvas.delete("all")
        # Use current target dimensions for idle text positioning
        current_dmd_width = int(self.v_target_width.get() * DMD_DISPLAY_SCALE_FACTOR)
        current_dmd_height = int(self.v_target_height.get() * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(
            current_dmd_width // 2, current_dmd_height // 2,
            text="← Select a file then\n  click 🔬 Refresh DMD",
            fill="#334455", font=("Helvetica", 11), justify="center"
        )
        if hasattr(self, "_dmd_info"):
            self._dmd_info.configure(text="")

    def _draw_auto_canvas_idle(self):
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="Auto action preview\n(disabled by default)",
            fill="#334466", font=("Helvetica", 11), justify="center"
        )
        if hasattr(self, "_auto_info"):
            self._auto_info.configure(text="")

    def _stop_src_preview(self):
        if self._src_job:
            self.after_cancel(self._src_job)
            self._src_job = None
        self._src_pil_frames.clear()
        self._src_frames.clear()
        self._src_delays.clear()
        self._src_idx = 0
        if self._src_tmpdir and os.path.isdir(self._src_tmpdir):
            shutil.rmtree(self._src_tmpdir, ignore_errors=True)
            self._src_tmpdir = None

    def _stop_auto_preview(self):
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        self._auto_pil_frames.clear()
        self._auto_frames.clear()
        self._auto_delays.clear()
        self._auto_idx = 0
        if self._auto_tmpdir and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None

    # Backward-compat alias
    def _stop_preview(self):
        self._stop_src_preview()

    def _load_preview(self, file_path):
        self._stop_src_preview()
        self._src_canvas.delete("all")
        self._src_canvas.create_text(
            SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
            text="⏳  Loading preview…",
            fill="#7ec8e3", font=("Helvetica", 12)
        )
        w, h, fps, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self._update_trim_sliders()
        self._trim_frame.grid()

        threading.Thread(
            target=self._extract_source_frames,
            args=(file_path,), daemon=True
        ).start()

        # Keep all three previews in sync when a new file is selected.
        self._start_auto_generation(file_path)
        self._start_dmd_generation(file_path)

    def _extract_source_frames(self, file_path):
        tmpdir = tempfile.mkdtemp(prefix="dmd_src_")
        fps_prev = 12.5
        dur = min(self._source_duration, 10.0)
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-t", str(dur),
            "-vf", (
                f"fps={fps_prev},"
                f"scale={SRC_CANVAS_W}:{SRC_CANVAS_H}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={SRC_CANVAS_W}:{SRC_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                f":color={BG_CANVAS[1:]}"
            ),
            "-f", "image2", os.path.join(tmpdir, "f%04d.png")
        ]
        subprocess.run(cmd, capture_output=True)
        paths = sorted(glob.glob(os.path.join(tmpdir, "f*.png")))
        # Decode as plain PIL Images — PhotoImage must be created on the main thread
        pil_frames, delays = [], []
        delay_ms = int(1000 / fps_prev)
        for fp in paths:
            try:
                pil_frames.append(Image.open(fp).convert("RGB").copy())
                delays.append(delay_ms)
            except Exception:
                pass
        self.after(0, lambda: self._on_source_frames_ready(pil_frames, delays, tmpdir, file_path))

    def _on_source_frames_ready(self, pil_frames, delays, tmpdir, file_path):
        if not pil_frames:
            self._src_canvas.delete("all")
            self._src_canvas.create_text(
                SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
                text="⚠️  Preview unavailable\n(ffmpeg missing?)",
                fill="#e74c3c", font=("Helvetica", 11), justify="center"
            )
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._src_tmpdir = tmpdir
        self._src_pil_frames = pil_frames
        self._src_frames = [None] * len(pil_frames)   # lazy PhotoImage cache
        self._src_delays = delays
        self._src_idx    = 0
        name = Path(file_path).name
        self._src_info.configure(
            text=f"{name}   ·   {len(pil_frames)} frames   ·   {self._source_duration:.1f} s"
        )
        self._animate_src()

    def _animate_src(self):
        if not self._src_pil_frames:
            return
        idx = self._src_idx % len(self._src_pil_frames)
        # Lazy PhotoImage creation — one frame at a time on the main thread
        if self._src_frames[idx] is None:
            self._src_frames[idx] = ImageTk.PhotoImage(self._src_pil_frames[idx])
        self._src_canvas.delete("all")
        self._src_canvas.create_image(0, 0, anchor="nw", image=self._src_frames[idx])
        self._src_idx = idx + 1
        delay = self._src_delays[idx] if self._src_delays else 80
        self._src_job = self.after(delay, self._animate_src)

    def show_source_preview(self):
        if self._selected_iid:
            path = self._file_data.get(self._selected_iid)
            if path:
                self._load_preview(path)
        else:
            messagebox.showinfo("Info", "Select a file first.")

    def refresh_all_previews(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        path = self._file_data.get(self._selected_iid)
        if not path:
            return
        self._load_preview(path)
        self._start_auto_generation(path)
        self._start_dmd_generation(path)

    def show_auto_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._start_auto_generation(src)

    def _start_auto_generation(self, src):
        if self._auto_rendering:
            # Queue the latest request — will start once the current render finishes
            self._auto_pending_src = src
            return
        if not self.v_auto_action_enabled.get():
            self._stop_auto_preview()
            self._draw_auto_canvas_idle()
            self._auto_info.configure(text="Auto action disabled")
            return
        if preprocess_video_for_dmd is None or AutoActionConfig is None:
            self._draw_auto_canvas_idle()
            self._auto_info.configure(text="Auto action unavailable (module missing)")
            return

        self._auto_pending_src = None
        self._auto_rendering = True
        self._stop_auto_preview()
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="⏳  Generating auto-action preview…",
            fill="#7aa2ff", font=("Helvetica", 11), justify="center"
        )
        self._btn_auto.configure(state="disabled", text="⏳ Auto…")

        start_s, end_s = self._get_trim()
        cfg = AutoActionConfig(
            detector=self.v_action_detector.get(),
            strength=float(self.v_action_strength.get()),
            smoothness=float(self.v_action_smoothness.get()),
            zoom_max=float(self.v_action_zoom_max.get()),
            padding=float(self.v_action_padding.get()),
            intro_duration=float(self.v_action_intro.get()),
            bg_sub_enable=self.v_bg_sub_enable.get(),
            start_s=start_s,
            end_s=end_s,
            target_width=self.v_target_width.get(),
            target_height=self.v_target_height.get(),
        )
        threading.Thread(
            target=self._generate_auto_preview,
            args=(src, cfg), daemon=True
        ).start()

    def _generate_auto_preview(self, src, cfg):
        """Run in a background thread. Returns PIL images (NOT PhotoImage) to the main thread."""
        try:
            ok, out_mp4, msg = preprocess_video_for_dmd(src, cfg)
            if not ok or not out_mp4:
                self.after(0, lambda: self._on_auto_fail(msg))
                return

            tmpdir = os.path.dirname(out_mp4)
            fps_prev = 12.5
            cmd = [
                "ffmpeg", "-y", "-i", out_mp4,
                "-vf", (
                    f"fps={fps_prev},"
                    f"scale={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:"
                    f"force_original_aspect_ratio=decrease,"
                    f"pad={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                    f":color={BG_CANVAS[1:]}"
                ),
                "-f", "image2", os.path.join(tmpdir, "a%04d.png"),
            ]
            subprocess.run(cmd, capture_output=True)

            paths = sorted(glob.glob(os.path.join(tmpdir, "a*.png")))
            # Decode as plain PIL Images — PhotoImage must be created on the main thread
            pil_frames, delays = [], []
            delay_ms = int(1000 / fps_prev)
            for fp in paths:
                try:
                    pil_frames.append(Image.open(fp).convert("RGB").copy())
                    delays.append(delay_ms)
                except Exception:
                    pass

            self.after(0, lambda: self._on_auto_ready(pil_frames, delays, tmpdir, msg))

        except Exception as exc:
            # Safety net: always unblock the rendering flag even on unexpected errors
            self.after(0, lambda: self._on_auto_fail(f"Unexpected error: {exc}"))

    def _on_auto_ready(self, pil_frames, delays, tmpdir, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        if not pil_frames:
            self._on_auto_fail("No frames produced for auto-action preview")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._stop_auto_preview()
        self._auto_tmpdir = tmpdir
        # Store PIL Images; PhotoImages are created lazily in _animate_auto (main thread, one per tick)
        self._auto_pil_frames = pil_frames
        self._auto_frames = [None] * len(pil_frames)
        self._auto_delays = delays
        self._auto_idx = 0
        self._auto_info.configure(text=f"{msg}  ·  {len(pil_frames)} frames")
        self._animate_auto()
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_auto_pending()

    def _on_auto_fail(self, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        # Ensure tmpdir is defined before trying to remove it
        if hasattr(self, '_auto_tmpdir') and self._auto_tmpdir and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="❌  Auto-action failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._auto_info.configure(text=msg)
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_auto_pending()

    def _flush_auto_pending(self):
        """If an Auto render was requested while we were busy, start it now."""
        pending = self._auto_pending_src
        self._auto_pending_src = None
        if pending and self._selected_iid:
            self.after(50, lambda: self._start_auto_generation(pending))

    def _animate_auto(self):
        if not self._auto_pil_frames:
            return
        idx = self._auto_idx % len(self._auto_pil_frames)
        # Lazy PhotoImage creation — one frame at a time on the main thread
        if self._auto_frames[idx] is None:
            self._auto_frames[idx] = ImageTk.PhotoImage(self._auto_pil_frames[idx])
        self._auto_canvas.delete("all")
        self._auto_canvas.create_image(0, 0, anchor="nw", image=self._auto_frames[idx])
        self._auto_idx = idx + 1
        delay = self._auto_delays[idx] if self._auto_delays else 80
        self._auto_job = self.after(delay, self._animate_auto)

    # ══════════════════════════════════════════════════════════════════════════
    #  DMD PREVIEW  (independent canvas + animation loop)
    # ══════════════════════════════════════════════════════════════════════════

    def _stop_dmd_preview(self):
        if self._dmd_job:
            self.after_cancel(self._dmd_job)
            self._dmd_job = None
        self._dmd_pil_frames.clear()
        self._dmd_frames.clear()
        self._dmd_delays.clear()
        self._dmd_idx = 0
        if self._dmd_tmpdir and os.path.isdir(self._dmd_tmpdir):
            shutil.rmtree(self._dmd_tmpdir, ignore_errors=True)
            self._dmd_tmpdir = None

    def show_dmd_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._start_dmd_generation(src)

    def _start_dmd_generation(self, src):
        if self._dmd_rendering:
            # Queue the latest request — will start once the current render finishes
            self._dmd_pending_src = src
            return
        self._dmd_pending_src = None
        self._dmd_rendering = True
        self._stop_dmd_preview()
        self._dmd_canvas.delete("all")
        # Use current target dimensions for idle text positioning
        current_dmd_width = int(self.v_target_width.get() * DMD_DISPLAY_SCALE_FACTOR)
        current_dmd_height = int(self.v_target_height.get() * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(
            current_dmd_width // 2, current_dmd_height // 2,
            text="⏳  Generating DMD…\n  (a few seconds)",
            fill="#f39c12", font=("Helvetica", 11), justify="center"
        )
        self._btn_dmd.configure(state="disabled", text="⏳ DMD…")
        params  = self._collect_params()
        start_s, end_s = self._get_trim()
        # Capture display dimensions on the main thread (Tkinter is not thread-safe)
        dmd_display_w = current_dmd_width
        dmd_display_h = current_dmd_height
        threading.Thread(
            target=self._generate_dmd_preview,
            args=(src, params, start_s, end_s, dmd_display_w, dmd_display_h), daemon=True
        ).start()

    def _generate_dmd_preview(self, src, params, start_s, end_s, dmd_display_w, dmd_display_h):
        """Run in a background thread. Returns PIL images (NOT PhotoImage) to the main thread."""
        tmpdir  = tempfile.mkdtemp(prefix="dmd_dmd_")
        try:
            out_gif = os.path.join(tmpdir, "preview.gif")
            success, msg = process_file(src, out_gif, params, start_s, end_s)

            if not success or not os.path.isfile(out_gif):
                self.after(0, lambda: self._on_dmd_fail(msg, tmpdir))
                return

            # Decode frames as plain PIL Images — PhotoImage must be created on the main thread
            pil_frames, delays = [], []
            try:
                img = Image.open(out_gif)
                while True:
                    pil_frames.append(
                        img.copy().convert("RGB").resize(
                            (dmd_display_w, dmd_display_h), Image.NEAREST
                        )
                    )
                    delays.append(max(img.info.get("duration", 80), 20))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass
            except Exception as exc:
                self.after(0, lambda: self._on_dmd_fail(str(exc), tmpdir))
                return

            if not pil_frames:
                self.after(0, lambda: self._on_dmd_fail("No frames decoded from GIF", tmpdir))
                return

            self.after(0, lambda: self._on_dmd_ready(pil_frames, delays, tmpdir, out_gif))

        except Exception as exc:
            # Safety net: always unblock the rendering flag even on unexpected errors
            self.after(0, lambda: self._on_dmd_fail(f"Unexpected error: {exc}", tmpdir))

    def _on_dmd_ready(self, pil_frames, delays, tmpdir, out_gif):
        self._dmd_rendering = False
        self._btn_dmd.configure(state="normal", text="🔬 DMD")
        self._stop_dmd_preview()
        self._dmd_tmpdir = tmpdir
        # Store PIL Images; PhotoImages are created lazily in _animate_dmd (main thread, one per tick)
        self._dmd_pil_frames = pil_frames
        self._dmd_frames = [None] * len(pil_frames)
        self._dmd_delays = delays
        self._dmd_idx    = 0
        size_kb = os.path.getsize(out_gif) // 1024
        self._dmd_info.configure(
            text=f"✅  {self.v_target_width.get()}×{self.v_target_height.get()}  ·  {len(pil_frames)} frames  ·  {size_kb} KB"
        )
        self._animate_dmd()
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_dmd_pending()

    def _on_dmd_fail(self, msg, tmpdir):
        self._dmd_rendering = False
        self._btn_dmd.configure(state="normal", text="🔬 DMD")
        shutil.rmtree(tmpdir, ignore_errors=True)
        self._dmd_canvas.delete("all")
        # Use current target dimensions for idle text positioning
        current_dmd_width = int(self.v_target_width.get() * DMD_DISPLAY_SCALE_FACTOR)
        current_dmd_height = int(self.v_target_height.get() * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(
            current_dmd_width // 2, current_dmd_height // 2,
            text="❌  DMD render failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._log(f"❌  DMD preview: {msg}", "error")
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_dmd_pending()

    def _flush_dmd_pending(self):
        """If a DMD render was requested while we were busy, start it now."""
        pending = self._dmd_pending_src
        self._dmd_pending_src = None
        if pending and self._selected_iid:
            self.after(50, lambda: self._start_dmd_generation(pending))

    def _animate_dmd(self):
        if not self._dmd_pil_frames:
            return
        idx = self._dmd_idx % len(self._dmd_pil_frames)
        # Lazy PhotoImage creation — one frame at a time on the main thread
        if self._dmd_frames[idx] is None:
            self._dmd_frames[idx] = ImageTk.PhotoImage(self._dmd_pil_frames[idx])
        self._dmd_canvas.delete("all")
        self._dmd_canvas.create_image(0, 0, anchor="nw", image=self._dmd_frames[idx])
        self._dmd_idx = idx + 1
        delay = self._dmd_delays[idx] if self._dmd_delays else 80
        self._dmd_job = self.after(delay, self._animate_dmd)

    # ── Auto-refresh debounce ─────────────────────────────────────────────────
    def _schedule_pipeline_refresh(self, *_):
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self._adv_refresh_job = self.after(DMD_REFRESH_DELAY_MS, self._auto_refresh_pipeline)

    def _auto_refresh_pipeline(self):
        self._adv_refresh_job = None
        if self._selected_iid and not self._busy and not self._auto_rendering and not self._dmd_rendering:
            src = self._file_data.get(self._selected_iid)
            if src:
                self._start_auto_generation(src)
                self._start_dmd_generation(src)

    # ══════════════════════════════════════════════════════════════════════════
    #  TRIM
    # ══════════════════════════════════════════════════════════════════════════

    # ── Max-duration helpers ──────────────────────────────────────────────────
    def _on_max_dur_toggle(self):
        """Enable/disable the max-duration slider and refresh the trim end."""
        enabled = self.v_max_dur_enabled.get()
        self._max_dur_slider.configure(state="normal" if enabled else "disabled")
        if hasattr(self, "_sl_end"):
            self._sl_end.configure(state="disabled" if enabled else "normal")
        self._apply_max_duration()

    def _apply_max_duration(self):
        """If max_duration is active, snap trim_end to trim_start + max_duration."""
        if not self.v_max_dur_enabled.get():
            return
        if not hasattr(self, "_sl_end"):
            return
        start = self.v_trim_start.get()
        max_dur = self.v_max_duration.get()
        new_end = min(start + max_dur, self._source_duration)
        self.v_trim_end.set(new_end)
        if hasattr(self, "_lbl_end"):
            self._lbl_end.configure(text=f"{new_end:.1f} s")

    def _update_trim_sliders(self):
        dur = max(self._source_duration, 0.1)
        self._sl_start.configure(to=dur)
        self._sl_end.configure(to=dur)
        self.v_trim_start.set(0.0)
        # When max_duration is active, initialise end = min(max_dur, dur)
        if self.v_max_dur_enabled.get():
            init_end = min(self.v_max_duration.get(), dur)
        else:
            init_end = dur
        self.v_trim_end.set(init_end)
        self._lbl_start.configure(text="0.0 s")
        self._lbl_end.configure(text=f"{init_end:.1f} s")
        # Reflect max-dur state on end slider
        self._sl_end.configure(
            state="disabled" if self.v_max_dur_enabled.get() else "normal"
        )

    def _on_start_drag(self, val):
        v = float(val)
        end = self.v_trim_end.get()
        if self.v_max_dur_enabled.get():
            # End follows start automatically — clamp start to leave room
            max_dur = self.v_max_duration.get()
            v = min(v, max(0.0, self._source_duration - max_dur))
            self.v_trim_start.set(v)
            new_end = min(v + max_dur, self._source_duration)
            self.v_trim_end.set(new_end)
            self._lbl_end.configure(text=f"{new_end:.1f} s")
        else:
            if v >= end:
                self.v_trim_start.set(max(0.0, end - 0.05))
        self._lbl_start.configure(text=f"{self.v_trim_start.get():.1f} s")

    def _on_end_drag(self, val):
        v = float(val)
        start = self.v_trim_start.get()
        if v <= start:
            self.v_trim_end.set(min(self._source_duration, start + 0.05))
        self._lbl_end.configure(text=f"{self.v_trim_end.get():.1f} s")

    def _reset_trim(self):
        self.v_trim_start.set(0.0)
        self.v_trim_end.set(self._source_duration)
        self._lbl_start.configure(text="0.0 s")
        self._lbl_end.configure(text=f"{self._source_duration:.1f} s")

    def _get_trim(self):
        s = self.v_trim_start.get()
        e = self.v_trim_end.get()
        if s <= 0.0 and e >= self._source_duration - 0.05:
            return None, None
        return s, e

    # ══════════════════════════════════════════════════════════════════════════
    #  PARAMS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_mode_change(self, mode):
        self._mode_desc_lbl.configure(text=_MODE_DESC.get(mode, ""))
        self._update_custom_visibility()

    def _on_auto_color_toggle(self):
        """Enable/disable Smart Color Boost.

        When enabled:
          • Greys out the mode selector and all colorimetry sliders so the user
            cannot accidentally override the computed values.
          • Saves colorimetry slider values in case mode is "custom" (so we can
            restore them when disabling).
          • Launches a background analysis and writes computed values + deltas
            into the info label.  If mode is already "custom", also fills the
            greyed sliders for visual feedback.
          NOTE: the mode is intentionally NOT changed — switching it would
          re-pack the colorimetry frame and push the Advanced Settings panel
          out of position.

        When disabled:
          • Restores the mode selector and colorimetry sliders.
          • If mode is "custom", restores the slider values to what they were
            before Smart Color Boost took over.
          • Clears the info label.
        """
        enabled = self.v_auto_color_enabled.get()

        if enabled:
            # ── Save colorimetry values (only used if mode == "custom") ────────
            self._pre_auto_color_values = {
                "contrast":    self.v_contrast.get(),
                "saturation":  self.v_saturation.get(),
                "brightness":  self.v_brightness.get(),
                "gamma":       self.v_gamma.get(),
                "sharpen_lum": self.v_sharpen_lum.get(),
                "sharpen_chr": self.v_sharpen_chr.get(),
            }
            # ── Grey out mode selector + colorimetry widgets ───────────────────
            self._mode_menu.configure(state="disabled")
            for w in self._colorimetry_widgets:
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass
            # ── Trigger background analysis ────────────────────────────────────
            self._auto_color_info.configure(text="⏳  Analysing…")
            if self._selected_iid:
                path = self._file_data.get(self._selected_iid)
                if path:
                    self._refresh_auto_color_values(path)
        else:
            # ── Restore colorimetry slider values (custom mode only) ───────────
            if self.v_mode.get() == "custom" and self._pre_auto_color_values:
                self.v_contrast.set(self._pre_auto_color_values["contrast"])
                self.v_saturation.set(self._pre_auto_color_values["saturation"])
                self.v_brightness.set(self._pre_auto_color_values["brightness"])
                self.v_gamma.set(self._pre_auto_color_values["gamma"])
                self.v_sharpen_lum.set(self._pre_auto_color_values["sharpen_lum"])
                self.v_sharpen_chr.set(self._pre_auto_color_values["sharpen_chr"])
            # ── Re-enable controls ─────────────────────────────────────────────
            self._mode_menu.configure(state="normal")
            for w in self._colorimetry_widgets:
                try:
                    w.configure(state="normal")
                except Exception:
                    pass
            self._auto_color_info.configure(text="")

    def _refresh_auto_color_values(self, path: str):
        """Run colorimetry analysis in background; update info label + sliders.

        The info label always shows the computed values + delta vs pixel_art.
        Slider vars are updated only when mode is already "custom" — we never
        force a mode switch here to avoid disrupting the pack layout.
        """
        if _ui_analyze_color is None:
            self._auto_color_info.configure(
                text="⚠️  OpenCV unavailable — install opencv-python"
            )
            return
        if self._auto_color_analyzing:
            return

        self._auto_color_analyzing = True
        self._auto_color_info.configure(text="⏳  Analysing keyframes…")

        def _run():
            try:
                ok, params, msg = _ui_analyze_color(path)
            except Exception as exc:
                ok, params, msg = False, {}, str(exc)

            def _apply():
                self._auto_color_analyzing = False
                if not self.v_auto_color_enabled.get():
                    return
                if ok and params:
                    # Update sliders only if already in custom mode
                    # (avoids re-packing layout and blocking Advanced Settings)
                    if self.v_mode.get() == "custom":
                        self.v_contrast.set(params["contrast"])
                        self.v_saturation.set(params["saturation"])
                        self.v_brightness.set(params["brightness"])
                        self.v_gamma.set(params["gamma"])
                        self.v_sharpen_lum.set(params.get("sharpen_lum", 1.8))
                        self.v_sharpen_chr.set(params.get("sharpen_chr", 0.5))
                    dc = params["contrast"]   - 1.60
                    ds = params["saturation"] - 2.20
                    self._auto_color_info.configure(
                        text=(
                            f"c={params['contrast']} ({dc:+.2f})  "
                            f"s={params['saturation']} ({ds:+.2f})  "
                            f"γ={params['gamma']}  bri={params['brightness']:+.3f}"
                        )
                    )
                else:
                    self._auto_color_info.configure(text=f"⚠️  {msg[:70]}")

            self.after(0, _apply)

        threading.Thread(target=_run, daemon=True).start()

    def _update_custom_visibility(self):
        is_custom = self.v_mode.get() == "custom"
        if is_custom:
            self._custom_header.pack(fill="x", padx=8, pady=(12, 2), anchor="w")
            self._custom_frame.pack(fill="x")
        else:
            self._custom_header.pack_forget()
            self._custom_frame.pack_forget()

    def _collect_params(self):
        return {
            # Standard parameters (identical to v2.0 defaults — no change)
            "mode":            self.v_mode.get(),
            "max_workers":     self.v_workers.get(),
            "scroll_speed":    self.v_scroll.get(),
            "bottom_crop_pct": self.v_bottom_crop.get(),
            "scroll_cycles":   self.v_scroll_cycles.get(),
            "fps_min":         self.v_fps_min.get(),
            "fps_max":         self.v_fps_max.get(),
            "contrast":        self.v_contrast.get(),
            "saturation":      self.v_saturation.get(),
            "brightness":      self.v_brightness.get(),
            "gamma":           self.v_gamma.get(),
            "sharpen_lum":     self.v_sharpen_lum.get(),
            "sharpen_chr":     self.v_sharpen_chr.get(),
            "dither":          self.v_dither.get(),
            # Advanced parameters (all default = no change vs v2.0)
            "scroll_enabled":  self.v_scroll_enabled.get(),
            "zoom":            self.v_zoom.get(),
            "manual_x":        self.v_manual_x.get(),
            "manual_y":        self.v_manual_y.get(),
            "hue_shift":       self.v_hue_shift.get(),
            "noise_reduction": self.v_noise_reduction.get(),
            "film_grain":      int(self.v_film_grain.get()),
            "vignette":        self.v_vignette.get(),
            "auto_action_enabled": self.v_auto_action_enabled.get(),
            "action_detector": self.v_action_detector.get(),
            "action_strength": self.v_action_strength.get(),
            "action_smoothness": self.v_action_smoothness.get(),
            "action_zoom_max": self.v_action_zoom_max.get(),
            "action_padding": self.v_action_padding.get(),
            "action_intro": self.v_action_intro.get(),
            "bg_sub_enable": self.v_bg_sub_enable.get(),
            "target_width": self.v_target_width.get(),
            "target_height": self.v_target_height.get(),
            "text_overlay_enabled": self.v_text_overlay_enabled.get(), # Collect text overlay params
            "text_content": self.v_text_content.get(),
            "text_font_size": self.v_text_font_size.get(),
            "text_color": self.v_text_color.get(),
            "text_position": self.v_text_position.get(),
            "text_font_file": self.v_text_font_file.get(),
            "text_style": self.v_text_style.get(),
            "text_bg": self.v_text_bg.get(),
            "text_bg_opacity": self.v_text_bg_opacity.get(),
            # max_duration: 0 = no limit when checkbox is off
            "max_duration": self.v_max_duration.get() if self.v_max_dur_enabled.get() else 0.0,
            # auto-colorimetry
            "auto_color_enabled": self.v_auto_color_enabled.get(),
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  CONVERSION
    # ══════════════════════════════════════════════════════════════════════════

    def _out_path(self, src):
        stem    = Path(src).stem
        out_dir = self.v_output_dir.get().strip() or str(Path(src).parent)
        return os.path.join(out_dir, stem + ".gif")

    def convert_selected(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file from the list first.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        out = self._out_path(src)
        start_s, end_s = self._get_trim()
        trim_info = f"  trim [{start_s:.1f}s → {end_s:.1f}s]" if start_s is not None else ""
        self._log(f"▶  Convert: {Path(src).name}{trim_info}")
        tasks = [(src, out, start_s, end_s, self._selected_iid)]
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def convert_all(self):
        if not self._file_data:
            messagebox.showinfo("Info", "The file list is empty.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        tasks = [
            (path, self._out_path(path), None, None, iid)
            for iid, path in self._file_data.items()
        ]
        self._log(f"⚡  Converting {len(tasks)} file(s)…")
        for _, _, _, _, iid in tasks:
            self._set_file_status(iid, "converting")
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def batch_folder(self):
        folder_in = filedialog.askdirectory(title="Source folder — Batch")
        if not folder_in:
            return
        out_dir = self.v_output_dir.get().strip()
        if not out_dir:
            out_dir = str(Path(folder_in).parent / (Path(folder_in).name + "_DMD"))
        files = [
            f for f in os.listdir(folder_in)
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            messagebox.showinfo("Info", "No supported files found in this folder.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        params = self._collect_params()
        self._log(f"📂  Batch: {len(files)} file(s)  →  {out_dir}")
        threading.Thread(
            target=self._run_batch_folder, args=(folder_in, out_dir, params), daemon=True
        ).start()

    def _run_tasks(self, tasks, params):
        self.after(0, lambda: self._set_busy(True))
        total = len(tasks)
        for i, (src, out, start_s, end_s, iid) in enumerate(tasks):
            self.after(0, lambda _iid=iid: self._set_file_status(_iid, "converting"))
            success, msg = process_file(
                src, out, params, start_s, end_s,
                callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv))
            )
            status = "done" if success else "error"
            self.after(0, lambda _iid=iid, s=status: self._set_file_status(_iid, s))
            self.after(0, lambda p=(i + 1) / total: self._progress.set(p))
        self.after(0, lambda: self._log(f"✅  {total} conversion(s) done."))
        self.after(0, lambda: self._set_busy(False))

    def _run_batch_folder(self, folder_in, folder_out, params):
        self.after(0, lambda: self._set_busy(True))
        process_folder(
            folder_in, folder_out, params,
            callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv))
        )
        self.after(0, lambda: self._log("✅  Batch folder done."))
        self.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self._btn_convert, self._btn_all, self._btn_batch):
            btn.configure(state=state)
        for btn in (self._btn_all_prev, self._btn_src, self._btn_auto, self._btn_dmd):
            btn.configure(state=state)
        self._status_lbl.configure(text="⏳  Converting…" if busy else "Ready")
        if not busy:
            self._progress.set(1.0)
            self.after(2500, lambda: self._progress.set(0))

    # ══════════════════════════════════════════════════════════════════════════
    #  LOG
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, message, level="info"):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", message + "\n")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    # ══════════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

    def _on_close(self):
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self.destroy()


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