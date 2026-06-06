"""
ConversionController — implements IController.

Handles all conversion-related user actions:
  - Starting a single-file or batch conversion
  - Cancelling an in-flight conversion
  - Reporting progress back to the view
"""
import logging
import threading
from typing import Any, Callable, Optional

from ..interfaces import IController, IView, IModel

logger = logging.getLogger(__name__)


class ConversionController(IController):
    """
    Manages conversion jobs, delegating to the converter services.
    Keeps all threading logic out of the view.
    """

    def __init__(self):
        self._view: Optional[IView] = None
        self._model: Optional[IModel] = None
        self._active_thread: Optional[threading.Thread] = None
        self._cancel_flag: bool = False

    def bind(self, view: IView, model: IModel) -> None:
        self._view = view
        self._model = model

    def on_action(self, action: str, payload: Any = None) -> None:
        if action == "convert_all":
            self._start_conversion(payload)
        elif action == "cancel":
            self._cancel_conversion()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _start_conversion(self, files: Optional[list] = None) -> None:
        if self._active_thread and self._active_thread.is_alive():
            logger.warning("Conversion already in progress.")
            return
        self._cancel_flag = False
        self._active_thread = threading.Thread(
            target=self._run_conversion,
            args=(files,),
            daemon=True,
        )
        self._active_thread.start()

    def _cancel_conversion(self) -> None:
        self._cancel_flag = True
        logger.info("Conversion cancellation requested.")

    def _run_conversion(self, files: Optional[list]) -> None:
        """Background worker that calls the converter for each file."""
        from src.converter.core import process_file

        if self._model is None:
            return

        params = self._model.build_params() if hasattr(self._model, "build_params") else {}
        output_dir = self._model.get("v_output_dir", "")
        trim_start = self._model.get("v_trim_start", 0.0)
        trim_end   = self._model.get("v_trim_end", 0.0)

        files = files or []
        total = len(files)

        for i, (iid, src_path) in enumerate(files):
            if self._cancel_flag:
                logger.info("Conversion cancelled at file %d/%d", i + 1, total)
                break

            import os
            from pathlib import Path
            filename = os.path.basename(src_path)
            out_name = Path(filename).stem + ".gif"
            out_path = os.path.join(output_dir, out_name) if output_dir else \
                       os.path.join(os.path.dirname(src_path), "dmd_out", out_name)

            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            start_s = trim_start if trim_start > 0 else None
            end_s   = trim_end   if trim_end   > 0 else None

            def _callback(msg: str, level: str = "info") -> None:
                if self._view and hasattr(self._view, "log"):
                    self._view.log(msg, level)

            success, msg = process_file(
                src_path, out_path, params=params,
                start_s=start_s, end_s=end_s,
                callback=_callback,
            )

            if self._view and hasattr(self._view, "on_file_converted"):
                self._view.on_file_converted(iid, src_path, out_path, success, msg)
