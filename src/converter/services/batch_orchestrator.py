"""
BatchOrchestrator — implements IBatchOrchestrator.

Handles parallel batch-conversion of entire folders, with optional
two-phase pipeline when Auto Action is enabled (Phase 1: OpenCV
preprocessing, Phase 2: FFmpeg conversion).
"""
import os
import concurrent.futures
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..interfaces import IBatchOrchestrator
from ..ffmpeg_utils import get_metadata

logger = logging.getLogger(__name__)


class BatchOrchestrator(IBatchOrchestrator):
    """Orchestrates parallel batch processing of video/GIF files."""

    SUPPORTED_EXTENSIONS = {
        ".gif", ".mp4", ".avi", ".mkv", ".mov", ".webm",
        ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"
    }

    def __init__(self, process_file_fn: Callable, preprocess_fn: Optional[Callable] = None):
        """
        Args:
            process_file_fn: The function to call for each file (e.g. process_file from core.py).
            preprocess_fn:   Optional auto-action preprocessor to run in Phase 1.
        """
        self._process_file = process_file_fn
        self._preprocess = preprocess_fn

    def process_folder(
        self,
        input_folder: str,
        output_folder: str,
        params: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
        callback: Optional[Callable] = None,
    ) -> List[Tuple[bool, str]]:
        """Batch-convert all supported files in *input_folder* to DMD GIFs."""
        os.makedirs(str(output_folder), exist_ok=True)

        files = [
            f for f in os.listdir(str(input_folder))
            if Path(f).suffix.lower() in self.SUPPORTED_EXTENSIONS
        ]
        if not files:
            logger.warning("No supported files found in %s", input_folder)
            return []

        max_workers = params.get("max_workers", 2)
        auto_enabled = bool(params.get("auto_action_enabled", False))

        def log(msg, level="info"):
            getattr(logger, level)(msg)
            if callback:
                callback(msg, level)

        # ── Single-phase path (auto_action disabled) ──────────────────────────
        if not auto_enabled or self._preprocess is None:
            total = len(files)
            done_count = [0]
            import threading
            done_lock = threading.Lock()

            def _one(filename):
                src = os.path.join(str(input_folder), filename)
                out = os.path.join(str(output_folder), Path(filename).stem + ".gif")
                result = self._process_file(src, out, params=params, callback=callback)
                with done_lock:
                    done_count[0] += 1
                    current = done_count[0]
                if progress_callback:
                    try:
                        progress_callback(current, total)
                    except Exception:
                        pass
                return result

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                return list(ex.map(_one, files))

        # ── Two-phase path (auto_action enabled) ──────────────────────────────
        log(f"[BATCH] Phase 1/2 — auto_action preprocessing ({len(files)} files, {max_workers} workers)")

        def _run_preprocess(filename):
            src = os.path.join(str(input_folder), filename)
            ok, pre_src, msg = self._preprocess(src)
            if ok and pre_src:
                log(f"[ACTION] {filename} — {msg}")
                return filename, pre_src, os.path.dirname(pre_src)
            else:
                log(f"[ACTION] {filename} — fallback: {msg}", "warning")
                return filename, src, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            pre_results = list(ex.map(_run_preprocess, files))

        p_no_action = {**params, "auto_action_enabled": False}
        log(f"[BATCH] Phase 2/2 — ffmpeg conversion ({len(files)} files, {max_workers} workers)")

        import threading
        total_2 = len(files)
        done_count2 = [0]
        done_lock2 = threading.Lock()

        def _convert(item):
            filename, pre_src, tmpdir = item
            out = os.path.join(str(output_folder), Path(filename).stem + ".gif")
            success, msg = self._process_file(pre_src, out, params=p_no_action, callback=callback)
            if tmpdir and os.path.isdir(tmpdir):
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            with done_lock2:
                done_count2[0] += 1
                current = done_count2[0]
            if progress_callback:
                try:
                    progress_callback(current, total_2)
                except Exception:
                    pass
            return success, msg

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_convert, pre_results))
