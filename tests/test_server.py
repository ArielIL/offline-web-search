"""Tests for the FastAPI search server endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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

    def test_limit_param(self, client):
        resp = client.get("/search", params={"q": "python", "limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()) <= 2

    def test_zim_filter(self, client):
        resp = client.get("/search", params={"q": "python", "zim": "devdocs"})
        assert resp.status_code == 200
        for r in resp.json():
            assert r["zim_name"] == "devdocs"

    def test_no_results(self, client):
        resp = client.get("/search", params={"q": "xyzzy_nonexistent_42"})
        assert resp.status_code == 200
        assert resp.json() == []


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
