import os
import glob
import tempfile
import shutil
import subprocess
from PIL import Image, ImageTk

from src.ui.constants import SRC_CANVAS_W, SRC_CANVAS_H, BG_CANVAS

class SourceController:
    """Manages the Source Preview rendering and extraction."""
    
    def __init__(self, canvas, info_label, action_button):
        self.canvas = canvas
        self.info_label = info_label
        self.action_button = action_button
        
        self.pil_frames = []
        self.frames = []
        self.delays = []
        self.idx = 0
        self.job = None
        self.tmpdir = None
        self.file_path = None
        
    def stop(self):
        if self.job:
            self.canvas.after_cancel(self.job)
            self.job = None
        self.pil_frames.clear()
        self.frames.clear()
        self.delays.clear()
        self.idx = 0
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None

    def load(self, file_path, source_duration):
        self.stop()
        self.file_path = file_path
        
        import threading
        threading.Thread(target=self._extract_frames, args=(file_path, source_duration), daemon=True).start()

    def _extract_frames(self, file_path, source_duration):
        tmpdir = tempfile.mkdtemp(prefix="dmd_src_")
        fps_prev = 12.5
        dur = min(source_duration, 10.0)
        cmd = ["ffmpeg", "-y", "-hwaccel", "auto", "-i", file_path, "-t", str(dur),
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
        self.canvas.after(0, lambda: self._on_frames_ready(pil_frames, delays, tmpdir))

    def _on_frames_ready(self, pil_frames, delays, tmpdir):
        if not pil_frames:
            self.canvas.delete("all")
            cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else SRC_CANVAS_W
            self.canvas.create_text(cw // 2, getattr(self, "_last_h", SRC_CANVAS_H) // 2,
                                    text="⚠️  Preview unavailable\n(ffmpeg missing?)",
                                    fill="#e74c3c", font=("Helvetica", 11), justify="center",
                                    width=cw - 20, tags="info_text")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
            
        self.tmpdir = tmpdir
        self.pil_frames = pil_frames
        self.frames = [None] * len(pil_frames)
        self.delays = delays
        self.idx = 0
        
        dur_s = len(pil_frames) / 12.5
        self.info_label.configure(text=f"🎥  {len(pil_frames)} frames  ·  {dur_s:.1f}s")
        self.action_button.configure(state="normal", text="🔍 Source")
        self._animate()

    def _animate(self):
        if not self.pil_frames:
            return
        num = len(self.pil_frames)
        idx = self.idx % num
        
        if self.frames[idx] is None:
            pil_img = self.pil_frames[idx]
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
            if cw < 10 or ch < 10:
                cw, ch = SRC_CANVAS_W, SRC_CANVAS_H
            if pil_img.width != cw or pil_img.height != ch:
                from src.ui.utils.image_utils import aspect_scale
                scaled = aspect_scale(pil_img, cw, ch, bg_color=BG_CANVAS)
                self.frames[idx] = ImageTk.PhotoImage(scaled)
            else:
                self.frames[idx] = ImageTk.PhotoImage(pil_img)
                
        img_tk = self.frames[idx]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.delete("img")
        self.canvas.create_image(cw // 2, ch // 2, image=img_tk, anchor="center", tags="img")
        self.idx += 1
        self.job = self.canvas.after(self.delays[idx], self._animate)

    def draw_idle(self):
        self.stop()
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else SRC_CANVAS_W
        self.canvas.create_text(cw // 2, getattr(self, "_last_h", SRC_CANVAS_H) // 2,
                                text="⏸️  Source idle", fill="#95a5a6", font=("Helvetica", 12),
                                justify="center", tags="info_text")
        self.info_label.configure(text="🎥  Idle")
        self.action_button.configure(state="normal", text="🔍 Source")
