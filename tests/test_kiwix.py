"""Tests for the kiwix module — process management and HTML formatting.

No live kiwix-serve is needed for unit testing pure functions here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from offline_search.kiwix import (
    html_to_markdown,
    is_port_open,
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
# html_to_markdown
# ---------------------------------------------------------------------------

class TestHtmlToMarkdown:

    def test_html_page_converted_to_markdown(self):
        html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        result = html_to_markdown(html)
        assert "Hello" in result
        assert "World" in result

    def test_content_capped_at_15k(self):
        html = "<html><body>" + "<p>word </p>" * 10_000 + "</body></html>"
        result = html_to_markdown(html, cap=15_000)
        assert len(result) <= 15_000

    def test_nav_script_elements_removed(self):
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
        result = html_to_markdown(html)
        assert "Content" in result
        assert "Site nav" not in result
        assert "alert(1)" not in result
        assert "Footer" not in result

