import os
import re
import sys
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

from src.converter.core import (
    get_metadata, process_file, process_folder,
    DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
)
from src.auto_action.main import AutoActionConfig, preprocess_video_for_dmd
from src.converter.colorimetry import analyze_and_compensate as _ui_analyze_color
from src.ui.widgets import _InfoBadge
from src.ui.constants import *
import os
import glob
import logging
import shutil
import tempfile
import threading
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk
from src.ui.dmd_led_sim import LED_SIM_SCALE, LED_SIM_GAP, LED_SIM_MAX_W, apply_led_grid as _apply_led_grid

class SettingsPanelMixin:
    def _build_right_panel(self):
        rp = ctk.CTkFrame(self, fg_color="transparent")
        rp.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        rp.grid_rowconfigure(1, weight=1)
        rp.grid_columnconfigure(0, weight=1)
        self._build_preview_area(rp)
        self._build_bottom_area(rp)

    # ── Dual Preview ──────────────────────────────────────────────────────────
    def _build_params_panel(self, parent):
        # Reset LMH widget list each time this panel is built
        self._lmh_widgets = []

        def section(text):
            ctk.CTkLabel(
                parent, text=text, font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#7ec8e3"
            ).pack(fill="x", padx=8, pady=(12, 2), anchor="w")

        def slider_row(label, var, from_, to, fmt="{:.1f}", suffix="", steps=None, lmh=True):
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

            def _lbl_txt():
                return fmt.format(var.get()) + suffix

            entry_sv = tk.StringVar(value=_lbl_txt())
            entry = ctk.CTkEntry(f, textvariable=entry_sv, width=72, justify="right",
                                 font=ctk.CTkFont(size=11))
            entry.grid(row=0, column=2, padx=(4, 4))

            _editing = [False]

            def _on_focus_in(_e):
                _editing[0] = True

            def _commit(*_):
                _editing[0] = False
                raw = entry_sv.get().strip()
                try:
                    m = re.match(r'^([+-]?\d*\.?\d+)', raw)
                    val = float(m.group(1)) if m else float(raw)
                    val = max(from_, min(to, val))
                    if is_int:
                        var.set(int(val))
                    else:
                        var.set(val)
                except (ValueError, AttributeError):
                    pass
                entry_sv.set(_lbl_txt())

            def _var_changed(*_):
                if not _editing[0]:
                    entry_sv.set(_lbl_txt())

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            if lmh:
                self._lmh_widgets.extend([sl, entry])
            return sl

        # ── Per-GIF config toggle ─────────────────────────────────────────────
        pg_frame = ctk.CTkFrame(parent, fg_color="#0f1a10", corner_radius=6)
        pg_frame.pack(fill="x", padx=8, pady=(8, 4))
        pg_frame.grid_columnconfigure(1, weight=1)
        self._per_gif_cb = ctk.CTkCheckBox(
            pg_frame,
            text="🎞️  Per-GIF Config  —  each file has its own settings",
            variable=self.v_per_gif_config,
            command=self._on_per_gif_toggle,
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#88ddaa",
        )
        self._per_gif_cb.pack(side="left", padx=12, pady=8)
        self._per_gif_status_lbl = ctk.CTkLabel(
            pg_frame, text="",
            text_color="#557755", font=ctk.CTkFont(size=10)
        )
        self._per_gif_status_lbl.pack(side="left", padx=(0, 8))

        # ── 🤖 Let me handle it ───────────────────────────────────────────────
        lmh_frame = ctk.CTkFrame(parent, fg_color="#1a1200", corner_radius=8,
                                 border_width=2, border_color="#ffaa22")
        lmh_frame.pack(fill="x", padx=8, pady=(6, 4))
        lmh_frame.grid_columnconfigure(1, weight=1)
        self._lmh_cb = ctk.CTkCheckBox(
            lmh_frame,
            text="🤖  Let me handle it  —  full auto, zero config",
            variable=self.v_let_me_handle_it,
            command=self._on_let_me_handle_toggle,
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#ffaa22",
            fg_color="#cc7700", hover_color="#ff9900",
            checkmark_color="#ffffff",
        )
        self._lmh_cb.pack(side="left", padx=12, pady=8)
        ctk.CTkLabel(
            lmh_frame,
            text="Activates: Smart Color Boost · Auto-framing · Smart Auto-Crop · BG Subtraction\n"
                 "Locks all other settings (overlay, per-GIF config & dimension preset remain free)",
            text_color="#886622", font=ctk.CTkFont(size=10), justify="left",
        ).pack(side="left", padx=(0, 12), pady=6)

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
        self._lmh_widgets.append(self._mode_menu)

        self._mode_desc_lbl = ctk.CTkLabel(
            parent, text=MODE_DESC["pixel_art"],
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
        self._lmh_widgets.append(self._auto_color_cb)
        self._auto_color_info = ctk.CTkLabel(
            ac_row, text="",
            text_color="#557755", font=ctk.CTkFont(size=10)
        )
        self._auto_color_info.pack(side="left", padx=(0, 8))

        # Parallelism
        section("⚡  Parallelism")
        slider_row("Workers (CPU)", self.v_workers, 1, 16, "{:.0f}", " workers", steps=15, lmh=False)

        # Scroll
        section("📜  Scroll")
        slider_row("Scroll speed",    self.v_scroll,        4.0, 80.0, "{:.0f}", " px/s")
        slider_row("Top crop (%)",    self.v_top_crop,      0.0,  0.5, "{:.0%}")
        slider_row("Bottom crop (%)", self.v_bottom_crop,   0.0,  0.5, "{:.0%}")
        slider_row("Scroll cycles",   self.v_scroll_cycles, 0.0,  5.0, "{:.2f}", " cyc")

        # FPS
        section("🎬  Render FPS")
        slider_row("FPS minimum", self.v_fps_min, 5.0,  30.0, "{:.1f}", " fps")
        slider_row("FPS maximum", self.v_fps_max, 10.0, 60.0, "{:.1f}", " fps") # FIX: Passed self.v_fps_max as var

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
        self._lmh_widgets.append(self._max_dur_cb)

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
        self._lmh_widgets.append(self._max_dur_slider)
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

            def _lbl_txt():
                return fmt.format(var.get()) + suffix

            entry_sv = tk.StringVar(value=_lbl_txt())
            entry = ctk.CTkEntry(f, textvariable=entry_sv, width=72, justify="right",
                                 font=ctk.CTkFont(size=11))
            entry.grid(row=0, column=2, padx=(4, 4))

            _editing = [False]

            def _on_focus_in(_e):
                _editing[0] = True

            def _commit(*_):
                _editing[0] = False
                raw = entry_sv.get().strip()
                try:
                    m = re.match(r'^([+-]?\d*\.?\d+)', raw)
                    val = float(m.group(1)) if m else float(raw)
                    val = max(from_, min(to, val))
                    if is_int:
                        var.set(int(val))
                    else:
                        var.set(val)
                except (ValueError, AttributeError):
                    pass
                entry_sv.set(_lbl_txt())

            def _var_changed(*_):
                if not _editing[0]:
                    entry_sv.set(_lbl_txt())

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            self._colorimetry_widgets.append(sl)
            self._colorimetry_widgets.append(entry)

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
        self._lmh_widgets.append(self._dither_menu)

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
                       steps=None, is_int=False, lmh=True):
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

            def _lbl_txt():
                return (fmt.format(int(var.get())) if is_int else fmt.format(var.get())) + suffix

            entry_sv = tk.StringVar(value=_lbl_txt())
            entry = ctk.CTkEntry(f, textvariable=entry_sv, width=80, justify="right",
                                 font=ctk.CTkFont(size=11))
            entry.grid(row=0, column=2, padx=(4, 4))

            _editing = [False]

            def _on_focus_in(_e):
                _editing[0] = True

            def _commit(*_):
                _editing[0] = False
                raw = entry_sv.get().strip()
                try:
                    m = re.match(r'^([+-]?\d*\.?\d+)', raw)
                    val = float(m.group(1)) if m else float(raw)
                    val = max(from_, min(to, val))
                    if is_int:
                        var.set(int(val))
                    else:
                        var.set(val)
                except (ValueError, AttributeError):
                    pass
                entry_sv.set(_lbl_txt())

            def _var_changed(*_):
                if not _editing[0]:
                    entry_sv.set(_lbl_txt())

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            if lmh:
                self._lmh_widgets.extend([sl, entry])
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
        self._cb_auto_action_enabled = ctk.CTkCheckBox(
            auto_row,
            text="Enable cinematic auto-framing before ffmpeg (default OFF)",
            variable=self.v_auto_action_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_auto_action_enabled.pack(side="left")
        self._lmh_widgets.append(self._cb_auto_action_enabled)

        mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=2)
        mode_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mode_row, text="Detection mode", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._action_detector_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self.v_action_detector,
            values=["person", "motion", "hybrid", "center"],
            width=200,
        )
        self._action_detector_menu.grid(row=0, column=1, sticky="w", padx=4)
        self._lmh_widgets.append(self._action_detector_menu)

        ctk.CTkLabel(
            parent,
            text="Default mode is person. Change detection mode here if you prefer.\n"
                 "Processed output keeps 4:1 ratio before standard DMD conversion.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_dmd_visibility_score_enabled = ctk.CTkCheckBox(
            row_frame,
            text="DMD Visibilité",
            variable=self.v_dmd_visibility_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_dmd_visibility_score_enabled.pack(side="left")
        self._lmh_widgets.append(self._cb_dmd_visibility_score_enabled)

        self._cb_dmd_readability_score_enabled = ctk.CTkCheckBox(
            row_frame,
            text="DMD Lisibilité",
            variable=self.v_dmd_readability_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_dmd_readability_score_enabled.pack(side="left", padx=(10, 0))
        self._lmh_widgets.append(self._cb_dmd_readability_score_enabled)

        ctk.CTkLabel(
            parent,
            text="    Active un ou deux scores pour limiter les zooms automatiques :\n"
                 "    - Visibilité seule : empêche les zooms qui rendent le sujet moins visible.\n"
                 "    - Lisibilité seule : empêche les zooms qui dégradent le contraste des formes.\n"
                 "    - Les deux : calcule une moyenne des deux métriques.",
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

        # ════════════════════════════════════════════════════════════════════
        # SECTION: Crop & Vertical Bias
        # ════════════════════════════════════════════════════════════════════
        ctk.CTkLabel(
            parent, text="━━  📐  Crop & Vertical Bias",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 2), anchor="w")

        # ── 🧠 Smart Auto Crop — single toggle that replaces the 3 checkboxes ──
        smart_row = ctk.CTkFrame(parent, fg_color="transparent")
        smart_row.pack(fill="x", padx=14, pady=(2, 0))
        self._cb_smart_auto_crop = ctk.CTkCheckBox(
            smart_row,
            text="🧠 Smart Auto Crop  —  engine analyses context & activates the optimal combination",
            variable=self.v_action_smart_auto_crop,
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#88ddff",
        )
        self._cb_smart_auto_crop.pack(side="left")
        self._lmh_widgets.append(self._cb_smart_auto_crop)

        ctk.CTkLabel(
            parent,
            text="    When ON: engine scans 60 frames, detects floor / blank space / character height\n"
                 "    and enables auto-bottom-crop, auto-top-crop and/or auto-floor-tracking\n"
                 "    automatically.  Handles the face-priority contradiction (tall character =\n"
                 "    no floor-tracking; normal character = floor-tracking enabled).\n"
                 "    When OFF: activate each option individually below — or use the sliders.",
            text_color="#557799", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # ── Bottom crop row (slider + Auto toggle) ────────────────────────────
        self._slider_bottom_crop = adv_slider(parent, "Bottom crop (%)", self.v_action_bottom_crop, 0.0, 0.5,
                   "{:.0%}", "", steps=50)
        bottom_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        bottom_auto_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_bottom_crop = ctk.CTkCheckBox(
            bottom_auto_row,
            text="Auto bottom crop  (overrides slider · detects floor / feet / face priority)",
            variable=self.v_action_auto_bottom_crop,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_bottom_crop.pack(side="left")
        self._lmh_widgets.append(self._cb_auto_bottom_crop)

        def _toggle_auto_bottom_crop(*_):
            if self.v_action_smart_auto_crop.get():
                return  # smart auto manages this — ignore individual toggle
            state = "disabled" if self.v_action_auto_bottom_crop.get() else "normal"
            self._slider_bottom_crop.configure(state=state)

        self.v_action_auto_bottom_crop.trace_add("write", _toggle_auto_bottom_crop)

        # ── Top crop row (slider + Auto toggle) ──────────────────────────────
        self._slider_top_crop = adv_slider(parent, "Top crop (%)", self.v_action_top_crop, 0.0, 0.5,
                   "{:.0%}", "", steps=50)
        top_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        top_auto_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_top_crop = ctk.CTkCheckBox(
            top_auto_row,
            text="Auto top crop  (overrides slider · detects head / sky / ceiling)",
            variable=self.v_action_auto_top_crop,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_top_crop.pack(side="left")
        self._lmh_widgets.append(self._cb_auto_top_crop)

        def _toggle_auto_top_crop(*_):
            if self.v_action_smart_auto_crop.get():
                return
            state = "disabled" if self.v_action_auto_top_crop.get() else "normal"
            self._slider_top_crop.configure(state=state)

        self.v_action_auto_top_crop.trace_add("write", _toggle_auto_top_crop)

        self._slider_vertical_bias = adv_slider(parent, "Vertical bias", self.v_action_vertical_bias, -1.0, 1.0,
                   "{:.2f}", "", steps=100)

        # ── Auto floor detect checkbox ──────────────────────────────────────
        auto_floor_row = ctk.CTkFrame(parent, fg_color="transparent")
        auto_floor_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_floor = ctk.CTkCheckBox(
            auto_floor_row,
            text="Auto floor detect (asymmetric EMA · overrides Vertical bias · ⚠ contradicts face priority)",
            variable=self.v_action_auto_vertical_bias,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_floor.pack(side="left")
        self._lmh_widgets.append(self._cb_auto_floor)

        def _toggle_auto_floor(*_):
            if self.v_action_smart_auto_crop.get():
                return
            state = "disabled" if self.v_action_auto_vertical_bias.get() else "normal"
            self._slider_vertical_bias.configure(state=state)

        self.v_action_auto_vertical_bias.trace_add("write", _toggle_auto_floor)

        # ── Smart Auto Crop toggle logic ──────────────────────────────────────
        # When Smart Auto is ON: disable the 3 individual auto checkboxes
        # (the engine decides at render time — the sliders remain active as
        # manual fallback values if the engine decides NOT to enable a mode).
        def _toggle_smart_auto(*_):
            smart_on  = self.v_action_smart_auto_crop.get()
            cb_state  = "disabled" if smart_on else "normal"
            self._cb_auto_bottom_crop.configure(state=cb_state)
            self._cb_auto_top_crop.configure(state=cb_state)
            self._cb_auto_floor.configure(state=cb_state)
            if not smart_on:
                # Restore slider states based on each individual checkbox
                _toggle_auto_bottom_crop()
                _toggle_auto_top_crop()
                _toggle_auto_floor()
            else:
                # Smart auto ON: sliders remain editable (manual fallback values)
                self._slider_bottom_crop.configure(state="normal")
                self._slider_top_crop.configure(state="normal")
                self._slider_vertical_bias.configure(state="normal")

        self.v_action_smart_auto_crop.trace_add("write", _toggle_smart_auto)

        ctk.CTkLabel(
            parent,
            text="    Intro: full-frame overview shown before zooming in on action.\n"
                 "    Set to 0 to disable (start immediately on action).\n"
                 "    Bottom crop: exclude bottom % of frame (feet / floor / HUD).\n"
                 "    Auto bottom crop: analyse ROI bounds to find feet automatically.\n"
                 "    Top crop: exclude top % of frame (sky / HUD / subtitles).\n"
                 "    Auto top crop: analyse ROI bounds to find head/top automatically.\n"
                 "      → Both auto modes detect face vs full-body content and adapt\n"
                 "        the crop margin accordingly (face = larger padding).\n"
                 "    Vertical bias: +1.0 = camera down (floor) · -1.0 = camera up.\n"
                 "    Auto floor detect: places ROI bottom at ~93 % of crop height.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # New: Background Subtraction Checkbox
        bg_sub_row = ctk.CTkFrame(parent, fg_color="transparent")
        bg_sub_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_bg_sub = ctk.CTkCheckBox(
            bg_sub_row,
            text="Enable Background Subtraction (replaces background with black)",
            variable=self.v_bg_sub_enable,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_bg_sub.pack(side="left")
        self._lmh_widgets.append(self._cb_bg_sub)
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

        self._tiling_preset_row = ctk.CTkFrame(parent, fg_color="transparent")
        tiling_preset_row = self._tiling_preset_row
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
        # Not packed initially — shown only when preset == "Custom"
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
                   "{:.0f}", " px", steps=28, is_int=True, lmh=False)

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
        self._cb_scroll_enabled = ctk.CTkCheckBox(
            scroll_row,
            text="Auto vertical scroll  (default — matches standard behaviour)",
            variable=self.v_scroll_enabled,
            command=self._on_scroll_enabled_change,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_scroll_enabled.pack(side="left")
        self._lmh_widgets.append(self._cb_scroll_enabled)

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
        self._cb_vignette = ctk.CTkCheckBox(
            vig_row,
            text="Vignette  (darkens edges — default OFF)",
            variable=self.v_vignette, font=ctk.CTkFont(size=12),
        )
        self._cb_vignette.pack(side="left")
        self._lmh_widgets.append(self._cb_vignette)

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
            # Insert right after the preset dropdown row, not at the end
            self._custom_tiling_frame.pack(
                fill="x", padx=10, pady=2, after=self._tiling_preset_row
            )
        else:
            width, height = map(int, preset.split(" ")[0].split("x"))
            self.v_target_width.set(width)
            self.v_target_height.set(height)
            self._custom_tiling_frame.pack_forget()
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

    # ── "Let Me Handle It" master toggle ─────────────────────────────────────
    def _on_let_me_handle_toggle(self):
        enabled = self.v_let_me_handle_it.get()
        if enabled:
            # Save current state of the 5 managed flags
            self._lmh_saved_state = {
                "auto_color_enabled":    self.v_auto_color_enabled.get(),
                "auto_action_enabled":   self.v_auto_action_enabled.get(),
                "action_smart_auto_crop": self.v_action_smart_auto_crop.get(),
                "bg_sub_enable":         self.v_bg_sub_enable.get(),
                "dmd_visibility_score_enabled": self.v_dmd_visibility_score_enabled.get(),
                "dmd_readability_score_enabled": self.v_dmd_readability_score_enabled.get(),
            }
            # Force all 5 flags ON (visual feedback)
            self.v_auto_color_enabled.set(True)
            self.v_auto_action_enabled.set(True)
            self.v_action_smart_auto_crop.set(True)
            self.v_dmd_visibility_score_enabled.set(True)
            self.v_dmd_readability_score_enabled.set(True)
            # Grey out every registered widget
            for w in self._lmh_widgets:
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass
        else:
            # Restore saved state
            saved = self._lmh_saved_state
            self.v_auto_color_enabled.set(saved.get("auto_color_enabled", False))
            self.v_auto_action_enabled.set(saved.get("auto_action_enabled", False))
            self.v_action_smart_auto_crop.set(saved.get("action_smart_auto_crop", False))
            self.v_bg_sub_enable.set(saved.get("bg_sub_enable", False))
            self.v_dmd_visibility_score_enabled.set(saved.get("dmd_visibility_score_enabled", False))
            self.v_dmd_readability_score_enabled.set(saved.get("dmd_readability_score_enabled", True))
            # Re-enable all registered widgets
            for w in self._lmh_widgets:
                try:
                    w.configure(state="normal")
                except Exception:
                    pass

    def _reset_advanced(self):
        self.v_auto_action_enabled.set(False)
        self.v_action_detector.set("person")
        self.v_action_strength.set(0.65)
        self.v_action_smoothness.set(0.65)
        self.v_action_zoom_max.set(2.0)
        self.v_action_padding.set(0.20)
        self.v_action_intro.set(1.5)
        self.v_action_bottom_crop.set(0.0)
        self.v_action_auto_bottom_crop.set(False)
        self.v_action_top_crop.set(0.0)
        self.v_action_auto_top_crop.set(False)
        self.v_action_vertical_bias.set(0.0)
        self.v_action_auto_vertical_bias.set(False)
        self.v_action_smart_auto_crop.set(False)
        self.v_bg_sub_enable.set(False) # Reset background subtraction
        self.v_dmd_visibility_score_enabled.set(False) # NEW: Reset DMD Visibility Score
        self.v_dmd_readability_score_enabled.set(True) # NEW: Reset DMD Readability Score
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
    def _on_per_gif_toggle(self):
        """Called when the Per-GIF config toggle changes."""
        is_on = self.v_per_gif_config.get()
        if is_on:
            # Capture current params as the "global default" baseline
            self._per_gif_global_snapshot = self._snapshot_params()
            if hasattr(self, "_per_gif_status_lbl"):
                self._per_gif_status_lbl.configure(text="ON — select a file to load/save its config")
        else:
            # Restore global snapshot so params go back to what they were before
            if self._per_gif_global_snapshot:
                self._restore_params(self._per_gif_global_snapshot)
            if hasattr(self, "_per_gif_status_lbl"):
                self._per_gif_status_lbl.configure(text="")

    def _update_per_gif_status(self, path: str, saved: bool):
        """Update the status label to reflect whether the current gif has a saved config."""
        if not hasattr(self, "_per_gif_status_lbl"):
            return
        name = Path(path).name
        if saved:
            self._per_gif_status_lbl.configure(
                text=f"✅ Config loaded for {name[:30]}", text_color="#88ddaa"
            )
        else:
            self._per_gif_status_lbl.configure(
                text=f"🆕 No saved config for {name[:30]} — using current defaults",
                text_color="#aaa855"
            )

    def _snapshot_params(self) -> dict:
        """Capture all current UI var values into a plain dict for per-gif storage."""
        return {
            "mode":                       self.v_mode.get(),
            "workers":                    self.v_workers.get(),
            "scroll":                     self.v_scroll.get(),
            "bottom_crop":                self.v_bottom_crop.get(),
            "top_crop":                   self.v_top_crop.get(),
            "scroll_cycles":              self.v_scroll_cycles.get(),
            "fps_min":                    self.v_fps_min.get(),
            "fps_max":                    self.v_fps_max.get(),
            "contrast":                   self.v_contrast.get(),
            "saturation":                 self.v_saturation.get(),
            "brightness":                 self.v_brightness.get(),
            "gamma":                      self.v_gamma.get(),
            "sharpen_lum":                self.v_sharpen_lum.get(),
            "sharpen_chr":                self.v_sharpen_chr.get(),
            "dither":                     self.v_dither.get(),
            "scroll_enabled":             self.v_scroll_enabled.get(),
            "zoom":                       self.v_zoom.get(),
            "manual_x":                   self.v_manual_x.get(),
            "manual_y":                   self.v_manual_y.get(),
            "hue_shift":                  self.v_hue_shift.get(),
            "noise_reduction":            self.v_noise_reduction.get(),
            "film_grain":                 self.v_film_grain.get(),
            "vignette":                   self.v_vignette.get(),
            "auto_action_enabled":        self.v_auto_action_enabled.get(),
            "action_detector":            self.v_action_detector.get(),
            "action_strength":            self.v_action_strength.get(),
            "action_smoothness":          self.v_action_smoothness.get(),
            "action_zoom_max":            self.v_action_zoom_max.get(),
            "action_padding":             self.v_action_padding.get(),
            "action_intro":               self.v_action_intro.get(),
            "action_bottom_crop":         self.v_action_bottom_crop.get(),
            "action_auto_bottom_crop":    self.v_action_auto_bottom_crop.get(),
            "action_top_crop":            self.v_action_top_crop.get(),
            "action_auto_top_crop":       self.v_action_auto_top_crop.get(),
            "action_vertical_bias":       self.v_action_vertical_bias.get(),
            "action_auto_vertical_bias":  self.v_action_auto_vertical_bias.get(),
            "action_smart_auto_crop":     self.v_action_smart_auto_crop.get(),
            "bg_sub_enable":              self.v_bg_sub_enable.get(),
            "dmd_visibility_score_enabled": self.v_dmd_visibility_score_enabled.get(), # NEW
            "dmd_readability_score_enabled": self.v_dmd_readability_score_enabled.get(), # NEW
            "target_width":               self.v_target_width.get(),
            "target_height":              self.v_target_height.get(),
            "target_preset":              self.v_target_preset.get(),
            "text_overlay_enabled":       self.v_text_overlay_enabled.get(),
            "text_content":               self.v_text_content.get(),
            "text_font_size":             self.v_text_font_size.get(),
            "text_color":                 self.v_text_color.get(),
            "text_position":              self.v_text_position.get(),
            "text_font_file":             self.v_text_font_file.get(),
            "text_style":                 self.v_text_style.get(),
            "text_bg":                    self.v_text_bg.get(),
            "text_bg_opacity":            self.v_text_bg_opacity.get(),
            "max_dur_enabled":            self.v_max_dur_enabled.get(),
            "max_duration":               self.v_max_duration.get(),
            "auto_color_enabled":         self.v_auto_color_enabled.get(),
        }

    def _restore_params(self, s: dict):
        """Restore all UI vars from a snapshot dict (per-gif or global)."""
        self.v_mode.set(s.get("mode", "pixel_art"))
        self.v_workers.set(s.get("workers", 2))
        self.v_scroll.set(s.get("scroll", 24.0))
        self.v_bottom_crop.set(s.get("bottom_crop", 0.15))
        self.v_top_crop.set(s.get("top_crop", 0.0))
        self.v_scroll_cycles.set(s.get("scroll_cycles", 1.5))
        self.v_fps_min.set(s.get("fps_min", 10.0))
        self.v_fps_max.set(s.get("fps_max", 25.0))
        self.v_contrast.set(s.get("contrast", 1.6))
        self.v_saturation.set(s.get("saturation", 2.2))
        self.v_brightness.set(s.get("brightness", -0.03))
        self.v_gamma.set(s.get("gamma", 0.85))
        self.v_sharpen_lum.set(s.get("sharpen_lum", 1.8))
        self.v_sharpen_chr.set(s.get("sharpen_chr", 0.5))
        self.v_dither.set(s.get("dither", "none"))
        self.v_scroll_enabled.set(s.get("scroll_enabled", True))
        self.v_zoom.set(s.get("zoom", 1.0))
        self.v_manual_x.set(s.get("manual_x", 0))
        self.v_manual_y.set(s.get("manual_y", 0))
        self.v_hue_shift.set(s.get("hue_shift", 0.0))
        self.v_noise_reduction.set(s.get("noise_reduction", 0.0))
        self.v_film_grain.set(s.get("film_grain", 0))
        self.v_vignette.set(s.get("vignette", False))
        self.v_auto_action_enabled.set(s.get("auto_action_enabled", False))
        self.v_action_detector.set(s.get("action_detector", "person"))
        self.v_action_strength.set(s.get("action_strength", 0.65))
        self.v_action_smoothness.set(s.get("action_smoothness", 0.65))
        self.v_action_zoom_max.set(s.get("action_zoom_max", 2.0))
        self.v_action_padding.set(s.get("action_padding", 0.20))
        self.v_action_intro.set(s.get("action_intro", 1.5))
        self.v_action_bottom_crop.set(s.get("action_bottom_crop", 0.0))
        self.v_action_auto_bottom_crop.set(s.get("action_auto_bottom_crop", False))
        self.v_action_top_crop.set(s.get("action_top_crop", 0.0))
        self.v_action_auto_top_crop.set(s.get("action_auto_top_crop", False))
        self.v_action_vertical_bias.set(s.get("action_vertical_bias", 0.0))
        self.v_action_auto_vertical_bias.set(s.get("action_auto_vertical_bias", False))
        self.v_action_smart_auto_crop.set(s.get("action_smart_auto_crop", False))
        self.v_bg_sub_enable.set(s.get("bg_sub_enable", False))
        self.v_dmd_visibility_score_enabled.set(s.get("dmd_visibility_score_enabled", False)) # NEW
        self.v_dmd_readability_score_enabled.set(s.get("dmd_readability_score_enabled", True)) # NEW
        self.v_target_width.set(s.get("target_width", 128))
        self.v_target_height.set(s.get("target_height", 32))
        self.v_target_preset.set(s.get("target_preset", "128x32 (1x1)"))
        self.v_text_overlay_enabled.set(s.get("text_overlay_enabled", False))
        self.v_text_content.set(s.get("text_content", ""))
        self.v_text_font_size.set(s.get("text_font_size", 8))
        self.v_text_color.set(s.get("text_color", "white"))
        self.v_text_position.set(s.get("text_position", "bottom_center"))
        self.v_text_font_file.set(s.get("text_font_file", "HelvetiPixel.ttf"))
        self.v_text_style.set(s.get("text_style", "outline"))
        self.v_text_bg.set(s.get("text_bg", False))
        self.v_text_bg_opacity.set(s.get("text_bg_opacity", 60))
        self.v_max_dur_enabled.set(s.get("max_dur_enabled", True))
        self.v_max_duration.set(s.get("max_duration", 120.0))
        self.v_auto_color_enabled.set(s.get("auto_color_enabled", False))
        # Sync UI widgets whose visibility is controlled by callbacks, not traces
        self._update_custom_visibility()
        self._on_text_overlay_toggle()
        self._on_scroll_enabled_change()
        self._on_text_bg_toggle()
        self._on_max_dur_toggle()

    # ══════════════════════════════════════════════════════════════════════════
    #  PARAMS
    # ══════════════════════════════════════════════════════════════════════════

    def _on_mode_change(self, mode):
        self._mode_desc_lbl.configure(text=MODE_DESC.get(mode, ""))
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
            "top_crop_pct":    self.v_top_crop.get(),
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
            "action_bottom_crop": self.v_action_bottom_crop.get(),
            "action_auto_bottom_crop": self.v_action_auto_bottom_crop.get(),
            "action_top_crop": self.v_action_top_crop.get(),
            "action_auto_top_crop": self.v_action_auto_top_crop.get(),
            "action_vertical_bias": self.v_action_vertical_bias.get(),
            "action_auto_vertical_bias": self.v_action_auto_vertical_bias.get(),
            "action_smart_auto_crop":    self.v_action_smart_auto_crop.get(),
            "bg_sub_enable": self.v_bg_sub_enable.get(),
            "dmd_visibility_score_enabled": self.v_dmd_visibility_score_enabled.get(), # NEW
            "dmd_readability_score_enabled": self.v_dmd_readability_score_enabled.get(), # NEW
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
        } | (
            # "Let Me Handle It" overrides — force the 5 managed params ON
            {
                "auto_color_enabled":     True,
                "auto_action_enabled":    True,
                "action_smart_auto_crop": True,
                "dmd_visibility_score_enabled": True,
                "dmd_readability_score_enabled": True,
            } if self.v_let_me_handle_it.get() else {}
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  CONVERSION
    # ══════════════════════════════════════════════════════════════════════════

