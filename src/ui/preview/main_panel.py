"""
PreviewPanel  —  standalone preview widget for the new modular UI.

Subscribes to EventBus:
  • PREVIEW_SOURCE_CHANGED  {"path": str, ...}   → load a new file preview
  • PREVIEW_REFRESH_REQUESTED {"action": str}     → stop / idle individual canvases
"""
import os
import glob
import logging
import shutil
import threading
import tempfile
import subprocess
import concurrent.futures
from pathlib import Path
from tkinter import filedialog, messagebox

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from src.engine.conversion.core import (
    get_metadata, process_file, process_folder,
    DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
)
from src.engine.auto_action.main import AutoActionConfig, preprocess_video_for_dmd
from src.ui.widgets import _InfoBadge
from src.ui.preview.controllers.source_controller import SourceController
from src.ui.preview.controllers.auto_controller import AutoController
from src.ui.preview.controllers.dmd_controller import DmdController

from src.ui.constants import (
    BG_CANVAS,
    SRC_CANVAS_W, SRC_CANVAS_H,
    AUTO_CANVAS_W, AUTO_CANVAS_H,
    DMD_DISPLAY_SCALE_FACTOR,
    DMD_REFRESH_DELAY_MS,
)
from src.ui.dmd_led_sim import (
    LED_SIM_SCALE, LED_SIM_GAP, LED_SIM_MAX_W,
    apply_led_grid as _apply_led_grid,
)
from src.ui.events.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


