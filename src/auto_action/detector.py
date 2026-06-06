import os
import urllib.request
from typing import Optional, Tuple
import numpy as np

# ── ONNX YOLOv8n model settings ───────────────────────────────────────────────
_YOLO_MODEL_URL = (
    "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.onnx"
)
_YOLO_MODEL_FILENAME = "yolov8n.onnx"
# Confidence threshold for person detection (class 0 in COCO)
_YOLO_CONF_THRESH = 0.30


def _get_model_path() -> str:
    """Return the local cache path for the ONNX model (creates dirs if needed)."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "dmd_gif_converter")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, _YOLO_MODEL_FILENAME)


def _ensure_yolo_model() -> Optional[str]:
    """Download YOLOv8n ONNX model if absent; return its local path or None on failure."""
    path = _get_model_path()
    if os.path.isfile(path):
        return path
    try:
        urllib.request.urlretrieve(_YOLO_MODEL_URL, path)
        return path
    except Exception:
        return None


def available_detectors() -> list[str]:
    """Return supported detector mode names."""
    return ["person", "motion", "hybrid", "center"]


def _fuse_rois(hits: list, roi_persistence_score: float = 1.0) -> Optional[Tuple[int, int, int, int]]:
    """Fuse multiple (score, (x, y, w, h)) detections into one weighted box.

    VNext Priority 5: The fused box is weighted by confidence * area * persistence.
    """
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0][1]
        
    def _weight(s, r):
        area = max(1.0, float(r[2] * r[3]))
        # Scale area to avoid massive boxes completely dominating tiny but high-conf boxes?
        # Actually area is fine if we want important ROIs to dominate.
        # We can take sqrt of area to balance.
        import math
        return s * math.sqrt(area) * roi_persistence_score

    total_w  = sum(_weight(s, r) for s, r in hits)
    if total_w <= 0:
        return hits[0][1]
        
    wcx = sum(_weight(s, r) * (r[0] + r[2] / 2.0) for s, r in hits) / total_w
    wcy = sum(_weight(s, r) * (r[1] + r[3] / 2.0) for s, r in hits) / total_w
    ww  = sum(_weight(s, r) * r[2] for s, r in hits) / total_w
    wh  = sum(_weight(s, r) * r[3] for s, r in hits) / total_w
    x   = int(wcx - ww / 2.0)
    y   = int(wcy - wh / 2.0)
    return (max(0, x), max(0, y), int(ww), int(wh))


class _FrameDetector:
    """Detector backend for person/motion ROI extraction.

    Person detection uses ONNX YOLOv8 nano (class 0 = person in COCO).
    Automatically downloads the ~6 MB model to ~/.cache/dmd_gif_converter/
    on first use.  Falls back to motion-only detection when onnxruntime is
    unavailable or the model cannot be downloaded.

    Motion detection uses MOG2 background subtraction + optical flow.
    MOG2 is also used by the bg_sub_enable background-replacement feature.
    """

    def __init__(self):
        import cv2  # local import: module remains importable without OpenCV

        self.cv2 = cv2
        self.prev_gray = None

        # ── ONNX YOLOv8n person detector ──────────────────────────────────────
        # Resolves the macOS ARM64 crash that plagued the old HOG backend:
        # YOLOv8n runs through onnxruntime (CPUExecutionProvider) which does not
        # use Apple GCD parallelism and is safe on all architectures.
        self._onnx_session = None
        self._try_load_onnx()

        # MOG2 background subtractor for motion detection and background removal
        self.bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=36)

    # ── ONNX helpers ──────────────────────────────────────────────────────────

    def _try_load_onnx(self) -> None:
        """Load the ONNX YOLOv8n session; silently skips on any failure."""
        try:
            import onnxruntime as ort  # optional dependency
            model_path = _ensure_yolo_model()
            if model_path is None:
                return
            self._onnx_session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
        except Exception:
            self._onnx_session = None

    def _detect_yolo(self, frame, min_conf: float = _YOLO_CONF_THRESH, roi_persistence_score: float = 1.0) -> Optional[Tuple[int, int, int, int]]:
        """Run YOLOv8n inference; return best person box (x, y, w, h) or None.

        VNext Priority 8: dynamic_confidence allows lower raw confidence if persistence is high.
        """
        cv2 = self.cv2
        h, w = frame.shape[:2]

        # Preprocess: BGR→RGB, resize to 640×640, normalize 0→1, NCHW layout
        img = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis]  # HWC → NCHW

        input_name = self._onnx_session.get_inputs()[0].name
        pred = self._onnx_session.run(None, {input_name: img})[0][0]  # [84, 8400]

        # YOLOv8 output layout: rows [cx, cy, w, h, class_0..class_79], 8 400 proposals
        boxes_raw  = pred[:4].T          # [8400, 4] — cx/cy/w/h in 640-px space
        class_prob = pred[4:].T          # [8400, 80] — direct class probabilities
        person_scores = class_prob[:, 0]  # COCO class 0 = person

        # Dynamic confidence threshold
        effective_min_conf = max(0.05, min_conf * (1.0 - 0.5 * roi_persistence_score))
        
        mask = person_scores > effective_min_conf
        if not np.any(mask):
            return None

        # Best score is raw score * persistence factor (not needed for single best, max is max)
        best_i = int(np.argmax(person_scores * mask))
        cx, cy, bw, bh = boxes_raw[best_i]

        # Scale box from 640×640 space back to original frame dimensions
        sx, sy = w / 640.0, h / 640.0
        x  = int((cx - bw / 2) * sx)
        y  = int((cy - bh / 2) * sy)
        bw = int(bw * sx)
        bh = int(bh * sy)

        # Clamp to frame boundaries
        x  = max(0, x)
        y  = max(0, y)
        bw = min(bw, w - x)
        bh = min(bh, h - y)
        if bw < 8 or bh < 8:
            return None
        return (x, y, bw, bh)

    # ── Public detection methods ──────────────────────────────────────────────

    def _detect_yolo_multi(self, frame, min_conf: float = _YOLO_CONF_THRESH, roi_persistence_score: float = 1.0) -> list:
        """Return ALL person boxes above the confidence threshold.

        Returns a list of (score, (x, y, w, h)) sorted by score descending.
        Empty list when ONNX is unavailable or no detection passes threshold.
        """
        if self._onnx_session is None:
            return []
        cv2  = self.cv2
        h, w = frame.shape[:2]
        img  = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_LINEAR)
        img  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img  = np.transpose(img, (2, 0, 1))[np.newaxis]
        input_name = self._onnx_session.get_inputs()[0].name
        pred       = self._onnx_session.run(None, {input_name: img})[0][0]
        boxes_raw     = pred[:4].T
        person_scores = pred[4:].T[:, 0]
        
        effective_min_conf = max(0.05, min_conf * (1.0 - 0.5 * roi_persistence_score))
        mask    = person_scores > effective_min_conf
        indices = np.where(mask)[0]
        if len(indices) == 0:
            return []
        sx, sy  = w / 640.0, h / 640.0
        results = []
        for i in indices:
            score      = float(person_scores[i])
            cx, cy, bw, bh = boxes_raw[i]
            x  = max(0, int((cx - bw / 2) * sx))
            y  = max(0, int((cy - bh / 2) * sy))
            bw = min(int(bw * sx), w - x)
            bh = min(int(bh * sy), h - y)
            if bw >= 8 and bh >= 8:
                results.append((score, (x, y, bw, bh)))
        results.sort(key=lambda t: t[0], reverse=True)
        return results

    def detect_person(
        self, frame, multi_fusion: bool = False, min_conf: float = _YOLO_CONF_THRESH, roi_persistence_score: float = 1.0
    ) -> Optional[Tuple[int, int, int, int]]:
        """Return person bounding box via ONNX YOLOv8n, or None.

        When *multi_fusion* is True, all confident detections are fused into a
        confidence-weighted centroid box (Priority 6 — Multi-ROI Fusion).
        """
        if self._onnx_session is None:
            return None
        if multi_fusion:
            hits = self._detect_yolo_multi(frame, min_conf=min_conf, roi_persistence_score=roi_persistence_score)
            return _fuse_rois(hits, roi_persistence_score=roi_persistence_score) if hits else None
        return self._detect_yolo(frame, min_conf=min_conf, roi_persistence_score=roi_persistence_score)

    def detect_motion(self, frame) -> Optional[Tuple[int, int, int, int]]:
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None:
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

        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if area < 120.0:
            return None

        x, y, w, h = cv2.boundingRect(c)
        return (int(x), int(y), int(w), int(h))

    def detect(
        self, frame, mode: str, multi_fusion: bool = False, min_conf: float = _YOLO_CONF_THRESH, roi_persistence_score: float = 1.0
    ) -> Optional[Tuple[int, int, int, int]]:
        mode = (mode or "person").lower()
        if mode not in available_detectors():
            mode = "person"

        if mode == "center":
            return None

        if mode == "person":
            p = self.detect_person(frame, multi_fusion=multi_fusion, min_conf=min_conf, roi_persistence_score=roi_persistence_score)
            if p is not None:
                return p
            return self.detect_motion(frame)

        if mode == "motion":
            m = self.detect_motion(frame)
            if m is not None:
                return m
            return self.detect_person(frame, multi_fusion=multi_fusion, min_conf=min_conf, roi_persistence_score=roi_persistence_score)

        # hybrid
        p = self.detect_person(frame, multi_fusion=multi_fusion, min_conf=min_conf, roi_persistence_score=roi_persistence_score)
        m = self.detect_motion(frame)
        if p and m:
            # Merge boxes for broader action framing.
            x1 = min(p[0], m[0])
            y1 = min(p[1], m[1])
            x2 = max(p[0] + p[2], m[0] + m[2])
            y2 = max(p[1] + p[3], m[1] + m[3])
            return (x1, y1, x2 - x1, y2 - y1)
        return p or m
