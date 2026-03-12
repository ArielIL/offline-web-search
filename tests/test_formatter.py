"""Tests for the WebSearch-format result formatter."""

from __future__ import annotations

import json

from offline_search.formatter import (
    NO_RESULTS_MESSAGE,
    SOURCES_REMINDER,
    format_search_result,
)
from offline_search.search_engine import SearchResult


BASE_URL = "http://localhost:8081"


def _result(
    title: str = "Python Docs",
    url: str = "docs/python.html",
    snippet: str = "A snippet",
) -> SearchResult:
    return SearchResult(
        title=title, url=url, snippet=snippet,
        zim_name="python_docs", namespace="A", score=-1.5,
    )


class TestFormatWithResults:
    def test_header_present(self):
        out = format_search_result("python", [_result()], BASE_URL)
        assert 'Offline search results for query: "python"' in out

    def test_links_json_present(self):
        out = format_search_result("python", [_result()], BASE_URL)
        assert "Links: [" in out

    def test_snippet_block_present(self):
        out = format_search_result("python", [_result()], BASE_URL)
        assert "**Python Docs**" in out
        assert "A snippet" in out

    def test_reminder_present(self):
        out = format_search_result("python", [_result()], BASE_URL)
        assert "REMINDER:" in out
        assert "Sources:" in out

    def test_multiple_results(self):
        results = [_result("Doc A", "a.html"), _result("Doc B", "b.html")]
        out = format_search_result("test", results, BASE_URL)
        assert "**Doc A**" in out
        assert "**Doc B**" in out

    def test_no_snippet_fallback(self):
        r = _result(snippet="")
        out = format_search_result("test", [r], BASE_URL)
        assert "No preview available." in out


class TestFormatEmptyResults:
    def test_no_results_message(self):
        out = format_search_result("xyzzy", [], BASE_URL)
        assert "No results found." in out

    def test_suggestions_present(self):
        out = format_search_result("xyzzy", [], BASE_URL)
        assert "Suggestions:" in out
        assert "broader keywords" in out

    def test_header_still_present(self):
        out = format_search_result("xyzzy", [], BASE_URL)
        assert 'Offline search results for query: "xyzzy"' in out

    def test_no_reminder_on_empty(self):
        out = format_search_result("xyzzy", [], BASE_URL)
        assert SOURCES_REMINDER not in out


class TestLinksJsonIsValid:
    def test_links_json_parseable(self):
        results = [_result("Doc A", "a.html"), _result("Doc B", "b.html")]
        out = format_search_result("test", results, BASE_URL)
        # Extract the Links line
        for line in out.split("\n"):
            if line.startswith("Links: "):
                json_str = line[len("Links: "):]
                links = json.loads(json_str)
                assert isinstance(links, list)
                assert len(links) == 2
                assert all("title" in l and "url" in l for l in links)
                break
        else:
            pytest.fail("No 'Links: ' line found in output")

    def test_links_urls_are_full(self):
        out = format_search_result("test", [_result()], BASE_URL)
        for line in out.split("\n"):
            if line.startswith("Links: "):
                links = json.loads(line[len("Links: "):])
                assert links[0]["url"].startswith("http://")
                break

    def test_external_url_preserved_in_links(self):
        r = SearchResult(
            title="Ext", url="https://example.com/page", snippet="s",
            zim_name="x", namespace="A",
        )
        out = format_search_result("test", [r], BASE_URL)
        for line in out.split("\n"):
            if line.startswith("Links: "):
                links = json.loads(line[len("Links: "):])
                assert links[0]["url"] == "https://example.com/page"
                break
