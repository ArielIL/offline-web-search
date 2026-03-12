#!/usr/bin/env python3
"""CLI search — prints formatted results to stdout.

Meant to be called by Claude Code via the offline-search skill::

    python search.py "python asyncio gather"

Requires the ``offline_search`` package to be installed.
"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python search.py <query>")
        print('Example: python search.py "python asyncio gather"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    try:
        from offline_search.config import settings
        from offline_search.formatter import format_search_result
        from offline_search.kiwix import search_kiwix_html, start_kiwix_server
        from offline_search.search_engine import SearchResult, search
    except ImportError:
        print(
            "ERROR: 'offline_search' package not installed.\n"
            "Run: pip install -e path/to/offline-search"
        )
        sys.exit(1)

    async def _run() -> None:
        # Primary: FTS5 index search
        results = await search(query)

        if not results:
            # Fallback: scrape Kiwix's built-in HTML search
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

        print(format_search_result(query, results or [], settings.kiwix_url))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
