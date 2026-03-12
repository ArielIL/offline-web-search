"""Tests for the unified MCP server — local and remote tool implementations.

All external I/O (search, kiwix, httpx) is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from offline_search.search_engine import SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(title: str = "Python Docs", url: str = "docs/python.html") -> SearchResult:
    return SearchResult(
        title=title, url=url, snippet="A snippet",
        zim_name="python_docs", namespace="A", score=-1.5,
    )


# We need to import the private functions. They live in mcp.py which also
# instantiates a FastMCP server at module-level.  That's fine for tests.
from offline_search.mcp import (
    _google_search_local,
    _google_search_remote,
    _visit_page_local,
    _visit_page_remote,
    google_search,
    visit_page,
)


# ---------------------------------------------------------------------------
# _google_search_local
# ---------------------------------------------------------------------------

class TestGoogleSearchLocal:
    async def test_fts5_results(self, tmp_db):
        from offline_search.config import settings
        original_db = settings.db_path
        settings.db_path = tmp_db
        try:
            out = await _google_search_local("python")
            assert 'Offline search results for query: "python"' in out
            assert "Links: [" in out
            assert "**Python Tutorial**" in out
            assert "REMINDER:" in out
        finally:
            settings.db_path = original_db

    async def test_fallback_to_kiwix_html(self):
        html_hits = [{"title": "HTML Hit", "url": "http://k/page", "snippet": "s"}]
        with (
            patch("offline_search.mcp.search", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=html_hits)),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            out = await _google_search_local("react")
        assert "**HTML Hit**" in out
        assert "Links: [" in out
        assert "REMINDER:" in out

    async def test_no_results(self, tmp_db):
        from offline_search.config import settings
        original_db = settings.db_path
        settings.db_path = tmp_db
        try:
            with (
                patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=[])),
                patch("offline_search.mcp.start_kiwix_server"),
            ):
                out = await _google_search_local("xyzzy")
            assert "No results found" in out
            assert "Suggestions:" in out
        finally:
            settings.db_path = original_db

    async def test_zim_filter_passthrough(self):
        mock_search = AsyncMock(return_value=[])
        with (
            patch("offline_search.mcp.search", mock_search),
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            await _google_search_local("python", zim_filter="devdocs")
        mock_search.assert_awaited_once_with("python", zim_filter="devdocs")

    async def test_exception_handled(self):
        with patch("offline_search.mcp.search", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await _google_search_local("fail")
        assert "Error" in out


# ---------------------------------------------------------------------------
# _visit_page_local
# ---------------------------------------------------------------------------

class TestVisitPageLocal:
    async def test_success(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value="# Hello")):
            out = await _visit_page_local("http://k/page")
        assert out == "# Hello"

    async def test_empty_content(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value="")):
            out = await _visit_page_local("http://k/page")
        assert "empty content" in out.lower()

    async def test_exception_handled(self):
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(side_effect=httpx.ConnectError("down"))):
            out = await _visit_page_local("http://k/page")
        assert "Error" in out


# ---------------------------------------------------------------------------
# _google_search_remote
# ---------------------------------------------------------------------------

class TestGoogleSearchRemote:
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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _google_search_remote("api")

        assert 'Offline search results for query: "api"' in out
        assert "Links: [" in out
        assert "**Remote Doc**" in out
        assert "API reference" in out
        assert "REMINDER:" in out

    async def test_external_url_preserved(self):
        """If the result URL is already absolute, don't prefix it."""
        payload = [
            {
                "title": "Ext",
                "url": "https://example.com/page",
                "snippet": "s",
                "zim_name": "x",
                "namespace": "A",
            },
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _google_search_remote("ext")

        assert "https://example.com/page" in out

    async def test_no_results(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _google_search_remote("nothing")

        assert "No results found" in out
        assert "Suggestions:" in out

    async def test_exception_handled(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _google_search_remote("fail")

        assert "Error" in out


# ---------------------------------------------------------------------------
# _visit_page_remote
# ---------------------------------------------------------------------------

class TestVisitPageRemote:
    async def test_html_to_markdown(self):
        html = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _visit_page_remote("http://remote/page")

        assert "Title" in out
        assert "Body text" in out

    async def test_plain_text(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "Just plain text."
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _visit_page_remote("http://remote/text")

        assert out == "Just plain text."

    async def test_content_capped_at_15k(self):
        huge = "x" * 20_000
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = huge
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _visit_page_remote("http://remote/huge")

        assert len(out) <= 15_000

    async def test_exception_handled(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _visit_page_remote("http://remote/fail")

        assert "Error" in out


# ---------------------------------------------------------------------------
# Mode dispatch (google_search / visit_page)
# ---------------------------------------------------------------------------

class TestModeDispatch:
    async def test_google_search_dispatches_local(self):
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=False)),
            patch("offline_search.mcp._google_search_local", new=AsyncMock(return_value="local")) as m,
        ):
            result = await google_search("q")
        assert result == "local"

    async def test_google_search_dispatches_remote(self):
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=True)),
            patch("offline_search.mcp._google_search_remote", new=AsyncMock(return_value="remote")) as m,
        ):
            result = await google_search("q")
        assert result == "remote"

    async def test_visit_page_dispatches_local(self):
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=False)),
            patch("offline_search.mcp._visit_page_local", new=AsyncMock(return_value="local")) as m,
        ):
            result = await visit_page("http://u")
        assert result == "local"

    async def test_visit_page_dispatches_remote(self):
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=True)),
            patch("offline_search.mcp._visit_page_remote", new=AsyncMock(return_value="remote")) as m,
        ):
            result = await visit_page("http://u")
        assert result == "remote"


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
