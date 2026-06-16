import subprocess
import platform
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_best_h264_encoder() -> str:
    """
    Detects the best available hardware-accelerated H.264 encoder by probing ffmpeg.
    Results are cached so the probe only runs once per application lifecycle.
    """
    sys_os = platform.system()
    
    if sys_os == "Darwin":
        # On macOS, VideoToolbox is almost universally available and preferred.
        if _test_encoder("h264_videotoolbox"):
            logger.info("[HW_ACCEL] Detected macOS. Using h264_videotoolbox.")
            return "h264_videotoolbox"
    
    # Ordered list of preferred encoders to test for Windows / Linux
    preferred_encoders = [
        "h264_nvenc",   # NVIDIA
        "h264_qsv",     # Intel QuickSync
        "h264_amf",     # AMD
    ]
    
    for encoder in preferred_encoders:
        if _test_encoder(encoder):
            logger.info(f"[HW_ACCEL] Hardware acceleration detected. Using {encoder}.")
            return encoder

    logger.info("[HW_ACCEL] No hardware acceleration detected. Falling back to libx264.")
    return "libx264"

def _test_encoder(encoder_name: str) -> bool:
    """
    Tests if a specific ffmpeg encoder is available and functioning by
    encoding a single black frame.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=128x32:d=0.1",
        "-c:v", encoder_name,
        "-f", "null",
        "-"
    ]
    
    try:
        # Run silently, we only care about the return code
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return result.returncode == 0
    except Exception:
        return False
