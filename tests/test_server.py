"""Tests for the FastAPI search server endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from offline_search.config import settings


@pytest.fixture()
def client(tmp_db, monkeypatch):
    """Create a FastAPI test client with a temporary database."""
    monkeypatch.setattr(settings, "db_path", tmp_db)
    from offline_search.server import app
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "index" in data

    def test_stats(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] > 0
        assert isinstance(data["sources"], list)


class TestSearchEndpoint:
    def test_basic_search(self, client):
        resp = client.get("/search", params={"q": "python"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) > 0
        assert "title" in results[0]
        assert "url" in results[0]
        assert "snippet" in results[0]

    def test_empty_query_rejected(self, client):
        resp = client.get("/search", params={"q": ""})
        assert resp.status_code == 400

    def test_whitespace_query_rejected(self, client):
        resp = client.get("/search", params={"q": "   "})
        assert resp.status_code == 400

    def test_limit_param(self, client):
        resp = client.get("/search", params={"q": "python", "limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_limit_too_high(self, client):
        """limit > 100 should be rejected by the validation."""
        resp = client.get("/search", params={"q": "python", "limit": 200})
        assert resp.status_code == 422  # validation error

    def test_limit_too_low(self, client):
        """limit < 1 should be rejected by the validation."""
        resp = client.get("/search", params={"q": "python", "limit": 0})
        assert resp.status_code == 422

    def test_zim_filter(self, client):
        resp = client.get("/search", params={"q": "python", "zim": "devdocs"})
        assert resp.status_code == 200
        for r in resp.json():
            assert r["zim_name"] == "devdocs"

    def test_no_results(self, client):
        resp = client.get("/search", params={"q": "xyzzy_nonexistent_42"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_results_have_expected_fields(self, client):
        """Every result dict should have the complete SearchResult fields."""
        resp = client.get("/search", params={"q": "python"})
        for r in resp.json():
            for key in ("title", "url", "snippet", "zim_name", "namespace", "score"):
                assert key in r, f"Missing field: {key}"


class TestIndexPageEndpoint:
    def test_index_single_page(self, client):
        resp = client.post("/index/page", json={
            "title": "New Test Page",
            "content": "This is brand new content for testing the index API.",
            "url": "https://example.com/test-page",
            "source_name": "test_source",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "docid" in data

        # Verify it's searchable
        search_resp = client.get("/search", params={"q": "brand new content"})
        results = search_resp.json()
        assert any("New Test Page" in r["title"] for r in results)

    def test_index_page_minimal_fields(self, client):
        """Only title, content, url are required; source_name defaults to 'external'."""
        resp = client.post("/index/page", json={
            "title": "Minimal",
            "content": "Minimal content for indexing test.",
            "url": "https://example.com/minimal",
        })
        assert resp.status_code == 200

    def test_index_page_missing_required_field(self, client):
        """Missing required field should return 422."""
        resp = client.post("/index/page", json={
            "title": "No Content",
            "url": "https://example.com/no-content",
        })
        assert resp.status_code == 422


class TestDeleteEndpoint:
    def test_delete_existing(self, client):
        # First index a page
        client.post("/index/page", json={
            "title": "To Delete",
            "content": "Deleteable content",
            "url": "https://example.com/to-delete",
        })
        # Then delete it
        resp = client.delete("/index", params={"url": "https://example.com/to-delete"})
        assert resp.status_code == 200

    def test_delete_nonexistent(self, client):
        resp = client.delete("/index", params={"url": "https://example.com/does-not-exist"})
        assert resp.status_code == 404

    def test_delete_then_search_empty(self, client):
        """After deletion the document should not appear in search results."""
        url = "https://example.com/ephemeral-page"
        client.post("/index/page", json={
            "title": "Ephemeral",
            "content": "ephemeral_unique_test_content_xyz",
            "url": url,
        })
        client.delete("/index", params={"url": url})
        resp = client.get("/search", params={"q": "ephemeral_unique_test_content_xyz"})
        assert resp.json() == []


class TestCrawlEndpoint:
    """The /index/crawl endpoint uses httpx internally — mock it."""

    def test_crawl_indexes_pages(self, tmp_db, monkeypatch):
        monkeypatch.setattr(settings, "db_path", tmp_db)

        html_page = (
            "<html><head><title>Test Page</title></head>"
            "<body><p>Test crawl content</p>"
            '<a href="http://example.com/page2">link</a>'
            "</body></html>"
        )
        html_page2 = (
            "<html><head><title>Page 2</title></head>"
            "<body><p>Second page content</p></body></html>"
        )

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.headers = {"content-type": "text/html"}
            resp.raise_for_status = MagicMock()
            resp.text = html_page if call_count == 1 else html_page2
            return resp

        mock_client_instance = AsyncMock()
        mock_client_instance.get = mock_get
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        original_async_client = httpx.AsyncClient

        def patched_async_client(*args, **kwargs):
            """Only intercept the crawl's outbound client, not ASGI transport."""
            # The TestClient's internal calls won't go through here because
            # TestClient uses requests, not httpx.AsyncClient.
            if kwargs.get("follow_redirects"):
                return mock_client_instance
            return original_async_client(*args, **kwargs)

        from offline_search.server import app

        with patch("httpx.AsyncClient", side_effect=patched_async_client):
            client = TestClient(app)
            resp = client.post("/index/crawl", json={
                "base_url": "http://example.com",
                "source_name": "test_crawl",
                "max_pages": 5,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["pages_indexed"] >= 1


class TestServerMain:
    """Smoke test for the server CLI entry point."""

    def test_main_calls_uvicorn(self):
        from offline_search.server import main

        mock_uvicorn = MagicMock()
        with patch.dict("sys.modules", {"uvicorn": mock_uvicorn}):
            main()

        mock_uvicorn.run.assert_called_once()
        call_args = mock_uvicorn.run.call_args
        assert call_args[0][0] == "offline_search.server:app" or \
               call_args[1].get("app") == "offline_search.server:app"
