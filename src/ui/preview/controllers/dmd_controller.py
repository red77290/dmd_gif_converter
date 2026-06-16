import os
import shutil
import tempfile
import logging
from PIL import Image, ImageTk

from src.ui.constants import DMD_REFRESH_DELAY_MS, BG_CANVAS, SRC_CANVAS_W, SRC_CANVAS_H
from src.ui.dmd_led_sim import apply_led_grid as _apply_led_grid

logger = logging.getLogger(__name__)

class DmdController:
    """Manages the DMD Preview rendering and LED simulation."""
    
    def __init__(self, canvas, info_label, action_button, progress_var, app_state):
        self.canvas = canvas
        self.info_label = info_label
        self.action_button = action_button
        self.progress_var = progress_var
        self.app_state = app_state
        
        self.pil_frames = []
        self.frames = []
        self.delays = []
        self.idx = 0
        self.job = None
        self.tmpdir = None
        self.file_path = None
        self.cached_out = None
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
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else SRC_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else SRC_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="⏸️  DMD idle", fill="#95a5a6", font=("Helvetica", 12),
                                justify="center", tags="info_text")
        self.info_label.configure(text="✅  Idle")
        self.action_button.configure(state="normal", text="🔬 DMD")

    def start_generation(self, file_path, is_already_converted=False):
        if self.rendering:
            self.pending_src = (file_path, is_already_converted)
            return

        self.rendering = True
        self.file_path = file_path
        self.session_id += 1
        current_session = self.session_id

        self.action_button.configure(state="disabled", text="⏳ Rendering...")
        self.info_label.configure(text="⏳  Generating final preview...")
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else SRC_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else SRC_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="⏳  Generating…", fill="#7ec8e3", font=("Helvetica", 12),
                                justify="center", tags="info_text")

        import threading
        threading.Thread(target=self._generate, args=(file_path, current_session, is_already_converted), daemon=True).start()

    def _generate(self, src, session_id, is_already_converted):
        from src.engine.conversion.core import process_file
        from src.engine.config.auto_action_config import AutoActionConfig
        
        tmpdir = tempfile.mkdtemp(prefix="dmd_prev_")
        
        if is_already_converted:
            out_gif = src
            success = True
            msg = "Already converted"
        else:
            out_gif = os.path.join(tmpdir, "preview.mp4")
            p = self.app_state.to_dict()
            # Force fast preview constraints
            p["max_duration"] = 10.0
            p["auto_action_enabled"] = False 

            cfg = AutoActionConfig.from_params(p)
            
            self.canvas.after(0, lambda: self.progress_var.configure(mode="indeterminate"))
            self.canvas.after(0, lambda: self.progress_var.start())
            
            success, msg = process_file(src, out_gif, params=p, callback=None)
            
            self.canvas.after(0, lambda: self.progress_var.stop())
            self.canvas.after(0, lambda: self.progress_var.configure(mode="determinate"))
            self.canvas.after(0, lambda: self.progress_var.set(0))
            
            if session_id != self.session_id:
                return

            if not success or not os.path.isfile(out_gif):
                self.canvas.after(0, lambda: self._on_fail(msg, tmpdir))
                return

        pil_frames, delays = [], []
        try:
            if out_gif.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.webm')):
                from src.engine.auto_action.reader import FFmpegPipeReader
                reader = FFmpegPipeReader(out_gif)
                ok, err = reader.open()
                if ok:
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
            logger.exception("DmdController._generate error: %s", exc)

        self.canvas.after(0, lambda: self._on_ready(pil_frames, delays, tmpdir, out_gif))

    def _on_fail(self, msg, tmpdir):
        self.rendering = False
        self.action_button.configure(state="normal", text="🔬 DMD")
        self.info_label.configure(text=f"❌  Error: {msg}")
        self.canvas.delete("all")
        cw = max(20, self.canvas.winfo_width()) if self.canvas.winfo_width() > 10 else SRC_CANVAS_W
        ch = max(20, self.canvas.winfo_height()) if self.canvas.winfo_height() > 10 else SRC_CANVAS_H
        self.canvas.create_text(cw // 2, ch // 2,
                                text="❌  Preview failed", fill="#e74c3c", font=("Helvetica", 12),
                                justify="center", tags="info_text")
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)
        self._flush_pending()

    def _on_ready(self, pil_frames, delays, tmpdir, out_gif):
        self.rendering = False
        self.action_button.configure(state="normal", text="🔬 DMD")
        self.stop()
        self.tmpdir = tmpdir
        self.cached_out = out_gif
        self.pil_frames = pil_frames
        self.frames = [None] * len(pil_frames)
        self.delays = delays
        self.idx = 0
        
        size_kb = os.path.getsize(out_gif) // 1024 if os.path.isfile(out_gif) else 0
        self.info_label.configure(
            text=(f"✅  {self.app_state.v_target_width.get()}"
                  f"×{self.app_state.v_target_height.get()}"
                  f"  ·  {len(pil_frames)} frames  ·  {size_kb} KB"))
        self._animate()
        self._flush_pending()

    def _flush_pending(self):
        if self.pending_src:
            s, c = self.pending_src
            self.pending_src = None
            self.start_generation(s, is_already_converted=c)

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
                
            from src.ui.utils.image_utils import aspect_scale
            scaled = aspect_scale(pil_img, cw, ch, bg_color=BG_CANVAS, resample=Image.NEAREST)
            
            if getattr(self.app_state, "v_led_sim", None) and self.app_state.v_led_sim.get():
                from src.ui.dmd_led_sim import LED_SIM_SCALE, LED_SIM_GAP
                led_w = pil_img.width * LED_SIM_SCALE
                led_h = pil_img.height * LED_SIM_SCALE
                
                # Check limits
                if led_w > cw:
                    sim_scale = max(1, cw // pil_img.width)
                    sim_gap = 1 if sim_scale > 2 else 0
                else:
                    sim_scale, sim_gap = LED_SIM_SCALE, LED_SIM_GAP
                    
                sim_img = _apply_led_grid(pil_img, sim_scale, sim_gap)
                from src.ui.utils.image_utils import pad_to_center
                padded = pad_to_center(sim_img, cw, ch, bg_color=BG_CANVAS)
                self.frames[idx] = ImageTk.PhotoImage(padded)
            else:
                self.frames[idx] = ImageTk.PhotoImage(scaled)
                
        img_tk = self.frames[idx]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.delete("img")
        self.canvas.create_image(cw // 2, ch // 2, image=img_tk, anchor="center", tags="img")
        self.idx += 1
        
        delay = self.delays[idx]
        if getattr(self.app_state, "v_led_sim", None) and self.app_state.v_led_sim.get():
            delay = max(delay, DMD_REFRESH_DELAY_MS)
            
        self.job = self.canvas.after(delay, self._animate)
