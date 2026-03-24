"""Tests for the WebSearch-format result formatter."""

from __future__ import annotations

import json

from offline_search.formatter import (
    NO_RESULTS_MESSAGE,
    SOURCES_REMINDER,
    format_search_result,
    format_search_result_compact,
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


class TestCompactFormat:
    def test_header_present(self):
        out = format_search_result_compact("python", [_result()], BASE_URL)
        assert 'Offline search results for query: "python"' in out

    def test_links_json_present_and_valid(self):
        results = [_result("Doc A", "a.html"), _result("Doc B", "b.html")]
        out = format_search_result_compact("test", results, BASE_URL)
        for line in out.split("\n"):
            if line.startswith("Links: "):
                links = json.loads(line[len("Links: "):])
                assert isinstance(links, list)
                assert len(links) == 2
                assert all("title" in l and "url" in l for l in links)
                break
        else:
            assert False, "No 'Links: ' line found in output"

    def test_snippet_truncated_to_80_chars(self):
        long_snippet = "x" * 200
        r = _result(snippet=long_snippet)
        out = format_search_result_compact("test", [r], BASE_URL)
        # Find the snippet line (starts with "- ")
        for line in out.split("\n"):
            if line.startswith("- Python Docs:"):
                snippet_part = line.split(": ", 1)[1]
                assert len(snippet_part) <= 81  # 80 chars + ellipsis char
                assert snippet_part.endswith("…")
                break
        else:
            assert False, "No snippet line found"

    def test_no_verbose_snippet_blocks(self):
        out = format_search_result_compact("test", [_result()], BASE_URL)
        assert "**Python Docs**" not in out

    def test_empty_results(self):
        out = format_search_result_compact("xyzzy", [], BASE_URL)
        assert "No results found." in out

    def test_reminder_present(self):
        out = format_search_result_compact("test", [_result()], BASE_URL)
        assert "REMINDER:" in out

    def test_compact_shorter_than_full(self):
        results = [
            _result("Doc A", "a.html", "A longer snippet with details"),
            _result("Doc B", "b.html", "Another snippet with more info"),
        ]
        full = format_search_result("test", results, BASE_URL)
        compact = format_search_result_compact("test", results, BASE_URL)
        assert len(compact) < len(full)

    def test_newlines_in_snippet_collapsed(self):
        r = _result(snippet="line one\nline two\nline three")
        out = format_search_result_compact("test", [r], BASE_URL)
        for line in out.split("\n"):
            if line.startswith("- Python Docs:"):
                assert "\n" not in line.split(": ", 1)[1]
                break
