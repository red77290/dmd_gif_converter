#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMD GIF Converter — Graphical Interface  v2.1
Cross-platform UI (macOS · Windows · Linux) to convert any video/GIF
to 128×32 LED DMD format.

New in v2.1:
  • Triple real-time preview (SOURCE + AUTO ACTION + DMD)
  • Auto/DMD preview auto-refreshes ~2 s after any parameter change
  • 🔧 Advanced Settings panel (collapsed by default):
      – Manual positioning: disable auto-scroll, set zoom / X / Y manually
      – Visual effects: hue shift, noise reduction, film grain, vignette

Usage:
    python dmd_gif_converter_ui.py
"""

import os
import sys
import platform
import glob
import shutil
import threading
import tempfile
import subprocess
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox

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
    print(f"\n❌  Missing dependencies: {', '.join(_missing)}")
    print(f"    Install them with:\n\n    pip install {' '.join(_missing)}\n")
    sys.exit(1)

# ── Import converter engine ───────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dmd_gif_converter import (
        get_metadata, process_file, process_folder,
        DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
    )
except ImportError as exc:
    print(f"❌  Could not import dmd_gif_converter: {exc}")
    sys.exit(1)

try:
    from dmd_auto_action import AutoActionConfig, preprocess_video_for_dmd
except ImportError:
    AutoActionConfig = None
    preprocess_video_for_dmd = None

# ── Constants ─────────────────────────────────────────────────────────────────
# Three preview canvases
SRC_CANVAS_W  = 300
SRC_CANVAS_H  = 170
AUTO_CANVAS_W = 300
AUTO_CANVAS_H = 170
DMD_CANVAS_W  = 300
DMD_CANVAS_H  = 170

# DMD output is still displayed at 128×32 scaled ×2.34
DMD_DISP_W    = 300
DMD_DISP_H    = 75

BG_CANVAS     = "#0d0d1a"
APP_VERSION   = "2.1"

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
        self._src_frames: list  = []
        self._src_delays: list  = []
        self._src_idx           = 0
        self._src_job           = None
        self._src_tmpdir        = None

        # DMD preview state (independent animation loop)
        self._dmd_frames: list  = []
        self._dmd_delays: list  = []
        self._dmd_idx           = 0
        self._dmd_job           = None
        self._dmd_tmpdir        = None
        self._dmd_rendering     = False

        # Auto-action preview state (intermediate pre-ffmpeg stage)
        self._auto_frames: list = []
        self._auto_delays: list = []
        self._auto_idx          = 0
        self._auto_job          = None
        self._auto_tmpdir       = None
        self._auto_rendering    = False

        # Auto-refresh debounce job
        self._adv_refresh_job   = None

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

        # ── Tkinter vars — max duration cap ───────────────────────────────────
        self.v_max_dur_enabled = tk.BooleanVar(value=True)    # ON by default (2 min cap)
        self.v_max_duration    = tk.DoubleVar(value=120.0)    # 2 minutes

        # ── Tkinter vars — auto-colorimetry ───────────────────────────────────
        self.v_auto_color_enabled = tk.BooleanVar(value=False)

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
            self.v_action_intro,
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
        ctk.CTkLabel(
            dmd_wrap, text="DMD OUTPUT 128×32",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#2e7a4a"
        ).pack(pady=(4, 0))
        self._dmd_canvas = tk.Canvas(
            dmd_wrap, width=DMD_CANVAS_W, height=DMD_CANVAS_H,
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

        # ── SECTION 1: POSITIONING ────────────────────────────────────────────
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

        # ── SECTION 2: VISUAL EFFECTS ─────────────────────────────────────────
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

    def _reset_advanced(self):
        self.v_auto_action_enabled.set(False)
        self.v_action_detector.set("person")
        self.v_action_strength.set(0.65)
        self.v_action_smoothness.set(0.85)
        self.v_action_zoom_max.set(2.0)
        self.v_action_padding.set(0.20)
        self.v_action_intro.set(1.5)
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
        self._dmd_canvas.create_text(
            DMD_CANVAS_W // 2, DMD_CANVAS_H // 2,
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
        frames, delays = [], []
        delay_ms = int(1000 / fps_prev)
        for fp in paths:
            try:
                img = Image.open(fp).convert("RGB")
                frames.append(ImageTk.PhotoImage(img))
                delays.append(delay_ms)
            except Exception:
                pass
        self.after(0, lambda: self._on_source_frames_ready(frames, delays, tmpdir, file_path))

    def _on_source_frames_ready(self, frames, delays, tmpdir, file_path):
        if not frames:
            self._src_canvas.delete("all")
            self._src_canvas.create_text(
                SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
                text="⚠️  Preview unavailable\n(ffmpeg missing?)",
                fill="#e74c3c", font=("Helvetica", 11), justify="center"
            )
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._src_tmpdir = tmpdir
        self._src_frames = frames
        self._src_delays = delays
        self._src_idx    = 0
        name = Path(file_path).name
        self._src_info.configure(
            text=f"{name}   ·   {len(frames)} frames   ·   {self._source_duration:.1f} s"
        )
        self._animate_src()

    def _animate_src(self):
        if not self._src_frames:
            return
        idx = self._src_idx % len(self._src_frames)
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
            start_s=start_s,
            end_s=end_s,
        )
        threading.Thread(
            target=self._generate_auto_preview,
            args=(src, cfg), daemon=True
        ).start()

    def _generate_auto_preview(self, src, cfg):
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
        frames, delays = [], []
        delay_ms = int(1000 / fps_prev)
        for fp in paths:
            try:
                img = Image.open(fp).convert("RGB")
                frames.append(ImageTk.PhotoImage(img))
                delays.append(delay_ms)
            except Exception:
                pass

        self.after(0, lambda: self._on_auto_ready(frames, delays, tmpdir, msg))

    def _on_auto_ready(self, frames, delays, tmpdir, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        if not frames:
            self._on_auto_fail("No frames produced for auto-action preview")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._stop_auto_preview()
        self._auto_tmpdir = tmpdir
        self._auto_frames = frames
        self._auto_delays = delays
        self._auto_idx = 0
        self._auto_info.configure(text=f"{msg}  ·  {len(frames)} frames")
        self._animate_auto()

    def _on_auto_fail(self, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="❌  Auto-action failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._auto_info.configure(text=msg)

    def _animate_auto(self):
        if not self._auto_frames:
            return
        idx = self._auto_idx % len(self._auto_frames)
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
            return
        self._dmd_rendering = True
        self._stop_dmd_preview()
        self._dmd_canvas.delete("all")
        self._dmd_canvas.create_text(
            DMD_CANVAS_W // 2, DMD_CANVAS_H // 2,
            text="⏳  Generating DMD…\n  (a few seconds)",
            fill="#f39c12", font=("Helvetica", 11), justify="center"
        )
        self._btn_dmd.configure(state="disabled", text="⏳ DMD…")
        params  = self._collect_params()
        start_s, end_s = self._get_trim()
        threading.Thread(
            target=self._generate_dmd_preview,
            args=(src, params, start_s, end_s), daemon=True
        ).start()

    def _generate_dmd_preview(self, src, params, start_s, end_s):
        tmpdir  = tempfile.mkdtemp(prefix="dmd_dmd_")
        out_gif = os.path.join(tmpdir, "preview.gif")
        success, msg = process_file(src, out_gif, params, start_s, end_s)

        if not success or not os.path.isfile(out_gif):
            self.after(0, lambda: self._on_dmd_fail(msg, tmpdir))
            return

        frames, delays = [], []
        try:
            img = Image.open(out_gif)
            while True:
                frame = img.copy().convert("RGB").resize(
                    (DMD_DISP_W, DMD_DISP_H), Image.NEAREST
                )
                frames.append(ImageTk.PhotoImage(frame))
                delays.append(max(img.info.get("duration", 80), 20))
                img.seek(img.tell() + 1)
        except EOFError:
            pass
        except Exception as exc:
            self.after(0, lambda: self._on_dmd_fail(str(exc), tmpdir))
            return

        self.after(0, lambda: self._on_dmd_ready(frames, delays, tmpdir, out_gif))

    def _on_dmd_ready(self, frames, delays, tmpdir, out_gif):
        self._dmd_rendering = False
        self._btn_dmd.configure(state="normal", text="🔬 DMD")
        self._stop_dmd_preview()
        self._dmd_tmpdir = tmpdir
        self._dmd_frames = frames
        self._dmd_delays = delays
        self._dmd_idx    = 0
        size_kb = os.path.getsize(out_gif) // 1024
        self._dmd_info.configure(
            text=f"✅  128×32  ·  {len(frames)} frames  ·  {size_kb} KB"
        )
        self._animate_dmd()

    def _on_dmd_fail(self, msg, tmpdir):
        self._dmd_rendering = False
        self._btn_dmd.configure(state="normal", text="🔬 DMD")
        shutil.rmtree(tmpdir, ignore_errors=True)
        self._dmd_canvas.delete("all")
        self._dmd_canvas.create_text(
            DMD_CANVAS_W // 2, DMD_CANVAS_H // 2,
            text="❌  DMD render failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._log(f"❌  DMD preview: {msg}", "error")

    def _animate_dmd(self):
        if not self._dmd_frames:
            return
        idx = self._dmd_idx % len(self._dmd_frames)
        self._dmd_canvas.delete("all")
        x_off = (DMD_CANVAS_W - DMD_DISP_W) // 2
        y_off = (DMD_CANVAS_H - DMD_DISP_H) // 2
        self._dmd_canvas.create_image(x_off, y_off, anchor="nw",
                                      image=self._dmd_frames[idx])
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
        """Enable/disable manual colorimetry controls when Smart Color Boost is toggled."""
        enabled = self.v_auto_color_enabled.get()
        # Gray out / restore mode selector and all colorimetry widgets
        col_state = "disabled" if enabled else "normal"
        self._mode_menu.configure(state=col_state)
        for w in self._colorimetry_widgets:
            try:
                w.configure(state=col_state)
            except Exception:
                pass
        # Info label
        if enabled:
            self._auto_color_info.configure(
                text="Values computed automatically at conversion · manual sliders overridden"
            )
        else:
            self._auto_color_info.configure(text="")

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
            print(
                "\n❌  Incompatible Python/Tk detected:\n"
                f"    Python: {sys.executable}\n"
                f"    Tk: {tk_ver}\n\n"
                "This macOS Python build uses Tk 8.5 and crashes with this UI.\n"
                "Use the launcher script (recommended) or Homebrew Python.\n\n"
                "  ./launch_ui.sh\n"
                "  brew install python@3.13\n"
            )
            sys.exit(1)

    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        msg = (
            "ffmpeg not found or not responding.\n\n"
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
            print(f"\n❌  {msg}\n")
        sys.exit(1)

    app = DMDConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()

