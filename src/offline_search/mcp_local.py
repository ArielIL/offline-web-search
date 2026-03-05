"""Local MCP server — all-in-one mode.

Exposes ``google_search`` and ``visit_page`` tools over the Model Context
Protocol.  Manages a local kiwix-serve process and searches the SQLite
FTS5 index directly.

Usage (standalone)::

    python -m offline_search.mcp_local

Or via the entry-point::

    offline-search-mcp
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .config import settings
from .kiwix import fetch_page, search_kiwix_html, start_kiwix_server
from .search_engine import search

logger = logging.getLogger(__name__)

mcp = FastMCP("offline-search")


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
    try:
        results = await search(query)

        if results:
            lines = [r.format_for_llm(settings.kiwix_url) for r in results]
            return "\n".join(lines)

        # Fallback: scrape Kiwix HTML search
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
        logger.exception("google_search failed")
        return f"Error executing offline search: {e}"


@mcp.tool()
async def visit_page(url: str) -> str:
    """Fetch the full content of a page from the offline documentation library.

    Use this after ``google_search`` when you need to read the complete
    article text rather than just the snippet.

    Args:
        url: The URL of the page to visit (as returned by google_search).
    """
    try:
        content = await fetch_page(url)
        if not content:
            return "Page returned empty content."
        return content
    except Exception as e:
        logger.exception("visit_page failed for url=%s", url)
        return f"Error fetching page: {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    start_kiwix_server()
    mcp.run()


if __name__ == "__main__":
    main()