class PreviewPanel(ctk.CTkFrame):
    """Animated preview + conversion actions."""

    def __init__(self, parent, app_state, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app_state = app_state

        # ── current file ──────────────────────────────────────────────────────
        self._current_path = None
        self._source_duration = 10.0

        # ── source preview state ──────────────────────────────────────────────
        self._src_pil_frames = []
        self._src_frames = []
        self._src_delays = []
        self._src_idx = 0
        self._src_job = None
        self._src_tmpdir = None

        # ── auto-action preview state ─────────────────────────────────────────
        self._auto_pil_frames = []
        self._auto_frames = []
        self._auto_delays = []
        self._auto_idx = 0
        self._auto_job = None
        self._auto_tmpdir = None
        self._auto_rendering = False
        self._auto_pending_src = None

        # ── DMD preview state ─────────────────────────────────────────────────
        self._dmd_pil_frames = []
        self._dmd_frames = []
        self._dmd_delays = []
        self._dmd_idx = 0
        self._dmd_job = None
        self._dmd_tmpdir = None
        self._dmd_rendering = False
        self._dmd_pending_src = None

        # ── conversion state ──────────────────────────────────────────────────
        self._busy = False
        self._cancel_event = threading.Event()

        # ── sibling panel refs (set from app.py) ─────────────────────────────
        self._left_panel = None
        self._middle_panel = None

        # ── misc ──────────────────────────────────────────────────────────────
        self._restoring_params = False
        self._adv_refresh_job = None

        # ── build widgets ─────────────────────────────────────────────────────
        self._build_preview_area(self)

        # ── EventBus subscriptions ────────────────────────────────────────────
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, self._on_source_changed)
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, self._on_refresh_requested)

        # Responsive layout bind
        self._is_stacked = False
        self.bind("<Configure>", self._on_resize)

    def set_sibling_panels(self, left_panel, middle_panel):
        """Inject sibling references so conversion can access the file list and result list."""
        self._left_panel = left_panel
        self._middle_panel = middle_panel

    # ══════════════════════════════════════════════════════════════════════════
    #  EventBus handlers
    # ══════════════════════════════════════════════════════════════════════════

    def _on_source_changed(self, payload):
        if not payload or "path" not in payload:
            return
        path = payload["path"]
        is_converted = payload.get("is_converted", False)
        converted_data = payload.get("converted_data")
        self._current_path = path
        self.after(0, lambda: self._load_preview(path,
                                                  is_converted=is_converted,
                                                  converted_data=converted_data))

    def _on_refresh_requested(self, payload):
        action = (payload or {}).get("action", "")
        dispatch = {
            "stop_src":  lambda: self.source_controller.stop() if hasattr(self, 'source_controller') else None,
            "stop_auto": lambda: self.auto_controller.stop() if hasattr(self, 'auto_controller') else None,
            "stop_dmd":  lambda: self.dmd_controller.stop() if hasattr(self, 'dmd_controller') else None,
            "idle_src":  lambda: self.source_controller.draw_idle() if hasattr(self, 'source_controller') else None,
            "idle_auto": lambda: self.auto_controller.draw_idle() if hasattr(self, 'auto_controller') else None,
            "idle_dmd":  lambda: self.dmd_controller.draw_idle() if hasattr(self, 'dmd_controller') else None,
        }
        if action == "stop_all":
            if hasattr(self, 'source_controller'): self.source_controller.stop()
            if hasattr(self, 'auto_controller'): self.auto_controller.stop()
            if hasattr(self, 'dmd_controller'): self.dmd_controller.stop()
            return
            
        fn = dispatch.get(action)
        if fn:
            self.after(0, fn)

    def _on_resize(self, event):
        # We handle canvas resizing in their own Configure events now.
        pass

    def _on_canvas_resize(self, event, canvas_id):
        w, h = event.width, event.height
        if w < 10 or h < 10:
            return
            
        canvas = None
        if canvas_id == "src":
            canvas = self._src_canvas
            if abs(w - getattr(self, "_last_src_w", 0)) > 5 or abs(h - getattr(self, "_last_src_h", 0)) > 5:
                self._last_src_w = w
                self._last_src_h = h
                self._src_frames = [None] * len(self._src_pil_frames) if hasattr(self, "_src_pil_frames") else []
        elif canvas_id == "auto":
            canvas = self._auto_canvas
            if abs(w - getattr(self, "_last_auto_w", 0)) > 5 or abs(h - getattr(self, "_last_auto_h", 0)) > 5:
                self._last_auto_w = w
                self._last_auto_h = h
                self._auto_frames = [None] * len(self._auto_pil_frames) if hasattr(self, "_auto_pil_frames") else []
        elif canvas_id == "dmd":
            canvas = self._dmd_canvas
            if abs(w - getattr(self, "_last_dmd_w", 0)) > 5 or abs(h - getattr(self, "_last_dmd_h", 0)) > 5:
                self._last_dmd_w = w
                self._last_dmd_h = h
                self._dmd_frames = [None] * len(self._dmd_pil_frames) if hasattr(self, "_dmd_pil_frames") else []
                
        # Handle button panel responsiveness based on scroll frame width (pf is the master of self)
        # However, we only get events for canvases here. We should bind Configure on PreviewPanel.
        # Actually, if we just use the main window width approx or self.winfo_width(), we can rearrange `_pb`.
        pw = self.winfo_width()
        if hasattr(self, "_pb"):
            if pw < 750:
                self._pb.grid(row=1, column=0, sticky="w", pady=(4, 0))
            else:
                self._pb.grid(row=0, column=1, sticky="e", pady=0)
                
        if canvas:
            for item in canvas.find_withtag("info_text"):
                canvas.coords(item, w // 2, h // 2)
                canvas.itemconfigure(item, width=max(20, w - 20))

    # ══════════════════════════════════════════════════════════════════════════
    #  BUILD UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build_preview_area(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=0)

        pf = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        pf.grid(row=0, column=0, sticky="nsew")
        pf.grid_columnconfigure(0, weight=1)
        
        # ── Actions section (Convert / Batch / Stop) — pinned at bottom, always visible
        self._build_actions_section(parent)
        # No row has weight: blocks (src/auto, dmd, trim, actions) stack
        # compactly from the top with no gaps between them.

        tr = ctk.CTkFrame(pf, fg_color="transparent")
        tr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        tr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            tr, text="🖥️  Preview  —  SOURCE → AUTO → DMD",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        self._pb = ctk.CTkFrame(tr, fg_color="transparent")
        self._pb.grid(row=0, column=1, sticky="e")
        self._btn_all_prev = ctk.CTkButton(
            self._pb, text="🔄 Refresh All", width=110, height=26,
            command=self.refresh_all_previews)
        self._btn_all_prev.pack(side="left", padx=2)
        self._btn_src = ctk.CTkButton(
            self._pb, text="▶ Source", width=80, height=26,
            command=self.show_source_preview)
        self._btn_src.pack(side="left", padx=2)
        self._btn_auto = ctk.CTkButton(
            self._pb, text="🎯 Auto", width=80, height=26,
            fg_color="#2b4b8a", hover_color="#234073",
            command=self.show_auto_preview)
        self._btn_auto.pack(side="left", padx=2)
        self._btn_dmd = ctk.CTkButton(
            self._pb, text="🔬 DMD", width=80, height=26,
            fg_color="#1e6a3c", hover_color="#155230",
            command=self.show_dmd_preview)
        self._btn_dmd.pack(side="left", padx=2)
        self._btn_led_sim = ctk.CTkButton(
            self._pb, text="💡 LED Sim ✓", width=90, height=26,
            fg_color="#5a4a00", hover_color="#7a6400",
            command=self._toggle_led_sim)
        self._btn_led_sim.pack(side="left", padx=2)

        dc = ctk.CTkFrame(pf, fg_color="transparent")
        dc.grid(row=1, column=0, padx=6, pady=4, sticky="ew")
        dc.grid_columnconfigure((0, 1), weight=1)

        self._src_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        self._src_wrap.grid(row=0, column=0, padx=(0, 4), pady=4, sticky="nsew")
        ctk.CTkLabel(self._src_wrap, text="SOURCE",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="#556677"
                     ).pack(pady=(4, 0))
        self._src_canvas = tk.Canvas(self._src_wrap, width=SRC_CANVAS_W, height=SRC_CANVAS_H,
                                     bg=BG_CANVAS, highlightthickness=0)
        self._src_canvas.pack(padx=2, pady=(2, 2), expand=True, fill="both")
        self._src_canvas.bind("<Configure>", lambda e: self._on_canvas_resize(e, "src"))
        self._src_info = _InfoBadge(self._src_wrap, width=SRC_CANVAS_W)
        self._src_info.pack(pady=(0, 4))

        self._auto_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        self._auto_wrap.grid(row=0, column=1, padx=(4, 0), pady=4, sticky="nsew")
        ctk.CTkLabel(self._auto_wrap, text="AUTO ACTION",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="#4f7bd9"
                     ).pack(pady=(4, 0))
        self._auto_canvas = tk.Canvas(self._auto_wrap, width=AUTO_CANVAS_W, height=AUTO_CANVAS_H,
                                      bg=BG_CANVAS, highlightthickness=0)
        self._auto_canvas.pack(padx=2, pady=(2, 2), expand=True, fill="both")
        self._auto_canvas.bind("<Configure>", lambda e: self._on_canvas_resize(e, "auto"))
        self._auto_info = _InfoBadge(self._auto_wrap, width=AUTO_CANVAS_W)
        self._auto_info.pack(pady=(0, 4))

        # dmd_wrap is a direct child of pf (row=2) to prevent it from being
        # squeezed when trim (row=3) appears and compresses the dc frame (row=1).
        dmd_wrap = ctk.CTkFrame(pf, fg_color=BG_CANVAS, corner_radius=6)
        dmd_wrap.grid(row=2, column=0, padx=4, pady=(4, 4), sticky="nsew")
        self._dmd_title_label = ctk.CTkLabel(
            dmd_wrap,
            text=f"DMD OUTPUT {DEFAULT_PARAMS['target_width']}×{DEFAULT_PARAMS['target_height']}",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#2e7a4a")
        self._dmd_title_label.pack(pady=(4, 0))
        self._dmd_canvas = tk.Canvas(
            dmd_wrap,
            width=int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR),
            height=int(DEFAULT_PARAMS["target_height"] * DMD_DISPLAY_SCALE_FACTOR),
            bg=BG_CANVAS, highlightthickness=0)
        self._dmd_canvas.pack(padx=2, pady=(2, 2), expand=True, fill="both")
        self._dmd_canvas.bind("<Configure>", lambda e: self._on_canvas_resize(e, "dmd"))
        self._dmd_info = _InfoBadge(
            dmd_wrap, width=int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR))
        self._dmd_info.pack(pady=(0, 4))

        self._canvas = self._src_canvas
        self._preview_info = self._src_info

        self.app_state.v_target_width.trace_add("write", self._update_dmd_canvas_size)
        self.app_state.v_target_height.trace_add("write", self._update_dmd_canvas_size)

        if hasattr(self, 'source_controller'): self.source_controller.draw_idle()
        if hasattr(self, 'auto_controller'): self.auto_controller.draw_idle()
        if hasattr(self, 'dmd_controller'): self.dmd_controller.draw_idle()

        # Sync canvas to actual initial size (LED sim may already be ON by default)
        self.after(0, self._update_dmd_canvas_size)

        # Trim frame
        self._trim_frame = ctk.CTkFrame(pf, fg_color="#16213e")
        self._trim_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._trim_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._trim_frame, text="✂️  Trim  (single-file only)",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color="#7ec8e3"
                     ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 4), sticky="w")
        ctk.CTkLabel(self._trim_frame, text="Start", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=(10, 4), pady=2)
        self._sl_start = ctk.CTkSlider(self._trim_frame, from_=0, to=1,
                                       variable=self.app_state.v_trim_start,
                                       command=self._on_start_drag)
        self._sl_start.grid(row=1, column=1, sticky="ew", padx=4)
        self._lbl_start = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                       font=ctk.CTkFont(size=11))
        self._lbl_start.grid(row=1, column=2, padx=4)
        ctk.CTkLabel(self._trim_frame, text="End", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=2, column=0, padx=(10, 4), pady=2)
        self._sl_end = ctk.CTkSlider(self._trim_frame, from_=0, to=1,
                                     variable=self.app_state.v_trim_end,
                                     command=self._on_end_drag)
        self._sl_end.grid(row=2, column=1, sticky="ew", padx=4, pady=(2, 8))
        self._lbl_end = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                     font=ctk.CTkFont(size=11))
        self._lbl_end.grid(row=2, column=2, padx=4)
        ctk.CTkButton(self._trim_frame, text="↺ Reset", command=self._reset_trim,
                      width=70, height=24, fg_color="transparent", border_width=1
                      ).grid(row=1, column=3, rowspan=2, padx=(4, 10))
        self._trim_frame.grid_remove()

        # Diagnosis frame
        self._diagnosis_frame = ctk.CTkFrame(pf, fg_color="#1a1a2e", corner_radius=6)
        self._diagnosis_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 8))
        self._diagnosis_frame.grid_columnconfigure(1, weight=1)
        self._lbl_score = ctk.CTkLabel(self._diagnosis_frame, text="",
                                       font=ctk.CTkFont(size=18, weight="bold"))
        self._lbl_score.grid(row=0, column=0, padx=12, pady=10)
        self._lbl_reasons = ctk.CTkLabel(self._diagnosis_frame, text="",
                                         justify="left", anchor="w")
        self._lbl_reasons.grid(row=0, column=1, sticky="w", padx=10)
        self._diagnosis_frame.grid_remove()

    # ══════════════════════════════════════════════════════════════════════════
    #  ACTIONS SECTION  (convert / batch / stop)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_actions_section(self, parent):
        af = ctk.CTkFrame(parent, fg_color="#0d1420", corner_radius=8,
                          border_width=1, border_color="#1a3a2a")
        af.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 8))
        af.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            af, text="🚀  Convert",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#7ec8e3"
        ).grid(row=0, column=0, padx=12, pady=(6, 2), sticky="w")

        bf = ctk.CTkFrame(af, fg_color="transparent")
        bf.grid(row=1, column=0, padx=8, pady=2, sticky="ew")
        bf.grid_columnconfigure(0, weight=1)

        self._btn_convert = ctk.CTkButton(
            bf, text="▶  Convert selected file",
            command=self.convert_selected,
            height=44, fg_color="#1a4f7a", hover_color="#1a618d",
            font=ctk.CTkFont(size=13, weight="bold"), state="disabled"
        )
        self._btn_convert.grid(row=0, column=0, padx=4, pady=(2, 4), sticky="ew")

        r2 = ctk.CTkFrame(bf, fg_color="transparent")
        r2.grid(row=1, column=0, sticky="ew")
        r2.grid_columnconfigure((0, 1), weight=1)

        self._btn_all = ctk.CTkButton(
            r2, text="⚡  Convert all",
            command=self.convert_all,
            height=32, fg_color="#5b2fa0", hover_color="#4a2585",
            font=ctk.CTkFont(size=12)
        )
        self._btn_all.grid(row=0, column=0, padx=(4, 2), pady=4, sticky="ew")

        self._btn_batch = ctk.CTkButton(
            r2, text="📂  Batch folder",
            command=self.batch_folder,
            height=32, fg_color="#1e6a3c", hover_color="#155230",
            font=ctk.CTkFont(size=12)
        )
        self._btn_batch.grid(row=0, column=1, padx=(2, 4), pady=4, sticky="ew")

        # Auto-Trash option for batch
        tr = ctk.CTkFrame(bf, fg_color="transparent")
        tr.grid(row=2, column=0, padx=4, pady=(0, 2), sticky="w")
        self.v_batch_auto_trash = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            tr, text="Auto-Trash ≤",
            variable=self.v_batch_auto_trash,
            checkbox_height=16, checkbox_width=16, font=ctk.CTkFont(size=11)
        ).pack(side="left", padx=(0, 2))
        self.v_batch_trash_score = tk.StringVar(value="50")
        ctk.CTkEntry(
            tr, textvariable=self.v_batch_trash_score,
            width=36, height=20, font=ctk.CTkFont(size=11), justify="center"
        ).pack(side="left")
        ctk.CTkLabel(tr, text="%  (batch)", font=ctk.CTkFont(size=11)).pack(side="left", padx=(2, 0))

        self._conv_progress = ctk.CTkProgressBar(bf, height=8)
        self._conv_progress.set(0)
        self._conv_progress.grid(row=3, column=0, padx=4, pady=(6, 2), sticky="ew")

        self._conv_status_lbl = ctk.CTkLabel(
            bf, text="Ready", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._conv_status_lbl.grid(row=4, column=0, padx=4, pady=2)

        self._btn_stop = ctk.CTkButton(
            bf, text="⏹ Force Stop",
            command=self.cancel_conversion,
            height=28, fg_color="#c0392b", hover_color="#922b21",
            font=ctk.CTkFont(size=11, weight="bold"), state="disabled"
        )
        self._btn_stop.grid(row=5, column=0, padx=4, pady=(2, 6), sticky="ew")

    def _compute_led_sim_display_size(self):
        try:
            w, h = self._get_target_dims()
            
        except Exception:
            w, h = 128, 32
        scale = int(LED_SIM_SCALE)
        while w * scale > LED_SIM_MAX_W and scale > 2:
            scale -= 1
        return int(w * scale), int(h * scale), scale

    def _get_target_dims(self):
        try:
            w = int(self.app_state.v_target_width.get())
            h = int(self.app_state.v_target_height.get())
            
            if w == 0 or h == 0:
                from src.engine.conversion.ffmpeg_utils import get_metadata
                if getattr(self, "_current_path", None):
                    mw, mh, _, _ = get_metadata(self._current_path)
                    if mw and mh:
                        return mw, mh
                return 128, 32
            return w, h
        except Exception:
            return 128, 32

    def _get_final_canvas_size(self):
        w, h = self._get_target_dims()
        led = getattr(self.app_state, "v_led_sim", None)
        if led and led.get():
            dw, dh, _ = self._compute_led_sim_display_size()
        else:
            dw, dh = int(w * DMD_DISPLAY_SCALE_FACTOR), int(h * DMD_DISPLAY_SCALE_FACTOR)
        MAX_W, MAX_H = 512, 160
        if dw > MAX_W or dh > MAX_H:
            s = min(MAX_W / dw, MAX_H / dh)
            dw, dh = int(dw * s), int(dh * s)
        return dw, dh

    def _update_dmd_canvas_size(self, *_):
        if not self.winfo_exists() or not getattr(self, "_dmd_canvas", None) or not self._dmd_canvas.winfo_exists():
            return
        w, h = self._get_target_dims()
        if w == 0 or h == 0:
            return
        nw, nh = self._get_final_canvas_size()
        self._dmd_canvas.configure(width=nw, height=nh)
        if hasattr(self, "_dmd_title_label"):
            sim = "  💡" if (getattr(self.app_state, "v_led_sim", None) and
                             self.app_state.v_led_sim.get()) else ""
            self._dmd_title_label.configure(text=f"DMD OUTPUT {w}×{h}{sim}")
        has_frames = hasattr(self, 'dmd_controller') and self.dmd_controller.pil_frames
        is_rendering = hasattr(self, 'dmd_controller') and self.dmd_controller.rendering
        if not has_frames and not is_rendering:
            if hasattr(self, 'dmd_controller'): self.dmd_controller.draw_idle()

    def _toggle_led_sim(self):
        is_on = not self.app_state.v_led_sim.get()
        self.app_state.v_led_sim.set(is_on)
        self._btn_led_sim.configure(
            fg_color="#5a4a00" if is_on else "#1a1a2e",
            hover_color="#7a6400" if is_on else "#2a2a4a",
            text="💡 LED Sim ✓" if is_on else "💡 LED Sim")
        self._update_dmd_canvas_size()
        self._dmd_frames = [None] * len(self._dmd_pil_frames) if hasattr(self, "_dmd_pil_frames") else []
        if getattr(self, "_dmd_cached_out", None) and os.path.isfile(self._dmd_cached_out):
            self._start_dmd_generation(self._dmd_cached_out, is_already_converted=True)
        elif self._current_path and not self._dmd_rendering:
            self._start_dmd_generation(self._current_path)

    # ══════════════════════════════════════════════════════════════════════════
    #  IDLE DRAW
    # ══════════════════════════════════════════════════════════════════════════

    def _draw_canvas_idle(self):
        self._src_canvas.delete("all")
        cw = max(20, self._src_canvas.winfo_width()) if self._src_canvas.winfo_width() > 10 else SRC_CANVAS_W
        self._src_canvas.create_text(cw // 2, getattr(self, "_last_src_h", SRC_CANVAS_H) // 2,
                                     text="← Select a file to preview",
                                     fill="#445566", font=("Helvetica", 12), justify="center",
                                     width=cw - 20, tags="info_text")
        if hasattr(self, "_src_info"):
            self._src_info.configure(text="")

    def _draw_auto_canvas_idle(self):
        self._auto_canvas.delete("all")
        cw = max(20, self._auto_canvas.winfo_width()) if self._auto_canvas.winfo_width() > 10 else AUTO_CANVAS_W
        self._auto_canvas.create_text(cw // 2, getattr(self, "_last_auto_h", AUTO_CANVAS_H) // 2,
                                      text="Auto action preview\n(disabled by default)",
                                      fill="#334466", font=("Helvetica", 11), justify="center",
                                      width=cw - 20, tags="info_text")
        if hasattr(self, "_auto_info"):
            self._auto_info.configure(text="")

    def _draw_dmd_canvas_idle(self):
        self._dmd_canvas.delete("all")
        try:
            cw, ch = self._get_final_canvas_size()
        except Exception:
            cw, ch = int(128 * DMD_DISPLAY_SCALE_FACTOR), int(32 * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(cw // 2, ch // 2,
                                     text="← Select a file then\n  click 🔬 Refresh DMD",
                                     fill="#334455", font=("Helvetica", 11), justify="center",
                                     width=cw - 20, tags="info_text")
        if hasattr(self, "_dmd_info"):
            self._dmd_info.configure(text="")

    # ══════════════════════════════════════════════════════════════════════════
    #  LOAD PREVIEW
    # ══════════════════════════════════════════════════════════════════════════

    def _load_preview(self, file_path, is_converted=False, converted_data=None):
        self._source_duration = 10.0
        from src.engine.conversion.utils import get_metadata
        _, __, ___, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self._update_trim_sliders()

        if is_converted:
            self._trim_frame.grid_remove()
            self._diagnosis_frame.grid()
            if converted_data:
                score = converted_data.get("score", 0)
                color = converted_data.get("color", "")
                rating = converted_data.get("rating", "")
                reasons = converted_data.get("reasons", [])
                self._lbl_score.configure(
                    text=f"{score}%\\n{rating}",
                    text_color=color if color and "#" in color else "#ffffff")
                
                reasons_text = " • " + "\\n • ".join(reasons) if reasons else "No specific reasons."
                self._lbl_reasons.configure(text=reasons_text)
            
            self.source_controller.draw_idle()
            self.auto_controller.draw_idle()
            self.dmd_controller.start_generation(file_path, is_already_converted=True)
        else:
            self._trim_frame.grid()
            self._diagnosis_frame.grid_remove()
            self.source_controller.load(file_path, self._source_duration)
            self.auto_controller.start_generation(file_path)

