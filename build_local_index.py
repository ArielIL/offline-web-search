import argparse
import sqlite3
from pathlib import Path
from xml.etree import ElementTree
from collections.abc import Iterable
from typing import Any

from bs4 import BeautifulSoup
from zimply.zimply import ZIMFile

DEFAULT_LIBRARY = Path(r"D:\Downloads\library.xml")
DEFAULT_OUTPUT = Path("data/offline_index.sqlite")
TEXT_NAMESPACES = {"A", "C"}


def iter_articles(zim_path: Path, limit: int | None = None) -> Iterable[dict[str, Any]]:
    zim = ZIMFile(str(zim_path), "utf-8")
    processed = 0
    try:
        for idx in range(len(zim)):
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

            title = entry.get("title") or soup.title.string.strip() if soup.title else entry.get("url")

            yield {
                "namespace": namespace,
                "url": entry.get("url"),
                "title": title,
                "content": text,
            }

            processed += 1
            if limit is not None and processed >= limit:
                break
    finally:
        zim.close()


def prepare_database(db_path: Path, reset: bool) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")

    if reset or not db_path.exists():
        conn.execute("DROP TABLE IF EXISTS metadata")
        conn.execute("DROP TABLE IF EXISTS documents")
        conn.execute(
            "CREATE VIRTUAL TABLE documents USING fts5(title, content, zim_name, namespace, url, tokenize='porter')"
        )
        conn.execute(
            "CREATE TABLE metadata (docid INTEGER PRIMARY KEY, zim_path TEXT NOT NULL)"
        )
        conn.commit()
    return conn


def index_zim(conn: sqlite3.Connection, zim_path: Path, zim_name: str, limit: Optional[int]) -> int:
    inserted = 0
    cursor = conn.cursor()
    for article in iter_articles(zim_path, limit=limit):
        cursor.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) VALUES (?, ?, ?, ?, ?)",
            (
                article["title"],
                article["content"],
                zim_name,
                article["namespace"],
                article["url"],
            ),
        )
        docid = cursor.lastrowid
        cursor.execute(
            "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
            (docid, str(zim_path)),
        )
        inserted += 1
    conn.commit()
    return inserted


def load_library(library_path: Path) -> Iterable[Dict[str, Any]]:
    tree = ElementTree.parse(library_path)
    root = tree.getroot()
    library_dir = library_path.parent
    for book in root.findall(".//book"):
        path_attr = book.get("path")
        if not path_attr:
            continue
        zim_path = (library_dir / path_attr).resolve()
        zim_name = book.get("name") or zim_path.stem
        tags = book.get("tags", "")
        yield {
            "zim_name": zim_name,
            "zim_path": zim_path,
            "tags": tags,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local full-text index from ZIM files")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY, help="Path to the library.xml file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="SQLite database output path")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit of articles per ZIM to index (useful for quick tests)",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Skip ZIMs that already have an index entry in the metadata table",
    )

    args = parser.parse_args()

    reset = not args.only_missing
    conn = prepare_database(args.output, reset=reset)

    already_indexed = set()
    if args.only_missing:
        cur = conn.execute("SELECT DISTINCT zim_path FROM metadata")
        already_indexed = {Path(row[0]) for row in cur.fetchall()}

    for entry in load_library(args.library):
        zim_path: Path = entry["zim_path"]
        zim_name: str = entry["zim_name"]

        if args.only_missing and zim_path in already_indexed:
            continue

        if not zim_path.exists():
            print(f"[skip] {zim_path} not found")
            continue

        print(f"[index] {zim_name} -> {zim_path}")
        inserted = index_zim(conn, zim_path, zim_name, limit=args.limit)
        print(f"  inserted {inserted} documents")

    conn.close()


if __name__ == "__main__":
    main()
