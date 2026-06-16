"""
Detector module — person & motion ROI extraction.

Architecture:
  AbstractDetector (IDetector)  ← defines the public contract
    └── _FrameDetector          ← concrete unified implementation
         ├── _detect_yolo()     ← best-single-box ONNX YOLOv8n inference
         ├── _detect_yolo_multi()  ← all-boxes multi-fusion variant
         ├── detect_person()    ← ONNX → motion fallback
         └── detect_motion()    ← MOG2 + optical-flow background subtraction

DetectorFactory.create(cfg)     ← returns the right detector for a config
"""
import os
import math
import urllib.request
from abc import abstractmethod
from typing import List, Optional, Tuple
import numpy as np
import cv2

from src.engine.auto_action.interfaces import IDetector, BoundingBox

# ── ONNX YOLOv8n model settings ───────────────────────────────────────────────
_YOLO_MODEL_URL = (
    "https://huggingface.co/flightsnotights/yolov8n_onnx/resolve/main/yolov8n.onnx"
)
_YOLO_MODEL_FILENAME = "yolov8n.onnx"
_YOLO_CONF_THRESH = 0.30


def _get_model_path() -> str:
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "dmd_gif_converter")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, _YOLO_MODEL_FILENAME)


def _ensure_yolo_model() -> Optional[str]:
    path = _get_model_path()
    if os.path.isfile(path):
        return path
    try:
        urllib.request.urlretrieve(_YOLO_MODEL_URL, path)
        return path
    except Exception:
        return None


def available_detectors() -> list[str]:
    return ["person", "motion", "hybrid", "center"]


def _fuse_rois(hits: list, roi_persistence_score: float = 1.0) -> Optional[BoundingBox]:
    """Fuse multiple (score, (x, y, w, h)) detections into one weighted box."""
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0][1]

    def _weight(s, r):
        area = max(1.0, float(r[2] * r[3]))
        return s * math.sqrt(area) * roi_persistence_score

    total_w = sum(_weight(s, r) for s, r in hits)
    if total_w <= 0:
        return hits[0][1]

    wcx = sum(_weight(s, r) * (r[0] + r[2] / 2.0) for s, r in hits) / total_w
    wcy = sum(_weight(s, r) * (r[1] + r[3] / 2.0) for s, r in hits) / total_w
    ww  = sum(_weight(s, r) * r[2] for s, r in hits) / total_w
    wh  = sum(_weight(s, r) * r[3] for s, r in hits) / total_w
    x   = int(wcx - ww / 2.0)
    y   = int(wcy - wh / 2.0)
    return BoundingBox(max(0, x), max(0, y), int(ww), int(wh))


class AbstractDetector(IDetector):
    """
    Abstract base for concrete detectors.
    Provides a default dispatch implementation of .detect() routing
    to detect_person() and detect_motion() based on *mode*.
    Subclasses only need to implement detect_person() and detect_motion().
    """

    def detect(
        self,
        frame: np.ndarray,
        mode: str,
        multi_fusion: bool = False,
        min_conf: float = _YOLO_CONF_THRESH,
        roi_persistence_score: float = 1.0,
        platformer_mode: bool = False,
        expected_floor_y: Optional[float] = None,
        is_batch: bool = False,
    ) -> Optional[BoundingBox]:
        mode = (mode or "person").lower()
        if mode not in available_detectors():
            mode = "person"

        if mode == "center":
            return None

        if mode == "person":
            p = self.detect_person(frame, multi_fusion=multi_fusion, min_conf=min_conf,
                                   roi_persistence_score=roi_persistence_score,
                                   platformer_mode=platformer_mode, expected_floor_y=expected_floor_y, is_batch=is_batch)
            return p if p is not None else self.detect_motion(frame, platformer_mode=platformer_mode, expected_floor_y=expected_floor_y)

        if mode == "motion":
            m = self.detect_motion(frame, platformer_mode=platformer_mode, expected_floor_y=expected_floor_y)
            return m if m is not None else self.detect_person(
                frame, multi_fusion=multi_fusion, min_conf=min_conf,
                roi_persistence_score=roi_persistence_score, platformer_mode=platformer_mode, expected_floor_y=expected_floor_y, is_batch=is_batch)

        # hybrid: merge both
        p = self.detect_person(frame, multi_fusion=multi_fusion, min_conf=min_conf,
                                roi_persistence_score=roi_persistence_score,
                                platformer_mode=platformer_mode, expected_floor_y=expected_floor_y, is_batch=is_batch)
        m = self.detect_motion(frame, platformer_mode=platformer_mode, expected_floor_y=expected_floor_y)
        if p and m:
            x1 = min(p[0], m[0])
            y1 = min(p[1], m[1])
            x2 = max(p[0] + p[2], m[0] + m[2])
            y2 = max(p[1] + p[3], m[1] + m[3])
            return BoundingBox(x1, y1, x2 - x1, y2 - y1)
        return p or m


