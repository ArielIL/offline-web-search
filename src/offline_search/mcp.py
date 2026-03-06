"""Unified MCP server — local and remote modes in a single entry point.

Exposes ``google_search`` and ``visit_page`` tools over the Model Context
Protocol.  The operating mode is determined by :pydata:`settings.mode`:

* **local** — manages a local kiwix-serve process and searches the SQLite
  FTS5 index directly.
* **remote** — proxies requests to a remote HTTP search API + Kiwix server.

Usage (standalone)::

    python -m offline_search.mcp          # auto-detects mode
    OFFLINE_SEARCH_MODE=remote python -m offline_search.mcp

Or via the entry-point::

    offline-search-mcp
"""

from __future__ import annotations

import logging
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

from .config import settings
from .kiwix import fetch_page, html_to_markdown, search_kiwix_html, start_kiwix_server
from .search_engine import search

logger = logging.getLogger(__name__)

mcp = FastMCP("offline-search")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def google_search(query: str) -> str:
    """Performs a full-text search across the offline documentation library.

    Use this tool whenever you need to look up documentation, API references,
    or technical guides regarding Python, programming, or any other topic
    present in the local library.

    This tool is your **primary source of external information** since you do
    not have internet access.

    Args:
        query: Search keywords — be specific (e.g. 'python asyncio gather',
               'sqlite fts5 syntax', 'react useEffect cleanup').
    """
    if settings.is_remote:
        return await _google_search_remote(query)
    return await _google_search_local(query)


@mcp.tool()
async def visit_page(url: str) -> str:
    """Fetch the full content of a page from the offline documentation library.

    Use this after ``google_search`` when you need to read the complete
    article text rather than just the snippet.

    Args:
        url: The URL of the page to visit (as returned by google_search).
    """
    if settings.is_remote:
        return await _visit_page_remote(url)
    return await _visit_page_local(url)


# ---------------------------------------------------------------------------
# Local-mode implementations
# ---------------------------------------------------------------------------

async def _google_search_local(query: str) -> str:
    try:
        results = await search(query)

        if results:
            lines = [r.format_for_llm(settings.kiwix_url) for r in results]
            return "\n".join(lines)

        # Fallback: scrape Kiwix HTML search (ensure kiwix is running)
        start_kiwix_server()
        html_hits = await search_kiwix_html(query)
        if html_hits:
            lines = [
                f"Title: {h['title']}\nURL: {h['url']}\n"
                f"Snippet: {h.get('snippet', 'No preview available.')}\n"
                for h in html_hits[:10]
            ]
            return "\n".join(lines)

        return "No results found. Try broader or different keywords."

    except Exception as e:
        logger.exception("google_search (local) failed")
        return f"Error executing offline search: {e}"


async def _visit_page_local(url: str) -> str:
    try:
        content = await fetch_page(url)
        if not content:
            return "Page returned empty content."
        return content
    except Exception as e:
        logger.exception("visit_page (local) failed for url=%s", url)
        return f"Error fetching page: {e}"


# ---------------------------------------------------------------------------
# Remote-mode implementations
# ---------------------------------------------------------------------------

async def _google_search_remote(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.search_api_url}/search",
                params={"q": query, "limit": settings.search_default_limit},
            )

            if resp.status_code == 200:
                results = resp.json()
                if results:
                    lines = []
                    for r in results:
                        zim = r.get("zim_name", "")
                        ns = r.get("namespace", "A")
                        partial_url = r.get("url", "")

                        if partial_url.startswith(("http://", "https://")):
                            full_link = partial_url
                        else:
                            encoded = urllib.parse.quote(partial_url, safe="/:?=&%._-#")
                            full_link = f"{settings.kiwix_url}/content/{zim}/{ns}/{encoded}"

                        snippet = r.get("snippet", "No preview available.")
                        lines.append(
                            f"Title: {r['title']}\nURL: {full_link}\nSnippet: {snippet}\n"
                        )
                    return "\n".join(lines)

        return "No results found."

    except Exception as e:
        logger.exception("google_search (remote) failed")
        return f"Error executing search: {e}"


async def _visit_page_remote(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            return html_to_markdown(resp.text)
        else:
            return resp.text[:15_000]
    except Exception as e:
        logger.exception("visit_page (remote) failed for url=%s", url)
        return f"Error fetching page: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Mode: %s", settings.mode)

    if settings.is_local:
        start_kiwix_server()
    else:
        logger.info(
            "Remote mode — proxying to search=%s kiwix=%s",
            settings.search_api_url,
            settings.kiwix_url,
        )

    mcp.run()


if __name__ == "__main__":
    main()
