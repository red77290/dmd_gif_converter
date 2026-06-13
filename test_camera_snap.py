import os
import sys
sys.path.insert(0, os.path.abspath("."))

from src.engine.auto_action.camera import _build_camera_rect
from src.engine.config.auto_action_config import AutoActionConfig

cfg = AutoActionConfig(target_width=128, target_height=32)
cfg.platformer_mode = True
cfg.platformer_floor_ratio = 0.80

frame_w = 512
frame_h = 240
effective_frame_h = 200
effective_frame_top = 0

# Mario at bottom of effective frame
roi = (240, 168, 32, 32)
y = 168
h = 32
fy = float(y + h) # 200

cx, cy, crop_w, crop_h = _build_camera_rect(
    frame_w, frame_h, roi, cfg,
    floor_y_est=fy,
    frame_top=0.0,
    face_priority_mode=False,
    effective_frame_left=0,
    effective_frame_w=frame_w,
    effective_frame_top=effective_frame_top,
    effective_frame_h=effective_frame_h
)

print(f"crop_h: {crop_h}")
print(f"cy: {cy}")
print(f"Camera top: {cy - crop_h/2}")
print(f"Camera bottom: {cy + crop_h/2}")
print(f"Floor ratio in camera: {(fy - (cy - crop_h/2)) / crop_h:.2f}")

