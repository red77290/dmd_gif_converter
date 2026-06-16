import os
import shutil
import logging
from PIL import Image, ImageTk

from src.ui.constants import BG_CANVAS, AUTO_CANVAS_W, AUTO_CANVAS_H

logger = logging.getLogger(__name__)

class AutoController:
    """Manages the Auto Action Preview generation and rendering."""
    
    def __init__(self, canvas, info_label, action_button, dmd_controller, app_state):
        self.canvas = canvas
        self.info_label = info_label
        self.action_button = action_button
        self.dmd_controller = dmd_controller
        self.app_state = app_state
        
        self.pil_frames = []
        self.frames = []
        self.delays = []
        self.idx = 0
        self.job = None
        self.tmpdir = None
        self.file_path = None
        self.rendering = False
        self.session_id = 0
        self.pending_src = None

    def stop(self):
        if self.job:
            self.canvas.after_cancel(self.job)
            self.job = None
        self.pil_frames.clear()
        self.frames.clear()
        self.delays.clear()
        self.idx = 0
        self.rendering = False

    def draw_idle(self):
        self.stop()
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else AUTO_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else AUTO_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="⏸️  Auto idle", fill="#95a5a6", font=("Helvetica", 12),
                                justify="center", tags="info_text")
        self.info_label.configure(text="🤖  Idle")
        self.action_button.configure(state="normal", text="🤖 Auto")

    def start_generation(self, file_path):
        if self.rendering:
            self.pending_src = file_path
            return

        self.rendering = True
        self.file_path = file_path
        self.session_id += 1
        current_session = self.session_id

        self.action_button.configure(state="disabled", text="⏳ Analyzing...")
        self.info_label.configure(text="⏳  Auto framing in progress...")
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else AUTO_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else AUTO_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="⏳  Analyzing scene…", fill="#7ec8e3", font=("Helvetica", 12),
                                justify="center", tags="info_text")

        import threading
        threading.Thread(target=self._generate, args=(file_path, current_session), daemon=True).start()

    def _generate(self, src, session_id):
        from src.engine.auto_action.main import AutoActionConfig, preprocess_video_for_dmd
        from src.engine.conversion.core import process_file
        
        cfg = AutoActionConfig.from_app_state(self.app_state)
        # Force max duration to 10s for preview to keep it fast
        if hasattr(self.app_state, "v_max_duration") and self.app_state.v_max_duration.get() > 10.0:
            from dataclasses import replace
            cfg = replace(cfg, max_duration=10.0)

        def _log(msg, level="info"):
            getattr(logger, level)(msg)
            if "Quality Score:" in str(msg):
                self.canvas.after(0, lambda: self.info_label.configure(text=f"🤖  {str(msg).split('—')[-1].strip()}"))

        ok, pre_src, msg = preprocess_video_for_dmd(src, cfg, callback=_log)
        if session_id != self.session_id:
            return

        if not ok or not pre_src:
            self.canvas.after(0, lambda: self._on_fail(msg))
            return

        pil_frames, delays = [], []
        try:
            from src.engine.auto_action.reader import FFmpegPipeReader
            reader = FFmpegPipeReader(pre_src)
            rok, rmsg = reader.open()
            if rok:
                fps = reader.fps or 25.0
                dm = int(1000 / fps) if fps > 0 else 40
                while True:
                    ret, frame = reader.read()
                    if not ret:
                        break
                    import cv2
                    comp = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    pil_frames.append(comp)
                    delays.append(dm)
                reader.release()
        except Exception as exc:
            logger.exception("AutoController._generate error: %s", exc)

        tmpdir = os.path.dirname(pre_src) if pre_src else None
        self.canvas.after(0, lambda: self._on_ready(pil_frames, delays, tmpdir, pre_src))

    def _on_fail(self, msg):
        self.rendering = False
        self.action_button.configure(state="normal", text="🤖 Auto")
        if "OpenCV" in msg:
            self.info_label.configure(text="❌  OpenCV missing")
        else:
            self.info_label.configure(text=f"❌  Error: {msg}")
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else AUTO_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else AUTO_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="⚠️  Auto Framing failed\n(Check logs)", fill="#e74c3c", font=("Helvetica", 12),
                                justify="center", tags="info_text")
        
        # Trigger DMD preview directly on the source as fallback
        self.dmd_controller.start_generation(self.file_path, is_already_converted=False)
        self._flush_pending()

    def _on_ready(self, pil_frames, delays, tmpdir, pre_src):
        self.rendering = False
        self.action_button.configure(state="normal", text="🤖 Auto")
        self.stop()
        self.tmpdir = tmpdir
        self.pil_frames = pil_frames
        self.frames = [None] * len(pil_frames)
        self.delays = delays
        self.idx = 0
        
        self._animate()
        
        # Chain to DMD generation
        self.dmd_controller.start_generation(pre_src, is_already_converted=False)
        self._flush_pending()

    def _flush_pending(self):
        if self.pending_src:
            s = self.pending_src
            self.pending_src = None
            self.start_generation(s)

    def _animate(self):
        if not self.pil_frames:
            return
        num = len(self.pil_frames)
        idx = self.idx % num
        
        if self.frames[idx] is None:
            pil_img = self.pil_frames[idx]
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            if cw < 10 or ch < 10:
                cw, ch = AUTO_CANVAS_W, AUTO_CANVAS_H
                
            from src.ui.utils.image_utils import aspect_scale
            scaled = aspect_scale(pil_img, cw, ch, bg_color=BG_CANVAS)
            self.frames[idx] = ImageTk.PhotoImage(scaled)
                
        img_tk = self.frames[idx]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.delete("img")
        self.canvas.create_image(cw // 2, ch // 2, image=img_tk, anchor="center", tags="img")
        self.idx += 1
        
        self.job = self.canvas.after(self.delays[idx], self._animate)
