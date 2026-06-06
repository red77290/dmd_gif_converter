"""
PreviewController — implements IController.

Handles all preview-related user actions:
  - Scheduling and debouncing DMD preview refresh
  - Managing source/auto-action/DMD animation loops
  - Cancelling in-flight preview renders
"""
import logging
import threading
from typing import Any, Optional

from ..interfaces import IController, IView, IModel

logger = logging.getLogger(__name__)


class PreviewController(IController):
    """
    Manages real-time DMD preview rendering.
    Debounces rapid parameter changes to avoid flooding the render thread.
    """

    DEBOUNCE_MS = 2000  # ms to wait after last change before re-rendering

    def __init__(self):
        self._view: Optional[IView] = None
        self._model: Optional[IModel] = None
        self._pending_job = None        # tkinter after() job id
        self._render_lock = threading.Lock()
        self._rendering = False

    def bind(self, view: IView, model: IModel) -> None:
        self._view = view
        self._model = model

    def on_action(self, action: str, payload: Any = None) -> None:
        if action == "schedule_refresh":
            self._schedule_refresh()
        elif action == "stop":
            self._cancel_pending()

    def schedule_refresh(self) -> None:
        """External entry point: debounce and schedule a preview render."""
        self._schedule_refresh()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        if self._view is None:
            return
        # Cancel any previously-pending refresh
        if self._pending_job is not None:
            try:
                self._view.after_cancel(self._pending_job)  # type: ignore[union-attr]
            except Exception:
                pass
        # Schedule a new one
        self._pending_job = self._view.after(  # type: ignore[union-attr]
            self.DEBOUNCE_MS, self._trigger_refresh
        )

    def _cancel_pending(self) -> None:
        if self._pending_job is not None and self._view is not None:
            try:
                self._view.after_cancel(self._pending_job)  # type: ignore[union-attr]
            except Exception:
                pass
            self._pending_job = None

    def _trigger_refresh(self) -> None:
        """Actually kick off the DMD preview render (called after debounce)."""
        self._pending_job = None
        if self._view and hasattr(self._view, "_generate_dmd_preview"):
            self._view._generate_dmd_preview()  # type: ignore[union-attr]
