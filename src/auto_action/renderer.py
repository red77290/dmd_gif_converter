"""
Renderer — implements IRenderer.
Responsible for cropping, vignette application, and resizing frames.
"""
import cv2
import numpy as np
from typing import Tuple, Optional

from .interfaces import IRenderer, BoundingBox, CamRect
from .camera import _crop_frame


class Renderer(IRenderer):
    """Concrete renderer: crops, applies vignette (if enabled), and resizes."""

    def __init__(self, frame_w: int, frame_h: int, out_w: int, out_h: int, bg_sub_enable: bool):
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.out_w = out_w
        self.out_h = out_h
        self.bg_sub_enable = bg_sub_enable
        self._last_vignette_mask: Optional[np.ndarray] = None

    @staticmethod
    def crop_frame_static(frame: np.ndarray, cam: CamRect) -> np.ndarray:
        return _crop_frame(frame, cam)

    def render(
        self,
        frame: np.ndarray,
        cam: CamRect,
        roi: Optional[BoundingBox] = None,
        is_tail: bool = False,
    ) -> np.ndarray:
        """Crop, apply vignette (if bg_sub_enable), and resize to output dimensions."""
        cropped_frame = _crop_frame(frame, cam)

        if self.bg_sub_enable:
            vignette = self._compute_vignette(roi, is_tail)
            if vignette is not None:
                cropped_mask = _crop_frame(np.expand_dims(vignette, axis=-1), cam)
                cropped_mask_float = cropped_mask.squeeze()
                cropped_frame = (
                    cropped_frame.astype(np.float32)
                    * np.expand_dims(cropped_mask_float, axis=-1)
                ).astype(np.uint8)

        return cv2.resize(cropped_frame, (self.out_w, self.out_h), interpolation=cv2.INTER_LANCZOS4)

    def _compute_vignette(
        self, roi: Optional[BoundingBox], is_tail: bool
    ) -> Optional[np.ndarray]:
        """Build or reuse the vignette mask. Returns None if unavailable."""
        if not is_tail:
            vignette = np.full((self.frame_h, self.frame_w), 0.35, dtype=np.float32)
            if roi is not None:
                rx, ry, rw, rh = roi
                cx, cy = rx + rw / 2, ry + rh / 2
                axes = (max(20, int(rw * 0.8)), max(20, int(rh * 0.8)))
                cv2.ellipse(vignette, (int(cx), int(cy)), axes, 0, 0, 360, 1.0, -1)
                vignette = cv2.GaussianBlur(vignette, (99, 99), 0)
                self._last_vignette_mask = vignette
            elif self._last_vignette_mask is not None:
                vignette = self._last_vignette_mask
            else:
                vignette = np.ones((self.frame_h, self.frame_w), dtype=np.float32)
        else:
            if self._last_vignette_mask is not None:
                vignette = self._last_vignette_mask
            else:
                vignette = np.ones((self.frame_h, self.frame_w), dtype=np.float32)
        return vignette
