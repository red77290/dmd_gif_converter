"""
Debug Tooling — Score timelines, signal timelines, ROI overlays, decision logs.

PURPOSE
-------
Help developers understand WHY scoring decisions are made.

All tools in this module are purely OBSERVATIONAL.
They produce structured data or annotated frames for inspection.
None of them modify any pipeline behavior.

COMPONENTS
----------
ScoreTimeline    — map frame_idx → FinalScore, exportable as JSON/CSV
SignalTimeline   — map frame_idx → FrameSignalScore (all fields), exportable
ROIOverlayRenderer — draw ROI bounding boxes on frames, return annotated list
DecisionLogger   — per-frame structured log of all bonuses and penalties

INTEGRATION
-----------
Purely additive. No existing code is modified.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from .signal_scoring_engine import FrameSignalScore
from .final_scoring_engine import FinalScore

logger = logging.getLogger(__name__)

BoundingBox = Tuple[int, int, int, int]  # (x, y, w, h)


# ---------------------------------------------------------------------------
# Score Timeline
# ---------------------------------------------------------------------------

class ScoreTimeline:
    """
    Records FinalScore for each frame in chronological order.

    Usage
    -----
    timeline = ScoreTimeline()
    for idx, signal in enumerate(signals):
        final = engine.score_frame(signal)
        timeline.record(idx, final)
    timeline.export_json("score_timeline.json")
    timeline.export_csv("score_timeline.csv")
    """

    def __init__(self) -> None:
        self._records: List[Dict] = []

    def record(self, frame_idx: int, final_score: FinalScore) -> None:
        """Add a FinalScore record."""
        self._records.append({
            "frame_idx": frame_idx,
            "score": final_score.score,
            "selected": final_score.selected,
            "ranking": final_score.ranking,
            "strategy": final_score.strategy_name,
            "penalties": final_score.penalties,
            "bonuses": final_score.bonuses,
            "explanation": final_score.explanation,
        })

    def as_list(self) -> List[Dict]:
        """Return the raw list of records."""
        return list(self._records)

    def export_json(self, path: str) -> None:
        """Write timeline to a JSON file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._records, f, indent=2)
            logger.info("ScoreTimeline saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export ScoreTimeline JSON: %s", exc)

    def export_csv(self, path: str) -> None:
        """Write timeline to a CSV file."""
        if not self._records:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["frame_idx", "score", "selected", "ranking",
                                "strategy", "penalties", "bonuses", "explanation"]
                )
                writer.writeheader()
                for rec in self._records:
                    row = dict(rec)
                    row["penalties"] = ";".join(rec["penalties"])
                    row["bonuses"] = ";".join(rec["bonuses"])
                    writer.writerow(row)
            logger.info("ScoreTimeline CSV saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export ScoreTimeline CSV: %s", exc)


# ---------------------------------------------------------------------------
# Signal Timeline
# ---------------------------------------------------------------------------

