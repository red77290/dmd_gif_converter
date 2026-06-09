"""
Interfaces (Abstract Base Classes) for the auto_action layer.
These define the contracts that all detection, tracking, and rendering
components must respect.
"""
from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
import numpy as np


BoundingBox = Tuple[int, int, int, int]  # (x, y, w, h)
CamRect = Tuple[float, float, float, float]  # (cx, cy, cw, ch)


class IDetector(ABC):
    """Contract for any object/motion detector backend."""

    @abstractmethod
    def detect(
        self,
        frame: np.ndarray,
        mode: str,
        multi_fusion: bool = False,
        min_conf: float = 0.30,
        roi_persistence_score: float = 1.0,
        platformer_mode: bool = False,
    ) -> Optional[BoundingBox]:
        """Process a BGR frame and return the best bounding box or None."""
        pass

    @abstractmethod
    def detect_person(
        self,
        frame: np.ndarray,
        multi_fusion: bool = False,
        min_conf: float = 0.30,
        roi_persistence_score: float = 1.0,
        platformer_mode: bool = False,
    ) -> Optional[BoundingBox]:
        """Detect the primary person in the frame."""
        pass

    @abstractmethod
    def detect_motion(self, frame: np.ndarray) -> Optional[BoundingBox]:
        """Detect the primary motion region in the frame."""
        pass


class ITracker(ABC):
    """Contract for a stateful camera tracking engine."""

    @abstractmethod
    def process_frame(
        self,
        frame: np.ndarray,
        cam_prev: CamRect,
        src_idx: int,
        out_w: int,
        out_h: int,
    ) -> CamRect:
        """Process a frame and return the proposed (un-smoothed) camera rect."""
        pass

    @property
    @abstractmethod
    def last_roi(self) -> Optional[BoundingBox]:
        """Returns the last detected ROI (for vignette rendering, etc.)."""
        pass

    @property
    @abstractmethod
    def cam_full_view(self) -> CamRect:
        """Returns the camera rect representing the full-frame view."""
        pass


class IRenderer(ABC):
    """Contract for frame rendering (crop, vignette, resize)."""

    @abstractmethod
    def render(
        self,
        frame: np.ndarray,
        cam: CamRect,
        roi: Optional[BoundingBox] = None,
        is_tail: bool = False,
    ) -> np.ndarray:
        """Crop and resize a frame to the output dimensions."""
        pass

    @staticmethod
    @abstractmethod
    def crop_frame_static(frame: np.ndarray, cam: CamRect) -> np.ndarray:
        """Utility method: crop a frame to a camera rect without resizing."""
        pass

class IScorer(ABC):
    """Contract for visual quality or relevance scorers."""
    
    @abstractmethod
    def compute(self, *args, **kwargs) -> float:
        """Calculate and return a normalized score [0.0, 1.0]."""
        pass
