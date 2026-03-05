"""System / integration tests — end-to-end flows across multiple modules.

These tests exercise the **real** code paths (no mocks for the core logic),
using an ephemeral FTS5 database built on-the-fly.  External I/O (kiwix-serve,
network) is still mocked where unavoidable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from offline_search.config import Settings, settings
from offline_search.indexer import (
    get_index_stats,
    index_html_page,
    prepare_database,
    remove_by_url,
)
from offline_search.search_engine import SearchResult, search_sync


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sys_db(tmp_path: Path) -> Path:
    """A fresh FTS5 database for system tests — starts empty."""
    db_path = tmp_path / "system_test.sqlite"
    conn = prepare_database(db_path, reset=True)
    conn.close()
    return db_path


@pytest.fixture()
def sys_client(sys_db: Path, monkeypatch) -> TestClient:
    """FastAPI test client wired to the ephemeral database."""
    monkeypatch.setattr(settings, "db_path", sys_db)
    from offline_search.server import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Index → Search round-trip
# ---------------------------------------------------------------------------

class TestIndexThenSearch:
    """Index content via the library, then verify search finds it."""

    def test_index_and_search_round_trip(self, sys_db):
        """Directly index pages, then search them with the real search engine."""
        conn = prepare_database(sys_db)
        index_html_page(
            conn,
            title="Rust Ownership",
            content="Rust uses ownership rules with borrowing and lifetimes for memory safety.",
            url="https://doc.rust-lang.org/book/ownership.html",
            source_name="rust_book",
        )
        index_html_page(
            conn,
            title="Rust Traits",
            content="Traits define shared behavior in Rust, similar to interfaces.",
            url="https://doc.rust-lang.org/book/traits.html",
            source_name="rust_book",
        )
        conn.close()

        results = search_sync("rust ownership borrowing", db_path=sys_db)
        assert len(results) >= 1
        assert any("Ownership" in r.title for r in results)

    def test_index_delete_search(self, sys_db):
        """Index → delete → verify search returns nothing."""
        conn = prepare_database(sys_db)
        url = "https://example.com/temp-page"
        index_html_page(
            conn, title="Temporary", content="temporary content xyz123",
            url=url, source_name="test",
        )
        # Confirm it's searchable
        results = search_sync("temporary content xyz123", db_path=sys_db)
        assert len(results) >= 1

        # Delete and re-search
        remove_by_url(conn, url)
        conn.close()

        results = search_sync("temporary content xyz123", db_path=sys_db)
        assert results == []

    def test_stats_reflect_indexed_content(self, sys_db):
        """get_index_stats should accurately count indexed documents."""
        conn = prepare_database(sys_db)
        for i in range(5):
            index_html_page(
                conn, title=f"Doc {i}", content=f"Content for document {i}",
                url=f"https://example.com/doc{i}", source_name="batch",
            )
        conn.close()

        stats = get_index_stats(db_path=sys_db)
        assert stats["exists"] is True
        assert stats["total_documents"] == 5
        assert stats["sources"][0]["name"] == "batch"
        assert stats["sources"][0]["count"] == 5


# ---------------------------------------------------------------------------
# Full API round-trip via FastAPI
# ---------------------------------------------------------------------------

class TestAPIRoundTrip:
    """End-to-end: POST /index/page → GET /search → DELETE /index."""

    def test_full_lifecycle(self, sys_client):
        url = "https://example.com/lifecycle-test"

        # 1. Index a page
        resp = sys_client.post("/index/page", json={
            "title": "Lifecycle Test",
            "content": "Unique lifecycle test content for system validation abc987.",
            "url": url,
            "source_name": "system_test",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # 2. Verify search finds it
        resp = sys_client.get("/search", params={"q": "lifecycle test content abc987"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("Lifecycle Test" in r["title"] for r in results)

        # 3. Health endpoint should show the document
        resp = sys_client.get("/health")
        assert resp.json()["index"]["total_documents"] >= 1

        # 4. Delete it
        resp = sys_client.delete("/index", params={"url": url})
        assert resp.status_code == 200

        # 5. Confirm it's gone
        resp = sys_client.get("/search", params={"q": "lifecycle test content abc987"})
        assert resp.json() == []

    def test_multiple_sources_searchable(self, sys_client):
        """Index from two sources, verify both are searchable and zim filter works."""
        sys_client.post("/index/page", json={
            "title": "Alpha Topic",
            "content": "alpha topic unique content a1b2c3",
            "url": "https://alpha.com/topic",
            "source_name": "alpha_source",
        })
        sys_client.post("/index/page", json={
            "title": "Beta Topic",
            "content": "beta topic unique content d4e5f6",
            "url": "https://beta.com/topic",
            "source_name": "beta_source",
        })

        # Both should appear in unfiltered search
        resp = sys_client.get("/search", params={"q": "topic unique content"})
        assert len(resp.json()) >= 2

        # Filtered search should narrow results
        resp = sys_client.get("/search", params={"q": "topic", "zim": "alpha_source"})
        results = resp.json()
        assert all(r["zim_name"] == "alpha_source" for r in results)


# ---------------------------------------------------------------------------
# Config → Search integration
# ---------------------------------------------------------------------------

class TestConfigSearchIntegration:
    """Verify config settings actually affect search behavior."""

    def test_custom_limit_propagates(self, tmp_db):
        """search_sync respects the limit parameter."""
        results_2 = search_sync("python", db_path=tmp_db, limit=2)
        results_10 = search_sync("python", db_path=tmp_db, limit=10)
        assert len(results_2) <= 2
        assert len(results_10) >= len(results_2)

    def test_zim_filter_isolates_source(self, tmp_db):
        """zim_filter should return only matching sources."""
        results = search_sync("python", db_path=tmp_db, zim_filter="stackoverflow")
        for r in results:
            assert r.zim_name == "stackoverflow"

    def test_search_result_urls_are_formattable(self, tmp_db):
        """Every SearchResult should produce a valid full URL."""
        results = search_sync("python", db_path=tmp_db, limit=5)
        for r in results:
            full_url = r.format_full_url("http://127.0.0.1:8081")
            assert full_url.startswith("http")
            assert "/content/" in full_url or "://" in full_url


# ---------------------------------------------------------------------------
# MCP tool → search integration (mock only kiwix, use real search)
# ---------------------------------------------------------------------------

class TestMCPSearchIntegration:
    """Test MCP tool functions with a real FTS5 database (only kiwix mocked)."""

    async def test_google_search_local_real_db(self, tmp_db, monkeypatch):
        monkeypatch.setattr(settings, "db_path", tmp_db)

        from offline_search.mcp import _google_search_local

        out = await _google_search_local("python asyncio")
        assert "Title:" in out
        assert "asyncio" in out.lower()

    async def test_google_search_local_no_results_real_db(self, tmp_db, monkeypatch):
        monkeypatch.setattr(settings, "db_path", tmp_db)

        from offline_search.mcp import _google_search_local

        # Prevent kiwix fallback from hitting the network
        with patch("offline_search.mcp.search_kiwix_html", return_value=[]):
            with patch("offline_search.mcp.start_kiwix_server"):
                out = await _google_search_local("xyzzy_nonexistent_12345")

        assert "No results found" in out
