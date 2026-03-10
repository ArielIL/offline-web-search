"""ZIM indexer — extracts text from ZIM archives into the SQLite FTS5 database.

This is a refactored version of the original ``build_local_index.py``.
It can be used as a CLI (``offline-search-index``) or imported as a library.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .config import settings

logger = logging.getLogger(__name__)

TEXT_NAMESPACES = {"A", "C"}


# ---------------------------------------------------------------------------
# ZIM iteration
# ---------------------------------------------------------------------------

def iter_articles(zim_path: Path, *, limit: int | None = None) -> Iterable[dict[str, Any]]:
    """Yield article dicts from a ZIM file.

    Each dict has keys: ``namespace``, ``url``, ``title``, ``content``.
    """
    import sys
    from unittest.mock import MagicMock

    # Prevent zimply from monkeypatching the entire process via gevent
    if "gevent" not in sys.modules:
        sys.modules["gevent"] = MagicMock()
        sys.modules["gevent.monkey"] = MagicMock()
        sys.modules["gevent.pywsgi"] = MagicMock()
    
    # pkg_resources was removed in python 3.12, zimply uses it for an unused falcon template
    if "pkg_resources" not in sys.modules:
        sys.modules["pkg_resources"] = MagicMock()

    from zimply.zimply import ZIMFile

    zim = ZIMFile(str(zim_path), "utf-8")
    processed = 0
    try:
        for idx in range(len(zim)):
            try:
                entry = zim.read_directory_entry_by_index(idx)
                namespace = entry.get("namespace")
                if namespace not in TEXT_NAMESPACES:
                    continue

                article = zim._get_article_by_index(idx)
                mimetype = getattr(article, "mimetype", "") or ""
                if not mimetype.startswith("text"):
                    continue

                raw_bytes = article.data or b""
                if not raw_bytes:
                    continue

                html_text = raw_bytes.decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html_text, "html.parser")
                text = soup.get_text("\n", strip=True)
                if not text:
                    continue

                title = entry.get("title")
                if not title and soup.title:
                    title = soup.title.get_text(strip=True)
                if not title:
                    title = entry.get("url")

                yield {
                    "namespace": namespace,
                    "url": entry.get("url"),
                    "title": title,
                    "content": text,
                }

                processed += 1
                if limit is not None and processed >= limit:
                    break
            except Exception:
                logger.debug("Skipping article idx=%d in %s", idx, zim_path, exc_info=True)
    finally:
        zim.close()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_schema_ready: set[str] = set()


def prepare_database(db_path: Path, *, reset: bool = False) -> sqlite3.Connection:
    """Open (and optionally reset) the FTS5 index database.

    Schema creation is cached per *db_path* so that repeated calls (e.g. from
    HTTP request handlers) skip the ``_table_exists`` check after the first
    successful initialisation.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    db_key = str(db_path)
    if reset or db_key not in _schema_ready:
        if reset or not _table_exists(conn, "documents"):
            conn.execute("DROP TABLE IF EXISTS metadata")
            conn.execute("DROP TABLE IF EXISTS documents")
            conn.execute(
                "CREATE VIRTUAL TABLE documents USING fts5("
                "title, content, zim_name, namespace, url, "
                "tokenize='porter'"
                ")"
            )
            conn.execute(
                "CREATE TABLE metadata ("
                "docid INTEGER PRIMARY KEY, "
                "zim_path TEXT NOT NULL"
                ")"
            )
            conn.commit()
        _schema_ready.add(db_key)
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Indexing logic
# ---------------------------------------------------------------------------

