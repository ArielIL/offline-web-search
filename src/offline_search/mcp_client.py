"""Remote MCP client adapter — thin proxy for distributed deployments.

Forwards ``google_search`` and ``visit_page`` calls to the central HTTP
search API and Kiwix server over the network.

Usage (standalone)::

    python -m offline_search.mcp_client

Or via the entry-point::

    offline-search-client
"""

from __future__ import annotations

import logging
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

from .config import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("offline-search-client")


@mcp.tool()
async def google_search(query: str) -> str:
    """Performs a full-text search across the offline documentation library (Remote Mode).

    Use this tool whenever you need to look up documentation, API references,
    or technical guides.

    Args:
        query: Search keywords (e.g. 'python 3.11 features').
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.remote_search_url}/search",
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
                            full_link = f"{settings.remote_kiwix_url}/content/{zim}/{ns}/{encoded}"

                        snippet = r.get("snippet", "No preview available.")
                        lines.append(
                            f"Title: {r['title']}\nURL: {full_link}\nSnippet: {snippet}\n"
                        )
                    return "\n".join(lines)

        return "No results found."

    except Exception as e:
        logger.exception("google_search (remote) failed")
        return f"Error executing search: {e}"


@mcp.tool()
async def visit_page(url: str) -> str:
    """Fetch the full content of a page from the offline documentation library.

    Use this after ``google_search`` when you need to read the complete
    article text rather than just the snippet.

    Args:
        url: The URL of the page to visit (as returned by google_search).
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        from bs4 import BeautifulSoup
        from markdownify import markdownify as md

        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup.select("nav, header, footer, script, style"):
                tag.decompose()
            text = md(str(soup), strip=["img"])
            lines = [l.rstrip() for l in text.splitlines() if l.strip()]
            return "\n".join(lines)[:15_000]
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
    mcp.run()


if __name__ == "__main__":
    main()
