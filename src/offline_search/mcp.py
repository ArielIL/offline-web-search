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

import httpx
from mcp.server.fastmcp import FastMCP

from .config import settings
from .formatter import format_search_result, format_search_result_compact
from .kiwix import fetch_page, html_to_markdown, search_kiwix_html, start_kiwix_server
from .search_engine import SearchResult, search

logger = logging.getLogger(__name__)

mcp = FastMCP("offline-search")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def google_search(query: str, zim_filter: str | None = None) -> str:
    """Search offline documentation and use the results to inform responses.

    Searches indexed ZIM archives (Python docs, Stack Overflow, DevDocs, etc.)
    and returns search results with links and snippets.

    Use this tool for looking up API references, programming guides, technical
    documentation, or any external knowledge.

    WHEN TO SEARCH:
      - Looking up specific APIs, function signatures, or library features
      - Verifying technical details that may differ between versions
      - Researching unfamiliar libraries, tools, or concepts
      - The user explicitly asks you to search or look something up
      - Finding specific facts or details you are unsure about

    WHEN NOT TO SEARCH — rely on your existing knowledge instead:
      - Stable, well-established facts (definitions, theories, fundamentals)
      - General explanations (e.g. "explain how TCP works", "what is recursion")
      - Information that rarely changes (historical dates, language syntax basics)
      - Casual conversation or opinion-based questions
      - Broad coding help like "how to write a for loop"

    QUERY TIPS:
      - Keep queries short and focused — 1 to 6 words work best
      - Break complex questions into multiple separate searches
      - Each query should be meaningfully different from previous ones
      - Include version numbers only when the user specifies one
      - Do not use search operators like '-', 'site:', '+', or 'NOT'

    CRITICAL REQUIREMENT - You MUST follow this:
      - After answering the user's question, you MUST include a "Sources:"
        section at the end of your response
      - In the Sources section, list relevant URLs from the search results
        as markdown hyperlinks: [Title](URL)
      - This is MANDATORY - never skip including sources in your response

    Args:
        query: Search keywords — be specific but concise
               (e.g. 'python asyncio gather', 'sqlite fts5 syntax').
        zim_filter: Optional — restrict results to a specific ZIM library name.
    """
    if settings.is_remote:
        return await _google_search_remote(query, zim_filter=zim_filter)
    return await _google_search_local(query, zim_filter=zim_filter)


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

async def _google_search_local(query: str, *, zim_filter: str | None = None) -> str:
    try:
        results = await search(query, zim_filter=zim_filter)

        if not results:
            # Fallback: scrape Kiwix HTML search (ensure kiwix is running)
            start_kiwix_server()
            html_hits = await search_kiwix_html(query)
            if html_hits:
                results = [
                    SearchResult(
                        title=h["title"], url=h["url"],
                        snippet=h.get("snippet", ""),
                        zim_name="kiwix", namespace="A",
                    )
                    for h in html_hits[:10]
                ]

        formatter = format_search_result_compact if settings.compact_format else format_search_result
        return formatter(query, results or [], settings.kiwix_url)
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

async def _google_search_remote(query: str, *, zim_filter: str | None = None) -> str:
    try:
        params: dict = {"q": query, "limit": settings.search_default_limit}
        if zim_filter:
            params["zim_filter"] = zim_filter

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.search_api_url}/search",
                params=params,
            )

            results: list[SearchResult] = []
            if resp.status_code == 200:
                for r in resp.json():
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("snippet", ""),
                        zim_name=r.get("zim_name", ""),
                        namespace=r.get("namespace", "A"),
                        score=r.get("score", 0.0),
                    ))

        formatter = format_search_result_compact if settings.compact_format else format_search_result
        return formatter(query, results, settings.kiwix_url)

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
