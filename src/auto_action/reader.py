import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple
import numpy as np

class VideoReader:
    """Handles video capture and GIF pre-conversion workaround."""
    
    def __init__(self, src_path: str):
        self.src_path = src_path
        self._gif_pre_tmpdir: Optional[str] = None
        self.cap = None
        self.fps: float = 25.0
        self.frame_w: int = 0
        self.frame_h: int = 0
        self.total_frames: int = 0
        
    def open(self) -> Tuple[bool, str]:
        """Preprocesses (if GIF) and opens the video capture. Returns (ok, message)."""
        import cv2
        # ── GIF pre-conversion ────────────────────────────────────────────────────
        if self.src_path.lower().endswith(".gif"):
            try:
                self._gif_pre_tmpdir = tempfile.mkdtemp(prefix="dmd_gifpre_")
                _gif_mp4 = os.path.join(self._gif_pre_tmpdir, "src.mp4")
                _gif_conv_cmd = [
                    "ffmpeg", "-y",
                    "-i", self.src_path,
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # ensure even dims
                    _gif_mp4,
                ]
                _gif_result = subprocess.run(
                    _gif_conv_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=120,
                )
                if _gif_result.returncode == 0 and os.path.isfile(_gif_mp4):
                    self.src_path = _gif_mp4
                else:
                    shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
                    self._gif_pre_tmpdir = None
            except Exception:
                if self._gif_pre_tmpdir:
                    shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
                    self._gif_pre_tmpdir = None

        self.cap = cv2.VideoCapture(self.src_path)
        if not self.cap.isOpened():
            self.release()
            return False, "Could not open source for action preprocessing."

        self.fps = max(1.0, float(self.cap.get(cv2.CAP_PROP_FPS) or 25.0))
        self.frame_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.frame_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if self.frame_w <= 0 or self.frame_h <= 0:
            self.release()
            return False, "Invalid source dimensions for action preprocessing."

        return True, ""

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Reads a frame and ensures it is BGR24."""
        if self.cap is None:
            return False, None
            
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return False, None
            
        import cv2
        # Safety: normalise to BGR (3-channel).
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            
        return True, frame

    def set_time(self, msec: float):
        import cv2
        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_POS_MSEC, float(msec))

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self._gif_pre_tmpdir:
            shutil.rmtree(self._gif_pre_tmpdir, ignore_errors=True)
            self._gif_pre_tmpdir = None
