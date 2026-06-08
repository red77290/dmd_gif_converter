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

class ActionsPanelMixin:
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

        ar = ctk.CTkScrollableFrame(bot, width=310)
        ar.grid(row=0, column=1, sticky="nsew")
        ar.grid_columnconfigure(0, weight=1)
        ar.grid_rowconfigure(3, weight=1)
        self._build_actions_panel(ar)

    # ── Params panel ──────────────────────────────────────────────────────────
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
        self._btn_batch.grid(row=2, column=0, padx=4, pady=(4, 0), sticky="ew")

        # Batch Auto-Cleanup Options
        batch_cleanup_frame = ctk.CTkFrame(af, fg_color="transparent")
        batch_cleanup_frame.grid(row=3, column=0, padx=4, pady=(0, 4), sticky="w")
        
        self.v_batch_auto_trash = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(batch_cleanup_frame, text="Auto-Trash <=", variable=self.v_batch_auto_trash, width=10, checkbox_height=18, checkbox_width=18, font=ctk.CTkFont(size=11)).pack(side="left", padx=(4, 2))
        
        self.v_batch_trash_score = tk.StringVar(value="50")
        ctk.CTkEntry(batch_cleanup_frame, textvariable=self.v_batch_trash_score, width=35, height=20, font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkLabel(batch_cleanup_frame, text="%", font=ctk.CTkFont(size=11)).pack(side="left")

        self._progress = ctk.CTkProgressBar(af, height=8)
        self._progress.set(0)
        self._progress.grid(row=4, column=0, padx=4, pady=(10, 2), sticky="ew")

        self._status_lbl = ctk.CTkLabel(
            af, text="Ready", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._status_lbl.grid(row=5, column=0, padx=4, pady=2)

        self._btn_stop = ctk.CTkButton(
            af, text="⏹ Force Stop",
            command=self.cancel_conversion,
            height=30, fg_color="#c0392b", hover_color="#922b21",
            font=ctk.CTkFont(size=12, weight="bold"), state="disabled"
        )
        self._btn_stop.grid(row=6, column=0, padx=4, pady=(2, 4), sticky="ew")

        logs_frame = ctk.CTkFrame(parent, fg_color="transparent")
        logs_frame.grid(row=2, column=0, padx=8, pady=(10, 4), sticky="ew")
        
        self._btn_toggle_logs = ctk.CTkButton(
            logs_frame, text="📝 Show / Hide Logs", width=140, height=28,
            fg_color="#3a3a4a", hover_color="#50506b",
            command=self._toggle_global_logs
        )
        self._btn_toggle_logs.pack(side="left", padx=4)

    def cancel_conversion(self):
        if hasattr(self, "_cancel_event"):
            self._cancel_event.set()
            self._log("⚠️  Cancellation requested... Interruption in progress.", "warning")
            self._btn_stop.configure(state="disabled", text="Stopping...")

    # ══════════════════════════════════════════════════════════════════════════
    #  FILE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def browse_output(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.v_output_dir.set(folder)

    # ══════════════════════════════════════════════════════════════════════════
    #  SOURCE PREVIEW
    # ══════════════════════════════════════════════════════════════════════════

    def _out_path(self, src):
        base = Path(src).stem + "_dmd" + Path(src).suffix
        out_dir = self.v_output_dir.get().strip()
        if out_dir and os.path.isdir(out_dir):
            return str(Path(out_dir) / base)
            
        # Use a temporary folder in the source directory by default
        tmp_dir = Path(src).parent / "dmd_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return str(tmp_dir / base)

    def convert_selected(self):
        if hasattr(self, "_cancel_event"): self._cancel_event.clear()
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
        if hasattr(self, "_cancel_event"): self._cancel_event.clear()
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
        if hasattr(self, "_cancel_event"): self._cancel_event.clear()
        folder_in = filedialog.askdirectory(title="Source folder — Batch")
        if not folder_in:
            return
        out_dir = self.v_output_dir.get().strip()
        if not out_dir:
            out_dir = str(Path(folder_in) / "dmd_tmp")
            Path(out_dir).mkdir(parents=True, exist_ok=True)
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
        import concurrent.futures
        self.after(0, lambda: self._set_busy(True))
        total = len(tasks)
        max_workers = int(params.get("max_workers", 2))
        self.after(0, lambda w=max_workers: self._log(f"🚀  Convert all: {total} files using {w} workers..."))
        
        done_count = [0]
        done_lock = threading.Lock()

        def _process_one_task(task_tuple):
            src, out, start_s, end_s, iid = task_tuple
            if hasattr(self, "_cancel_event") and self._cancel_event.is_set():
                return
            
            self.after(0, lambda _iid=iid: self._set_file_status(_iid, "converting"))
            success, msg = process_file(
                src, out, params, start_s, end_s,
                callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv)),
                cancel_event=getattr(self, "_cancel_event", None)
            )
            
            if success:
                from src.converter.quality import load_score_sidecar
                score_result = load_score_sidecar(out) or {"score": 0, "rating": "Unknown", "color": "⚪", "reasons": ["No score"]}
                self.after(0, lambda _out=out, _res=score_result: self._add_converted_file(_out, _res))
                self.after(0, lambda _iid=iid: self._remove_specific_file(_iid))
            else:
                self.after(0, lambda _iid=iid: self._set_file_status(_iid, "error"))
                
            with done_lock:
                done_count[0] += 1
                progress = done_count[0] / total
                self.after(0, lambda p=progress: self._progress.set(p))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_process_one_task, t) for t in tasks]
            concurrent.futures.wait(futures)

        if hasattr(self, "_cancel_event") and self._cancel_event.is_set():
            self.after(0, lambda: self._log("🛑  List processing cancelled."))
        else:
            self.after(0, lambda: self._log(f"✅  {total} conversion(s) done."))
            
        self.after(0, lambda: self._set_busy(False))

    def _run_batch_folder(self, folder_in, folder_out, params):
        folder_out = os.path.abspath(folder_out)
        self.after(0, lambda: self._set_busy(True))
        self.after(0, lambda: self._progress.set(0))

        def on_progress(done, total):
            frac = done / max(1, total)
            self.after(0, lambda f=frac: self._progress.set(f))

        process_folder(
            folder_in, folder_out, params,
            callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv)),
            progress_callback=on_progress,
            cancel_event=getattr(self, "_cancel_event", None)
        )
        
        if hasattr(self, "_cancel_event") and self._cancel_event.is_set():
            self.after(0, lambda: self._log("🛑  Batch processing cancelled."))
            self.after(0, lambda: self._set_busy(False))
            return

        # Perform Auto-Cleanup if enabled
        if self.v_batch_auto_trash.get():
            try:
                threshold = int(self.v_batch_trash_score.get())
                self.after(0, lambda: self._log(f"🧹 Running Auto-Cleanup (Trash <= {threshold}%)..."))
                
                from src.converter.quality import load_score_sidecar
                try:
                    import send2trash
                    safe_delete = send2trash.send2trash
                except ImportError:
                    self.after(0, lambda: self._log("send2trash module missing. Deleting permanently instead.", "warning"))
                    safe_delete = os.remove
                
                trashed_count = 0
                for f in os.listdir(folder_out):
                    if f.lower().endswith('.gif'):
                        gif_path = os.path.join(folder_out, f)
                        score_result = load_score_sidecar(gif_path)
                        if score_result and score_result.get("score", 0) <= threshold:
                            try:
                                safe_delete(gif_path)
                                trashed_count += 1
                                # Also trash sidecar if it exists
                                sidecar = gif_path + ".scores.json"
                                if os.path.exists(sidecar):
                                    safe_delete(sidecar)
                                    
                                # Remove from UI list (must be on main thread)
                                def _remove_from_ui(p=gif_path):
                                    for iid, data in list(self._converted_data.items()):
                                        if data["path"] == p:
                                            self._converted_paths.discard(p)
                                            del self._converted_data[iid]
                                            if self._tree_converted.exists(iid):
                                                self._tree_converted.delete(iid)
                                    self._update_converted_count()
                                    self._update_statistics()
                                    
                                self.after(0, _remove_from_ui)
                            except Exception as e:
                                self.after(0, lambda err=e: self._log(f"Failed to trash: {err}", "warning"))
                                
                self.after(0, lambda c=trashed_count: self._log(f"✅  Auto-Cleanup removed {c} bad conversions."))
            except ValueError:
                self.after(0, lambda: self._log("⚠️  Invalid Auto-Trash percentage. Skipping cleanup.", "warning"))

        self.after(0, lambda: self._log("✅  Batch folder done."))
        self.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self._btn_convert, self._btn_all, self._btn_batch):
            btn.configure(state=state)
        for btn in (self._btn_all_prev, self._btn_src, self._btn_auto, self._btn_dmd):
            if hasattr(self, "_btn_src"):
                btn.configure(state=state)
        if hasattr(self, "_btn_stop"):
            self._btn_stop.configure(state="normal" if busy else "disabled", text="⏹ Force Stop")
        self._status_lbl.configure(text="⏳  Converting…" if busy else "Ready")
        if not busy:
            self._progress.set(1.0)
            self.after(2500, lambda: self._progress.set(0))

    # ══════════════════════════════════════════════════════════════════════════
    #  LOG
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_global_logs(self):
        if hasattr(self, "toggle_log_panel"):
            self.toggle_log_panel()

    def _log(self, message, level="info"):
        if not hasattr(self, "_log_box"):
            return
            
        levels = {"debug": 10, "info": 20, "warning": 30, "error": 40}
        msg_lvl = levels.get(level.lower(), 20)
        
        if not hasattr(self, "_all_logs"):
            self._all_logs = []
            
        self._all_logs.append((msg_lvl, message))
        
        current_lvl_str = getattr(self, "v_log_level", None)
        current_lvl = levels.get(current_lvl_str.get().lower(), 20) if current_lvl_str else 20
        
        if msg_lvl >= current_lvl:
            try:
                self._log_box.configure(state="normal")
                self._log_box.insert("end", message + "\n")
                self._log_box.configure(state="disabled")
                self._log_box.see("end")
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