class SignalTimeline:
    """
    Records FrameSignalScore for each frame in chronological order.

    Captures the full signal state for later visualization and analysis.

    Usage
    -----
    timeline = SignalTimeline()
    for idx, frame in enumerate(frames):
        signal = signal_engine.score_frame(frame, frame_idx=idx)
        timeline.record(signal)
    timeline.export_json("signal_timeline.json")
    """

    # Fields to export (excludes raw data like roi tuple for CSV friendliness)
    _SIGNAL_FIELDS = [
        "frame_idx",
        "is_dark",
        "has_detection",
        "motion_score",
        "optical_flow_score",
        "stability_score",
        "entropy_score",
        "contrast_score",
        "edge_density_score",
        "saliency_score",
        "subject_score",
        "face_score",
        "object_score",
        "subject_centering_score",
        "readability_score",
        "attention_score",
    ]

    def __init__(self) -> None:
        self._records: List[Dict] = []

    def record(self, signal: FrameSignalScore) -> None:
        """Add a FrameSignalScore record."""
        record = {k: getattr(signal, k, None) for k in self._SIGNAL_FIELDS}
        self._records.append(record)

    def as_list(self) -> List[Dict]:
        return list(self._records)

    def export_json(self, path: str) -> None:
        """Write signal timeline to JSON."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._records, f, indent=2)
            logger.info("SignalTimeline saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export SignalTimeline JSON: %s", exc)

    def export_csv(self, path: str) -> None:
        """Write signal timeline to CSV."""
        if not self._records:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._SIGNAL_FIELDS)
                writer.writeheader()
                for rec in self._records:
                    writer.writerow({
                        k: ("" if v is None else round(v, 4) if isinstance(v, float) else v)
                        for k, v in rec.items()
                    })
            logger.info("SignalTimeline CSV saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export SignalTimeline CSV: %s", exc)

    def get_field_series(self, field_name: str) -> List[Optional[float]]:
        """
        Extract a single signal field as a time series.

        Useful for plotting:
          motion_values = timeline.get_field_series("motion_score")
        """
        return [rec.get(field_name) for rec in self._records]


# ---------------------------------------------------------------------------
# ROI Overlay Renderer
# ---------------------------------------------------------------------------

class ROIOverlayRenderer:
    """
    Draw annotated bounding boxes on frames to visualize:
      - Detected ROI (from detector)
      - Tracked ROI (from tracker / camera rect)
      - Camera window (the output crop region)

    Returns annotated copies of frames — original frames are never modified.

    Usage
    -----
    renderer = ROIOverlayRenderer()
    annotated = renderer.render_frame(frame, detected_roi=roi, tracked_roi=cam_rect)
    annotated_sequence = renderer.render_sequence(frames, rois=...)
    """

    # BGR colors for each annotation layer
    COLOR_DETECTED: Tuple[int, int, int] = (0, 255, 0)    # Green
    COLOR_TRACKED: Tuple[int, int, int] = (255, 165, 0)   # Orange
    COLOR_CAMERA: Tuple[int, int, int] = (0, 128, 255)    # Blue
    COLOR_LABEL_BG: Tuple[int, int, int] = (0, 0, 0)      # Black

    def render_frame(
        self,
        frame: np.ndarray,
        detected_roi: Optional[BoundingBox] = None,
        tracked_roi: Optional[BoundingBox] = None,
        camera_rect: Optional[Tuple[float, float, float, float]] = None,
        frame_score: Optional[float] = None,
        frame_idx: Optional[int] = None,
    ) -> np.ndarray:
        """
        Annotate a single frame with ROI boxes and score.

        Parameters
        ----------
        frame : np.ndarray
            BGR source frame.
        detected_roi : (x, y, w, h) or None
            Bounding box from detector (IDetector output).
        tracked_roi : (x, y, w, h) or None
            Bounding box from tracker (may differ from detected).
        camera_rect : (cx, cy, cw, ch) or None
            Camera center/size tuple (as from CamRect in interfaces.py).
        frame_score : float or None
            FinalScore.score to display on the frame.
        frame_idx : int or None
            Frame index to display.
        """
        try:
            import cv2
        except ImportError:
            return frame.copy() if frame is not None else np.zeros((32, 128, 3), dtype=np.uint8)

        if frame is None or frame.size == 0:
            return np.zeros((32, 128, 3), dtype=np.uint8)

        annotated = frame.copy()

        # Detected ROI — green
        if detected_roi is not None:
            x, y, w, h = detected_roi
            cv2.rectangle(annotated, (x, y), (x + w, y + h), self.COLOR_DETECTED, 2)
            self._draw_label(annotated, "DET", x, y, self.COLOR_DETECTED, cv2)

        # Tracked ROI — orange (passed as (x, y, w, h))
        if tracked_roi is not None:
            x, y, w, h = tracked_roi
            cv2.rectangle(annotated, (x, y), (x + w, y + h), self.COLOR_TRACKED, 2)
            self._draw_label(annotated, "TRK", x, y + h, self.COLOR_TRACKED, cv2)

        # Camera window — blue (convert from CamRect to pixel rect)
        if camera_rect is not None:
            cx, cy, cw, ch = camera_rect
            fh, fw = frame.shape[:2]
            px = int(cx - cw / 2)
            py = int(cy - ch / 2)
            pw = int(cw)
            ph = int(ch)
            cv2.rectangle(
                annotated,
                (max(0, px), max(0, py)),
                (min(fw, px + pw), min(fh, py + ph)),
                self.COLOR_CAMERA, 1
            )
            self._draw_label(annotated, "CAM", max(0, px), max(0, py), self.COLOR_CAMERA, cv2)

        # Score overlay
        if frame_score is not None or frame_idx is not None:
            label_parts = []
            if frame_idx is not None:
                label_parts.append(f"#{frame_idx}")
            if frame_score is not None:
                label_parts.append(f"score={frame_score:.1f}")
            label = " ".join(label_parts)
            self._draw_label(annotated, label, 2, 2, (255, 255, 255), cv2)

        return annotated

    def render_sequence(
        self,
        frames: List[np.ndarray],
        detected_rois: Optional[List[Optional[BoundingBox]]] = None,
        tracked_rois: Optional[List[Optional[BoundingBox]]] = None,
        camera_rects: Optional[List[Optional[Tuple]]] = None,
        scores: Optional[List[Optional[float]]] = None,
    ) -> List[np.ndarray]:
        """
        Annotate a sequence of frames.

        Returns annotated copies. Original frames are unchanged.
        """
        n = len(frames)
        detected_rois = detected_rois or [None] * n
        tracked_rois = tracked_rois or [None] * n
        camera_rects = camera_rects or [None] * n
        scores = scores or [None] * n

        return [
            self.render_frame(
                frames[i],
                detected_roi=detected_rois[i],
                tracked_roi=tracked_rois[i],
                camera_rect=camera_rects[i],
                frame_score=scores[i],
                frame_idx=i,
            )
            for i in range(n)
        ]

    @staticmethod
    def _draw_label(
        frame: np.ndarray,
        text: str,
        x: int,
        y: int,
        color: Tuple[int, int, int],
        cv2,
    ) -> None:
        """Draw a small label with black background at (x, y)."""
        scale = 0.35
        thickness = 1
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        # Background
        cv2.rectangle(frame, (x, y - th - 2), (x + tw + 2, y + 2), (0, 0, 0), -1)
        # Text
        cv2.putText(frame, text, (x + 1, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, thickness, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Decision Logger
# ---------------------------------------------------------------------------

class DecisionLogger:
    """
    Structured per-frame log of scoring decisions.

    Records a complete trace of every decision: what signals were used,
    what penalties and bonuses were applied, what the final verdict was,
    and why.

    Usage
    -----
    log = DecisionLogger()
    for idx, (signal, final) in enumerate(zip(signals, final_scores)):
        log.record(idx, signal, final)
    log.export_json("decisions.json")
    log.print_summary()
    """

    def __init__(self) -> None:
        self._entries: List[Dict] = []
        self._selected_count: int = 0
        self._dropped_count: int = 0

    def record(
        self,
        frame_idx: int,
        signal: FrameSignalScore,
        final: FinalScore,
    ) -> None:
        """Record a complete decision for a single frame."""
        entry = {
            "frame_idx": frame_idx,
            "verdict": "KEEP" if final.selected else "DROP",
            "score": final.score,
            "ranking": final.ranking,
            "strategy": final.strategy_name,
            "explanation": final.explanation,
            "penalties": final.penalties,
            "bonuses": final.bonuses,
            "signals": {
                "is_dark": signal.is_dark,
                "has_detection": signal.has_detection,
                "motion_score": signal.motion_score,
                "contrast_score": signal.contrast_score,
                "entropy_score": signal.entropy_score,
                "readability_score": signal.readability_score,
                "subject_score": signal.subject_score,
                "subject_centering_score": signal.subject_centering_score,
                "stability_score": signal.stability_score,
                "attention_score": signal.attention_score,
            },
        }
        self._entries.append(entry)

        if final.selected:
            self._selected_count += 1
        else:
            self._dropped_count += 1

    @property
    def selected_count(self) -> int:
        return self._selected_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def total_count(self) -> int:
        return len(self._entries)

    def export_json(self, path: str) -> None:
        """Write all decision entries to JSON."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "summary": {
                        "total": self.total_count,
                        "selected": self._selected_count,
                        "dropped": self._dropped_count,
                        "selection_rate": (
                            self._selected_count / max(1, self.total_count)
                        ),
                    },
                    "decisions": self._entries,
                }, f, indent=2)
            logger.info("DecisionLogger saved → %s", path)
        except Exception as exc:
            logger.error("Failed to export DecisionLogger JSON: %s", exc)

    def print_summary(self) -> None:
        """Print a concise summary to the logger."""
        total = self.total_count
        rate = self._selected_count / max(1, total) * 100.0
        logger.info(
            "DecisionLogger: %d frames | KEEP=%d (%.1f%%) | DROP=%d (%.1f%%)",
            total,
            self._selected_count, rate,
            self._dropped_count, 100.0 - rate,
        )
        # List unique penalty types
        penalty_counts: Dict[str, int] = {}
        for e in self._entries:
            for p in e.get("penalties", []):
                penalty_counts[p] = penalty_counts.get(p, 0) + 1
        if penalty_counts:
            logger.info("  Penalties applied: %s", penalty_counts)

        bonus_counts: Dict[str, int] = {}
        for e in self._entries:
            for b in e.get("bonuses", []):
                bonus_counts[b] = bonus_counts.get(b, 0) + 1
        if bonus_counts:
            logger.info("  Bonuses applied:   %s", bonus_counts)
