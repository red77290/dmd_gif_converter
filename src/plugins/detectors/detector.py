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
        if os.path.getsize(path) > 1_000_000:
            return path
        try:
            os.remove(path)
        except Exception:
            pass

    try:
        urllib.request.urlretrieve(_YOLO_MODEL_URL, path)
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            return path
    except Exception:
        pass

    try:
        import requests
        r = requests.get(_YOLO_MODEL_URL, stream=True, timeout=60, verify=False)
        if r.status_code == 200:
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
                return path
    except Exception:
        pass

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
        expected_cx: Optional[float] = None,
        expected_cy: Optional[float] = None,
        expected_h: Optional[float] = None,
    ) -> Optional[BoundingBox]:
        mode = (mode or "person").lower()
        if mode not in available_detectors():
            mode = "person"

        if mode == "center":
            return None

        person_kw = dict(
            multi_fusion=multi_fusion,
            min_conf=min_conf,
            roi_persistence_score=roi_persistence_score,
            platformer_mode=platformer_mode,
            expected_floor_y=expected_floor_y,
            is_batch=is_batch,
        )
        motion_kw = dict(
            platformer_mode=platformer_mode,
            expected_floor_y=expected_floor_y,
        )
        if isinstance(self, _FrameDetector):
            if expected_cx is not None:
                person_kw["expected_cx"] = expected_cx
                motion_kw["expected_cx"] = expected_cx
            if expected_cy is not None:
                person_kw["expected_cy"] = expected_cy
                motion_kw["expected_cy"] = expected_cy
            if expected_h is not None and float(expected_h) > 8.0:
                motion_kw["expected_h"] = float(expected_h)

        if mode == "person":
            p = self.detect_person(frame, **person_kw)
            return p if p is not None else self.detect_motion(frame, **motion_kw)

        if mode == "motion":
            m = self.detect_motion(frame, **motion_kw)
            return m if m is not None else self.detect_person(frame, **person_kw)

        # hybrid: merge only spatially adjacent boxes in non-platformer scenes;
        # never fuse a clean sprite box with disjoint scrolling ground/background contours.
        p = self.detect_person(frame, **person_kw)
        m = self.detect_motion(frame, **motion_kw)
        if p and m:
            px2, py2 = p[0] + p[2], p[1] + p[3]
            mx2, my2 = m[0] + m[2], m[1] + m[3]
            pad_x = max(p[2], m[2]) * 0.35
            pad_y = max(p[3], m[3]) * 0.35
            near_overlap = not (
                px2 + pad_x < m[0]
                or mx2 + pad_x < p[0]
                or py2 + pad_y < m[1]
                or my2 + pad_y < p[1]
            )
            if near_overlap and not platformer_mode:
                x1 = min(p[0], m[0])
                y1 = min(p[1], m[1])
                x2 = max(px2, mx2)
                y2 = max(py2, my2)
                return BoundingBox(x1, y1, x2 - x1, y2 - y1)
            return p
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
        self.last_bg_scroll: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._scroll_window: Optional[np.ndarray] = None
        self._try_load_onnx()

    def feed_subsampled_frame(self, frame: np.ndarray) -> None:
        """Keep temporal motion state fresh on subsampled non-YOLO frames to prevent multi-frame ghost lag."""
        if frame is None or frame.size == 0:
            return
        try:
            self.prev_gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            self.bg_sub.apply(frame, learningRate=0.005)
        except Exception:
            pass

    _shared_session_fast = None
    _shared_session_batch = None
    _shared_model_path: Optional[str] = None
    _shared_model_checked: bool = False
    _shared_model_h = 640
    _shared_model_w = 640
    _shared_model_type = ""
    _session_lock = __import__("threading").Lock()

    def _create_session(self, model_path: str, num_threads: int):
        import onnxruntime as ort
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = max(1, int(num_threads))
        sess_options.inter_op_num_threads = 1
        sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess_options.enable_cpu_mem_arena = False

        session = ort.InferenceSession(
            model_path,
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        return session

    @staticmethod
    def _resolve_ort_threads(is_batch: bool) -> int:
        env_raw = os.environ.get("DMD_ORT_THREADS") or os.environ.get("OMP_NUM_THREADS")
        if env_raw:
            try:
                return max(1, min(8, int(env_raw)))
            except ValueError:
                pass
        cpu_cores = os.cpu_count() or 4
        if is_batch:
            return max(1, min(2, cpu_cores // 2))
        return min(4, max(1, cpu_cores))

    def _try_load_onnx(self) -> None:
        with self._session_lock:
            self._onnx_session_fast = _FrameDetector._shared_session_fast
            self._onnx_session_batch = _FrameDetector._shared_session_batch
            self._model_h = _FrameDetector._shared_model_h
            self._model_w = _FrameDetector._shared_model_w
            if _FrameDetector._shared_model_checked:
                self._model_path = _FrameDetector._shared_model_path
                self.model_type = _FrameDetector._shared_model_type
                return

            try:
                model_path = _ensure_yolo_model()
                _FrameDetector._shared_model_checked = True
                _FrameDetector._shared_model_path = model_path
                _FrameDetector._shared_model_type = "onnx" if model_path else ""
                self._model_path = model_path
                self.model_type = _FrameDetector._shared_model_type
            except Exception:
                _FrameDetector._shared_model_checked = True
                _FrameDetector._shared_model_path = None
                _FrameDetector._shared_model_type = ""
                self._model_path = None
                self.model_type = ""

    def _get_active_session(self, is_batch: bool = False):
        if is_batch and self._onnx_session_batch is not None:
            return self._onnx_session_batch
        if not is_batch and self._onnx_session_fast is not None:
            return self._onnx_session_fast

        with self._session_lock:
            if is_batch and _FrameDetector._shared_session_batch is not None:
                self._onnx_session_batch = _FrameDetector._shared_session_batch
                self._model_h = _FrameDetector._shared_model_h
                self._model_w = _FrameDetector._shared_model_w
                return self._onnx_session_batch
            if not is_batch and _FrameDetector._shared_session_fast is not None:
                self._onnx_session_fast = _FrameDetector._shared_session_fast
                self._model_h = _FrameDetector._shared_model_h
                self._model_w = _FrameDetector._shared_model_w
                return self._onnx_session_fast

            model_path = getattr(self, "_model_path", None) or _FrameDetector._shared_model_path
            if not model_path:
                return None

            try:
                threads = self._resolve_ort_threads(is_batch=is_batch)
                session = self._create_session(model_path, threads)
                inputs = session.get_inputs()[0]
                model_h, model_w = inputs.shape[2], inputs.shape[3]
                if not isinstance(model_h, int) or not isinstance(model_w, int):
                    model_h, model_w = 640, 640
                _FrameDetector._shared_model_h = model_h
                _FrameDetector._shared_model_w = model_w
                self._model_h = model_h
                self._model_w = model_w
                if is_batch:
                    _FrameDetector._shared_session_batch = session
                    self._onnx_session_batch = session
                else:
                    _FrameDetector._shared_session_fast = session
                    self._onnx_session_fast = session
                return session
            except Exception:
                return None

    def _detect_yolo(self, frame: np.ndarray, min_conf: float = _YOLO_CONF_THRESH,
                     roi_persistence_score: float = 1.0, platformer_mode: bool = False,
                     expected_floor_y: Optional[float] = None, is_batch: bool = False,
                     expected_cx: Optional[float] = None,
                     expected_cy: Optional[float] = None) -> Optional[BoundingBox]:
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

        if platformer_mode:
            effective_min_conf = max(0.18, min_conf * (1.0 - 0.30 * roi_persistence_score))
        else:
            effective_min_conf = max(0.05, min_conf * (1.0 - 0.5 * roi_persistence_score))
        mask = person_scores > effective_min_conf
        if not np.any(mask):
            return None

        if platformer_mode:
            boxes_bottom = boxes_raw[:, 1] + boxes_raw[:, 3] / 2.0
            bottomness = boxes_bottom / float(self._model_h)
            bw_norm = boxes_raw[:, 2] / float(self._model_w)
            bh_norm = boxes_raw[:, 3] / float(self._model_h)
            area_norm = bw_norm * bh_norm
            aspect_wh = boxes_raw[:, 2] / np.maximum(1.0, boxes_raw[:, 3])

            # Reject wide horizontal ground/HUD scroll bands, bulky background scenery
            # pareidolia (e.g. cave rock arches spanning >40% screen width or >22% screen area),
            # and bottom-border slabs.
            wide_band = (bw_norm > 0.40) & (aspect_wh > 2.4)
            bulky_scenery = (bw_norm > 0.40) | (area_norm > 0.22)
            bottom_slab = (bottomness >= 0.98) & (bw_norm > 0.24) & (aspect_wh > 1.8)
            mask = mask & ~wide_band & ~bulky_scenery & ~bottom_slab

            # Playfield-balanced vertical weighting: favor 0.45..0.88 (covering normal & thick ground)
            # and upper platforms (0.28..0.45) without boosting deep bottom-slab tile noise (>0.88).
            playfield_weight = np.where(
                (bottomness >= 0.45) & (bottomness <= 0.88),
                1.25,
                np.where(
                    (bottomness >= 0.28) & (bottomness < 0.45),
                    0.75 + 2.9 * (bottomness - 0.28),
                    np.where(
                        (bottomness > 0.88) & (bottomness <= 0.93),
                        0.85,
                        np.where(bottomness > 0.93, 0.40, 0.30),
                    ),
                ),
            )

            # 2D subject continuity: prevent argmax ping-pong between a jumping hero and
            # secondary enemies/hazards, while penalizing static outer-border props
            # (e.g. level-edge signposts at x < 7% or x > 93% of frame width).
            cx_norm = boxes_raw[:, 0] / float(self._model_w)
            edge_weight = np.where((cx_norm < 0.07) | (cx_norm > 0.93), 0.35, 1.0)
            exp_cx_norm = (
                float(expected_cx) / max(1.0, float(w)) if expected_cx is not None else -1.0
            )
            exp_cy_norm = (
                float(expected_cy) / max(1.0, float(h)) if expected_cy is not None else -1.0
            )
            near_tracked_2d = None
            dist_2d_arr = None
            if expected_cx is not None and 0.07 <= exp_cx_norm <= 0.93:
                cx_model = float(expected_cx) * (self._model_w / max(1.0, float(w)))
                dx_norm = np.abs(boxes_raw[:, 0] - cx_model) / float(self._model_w)
                if expected_cy is not None and 0.03 <= exp_cy_norm <= 0.96:
                    cy_model = float(expected_cy) * (self._model_h / max(1.0, float(h)))
                    dy_norm = np.abs(boxes_raw[:, 1] - cy_model) / float(self._model_h)
                    dist_2d_arr = np.hypot(dx_norm, dy_norm * 0.85)
                    near_tracked_2d = dist_2d_arr < 0.24
                    horiz_weight = (1.0 + 1.85 * np.exp(-dist_2d_arr * 4.5)) * edge_weight
                    playfield_weight = np.where(
                        near_tracked_2d & (bottomness <= 0.88),
                        np.maximum(playfield_weight, 1.15),
                        playfield_weight,
                    )
                else:
                    horiz_weight = (1.0 + 0.90 * np.exp(-dx_norm * 5.0)) * edge_weight
            else:
                horiz_weight = (1.0 + 0.30 * np.maximum(0.0, 0.5 - np.abs(cx_norm - 0.5))) * edge_weight

            if expected_floor_y is not None:
                sy_model = self._model_h / float(h)
                expected_floor_model = expected_floor_y * sy_model
                dist_to_floor = np.abs(boxes_bottom - expected_floor_model) / float(self._model_h)

                # Reject ONLY hard ceiling pareidolia: detections whose TOP is above the
                # established floor_y AND whose bottom is far from the floor (unless tracking
                # a hero actively climbing/jumping in that exact 2D neighborhood).
                boxes_top = boxes_raw[:, 1] - boxes_raw[:, 3] / 2.0
                is_above_floor = boxes_top < expected_floor_model
                is_far_from_floor = dist_to_floor > 0.65
                if near_tracked_2d is not None:
                    ceiling_block = is_above_floor & is_far_from_floor & ~near_tracked_2d
                else:
                    ceiling_block = is_above_floor & is_far_from_floor
                mask = mask & ~ceiling_block

                # Moderated floor affinity (~5x range instead of 95x): keeps grounded players
                # favored over background hops while guaranteeing that a real sprite on the
                # surface immediately breaks free if expected_floor_y ever drifted underground.
                is_playfield_drop = (
                    (boxes_bottom > expected_floor_model)
                    & (bottomness <= 0.93)
                    & (aspect_wh <= 1.35)
                )
                is_border_drop = (boxes_bottom > expected_floor_model) & (bottomness > 0.94)
                floor_weight = np.where(
                    is_playfield_drop,
                    0.45 + 2.4 * np.exp(-dist_to_floor * 3.8),
                    np.where(
                        is_border_drop,
                        0.08 + 1.8 * np.exp(-dist_to_floor * 7.5),
                        0.50 + 2.0 * np.exp(-dist_to_floor * 5.0),
                    ),
                )
                if near_tracked_2d is not None and dist_2d_arr is not None:
                    # Never penalize a tracked hero mid-jump relative to grounded enemies
                    airborne_guard = 1.05 + 1.25 * np.exp(-dist_2d_arr * 4.5)
                    floor_weight = np.where(
                        near_tracked_2d & (bottomness <= 0.90),
                        np.maximum(floor_weight, airborne_guard),
                        floor_weight,
                    )
                platformer_scores = person_scores * mask * playfield_weight * horiz_weight * floor_weight
            else:
                platformer_scores = person_scores * mask * playfield_weight * horiz_weight

            if not np.any(mask):
                return None

            best_i = int(np.argmax(platformer_scores))
        else:
            valid_indices = np.where(mask)[0]
            if len(valid_indices) == 0:
                return None
            
            valid_scores = person_scores[valid_indices]
            valid_boxes = boxes_raw[valid_indices]
            
            # Bias toward the center of the frame
            center_x_norm = valid_boxes[:, 0] / float(self._model_w)
            center_y_norm = valid_boxes[:, 1] / float(self._model_h)
            
            # Distance from center (0.5, 0.5)
            # Max possible distance from center is ~0.707
            dist_from_center = np.sqrt((center_x_norm - 0.5)**2 + (center_y_norm - 0.5)**2)
            
            # Apply a centering bonus (up to 1.5x multiplier for perfectly centered)
            center_bias = 1.0 + np.maximum(0.0, 0.5 - dist_from_center)
            
            centered_scores = valid_scores * center_bias
            best_idx_in_valid = int(np.argmax(centered_scores))
            best_i = valid_indices[best_idx_in_valid]

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
        if platformer_mode and bw >= 8 and bh > int(bw * 3.2):
            # Trim downward pillar/column bleed beneath a standing sprite anchored at head `y`
            bh = min(bh, max(8, int(round(bw * 2.4))))
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
                      is_batch: bool = False,
                      expected_cx: Optional[float] = None,
                      expected_cy: Optional[float] = None) -> Optional[BoundingBox]:
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
                                  is_batch=is_batch,
                                  expected_cx=expected_cx,
                                  expected_cy=expected_cy)

    def _strip_wide_platformer_bands(self, mask: np.ndarray, frame_w: int) -> np.ndarray:
        """Bridge horizontal brick/mortar gaps along X only, then strip wide scroll bands."""
        cv2 = self.cv2
        gap_w = max(9, int(frame_w * 0.065))
        gap_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (gap_w, 1))
        band_probe = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, gap_kernel)
        band_w = max(16, int(frame_w * 0.38))
        horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (band_w, 3))
        wide_bands = cv2.morphologyEx(band_probe, cv2.MORPH_OPEN, horiz_kernel)
        stripped = cv2.bitwise_and(mask, cv2.bitwise_not(wide_bands))
        return stripped if cv2.countNonZero(stripped) > 0 else mask

    def _build_scroll_compensated_mask(
        self, prev_gray: np.ndarray, gray: np.ndarray
    ) -> Optional[np.ndarray]:
        """
        Estimate global 2D background camera scroll `(bg_dx, bg_dy)` and extract sprites moving
        independently of the scrolling background (pipes, clouds, coral reefs, tile walls).
        """
        cv2 = self.cv2
        frame_h, frame_w = gray.shape[:2]
        if frame_w < 96 or frame_h < 80:
            self.last_bg_scroll = (0.0, 0.0, 0.0)
            return None
        y0 = int(frame_h * 0.14)
        play_h = frame_h - y0
        if play_h < 48:
            self.last_bg_scroll = (0.0, 0.0, 0.0)
            return None

        try:
            s_prev = cv2.resize(prev_gray[y0:, :], (128, 96), interpolation=cv2.INTER_AREA).astype(np.float32)
            s_curr = cv2.resize(gray[y0:, :], (128, 96), interpolation=cv2.INTER_AREA).astype(np.float32)
            if self._scroll_window is None or self._scroll_window.shape != (96, 128):
                self._scroll_window = cv2.createHanningWindow((128, 96), cv2.CV_32F)
            (dx_s, dy_s), resp = cv2.phaseCorrelate(s_prev, s_curr, self._scroll_window)
            bg_dx = float(dx_s) * (float(frame_w) / 128.0)
            bg_dy = float(dy_s) * (float(play_h) / 96.0)
            self.last_bg_scroll = (bg_dx, bg_dy, float(resp))
        except Exception:
            self.last_bg_scroll = (0.0, 0.0, 0.0)
            return None

        scroll_mag = math.hypot(bg_dx, bg_dy)
        max_scroll = max(float(frame_w), float(frame_h)) * 0.25
        if resp < 0.30 or scroll_mag < 2.5 or scroll_mag > max_scroll:
            return None

        warp_mat = np.float32([[1.0, 0.0, bg_dx], [0.0, 1.0, bg_dy]])
        aligned_prev = cv2.warpAffine(
            prev_gray,
            warp_mat,
            (frame_w, frame_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        res_diff = cv2.absdiff(gray, aligned_prev)
        bx = min(frame_w // 3, int(math.ceil(abs(bg_dx))) + 2)
        by = min(frame_h // 3, int(math.ceil(abs(bg_dy))) + 2)
        if bg_dx > 0.5 and bx > 0:
            res_diff[:, :bx] = 0
        elif bg_dx < -0.5 and bx > 0:
            res_diff[:, frame_w - bx :] = 0
        if bg_dy > 0.5 and by > 0:
            res_diff[:by, :] = 0
        elif bg_dy < -0.5 and by > 0:
            res_diff[frame_h - by :, :] = 0
        # Mask static top HUD score/timer row flicker during camera scroll
        res_diff[: int(frame_h * 0.11), :] = 0

        _, smask = cv2.threshold(cv2.GaussianBlur(res_diff, (5, 5), 0), 24, 255, cv2.THRESH_BINARY)
        # Suppress empty background ghost holes left at the sprite's previous world position by
        # requiring current-frame spatial detail (sprite edges/silhouette present in `gray`).
        grad_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, grad_k)
        _, detail_mask = cv2.threshold(grad, 14, 255, cv2.THRESH_BINARY)
        k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        detail_mask = cv2.dilate(detail_mask, k5, iterations=2)
        smask = cv2.bitwise_and(smask, detail_mask)
        smask = cv2.morphologyEx(smask, cv2.MORPH_OPEN, k5)
        smask = cv2.morphologyEx(smask, cv2.MORPH_DILATE, k5, iterations=2)

        nz = cv2.countNonZero(smask)
        if nz <= 0 or nz > int(frame_w * frame_h * 0.28):
            # Reject global multi-layer parallax shimmer floods
            return None
        return self._strip_wide_platformer_bands(smask, frame_w)

    def detect_motion(self, frame: np.ndarray, platformer_mode: bool = False,
                      expected_floor_y: Optional[float] = None,
                      expected_cx: Optional[float] = None,
                      expected_cy: Optional[float] = None,
                      expected_h: Optional[float] = None) -> Optional[BoundingBox]:
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None or self.prev_gray.shape != gray.shape:
            self.prev_gray = gray
            self.last_bg_scroll = (0.0, 0.0, 0.0)
            return None

        prev_gray_ref = self.prev_gray
        diff = cv2.absdiff(gray, prev_gray_ref)
        self.prev_gray = gray
        blur = cv2.GaussianBlur(diff, (7, 7), 0)
        _, mask = cv2.threshold(blur, 24, 255, cv2.THRESH_BINARY)

        fg = self.bg_sub.apply(frame)
        mask = cv2.bitwise_and(mask, fg)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

        frame_h, frame_w = frame.shape[:2]
        scroll_comp_mask: Optional[np.ndarray] = None
        if platformer_mode:
            scroll_comp_mask = self._build_scroll_compensated_mask(prev_gray_ref, gray)
            # Reject global camera flashes before band suppression
            if cv2.countNonZero(mask) > int(frame_w * frame_h * 0.70):
                if scroll_comp_mask is None:
                    return None
                mask = scroll_comp_mask
            else:
                mask = self._strip_wide_platformer_bands(mask, frame_w)

        def score_contour(c):
            area = cv2.contourArea(c)
            if area < 100.0 if platformer_mode else area < 120.0:
                return 0.0
            x, y, w, h = cv2.boundingRect(c)
            # Reject full-frame camera scroll / global flash artifacts (>92% width and >85% height)
            if w > frame_w * 0.92 and h > frame_h * 0.85:
                return 0.0
            if not platformer_mode and (w * h) < (frame_w * frame_h * 0.015):
                return 0.0
            if platformer_mode:
                if (w > frame_w * 0.72 and h > frame_h * 0.65) or h > frame_h * 0.58:
                    return 0.0
                if w > frame_w * 0.48 and h > frame_h * 0.42:
                    return 0.0
                bottom_y = y + h
                if bottom_y < frame_h * 0.12:
                    return 0.0
                aspect_wh = float(w) / max(1.0, float(h))
                # Reject wide horizontal ground/HUD scroll bands and thick bottom-border slabs
                if w > frame_w * 0.40 and aspect_wh > 2.4:
                    return 0.0
                if bottom_y >= frame_h * 0.98 and w > frame_w * 0.24 and aspect_wh > 1.8:
                    return 0.0
                if bottom_y >= frame_h * 0.98 and w > frame_w * 0.42 and aspect_wh > 1.35:
                    return 0.0

                eff_area = min(float(area), max(350.0, float(frame_w * frame_h) * 0.0040))
                aspect_hw = float(h) / max(1.0, float(w))
                if 0.60 <= aspect_hw <= 2.6:
                    shape_weight = 1.35
                elif 0.35 <= aspect_hw <= 3.2:
                    shape_weight = 1.0
                else:
                    shape_weight = 0.25

                # Scale consistency against established hero height: demote tiny projectiles,
                # bubbles, shells, coins, or fireballs (<48% of hero height) and oversized props.
                scale_weight = 1.0
                if expected_h is not None and float(expected_h) >= 16.0:
                    h_ratio = float(h) / float(expected_h)
                    if h_ratio < 0.48:
                        scale_weight = 0.35
                    elif 0.62 <= h_ratio <= 1.50:
                        scale_weight = 1.22
                    elif h_ratio > 2.10:
                        scale_weight = 0.55

                # Chromatic sprite salience: in 8/16-bit platformers, player sprites use vivid
                # saturated palettes whereas mechanical hazards (sawblades, chains, rotating stone
                # platforms, brick walls) are achromatic grey/white. Uniform grayscale frames keep
                # identical relative scores across all contours.
                sat_weight = 1.0
                if frame.ndim == 3 and frame.shape[2] == 3 and w >= 6 and h >= 6:
                    sub_bgr = frame[y : y + h, x : x + w]
                    b_ch = sub_bgr[:, :, 0].astype(np.int16)
                    g_ch = sub_bgr[:, :, 1].astype(np.int16)
                    r_ch = sub_bgr[:, :, 2].astype(np.int16)
                    c_max = np.maximum(np.maximum(r_ch, g_ch), b_ch)
                    c_min = np.minimum(np.minimum(r_ch, g_ch), b_ch)
                    chroma = c_max - c_min
                    active_px = c_max > 28
                    mean_chroma = float(np.mean(chroma[active_px])) if np.any(active_px) else 0.0
                    if mean_chroma < 18.0:
                        sat_weight = 0.72
                    elif mean_chroma >= 55.0:
                        sat_weight = 1.42
                    else:
                        sat_weight = 0.72 + 0.70 * ((mean_chroma - 18.0) / 37.0)

                bottomness = bottom_y / float(frame_h)
                is_initial_lock = expected_floor_y is None and expected_cx is None
                if 0.55 <= bottomness <= 0.88:
                    playfield_weight = 1.60 if is_initial_lock else 1.25
                elif 0.45 <= bottomness < 0.55:
                    playfield_weight = 1.05 if is_initial_lock else 1.25
                elif 0.25 <= bottomness < 0.45:
                    playfield_weight = (0.60 if is_initial_lock else 0.75) + 2.2 * (bottomness - 0.25)
                elif 0.88 < bottomness <= 0.94:
                    playfield_weight = 0.85
                elif bottomness > 0.94:
                    playfield_weight = 0.25
                else:
                    playfield_weight = 0.55

                near_tracked = False
                dist_2d = 1.0
                if expected_cx is not None:
                    cx_c = float(x) + float(w) * 0.5
                    dx_norm = abs(cx_c - float(expected_cx)) / max(1.0, float(frame_w))
                    if expected_cy is not None:
                        cy_c = float(y) + float(h) * 0.5
                        dy_norm = abs(cy_c - float(expected_cy)) / max(1.0, float(frame_h))
                        dist_2d = math.hypot(dx_norm, dy_norm * 0.85)
                        near_tracked = dist_2d < 0.24
                        horiz_weight = 1.0 + 2.10 * math.exp(-dist_2d * 4.5)
                        if near_tracked and bottomness <= 0.88:
                            playfield_weight = max(playfield_weight, 1.15)
                    else:
                        horiz_weight = 1.0 + 0.90 * math.exp(-dx_norm * 5.0)
                else:
                    horiz_weight = 1.0

                base_score = eff_area * shape_weight * scale_weight * sat_weight * playfield_weight * horiz_weight
                if expected_floor_y is not None:
                    dist_to_floor = abs(bottom_y - expected_floor_y) / float(frame_h)
                    if bottom_y > expected_floor_y and bottomness <= 0.94:
                        fw_mult = 0.45 + 2.4 * math.exp(-dist_to_floor * 3.8)
                    elif bottom_y > expected_floor_y:
                        fw_mult = 0.08 + 1.8 * math.exp(-dist_to_floor * 7.5)
                    else:
                        fw_mult = 0.50 + 2.0 * math.exp(-dist_to_floor * 5.0)
                    if near_tracked and bottomness <= 0.90:
                        fw_mult = max(fw_mult, 1.05 + 1.25 * math.exp(-dist_2d * 4.5))
                    return base_score * fw_mult
                return base_score
            return area

        if scroll_comp_mask is not None:
            sc_contours, _ = cv2.findContours(
                scroll_comp_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            valid_sc = [
                c for c in sc_contours
                if cv2.boundingRect(c)[2] <= frame_w * 0.36
                and cv2.boundingRect(c)[3] <= frame_h * 0.46
            ]
            if valid_sc:
                c_sc_best = max(valid_sc, key=score_contour)
                if score_contour(c_sc_best) > 0.0:
                    sx, sy, sw, sh = cv2.boundingRect(c_sc_best)
                    return BoundingBox(int(sx), int(sy), int(sw), int(sh))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

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
