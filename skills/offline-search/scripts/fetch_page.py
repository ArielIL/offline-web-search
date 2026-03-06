#!/usr/bin/env python3
"""CLI page fetch — prints clean Markdown to stdout.

Meant to be called by Claude Code via the offline-search skill::

    python fetch_page.py "http://127.0.0.1:8081/content/..."

Requires the ``offline_search`` package to be installed.
"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: python fetch_page.py <url>")
        print('Example: python fetch_page.py "http://127.0.0.1:8081/content/..."')
        sys.exit(1)

    url = sys.argv[1]

    try:
        from offline_search.kiwix import fetch_page, start_kiwix_server
    except ImportError:
        print(
            "ERROR: 'offline_search' package not installed.\n"
            "Run: pip install -e path/to/offline-search"
        )
        sys.exit(1)

    # Ensure kiwix-serve is running (no-op if already up)
    start_kiwix_server()

    async def _run() -> str:
        return await fetch_page(url)

    content = asyncio.run(_run())
    if content:
        print(content)
    else:
        print("Page returned empty content.")


if __name__ == "__main__":
    main()
