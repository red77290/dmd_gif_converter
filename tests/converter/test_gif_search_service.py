from unittest import mock
import pytest

from src.converter.services.search_models import GifSearchFilter, GifSearchResult
from src.converter.services.search_engines import (
    DuckDuckGoSearchEngine,
    TenorSearchEngine,
    GiphySearchEngine,
)
from src.converter.services.gif_search_service import GifSearchService

@pytest.fixture
def base_filters():
    return GifSearchFilter(min_width=100, min_height=100, ratio="All")

def dummy_cancel():
    return False

def test_duckduckgo_search_engine(base_filters):
    engine = DuckDuckGoSearchEngine()
    
    with mock.patch("src.converter.services.search_engines._DDGS") as mock_ddgs:
        mock_instance = mock_ddgs.return_value
        # Mock what DDGS.images yields
        mock_instance.images.return_value = [
            {"width": 200, "height": 200, "image": "http://example.com/1.gif"},
            {"width": 50, "height": 50, "image": "http://example.com/2.gif"},  # filtered out by min_width/height
            {"width": 300, "height": 300, "image": "http://example.com/3.gif"}
        ]
        
        results = engine.search("test", 2, base_filters, "", dummy_cancel)
        
        assert len(results) == 2
        assert results[0].url == "http://example.com/1.gif"
        assert results[1].url == "http://example.com/3.gif"
        mock_instance.images.assert_called_once_with(
            "test gif", safesearch="off", type_image="gif", max_results=10
        )

def test_tenor_search_engine(base_filters):
    engine = TenorSearchEngine()
    
    with mock.patch("src.converter.services.search_engines._requests") as mock_requests:
        mock_resp = mock.MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"media_formats": {"gif": {"dims": [200, 200], "url": "http://tenor.com/1.gif"}}},
                {"media_formats": {"gif": {"dims": [50, 50], "url": "http://tenor.com/2.gif"}}}
            ]
        }
        mock_requests.get.return_value = mock_resp
        
        results = engine.search("test", 5, base_filters, "my_key", dummy_cancel)
        
        assert len(results) == 1
        assert results[0].url == "http://tenor.com/1.gif"
        mock_requests.get.assert_called_once()
        assert "key=my_key" in mock_requests.get.call_args[0][0]

def test_giphy_search_engine(base_filters):
    engine = GiphySearchEngine()
    
    with mock.patch("src.converter.services.search_engines._requests") as mock_requests:
        mock_resp = mock.MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"images": {"original": {"width": "200", "height": "200", "url": "http://giphy.com/1.gif"}}}
            ]
        }
        mock_requests.get.return_value = mock_resp
        
        results = engine.search("test", 5, base_filters, "my_key", dummy_cancel)
        
        assert len(results) == 1
        assert results[0].url == "http://giphy.com/1.gif"
        mock_requests.get.assert_called_once()
        assert "api_key=my_key" in mock_requests.get.call_args[0][0]

def test_gif_search_service_routing():
    service = GifSearchService()
    
    # Check that service has the engines registered
    assert "DuckDuckGo" in service.engines
    assert "Tenor" in service.engines
    assert "Giphy" in service.engines

    with mock.patch.object(service.engines["DuckDuckGo"], "search") as mock_search:
        mock_search.return_value = [GifSearchResult(url="http://mock.url/1.gif")]
        
        filters = GifSearchFilter()
        results = service.search("cat", 1, "DuckDuckGo", filters)
        
        assert len(results) == 1
        assert results[0].url == "http://mock.url/1.gif"
        mock_search.assert_called_once()
        
def test_gif_search_service_download(tmp_path):
    service = GifSearchService()
    result = GifSearchResult(url="http://mock.url/test_image.gif")
    
    with mock.patch("src.converter.services.gif_search_service._requests") as mock_requests:
        mock_resp = mock.MagicMock()
        mock_resp.headers = {"Content-Type": "image/gif"}
        mock_resp.iter_content.return_value = [b"gif_data"]
        mock_requests.get.return_value = mock_resp
        
        download_path = service.download(result, str(tmp_path), 0, "test")
        
        assert download_path is not None
        assert download_path.endswith("test_image.gif")
        
        with open(download_path, "rb") as f:
            assert f.read() == b"gif_data"
