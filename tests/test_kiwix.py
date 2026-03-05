"""Tests for the kiwix module — process management, page fetching, and HTML search.

Every test mocks I/O (sockets, subprocesses, HTTP) so no live kiwix-serve is needed.
"""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from offline_search.kiwix import (
    fetch_page,
    is_port_open,
    search_kiwix_html,
    start_kiwix_server,
)


# ---------------------------------------------------------------------------
# is_port_open
# ---------------------------------------------------------------------------

class TestIsPortOpen:
    def test_port_open(self):
        """When connect_ex returns 0 the port is open."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("offline_search.kiwix.socket.socket", return_value=mock_sock):
            assert is_port_open(8081) is True

    def test_port_closed(self):
        """When connect_ex returns non-zero the port is closed."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 1
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("offline_search.kiwix.socket.socket", return_value=mock_sock):
            assert is_port_open(8081) is False


# ---------------------------------------------------------------------------
# start_kiwix_server
# ---------------------------------------------------------------------------

class TestStartKiwixServer:
    def test_already_running(self):
        """If the port is already open, return True without spawning."""
        with patch("offline_search.kiwix.is_port_open", return_value=True):
            assert start_kiwix_server(exe="kiwix-serve", port=8081, library_xml="lib.xml") is True

    def test_starts_successfully(self):
        """Spawn kiwix-serve, poll, port opens → True."""
        call_count = 0

        def _port_open(port, host="127.0.0.1"):
            nonlocal call_count
            call_count += 1
            # First call: not running, subsequent calls: running
            return call_count > 1

        with (
            patch("offline_search.kiwix.is_port_open", side_effect=_port_open),
            patch("offline_search.kiwix.subprocess.Popen") as mock_popen,
            patch("offline_search.kiwix.time.sleep"),
        ):
            result = start_kiwix_server(
                exe="kiwix-serve", port=8081, library_xml="lib.xml", timeout=2.0,
            )
            assert result is True
            mock_popen.assert_called_once()

    def test_binary_not_found(self):
        """FileNotFoundError from Popen → return False."""
        with (
            patch("offline_search.kiwix.is_port_open", return_value=False),
            patch(
                "offline_search.kiwix.subprocess.Popen",
                side_effect=FileNotFoundError("no binary"),
            ),
        ):
            assert start_kiwix_server(
                exe="/missing/kiwix-serve", port=8081, library_xml="lib.xml",
            ) is False

    def test_popen_generic_exception(self):
        """Any other Popen exception → return False."""
        with (
            patch("offline_search.kiwix.is_port_open", return_value=False),
            patch(
                "offline_search.kiwix.subprocess.Popen",
                side_effect=PermissionError("denied"),
            ),
        ):
            assert start_kiwix_server(
                exe="kiwix-serve", port=8081, library_xml="lib.xml",
            ) is False

    def test_timeout_waiting_for_port(self):
        """Port never opens within timeout → return False."""
        with (
            patch("offline_search.kiwix.is_port_open", return_value=False),
            patch("offline_search.kiwix.subprocess.Popen"),
            patch("offline_search.kiwix.time.sleep"),
            patch("offline_search.kiwix.time.monotonic", side_effect=[0.0, 0.5, 1.0, 100.0]),
        ):
            assert start_kiwix_server(
                exe="kiwix-serve", port=8081, library_xml="lib.xml", timeout=2.0,
            ) is False


# ---------------------------------------------------------------------------
# fetch_page
# ---------------------------------------------------------------------------

class TestFetchPage:
    """All tests mock httpx so no network is touched."""

    async def test_html_page_converted_to_markdown(self):
        html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_page("http://localhost:8081/page")

        assert "Hello" in result
        assert "World" in result

    async def test_relative_url_prepended(self):
        """A relative URL should be expanded using settings.kiwix_url."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "plain text content"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_page("content/docs/page.html")

        # Verify the client received the full URL
        called_url = mock_client.get.call_args[0][0]
        assert called_url.startswith("http://")
        assert "content/docs/page.html" in called_url
        assert result == "plain text content"

    async def test_plain_text_fallback(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"data": "value"}'
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_page("http://localhost:8081/api")

        assert '{"data": "value"}' == result

    async def test_content_capped_at_15k(self):
        html = "<html><body>" + "<p>word </p>" * 10_000 + "</body></html>"
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_page("http://localhost:8081/big")

        assert len(result) <= 15_000

    async def test_nav_script_elements_removed(self):
        """Boilerplate elements (nav, script, style, footer) should be stripped."""
        html = (
            "<html><body>"
            "<nav>Site nav</nav>"
            "<script>alert(1)</script>"
            "<style>.x{}</style>"
            "<h1>Content</h1>"
            "<footer>Footer</footer>"
            "</body></html>"
        )
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_page("http://localhost:8081/page")

        assert "Content" in result
        assert "Site nav" not in result
        assert "alert(1)" not in result
        assert "Footer" not in result


# ---------------------------------------------------------------------------
# search_kiwix_html
# ---------------------------------------------------------------------------

class TestSearchKiwixHtml:
    async def test_parses_result_list(self):
        """Extract title/url/snippet from <li class='result'> elements."""
        html = """
        <html><body>
        <ul>
          <li class="result">
            <a href="/content/docs/python">Python Guide</a>
            <p>Learn Python programming</p>
          </li>
          <li class="result">
            <a href="/content/docs/js">JS Guide</a>
            <p>Learn JavaScript</p>
          </li>
        </ul>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            results = await search_kiwix_html("python", kiwix_url="http://localhost:8081")

        assert len(results) == 2
        assert results[0]["title"] == "Python Guide"
        assert results[0]["snippet"] == "Learn Python programming"
        assert "localhost:8081" in results[0]["url"]

    async def test_empty_results_page(self):
        html = "<html><body><p>No results found</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            results = await search_kiwix_html("xyzzy", kiwix_url="http://localhost:8081")

        assert results == []

    async def test_http_error_returns_empty(self):
        """Network/HTTP errors should be caught and return []."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            results = await search_kiwix_html("python", kiwix_url="http://localhost:8081")

        assert results == []

    async def test_absolute_hrefs_preserved(self):
        """Links that already start with http should not be prefixed."""
        html = """
        <html><body>
        <li class="result">
          <a href="https://external.com/doc">External Doc</a>
          <p>External snippet</p>
        </li>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("offline_search.kiwix.httpx.AsyncClient", return_value=mock_client):
            results = await search_kiwix_html("external", kiwix_url="http://localhost:8081")

        assert results[0]["url"] == "https://external.com/doc"
