"""Shared WebSearch-format result formatter.

Formats search results into the same structure as Claude Code's WebSearch
tool_result: header, Links JSON array, snippet blocks, and a REMINDER footer
demanding source citations.
"""

from __future__ import annotations

import json

from .search_engine import SearchResult

SOURCES_REMINDER = (
    "REMINDER: You MUST include the sources above in your response "
    "to the user using markdown hyperlinks. Format: [Title](URL). "
    'List sources under a "Sources:" section at the end of your response.'
)

NO_RESULTS_MESSAGE = (
    "No results found.\n\n"
    "Suggestions:\n"
    "- Try shorter or broader keywords (e.g. 'asyncio' instead of 'python asyncio gather timeout')\n"
    "- Try synonyms — auto-expanded: js→javascript, py→python, ts→typescript, "
    "db→database, async→asynchronous, config→configuration, auth→authentication\n"
    "- Try individual key terms separately"
)


def format_search_result(
    query: str,
    results: list[SearchResult],
    kiwix_base_url: str,
) -> str:
    """Format search results into WebSearch-compatible tool_result string."""
    header = f'Offline search results for query: "{query}"'

    if not results:
        return f"{header}\n\n{NO_RESULTS_MESSAGE}"

    # Links JSON array — matches WebSearch [{"title":..,"url":..}, ...]
    links = [
        {"title": r.title, "url": r.format_full_url(kiwix_base_url)}
        for r in results
    ]
    links_line = f"Links: {json.dumps(links)}"

    # Snippet blocks
    snippets = []
    for r in results:
        full_url = r.format_full_url(kiwix_base_url)
        snippet = r.snippet or "No preview available."
        snippets.append(f"**{r.title}**\n{full_url}\n{snippet}")

    parts = [header, links_line, *snippets, SOURCES_REMINDER]
    return "\n\n".join(parts)
