import os
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

# Ensure src is in sys.path
SRC_PATH = str(Path(__file__).resolve().parent.parent / "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment(tmp_path_factory):
    """Session-scoped fixture to isolate the test suite from external APIs."""
    # Set default mock availability flag
    os.environ["TONI_USE_MOCK_AVAILABILITY"] = "true"

    # Create temporary directories for logs and cache to prevent test pollution
    temp_dir = tmp_path_factory.mktemp("test_logs_and_cache")
    temp_trace_path = temp_dir / "parallel_traces.jsonl"
    temp_cache_path = temp_dir / "evidence_cache.json"

    # Patch TRACE_LOG_PATH and CACHE_PATH globally for all tests
    patch_trace1 = patch("src.evidence.TRACE_LOG_PATH", temp_trace_path)
    patch_cache1 = patch("src.evidence.CACHE_PATH", temp_cache_path)
    patch_trace2 = patch("evidence.TRACE_LOG_PATH", temp_trace_path)
    patch_cache2 = patch("evidence.CACHE_PATH", temp_cache_path)

    patch_trace1.start()
    patch_cache1.start()
    patch_trace2.start()
    patch_cache2.start()

    # Setup global Parallel stub
    mock_client = MagicMock()
    
    mock_search_response = MagicMock()
    mock_search_response.search_id = "stub_search_id"
    mock_search_response.session_id = "stub_session_id"
    
    class StubSearchItem:
        def __init__(self, url):
            self.url = url
            
    mock_search_response.results = [
        StubSearchItem("https://www.theguardian.com/film/review/dummy"),
        StubSearchItem("https://www.avclub.com/dummy-review")
    ]
    mock_client.search.return_value = mock_search_response
    
    class StubExtractItem:
        def __init__(self, url, title, full_content):
            self.url = url
            self.title = title
            self.full_content = full_content
            
    mock_extract_response = MagicMock()
    mock_extract_response.extract_id = "stub_extract_id"
    mock_extract_response.results = [
        StubExtractItem("https://www.theguardian.com/film/review/dummy", "Dummy Review 1", "This is dummy review content " * 30),
        StubExtractItem("https://www.avclub.com/dummy-review", "Dummy Review 2", "This is another dummy review content " * 30)
    ]
    mock_extract_response.errors = []
    mock_client.extract.return_value = mock_extract_response
    
    mock_parallel_class = MagicMock(return_value=mock_client)
    
    patcher = patch("src.evidence.Parallel", mock_parallel_class)
    patcher2 = patch("evidence.Parallel", mock_parallel_class)
    patcher.start()
    patcher2.start()
    
    yield
    
    patcher.stop()
    patcher2.stop()
    patch_trace1.stop()
    patch_cache1.stop()
    patch_trace2.stop()
    patch_cache2.stop()
