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
        from src.engine.conversion.core import process_file

        if self._model is None:
            return

        params = self._model.build_params() if hasattr(self._model, "build_params") else {}
        output_dir = self._model.get("v_output_dir", "")
        trim_start = self._model.get("v_trim_start", 0.0)
        trim_end   = self._model.get("v_trim_end", 0.0)

        files = files or []
        
        from src.engine.conversion.services.job_expander import expand_conversion_jobs
        jobs = expand_conversion_jobs(files, params)
        total_jobs = len(jobs)

        for i, (iid, src_path, job_params, suffix) in enumerate(jobs):
            if self._cancel_flag:
                logger.info("Conversion cancelled at job %d/%d", i + 1, total_jobs)
                break

            import os
            from pathlib import Path
            filename = os.path.basename(src_path)
            
            # Apply suffix if we have one (e.g. _top1 from auto-cutter)
            base_name = Path(filename).stem
            if suffix:
                base_name += suffix
            out_name = base_name + ".gif"
            
            out_path = os.path.join(output_dir, out_name) if output_dir else \
                       os.path.join(os.path.dirname(src_path), "dmd_out", out_name)

            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            start_s = job_params.get("trim_start")
            end_s   = job_params.get("trim_end")
            
            # Fallback to model values if not in job_params explicitly
            if start_s is None: start_s = trim_start if trim_start > 0 else None
            if end_s is None:   end_s   = trim_end   if trim_end   > 0 else None

            def _callback(msg: str, level: str = "info") -> None:
                if self._view:
                    # Pass the message to the view
                    self._view.after(0, lambda m=msg, l=level: getattr(self._view, "_log")(m, l))
                else:
                    getattr(logger, level)(msg)

            # Pre-processing for Auto Action
            pre_src = src_path
            tmpdir = None
            auto_action_was_enabled = job_params.get("auto_action_enabled", False)

            if auto_action_was_enabled:
                from src.engine.auto_action.main import preprocess_video_for_dmd
                ok, p_src, msg = preprocess_video_for_dmd(src_path, callback=_callback, trim_start=start_s, trim_end=end_s)
                if ok and p_src:
                    pre_src = p_src
                    tmpdir = os.path.dirname(pre_src)
                    start_s = None
                    end_s = None
                else:
                    logger.warning("Auto action failed: %s", msg)

            p_no_action = {**job_params, "auto_action_enabled": False}

            success, msg = process_file(
                pre_src,
                out_path,
                trim_start=start_s,
                trim_end=end_s,
                params=p_no_action,
                callback=_callback
            )

            if tmpdir and os.path.isdir(tmpdir):
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

            if self._view:
                if success:
                    self._view.after(0, lambda p=out_path, _id=iid: self._view.on_conversion_success(p, _id))
                else:
                    self._view.after(0, lambda e=msg, _id=iid: self._view.on_conversion_error(e, _id))
                # Update progress based on jobs
                self._view.after(0, lambda c=i+1, t=total_jobs: self._view.on_conversion_progress(c, t))

        if self._view:
            self._view.after(0, self._view.on_conversion_finished)
        self._active_thread = None