class _FrameDetector(AbstractDetector):
    """
    Concrete detector implementation.
    Uses ONNX YOLOv8n for person detection (falls back to motion when unavailable).
    Uses MOG2 background subtractor + optical flow for motion detection.
    """

    def __init__(self):
        self.cv2 = cv2
        self.prev_gray = None
        self.bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=36)
        self._try_load_onnx()

    _shared_session_fast = None
    _shared_session_batch = None
    _shared_model_h = 640
    _shared_model_w = 640
    _shared_model_type = ""
    _session_lock = __import__("threading").Lock()

    def _create_session(self, model_path: str, num_threads: int):
        import onnxruntime as ort
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = num_threads
        sess_options.inter_op_num_threads = 2
        
        session = ort.InferenceSession(
            model_path, 
            sess_options=sess_options,
            providers=["CPUExecutionProvider"]
        )
        return session

    def _try_load_onnx(self) -> None:
        with self._session_lock:
            if _FrameDetector._shared_session_fast is not None:
                self._onnx_session_fast = _FrameDetector._shared_session_fast
                self._onnx_session_batch = _FrameDetector._shared_session_batch
                self._model_h = _FrameDetector._shared_model_h
                self._model_w = _FrameDetector._shared_model_w
                self.model_type = _FrameDetector._shared_model_type
                return

            try:
                model_path = _ensure_yolo_model()
                if model_path is None:
                    self._onnx_session_fast = None
                    self._onnx_session_batch = None
                    return
                
                import os
                cpu_cores = os.cpu_count() or 4
                fast_threads = min(8, max(1, cpu_cores))
                batch_threads = max(1, min(2, cpu_cores // 2))
                
                session_fast = self._create_session(model_path, fast_threads)
                session_batch = self._create_session(model_path, batch_threads)
                
                inputs = session_fast.get_inputs()[0]
                model_h = inputs.shape[2]
                model_w = inputs.shape[3]
                if not isinstance(model_h, int) or not isinstance(model_w, int):
                    model_h, model_w = 640, 640
                
                _FrameDetector._shared_session_fast = session_fast
                _FrameDetector._shared_session_batch = session_batch
                _FrameDetector._shared_model_h = model_h
                _FrameDetector._shared_model_w = model_w
                _FrameDetector._shared_model_type = "onnx"

                self._onnx_session_fast = session_fast
                self._onnx_session_batch = session_batch
                self._model_h = model_h
                self._model_w = model_w
                self.model_type = "onnx"
            except Exception:
                self._onnx_session_fast = None
                self._onnx_session_batch = None
                self._model_h = 640
                self._model_w = 640
                self.model_type = ""

    def _get_active_session(self, is_batch: bool = False):
        if is_batch:
            return self._onnx_session_batch
        return self._onnx_session_fast

    def _detect_yolo(self, frame: np.ndarray, min_conf: float = _YOLO_CONF_THRESH,
                     roi_persistence_score: float = 1.0, platformer_mode: bool = False,
                     expected_floor_y: Optional[float] = None, is_batch: bool = False) -> Optional[BoundingBox]:
        session = self._get_active_session(is_batch)
        if session is None:
            return None
            
        cv2 = self.cv2
        h, w = frame.shape[:2]

        img = cv2.resize(frame, (self._model_w, self._model_h), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis]

        input_name = session.get_inputs()[0].name
        pred = session.run(None, {input_name: img})[0][0]

        boxes_raw = pred[:4].T
        class_prob = pred[4:].T
        person_scores = class_prob[:, 0]

        effective_min_conf = max(0.05, min_conf * (1.0 - 0.5 * roi_persistence_score))
        mask = person_scores > effective_min_conf
        if not np.any(mask):
            return None

        if platformer_mode:
            if expected_floor_y is not None:
                sy_model = self._model_h / float(h)
                expected_floor_model = expected_floor_y * sy_model
                boxes_bottom = boxes_raw[:, 1] + boxes_raw[:, 3] / 2.0
                dist_to_floor = np.abs(boxes_bottom - expected_floor_model) / float(self._model_h)
                
                # Reject ONLY hard ceiling pareidolia: detections whose TOP is above the
                # established floor_y AND whose bottom is far from the floor.
                # This lets Mario jump freely (his bottom follows the arc), but blocks
                # a ceiling block that is fully above the floor line.
                boxes_top = boxes_raw[:, 1] - boxes_raw[:, 3] / 2.0
                is_above_floor = boxes_top < expected_floor_model
                is_far_from_floor = dist_to_floor > 0.60
                ceiling_block = is_above_floor & is_far_from_floor
                mask = mask & ~ceiling_block
                
                platformer_scores = person_scores * mask * (0.01 + 100.0 * np.exp(-dist_to_floor * 10.0))
            else:
                # Initial floor discovery: only bias toward bottom half, do NOT hard-reject.
                # boxes_raw[:, 1] is the CENTER y in model coords — a box at the very top
                # of the screen has center ~0.0, one at the very bottom ~1.0.
                center_y_norm = boxes_raw[:, 1] / self._model_h
                # Strong bias toward low-center detections (boxes near the bottom of screen)
                # but never fully zero out boxes at the top — Mario could start a jump on frame 1.
                floor_bias = (0.1 + center_y_norm) ** 4   # ~0.0001 at top, ~1.3 at bottom
                platformer_scores = person_scores * mask * floor_bias * 100.0
                
            if not np.any(mask):
                return None
                
            best_i = int(np.argmax(platformer_scores))
        else:
            best_i = int(np.argmax(person_scores * mask))

        cx, cy, bw, bh = boxes_raw[best_i]
        sx, sy = w / float(self._model_w), h / float(self._model_h)
        x  = int((cx - bw / 2) * sx)
        y  = int((cy - bh / 2) * sy)
        bw = int(bw * sx)
        bh = int(bh * sy)

        x  = max(0, x)
        y  = max(0, y)
        bw = min(bw, w - x)
        bh = min(bh, h - y)
        if bw < 8 or bh < 8:
            return None
        return BoundingBox(x, y, bw, bh)

    def _detect_yolo_multi(self, frame: np.ndarray, min_conf: float = _YOLO_CONF_THRESH,
                            roi_persistence_score: float = 1.0, is_batch: bool = False) -> List:
        session = self._get_active_session(is_batch)
        if session is None:
            return []
        cv2 = self.cv2
        h, w = frame.shape[:2]
        img = cv2.resize(frame, (self._model_w, self._model_h), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis]
        input_name = session.get_inputs()[0].name
        pred = session.run(None, {input_name: img})[0][0]
        boxes_raw     = pred[:4].T
        person_scores = pred[4:].T[:, 0]

        effective_min_conf = max(0.05, min_conf * (1.0 - 0.5 * roi_persistence_score))
        mask    = person_scores > effective_min_conf
        indices = np.where(mask)[0]
        if len(indices) == 0:
            return []

        sx, sy  = w / float(self._model_w), h / float(self._model_h)
        results = []
        for i in indices:
            score = float(person_scores[i])
            cx, cy, bw, bh = boxes_raw[i]
            x  = max(0, int((cx - bw / 2) * sx))
            y  = max(0, int((cy - bh / 2) * sy))
            bw = int(bw * sx)
            bh = int(bh * sy)
            bw = min(bw, w - x)
            bh = min(bh, h - y)
            if bw >= 8 and bh >= 8:
                results.append((score, BoundingBox(x, y, bw, bh)))
        results.sort(key=lambda t: t[0], reverse=True)
        return results

    def detect_person(self, frame: np.ndarray, multi_fusion: bool = False,
                      min_conf: float = _YOLO_CONF_THRESH,
                      roi_persistence_score: float = 1.0,
                      platformer_mode: bool = False,
                      expected_floor_y: Optional[float] = None,
                      is_batch: bool = False) -> Optional[BoundingBox]:
        if self._get_active_session(is_batch) is None:
            return None
        if multi_fusion:
            hits = self._detect_yolo_multi(frame, min_conf=min_conf,
                                            roi_persistence_score=roi_persistence_score,
                                            is_batch=is_batch)
            return _fuse_rois(hits, roi_persistence_score=roi_persistence_score) if hits else None
        return self._detect_yolo(frame, min_conf=min_conf,
                                  roi_persistence_score=roi_persistence_score,
                                  platformer_mode=platformer_mode,
                                  expected_floor_y=expected_floor_y,
                                  is_batch=is_batch)

    def detect_motion(self, frame: np.ndarray, platformer_mode: bool = False,
                      expected_floor_y: Optional[float] = None) -> Optional[BoundingBox]:
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None or self.prev_gray.shape != gray.shape:
            self.prev_gray = gray
            return None

        diff = cv2.absdiff(gray, self.prev_gray)
        self.prev_gray = gray
        blur = cv2.GaussianBlur(diff, (7, 7), 0)
        _, mask = cv2.threshold(blur, 24, 255, cv2.THRESH_BINARY)

        fg = self.bg_sub.apply(frame)
        mask = cv2.bitwise_and(mask, fg)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        frame_h = frame.shape[0]

        def score_contour(c):
            area = cv2.contourArea(c)
            if area < 120.0:
                return 0.0
            if platformer_mode:
                x, y, w, h = cv2.boundingRect(c)
                bottom_y = y + h
                if expected_floor_y is not None:
                    import math
                    dist_to_floor = abs(bottom_y - expected_floor_y) / float(frame_h)
                    return area * (0.01 + 100.0 * math.exp(-dist_to_floor * 10.0))
                else:
                    bottomness = bottom_y / frame_h
                    # Extreme floor tracking: massive penalty for ceiling to prevent boss/fx tracking
                    return area * (0.01 + 100.0 * (bottomness ** 4))
            return area

        c_best = max(contours, key=score_contour)
        if score_contour(c_best) == 0.0:
            return None

        x, y, w, h = cv2.boundingRect(c_best)
        return BoundingBox(int(x), int(y), int(w), int(h))


class DetectorFactory:
    """Factory that creates the right detector for a given config."""

    @staticmethod
    def create() -> IDetector:
        """Return the default unified detector."""
        return _FrameDetector()
