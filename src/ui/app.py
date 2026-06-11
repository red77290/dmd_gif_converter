import os
import sys
import threading
import logging
import platform
import shutil
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import customtkinter as ctk

# Suppress [mp3float @ ...] Header missing messages from OpenCV/ffmpeg
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

from src.ui.models.application_state import ApplicationState
from src.ui.events.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)

from src.ui.panels.left_panel import LeftPanel
from src.ui.panels.middle_panel import MiddlePanel
from src.ui.preview.preview_panel import PreviewPanel
from src.ui.panels.ai_moments_panel import AiMomentsPanel

class DMDConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🎞️  DMD GIF Converter  v6.2.0")
        self.geometry("1300x920")
        self.minsize(980, 720)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.app_state = ApplicationState()
        self._build_ui()
        # Subscribe to log events
        EventBus.subscribe(EventType.CONVERSION_PROGRESS, self._on_log_event)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)  # log panel

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=(0, 5))

        self.tab_conversion = self.tabview.add("Conversion")
        self.tab_ai_moments = self.tabview.add("Moments")

        # ── Moments Tab ───────────────────────────────────────────────────────
        self.tab_ai_moments.grid_columnconfigure(0, weight=1)
        self.tab_ai_moments.grid_rowconfigure(0, weight=1)
        self.ai_moments_panel = AiMomentsPanel(self.tab_ai_moments, self.app_state)
        self.ai_moments_panel.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # ── Conversion Tab ────────────────────────────────────────────────────
        self.tab_conversion.grid_columnconfigure(0, weight=1)
        self.tab_conversion.grid_columnconfigure(1, weight=1)
        self.tab_conversion.grid_columnconfigure(2, weight=2)
        self.tab_conversion.grid_rowconfigure(0, weight=1)

        self.left_panel = LeftPanel(self.tab_conversion, self.app_state)
        self.middle_panel = MiddlePanel(self.tab_conversion, self.app_state)
        self.preview_panel = PreviewPanel(self.tab_conversion, self.app_state)

        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.middle_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        # Wire panels together: PreviewPanel owns conversion logic
        self.preview_panel.set_sibling_panels(self.left_panel, self.middle_panel)

        # Enable "Convert selected" button when a file is selected in LeftPanel
        def _on_selection_changed(payload):
            path = (payload or {}).get("path")
            if path and not self.preview_panel._busy:
                self.preview_panel._btn_convert.configure(state="normal")
            else:
                self.preview_panel._btn_convert.configure(state="disabled")
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, _on_selection_changed)

        # ── Log panel (bottom, retractable) ──────────────────────────────────
        self._all_logs: list = []          # (level_int, message) — full history
        self._log_visible: bool = True
        self._log_levels = {"debug": 10, "info": 20, "warning": 30, "error": 40}
        self.v_log_level = tk.StringVar(value="INFO")

        self._log_outer = ctk.CTkFrame(self, fg_color="#0a0a14", corner_radius=0)
        self._log_outer.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        self._log_outer.grid_columnconfigure(0, weight=1)

        # Header bar (always visible)
        log_header = ctk.CTkFrame(self._log_outer, fg_color="#0d0d1a", corner_radius=0)
        log_header.grid(row=0, column=0, sticky="ew")
        log_header.grid_columnconfigure(1, weight=1)

        self._btn_log_toggle = ctk.CTkButton(
            log_header, text="▼  Log", width=70, height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="transparent", hover_color="#1a1a2e",
            text_color="#556677", anchor="w",
            command=self.toggle_log_panel,
        )
        self._btn_log_toggle.grid(row=0, column=0, padx=(6, 4), pady=2, sticky="w")

        # Level filter dropdown
        ctk.CTkLabel(
            log_header, text="Filter:",
            font=ctk.CTkFont(size=10), text_color="#445566"
        ).grid(row=0, column=2, padx=(0, 2), pady=2)
        self._log_level_menu = ctk.CTkOptionMenu(
            log_header,
            variable=self.v_log_level,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            width=90, height=22,
            font=ctk.CTkFont(size=10),
            command=self._on_log_level_change,
        )
        self._log_level_menu.grid(row=0, column=3, padx=(0, 4), pady=2)

        ctk.CTkButton(
            log_header, text="Clear", width=46, height=22,
            font=ctk.CTkFont(size=10), fg_color="#2a2a3a", hover_color="#e74c3c",
            command=self._clear_log,
        ).grid(row=0, column=4, padx=(0, 6), pady=2)

        # Collapsible body
        self._log_body = ctk.CTkFrame(self._log_outer, fg_color="transparent")
        self._log_body.grid(row=1, column=0, sticky="ew")

        self._log_box = ctk.CTkTextbox(
            self._log_body, height=90,
            font=ctk.CTkFont(family="Courier", size=11),
            fg_color="#0a0a14", text_color="#8899aa",
            state="disabled", wrap="word",
        )
        self._log_box.pack(fill="x", padx=6, pady=(2, 4))

    def _on_log_event(self, payload):
        if not payload or "log" not in payload:
            return
        msg = payload["log"]
        level = payload.get("level", "info").lower()
        level_int = self._log_levels.get(level, 20)
        self._all_logs.append((level_int, level, msg))
        # Only display if passes current filter
        current_min = self._log_levels.get(self.v_log_level.get().lower(), 20)
        if level_int >= current_min:
            self._append_log_line(msg, level)

    def _append_log_line(self, msg: str, level: str = "info"):
        colors = {"debug": "#445566", "info": "#8899aa",
                  "warning": "#f39c12", "error": "#e74c3c"}
        try:
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass

    def _on_log_level_change(self, _value=None):
        """Re-render the log box from full history using the new filter level."""
        current_min = self._log_levels.get(self.v_log_level.get().lower(), 20)
        try:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            for level_int, level, msg in self._all_logs:
                if level_int >= current_min:
                    self._log_box.insert("end", msg + "\n")
            self._log_box.configure(state="disabled")
            self._log_box.see("end")
        except Exception:
            pass

    def toggle_log_panel(self):
        """Show or hide the log body (retractable panel)."""
        if self._log_visible:
            self._log_body.grid_remove()
            self._btn_log_toggle.configure(text="▶  Log")
            self._log_visible = False
        else:
            self._log_body.grid()
            self._btn_log_toggle.configure(text="▼  Log")
            self._log_visible = True

    def _clear_log(self):
        self._all_logs.clear()
        try:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            self._log_box.configure(state="disabled")
        except Exception:
            pass

    def _on_close(self):
        EventBus.clear()
        self.destroy()

def main():
    import logging as _logging
    # Ensure terminal logs reach the console even when called directly
    # (not via launcher.py which already configures basicConfig).
    if not _logging.root.handlers:
        _logging.basicConfig(
            level=_logging.INFO,
            format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    app = DMDConverterApp()
    app.mainloop()

if __name__ == "__main__":
    main()
