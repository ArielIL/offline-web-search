"""Core search engine — single source of truth for FTS5 queries, ranking, and result formatting.

Both the local MCP adapter and the HTTP search server delegate to this module.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "how", "if", "in", "into", "is", "it", "its",
    "no", "not", "of", "on", "or", "so", "such", "that", "the",
    "their", "then", "there", "these", "they", "this", "to", "was",
    "what", "when", "which", "who", "will", "with", "between",
})

# Common programming-term synonyms for lightweight query expansion.
SYNONYMS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "cpp": "c++",
    "csharp": "c#",
    "golang": "go",
    "regex": "regular expression",
    "db": "database",
    "env": "environment",
    "config": "configuration",
    "auth": "authentication",
    "async": "asynchronous",
}

# URL fragments that signal non-English content.
_NON_ENGLISH_MARKERS: tuple[str, ...] = (
    "/ja/", "/zh-cn/", "/zh-tw/", "/ko/", "/fr/", "/de/",
    "/pt-br/", "/pt/", "/es/", "/ru/", "/it/", "/pl/", "/tr/",
)

# URL substrings that should always be filtered out.
_URL_BLACKLIST: tuple[str, ...] = (
    "analytics.python.org",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """One search hit."""
    title: str
    url: str
    snippet: str
    zim_name: str
    namespace: str
    score: float = 0.0
    is_non_english: bool = False

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "zim_name": self.zim_name,
            "namespace": self.namespace,
            "score": self.score,
        }

    def format_full_url(self, kiwix_base_url: str) -> str:
        """Return the complete Kiwix URL for this result."""
        if self.url.startswith(("http://", "https://")):
            return self.url
        safe_fragment = urllib.parse.quote(self.url, safe="/:?=&%._-#")
        ns = self.namespace or "A"
        return f"{kiwix_base_url}/content/{self.zim_name}/{ns}/{safe_fragment}"

    def format_for_llm(self, kiwix_base_url: str) -> str:
        """Return a text block ready for LLM consumption."""
        full_url = self.format_full_url(kiwix_base_url)
        snippet = self.snippet or "No preview available."
        return f"Title: {self.title}\nURL: {full_url}\nSnippet: {snippet}\n"


# ---------------------------------------------------------------------------
# Query processing
# ---------------------------------------------------------------------------

def _tokenize_query(raw_query: str) -> list[str]:
    """Split *raw_query* into individual search terms, stripping stop-words."""
    raw_terms = raw_query.strip().split()
    terms = [t for t in raw_terms if t.lower() not in STOP_WORDS]
    # Fallback: if all words are stop-words keep the originals.
    if not terms and raw_terms:
        terms = raw_terms
    return terms


def _expand_synonyms(terms: list[str]) -> list[str]:
    """Expand well-known abbreviations for broader recall."""
    expanded: list[str] = []
    for t in terms:
        low = t.lower()
        expanded.append(t)
        if low in SYNONYMS and SYNONYMS[low] not in [x.lower() for x in expanded]:
            expanded.append(SYNONYMS[low])
    return expanded


def _build_fts5_or_query(terms: list[str], *, use_prefix: bool = True) -> str:
    """Build a safe FTS5 MATCH expression using OR (any term matches).

    Same quoting/prefix logic as :func:`_build_fts5_query` but joins with
    ``OR`` instead of implicit AND, giving broader recall.
    """
    if not terms:
        return ""
    safe: list[str] = []
    for i, term in enumerate(terms):
        escaped = term.replace('"', '""')
        is_last = i == len(terms) - 1
        if is_last and use_prefix and len(term) >= 2:
            safe.append(f'"{escaped}"*')
        else:
            safe.append(f'"{escaped}"')
    return " OR ".join(safe)


def _build_fts5_query(terms: list[str], *, use_prefix: bool = True) -> str:
    """Build a safe FTS5 MATCH expression from a list of tokens.

    Each term is double-quoted for literal matching.  The last term gets a
    trailing ``*`` for prefix-matching (autocomplete-style behaviour) unless
    *use_prefix* is ``False``.
    """
    if not terms:
        return ""

    safe: list[str] = []
    for i, term in enumerate(terms):
        escaped = term.replace('"', '""')
        is_last = i == len(terms) - 1
        if is_last and use_prefix and len(term) >= 2:
            safe.append(f'"{escaped}"*')
        else:
            safe.append(f'"{escaped}"')
    return " ".join(safe)


# ---------------------------------------------------------------------------
# Search execution
# ---------------------------------------------------------------------------

def _execute_fts5(
    conn: sqlite3.Connection,
    fts_query: str,
    zim_filter: str | None,
    limit: int,
) -> list[sqlite3.Row]:
    """Execute FTS5 MATCH query, return raw rows."""
    sql = (
        "SELECT title, url, zim_name, namespace, "
        f"snippet(documents, 1, '**', '**', ' … ', {settings.snippet_tokens}) AS snippet, "
        "bm25(documents, 10.0, 1.0, 0.0, 0.0, 0.0) AS score "
        "FROM documents WHERE documents MATCH ?"
    )
    params: list = [fts_query]
    if zim_filter:
        sql += " AND zim_name = ?"
        params.append(zim_filter)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        logger.exception("FTS5 query failed: %r", fts_query)
        return []


def search_sync(
    query: str,
    *,
    limit: int | None = None,
    db_path: Path | None = None,
    zim_filter: str | None = None,
) -> list[SearchResult]:
    """Run a full-text search against the SQLite FTS5 index (blocking).

    Uses progressive query relaxation: tries AND first (all terms must match),
    then falls back to OR (any term matches) if AND returns nothing.

    Parameters
    ----------
    query:
        Raw user query string.
    limit:
        Max results to return (defaults to ``settings.search_default_limit``).
    db_path:
        Override the database path (useful for testing).
    zim_filter:
        If set, restrict results to this ``zim_name``.
    """
    limit = limit or settings.search_default_limit
    db = db_path or settings.db_path

    if not db.exists():
        logger.warning("Index database not found at %s", db)
        return []

    terms = _tokenize_query(query)
    if not terms:
        return []

    terms = _expand_synonyms(terms)
    fts_query = _build_fts5_query(terms)
    if not fts_query:
        return []

    overfetch = limit * settings.search_overfetch_factor

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        # Strategy 1: AND (all terms must match) — best precision
        rows = _execute_fts5(conn, fts_query, zim_filter, overfetch)

        # Strategy 2: OR fallback (any term matches) — broader recall
        if not rows and len(terms) > 1:
            fts_or_query = _build_fts5_or_query(terms)
            rows = _execute_fts5(conn, fts_or_query, zim_filter, overfetch)

        candidates: list[SearchResult] = []
        for row in rows:
            url_fragment = row["url"] or ""

            # Hard filter
            if any(bl in url_fragment for bl in _URL_BLACKLIST):
                continue

            is_non_en = any(m in url_fragment for m in _NON_ENGLISH_MARKERS)

            candidates.append(SearchResult(
                title=row["title"] or "",
                url=url_fragment,
                snippet=(row["snippet"] or "").strip(),
                zim_name=row["zim_name"] or "",
                namespace=row["namespace"] or "A",
                score=row["score"],
                is_non_english=is_non_en,
            ))

        # Stable sort: English results first
        candidates.sort(key=lambda c: c.is_non_english)

        return candidates[:limit]
    except sqlite3.Error:
        logger.exception("FTS5 search failed for query=%r", query)
        return []
    finally:
        conn.close()


async def search(
    query: str,
    **kwargs,
) -> list[SearchResult]:
    """Async wrapper around :func:`search_sync`."""
    return await asyncio.to_thread(search_sync, query, **kwargs)
