"""Tests for the search_engine module — query processing, ranking, and filtering."""

from __future__ import annotations

import pytest

from offline_search.search_engine import (
    SearchResult,
    _build_fts5_query,
    _expand_synonyms,
    _tokenize_query,
    search_sync,
)


# ── Query tokenisation ─────────────────────────────────────────────

class TestTokenizeQuery:
    def test_basic_terms(self):
        assert _tokenize_query("python asyncio") == ["python", "asyncio"]

    def test_stop_words_removed(self):
        result = _tokenize_query("how to use python for data")
        assert "how" not in result
        assert "to" not in result
        assert "for" not in result
        assert "python" in result
        assert "data" in result

    def test_all_stop_words_fallback(self):
        """When every word is a stop-word, keep them all."""
        result = _tokenize_query("to be or not to be")
        assert len(result) > 0

    def test_empty_query(self):
        assert _tokenize_query("") == []
        assert _tokenize_query("   ") == []


# ── Synonym expansion ──────────────────────────────────────────────

class TestExpandSynonyms:
    def test_js_expands(self):
        result = _expand_synonyms(["js", "framework"])
        assert "javascript" in result
        assert "js" in result
        assert "framework" in result

    def test_no_expansion_for_unknown(self):
        result = _expand_synonyms(["python"])
        assert result == ["python"]

    def test_py_expands(self):
        result = _expand_synonyms(["py"])
        assert "python" in result


# ── FTS5 query building ───────────────────────────────────────────

class TestBuildFTS5Query:
    def test_single_term(self):
        assert _build_fts5_query(["python"]) == '"python"*'

    def test_multiple_terms(self):
        result = _build_fts5_query(["python", "asyncio"])
        assert '"python"' in result
        assert '"asyncio"*' in result  # last term gets prefix

    def test_no_prefix_option(self):
        result = _build_fts5_query(["python"], use_prefix=False)
        assert result == '"python"'

    def test_empty_terms(self):
        assert _build_fts5_query([]) == ""

    def test_quotes_escaped(self):
        result = _build_fts5_query(['say "hello"'])
        assert '""' in result  # double-quotes should be escaped


# ── Search execution against test DB ───────────────────────────────

class TestSearchSync:
    def test_basic_search(self, tmp_db):
        results = search_sync("python", db_path=tmp_db)
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    def test_no_results_for_nonsense(self, tmp_db):
        results = search_sync("xyzzy_nonexistent_term_42", db_path=tmp_db)
        assert results == []

    def test_url_blacklist_filtered(self, tmp_db):
        """The analytics.python.org page should be filtered out."""
        results = search_sync("analytics tracking", db_path=tmp_db)
        urls = [r.url for r in results]
        assert not any("analytics.python.org" in u for u in urls)

    def test_non_english_deprioritized(self, tmp_db):
        """English results should appear before French ones for same query."""
        results = search_sync("python tutorial", db_path=tmp_db, limit=10)
        if len(results) >= 2:
            english_idx = next(
                (i for i, r in enumerate(results) if not r.is_non_english), None
            )
            french_idx = next(
                (i for i, r in enumerate(results) if r.is_non_english), None
            )
            if english_idx is not None and french_idx is not None:
                assert english_idx < french_idx

    def test_limit_respected(self, tmp_db):
        results = search_sync("python", db_path=tmp_db, limit=2)
        assert len(results) <= 2

    def test_zim_filter(self, tmp_db):
        results = search_sync("python", db_path=tmp_db, zim_filter="devdocs")
        for r in results:
            assert r.zim_name == "devdocs"

    def test_synonym_expansion_js(self, tmp_db):
        """Searching 'javascript' should find JS content, and 'js' should expand."""
        # Direct search for javascript should work
        results = search_sync("javascript guide", db_path=tmp_db)
        titles = [r.title.lower() for r in results]
        assert any("javascript" in t for t in titles)

        # The synonym expansion ensures 'js' adds 'javascript' to the query terms
        from offline_search.search_engine import _expand_synonyms
        expanded = _expand_synonyms(["js"])
        assert "javascript" in expanded

    def test_missing_db_returns_empty(self, tmp_path):
        results = search_sync("python", db_path=tmp_path / "nonexistent.db")
        assert results == []


# ── SearchResult formatting ────────────────────────────────────────

class TestSearchResult:
    def test_format_full_url_zim(self):
        r = SearchResult(
            title="Test", url="docs/api.html", snippet="",
            zim_name="python_docs", namespace="A",
        )
        full = r.format_full_url("http://localhost:8081")
        assert full == "http://localhost:8081/content/python_docs/A/docs/api.html"

    def test_format_full_url_external(self):
        r = SearchResult(
            title="Test", url="https://example.com/page", snippet="",
            zim_name="ext", namespace="W",
        )
        assert r.format_full_url("http://localhost:8081") == "https://example.com/page"

    def test_format_for_llm(self):
        r = SearchResult(
            title="My Doc", url="docs/test.html", snippet="A **snippet** here",
            zim_name="test", namespace="A",
        )
        text = r.format_for_llm("http://localhost:8081")
        assert "Title: My Doc" in text
        assert "URL: http://localhost:8081/content/test/A/docs/test.html" in text
        assert "Snippet: A **snippet** here" in text

    def test_to_dict(self):
        r = SearchResult(
            title="T", url="u", snippet="s", zim_name="z", namespace="n", score=-1.5,
        )
        d = r.to_dict()
        assert d["title"] == "T"
        assert d["score"] == -1.5
