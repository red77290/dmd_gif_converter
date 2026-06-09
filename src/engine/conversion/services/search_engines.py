import abc
from typing import Callable, List

from .search_models import GifSearchFilter, GifSearchResult, check_ratio

try:
    import requests as _requests

    try:
        from ddgs import DDGS as _DDGS  # new name (v9+)
    except ImportError:
        from duckduckgo_search import DDGS as _DDGS  # legacy name (<=8.x)
except ImportError:
    _requests = None  # type: ignore[assignment]
    _DDGS = None  # type: ignore[assignment]


from src.engine.conversion.interfaces import ISearchEngine

class DuckDuckGoSearchEngine(ISearchEngine):
    """DuckDuckGo implementation of SearchEngine."""
    
    def search(
        self,
        keyword: str,
        qty: int,
        filters: GifSearchFilter,
        api_key: str,
        cancelled: Callable[[], bool],
    ) -> List[GifSearchResult]:
        if not _DDGS:
            return []
            
        results: List[GifSearchResult] = []
        for r in _DDGS().images(
            keyword + " gif",
            safesearch="off",
            type_image="gif",
            max_results=qty * 5,
        ):
            if cancelled() or len(results) >= qty:
                break
            try:
                w, h = int(r.get("width", 0)), int(r.get("height", 0))
            except (ValueError, TypeError):
                w, h = 0, 0
            if (
                w >= filters.min_width
                and h >= filters.min_height
                and check_ratio(w, h, filters.ratio)
            ):
                url = r.get("image")
                if url:
                    results.append(GifSearchResult(url=url))
        return results


class TenorSearchEngine(ISearchEngine):
    """Tenor implementation of SearchEngine."""
    
    def search(
        self,
        keyword: str,
        qty: int,
        filters: GifSearchFilter,
        api_key: str,
        cancelled: Callable[[], bool],
    ) -> List[GifSearchResult]:
        if not _requests:
            return []
            
        results: List[GifSearchResult] = []
        url = (
            f"https://tenor.googleapis.com/v2/search"
            f"?q={keyword}&key={api_key}&limit={qty * 3}"
        )
        resp = _requests.get(url, timeout=10).json()
        for r in resp.get("results", []):
            if cancelled() or len(results) >= qty:
                break
            media = r.get("media_formats", {}).get("gif", {})
            try:
                w, h = int(media.get("dims", [0, 0])[0]), int(media.get("dims", [0, 0])[1])
            except (ValueError, TypeError, IndexError):
                w, h = 0, 0
            if (
                w >= filters.min_width
                and h >= filters.min_height
                and check_ratio(w, h, filters.ratio)
            ):
                u = media.get("url")
                if u:
                    results.append(GifSearchResult(url=u))
        return results


class GiphySearchEngine(ISearchEngine):
    """Giphy implementation of SearchEngine."""
    
    def search(
        self,
        keyword: str,
        qty: int,
        filters: GifSearchFilter,
        api_key: str,
        cancelled: Callable[[], bool],
    ) -> List[GifSearchResult]:
        if not _requests:
            return []
            
        results: List[GifSearchResult] = []
        url = (
            f"https://api.giphy.com/v1/gifs/search"
            f"?api_key={api_key}&q={keyword}&limit={qty * 3}"
        )
        resp = _requests.get(url, timeout=10).json()
        for r in resp.get("data", []):
            if cancelled() or len(results) >= qty:
                break
            img = r.get("images", {}).get("original", {})
            try:
                w, h = int(img.get("width", 0)), int(img.get("height", 0))
            except ValueError:
                w, h = 0, 0
            if (
                w >= filters.min_width
                and h >= filters.min_height
                and check_ratio(w, h, filters.ratio)
            ):
                u = img.get("url")
                if u:
                    results.append(GifSearchResult(url=u))
        return results
