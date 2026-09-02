import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.evidence import (
    build_objective,
    build_queries,
    filter_search_results,
    log_trace,
    load_from_cache,
    save_to_cache,
    get_film_evidence,
    TRACE_LOG_PATH,
    CACHE_PATH,
)


def test_objective_formulation():
    obj = build_objective("Babylon", 2022, "Damien Chazelle")
    assert "film critic reviews" in obj
    assert "Babylon" in obj
    assert "Damien Chazelle" in obj
    assert "2022" in obj

    queries = build_queries("Babylon", 2022, "Damien Chazelle")
    assert len(queries) == 3
    assert "Babylon 2022 movie review" in queries


def test_domain_filtering():
    class MockResult:
        def __init__(self, url):
            self.url = url

    results = [
        MockResult("https://www.theguardian.com/film/review/babylon"),
        MockResult("https://en.wikipedia.org/wiki/Babylon_(film)"),
        MockResult("https://www.rottentomatoes.com/m/babylon_2022"),
        MockResult("https://www.avclub.com/babylon-review"),
    ]

    filtered = filter_search_results(results)
    assert len(filtered) == 2
    assert "theguardian.com" in filtered[0]
    assert "avclub.com" in filtered[1]


def test_trace_logging(tmp_path, monkeypatch):
    # Set TRACE_LOG_PATH to a temporary file
    temp_trace_path = tmp_path / "parallel_traces.jsonl"
    monkeypatch.setattr("src.evidence.TRACE_LOG_PATH", temp_trace_path)

    log_trace(
        title="Inception",
        year=2010,
        search_id="search_123",
        extract_id="extract_456",
        latency_sec=2.5,
        success_count=3,
        error_count=1,
        errors=["Error 1"]
    )

    assert temp_trace_path.exists()
    lines = temp_trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["title"] == "Inception"
    assert data["search_id"] == "search_123"
    assert data["extract_id"] == "extract_456"
    assert data["latency_sec"] == 2.5
    assert data["success_count"] == 3
    assert data["error_count"] == 1
    assert data["errors"] == ["Error 1"]


def test_caching_mechanics(tmp_path, monkeypatch):
    # Set CACHE_PATH to a temporary file
    temp_cache_path = tmp_path / "evidence_cache.json"
    monkeypatch.setattr("src.evidence.CACHE_PATH", temp_cache_path)

    # Ensure cache miss
    cached = load_from_cache("Pulp Fiction", 1994)
    assert cached is None

    # Save to cache
    mock_data = [
        {"url": "https://example.com/review", "title": "Pulp Fiction Review", "content": "A masterpiece of cinema."}
    ]
    save_to_cache("Pulp Fiction", 1994, mock_data)

    # Ensure cache hit
    cached = load_from_cache("Pulp Fiction", 1994)
    assert cached is not None
    assert cached[0]["url"] == "https://example.com/review"
    assert cached[0]["content"] == "A masterpiece of cinema."


@patch("src.evidence.Parallel")
def test_get_film_evidence_flow(mock_parallel_class, monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "dummy_key")
    # Setup mock search response
    mock_client = MagicMock()
    mock_parallel_class.return_value = mock_client

    class MockSearchItem:
        def __init__(self, url):
            self.url = url

    mock_search_response = MagicMock()
    mock_search_response.search_id = "search_test_id"
    mock_search_response.session_id = "session_test_id"
    mock_search_response.results = [
        MockSearchItem("https://www.theguardian.com/film/review/babylon"),
        MockSearchItem("https://en.wikipedia.org/wiki/Babylon"),
        MockSearchItem("https://www.avclub.com/babylon-review"),
    ]
    mock_client.search.return_value = mock_search_response

    # Setup mock extract response
    class MockExtractItem:
        def __init__(self, url, title, full_content):
            self.url = url
            self.title = title
            self.full_content = full_content

    class MockExtractError:
        def __init__(self, url, http_status_code, error_type):
            self.url = url
            self.http_status_code = http_status_code
            self.error_type = error_type

    mock_extract_response = MagicMock()
    mock_extract_response.extract_id = "extract_test_id"
    # One good, one thin, one error
    mock_extract_response.results = [
        MockExtractItem("https://www.theguardian.com/film/review/babylon", "Review 1", "A" * 600),  # Valid
        MockExtractItem("https://www.avclub.com/babylon-review", "Review 2", "A" * 100),  # Thin
    ]
    mock_extract_response.errors = [
        MockExtractError("https://www.avclub.com/failed", 404, "NOT_FOUND")
    ]
    mock_client.extract.return_value = mock_extract_response

    # Force live to bypass cache
    evidence = get_film_evidence("Babylon", 2022, "Damien Chazelle", force_live=True)

    # Verify search and extract were called sequentially
    mock_client.search.assert_called_once()
    # Ensure blocked Wikipedia URL was filtered out and only the 2 valid URLs were extracted
    mock_client.extract.assert_called_once_with(
        urls=["https://www.theguardian.com/film/review/babylon", "https://www.avclub.com/babylon-review"],
        session_id="session_test_id",
        advanced_settings={"full_content": True},
        timeout=10.0
    )

    # Verify return list has exactly 1 valid item (excluding the thin 100-character one)
    assert len(evidence) == 1
    assert evidence[0]["url"] == "https://www.theguardian.com/film/review/babylon"
    assert len(evidence[0]["content"]) == 600
