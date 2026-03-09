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

    def test_allowed_zims_single(self, tmp_db):
        """allowed_zims with one entry restricts results to that ZIM."""
        results = search_sync("python", db_path=tmp_db, allowed_zims=["python_docs"])
        assert len(results) > 0
        for r in results:
            assert r.zim_name == "python_docs"

    def test_allowed_zims_multiple(self, tmp_db):
        """allowed_zims with multiple entries restricts to those ZIMs only."""
        results = search_sync("python", db_path=tmp_db, allowed_zims=["python_docs", "devdocs"])
        assert len(results) > 0
        for r in results:
            assert r.zim_name in {"python_docs", "devdocs"}

    def test_allowed_zims_none_no_filter(self, tmp_db):
        """allowed_zims=None applies no ZIM filtering."""
        all_results = search_sync("python", db_path=tmp_db)
        filtered_results = search_sync("python", db_path=tmp_db, allowed_zims=None)
        assert len(all_results) == len(filtered_results)

    def test_blocked_zims_excludes_sources(self, tmp_db):
        """blocked_zims excludes the listed ZIM archives from results."""
        results = search_sync("python", db_path=tmp_db, blocked_zims=["python_docs"])
        for r in results:
            assert r.zim_name != "python_docs"

    def test_blocked_zims_multiple(self, tmp_db):
        """blocked_zims with multiple entries excludes all of them."""
        results = search_sync("python", db_path=tmp_db, blocked_zims=["python_docs", "devdocs"])
        for r in results:
            assert r.zim_name not in {"python_docs", "devdocs"}

    def test_allowed_and_blocked_zims_combined(self, tmp_db):
        """allowed_zims and blocked_zims can be combined; blocked takes precedence."""
        results = search_sync(
            "python",
            db_path=tmp_db,
            allowed_zims=["python_docs", "devdocs"],
            blocked_zims=["devdocs"],
        )
        for r in results:
            assert r.zim_name == "python_docs"

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

    def test_format_for_llm_no_snippet(self):
        """When snippet is empty, format_for_llm should say 'No preview available.'."""
        r = SearchResult(
            title="Blank", url="u", snippet="", zim_name="z", namespace="A",
        )
        text = r.format_for_llm("http://localhost:8081")
        assert "No preview available." in text

    def test_format_full_url_empty_namespace(self):
        """Empty namespace should default to 'A'."""
        r = SearchResult(
            title="T", url="docs/page", snippet="s", zim_name="z", namespace="",
        )
        full = r.format_full_url("http://localhost:8081")
        assert "/A/" in full

    def test_url_with_special_chars_encoded(self):
        """URLs with spaces or special chars should be safely encoded."""
        r = SearchResult(
            title="T", url="docs/my page.html", snippet="s",
            zim_name="z", namespace="A",
        )
        full = r.format_full_url("http://localhost:8081")
        assert "my%20page.html" in full
        assert full.startswith("http://localhost:8081/content/z/A/")


# ── Async wrapper ──────────────────────────────────────────────────

class TestSearchAsync:
    async def test_async_search_delegates_to_sync(self, tmp_db):
        """The async ``search()`` wrapper should return the same results as sync."""
        from offline_search.search_engine import search

        sync_results = search_sync("python", db_path=tmp_db)
        async_results = await search("python", db_path=tmp_db)
        assert len(async_results) == len(sync_results)
        assert [r.title for r in async_results] == [r.title for r in sync_results]

    async def test_async_search_no_results(self, tmp_path):
        from offline_search.search_engine import search

        results = await search("python", db_path=tmp_path / "nonexistent.db")
        assert results == []


# ── Edge cases / error branches ────────────────────────────────────

class TestSearchEdgeCases:
    def test_corrupt_db_returns_empty(self, tmp_path):
        """A non-SQLite file at db_path should not crash."""
        fake_db = tmp_path / "bad.sqlite"
        fake_db.write_text("this is not a database")
        results = search_sync("python", db_path=fake_db)
        assert results == []

    def test_all_results_blacklisted(self, tmp_db):
        """Searching for a term that only matches blacklisted URLs → empty."""
        results = search_sync("analytics tracking", db_path=tmp_db)
        urls = [r.url for r in results]
        assert not any("analytics.python.org" in u for u in urls)

    def test_unicode_query(self, tmp_db):
        """Unicode characters in the query should not crash."""
        results = search_sync("données françaises 日本語", db_path=tmp_db)
        assert isinstance(results, list)  # may be empty, but should not raise

    def test_special_fts5_chars_in_query(self, tmp_db):
        """FTS5 special characters should be handled gracefully."""
        results = search_sync('python "asyncio" OR NOT', db_path=tmp_db)
        assert isinstance(results, list)

    def test_whitespace_only_query(self, tmp_db):
        """A whitespace-only query should short-circuit to empty list."""
        results = search_sync("   ", db_path=tmp_db)
        assert results == []

    def test_stop_words_only_still_returns(self, tmp_db):
        """Query with only stop words should still attempt search (fallback)."""
        results = search_sync("the is a", db_path=tmp_db)
        assert isinstance(results, list)
