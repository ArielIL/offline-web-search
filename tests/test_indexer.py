"""Tests for the indexer module — database setup and content ingestion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from offline_search.indexer import (
    _table_exists,
    get_index_stats,
    index_html_page,
    prepare_database,
    remove_by_url,
)


class TestPrepareDatabase:
    def test_creates_tables(self, tmp_path):
        db_path = tmp_path / "new_index.sqlite"
        conn = prepare_database(db_path, reset=True)
        assert _table_exists(conn, "documents")
        assert _table_exists(conn, "metadata")
        conn.close()

    def test_reset_clears_data(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES ('t', 'c', 'z', 'A', 'u')"
        )
        conn.commit()
        conn.close()

        conn2 = prepare_database(db_path, reset=True)
        count = conn2.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 0
        conn2.close()

    def test_no_reset_preserves_data(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES ('t', 'c', 'z', 'A', 'u')"
        )
        conn.commit()
        conn.close()

        conn2 = prepare_database(db_path, reset=False)
        count = conn2.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 1
        conn2.close()


class TestIndexHtmlPage:
    def test_inserts_and_returns_docid(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        docid = index_html_page(
            conn, title="Test", content="Hello world",
            url="http://example.com", source_name="test",
        )
        assert isinstance(docid, int)
        assert docid > 0
        conn.close()


class TestRemoveByUrl:
    def test_removes_matching(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        index_html_page(conn, title="A", content="c", url="http://a.com", source_name="t")
        index_html_page(conn, title="B", content="c", url="http://b.com", source_name="t")
        deleted = remove_by_url(conn, "http://a.com")
        assert deleted == 1
        remaining = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert remaining == 1
        conn.close()


class TestGetIndexStats:
    def test_stats_with_data(self, tmp_db):
        stats = get_index_stats(db_path=tmp_db)
        assert stats["exists"] is True
        assert stats["total_documents"] > 0
        assert len(stats["sources"]) > 0

    def test_stats_missing_db(self, tmp_path):
        stats = get_index_stats(db_path=tmp_path / "nope.sqlite")
        assert stats["exists"] is False
        assert stats["total_documents"] == 0
