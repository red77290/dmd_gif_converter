import os
import sys
import threading
import logging
import platform
import shutil
import tkinter as tk
import queue
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import customtkinter as ctk

# Suppress [mp3float @ ...] Header missing messages from OpenCV/ffmpeg
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

from src.ui.models.application_state import ApplicationState
from src.ui.events.event_bus import EventBus, EventType
from src.ui.controllers.preview_controller import PreviewController

logger = logging.getLogger(__name__)

from src.ui.panels.left_panel import LeftPanel
from src.ui.panels.middle_panel import MiddlePanel
from src.ui.preview.preview_panel import PreviewPanel
from src.ui.panels.ai_moments_panel import AiMomentsPanel
from src.ui.panels.log_console import LogConsole

from src.ui.constants import APP_VERSION

class DMDConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"🎞️  DMD GIF Converter  v{APP_VERSION}")
        self.geometry("1300x920")
        self.minsize(980, 720)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.app_state = ApplicationState()
        self._build_ui()
        self._log_queue = queue.Queue()
        # Subscribe to log events
        EventBus.subscribe(EventType.CONVERSION_PROGRESS, self._on_log_event)
        self._poll_logs()

        # Log hardware acceleration on startup
        threading.Thread(target=self._log_startup_hw_accel, daemon=True).start()

    def _log_startup_hw_accel(self):
        try:
            from src.engine.conversion.hardware_accel import get_best_h264_encoder
            best = get_best_h264_encoder()
            if best != "libx264":
                logger.info(f"[HW_ACCEL] Hardware Acceleration Enabled: {best}")
            else:
                logger.info("[HW_ACCEL] Hardware Acceleration: CPU only (libx264)")
        except Exception:
            pass

    def _poll_logs(self):
        try:
            while True:
                payload = self._log_queue.get_nowait()
                self._process_log_event(payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_logs)

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
        self.preview_controller = PreviewController()
        self.preview_controller.bind(self.preview_panel, self.app_state)
        
        # Trigger auto-refresh for visual parameters
        refresh_vars = [
            "v_target_width", "v_target_height",
            "v_text_overlay_enabled", "v_text_content", "v_text_font_size",
            "v_text_color", "v_text_position", "v_text_style", "v_text_animation",
            "v_text_bg", "v_text_bg_opacity", "v_text_font_file"
        ]
        for v_name in refresh_vars:
            var = getattr(self.app_state, v_name, None)
            if var:
                var.trace_add("write", lambda *_: self.preview_controller.schedule_refresh())

        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.middle_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.preview_panel.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        # Wire panels together: PreviewPanel owns conversion logic
        self.preview_panel.set_sibling_panels(self.left_panel, self.middle_panel)

        # Enable "Convert selected" button when a file is selected in LeftPanel
        def _on_selection_changed(payload):
            if self.left_panel._selected_iid:
                if not getattr(self.preview_panel, "_busy", False):
                    self.preview_panel.controls._btn_conv_sel.configure(state="normal")
            else:
                self.preview_panel.controls._btn_conv_sel.configure(state="disabled")
        
        def _cancel_debounce(*_):
            self.preview_controller._cancel_pending()
            
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, _cancel_debounce)
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, _on_selection_changed)

        # ── Log panel (bottom, retractable) ──────────────────────────────────
        self.log_console = LogConsole(self)
        self.log_console.grid(row=1, column=0, sticky="ew", padx=0, pady=0)

    def _on_log_event(self, payload):
        self._log_queue.put(payload)

    def _process_log_event(self, payload):
        self.log_console.process_log_event(payload)

    def _on_close(self):
        EventBus.clear()
        self.destroy()

class EventBusLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            EventBus.publish(EventType.CONVERSION_PROGRESS, {"log": msg, "level": record.levelname})
        except Exception:
            pass

class WorkerFormatter(logging.Formatter):
    def format(self, record):
        tname = record.threadName
        if tname == "MainThread":
            record.worker_id = "Main"
        elif "ThreadPoolExecutor" in tname:
            try:
                # "ThreadPoolExecutor-0_0" -> W1
                worker_num = int(tname.split("_")[-1]) + 1
                record.worker_id = f"W{worker_num}"
            except Exception:
                record.worker_id = "W?"
        else:
            record.worker_id = tname[:4]
        return super().format(record)

def main():
    import logging as _logging
    from pathlib import Path
    
    if not _logging.root.handlers:
        import platform
        if platform.system() == "Windows":
            log_dir = Path(os.environ.get("APPDATA", "~")) / "DMD_Converter"
        else:
            log_dir = Path.home() / ".dmd_converter"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dmd_converter.log"
        
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

        _logging.basicConfig(
            level=_logging.DEBUG,
            format="%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
            handlers=[
                _logging.FileHandler(str(log_file), mode='w', encoding='utf-8'),
                _logging.StreamHandler(sys.stdout)
            ]
        )
    
    # Always ensure EventBus gets the logs if not already added
    has_eb_handler = any(isinstance(h, EventBusLogHandler) for h in _logging.root.handlers)
    if not has_eb_handler:
        eb_handler = EventBusLogHandler()
        eb_handler.setFormatter(WorkerFormatter("%(asctime)s [%(levelname)-7s] [%(worker_id)s] %(name)s — %(message)s", datefmt="%H:%M:%S"))
        eb_handler.setLevel(_logging.DEBUG)
        _logging.root.addHandler(eb_handler)

    app = DMDConverterApp()
    app.mainloop()

if __name__ == "__main__":
    main()
