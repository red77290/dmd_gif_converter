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


class PreviewPanel(ctk.CTkFrame):
    """Animated preview + conversion actions."""

    def __init__(self, parent, app_state, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self._left_panel = None
        self._middle_panel = None
        
        from src.ui.preview.preview_player import PreviewPlayer
        from src.ui.preview.preview_controls import PreviewControls

        self._busy = False
        self._cancel_event = threading.Event()
        self._restoring_params = False
        self._adv_refresh_job = None
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.controls = PreviewControls(app_state, {
            "refresh_all": self._on_refresh_all,
            "show_src": self._on_show_src,
            "show_auto": self._on_show_auto,
            "show_dmd": self._on_show_dmd,
            "toggle_led": self._on_toggle_led,
            "on_start_drag": self._on_start_drag,
            "on_end_drag": self._on_end_drag,
            "reset_trim": self._reset_trim,
            "convert_selected": self.convert_selected,
            "convert_all": self.convert_all,
            "batch_folder": self.batch_folder,
            "cancel_conversion": self.cancel_conversion
        })
        
        self.controls.build_top_bar(self).grid(row=0, column=0, sticky="ew")
        
        self.player = PreviewPlayer(self, app_state)
        self.player.grid(row=1, column=0, sticky="nsew")
        
        self.controls.build_bottom_bar(self).grid(row=2, column=0, sticky="ew")
        
        self.bind("<Configure>", lambda e: self.controls.handle_resize(self.winfo_width()))
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, self._on_source_changed)

    def set_sibling_panels(self, left_panel, middle_panel):
        self._left_panel = left_panel
        self._middle_panel = middle_panel
        self.player.set_sibling_panels(left_panel, middle_panel)
        
    def _on_source_changed(self, payload):
        self.player._on_source_changed(payload)
        
    def _on_refresh_all(self): self.player.refresh_all_previews()
    def _on_show_src(self): self.player.show_source_preview()
    def _on_show_auto(self): self.player.show_auto_preview()
    def _on_show_dmd(self): self.player.show_dmd_preview()
    def _on_toggle_led(self): 
        is_on = self.player._toggle_led_sim()
        self.controls.set_led_sim_text(is_on)
    def _collect_params(self):
        s = self.app_state
        params = {}
        
        # 1. Dynamically collect all scalar variables from ApplicationState
        # This prevents the recurring problem of forgetting to add new configs here.
        for k, var in s._var_map.items():
            if k in ("v_trim_start", "v_trim_end"):
                continue  # Trim is per-file, not global
            if k.startswith("v_") and not k.startswith("v_action_"):
                # e.g., v_mode -> mode
                params[k[2:]] = var.get()

        # 2. Map aliases expected by the converter's DEFAULT_PARAMS
        if "bottom_crop" in params:
            params["bottom_crop_pct"] = params.pop("bottom_crop")
        if "top_crop" in params:
            params["top_crop_pct"] = params.pop("top_crop")
        if "workers" in params:
            params["max_workers"] = params["workers"]
            
        # 3. Special conditions
        params["max_duration"] = params.get("max_duration", 0.0) if params.get("max_dur_enabled", True) else 0.0
        params["smart_ratio_bypass"] = getattr(s, "v_smart_ratio_bypass", tk.BooleanVar(value=True)).get()
        params["log_level"] = getattr(self.winfo_toplevel(), "v_log_level", tk.StringVar(value="INFO")).get()

        # Inject all auto-action configuration parameters
        from src.engine.config.auto_action_config import AutoActionConfig
        action_cfg = AutoActionConfig.from_app_state(s)
        params.update(action_cfg.to_params_dict())
        # The main enable flag is not part of AutoActionConfig itself
        params["auto_action_enabled"] = s.v_action_enabled.get()
        if s.v_let_me_handle_it.get():
            params.update({
                "auto_color_enabled": True, "auto_action_enabled": True,
                "action_smart_auto_crop": True, "action_auto_pillarbox": True,
                "action_auto_scene_type": True, "action_auto_strength": True,
                "action_auto_smoothness": True, "action_auto_detector_fallback": True,
                "dmd_visibility_score_enabled": True, "dmd_readability_score_enabled": True,
            })
        return params

    # ══════════════════════════════════════════════════════════════════════════
    #  TRIM
    # ══════════════════════════════════════════════════════════════════════════

    def _update_trim_sliders(self):
        dur = max(self.player._source_duration, 0.1)
        self.controls._sl_start.configure(to=dur)
        self.controls._sl_end.configure(to=dur)
        self.app_state.v_trim_start.set(0.0)
        self.app_state.v_trim_end.set(dur)
        self.controls._lbl_start.configure(text="0.0 s")
        self.controls._lbl_end.configure(text=f"{dur:.1f} s")
        self.controls._sl_end.configure(state="normal")

    def _invalidate_auto_cache_and_refresh(self):
        if getattr(self.player, "_auto_tmpdir", None):
            import shutil, os
            if os.path.isdir(self.player._auto_tmpdir):
                shutil.rmtree(self.player._auto_tmpdir, ignore_errors=True)
            self.player._auto_tmpdir = None
        self._schedule_pipeline_refresh()

    def _on_start_drag(self, val):
        v = float(val)
        end = self.app_state.v_trim_end.get()
        if v >= end:
            self.app_state.v_trim_start.set(max(0.0, end - 0.05))
        self.controls._lbl_start.configure(text=f"{self.app_state.v_trim_start.get():.1f} s")
        self._invalidate_auto_cache_and_refresh()

    def _on_end_drag(self, val):
        v = float(val)
        start = self.app_state.v_trim_start.get()
        if v <= start:
            self.app_state.v_trim_end.set(min(self.player._source_duration, start + 0.05))
        self.controls._lbl_end.configure(text=f"{self.app_state.v_trim_end.get():.1f} s")
        self._invalidate_auto_cache_and_refresh()

    def _reset_trim(self):
        self.app_state.v_trim_start.set(0.0)
        self.app_state.v_trim_end.set(self.player._source_duration)
        self.controls._lbl_start.configure(text="0.0 s")
        self.controls._lbl_end.configure(text=f"{self.player._source_duration:.1f} s")
        self._invalidate_auto_cache_and_refresh()

    def _get_trim(self):
        s = self.app_state.v_trim_start.get()
        e = self.app_state.v_trim_end.get()
        return (None, None) if s <= 0.0 and e >= self.player._source_duration - 0.05 else (s, e)

    # ══════════════════════════════════════════════════════════════════════════
    #  DEBOUNCED REFRESH
    # ══════════════════════════════════════════════════════════════════════════

    def _schedule_pipeline_refresh(self, *_):
        if self._restoring_params:
            return
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self._adv_refresh_job = self.after(DMD_REFRESH_DELAY_MS, self._auto_refresh_pipeline)

    def _schedule_dmd_only_refresh(self, *_):
        if self._restoring_params:
            return
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self._adv_refresh_job = self.after(DMD_REFRESH_DELAY_MS, self._auto_refresh_dmd_only)

    def _auto_refresh_pipeline(self):
        self._adv_refresh_job = None
        if self.player._current_path and not self._busy and not self.player._auto_rendering and not self.player._dmd_rendering:
            self.player._start_auto_generation(self.player._current_path)
            self.player._start_dmd_generation(self.player._current_path)

    def _auto_refresh_dmd_only(self):
        self._adv_refresh_job = None
        if self.player._current_path and not self._busy and not self.player._dmd_rendering:
            self.player._start_dmd_generation(self.player._current_path)

    # ══════════════════════════════════════════════════════════════════════════
    #  CONVERSION LOGIC
    # ══════════════════════════════════════════════════════════════════════════

    def _out_path(self, src, iid=None):
        base = Path(src).stem + "_dmd" + ".gif"
        out_dir = self.app_state.v_output_dir.get().strip()
        if out_dir and os.path.isdir(out_dir):
            return str(Path(out_dir) / base)
        tmp_dir = Path(src).parent / "dmd_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return str(tmp_dir / base)

    def convert_selected(self):
        self._cancel_event.clear()
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        lp = self._left_panel
        if lp is None or not lp._selected_iid:
            messagebox.showinfo("Info", "Select a file from the list first.")
            return
        src = lp._file_data.get(lp._selected_iid)
        if not src:
            return
        out = self._out_path(src, iid=lp._selected_iid)
        start_s, end_s = self._get_trim()
        trim_info = f"  trim [{start_s:.1f}s → {end_s:.1f}s]" if start_s is not None else ""
        self._log(f"▶  Convert: {Path(src).name}{trim_info}")
        tasks = [(src, out, start_s, end_s, lp._selected_iid)]
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def convert_all(self):
        self._cancel_event.clear()
        lp = self._left_panel
        if lp is None or not lp._file_data:
            messagebox.showinfo("Info", "The file list is empty.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        tasks = [
            (path, self._out_path(path, iid=iid), None, None, iid)
            for iid, path in lp._file_data.items()
        ]
        self._log(f"⚡  Converting {len(tasks)} file(s)…")
        for _, _, _, _, iid in tasks:
            lp._set_file_status(iid, "converting")
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def batch_folder(self):
        self._cancel_event.clear()
        folder_in = filedialog.askdirectory(title="Source folder — Batch")
        if not folder_in:
            return
        out_dir = self.app_state.v_output_dir.get().strip()
        if not out_dir:
            out_dir = str(Path(folder_in) / "dmd_tmp")
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        files = [f for f in os.listdir(folder_in)
                 if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS]
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

    def cancel_conversion(self):
        self._cancel_event.set()
        self._log("⚠️  Cancellation requested…", "warning")
        self.controls._btn_cancel.configure(state="disabled", text="Stopping…")

    def _run_tasks(self, tasks, params):
        self.after(0, lambda: self._set_conv_busy(True))
        total = len(tasks)
        
        v_auto_workers = params.get("auto_workers", True)
        if v_auto_workers:
            max_workers = max(1, min(16, (os.cpu_count() or 4) // 2))
        else:
            max_workers = int(params.get("max_workers", 2))
            
        self.after(0, lambda w=max_workers: self._log(
            f"🚀  Convert {total} file(s) using {w} worker(s)…"))

        done_count = [0]
        done_lock = threading.Lock()
        # Per-task sequential worker ID for log isolation
        _wid_seq = [0]
        _wid_lock = threading.Lock()
        lp = self._left_panel
        mp = self._middle_panel
        per_gif_enabled = (
            lp is not None and
            hasattr(lp, "_per_gif_configs") and
            self.app_state.v_per_gif_config.get()
        )

        def _process_one(task_tuple):
            with _wid_lock:
                _wid_seq[0] += 1
                wid = _wid_seq[0]
            wid_tag = f"[W{wid}] "
            src, out, start_s, end_s, iid = task_tuple
            if self._cancel_event.is_set():
                return
            task_params = dict(params)
            if per_gif_enabled and iid in lp._per_gif_configs:
                task_params.update(lp._per_gif_configs[iid])
            if lp:
                self.after(0, lambda _i=iid: lp._set_file_status(_i, "converting"))
            success, msg = process_file(
                src, out, task_params, start_s, end_s,
                cancel_event=self._cancel_event,
            )
            if success:
                from src.engine.conversion.quality import load_score_sidecar
                score_result = load_score_sidecar(out) or {
                    "score": 0, "rating": "Unknown", "color": "⚪", "reasons": []
                }
                if mp:
                    self.after(0, lambda _o=out, _r=score_result:
                               mp._add_converted_file(_o, _r))
                if lp:
                    self.after(0, lambda _i=iid: lp._remove_specific_file(_i))
            else:
                if lp:
                    self.after(0, lambda _i=iid: lp._set_file_status(_i, "error"))
            with done_lock:
                done_count[0] += 1
                prog = done_count[0] / total
                self.after(0, lambda p=prog: self.controls._conv_progress.set(p))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            concurrent.futures.wait([ex.submit(_process_one, t) for t in tasks])

        if self._cancel_event.is_set():
            self.after(0, lambda: self._log("🛑  Conversion cancelled."))
        else:
            self.after(0, lambda: self._log(f"✅  {total} conversion(s) done."))
        self.after(0, lambda: self._set_conv_busy(False))

    def _run_batch_folder(self, folder_in, folder_out, params):
        folder_out = os.path.abspath(folder_out)
        self.after(0, lambda: self._set_conv_busy(True))
        self.after(0, lambda: self.controls._conv_progress.set(0))
        mp = self._middle_panel

        def on_progress(done, total):
            self.after(0, lambda f=done / max(1, total): self.controls._conv_progress.set(f))

        process_folder(
            folder_in, folder_out, params,
            progress_callback=on_progress,
            cancel_event=self._cancel_event,
        )

        if self._cancel_event.is_set():
            self.after(0, lambda: self._log("🛑  Batch cancelled."))
            self.after(0, lambda: self._set_conv_busy(False))
            return

        if self.controls.v_batch_auto_trash.get():
            try:
                threshold = int(self.controls.v_batch_trash_score.get())
                self.after(0, lambda: self._log(f"🧹 Auto-Trash ≤ {threshold}%…"))
                from src.engine.conversion.quality import load_score_sidecar
                try:
                    import send2trash; safe_delete = send2trash.send2trash
                except ImportError:
                    self.after(0, lambda: self._log(
                        "send2trash missing — deleting permanently", "warning"))
                    safe_delete = os.remove
                trashed = 0
                for f in os.listdir(folder_out):
                    if f.lower().endswith(".gif"):
                        gp = os.path.join(folder_out, f)
                        res = load_score_sidecar(gp)
                        if res and res.get("score", 0) <= threshold:
                            try:
                                safe_delete(gp)
                                trashed += 1
                                sc = gp + ".scores.json"
                                if os.path.exists(sc):
                                    safe_delete(sc)
                            except Exception as e:
                                self.after(0, lambda err=e: self._log(
                                    f"Trash failed: {err}", "warning"))
                self.after(0, lambda c=trashed: self._log(
                    f"✅  Auto-Trash removed {c} file(s)."))
            except ValueError:
                self.after(0, lambda: self._log(
                    "⚠️  Invalid threshold — skipping Auto-Trash.", "warning"))

        self.after(0, lambda: self._log("✅  Batch done."))
        self.after(0, lambda: self._set_conv_busy(False))

    def _set_conv_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        lp = self._left_panel
        for btn in (self.controls._btn_conv_all, self.controls._btn_batch):
            btn.configure(state=state)
        if not busy and lp and lp._selected_iid:
            self.controls._btn_conv_sel.configure(state="normal")
        else:
            self.controls._btn_conv_sel.configure(state="disabled")
        self.controls._btn_cancel.configure(
            state="normal" if busy else "disabled",
            text="⏹ Force Stop")
        self.controls._conv_status_lbl.configure(
            text="⏳  Converting…" if busy else "Ready")
        if not busy:
            self.after(2500, lambda: self.controls._conv_progress.set(0))
        EventBus.publish(
            EventType.CONVERSION_STARTED if busy else EventType.CONVERSION_FINISHED,
            {"busy": busy})

    def _log(self, message: str, level: str = "info"):
        lvl = {"debug": logging.DEBUG, "info": logging.INFO,
               "warning": logging.WARNING, "error": logging.ERROR}.get(level.lower(), logging.INFO)
        logger.log(lvl, message)

