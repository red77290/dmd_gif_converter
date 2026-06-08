"""GIF search service — infrastructure layer (HTTP, external API calls).

Supports DuckDuckGo (free), Tenor (API key required) and Giphy (API key required).
This module contains ALL network I/O for GIF searching.  No UI / Tkinter code here.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional

from .search_models import GifSearchFilter, GifSearchResult
from src.converter.interfaces import ISearchEngine
from .search_engines import (
    DuckDuckGoSearchEngine,
    TenorSearchEngine,
    GiphySearchEngine,
)

logger = logging.getLogger(__name__)

# ── Optional dependencies ─────────────────────────────────────────────────────
try:
    import requests as _requests

    try:
        from ddgs import DDGS as _DDGS  # new name (v9+)
    except ImportError:
        from duckduckgo_search import DDGS as _DDGS  # legacy name (<=8.x)

    GIF_SEARCH_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _DDGS = None  # type: ignore[assignment]
    GIF_SEARCH_AVAILABLE = False


# ── Service ───────────────────────────────────────────────────────────────────

class GifSearchService:
    """Fetches GIF URLs from DuckDuckGo, Tenor or Giphy and downloads them.

    All network I/O lives here so that higher-level code (UI, CLI, API …)
    only needs to call :meth:`search` and :meth:`download`.
    """

    def __init__(self) -> None:
        self.engines: dict[str, ISearchEngine] = {
            "DuckDuckGo": DuckDuckGoSearchEngine(),
            "Tenor": TenorSearchEngine(),
            "Giphy": GiphySearchEngine(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        keyword: str,
        qty: int,
        engine: str,
        filters: GifSearchFilter,
        api_key: str = "",
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> List[GifSearchResult]:
        """Return up to *qty* :class:`GifSearchResult` objects.

        :param keyword:     Search terms.
        :param qty:         Maximum number of results to return.
        :param engine:      ``"DuckDuckGo"``, ``"Tenor"`` or ``"Giphy"``.
        :param filters:     Dimension / ratio filters.
        :param api_key:     Required for Tenor and Giphy engines.
        :param cancel_flag: Callable returning ``True`` to abort early.
        :raises RuntimeError: If the required packages are not installed.
        """
        if not GIF_SEARCH_AVAILABLE:
            raise RuntimeError(
                "GIF Search requires extra packages.\n\n"
                "Install with:\n  pip install duckduckgo-search requests\n\n"
                "Or re-run ./launch_ui.sh — it installs automatically."
            )

        def _cancelled() -> bool:
            return cancel_flag() if cancel_flag else False

        search_engine = self.engines.get(engine)
        if search_engine:
            return search_engine.search(keyword, qty, filters, api_key, _cancelled)
        
        logger.warning("Unknown search engine: %s", engine)
        return []

    def download(
        self,
        result: GifSearchResult,
        dest_dir: str,
        index: int,
        keyword: str,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> Optional[str]:
        """Download one GIF to *dest_dir*.

        :returns: Local file path on success, ``None`` if cancelled or skipped.
        :raises requests.exceptions.RequestException: On network error.
        """
        if not GIF_SEARCH_AVAILABLE or _requests is None:
            raise RuntimeError("requests is not available")

        def _cancelled() -> bool:
            return cancel_flag() if cancel_flag else False

        image_url = result.url
        basename = os.path.basename(image_url).split("?")[0]
        if not basename or "." not in basename:
            basename = f"{keyword.replace(' ', '_')}_{index + 1}.gif"
        if not basename.lower().endswith(".gif"):
            basename = os.path.splitext(basename)[0] + ".gif"

        safe_name = "".join(
            c if c.isalnum() or c in ("_", "-", ".") else "_" for c in basename
        )
        file_path = os.path.join(dest_dir, safe_name)
        if os.path.exists(file_path):
            stem, ext = os.path.splitext(safe_name)
            file_path = os.path.join(dest_dir, f"{stem}_{index}{ext}")

        resp = _requests.get(image_url, stream=True, timeout=12)
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if ct and "image" not in ct and "octet-stream" not in ct:
            logger.debug("Skipping non-image URL: %s (CT=%s)", image_url, ct)
            return None

        with open(file_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if _cancelled():
                    break
                fh.write(chunk)

        if _cancelled():
            try:
                os.remove(file_path)
            except OSError:
                pass
            return None

        return file_path
