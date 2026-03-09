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
    try:
        subprocess.Popen(
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


def filter_content_by_prompt(content: str, prompt: str, *, max_chars: int = 15_000) -> str:
    """Extract sections of *content* that are most relevant to *prompt*.

    This is the offline equivalent of Claude Code's ``web_fetch`` "dynamic
    filtering" mechanism: instead of returning the full page verbatim, only
    the sections that relate to the user's stated intent are included.
    Filtering is keyword-based (no model required).

    The document introduction (first block) is always preserved so the LLM
    has context about the page.  Subsequent blocks are scored by keyword
    overlap with the prompt and included in relevance order until
    *max_chars* is reached.

    Parameters
    ----------
    content:
        Full markdown text of the page.
    prompt:
        User intent / extraction query (e.g. ``"how to use asyncio.gather"``).
    max_chars:
        Maximum number of characters to return.
    """
    if not prompt or not content:
        return content[:max_chars]

    # Import here to avoid a circular import at module level.
    from .search_engine import STOP_WORDS

    # Extract meaningful keywords from the prompt.
    raw_tokens = prompt.lower().split()
    keywords = [t.strip(".,;:!?'\"()[]{}") for t in raw_tokens if t not in STOP_WORDS]
    if not keywords:
        keywords = [t.strip(".,;:!?'\"()[]{}") for t in raw_tokens]  # fallback: keep all
    keywords = [k for k in keywords if k]

    if not keywords:
        return content[:max_chars]

    # Split content into blocks at blank lines or heading boundaries.
    blocks: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current))
                current = []
        elif stripped.startswith("#"):
            if current:
                blocks.append("\n".join(current))
                current = []
            current.append(line)
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    if not blocks:
        return content[:max_chars]

    def _score(block: str) -> int:
        lower = block.lower()
        return sum(1 for kw in keywords if kw in lower)

    # The first block is the document intro/title — always included first.
    intro = blocks[0]
    rest = blocks[1:]

    # Sort remaining blocks by relevance (descending), then by original position
    # so that equally-scored blocks appear in document order.
    scored = sorted(enumerate(rest), key=lambda pair: -_score(pair[1]))

    parts: list[str] = []
    remaining = max_chars

    if intro and remaining > 0:
        chunk = intro[:remaining]
        parts.append(chunk)
        remaining -= len(chunk)

    for _orig_idx, block in scored:
        if remaining <= 0:
            break
        if _score(block) == 0:
            break  # no keyword hits; skip the rest
        chunk = block[:remaining]
        parts.append(chunk)
        remaining -= len(chunk)

    if not parts:
        return content[:max_chars]

    return "\n\n".join(parts)[:max_chars]


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
