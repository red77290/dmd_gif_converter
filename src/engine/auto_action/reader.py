import os
import shutil
import subprocess
import tempfile
import contextlib
import cv2
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
    """Fast, hardware-accelerated video reader with automatic OpenCV fallback."""
    def __init__(self, src_path: str):
        self.src_path = src_path
        self._gif_pre_tmpdir: Optional[str] = None
        self.proc = None
        self.fps: float = 25.0
        self.frame_w: int = 0
        self.frame_h: int = 0
        self.total_frames: int = 0
        self._frame_bytes = 0

        # OpenCV fallback attributes
        self._use_cv2_fallback = False
        self._cv2_cap = None
        self._frame_step: float = 1.0
        self._next_target_frame: float = 0.0
        self._current_src_frame: int = 0

    def open(self, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        from src.engine.conversion.ffmpeg_utils import get_metadata
        w, h, f, dur = get_metadata(self.src_path)
        if not w or not h:
            # Fall back to OpenCV VideoCapture if ffprobe is not in PATH or fails
            return self._open_cv2(target_fps)

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
        except Exception:
            # Fall back to OpenCV if ffmpeg process fails to launch
            return self._open_cv2(target_fps)

        return True, ""

    def _open_cv2(self, target_fps: Optional[float] = None) -> Tuple[bool, str]:
        with _quiet_c_stderr():
            self._cv2_cap = cv2.VideoCapture(self.src_path, cv2.CAP_FFMPEG)
            if self._cv2_cap is None or not self._cv2_cap.isOpened():
                self._cv2_cap = cv2.VideoCapture(self.src_path)

        if not self._cv2_cap or not self._cv2_cap.isOpened():
            return False, f"Could not open video file: {self.src_path}"

        self.frame_w = int(self._cv2_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_h = int(self._cv2_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if self.frame_w <= 0 or self.frame_h <= 0:
            return False, f"Invalid video dimensions: {self.frame_w}x{self.frame_h}"

        src_fps = self._cv2_cap.get(cv2.CAP_PROP_FPS)
        if src_fps <= 0 or np.isnan(src_fps):
            src_fps = 25.0

        total_src_frames = int(self._cv2_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_src_frames / src_fps if total_src_frames > 0 else 0.0

        if target_fps and target_fps > 0 and target_fps < src_fps:
            self.fps = target_fps
            self._frame_step = src_fps / target_fps
            self.total_frames = int(duration * target_fps) if duration > 0 else total_src_frames
        else:
            self.fps = src_fps
            self._frame_step = 1.0
            self.total_frames = total_src_frames

        self._next_target_frame = 0.0
        self._current_src_frame = 0
        self._use_cv2_fallback = True
        return True, ""

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._use_cv2_fallback:
            if not self._cv2_cap or not self._cv2_cap.isOpened():
                return False, None

            if self._frame_step <= 1.0:
                ret, frame = self._cv2_cap.read()
                return ret, frame

            target_src_index = int(round(self._next_target_frame))
            while self._current_src_frame < target_src_index:
                ret = self._cv2_cap.grab()
                if not ret:
                    return False, None
                self._current_src_frame += 1

            ret, frame = self._cv2_cap.retrieve()
            if not ret:
                ret, frame = self._cv2_cap.read()
                if not ret:
                    return False, None

            self._next_target_frame += self._frame_step
            self._current_src_frame += 1
            return True, frame

        if self.proc is None or self.proc.stdout is None:
            return False, None

        raw_frame = self.proc.stdout.read(self._frame_bytes)
        if len(raw_frame) != self._frame_bytes:
            return False, None

        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((self.frame_h, self.frame_w, 3))
        return True, frame

    def set_time(self, msec: float):
        pass

    def release(self):
        if self._use_cv2_fallback and self._cv2_cap:
            self._cv2_cap.release()
            self._cv2_cap = None
        if self.proc:
            try:
                self.proc.stdout.close()
                self.proc.terminate()
                self.proc.wait()
            except Exception:
                pass
            self.proc = None
        if self._gif_pre_tmpdir:
            shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
            self._gif_pre_tmpdir = None

# Backwards compatibility alias
VideoReader = FFmpegPipeReader
