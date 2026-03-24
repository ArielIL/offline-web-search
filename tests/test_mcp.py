"""Tests for the unified MCP server — google_search and visit_page tools.

Tests go through the public tool functions. Mocks exist only at external
boundaries: network I/O (httpx, kiwix-serve process).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from offline_search.mcp import google_search, visit_page


# ---------------------------------------------------------------------------
# google_search — local mode (real FTS5 DB)
# ---------------------------------------------------------------------------

class TestGoogleSearchLocal:
    """Test google_search() in local mode with a real FTS5 database."""

    @pytest.fixture(autouse=True)
    def _local_mode(self, tmp_db):
        """Configure local mode with the test database."""
        from offline_search.config import settings
        self._original_db = settings.db_path
        self._original_mode = settings.mode
        settings.db_path = tmp_db
        settings.mode = "local"
        yield
        settings.db_path = self._original_db
        settings.mode = self._original_mode

    async def test_returns_formatted_results(self):
        out = await google_search("python")
        assert 'Offline search results for query: "python"' in out
        assert "Links: [" in out
        assert "Python" in out
        assert "REMINDER:" in out

    async def test_no_results_shows_suggestions(self):
        with (
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            out = await google_search("xyzzy_nonexistent_42")
        assert "No results found" in out
        assert "Suggestions:" in out

    async def test_kiwix_fallback_when_fts_empty(self):
        """When FTS5 returns nothing, falls back to kiwix HTML search."""
        html_hits = [{"title": "HTML Hit", "url": "http://k/page", "snippet": "s"}]
        with (
            patch("offline_search.mcp.search", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=html_hits)),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            out = await google_search("react")
        assert "**HTML Hit**" in out
        assert "REMINDER:" in out

    async def test_zim_filter(self):
        out = await google_search("python", zim_filter="devdocs")
        # devdocs doesn't have "python" in its titles in test data,
        # so this should return empty or only devdocs results
        if "Links: [" in out:
            assert "devdocs" in out or "No results found" in out

    async def test_exception_returns_error(self):
        with patch("offline_search.mcp.search", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await google_search("fail")
        assert "Error" in out


# ---------------------------------------------------------------------------
# google_search — remote mode (mock httpx — network boundary)
# ---------------------------------------------------------------------------

class TestGoogleSearchRemote:
    """Test google_search() in remote mode with mocked HTTP."""

    @pytest.fixture(autouse=True)
    def _remote_mode(self):
        from offline_search.config import settings
        self._original_mode = settings.mode
        self._original_host = settings.remote_host
        settings.mode = "remote"
        settings.remote_host = "10.0.0.5"
        yield
        settings.mode = self._original_mode
        settings.remote_host = self._original_host

    def _mock_http_response(self, payload, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = payload

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    async def test_results_formatted(self):
        payload = [
            {
                "title": "Remote Doc",
                "url": "docs/api.html",
                "snippet": "API reference",
                "zim_name": "python_docs",
                "namespace": "A",
            },
        ]
        mock_client = self._mock_http_response(payload)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await google_search("api")

        assert 'Offline search results for query: "api"' in out
        assert "**Remote Doc**" in out
        assert "API reference" in out
        assert "REMINDER:" in out

    async def test_external_url_preserved(self):
        payload = [
            {
                "title": "Ext",
                "url": "https://example.com/page",
                "snippet": "s",
                "zim_name": "x",
                "namespace": "A",
            },
        ]
        mock_client = self._mock_http_response(payload)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await google_search("ext")

        assert "https://example.com/page" in out

    async def test_no_results(self):
        mock_client = self._mock_http_response([])

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await google_search("nothing")

        assert "No results found" in out
        assert "Suggestions:" in out

    async def test_network_error(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await google_search("fail")

        assert "Error" in out


# ---------------------------------------------------------------------------
# visit_page — local mode (mock fetch_page — network boundary to kiwix)
# ---------------------------------------------------------------------------

class TestVisitPageLocal:
    @pytest.fixture(autouse=True)
    def _local_mode(self):
        from offline_search.config import settings
        self._original_mode = settings.mode
        settings.mode = "local"
        yield
        settings.mode = self._original_mode

    async def test_success(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value="# Hello")):
            out = await visit_page("http://k/page")
        assert out == "# Hello"

    async def test_empty_content(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value="")):
            out = await visit_page("http://k/page")
        assert "empty content" in out.lower()

    async def test_network_error(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(side_effect=httpx.ConnectError("down"))):
            out = await visit_page("http://k/page")
        assert "Error" in out


# ---------------------------------------------------------------------------
# visit_page — remote mode (mock httpx — network boundary)
# ---------------------------------------------------------------------------

class TestVisitPageRemote:
    @pytest.fixture(autouse=True)
    def _remote_mode(self):
        from offline_search.config import settings
        self._original_mode = settings.mode
        self._original_host = settings.remote_host
        settings.mode = "remote"
        settings.remote_host = "10.0.0.5"
        yield
        settings.mode = self._original_mode
        settings.remote_host = self._original_host

    def _mock_http_client(self, *, content_type="text/html", text="", side_effect=None):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": content_type}
        mock_resp.text = text
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        if side_effect:
            mock_client.get.side_effect = side_effect
        else:
            mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    async def test_html_to_markdown(self):
        html = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
        mock_client = self._mock_http_client(text=html)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await visit_page("http://remote/page")

        assert "Title" in out
        assert "Body text" in out

    async def test_plain_text(self):
        mock_client = self._mock_http_client(content_type="text/plain", text="Just plain text.")

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await visit_page("http://remote/text")

        assert out == "Just plain text."

    async def test_content_capped_at_15k(self):
        huge = "x" * 20_000
        mock_client = self._mock_http_client(content_type="text/plain", text=huge)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await visit_page("http://remote/huge")

        assert len(out) <= 15_000

    async def test_network_error(self):
        mock_client = self._mock_http_client(side_effect=httpx.ConnectError("refused"))

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await visit_page("http://remote/fail")

        assert "Error" in out


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------

class TestMCPMain:
    def test_main_local_starts_kiwix(self):
        """In local mode, main() starts kiwix-serve and calls mcp.run()."""
        from offline_search.mcp import main

        mock_settings = MagicMock(mode="local", is_local=True)
        with (
            patch("offline_search.mcp.settings", mock_settings),
            patch("offline_search.mcp.start_kiwix_server") as mock_start,
            patch("offline_search.mcp.mcp") as mock_mcp,
        ):
            main()

        mock_start.assert_called_once()
        mock_mcp.run.assert_called_once()

    def test_main_remote_skips_kiwix(self):
        """In remote mode, main() does NOT start kiwix-serve."""
        from offline_search.mcp import main

        mock_settings = MagicMock(
            mode="remote", is_local=False,
            search_api_url="http://remote:8082", kiwix_url="http://remote:8081",
        )
        with (
            patch("offline_search.mcp.settings", mock_settings),
            patch("offline_search.mcp.start_kiwix_server") as mock_start,
            patch("offline_search.mcp.mcp") as mock_mcp,
        ):
            main()

        mock_start.assert_not_called()
        mock_mcp.run.assert_called_once()
