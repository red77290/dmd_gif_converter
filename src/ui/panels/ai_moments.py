import os
import tkinter as tk
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog

class AiMomentsPanelMixin:
    def _build_ai_moments_panel(self, parent=None):
        parent = parent or self
        
        # Split into left configuration column and right results column
        parent.grid_columnconfigure(0, weight=0, minsize=350)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # ── Left Column: Configuration ───────────────────────────────────────
        cfg_frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        cfg_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # Section 1 - Video Selection
        self._build_ai_video_selection(cfg_frame)
        
        # Section 2 - Detection Settings
        self._build_ai_detection_settings(cfg_frame)
        
        # Section 3 - Analysis Strategy
        self._build_ai_analysis_strategy(cfg_frame)
        
        # Section 4 - Generation Settings
        self._build_ai_generation_settings(cfg_frame)
        
        # Start Button
        self._btn_ai_start = ctk.CTkButton(
            cfg_frame, text="Generate AI Moments", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._on_generate_ai_moments
        )
        self._btn_ai_start.pack(fill="x", pady=(20, 5))
        
        # Show Report Button
        self._btn_ai_show_report = ctk.CTkButton(
            cfg_frame, text="📊 Show AI Report", height=40,
            fg_color="#444", hover_color="#555",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._show_ai_report_popup,
            state="disabled"
        )
        self._btn_ai_show_report.pack(fill="x", pady=(0, 20))
        
        # ── Right Column: Studio Timeline ────────────────────────────────────
        res_frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="black")
        res_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self._build_studio_timeline(res_frame)

    def _build_ai_video_selection(self, parent):
        f = ctk.CTkFrame(parent)
        f.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(f, text="Section 1 - Video Selection", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        self._ai_video_label = ctk.CTkLabel(f, text="No video selected", text_color="gray")
        self._ai_video_label.pack(anchor="w", padx=10)
        
        self._ai_video_meta = ctk.CTkLabel(f, text="Duration: -- | Resolution: --", text_color="gray")
        self._ai_video_meta.pack(anchor="w", padx=10)
        
        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkButton(btn_row, text="Select Video", command=self._ai_select_video).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_row, text="Use Current Video", command=self._ai_use_current_video, fg_color="#444").pack(side="left")

    def _build_ai_detection_settings(self, parent):
        f = ctk.CTkFrame(parent)
        f.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(f, text="Section 2 - Detection Settings", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(row, text="Moments to Generate").pack(side="left")
        self.v_ai_moments_count = tk.StringVar(value="10")
        ctk.CTkOptionMenu(row, variable=self.v_ai_moments_count, values=["3", "5", "10", "20", "50"], width=80).pack(side="right")
        
        # Chips
        ctk.CTkLabel(f, text="Detection Criteria").pack(anchor="w", padx=10)
        chip_frame = ctk.CTkFrame(f, fg_color="transparent")
        chip_frame.pack(fill="x", padx=10, pady=5)
        
        self.v_ai_crit_action = tk.BooleanVar(value=True)
        self.v_ai_crit_epic = tk.BooleanVar(value=True)
        self.v_ai_crit_character = tk.BooleanVar(value=False)
        self.v_ai_crit_loopable = tk.BooleanVar(value=True)
        self.v_ai_crit_dmd = tk.BooleanVar(value=True)
        
        from src.ui.widgets import CTkChip
        CTkChip(chip_frame, text="Action", variable=self.v_ai_crit_action).grid(row=0, column=0, padx=5, pady=5)
        CTkChip(chip_frame, text="Epic", variable=self.v_ai_crit_epic).grid(row=0, column=1, padx=5, pady=5)
        CTkChip(chip_frame, text="Character", variable=self.v_ai_crit_character).grid(row=0, column=2, padx=5, pady=5)
        CTkChip(chip_frame, text="Loopable", variable=self.v_ai_crit_loopable).grid(row=1, column=0, padx=5, pady=5)
        CTkChip(chip_frame, text="DMD", variable=self.v_ai_crit_dmd).grid(row=1, column=1, padx=5, pady=5)

    def _build_ai_analysis_strategy(self, parent):
        f = ctk.CTkFrame(parent)
        f.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(f, text="Section 3 - Analysis Strategy", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        self.v_ai_strategy = tk.StringVar(value="Balanced")
        modes = ["Balanced", "Maximum Action", "Maximum DMD Visibility", "Loop Priority", "Custom"]
        
        for m in modes:
            ctk.CTkRadioButton(f, text=m, variable=self.v_ai_strategy, value=m, command=self._on_ai_strategy_change).pack(anchor="w", padx=10, pady=2)
            
        self._ai_custom_frame = ctk.CTkFrame(f, fg_color="transparent")
        
        self.v_ai_w_action = tk.DoubleVar(value=70)
        self.v_ai_w_epic = tk.DoubleVar(value=100)
        self.v_ai_w_character = tk.DoubleVar(value=40)
        self.v_ai_w_loopable = tk.DoubleVar(value=70)
        self.v_ai_w_dmd = tk.DoubleVar(value=100)
        
        weights = [
            ("Action", self.v_ai_w_action),
            ("Epic", self.v_ai_w_epic),
            ("Character", self.v_ai_w_character),
            ("Loopable", self.v_ai_w_loopable),
            ("DMD Visibility", self.v_ai_w_dmd),
        ]
        
        for i, (name, var) in enumerate(weights):
            lbl = ctk.CTkLabel(self._ai_custom_frame, text=name, width=100, anchor="w")
            lbl.grid(row=i, column=0, padx=5, pady=2)
            slider = ctk.CTkSlider(self._ai_custom_frame, from_=0, to=100, variable=var)
            slider.grid(row=i, column=1, padx=5, pady=2)
            
    def _on_ai_strategy_change(self):
        if self.v_ai_strategy.get() == "Custom":
            self._ai_custom_frame.pack(fill="x", padx=10, pady=10)
        else:
            self._ai_custom_frame.pack_forget()

    def _build_ai_generation_settings(self, parent):
        f = ctk.CTkFrame(parent)
        f.pack(fill="x", pady=(0, 10))
        
        ctk.CTkLabel(f, text="Section 4 - Generation Settings", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        self.v_ai_dur_min = tk.StringVar(value="2.0")
        self.v_ai_dur_max = tk.StringVar(value="5.0")
        
        ctk.CTkLabel(row, text="Duration Range (s):").pack(side="left")
        
        ctk.CTkLabel(row, text="Min", text_color="gray").pack(side="left", padx=(10, 5))
        ctk.CTkEntry(row, textvariable=self.v_ai_dur_min, width=50).pack(side="left")
        
        ctk.CTkLabel(row, text="Max", text_color="gray").pack(side="left", padx=(10, 5))
        ctk.CTkEntry(row, textvariable=self.v_ai_dur_max, width=50).pack(side="left")
        
        self.v_ai_auto_framing = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Auto Action Framing", variable=self.v_ai_auto_framing).pack(anchor="w", padx=10, pady=5)
        
        self.v_ai_opt_dmd = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Optimize for DMD", variable=self.v_ai_opt_dmd).pack(anchor="w", padx=10, pady=5)

    def _build_studio_timeline(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # 1. Huge Video Preview
        preview_container = ctk.CTkFrame(parent, fg_color="black")
        preview_container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        preview_container.grid_columnconfigure(0, weight=1)
        preview_container.grid_rowconfigure(0, weight=1)
        
        self._ai_studio_preview_lbl = tk.Label(preview_container, text="No Video Loaded", bg="black", fg="#555", font=("Arial", 24))
        self._ai_studio_preview_lbl.grid(row=0, column=0, sticky="nsew")
        
        # 2. Timeline Controls Frame
        controls_frame = ctk.CTkFrame(parent, fg_color="#1a1a1a", height=100)
        controls_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        controls_frame.grid_columnconfigure(1, weight=1)
        
        self.v_playhead = tk.DoubleVar(value=0.0)
        self.v_manual_start = tk.DoubleVar(value=0.0)
        self.v_manual_end = tk.DoubleVar(value=5.0)
        
        # Scrubber
        self._lbl_playhead = ctk.CTkLabel(controls_frame, text="00:00.0", width=60, font=ctk.CTkFont(family="monospace", size=14))
        self._lbl_playhead.grid(row=0, column=0, padx=(15, 5), pady=15)
        
        self._sl_playhead = ctk.CTkSlider(controls_frame, variable=self.v_playhead, from_=0, to=100, command=self._on_playhead_change)
        self._sl_playhead.grid(row=0, column=1, sticky="ew", padx=10, pady=15)
        
        # Tools row
        tools_row = ctk.CTkFrame(controls_frame, fg_color="transparent")
        tools_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 15))
        tools_row.grid_columnconfigure(2, weight=1)
        
        btn_in = ctk.CTkButton(tools_row, text="[ Set IN Point", font=ctk.CTkFont(weight="bold"), width=120, height=32, command=self._set_in_point, fg_color="#C25A24", hover_color="#9A451A")
        btn_in.grid(row=0, column=0, padx=5)
        
        btn_out = ctk.CTkButton(tools_row, text="Set OUT Point ]", font=ctk.CTkFont(weight="bold"), width=120, height=32, command=self._set_out_point, fg_color="#2471A3", hover_color="#1A5276")
        btn_out.grid(row=0, column=1, sticky="w", padx=5)
        
        self._lbl_selection = ctk.CTkLabel(tools_row, text="Selected: 00.0s — 05.0s", text_color="#F1C40F", font=ctk.CTkFont(family="monospace", weight="bold", size=14))
        self._lbl_selection.grid(row=0, column=2, padx=15)
        
        self._is_playing_selection = False
        self._btn_play_selection = ctk.CTkButton(tools_row, text="▶ Play Selection", width=140, fg_color="#2b4b8a", hover_color="#234073", height=36, command=self._toggle_play_selection)
        self._btn_play_selection.grid(row=0, column=3, padx=5)
        
        self._btn_add_manual = ctk.CTkButton(tools_row, text="✂️ Add Manual Moment", fg_color="#2FA572", hover_color="#1E7A52", height=36, command=self._on_add_manual_moment)
        self._btn_add_manual.grid(row=0, column=4, padx=5)

    def _on_playhead_change(self, val):
        self._lbl_playhead.configure(text=f"{val:05.1f}s")
        self._update_studio_preview(val)
        
    def _set_in_point(self):
        val = self.v_playhead.get()
        if val >= self.v_manual_end.get():
            self.v_manual_end.set(val + 1.0)
        self.v_manual_start.set(val)
        self._lbl_selection.configure(text=f"Selected: {self.v_manual_start.get():04.1f}s — {self.v_manual_end.get():04.1f}s")
        
    def _set_out_point(self):
        val = self.v_playhead.get()
        if val <= self.v_manual_start.get():
            self.v_manual_start.set(max(0.0, val - 1.0))
        self.v_manual_end.set(val)
        self._lbl_selection.configure(text=f"Selected: {self.v_manual_start.get():04.1f}s — {self.v_manual_end.get():04.1f}s")

    def _update_studio_preview(self, time_sec):
        if not getattr(self, '_ai_preview_cap', None):
            return
            
        import cv2
        from PIL import Image, ImageTk
        
        try:
            self._ai_preview_cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
            ret, frame = self._ai_preview_cap.read()
            if ret:
                # Resize to fit the label (max ~800x450)
                h, w = frame.shape[:2]
                target_w, target_h = 800, 450
                ratio = min(target_w/w, target_h/h)
                new_w, new_h = int(w*ratio), int(h*ratio)
                frame = cv2.resize(frame, (new_w, new_h))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                img = Image.fromarray(frame)
                imgtk = ImageTk.PhotoImage(image=img)
                self._ai_studio_preview_lbl.imgtk = imgtk
                self._ai_studio_preview_lbl.configure(image=imgtk, width=new_w, height=new_h)
        except Exception:
            pass
            
    def _toggle_play_selection(self):
        if not hasattr(self, '_ai_preview_cap') or not self._ai_preview_cap:
            return
            
        if self._is_playing_selection:
            self._is_playing_selection = False
            self._btn_play_selection.configure(text="▶ Play Selection", fg_color="#2b4b8a", hover_color="#234073")
        else:
            self._is_playing_selection = True
            self._btn_play_selection.configure(text="⏸ Pause", fg_color="#8a2b2b", hover_color="#732323")
            # Restart playhead from IN point
            self.v_playhead.set(self.v_manual_start.get())
            self._on_playhead_change(self.v_playhead.get())
            
            import cv2
            fps = self._ai_preview_cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0: fps = 25.0
            delay_ms = int(1000 / fps)
            self.after(delay_ms, self._play_loop, delay_ms)
            
    def _play_loop(self, delay_ms):
        if not self._is_playing_selection:
            return
            
        current = self.v_playhead.get()
        # Advance by delay
        next_time = current + (delay_ms / 1000.0)
        
        if next_time >= self.v_manual_end.get():
            # Loop back to IN point
            next_time = self.v_manual_start.get()
            
        self.v_playhead.set(next_time)
        self._on_playhead_change(next_time)
        
        self.after(delay_ms, self._play_loop, delay_ms)
            
    def _on_add_manual_moment(self):
        if not hasattr(self, '_ai_video_path') or not self._ai_video_path:
            import tkinter.messagebox as msg
            msg.showwarning("No Video", "Please select a video first.")
            return
            
        start = self.v_manual_start.get()
        end = self.v_manual_end.get()
        
        if end <= start:
            import tkinter.messagebox as msg
            msg.showwarning("Invalid Range", "End time must be greater than start time.")
            return
            
        from src.auto_action.ai_moments import AiMoment
        m = AiMoment(
            start_time=start,
            end_time=end,
            start_frame=0,
            end_frame=0,
            scores={"Manual": 100},
            overall_score=100.0
        )
        
        # Append to current results (but don't force UI update on hidden popup)
        if not hasattr(self, '_ai_results'):
            self._ai_results = []
        self._ai_results.append(m)
        
        # Add to extraction queue (this pushes it to the main left-panel treeview)
        self._add_moments_to_queue([m])

    def _show_ai_report_popup(self, mode="results"):
        if getattr(self, "_report_popup", None) and self._report_popup.winfo_exists():
            self._report_popup.focus()
            if mode == "results":
                self._show_ai_results_view()
            else:
                self._show_ai_analysis_view()
            return
            
        self._report_popup = ctk.CTkToplevel(self)
        self._report_popup.title("AI Moments Report")
        self._report_popup.geometry("600x600")
        self._report_popup.transient(self.winfo_toplevel())
        
        self._ai_right_container = ctk.CTkFrame(self._report_popup, fg_color="transparent")
        self._ai_right_container.pack(fill="both", expand=True, padx=10, pady=10)
        self._ai_right_container.grid_columnconfigure(0, weight=1)
        self._ai_right_container.grid_rowconfigure(0, weight=1)
        
        # --- Analysis View ---
        self._ai_analysis_view = ctk.CTkFrame(self._ai_right_container, fg_color="transparent")
        self._ai_analysis_view.grid(row=0, column=0, sticky="nsew")
        self._ai_analysis_view.grid_remove() # hidden by default
        
        lbl = ctk.CTkLabel(self._ai_analysis_view, text="Analyzing...", font=ctk.CTkFont(size=24, weight="bold"))
        lbl.pack(pady=(40, 20))
        
        self._ai_progress_bar = ctk.CTkProgressBar(self._ai_analysis_view, width=400)
        self._ai_progress_bar.set(0)
        self._ai_progress_bar.pack(pady=10)
        
        self._ai_progress_lbl = ctk.CTkLabel(self._ai_analysis_view, text="0%", font=ctk.CTkFont(size=16))
        self._ai_progress_lbl.pack(pady=(0, 20))
        
        # Detailed Progress List
        self._ai_tasks_frame = ctk.CTkFrame(self._ai_analysis_view, fg_color="transparent")
        self._ai_tasks_frame.pack(pady=10)
        
        self._ai_task_vars = {}
        tasks = [
            "Scene Detection",
            "Subject Detection",
            "Motion Analysis",
            "DMD Analysis",
            "Ranking Moments"
        ]
        for t in tasks:
            var = tk.StringVar(value="[ ]")
            self._ai_task_vars[t] = var
            row = ctk.CTkFrame(self._ai_tasks_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, textvariable=var, width=30, font=ctk.CTkFont(family="Courier")).pack(side="left")
            ctk.CTkLabel(row, text=t).pack(side="left", padx=10)
        
        # --- Results View ---
        self._ai_results_view = ctk.CTkFrame(self._ai_right_container, fg_color="transparent")
        self._ai_results_view.grid(row=0, column=0, sticky="nsew")
        self._ai_results_view.grid_columnconfigure(0, weight=1)
        self._ai_results_view.grid_rowconfigure(0, weight=1)
        
        self._ai_results_scroll = ctk.CTkScrollableFrame(self._ai_results_view, height=400)
        self._ai_results_scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self._ai_results_scroll.grid_columnconfigure(0, weight=1)
        
        self._ai_empty_lbl = ctk.CTkLabel(self._ai_results_scroll, text="Select a video and generate AI moments.", text_color="gray")
        self._ai_empty_lbl.pack(pady=50)
        
        if mode == "results":
            self._show_ai_results_view()
        else:
            self._show_ai_analysis_view()

    def _show_ai_analysis_view(self):
        if hasattr(self, '_ai_results_view'):
            self._ai_results_view.grid_remove()
        if hasattr(self, '_ai_analysis_view'):
            self._ai_analysis_view.grid(row=0, column=0, sticky="nsew")
        
    def _show_ai_results_view(self):
        if hasattr(self, '_ai_analysis_view'):
            self._ai_analysis_view.grid_remove()
        if hasattr(self, '_ai_results_view'):
            self._ai_results_view.grid(row=0, column=0, sticky="nsew")

    # ── Callbacks ────────────────────────────────────────────────────────────
    def _ai_select_video(self):
        path = filedialog.askopenfilename(
            title="Select Video for AI Analysis",
            filetypes=[("Video/GIF", "*.mp4 *.mkv *.mov *.avi *.webm *.gif"), ("All", "*.*")]
        )
        if path:
            self._ai_set_video(path)

    def _ai_use_current_video(self):
        # We need to get the currently selected video from the left panel's treeview
        if hasattr(self, "_selected_iid") and self._selected_iid:
            path = self._file_data.get(self._selected_iid)
            if path:
                self._ai_set_video(path)
                return
        import tkinter.messagebox as msg
        msg.showwarning("No Video", "Please select a video in the Conversion tab first.")

    def _ai_set_video(self, path):
        self._ai_video_path = path
        name = Path(path).name
        self._ai_video_label.configure(text=name, text_color="white")
        
        # Load VideoCapture for preview
        import cv2
        if getattr(self, '_ai_preview_cap', None):
            self._ai_preview_cap.release()
        self._ai_preview_cap = cv2.VideoCapture(path)
        
        from src.converter.ffmpeg_utils import get_metadata
        _, _, _, dur = get_metadata(path)
        if dur > 0:
            self._ai_video_meta.configure(text=f"Ready to analyze | Duration: {dur:.1f}s")
            
            # Configure playhead
            self._sl_playhead.configure(to=dur)
            self.v_playhead.set(0.0)
            
            if dur > 5.0:
                self.v_manual_start.set(0.0)
                self.v_manual_end.set(5.0)
            else:
                self.v_manual_start.set(0.0)
                self.v_manual_end.set(dur)
            self._lbl_selection.configure(text=f"Selected: {self.v_manual_start.get():04.1f}s — {self.v_manual_end.get():04.1f}s")
        else:
            self._ai_video_meta.configure(text=f"Ready to analyze")
            
        # Update preview with start time
        self.after(100, lambda: self._update_studio_preview(self.v_playhead.get()))

    def _on_generate_ai_moments(self):
        if not hasattr(self, '_ai_video_path') or not self._ai_video_path:
            import tkinter.messagebox as msg
            msg.showwarning("No Video", "Please select a video first.")
            return
            
        self._show_ai_report_popup(mode="analysis")
        
        self._btn_ai_start.configure(state="disabled")
        self._btn_ai_show_report.configure(state="disabled")
        self._ai_progress_bar.set(0)
        self._ai_progress_lbl.configure(text="0%")
        for var in self._ai_task_vars.values():
            var.set("[ ]")
            
        options = {
            "moments_count": int(self.v_ai_moments_count.get()),
            "crit_action": self.v_ai_crit_action.get(),
            "crit_epic": self.v_ai_crit_epic.get(),
            "crit_character": self.v_ai_crit_character.get(),
            "crit_loopable": self.v_ai_crit_loopable.get(),
            "crit_dmd": self.v_ai_crit_dmd.get(),
            "strategy": self.v_ai_strategy.get(),
            "w_action": self.v_ai_w_action.get(),
            "w_epic": self.v_ai_w_epic.get(),
            "w_character": self.v_ai_w_character.get(),
            "w_loopable": self.v_ai_w_loopable.get(),
            "w_dmd": self.v_ai_w_dmd.get(),
            "dur_min": float(self.v_ai_dur_min.get() or 2.0),
            "dur_max": float(self.v_ai_dur_max.get() or 5.0),
            "auto_framing": self.v_ai_auto_framing.get(),
            "opt_dmd": self.v_ai_opt_dmd.get()
        }
        
        # Trigger analysis thread
        import threading
        threading.Thread(target=self._run_ai_analysis, args=(options,), daemon=True).start()

    def _run_ai_analysis(self, options):
        from src.auto_action.ai_moments import AiMomentsEngine
        
        # Helper to safely update UI from thread
        def progress_cb(task_name: str, progress: float):
            self.after(0, lambda: self._update_ai_progress(task_name, progress))
            
        self._ai_engine = AiMomentsEngine(self._ai_video_path, options, progress_cb)
        results = self._ai_engine.run()
        
        # Finish
        self.after(100, lambda: self._on_ai_analysis_complete(results))

    def _update_ai_progress(self, task_name: str, progress: float):
        self._ai_progress_bar.set(progress)
        self._ai_progress_lbl.configure(text=f"{int(progress * 100)}%")
        
        for t, var in self._ai_task_vars.items():
            if t == task_name:
                var.set("[-]")
            elif progress == 1.0 or list(self._ai_task_vars.keys()).index(t) < list(self._ai_task_vars.keys()).index(task_name):
                var.set("[✓]")
    def _on_ai_analysis_complete(self, results):
        self._ai_results = results
        self._btn_ai_show_report.configure(state="normal")
        
        self._show_ai_report_popup(mode="results")
        self._populate_results()
        
        # Add moments directly to the conversion queue
        if results:
            self._add_moments_to_queue(results)

    def _populate_results(self):
        import customtkinter as ctk
        
        # Clear old results
        if not hasattr(self, '_ai_result_widgets'):
            self._ai_result_widgets = []
            
        for widget in self._ai_result_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._ai_result_widgets.clear()
        
        # Also hide the empty placeholder if it exists
        if hasattr(self, '_ai_empty_lbl') and self._ai_empty_lbl.winfo_exists():
            self._ai_empty_lbl.pack_forget()
            
        # Add result cards (Inline Report)
        if not hasattr(self, '_ai_results') or not self._ai_results:
            lbl = ctk.CTkLabel(self._ai_results_scroll, text="No moments found.", text_color="gray")
            lbl.pack(pady=50)
            self._ai_result_widgets.append(lbl)
            return
            
        for i, m in enumerate(self._ai_results):
            card = ctk.CTkFrame(self._ai_results_scroll)
            card.pack(fill="x", pady=5, padx=5)
            self._ai_result_widgets.append(card)
            
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=10, pady=5)
            
            def format_time(s):
                return f"{int(s//60):02d}:{int(s%60):02d}"
                
            time_str = f"[{format_time(m.start_time)} → {format_time(m.end_time)}]"
            ctk.CTkLabel(header, text=f"Moment #{i+1} {time_str}", font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(header, text=f"Score: {int(m.overall_score)}", font=ctk.CTkFont(weight="bold"), text_color="#2FA572").pack(side="right")
            
            metrics_frame = ctk.CTkFrame(card, fg_color="transparent")
            metrics_frame.pack(fill="x", padx=10, pady=(0, 5))
            
            metrics_text = " | ".join([f"{k}: {int(v)}" for k, v in m.scores.items()])
            ctk.CTkLabel(metrics_frame, text=metrics_text, font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")

    def _add_moments_to_queue(self, results):
        from pathlib import Path
        import threading
        import subprocess
        import os
        
        if hasattr(self, '_btn_ai_start'):
            self._btn_ai_start.configure(state="disabled")
            
        if hasattr(self, '_btn_add_manual'):
            self._btn_add_manual.configure(state="disabled", text="Extracting...")
            
        if getattr(self, "_report_popup", None) and self._report_popup.winfo_exists() and hasattr(self, '_ai_progress_lbl'):
            self._ai_progress_lbl.configure(text="Extracting moments to temporary files...")
            self._ai_progress_bar.set(0.1)
        
        src_path = self._ai_video_path
        src_dir = Path(src_path).parent
        tmp_dir = src_dir / "ai_moments_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        
        def _extract():
            new_files = []
            total = len(results)
            base_name = Path(src_path).stem
            ext = Path(src_path).suffix
            
            for i, m in enumerate(results):
                if "Manual" in m.scores:
                    out_name = f"{base_name}_Manual_{int(m.start_time)}s_to_{int(m.end_time)}s{ext}"
                else:
                    out_name = f"{base_name}_M{i+1}{ext}"
                out_path = tmp_dir / out_name
                
                # Use ffmpeg to cut the moment
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(m.start_time),
                    "-i", src_path,
                    "-to", str(m.end_time - m.start_time),
                    "-c", "copy",
                    str(out_path)
                ]
                
                try:
                    subprocess.run(cmd, capture_output=True, check=True)
                    if out_path.exists():
                        new_files.append(str(out_path))
                except Exception as e:
                    print(f"Failed to extract moment {i+1}: {e}")
                    
                if getattr(self, "_report_popup", None) and self._report_popup.winfo_exists() and hasattr(self, '_ai_progress_bar'):
                    self.after(0, lambda p=(i+1)/total: self._ai_progress_bar.set(0.1 + p * 0.9))
                
            self.after(0, lambda: _finish(new_files))
            
        def _finish(files):
            if files and hasattr(self, '_batch_insert'):
                self._batch_insert(files, 0)
                
            if getattr(self, "_report_popup", None) and self._report_popup.winfo_exists() and hasattr(self, '_ai_progress_lbl'):
                self._ai_progress_lbl.configure(text=f"Added {len(files)} extracted moments to the Conversion list!")
                self._ai_progress_bar.set(1.0)
                
            if hasattr(self, '_btn_ai_start'):
                self._btn_ai_start.configure(state="normal")
                
            if hasattr(self, '_btn_add_manual'):
                self._btn_add_manual.configure(state="normal", text="✂️ Add Manual Moment")
            
        threading.Thread(target=_extract, daemon=True).start()
