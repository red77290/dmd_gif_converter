import os
import subprocess
import tempfile
from typing import Tuple, Optional
import numpy as np

class FFmpegWriter:
    """Handles piping raw BGR24 frames to an FFmpeg subprocess for ultra-fast H.264 encoding."""
    
    def __init__(self, out_w: int, out_h: int, fps: float):
        self.out_w = out_w
        self.out_h = out_h
        self.fps = fps
        self.tmpdir: Optional[str] = None
        self.out_path: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        
    def open(self) -> Tuple[bool, str]:
        """Starts the FFmpeg subprocess. Returns (ok, message)."""
        self.tmpdir = tempfile.mkdtemp(prefix="dmd_action_")
        self.out_path = os.path.join(self.tmpdir, "action_pre.mp4")
        
        _fps_str = f"{self.fps:.6f}"
        _pipe_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.out_w}x{self.out_h}",
            "-r", _fps_str,
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            self.out_path,
        ]
        try:
            self.proc = subprocess.Popen(
                _pipe_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            return True, ""
        except Exception as exc:
            return False, f"Could not start FFmpeg pipe for action preprocessing: {exc}"

    def write_frame(self, frame: np.ndarray) -> bool:
        """Writes a raw BGR24 frame to the FFmpeg pipe. Returns True if successful."""
        if self.proc is None or self.proc.stdin is None:
            return False
            
        try:
            self.proc.stdin.write(frame.tobytes())
            return True
        except (BrokenPipeError, OSError):
            return False

    def close(self) -> Tuple[bool, str]:
        """Closes the pipe and waits for FFmpeg to finish. Returns (ok, stderr_hint)."""
        if self.proc is None:
            return False, "Process not started"
            
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
            
        rc = self.proc.wait()
        
        _stderr_hint = ""
        if rc != 0 or not os.path.isfile(self.out_path):
            try:
                if self.proc.stderr:
                    _se = self.proc.stderr.read().decode(errors="replace").strip()
                    if _se:
                        _stderr_hint = " | ffmpeg: " + _se[-300:]
            except Exception:
                pass
            return False, _stderr_hint
            
        return True, ""
