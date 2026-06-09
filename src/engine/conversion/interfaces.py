from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
from pathlib import Path

class IConverter(ABC):
    """Base contract for converting a single file."""

    @abstractmethod
    def process(self, src_path: str, out_path: str, params: Dict[str, Any], start_s: Optional[float] = None, end_s: Optional[float] = None) -> Tuple[bool, str]:
        """Process the source file and produce the output file.

        Returns a tuple (success: bool, message: str).
        """
        pass

class IMetadataExtractor(ABC):
    """Base contract for extracting metadata from a video / GIF."""

    @abstractmethod
    def get_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Return a metadata dict or None on failure."""
        pass

class IQualityScorer(ABC):
    """Base contract for evaluating conversion quality."""

    @abstractmethod
    def evaluate(self, gif_path: str) -> float:
        """Evaluate a GIF (e.g. 128×32) and return a score between 0.0 and 100.0."""
        pass

class IBatchOrchestrator(ABC):
    """Base contract for batch (folder) processing."""

    @abstractmethod
    def process_folder(self, input_folder: str, output_folder: str, params: Dict[str, Any], progress_callback=None) -> List[Tuple[str, str]]:
        """Process all supported files in a folder. Returns a list of generated file paths."""
        pass

class ISearchEngine(ABC):
    """Base contract for GIF search engines (DuckDuckGo, Tenor, Giphy, etc)."""
    
    @abstractmethod
    def search(
        self,
        keyword: str,
        qty: int,
        filters: Any,  # GifSearchFilter
        api_key: str,
        cancelled: Any, # Callable[[], bool]
    ) -> List[Any]: # List[GifSearchResult]
        """Perform search and return a list of results."""
        pass