def index_zim(
    conn: sqlite3.Connection,
    zim_path: Path,
    zim_name: str,
    *,
    limit: int | None = None,
) -> int:
    """Index a single ZIM file into *conn*. Returns the number of inserted docs."""
    inserted = 0
    cursor = conn.cursor()
    logger.info("Indexing %s …", zim_name)
    for article in iter_articles(zim_path, limit=limit):
        cursor.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES (?, ?, ?, ?, ?)",
            (article["title"], article["content"], zim_name, article["namespace"], article["url"]),
        )
        docid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
            (docid, str(zim_path)),
        )
        inserted += 1
        if inserted % 100 == 0:
            logger.info("  %s: %d articles indexed …", zim_name, inserted)
            conn.commit()

    conn.commit()
    logger.info("  %s: done — %d articles total.", zim_name, inserted)
    return inserted


def index_html_page(
    conn: sqlite3.Connection,
    *,
    title: str,
    content: str,
    url: str,
    source_name: str = "external",
    namespace: str = "W",
) -> int:
    """Index a single HTML/text page. Returns the new docid."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO documents (title, content, zim_name, namespace, url) "
        "VALUES (?, ?, ?, ?, ?)",
        (title, content, source_name, namespace, url),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def remove_by_url(conn: sqlite3.Connection, url: str) -> int:
    """Remove all documents matching *url*. Returns rows deleted."""
    cur = conn.execute(
        "DELETE FROM documents WHERE url = ?", (url,)
    )
    conn.commit()
    return cur.rowcount


def get_index_stats(db_path: Path | None = None) -> dict:
    """Return basic stats about the index."""
    db = db_path or settings.db_path
    if not db.exists():
        return {"total_documents": 0, "sources": [], "exists": False}
    conn = sqlite3.connect(db)
    try:
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        sources_rows = conn.execute(
            "SELECT zim_name, COUNT(*) AS cnt FROM documents GROUP BY zim_name ORDER BY cnt DESC"
        ).fetchall()
        sources = [{"name": r[0], "count": r[1]} for r in sources_rows]
        return {"total_documents": total, "sources": sources, "exists": True}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Library XML parsing
# ---------------------------------------------------------------------------

def load_library(library_path: Path) -> Iterable[dict[str, Any]]:
    """Parse a Kiwix ``library.xml`` and yield book entries."""
    tree = ElementTree.parse(library_path)
    root = tree.getroot()
    library_dir = library_path.parent
    for book in root.findall(".//book"):
        path_attr = book.get("path")
        if not path_attr:
            continue
        zim_path = (library_dir / path_attr).resolve()
        # kiwix-serve uses the filename stem (without .zim) for the URL mount point
        zim_name = zim_path.stem
        tags = book.get("tags", "")
        yield {"zim_name": zim_name, "zim_path": zim_path, "tags": tags}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI: ``offline-search-index``"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Build a local full-text index from ZIM files."
    )
    parser.add_argument(
        "--library", type=Path, default=settings.library_xml,
        help="Path to the library.xml file",
    )
    parser.add_argument(
        "--output", type=Path, default=settings.db_path,
        help="SQLite database output path",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max articles per ZIM to index (useful for quick tests)",
    )
    parser.add_argument(
        "--only-missing", action="store_true",
        help="Skip ZIMs that are already indexed",
    )
    args = parser.parse_args()

    reset = not args.only_missing
    conn = prepare_database(args.output, reset=reset)

    already_indexed: set[Path] = set()
    if args.only_missing:
        cur = conn.execute("SELECT DISTINCT zim_path FROM metadata")
        already_indexed = {Path(row[0]) for row in cur.fetchall()}

    total = 0
    for entry in load_library(args.library):
        zim_path: Path = entry["zim_path"]
        zim_name: str = entry["zim_name"]

        if args.only_missing and zim_path in already_indexed:
            logger.info("[skip] %s already indexed", zim_name)
            continue

        if not zim_path.exists():
            logger.warning("[skip] %s — file not found", zim_path)
            continue

        inserted = index_zim(conn, zim_path, zim_name, limit=args.limit)
        total += inserted

    conn.close()
    logger.info("Indexing complete. %d documents total.", total)


if __name__ == "__main__":
    main()
