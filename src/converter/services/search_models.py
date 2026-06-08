from dataclasses import dataclass

@dataclass
class GifSearchFilter:
    """Filtering criteria applied during result collection."""
    min_width: int = 0
    min_height: int = 0
    ratio: str = "All"  # "All" | "Landscape" | "Portrait" | "Square"

@dataclass
class GifSearchResult:
    """A single search result holding the remote GIF URL."""
    url: str

def check_ratio(w: int, h: int, ratio: str) -> bool:
    if ratio == "All" or w == 0 or h == 0:
        return True
    if ratio == "Landscape" and w > h:
        return True
    if ratio == "Portrait" and h > w:
        return True
    if ratio == "Square" and w == h:
        return True
    return False
