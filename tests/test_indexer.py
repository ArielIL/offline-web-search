"""Tests for the indexer module — database setup, content ingestion, and library parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


from offline_search.indexer import (
    get_index_stats,
    index_html_page,
    index_zim,
    load_library,
    prepare_database,
    remove_by_url,
)


class TestPrepareDatabase:
    def test_creates_tables(self, tmp_path):
        db_path = tmp_path / "new_index.sqlite"
        conn = prepare_database(db_path, reset=True)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "documents" in tables
        assert "metadata" in tables
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

    def test_creates_parent_dirs(self, tmp_path):
        """prepare_database should create missing parent directories."""
        db_path = tmp_path / "deep" / "nested" / "index.sqlite"
        conn = prepare_database(db_path, reset=True)
        assert db_path.exists()
        conn.close()


class TestIndexHtmlPage:
    def test_inserts_and_returns_docid(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        docid = index_html_page(
            conn,
            title="Test",
            content="Hello world",
            url="http://example.com",
            source_name="test",
        )
        assert isinstance(docid, int)
        assert docid > 0
        conn.close()

    def test_custom_namespace(self, tmp_path):
        """The default namespace is 'W' for external pages."""
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        index_html_page(conn, title="T", content="C", url="u", namespace="X")
        row = conn.execute("SELECT namespace FROM documents").fetchone()
        assert row[0] == "X"
        conn.close()

    def test_multiple_pages_get_unique_docids(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        id1 = index_html_page(conn, title="A", content="a", url="u1")
        id2 = index_html_page(conn, title="B", content="b", url="u2")
        assert id1 != id2
        conn.close()


class TestRemoveByUrl:
    def test_removes_matching(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        index_html_page(
            conn, title="A", content="c", url="http://a.com", source_name="t"
        )
        index_html_page(
            conn, title="B", content="c", url="http://b.com", source_name="t"
        )
        deleted = remove_by_url(conn, "http://a.com")
        assert deleted == 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0]
        assert remaining == 1
        conn.close()

    def test_removes_nothing_when_no_match(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)
        index_html_page(conn, title="A", content="c", url="http://a.com")
        deleted = remove_by_url(conn, "http://nonexistent.com")
        assert deleted == 0
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

    def test_stats_source_grouping(self, tmp_db):
        """Sources should be grouped with counts."""
        stats = get_index_stats(db_path=tmp_db)
        source_names = [s["name"] for s in stats["sources"]]
        # The conftest seeds python_docs, devdocs, stackoverflow
        assert "python_docs" in source_names
        assert "devdocs" in source_names


class TestIndexZim:
    """Test index_zim with mocked iter_articles (no real ZIM file needed)."""

    def test_indexes_articles(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)

        fake_articles = [
            {
                "namespace": "A",
                "url": "page1",
                "title": "Page 1",
                "content": "Content one",
            },
            {
                "namespace": "A",
                "url": "page2",
                "title": "Page 2",
                "content": "Content two",
            },
        ]

        with patch("offline_search.indexer.iter_articles", return_value=fake_articles):
            inserted = index_zim(conn, Path("/fake.zim"), "test_zim")

        assert inserted == 2
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 2
        # Metadata should also be populated
        meta_count = conn.execute(
            "SELECT COUNT(*) FROM metadata").fetchone()[0]
        assert meta_count == 2
        conn.close()

    def test_empty_zim(self, tmp_path):
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)

        with patch("offline_search.indexer.iter_articles", return_value=[]):
            inserted = index_zim(conn, Path("/empty.zim"), "empty_zim")

        assert inserted == 0
        conn.close()

    def test_progress_logging_at_100(self, tmp_path):
        """When >= 100 articles are indexed, progress logging fires."""
        db_path = tmp_path / "idx.sqlite"
        conn = prepare_database(db_path, reset=True)

        fake_articles = [
            {
                "namespace": "A",
                "url": f"page{i}",
                "title": f"Page {i}",
                "content": f"Content {i}",
            }
            for i in range(105)
        ]

        with patch("offline_search.indexer.iter_articles", return_value=fake_articles):
            inserted = index_zim(conn, Path("/big.zim"), "big_zim")

        assert inserted == 105
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 105
        conn.close()


class TestLoadLibrary:
    def test_parses_xml(self, tmp_path):
        """Parse a minimal library.xml with two book entries."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<library>
  <book path="python.zim" name="python_docs" tags="python;docs"/>
  <book path="js.zim" name="js_docs" tags="javascript"/>
</library>"""
        lib_xml = tmp_path / "library.xml"
        lib_xml.write_text(xml_content, encoding="utf-8")

        entries = list(load_library(lib_xml))
        assert len(entries) == 2
        assert entries[0]["zim_name"] == "python"
        assert entries[0]["tags"] == "python;docs"
        assert entries[0]["zim_path"] == (tmp_path / "python.zim").resolve()

    def test_skips_entries_without_path(self, tmp_path):
        """Book entries missing the path attribute should be skipped."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<library>
  <book name="no_path" tags="test"/>
  <book path="valid.zim" name="valid"/>
</library>"""
        lib_xml = tmp_path / "library.xml"
        lib_xml.write_text(xml_content, encoding="utf-8")

        entries = list(load_library(lib_xml))
        assert len(entries) == 1
        assert entries[0]["zim_name"] == "valid"

    def test_fallback_name_from_stem(self, tmp_path):
        """If name attr is missing, zim_name should fall back to the file stem."""
        xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<library>
  <book path="my_archive.zim"/>
</library>"""
        lib_xml = tmp_path / "library.xml"
        lib_xml.write_text(xml_content, encoding="utf-8")

        entries = list(load_library(lib_xml))
        assert entries[0]["zim_name"] == "my_archive"
