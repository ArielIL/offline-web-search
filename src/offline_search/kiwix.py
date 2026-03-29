"""Kiwix-serve process lifecycle management.

Handles starting, health-checking, and page-fetching from the local
kiwix-serve instance.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

_kiwix_process: subprocess.Popen | None = None


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Return ``True`` if *port* is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def start_kiwix_server(
    *,
    exe: str | None = None,
    port: int | None = None,
    library_xml: str | None = None,
    timeout: float = 8.0,
) -> bool:
    """Start kiwix-serve in the background if it is not already running.

    Returns ``True`` if the server is reachable after this call.
    """
    exe = exe or settings.kiwix_exe
    port = port or settings.kiwix_port
    library_xml = library_xml or settings.library_xml

    if is_port_open(port):
        logger.info("Kiwix server already running on port %d", port)
        return True

    logger.info("Starting kiwix-serve on port %d …", port)
    global _kiwix_process
    try:
        _kiwix_process = subprocess.Popen(
            [exe, "--port", str(port), "--library", library_xml],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.error("kiwix-serve binary not found at %r", exe)
        return False
    except Exception:
        logger.exception("Failed to start kiwix-serve")
        return False

    # Poll until the port opens
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_port_open(port):
            logger.info("Kiwix server started successfully.")
            return True
        time.sleep(0.4)

    logger.warning("Kiwix server did not respond within %.1fs", timeout)
    return False


def stop_kiwix_server(*, timeout: float = 5.0) -> bool:
    """Stop the kiwix-serve process started by :func:`start_kiwix_server`.

    Returns ``True`` if the process was stopped (or was not running).
    """
    global _kiwix_process
    if _kiwix_process is None:
        logger.info("No kiwix-serve process to stop.")
        return True

    logger.info("Stopping kiwix-serve (pid=%d) …", _kiwix_process.pid)
    try:
        _kiwix_process.terminate()
        _kiwix_process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("kiwix-serve did not stop gracefully, killing …")
        _kiwix_process.kill()
        _kiwix_process.wait(timeout=2.0)
    except Exception:
        logger.exception("Failed to stop kiwix-serve")
        return False
    finally:
        _kiwix_process = None

    logger.info("kiwix-serve stopped.")
    return True


def restart_kiwix_server(
    *,
    exe: str | None = None,
    port: int | None = None,
    library_xml: str | None = None,
    timeout: float = 8.0,
) -> bool:
    """Stop and restart kiwix-serve. Returns ``True`` if healthy after restart."""
    stop_kiwix_server()
    # Brief pause to release the port
    time.sleep(0.5)
    return start_kiwix_server(
        exe=exe, port=port, library_xml=library_xml, timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Page fetching
# ---------------------------------------------------------------------------

def html_to_markdown(html: str, *, cap: int = 15_000) -> str:
    """Convert HTML to clean Markdown, stripping boilerplate elements.

    This is the **single source of truth** for HTML → Markdown conversion,
    shared by :func:`fetch_page` (local) and the remote ``visit_page`` path
    in :mod:`offline_search.mcp`.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("nav, header, footer, script, style, .mw-jump-link"):
        tag.decompose()
    markdown_text = md(str(soup), strip=["img"])
    lines = [line.rstrip() for line in markdown_text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned[:cap]


async def fetch_page(url: str, *, timeout: float = 10.0) -> str:
    """Fetch a page from Kiwix and return it as clean Markdown text.

    *url* can be either a full ``http://`` URL or a path relative to the
    Kiwix base URL.
    """
    if not url.startswith(("http://", "https://")):
        url = f"{settings.kiwix_url}/{url.lstrip('/')}"

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        return html_to_markdown(resp.text)
    else:
        return resp.text[:15_000]


async def search_kiwix_html(query: str, kiwix_url: str | None = None) -> list[dict]:
    """Fallback: scrape Kiwix's built-in HTML search results page."""
    base = kiwix_url or settings.kiwix_url
    search_url = f"{base}/search?pattern={urllib.parse.quote(query)}"

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(search_url)
            resp.raise_for_status()
    except Exception:
        logger.exception("Kiwix HTML search failed")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict] = []

    for result_el in soup.select("li.result, div.result_row, div.result, tr.result"):
        link = result_el.find("a")
        if not link:
            continue
        title = link.get_text(strip=True)
        href = link.get("href", "")
        if href and not href.startswith("http"):
            href = f"{base}{href}"
        snippet_el = result_el.find("p") or result_el.find("div", class_="snippet")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        results.append({"title": title, "url": href, "snippet": snippet})

    return results
