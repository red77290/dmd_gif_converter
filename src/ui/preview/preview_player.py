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


class PreviewPlayer(ctk.CTkScrollableFrame):
    """Animated preview + conversion actions."""

    def __init__(self, parent, app_state, **kwargs):
        super().__init__(parent, fg_color="transparent", height=1, **kwargs)
        self.panel = parent
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

        # ── sibling panel refs (set from app.py) ─────────────────────────────

        # ── misc ──────────────────────────────────────────────────────────────

        # ── build widgets ─────────────────────────────────────────────────────
        self._build_preview_area(self)

        # ── EventBus subscriptions ────────────────────────────────────────────

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
            "stop_src":  self._stop_src_preview,
            "stop_auto": self._stop_auto_preview,
            "stop_dmd":  self._stop_dmd_preview,
            "idle_src":  self._draw_canvas_idle,
            "idle_auto": self._draw_auto_canvas_idle,
            "idle_dmd":  self._draw_dmd_canvas_idle,
        }
        fn = dispatch.get(action)
        if fn:
            self.after(0, fn)

    def _on_resize(self, event):
        # Trigger DMD canvas re-scale when panel width changes significantly
        if abs(event.width - getattr(self, "_last_panel_w", 0)) > 20:
            self._last_panel_w = event.width
            self.after(100, self._update_dmd_canvas_size)

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
        pf = self
        pf.grid_columnconfigure(0, weight=1)
        
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

        # Forward mouse wheel from standard tk.Canvas to CTkScrollableFrame parent
        for c in (self._src_canvas, self._auto_canvas, self._dmd_canvas):
            if hasattr(self, "_mouse_wheel_all"):
                c.bind("<MouseWheel>", self._mouse_wheel_all, add="+")
                c.bind("<Button-4>", self._mouse_wheel_all, add="+")
                c.bind("<Button-5>", self._mouse_wheel_all, add="+")

        self.app_state.v_target_width.trace_add("write", self._update_dmd_canvas_size)
        self.app_state.v_target_height.trace_add("write", self._update_dmd_canvas_size)

        self._draw_canvas_idle()
        self._draw_auto_canvas_idle()
        self._draw_dmd_canvas_idle()

        self.after(0, self._update_dmd_canvas_size)


    # ══════════════════════════════════════════════════════════════════════════
    #  ACTIONS SECTION  (convert / batch / stop)
    # ══════════════════════════════════════════════════════════════════════════

    def _compute_led_sim_display_size(self, max_w=None):
        try:
            w, h = self._get_target_dims()
        except Exception:
            w, h = 128, 32
            
        max_width = max_w if max_w else LED_SIM_MAX_W
        scale = int(LED_SIM_SCALE)
        while w * scale > max_width and scale > 2:
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
        
        available_w = self.winfo_width()
        MAX_W = max(200, available_w - 60) if available_w > 10 else 512
        MAX_H = 160
        
        led = getattr(self.app_state, "v_led_sim", None)
        if led and led.get():
            dw, dh, _ = self._compute_led_sim_display_size(max_w=MAX_W)
        else:
            dw, dh = int(w * DMD_DISPLAY_SCALE_FACTOR), int(h * DMD_DISPLAY_SCALE_FACTOR)

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
        self._last_dmd_w = nw
        self._last_dmd_h = nh
        
        # Force scroll region update in case geometry manager delays
        self.after(50, lambda: self._parent_canvas.configure(scrollregion=self._parent_canvas.bbox("all")))
        
        if hasattr(self, "_dmd_title_label"):
            sim = "  💡" if (getattr(self.app_state, "v_led_sim", None) and
                             self.app_state.v_led_sim.get()) else ""
            self._dmd_title_label.configure(text=f"DMD OUTPUT {w}×{h}{sim}")
        if not self._dmd_frames and not self._dmd_rendering:
            self._draw_dmd_canvas_idle()

    def _toggle_led_sim(self):
        is_on = not self.app_state.v_led_sim.get()
        self.app_state.v_led_sim.set(is_on)
        self.panel.controls._btn_led_sim.configure(
            fg_color="#5a4a00" if is_on else "#1a1a2e",
            hover_color="#7a6400" if is_on else "#2a2a4a",
            text="💡 LED Sim ✓" if is_on else "💡 LED Sim")
        self._update_dmd_canvas_size()
        
        # If we already have PIL frames, just clear the ImageTk cache so the running _animate_dmd loop recreates them.
        if getattr(self, "_dmd_pil_frames", None):
            self._dmd_frames = [None] * len(self._dmd_pil_frames)
        else:
            self._dmd_frames = []
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
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        for c in (self._src_canvas, self._auto_canvas, self._dmd_canvas):
            c.delete("all")
        cw = max(20, self._src_canvas.winfo_width()) if self._src_canvas.winfo_width() > 10 else SRC_CANVAS_W
        self._src_canvas.create_text(cw // 2, getattr(self, "_last_src_h", SRC_CANVAS_H) // 2,
                                     text="⏳  Loading preview…",
                                     fill="#7ec8e3", font=("Helvetica", 12), justify="center",
                                     width=cw - 20, tags="info_text")
        _, __, ___, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self.panel._update_trim_sliders()

        if is_converted:
            self.panel.controls.hide_trim()
            self.panel.controls._diagnosis_frame.grid()
            if converted_data:
                score = converted_data.get("score", 0)
                color = converted_data.get("color", "")
                rating = converted_data.get("rating", "")
                reasons = converted_data.get("reasons", [])
                self.panel.controls._lbl_score.configure(
                    text=f"{score}%\n{rating}",
                    text_color=color if color and "#" in color else "#ffffff")
                self.panel.controls._lbl_reasons.configure(
                    text=" • " + "\n • ".join(reasons) if reasons else "No specific reasons.")
            self._start_dmd_generation(file_path, is_already_converted=True)
            self._draw_canvas_idle()
            self._draw_auto_canvas_idle()
        else:
            self.panel.controls.show_trim()
            self.panel.controls.hide_diagnosis()
            threading.Thread(target=self._extract_source_frames,
                             args=(file_path, getattr(self, "_src_gen_id", 0)), daemon=True).start()
            # Only start auto-generation here. It will chain to DMD generation when finished.
            self._start_auto_generation(file_path)

    # ══════════════════════════════════════════════════════════════════════════
    #  SOURCE
    # ══════════════════════════════════════════════════════════════════════════

    def _stop_src_preview(self):
        self._src_gen_id = getattr(self, "_src_gen_id", 0) + 1
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

    def _extract_source_frames(self, file_path, gen_id):
        tmpdir = tempfile.mkdtemp(prefix="dmd_src_")
        fps_prev = 12.5
        dur = min(self._source_duration, 10.0)
        cmd = ["ffmpeg", "-y", "-i", file_path, "-t", str(dur),
               "-vf", (f"fps={fps_prev},"
                       f"scale={SRC_CANVAS_W}:{SRC_CANVAS_H}:"
                       f"force_original_aspect_ratio=decrease,"
                       f"pad={SRC_CANVAS_W}:{SRC_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                       f":color={BG_CANVAS[1:]}"),
               "-f", "image2", os.path.join(tmpdir, "f%04d.png")]
        subprocess.run(cmd, capture_output=True)
        paths = sorted(glob.glob(os.path.join(tmpdir, "f*.png")))
        pil_frames, delays = [], []
        delay_ms = int(1000 / fps_prev)
        for fp in paths:
            try:
                pil_frames.append(Image.open(fp).convert("RGB").copy())
                delays.append(delay_ms)
            except Exception:
                pass
        self.after(0, lambda: self._on_source_frames_ready(pil_frames, delays, tmpdir, file_path, gen_id))

    def _on_source_frames_ready(self, pil_frames, delays, tmpdir, file_path, gen_id=0):
        if getattr(self, "_src_gen_id", 0) != gen_id:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._src_rendering = False
            self._flush_src_pending()
            return
            
        if not pil_frames:
            self._src_canvas.delete("all")
            cw = max(20, self._src_canvas.winfo_width()) if self._src_canvas.winfo_width() > 10 else SRC_CANVAS_W
            self._src_canvas.create_text(cw // 2, getattr(self, "_last_src_h", SRC_CANVAS_H) // 2,
                                         text="⚠️  Preview unavailable\n(ffmpeg missing?)",
                                         fill="#e74c3c", font=("Helvetica", 11), justify="center",
                                         width=cw - 20, tags="info_text")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._src_tmpdir = tmpdir
        self._src_pil_frames = pil_frames
        self._src_frames = [None] * len(pil_frames)
        self._src_delays = delays
        self._src_idx = 0
        self._src_info.configure(
            text=f"{Path(file_path).name}   ·   {len(pil_frames)} frames   ·   {self._source_duration:.1f} s")
        self._animate_src()

    def _animate_src(self):
        if not self._src_pil_frames:
            return
        num = len(self._src_pil_frames)
        idx = self._src_idx % (num + 1)
        if idx == num:
            self._src_canvas.delete("all")
            self._src_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
            self._src_idx += 1
            self._src_job = self.after(1000, self._animate_src)
            return
            
        cw = getattr(self, "_last_src_w", SRC_CANVAS_W)
        ch = getattr(self, "_last_src_h", SRC_CANVAS_H)
        
        if self._src_frames[idx] is None:
            pil_img = self._src_pil_frames[idx]
            img_ratio = pil_img.width / pil_img.height
            canvas_ratio = cw / ch
            if img_ratio > canvas_ratio:
                new_w = cw
                new_h = int(cw / img_ratio)
            else:
                new_h = ch
                new_w = int(ch * img_ratio)
            resized = pil_img.resize((new_w, new_h), Image.BILINEAR)
            self._src_frames[idx] = ImageTk.PhotoImage(resized)
            
        self._src_canvas.delete("all")
        self._src_canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._src_frames[idx])
        self._src_idx += 1
        self._src_job = self.after(self._src_delays[idx] if self._src_delays else 80, self._animate_src)

    def show_source_preview(self):
        if not self._current_path:
            from tkinter import messagebox; messagebox.showinfo("Info", "Select a file first.")
            return
        self._start_dmd_generation(self._current_path)

    # ══════════════════════════════════════════════════════════════════════════
    #  AUTO-ACTION
    # ══════════════════════════════════════════════════════════════════════════

    def _stop_auto_preview(self):
        self._auto_gen_id = getattr(self, "_auto_gen_id", 0) + 1
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

    def show_auto_preview(self):
        if not self._current_path:
            from tkinter import messagebox; messagebox.showinfo("Info", "Select a file first.")
            return
        self._start_auto_generation(self._current_path)

    def _start_auto_generation(self, src):
        self._auto_gen_id = getattr(self, "_auto_gen_id", 0) + 1
        if self._auto_rendering:
            self._auto_pending_src = src
            return
        if not self.app_state.v_action_enabled.get():
            self._stop_auto_preview()
            self._draw_auto_canvas_idle()
            self._auto_info.configure(text="Auto action disabled")
            return
        self._auto_pending_src = None
        self._auto_rendering = True
        self._stop_auto_preview()
        self._auto_canvas.delete("all")
        cw = max(20, self._auto_canvas.winfo_width()) if self._auto_canvas.winfo_width() > 10 else AUTO_CANVAS_W
        self._auto_canvas.create_text(cw // 2, getattr(self, "_last_auto_h", AUTO_CANVAS_H) // 2,
                                      text="⏳  Generating auto-action preview…",
                                      fill="#7aa2ff", font=("Helvetica", 11), justify="center",
                                      width=cw - 20, tags="info_text")
        self.panel.controls._btn_auto.configure(state="disabled", text="⏳ Auto…")
        start_s, end_s = self.panel._get_trim()
        s = self.app_state
        
        tw, th = self._get_target_dims()

        # Check smart ratio bypass
        bypass_active = s.v_smart_ratio_bypass.get() if hasattr(s, "v_smart_ratio_bypass") else True
        is_perfect_ratio = False
        is_original_mode = False
        print(f"target_width: {s.v_target_width.get()}")
        
        try:
            if str(s.v_target_width.get()) == "0" or str(s.v_target_height.get()) == "0":
                is_original_mode = True
        except Exception:
            pass
            
        try:
            if getattr(self, "_current_path", None):
                from src.engine.conversion.ffmpeg_utils import get_metadata
                src_w, src_h, _, _ = get_metadata(self._current_path)
                if src_w and src_h and tw and th:
                    if abs((src_w / src_h) - (tw / th)) < 0.05:
                        is_perfect_ratio = True
        except Exception:
            pass

        if is_original_mode or (bypass_active and is_perfect_ratio):
            self._on_auto_bypass()
            return

        cfg = AutoActionConfig.from_app_state(s, start_s=start_s, end_s=end_s, target_width=tw, target_height=th)
        
        # Enforce max 10 seconds for preview generation to prevent massive UI slowdowns
        effective_start = cfg.start_s if cfg.start_s is not None else 0.0
        effective_end = cfg.end_s if cfg.end_s is not None else getattr(self, "_source_duration", 10.0)
        if effective_end - effective_start > 10.0:
            cfg.end_s = effective_start + 10.0
            

        threading.Thread(target=self._generate_auto_preview,
                         args=(src, cfg, self._auto_gen_id), daemon=True).start()

    def _generate_auto_preview(self, src, cfg, gen_id):
        try:
            self.after(0, lambda: self.panel.controls._conv_progress.configure(mode="indeterminate"))
            self.after(0, lambda: self.panel.controls._conv_progress.start())
            
            ok, out_mp4, msg = preprocess_video_for_dmd(
                src, cfg
            )
            
            if msg:
                self.panel._log(f"[ACTION] {os.path.basename(src)} — {msg}", "info")
            
            self.after(0, lambda: self.panel.controls._conv_progress.stop())
            self.after(0, lambda: self.panel.controls._conv_progress.configure(mode="determinate"))
            self.after(0, lambda: self.panel.controls._conv_progress.set(0))
            
            if not ok or not out_mp4:
                self.after(0, lambda: self._on_auto_fail(msg, gen_id))
                return
            tmpdir = os.path.dirname(out_mp4)
            fps_prev = 12.5
            cmd = ["ffmpeg", "-y", "-i", out_mp4,
                   "-vf", (f"fps={fps_prev},"
                            f"scale={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:"
                            f"force_original_aspect_ratio=decrease,"
                            f"pad={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                            f":color={BG_CANVAS[1:]}"),
                   "-f", "image2", os.path.join(tmpdir, "a%04d.png")]
            subprocess.run(cmd, capture_output=True)
            paths = sorted(glob.glob(os.path.join(tmpdir, "a*.png")))
            pil_frames, delays = [], []
            for fp in paths:
                try:
                    pil_frames.append(Image.open(fp).convert("RGB").copy())
                    delays.append(int(1000 / fps_prev))
                except Exception:
                    pass
            self.after(0, lambda: self._on_auto_ready(pil_frames, delays, tmpdir, msg, gen_id))
        except Exception as exc:
            _m = str(exc)
            self.after(0, lambda _msg=_m: self._on_auto_fail(_msg, gen_id))

    def _on_auto_ready(self, pil_frames, delays, tmpdir, msg, gen_id=0):
        if getattr(self, "_auto_gen_id", 0) != gen_id:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._auto_rendering = False
            self._flush_auto_pending()
            return
            
        self._auto_rendering = False
        self.panel.controls._btn_auto.configure(state="normal", text="🎯 Auto")
        if not pil_frames:
            self._on_auto_fail("No frames produced")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._stop_auto_preview()
        self._auto_tmpdir = tmpdir
        self._auto_pil_frames = pil_frames
        self._auto_frames = [None] * len(pil_frames)
        self._auto_delays = delays
        self._auto_idx = 0
        summary_line = msg.split('\n')[-1] if msg else "Auto action complete"
        self._auto_info.configure(text=f"{summary_line}  ·  {len(pil_frames)} frames")
        self._animate_auto()
        self._flush_auto_pending()
        
        # Chain to DMD generation now that auto cache is ready
        if self._current_path:
            self._start_dmd_generation(self._current_path)

    def _on_auto_fail(self, msg, gen_id=0):
        if getattr(self, "_auto_gen_id", 0) != gen_id:
            if getattr(self, "_auto_tmpdir", None) and os.path.isdir(self._auto_tmpdir):
                shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
                self._auto_tmpdir = None
            self._auto_rendering = False
            self._flush_auto_pending()
            return
            
        self._auto_rendering = False
        self.panel.controls._btn_auto.configure(state="normal", text="🎯 Auto")
        if getattr(self, "_auto_tmpdir", None) and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None
        cw = max(20, self._auto_canvas.winfo_width()) if self._auto_canvas.winfo_width() > 10 else AUTO_CANVAS_W
        self._auto_canvas.create_text(cw // 2, getattr(self, "_last_auto_h", AUTO_CANVAS_H) // 2,
                                      text="❌  Auto-action failed",
                                      fill="#e74c3c", font=("Helvetica", 11), justify="center",
                                      width=cw - 20, tags="info_text")
        self._auto_info.configure(text=msg)
        self._flush_auto_pending()
        
        # Still try to run DMD generation even if auto failed
        if self._current_path:
            self._start_dmd_generation(self._current_path)

    def _on_auto_bypass(self):
        self._auto_rendering = False
        self.panel.controls._btn_auto.configure(state="normal", text="🎯 Auto")
        import shutil, os
        if getattr(self, "_auto_tmpdir", None) and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None
        self._auto_canvas.delete("all")
        cw = max(20, self._auto_canvas.winfo_width()) if self._auto_canvas.winfo_width() > 10 else AUTO_CANVAS_W
        self._auto_canvas.create_text(cw // 2, getattr(self, "_last_auto_h", AUTO_CANVAS_H) // 2,
                                      text="⏭️  Bypassed\n(Original or perfect ratio)",
                                      fill="#2ecc71", font=("Helvetica", 12), justify="center",
                                      width=cw - 20, tags="info_text")
        self._auto_info.configure(text="Auto Action is skipped. Color Boost & FPS only.")
        self._flush_auto_pending()
        
        # Chain to DMD generation
        if self._current_path:
            self._start_dmd_generation(self._current_path)

    def _flush_auto_pending(self):
        pending, self._auto_pending_src = self._auto_pending_src, None
        if pending and self._current_path:
            self.after(50, lambda: self._start_auto_generation(pending))

    def _animate_auto(self):
        if not self._auto_pil_frames:
            return
        num = len(self._auto_pil_frames)
        idx = self._auto_idx % (num + 1)
        if idx == num:
            self._auto_canvas.delete("all")
            self._auto_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
            self._auto_idx += 1
            self._auto_job = self.after(1000, self._animate_auto)
            return
            
        cw = getattr(self, "_last_auto_w", AUTO_CANVAS_W)
        ch = getattr(self, "_last_auto_h", AUTO_CANVAS_H)
        
        if self._auto_frames[idx] is None:
            pil_img = self._auto_pil_frames[idx]
            img_ratio = pil_img.width / max(1, pil_img.height)
            canvas_ratio = cw / max(1, ch)
            if img_ratio > canvas_ratio:
                new_w = cw
                new_h = int(cw / img_ratio)
            else:
                new_h = ch
                new_w = int(ch * img_ratio)
            resized = pil_img.resize((max(1, new_w), max(1, new_h)), Image.BILINEAR)
            self._auto_frames[idx] = ImageTk.PhotoImage(resized)
            
        self._auto_canvas.delete("all")
        self._auto_canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._auto_frames[idx])
        self._auto_idx += 1
        self._auto_job = self.after(self._auto_delays[idx] if self._auto_delays else 80, self._animate_auto)

    # ══════════════════════════════════════════════════════════════════════════
    #  DMD
    # ══════════════════════════════════════════════════════════════════════════

    def _stop_dmd_preview(self):
        self._dmd_gen_id = getattr(self, "_dmd_gen_id", 0) + 1
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
        if not self._current_path:
            from tkinter import messagebox; messagebox.showinfo("Info", "Select a file first.")
            return
        self._start_dmd_generation(self._current_path)

    def refresh_all_previews(self):
        if not self._current_path:
            from tkinter import messagebox; messagebox.showinfo("Info", "Select a file first.")
            return
        self._start_dmd_generation(self._current_path)

    def _start_dmd_generation(self, src, is_already_converted=False):
        self._dmd_gen_id = getattr(self, "_dmd_gen_id", 0) + 1
        if self._dmd_rendering:
            self._dmd_pending_src = src
            return
        self._dmd_pending_src = None
        self._dmd_rendering = True
        self.panel.controls._btn_dmd.configure(state="disabled", text="⏳ DMD…")
        # Always sync canvas size before computing frame dimensions
        self._update_dmd_canvas_size()
        try:
            cw, ch = self._get_final_canvas_size()
        except Exception:
            cw, ch = 128, 32
        self._dmd_canvas.delete("refresh_tag")
        self._dmd_canvas.create_text(cw - 4, 4, text="↻", fill="#f39c12",
                                     font=("Helvetica", 10, "bold"),
                                     anchor="ne", tags="refresh_tag")
        params = self.panel._collect_params()
        start_s, end_s = self.panel._get_trim()
        
        # Enforce max 10 seconds for preview generation
        effective_start = start_s if start_s is not None else 0.0
        effective_end = end_s if end_s is not None else getattr(self, "_source_duration", 10.0)
        if effective_end - effective_start > 10.0:
            start_s = effective_start
            end_s = effective_start + 10.0
            

        
        # Bypass YOLO tracking if the Auto Action preview has already generated the intermediate video
        if params.get("auto_action_enabled") and getattr(self, "_auto_tmpdir", None):
            cached_mp4 = os.path.join(self._auto_tmpdir, "action_pre.mp4")
            if os.path.isfile(cached_mp4):
                src = cached_mp4
                params["auto_action_enabled"] = False
                start_s = None  # The intermediate video is already trimmed
                end_s = None
                self.panel._log("⚡ Bypassing YOLO analysis (using cached Auto Action video).", "info")

        led = getattr(self.app_state, "v_led_sim", None)
        led_on = led.get() if led else False
        if led_on:
            dw, dh, sim_scale = self._compute_led_sim_display_size()
        else:
            dw, dh, sim_scale = cw, ch, 0
            
        threading.Thread(
            target=self._generate_dmd_preview,
            args=(src, params, start_s, end_s, is_already_converted, self._dmd_gen_id),
            daemon=True).start()

    def _generate_dmd_preview(self, src, params, start_s, end_s, is_already_converted=False, gen_id=0):
        tmpdir = tempfile.mkdtemp(prefix="dmd_dmd_")
        try:
            if is_already_converted:
                out_gif = src
            else:
                out_gif = os.path.join(tmpdir, "preview.mp4")
                
                if getattr(self, "_dmd_gen_id", 0) != gen_id:
                    self.after(0, lambda: self._on_dmd_fail("Aborted", tmpdir, gen_id))
                    return
                    
                self.after(0, lambda: self.panel.controls._conv_progress.configure(mode="indeterminate"))
                self.after(0, lambda: self.panel.controls._conv_progress.start())
                
                success, msg = process_file(
                    src, out_gif, params, start_s, end_s,
                    callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self.panel._log(_m, _lv))
                )
                
                if getattr(self, "_dmd_gen_id", 0) != gen_id:
                    self.after(0, lambda: self._on_dmd_fail("Aborted", tmpdir, gen_id))
                    return
                
                self.after(0, lambda: self.panel.controls._conv_progress.stop())
                self.after(0, lambda: self.panel.controls._conv_progress.configure(mode="determinate"))
                self.after(0, lambda: self.panel.controls._conv_progress.set(0))
                
                if not success or not os.path.isfile(out_gif):
                    self.after(0, lambda: self._on_dmd_fail(msg, tmpdir, gen_id))
                    return
            
            if getattr(self, "_dmd_gen_id", 0) != gen_id:
                self.after(0, lambda: self._on_dmd_fail("Aborted", tmpdir, gen_id))
                return
                
            pil_frames, delays = [], []
            try:
                if out_gif.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.webm')):
                    import cv2
                    from src.engine.auto_action.reader import _quiet_c_stderr
                    with _quiet_c_stderr():
                        cap = cv2.VideoCapture(out_gif)
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    dm = int(1000 / fps) if fps > 0 else 40
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        comp = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        pil_frames.append(comp)
                        delays.append(dm)
                    cap.release()
                else:
                    from PIL import ImageSequence
                    img = Image.open(out_gif)
                    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
                    for frame in ImageSequence.Iterator(img):
                        bg.paste(frame, (0, 0), frame.convert("RGBA"))
                        comp = bg.copy().convert("RGB")
                        pil_frames.append(comp)
                        delays.append(max(img.info.get("duration", 80), 20))
            except Exception as exc:
                self.after(0, lambda: self._on_dmd_fail(str(exc), tmpdir, gen_id))
                return
            if not pil_frames:
                self.after(0, lambda: self._on_dmd_fail("No frames decoded", tmpdir, gen_id))
                return
            self.after(0, lambda: self._on_dmd_ready(pil_frames, delays, tmpdir, out_gif, gen_id))
        except Exception as exc:
            self.after(0, lambda: self._on_dmd_fail(str(exc), tmpdir, gen_id))

    def _on_dmd_ready(self, pil_frames, delays, tmpdir, out_gif, gen_id=0):
        if getattr(self, "_dmd_gen_id", 0) != gen_id:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._dmd_rendering = False
            self._flush_dmd_pending()
            return
            
        try:
            self._dmd_rendering = False
            self.panel.controls._btn_dmd.configure(state="normal", text="🔬 DMD")
            self._stop_dmd_preview()
            self._dmd_tmpdir = tmpdir
            self._dmd_cached_out = out_gif
            self._dmd_pil_frames = pil_frames
            self._dmd_frames = [None] * len(pil_frames)
            self._dmd_delays = delays
            self._dmd_idx = 0
            size_kb = os.path.getsize(out_gif) // 1024 if os.path.isfile(out_gif) else 0
            self._dmd_info.configure(
                text=(f"✅  {self.app_state.v_target_width.get()}"
                      f"×{self.app_state.v_target_height.get()}"
                      f"  ·  {len(pil_frames)} frames  ·  {size_kb} KB"))
            self._animate_dmd()
            self._flush_dmd_pending()
        except Exception as e:
            logger.exception("_on_dmd_ready: %s", e)

    def _on_dmd_fail(self, msg, tmpdir, gen_id=0):
        if getattr(self, "_dmd_gen_id", 0) != gen_id:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._dmd_rendering = False
            self._flush_dmd_pending()
            return
            
        self._dmd_rendering = False
        self.panel.controls._btn_dmd.configure(state="normal", text="🔬 DMD")
        shutil.rmtree(tmpdir, ignore_errors=True)
        self._stop_dmd_preview()
        self._dmd_canvas.delete("all")
        try:
            cw, ch = self._get_final_canvas_size()
        except Exception:
            cw, ch = int(128 * DMD_DISPLAY_SCALE_FACTOR), int(32 * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(cw // 2, ch // 2,
                                     text="❌  DMD render failed",
                                     fill="#e74c3c", font=("Helvetica", 11), justify="center",
                                     width=cw - 20, tags="info_text")
        logger.error("DMD preview: %s", msg)
        self._flush_dmd_pending()

    def _flush_dmd_pending(self):
        pending, self._dmd_pending_src = self._dmd_pending_src, None
        if pending and self._current_path:
            self.after(50, lambda: self._start_dmd_generation(pending))

    def _animate_dmd(self):
        if not self._dmd_pil_frames:
            return
        try:
            num = len(self._dmd_pil_frames)
            idx = self._dmd_idx % (num + 1)
            if idx == num:
                self._dmd_canvas.delete("all")
                self._dmd_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
                self._dmd_idx += 1
                self._dmd_job = self.after(1000, self._animate_dmd)
                return
                
            cw = getattr(self, "_last_dmd_w", int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR))
            ch = getattr(self, "_last_dmd_h", int(DEFAULT_PARAMS["target_height"] * DMD_DISPLAY_SCALE_FACTOR))
                
            if self._dmd_frames[idx] is None:
                pil_img = self._dmd_pil_frames[idx]
                
                led = getattr(self.app_state, "v_led_sim", None)
                scale_w = cw // pil_img.width if pil_img.width > 0 else 2
                scale_h = ch // pil_img.height if pil_img.height > 0 else 2
                scale = min(scale_w, scale_h)
                
                if led and led.get() and scale >= 2:
                    if pil_img.width * scale > LED_SIM_MAX_W and scale > 2:
                        scale = max(2, LED_SIM_MAX_W // pil_img.width)
                        
                    resized = pil_img.resize((pil_img.width * scale, pil_img.height * scale), Image.NEAREST)
                    resized = _apply_led_grid(resized, scale)
                else:
                    img_ratio = pil_img.width / max(1, pil_img.height)
                    canvas_ratio = cw / max(1, ch)
                    if img_ratio > canvas_ratio:
                        new_w = cw
                        new_h = int(cw / img_ratio)
                    else:
                        new_h = ch
                        new_w = int(ch * img_ratio)
                    resized = pil_img.resize((max(1, new_w), max(1, new_h)), Image.NEAREST)
                    
                self._dmd_frames[idx] = ImageTk.PhotoImage(resized)
                
            self._dmd_canvas.delete("all")
            
            # Place the image exactly in the center of the actual canvas boundaries 
            # to prevent it from appearing off-center if the canvas was stretched by the geometry manager.
            actual_cw = self._dmd_canvas.winfo_width()
            actual_ch = self._dmd_canvas.winfo_height()
            draw_x = (actual_cw // 2) if actual_cw > 10 else (cw // 2)
            draw_y = (actual_ch // 2) if actual_ch > 10 else (ch // 2)
            
            self._dmd_canvas.create_image(draw_x, draw_y, anchor="center", image=self._dmd_frames[idx])
            self._dmd_idx += 1
            self._dmd_job = self.after(
                self._dmd_delays[idx] if self._dmd_delays else 80, self._animate_dmd)
        except Exception as e:
            logger.exception("_animate_dmd: %s", e)

    # ══════════════════════════════════════════════════════════════════════════
    #  PARAMS COLLECTION
    # ══════════════════════════════════════════════════════════════════════════

