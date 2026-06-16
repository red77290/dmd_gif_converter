import tkinter as tk
import customtkinter as ctk

class LogConsole(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="#0a0a14", corner_radius=0, **kwargs)
        
        self._all_logs = []
        self._log_visible = True
        self._log_levels = {"debug": 10, "info": 20, "warning": 30, "error": 40}
        self.v_log_level = tk.StringVar(value="INFO")
        
        self.grid_columnconfigure(0, weight=1)
        
        # Header bar
        log_header = ctk.CTkFrame(self, fg_color="#0d0d1a", corner_radius=0)
        log_header.grid(row=0, column=0, sticky="ew")
        log_header.grid_columnconfigure(2, weight=1)
        
        self._btn_log_toggle = ctk.CTkButton(
            log_header, text="▼  Log", width=70, height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="transparent", hover_color="#1a1a2e",
            text_color="#556677", anchor="w",
            command=self.toggle_log_panel,
        )
        self._btn_log_toggle.grid(row=0, column=0, padx=(6, 4), pady=2, sticky="w")

        # Drag handle (Sash)
        self._sash = ctk.CTkFrame(log_header, width=50, height=6, fg_color="#334455", corner_radius=3, cursor="sb_v_double_arrow")
        self._sash.grid(row=0, column=1, padx=(10, 10), pady=4)
        self._sash.bind("<B1-Motion>", self._on_sash_drag)
        self._sash.bind("<Button-1>", self._on_sash_press)
        
        ctk.CTkLabel(log_header, text="Filter:", font=ctk.CTkFont(size=10), text_color="#445566").grid(row=0, column=3, padx=(0, 2), pady=2)
        self._log_level_menu = ctk.CTkOptionMenu(
            log_header, variable=self.v_log_level, values=["DEBUG", "INFO", "WARNING", "ERROR"],
            width=90, height=22, font=ctk.CTkFont(size=10), command=self._on_log_level_change
        )
        self._log_level_menu.grid(row=0, column=4, padx=(0, 4), pady=2)
        
        ctk.CTkButton(
            log_header, text="Clear", width=46, height=22,
            font=ctk.CTkFont(size=10), fg_color="#2a2a3a", hover_color="#e74c3c", command=self._clear_log
        ).grid(row=0, column=5, padx=(0, 6), pady=2)
        
        # Collapsible body
        self._log_body = ctk.CTkFrame(self, fg_color="transparent")
        self._log_body.grid(row=1, column=0, sticky="ew")
        
        self._console_height = 250
        
        self._log_box = ctk.CTkTextbox(
            self._log_body, height=self._console_height,
            font=ctk.CTkFont(family="Courier", size=11),
            fg_color="#0a0a14", text_color="#8899aa",
            state="disabled", wrap="word",
        )
        self._log_box.pack(fill="x", padx=6, pady=(2, 4))
        
        # Make the textbox itself expandable too if the app resizes
        self._log_body.pack_propagate(False)
        self._log_body.configure(height=self._console_height + 10)
        self._log_box.pack(expand=True, fill="both")
        
        self._drag_start_y = 0
        self._drag_start_h = 0
        
        # Hide by default
        self.toggle_log_panel()

    def _on_sash_press(self, event):
        self._drag_start_y = event.y_root
        self._drag_start_h = self._console_height
        
    def _on_sash_drag(self, event):
        if not self._log_visible:
            return
        delta = self._drag_start_y - event.y_root  # Pulling UP increases height
        new_h = max(30, min(800, self._drag_start_h + delta))
        self._console_height = new_h
        self._log_body.configure(height=new_h + 10)
        self._log_box.configure(height=new_h)
        
    def process_log_event(self, payload):
        if not payload or "log" not in payload:
            return
        msg = payload["log"]
        level = payload.get("level", "info").lower()
        level_int = self._log_levels.get(level, 20)
        self._all_logs.append((level_int, level, msg))
        current_min = self._log_levels.get(self.v_log_level.get().lower(), 20)
        if level_int >= current_min:
            self._append_log_line(msg, level)
            
    def _append_log_line(self, msg: str, level: str = "info"):
        if "[AI MOMENT]" in msg:
            self._render_ai_moment(msg)
            return

        try:
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass
        
    def _render_ai_moment(self, msg: str):
        # Remove the tag from the output visually but keep it highlighted
        clean_msg = msg.replace("[AI MOMENT]", "").strip()
        try:
            self._log_box.configure(state="normal")
            
            # Use visual blocks for AI logs
            prefix = "⚡ "
            if "processing frame" in clean_msg.lower():
                prefix = "⏳ "
            elif "detected" in clean_msg.lower() or "score" in clean_msg.lower():
                prefix = "🎯 "
            elif "error" in clean_msg.lower():
                prefix = "❌ "
                
            self._log_box.insert("end", f"{prefix}{clean_msg}\n", "ai_tag")
            self._log_box.tag_config("ai_tag", foreground="#88ddff", font=ctk.CTkFont(family="Courier", size=11, weight="bold"))
            
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass

    def _on_log_level_change(self, _value=None):
        current_min = self._log_levels.get(self.v_log_level.get().lower(), 20)
        try:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            for level_int, level, msg in self._all_logs:
                if level_int >= current_min:
                    self._append_log_line(msg, level)
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass

    def toggle_log_panel(self):
        if self._log_visible:
            self._log_body.grid_remove()
            self._btn_log_toggle.configure(text="▶  Log")
            self._log_visible = False
        else:
            self._log_body.grid()
            self._btn_log_toggle.configure(text="▼  Log")
            self._log_visible = True

    def clear_log(self):
        self._clear_log()
        
    def _clear_log(self):
        self._all_logs.clear()
        try:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            self._log_box.configure(state="disabled")
        except Exception:
            pass
