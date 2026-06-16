import os
import shutil
import subprocess
import tempfile
import contextlib
from typing import Optional, Tuple
import numpy as np

# Suppress [mp3float @ ...] / Header missing messages from OpenCV's internal
# FFmpeg decoder. Must be set before any cv2 import.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")


import threading

_stderr_lock = threading.Lock()

@contextlib.contextmanager
def _quiet_c_stderr():
    """Redirect C-level fd 2 (stderr) to /dev/null safely across threads."""
    with _stderr_lock:
        try:
            devnull_fd = os.open(os.devnull, os.O_WRONLY)
            old_fd = os.dup(2)
            os.dup2(devnull_fd, 2)
            os.close(devnull_fd)
            try:
                yield
            finally:
                os.dup2(old_fd, 2)
                os.close(old_fd)
        except Exception:
            yield  # fallback: do nothing if fd manipulation fails

class FFmpegPipeReader:
    """Fast, hardware-accelerated video reader bypassing OpenCV threading issues."""
    def __init__(self, src_path: str):
        self.src_path = src_path
        self._gif_pre_tmpdir: Optional[str] = None
        self.proc = None
        self.fps: float = 25.0
        self.frame_w: int = 0
        self.frame_h: int = 0
        self.total_frames: int = 0
        self._frame_bytes = 0

    def open(self, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        from src.engine.conversion.ffmpeg_utils import get_metadata
        w, h, f, dur = get_metadata(self.src_path)
        if not w or not h:
            return False, "Could not get video metadata."
            
        self.frame_w = w
        self.frame_h = h
        self.fps = target_fps if target_fps else (f if f and f > 0 else 25.0)
        self.total_frames = int(self.fps * dur) if dur else 0
        self._frame_bytes = self.frame_w * self.frame_h * 3
        
        # ── GIF pre-conversion ────────────────────────────────────────────────────
        if self.src_path.lower().endswith(".gif"):
            try:
                self._gif_pre_tmpdir = tempfile.mkdtemp(prefix="dmd_gifpre_")
                _gif_mp4 = os.path.join(self._gif_pre_tmpdir, "src.mp4")
                _gif_conv_cmd = [
                    "ffmpeg", "-y", "-i", self.src_path,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    _gif_mp4,
                ]
                _gif_result = subprocess.run(_gif_conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
                if _gif_result.returncode == 0 and os.path.isfile(_gif_mp4):
                    self.src_path = _gif_mp4
                    # ffmpeg scale=trunc(iw/2)*2 may have changed dimensions
                    self.frame_w = (w // 2) * 2
                    self.frame_h = (h // 2) * 2
                    self._frame_bytes = self.frame_w * self.frame_h * 3
                else:
                    shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
                    self._gif_pre_tmpdir = None
            except Exception:
                if self._gif_pre_tmpdir:
                    shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
                    self._gif_pre_tmpdir = None

        cmd = [
            "ffmpeg", "-y",
            "-i", self.src_path,
            "-f", "image2pipe",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24"
        ]
        if target_fps:
            cmd.extend(["-vf", f"fps={target_fps}"])
        cmd.extend([
            "-vsync", "0",
            "-"
        ])
        
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self._frame_bytes * 10)
        except Exception as e:
            return False, str(e)
            
        return True, ""

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.proc is None or self.proc.stdout is None:
            return False, None
            
        raw_frame = self.proc.stdout.read(self._frame_bytes)
        if len(raw_frame) != self._frame_bytes:
            return False, None
            
        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((self.frame_h, self.frame_w, 3))
        return True, frame

    def set_time(self, msec: float):
        # Setting time mid-stream is unsupported for pipe reader without restarting ffmpeg.
        # Auto-action does not use set_time.
        pass

    def release(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.terminate()
            self.proc.wait()
            self.proc = None
        if self._gif_pre_tmpdir:
            shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
            self._gif_pre_tmpdir = None

# Backwards compatibility alias
VideoReader = FFmpegPipeReader
