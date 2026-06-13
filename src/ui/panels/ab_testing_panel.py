import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from src.engine.testing.ab_testing_engine import ABTestingEngine
from src.engine.conversion import DEFAULT_PARAMS
from src.engine.scoring.final_scoring_engine import BUILTIN_STRATEGIES

class ABTestingPanel(ctk.CTkFrame):
    """
    A dedicated panel for A/B testing Scoring V2 strategies on a selected video.
    """
    def __init__(self, master, available_strategies=None, **kwargs):
        super().__init__(master, **kwargs)
        
        self.available_strategies = available_strategies or list(BUILTIN_STRATEGIES.keys())
        self.selected_file = tk.StringVar(value="")
        
        self._build_ui()
        
    def _build_ui(self):
        # Title
        title = ctk.CTkLabel(self, text="A/B Testing (Scoring V2)", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(20, 10), padx=20, anchor="w")
        
        desc = ctk.CTkLabel(self, text="Compare how different scoring strategies evaluate a video.", text_color="gray")
        desc.pack(padx=20, anchor="w")
        
        # File Selection
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(file_frame, text="Target Video:").pack(side="left")
        self.lbl_file = ctk.CTkLabel(file_frame, textvariable=self.selected_file, text_color="cyan", width=300, anchor="w")
        self.lbl_file.pack(side="left", padx=10, fill="x", expand=True)
        
        btn_browse = ctk.CTkButton(file_frame, text="Browse...", width=100, command=self._browse_file)
        btn_browse.pack(side="right")
        
        # Strategies Selection
        strat_frame = ctk.CTkFrame(self)
        strat_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(strat_frame, text="Select Strategies to Compare:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        
        self.strat_vars = {}
        for strat in self.available_strategies:
            var = tk.BooleanVar(value=True if strat in ("baseline_v1", "balanced_v2") else False)
            chk = ctk.CTkCheckBox(strat_frame, text=strat, variable=var)
            chk.pack(anchor="w", padx=20, pady=5)
            self.strat_vars[strat] = var
            
        # Run Button
        self.btn_run = ctk.CTkButton(self, text="Run A/B Test", command=self._run_test, height=40, font=ctk.CTkFont(weight="bold"))
        self.btn_run.pack(pady=20, padx=20, fill="x")
        
        # Results Area
        self.txt_results = ctk.CTkTextbox(self, height=200, font=ctk.CTkFont(family="Courier", size=12))
        self.txt_results.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.txt_results.insert("1.0", "Leaderboard will appear here...\n")
        self.txt_results.configure(state="disabled")

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="Select Video for A/B Testing",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv *.gif")]
        )
        if f:
            self.selected_file.set(f)

    def _run_test(self):
        video_path = self.selected_file.get()
        if not video_path or not os.path.exists(video_path):
            messagebox.showerror("Error", "Please select a valid video file.")
            return
            
        strategies = [s for s, var in self.strat_vars.items() if var.get()]
        if len(strategies) < 2:
            messagebox.showwarning("Warning", "Select at least 2 strategies to compare.")
            return
            
        self.btn_run.configure(state="disabled", text="Running Test...")
        self.txt_results.configure(state="normal")
        self.txt_results.delete("1.0", tk.END)
        self.txt_results.insert(tk.END, f"Extracting signals from {os.path.basename(video_path)}...\nThis may take a minute...\n")
        self.txt_results.configure(state="disabled")
        
        threading.Thread(target=self._test_thread, args=(video_path, strategies), daemon=True).start()
        
    def _test_thread(self, video_path, strategies):
        try:
            from src.plugins.detectors.detector import DetectorFactory
            detector = DetectorFactory.create_detector()
            
            engine = ABTestingEngine(
                video_path=video_path, 
                target_w=int(DEFAULT_PARAMS["target_width"]), 
                target_h=int(DEFAULT_PARAMS["target_height"]),
                detector=detector,
                use_optical_flow=True
            )
            report = engine.run(strategy_names=strategies)
            
            # Format leaderboard for Textbox
            lines = []
            lines.append("="*60)
            lines.append(f"A/B TEST LEADERBOARD — {os.path.basename(video_path)}")
            lines.append("="*60)
            
            ranked = sorted(
                report.composite_scores.items(), key=lambda x: x[1], reverse=True
            )
            
            for idx, (name, score) in enumerate(ranked):
                r = report.results.get(name)
                is_winner = " ← WINNER" if name == report.best_strategy else ""
                lines.append(f"{idx+1}. {name:<20} composite={score:.1f} | readability={r.avg_readability if r else 0.0:.1f} | stability={r.temporal_stability if r else 0.0:.1f} | selection={r.selection_rate*100 if r else 0.0:.0f}%{is_winner}")
                
            lines.append("="*60)
            result_text = "\n".join(lines)
            
            self.master.after(0, self._on_test_complete, result_text)
            
        except Exception as e:
            self.master.after(0, self._on_test_complete, f"Error running A/B Test:\n{str(e)}")
            
    def _on_test_complete(self, result_text):
        self.txt_results.configure(state="normal")
        self.txt_results.delete("1.0", tk.END)
        self.txt_results.insert(tk.END, result_text)
        self.txt_results.configure(state="disabled")
        self.btn_run.configure(state="normal", text="Run A/B Test")
