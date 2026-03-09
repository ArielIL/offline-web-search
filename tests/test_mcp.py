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


def _get_mock_call_params(mock_call) -> dict:
    """Extract the ``params`` keyword argument from a mock call."""
    return mock_call.kwargs.get("params") or mock_call.args[1]


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
    async def test_fts5_results(self):
        r = _result()
        with (
            patch("offline_search.mcp.search", new=AsyncMock(return_value=[r])),
        ):
            out = await _google_search_local("python")
        assert "Python Docs" in out
        assert "Snippet" in out

    async def test_allowed_zims_passed_to_search(self):
        """allowed_zims is forwarded to the underlying search function."""
        r = _result()
        with patch("offline_search.mcp.search", new=AsyncMock(return_value=[r])) as mock_search:
            await _google_search_local("python", allowed_zims=["python_docs"])
        mock_search.assert_called_once_with("python", allowed_zims=["python_docs"], blocked_zims=None)

    async def test_blocked_zims_passed_to_search(self):
        """blocked_zims is forwarded to the underlying search function."""
        r = _result()
        with patch("offline_search.mcp.search", new=AsyncMock(return_value=[r])) as mock_search:
            await _google_search_local("python", blocked_zims=["stackoverflow"])
        mock_search.assert_called_once_with("python", allowed_zims=None, blocked_zims=["stackoverflow"])

    async def test_fallback_to_kiwix_html(self):
        html_hits = [{"title": "HTML Hit", "url": "http://k/page", "snippet": "s"}]
        with (
            patch("offline_search.mcp.search", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=html_hits)),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            out = await _google_search_local("react")
        assert "HTML Hit" in out

    async def test_no_results(self):
        with (
            patch("offline_search.mcp.search", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.search_kiwix_html", new=AsyncMock(return_value=[])),
            patch("offline_search.mcp.start_kiwix_server"),
        ):
            out = await _google_search_local("xyzzy")
        assert "No results found" in out

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

    async def test_prompt_triggers_filtering(self):
        """When a prompt is provided, filter_content_by_prompt is called."""
        content = "# Title\n\nIntro text.\n\n## Relevant\n\nGather runs tasks.\n\n## Other\n\nUnrelated stuff."
        with (
            patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value=content)),
            patch("offline_search.mcp.filter_content_by_prompt", return_value="filtered") as mock_filter,
        ):
            out = await _visit_page_local("http://k/page", prompt="gather tasks")
        mock_filter.assert_called_once()
        assert out == "filtered"

    async def test_max_content_tokens_without_prompt_trims_content(self):
        """max_content_tokens alone (no prompt) truncates by character count."""
        long_content = "x" * 1000
        with patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value=long_content)):
            out = await _visit_page_local("http://k/page", max_content_tokens=10)
        assert len(out) <= 40  # 10 tokens * 4 chars/token

    async def test_max_content_tokens_with_prompt(self):
        """max_content_tokens is forwarded to filter_content_by_prompt as max_chars."""
        content = "# Title\n\nIntro.\n\n## Section\n\nGather coroutines.\n"
        with (
            patch("offline_search.mcp.fetch_page", new=AsyncMock(return_value=content)),
            patch("offline_search.mcp.filter_content_by_prompt", return_value="ok") as mock_filter,
        ):
            await _visit_page_local("http://k/page", prompt="gather", max_content_tokens=100)
        _, kwargs = mock_filter.call_args
        assert kwargs.get("max_chars") == 400  # 100 tokens * 4


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

        assert "Remote Doc" in out
        assert "API reference" in out

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

    async def test_exception_handled(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _google_search_remote("fail")

        assert "Error" in out

    async def test_allowed_zims_sent_as_params(self):
        """allowed_zims is included in the HTTP request params."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            await _google_search_remote("python", allowed_zims=["python_docs"])

        sent_params = _get_mock_call_params(mock_client.get.call_args)
        assert "allowed_zims" in sent_params

    async def test_blocked_zims_sent_as_params(self):
        """blocked_zims is included in the HTTP request params."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            await _google_search_remote("python", blocked_zims=["stackoverflow"])

        sent_params = _get_mock_call_params(mock_client.get.call_args)
        assert "blocked_zims" in sent_params


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

    async def test_prompt_triggers_filtering(self):
        """When a prompt is given, filter_content_by_prompt is applied to the content."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "# Title\n\nIntro.\n\n## Section\n\nGather tasks."
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client),
            patch("offline_search.mcp.filter_content_by_prompt", return_value="filtered") as mock_filter,
        ):
            out = await _visit_page_remote("http://remote/page", prompt="gather tasks")

        mock_filter.assert_called_once()
        assert out == "filtered"

    async def test_max_content_tokens_respected(self):
        """max_content_tokens * 4 is used as the character cap."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "x" * 10_000
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.mcp.httpx.AsyncClient", return_value=mock_client):
            out = await _visit_page_remote("http://remote/page", max_content_tokens=100)

        assert len(out) <= 400  # 100 tokens * 4 chars


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

    async def test_visit_page_forwards_prompt_and_tokens_local(self):
        """prompt and max_content_tokens are forwarded to the local impl."""
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=False)),
            patch("offline_search.mcp._visit_page_local", new=AsyncMock(return_value="local")) as m,
        ):
            await visit_page("http://u", prompt="gather", max_content_tokens=200)
        m.assert_called_once_with("http://u", prompt="gather", max_content_tokens=200)

    async def test_visit_page_dispatches_remote(self):
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=True)),
            patch("offline_search.mcp._visit_page_remote", new=AsyncMock(return_value="remote")) as m,
        ):
            result = await visit_page("http://u")
        assert result == "remote"

    async def test_visit_page_forwards_prompt_and_tokens_remote(self):
        """prompt and max_content_tokens are forwarded to the remote impl."""
        with (
            patch("offline_search.mcp.settings", MagicMock(is_remote=True)),
            patch("offline_search.mcp._visit_page_remote", new=AsyncMock(return_value="remote")) as m,
        ):
            await visit_page("http://u", prompt="gather", max_content_tokens=200)
        m.assert_called_once_with("http://u", prompt="gather", max_content_tokens=200)


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
