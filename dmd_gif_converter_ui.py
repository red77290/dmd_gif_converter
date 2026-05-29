#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMD GIF Converter — Graphical Interface
Cross-platform UI (macOS · Windows · Linux) to convert any video/GIF
to 128×32 LED DMD format.

Usage:
    python dmd_gif_converter_ui.py
"""

import os
import sys
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

# ── Constants ─────────────────────────────────────────────────────────────────
PREVIEW_W   = 640   # canvas width  = 128 × 5
PREVIEW_H   = 160   # canvas height =  32 × 5
BG_CANVAS   = "#0d0d1a"
APP_VERSION = "2.0"

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
#  FileRow — one row in the file list
# ─────────────────────────────────────────────────────────────────────────────
class FileRow(ctk.CTkFrame):
    """Widget representing a single source file in the list."""

    def __init__(self, master, file_path, on_select, on_remove, **kw):
        super().__init__(master, corner_radius=6, fg_color="#2a2a3e", cursor="hand2", **kw)
        self.file_path = file_path
        self.on_select = on_select
        self.on_remove = on_remove
        self.status = "idle"

        ext  = Path(file_path).suffix.lower()
        icon = "🎞️" if ext == ".gif" else "🎬"
        name = Path(file_path).name
        disp = (name[:26] + "…") if len(name) > 28 else name

        self.grid_columnconfigure(1, weight=1)

        self._icon  = ctk.CTkLabel(self, text=icon, width=22, font=ctk.CTkFont(size=13))
        self._icon.grid(row=0, column=0, padx=(6, 2), pady=5)

        self._name  = ctk.CTkLabel(self, text=disp, anchor="w", font=ctk.CTkFont(size=12))
        self._name.grid(row=0, column=1, padx=4, pady=5, sticky="ew")

        self._dot   = ctk.CTkLabel(self, text="●", text_color=_STATUS_COLOR["idle"], width=14)
        self._dot.grid(row=0, column=2, padx=2, pady=5)

        self._rm    = ctk.CTkButton(
            self, text="✕", width=22, height=22, corner_radius=4,
            fg_color="transparent", hover_color="#c0392b",
            command=lambda: self.on_remove(self)
        )
        self._rm.grid(row=0, column=3, padx=(2, 6), pady=5)

        for w in (self, self._icon, self._name, self._dot):
            w.bind("<Button-1>", lambda _e: self.on_select(self))

    def set_selected(self, selected):
        self.configure(fg_color="#1e3a5f" if selected else "#2a2a3e")

    def set_status(self, status):
        self.status = status
        self._dot.configure(text_color=_STATUS_COLOR.get(status, "#666688"))


# ─────────────────────────────────────────────────────────────────────────────
#  DMDConverterApp — main window
# ─────────────────────────────────────────────────────────────────────────────
class DMDConverterApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title(f"🎞️  DMD GIF Converter  v{APP_VERSION}")
        self.geometry("1300x840")
        self.minsize(980, 660)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── State ─────────────────────────────────────────────────────────────
        # iid (treeview row id) → file_path  — fast O(1) lookup, no widget per row
        self._file_data:    dict = {}   # iid → path
        self._file_paths:   set  = set()  # deduplicate fast
        self._selected_iid: str  = ""
        self._preview_frames: list  = []
        self._preview_delays: list  = []
        self._preview_idx           = 0
        self._preview_job           = None
        self._preview_tmpdir        = None
        self._source_duration       = 0.0
        self._busy                  = False

        # ── Tkinter vars ──────────────────────────────────────────────────────
        self.v_output_dir   = tk.StringVar(value="")
        self.v_mode         = tk.StringVar(value="pixel_art")
        self.v_workers      = tk.IntVar   (value=2)
        self.v_scroll       = tk.DoubleVar(value=24.0)
        self.v_bottom_crop  = tk.DoubleVar(value=0.15)
        self.v_scroll_cycles = tk.DoubleVar(value=1.5)
        self.v_fps_min      = tk.DoubleVar(value=10.0)
        self.v_fps_max      = tk.DoubleVar(value=25.0)
        self.v_contrast     = tk.DoubleVar(value=1.6)
        self.v_saturation   = tk.DoubleVar(value=2.2)
        self.v_brightness   = tk.DoubleVar(value=-0.03)
        self.v_gamma        = tk.DoubleVar(value=0.85)
        self.v_sharpen_lum  = tk.DoubleVar(value=1.8)
        self.v_sharpen_chr  = tk.DoubleVar(value=0.5)
        self.v_dither       = tk.StringVar(value="none")
        self.v_trim_start   = tk.DoubleVar(value=0.0)
        self.v_trim_end     = tk.DoubleVar(value=0.0)

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

        # Header row
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

        # Add buttons
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

        # ── Treeview (handles thousands of rows natively) ─────────────────────
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

        # Tag colours per status
        self._tree.tag_configure("idle",       foreground="#aaaacc")
        self._tree.tag_configure("converting", foreground="#f39c12")
        self._tree.tag_configure("done",       foreground="#2ecc71")
        self._tree.tag_configure("error",      foreground="#e74c3c")

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Delete>",           lambda _e: self._remove_selected())
        self._tree.bind("<BackSpace>",        lambda _e: self._remove_selected())

        # Selection hint
        ctk.CTkLabel(lp, text="👆 Click a row to select · Del to remove",
                     text_color="#444466", font=ctk.CTkFont(size=10)
                     ).grid(row=3, column=0, padx=8, pady=(0, 2), sticky="w")

        # Bottom controls
        bot = ctk.CTkFrame(lp, fg_color="transparent")
        bot.grid(row=3, column=0, padx=6, pady=6, sticky="ew")
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
        """Apply dark theme to the ttk.Treeview."""
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

    # ── Right panel : preview + params + actions ───────────────────────────────
    def _build_right_panel(self):
        rp = ctk.CTkFrame(self, fg_color="transparent")
        rp.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        rp.grid_rowconfigure(1, weight=1)
        rp.grid_columnconfigure(0, weight=1)

        self._build_preview_area(rp)
        self._build_bottom_area(rp)

    # ── Preview ───────────────────────────────────────────────────────────────
    def _build_preview_area(self, parent):
        pf = ctk.CTkFrame(parent)
        pf.grid(row=0, column=0, padx=4, pady=(4, 2), sticky="ew")
        pf.grid_columnconfigure(0, weight=1)

        # Title row
        tr = ctk.CTkFrame(pf, fg_color="transparent")
        tr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        tr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            tr, text="🖥️  Preview",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        pb = ctk.CTkFrame(tr, fg_color="transparent")
        pb.grid(row=0, column=1, sticky="e")
        self._btn_src = ctk.CTkButton(
            pb, text="▶  Source", width=105, height=28,
            command=self.show_source_preview
        )
        self._btn_src.pack(side="left", padx=3)
        self._btn_dmd = ctk.CTkButton(
            pb, text="🔬 DMD Preview", width=130, height=28,
            fg_color="#1e6a3c", hover_color="#155230",
            command=self.show_dmd_preview
        )
        self._btn_dmd.pack(side="left", padx=3)

        # Canvas (128×32 × 5 = 640×160)
        cf = ctk.CTkFrame(pf, fg_color=BG_CANVAS, corner_radius=6)
        cf.grid(row=1, column=0, padx=10, pady=4)
        self._canvas = tk.Canvas(
            cf, width=PREVIEW_W, height=PREVIEW_H,
            bg=BG_CANVAS, highlightthickness=0
        )
        self._canvas.pack(padx=2, pady=2)
        self._draw_canvas_idle()

        self._preview_info = ctk.CTkLabel(
            pf, text="", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._preview_info.grid(row=2, column=0, pady=(0, 2))

        # Trim controls (hidden until file selected)
        self._trim_frame = ctk.CTkFrame(pf, fg_color="#16213e")
        self._trim_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._trim_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._trim_frame, text="✂️  Trim  (single-file conversion only)",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#7ec8e3"
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(self._trim_frame, text="Start", width=44, font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, padx=(10, 4), pady=2
        )
        self._sl_start = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_start,
            command=self._on_start_drag
        )
        self._sl_start.grid(row=1, column=1, padx=4, sticky="ew")
        self._lbl_start = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54, font=ctk.CTkFont(size=11))
        self._lbl_start.grid(row=1, column=2, padx=4)

        ctk.CTkLabel(self._trim_frame, text="End", width=44, font=ctk.CTkFont(size=11)).grid(
            row=2, column=0, padx=(10, 4), pady=2
        )
        self._sl_end = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_end,
            command=self._on_end_drag
        )
        self._sl_end.grid(row=2, column=1, padx=4, sticky="ew", pady=(2, 8))
        self._lbl_end = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54, font=ctk.CTkFont(size=11))
        self._lbl_end.grid(row=2, column=2, padx=4)

        ctk.CTkButton(
            self._trim_frame, text="↺ Reset", command=self._reset_trim,
            width=70, height=24, fg_color="transparent", border_width=1
        ).grid(row=1, column=3, rowspan=2, padx=(4, 10))

        self._trim_frame.grid_remove()  # hidden by default

    # ── Bottom : params + actions/log ─────────────────────────────────────────
    def _build_bottom_area(self, parent):
        bot = ctk.CTkFrame(parent, fg_color="transparent")
        bot.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        bot.grid_columnconfigure(0, weight=1)
        bot.grid_columnconfigure(1, weight=0)
        bot.grid_rowconfigure(0, weight=1)

        # Params (left, scrollable)
        self._params_scroll = ctk.CTkScrollableFrame(bot, label_text="⚙️  Parameters")
        self._params_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._params_scroll.grid_columnconfigure(0, weight=1)
        self._build_params_panel(self._params_scroll)

        # Actions + log (right, fixed width)
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
            ctk.CTkLabel(f, text=label, width=135, anchor="w", font=ctk.CTkFont(size=12)).grid(
                row=0, column=0, padx=(4, 6)
            )
            kw = dict(from_=from_, to=to, variable=var)
            if steps is not None:
                kw["number_of_steps"] = steps
            sl = ctk.CTkSlider(f, **kw)
            sl.grid(row=0, column=1, sticky="ew", padx=4)
            lbl = ctk.CTkLabel(f, text=fmt.format(var.get()) + suffix, width=72, anchor="e",
                               font=ctk.CTkFont(size=11))
            lbl.grid(row=0, column=2, padx=(4, 4))
            var.trace_add("write", lambda *_: lbl.configure(text=fmt.format(var.get()) + suffix))
            return sl

        # ── Mode ──────────────────────────────────────────────────────────────
        section("🎨  Content mode")
        mr = ctk.CTkFrame(parent, fg_color="transparent")
        mr.pack(fill="x", padx=8, pady=2)
        mr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mr, text="Mode", width=135, anchor="w", font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, padx=(4, 6)
        )
        ctk.CTkOptionMenu(
            mr, variable=self.v_mode,
            values=["pixel_art", "anime", "cinema", "custom"],
            command=self._on_mode_change, width=180
        ).grid(row=0, column=1, padx=4, sticky="w")

        self._mode_desc_lbl = ctk.CTkLabel(
            parent, text=_MODE_DESC["pixel_art"],
            text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._mode_desc_lbl.pack(padx=12, pady=(0, 4), anchor="w")

        # ── Parallélisme ──────────────────────────────────────────────────────
        section("⚡  Parallelism")
        slider_row("Workers (CPU)", self.v_workers, 1, 16, "{:.0f}", " workers", steps=15)

        # ── Scroll ────────────────────────────────────────────────────────────
        section("📜  Scroll")
        slider_row("Scroll speed",    self.v_scroll,        4.0, 80.0, "{:.0f}", " px/s")
        slider_row("Bottom crop (%)", self.v_bottom_crop,   0.0,  0.5, "{:.0%}")
        slider_row("Scroll cycles",   self.v_scroll_cycles, 0.0,  5.0, "{:.2f}", " cyc")

        # ── FPS ───────────────────────────────────────────────────────────────
        section("🎬  Render FPS")
        slider_row("FPS minimum", self.v_fps_min, 5.0,  30.0, "{:.1f}", " fps")
        slider_row("FPS maximum", self.v_fps_max, 10.0, 60.0, "{:.1f}", " fps")

        # ── Colorimétrie custom ───────────────────────────────────────────────
        self._custom_header = ctk.CTkLabel(
            parent, text="🎛️  Colorimetry  (custom mode only)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        )
        self._custom_header.pack(fill="x", padx=8, pady=(12, 2), anchor="w")

        self._custom_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._custom_frame.pack(fill="x")
        self._custom_frame.grid_columnconfigure(0, weight=1)

        def cslider(label, var, from_, to, fmt="{:.2f}", suffix=""):
            f = ctk.CTkFrame(self._custom_frame, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=label, width=135, anchor="w", font=ctk.CTkFont(size=12)).grid(
                row=0, column=0, padx=(4, 6)
            )
            sl = ctk.CTkSlider(f, from_=from_, to=to, variable=var)
            sl.grid(row=0, column=1, sticky="ew", padx=4)
            lbl = ctk.CTkLabel(f, text=fmt.format(var.get()) + suffix, width=72, anchor="e",
                               font=ctk.CTkFont(size=11))
            lbl.grid(row=0, column=2, padx=(4, 4))
            var.trace_add("write", lambda *_: lbl.configure(text=fmt.format(var.get()) + suffix))

        cslider("Contrast",     self.v_contrast,    0.5,  2.5)
        cslider("Saturation",   self.v_saturation,  0.0,  4.0)
        cslider("Brightness",   self.v_brightness, -0.5,  0.5, "{:.3f}")
        cslider("Gamma",        self.v_gamma,       0.1,  2.5)
        cslider("Sharpen Lum",  self.v_sharpen_lum, 0.0,  3.0)
        cslider("Sharpen Chr",  self.v_sharpen_chr, 0.0,  2.0)

        dr = ctk.CTkFrame(self._custom_frame, fg_color="transparent")
        dr.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(dr, text="Dithering", width=135, anchor="w", font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(4, 6)
        )
        ctk.CTkOptionMenu(
            dr, variable=self.v_dither,
            values=["none", "bayer:bayer_scale=1", "bayer:bayer_scale=2", "sierra2_4a"],
            width=200
        ).pack(side="left")

        # Initially sync visibility
        self._update_custom_visibility()

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
            font=ctk.CTkFont(size=13),
            state="disabled"   # enabled when a file is selected
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

        # Progress
        self._progress = ctk.CTkProgressBar(af, height=8)
        self._progress.set(0)
        self._progress.grid(row=3, column=0, padx=4, pady=(10, 2), sticky="ew")

        self._status_lbl = ctk.CTkLabel(
            af, text="Ready", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._status_lbl.grid(row=4, column=0, padx=4, pady=2)

        # Log
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
        # Scan in a background thread so the dialog closes immediately
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
        """Insert files into the treeview in batches — keeps the UI responsive."""
        batch = paths[start:start + batch_size]
        for p in batch:
            self._add_file_raw(p)
        self._update_count()
        remaining = start + batch_size
        if remaining < len(paths):
            # Yield to the event loop, then continue
            self.after(0, lambda: self._batch_insert(paths, remaining, source_folder, batch_size))
        else:
            folder_name = Path(source_folder).name if source_folder else ""
            added = sum(1 for p in paths if p in self._file_paths)
            if folder_name:
                self._log(f"📂  {len(paths)} file(s) added from '{folder_name}'")

    def _add_file_raw(self, path):
        """Insert one file into the treeview (no UI refresh — call _update_count after batch)."""
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
        # Enable single-file convert button now that something is selected
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
            self._stop_preview()
            self._selected_iid = ""
            self._trim_frame.grid_remove()
            self._draw_canvas_idle()
        path = self._file_data.pop(iid, None)
        if path:
            self._file_paths.discard(path)
        self._tree.delete(iid)
        self._update_count()

    def clear_files(self):
        self._stop_preview()
        self._tree.delete(*self._tree.get_children())
        self._file_data.clear()
        self._file_paths.clear()
        self._selected_iid = ""
        self._trim_frame.grid_remove()
        self._draw_canvas_idle()
        self._update_count()

    def _set_file_status(self, iid, status):
        try:
            self._tree.item(iid, tags=(status,))
        except tk.TclError:
            pass  # row may have been deleted

    def browse_output(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.v_output_dir.set(folder)

    # ══════════════════════════════════════════════════════════════════════════
    #  PREVIEW
    # ══════════════════════════════════════════════════════════════════════════

    def _draw_canvas_idle(self):
        self._canvas.delete("all")
        self._canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2,
            text="← Click a file in the list to preview it",
            fill="#445566", font=("Helvetica", 13)
        )
        if hasattr(self, "_preview_info"):
            self._preview_info.configure(text="")
        # Disable convert button when nothing selected
        if hasattr(self, "_btn_convert"):
            self._btn_convert.configure(state="disabled")

    def _stop_preview(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_frames.clear()
        self._preview_delays.clear()
        self._preview_idx = 0
        if self._preview_tmpdir and os.path.isdir(self._preview_tmpdir):
            shutil.rmtree(self._preview_tmpdir, ignore_errors=True)
            self._preview_tmpdir = None

    def _load_preview(self, file_path):
        self._stop_preview()
        self._canvas.delete("all")
        self._canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2,
            text="⏳  Loading preview…",
            fill="#7ec8e3", font=("Helvetica", 13)
        )
        # Get metadata to update trim sliders
        w, h, fps, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self._update_trim_sliders()
        self._trim_frame.grid()

        threading.Thread(
            target=self._extract_source_frames,
            args=(file_path,), daemon=True
        ).start()

    def _extract_source_frames(self, file_path):
        """Background: extract source frames via ffmpeg for preview."""
        tmpdir = tempfile.mkdtemp(prefix="dmd_src_")
        fps_prev = 12.5
        dur = min(self._source_duration, 10.0)

        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-t", str(dur),
            "-vf", (
                f"fps={fps_prev},"
                f"scale={PREVIEW_W}:{PREVIEW_H}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={PREVIEW_W}:{PREVIEW_H}:(ow-iw)/2:(oh-ih)/2:color={BG_CANVAS[1:]}"
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

        self.after(0, lambda: self._on_source_frames_ready(
            frames, delays, tmpdir, file_path
        ))

    def _on_source_frames_ready(self, frames, delays, tmpdir, file_path):
        if not frames:
            self._canvas.delete("all")
            self._canvas.create_text(
                PREVIEW_W // 2, PREVIEW_H // 2,
                text="⚠️  Preview unavailable  (ffmpeg missing?)",
                fill="#e74c3c", font=("Helvetica", 12)
            )
            shutil.rmtree(tmpdir, ignore_errors=True)
            return

        self._preview_tmpdir = tmpdir
        self._preview_frames = frames
        self._preview_delays = delays
        self._preview_idx    = 0

        name = Path(file_path).name
        self._preview_info.configure(
            text=f"{name}   ·   {len(frames)} frames   ·   {self._source_duration:.1f} s"
        )
        self._animate_preview()

    def _animate_preview(self):
        if not self._preview_frames:
            return
        idx = self._preview_idx % len(self._preview_frames)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._preview_frames[idx])
        self._preview_idx = idx + 1
        delay = self._preview_delays[idx] if self._preview_delays else 80
        self._preview_job = self.after(delay, self._animate_preview)

    def show_source_preview(self):
        if self._selected_iid:
            path = self._file_data.get(self._selected_iid)
            if path:
                self._load_preview(path)
        else:
            messagebox.showinfo("Info", "Select a file first.")

    def show_dmd_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._stop_preview()
        self._canvas.delete("all")
        self._canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2,
            text="⏳  Generating DMD render…\n    (a few seconds)",
            fill="#f39c12", font=("Helvetica", 12)
        )
        self._btn_dmd.configure(state="disabled", text="⏳  Rendering…")
        self._btn_src.configure(state="disabled")

        params = self._collect_params()
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

        # Load and scale up the 128×32 output GIF
        frames, delays = [], []
        try:
            img = Image.open(out_gif)
            while True:
                frame = img.copy().convert("RGB").resize(
                    (PREVIEW_W, PREVIEW_H), Image.NEAREST
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
        self._btn_dmd.configure(state="normal", text="🔬 DMD Preview")
        self._btn_src.configure(state="normal")
        if self._preview_tmpdir:
            shutil.rmtree(self._preview_tmpdir, ignore_errors=True)
        self._preview_tmpdir = tmpdir
        self._preview_frames = frames
        self._preview_delays = delays
        self._preview_idx    = 0
        self._preview_info.configure(
            text=f"✅  DMD render  ·  128 × 32  ·  {len(frames)} frames  "
                 f"·  {os.path.getsize(out_gif) // 1024} KB"
        )
        self._animate_preview()

    def _on_dmd_fail(self, msg, tmpdir):
        self._btn_dmd.configure(state="normal", text="🔬 DMD Preview")
        self._btn_src.configure(state="normal")
        shutil.rmtree(tmpdir, ignore_errors=True)
        self._canvas.delete("all")
        self._canvas.create_text(
            PREVIEW_W // 2, PREVIEW_H // 2,
            text="❌  DMD render failed", fill="#e74c3c", font=("Helvetica", 13)
        )
        self._log(f"❌  DMD preview: {msg}", "error")

    # ══════════════════════════════════════════════════════════════════════════
    #  TRIM
    # ══════════════════════════════════════════════════════════════════════════

    def _update_trim_sliders(self):
        dur = max(self._source_duration, 0.1)
        self._sl_start.configure(to=dur)
        self._sl_end.configure(to=dur)
        self.v_trim_start.set(0.0)
        self.v_trim_end.set(dur)
        self._lbl_start.configure(text="0.0 s")
        self._lbl_end.configure(text=f"{dur:.1f} s")

    def _on_start_drag(self, val):
        v = float(val)
        end = self.v_trim_end.get()
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
        """Return (start_s, end_s) or (None, None) if full file."""
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
            "mode":           self.v_mode.get(),
            "max_workers":    self.v_workers.get(),
            "scroll_speed":   self.v_scroll.get(),
            "bottom_crop_pct": self.v_bottom_crop.get(),
            "scroll_cycles":  self.v_scroll_cycles.get(),
            "fps_min":        self.v_fps_min.get(),
            "fps_max":        self.v_fps_max.get(),
            "contrast":       self.v_contrast.get(),
            "saturation":     self.v_saturation.get(),
            "brightness":     self.v_brightness.get(),
            "gamma":          self.v_gamma.get(),
            "sharpen_lum":    self.v_sharpen_lum.get(),
            "sharpen_chr":    self.v_sharpen_chr.get(),
            "dither":         self.v_dither.get(),
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
        self._stop_preview()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # Verify ffmpeg is available
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
        # Show as tk messagebox if possible
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

