"""Tests for the updater module — ZIM version parsing, validation, and zero-downtime ingest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from offline_search.indexer import prepare_database
from offline_search.updater import (
    IngestResult,
    ZimInfo,
    ZIM_MAGIC,
    export_manifest,
    find_older_version,
    get_installed_zims,
    ingest_zim,
    parse_zim_version,
    validate_zim_file,
)


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

class TestParseZimVersion:
    def test_standard_filename(self):
        base, ver = parse_zim_version("devdocs_en_python_2026-01.zim")
        assert base == "devdocs_en_python"
        assert ver == "2026-01"

    def test_no_extension(self):
        base, ver = parse_zim_version("wikipedia_en_2025-03")
        assert base == "wikipedia_en"
        assert ver == "2025-03"

    def test_multiple_underscores(self):
        base, ver = parse_zim_version("stack_overflow_en_all_2025-11.zim")
        assert base == "stack_overflow_en_all"
        assert ver == "2025-11"

    def test_invalid_no_version(self):
        with pytest.raises(ValueError, match="Cannot parse version"):
            parse_zim_version("no_version_here.zim")

    def test_invalid_bad_date(self):
        with pytest.raises(ValueError, match="Cannot parse version"):
            parse_zim_version("test_20251.zim")


# ---------------------------------------------------------------------------
# ZIM file validation
# ---------------------------------------------------------------------------

class TestValidateZimFile:
    def test_valid_zim(self, tmp_path):
        zim = tmp_path / "test_2025-01.zim"
        zim.write_bytes(ZIM_MAGIC + b"\x00" * 100)
        assert validate_zim_file(zim) is True

    def test_wrong_magic(self, tmp_path):
        zim = tmp_path / "test_2025-01.zim"
        zim.write_bytes(b"\x00\x00\x00\x00" + b"\x00" * 100)
        assert validate_zim_file(zim) is False

    def test_wrong_extension(self, tmp_path):
        notazim = tmp_path / "test_2025-01.txt"
        notazim.write_bytes(ZIM_MAGIC + b"\x00" * 100)
        assert validate_zim_file(notazim) is False

    def test_nonexistent(self, tmp_path):
        assert validate_zim_file(tmp_path / "missing.zim") is False

    def test_directory(self, tmp_path):
        assert validate_zim_file(tmp_path) is False


# ---------------------------------------------------------------------------
# Zero-downtime ingest pipeline
# ---------------------------------------------------------------------------

class TestIngestZim:
    """Test the full ingest pipeline with mocked system boundaries."""

    def _make_zim(self, tmp_path: Path, name: str) -> Path:
        """Create a fake ZIM file with valid magic bytes."""
        zim = tmp_path / name
        zim.write_bytes(ZIM_MAGIC + b"\x00" * 100)
        return zim

    def _make_library_xml(self, tmp_path: Path, entries: list[str]) -> Path:
        """Create a minimal library.xml."""
        books = "\n".join(f'  <book path="{e}"/>' for e in entries)
        xml = f'<?xml version="1.0"?>\n<library>\n{books}\n</library>'
        lib = tmp_path / "library.xml"
        lib.write_text(xml, encoding="utf-8")
        return lib

    def test_ingest_new_zim(self, tmp_path):
        """Ingesting a new ZIM should index articles and report success."""
        zim = self._make_zim(tmp_path, "devdocs_en_python_2026-01.zim")
        lib_xml = self._make_library_xml(tmp_path, [])
        db_path = tmp_path / "idx.sqlite"

        fake_articles = [
            {"namespace": "A", "url": "p1", "title": "Page 1", "content": "Content one"},
            {"namespace": "A", "url": "p2", "title": "Page 2", "content": "Content two"},
        ]

        with (
            patch("offline_search.updater.kiwix_manage_add", return_value=True),
            patch("offline_search.updater.restart_kiwix_server", return_value=True),
            patch("offline_search.indexer.iter_articles", return_value=fake_articles),
        ):
            result = ingest_zim(
                zim, library_xml=lib_xml, db_path=db_path, restart_kiwix=False,
            )

        assert result.success is True
        assert result.articles_indexed == 2
        assert result.zim_info.base_name == "devdocs_en_python"
        assert result.zim_info.version == "2026-01"

    def test_ingest_replaces_old_version(self, tmp_path):
        """When an older version exists, its rows should be removed after indexing."""
        old_zim = self._make_zim(tmp_path, "devdocs_en_python_2025-01.zim")
        new_zim = self._make_zim(tmp_path, "devdocs_en_python_2026-01.zim")
        lib_xml = self._make_library_xml(tmp_path, [old_zim.name])
        db_path = tmp_path / "idx.sqlite"

        # Pre-index old content
        conn = prepare_database(db_path, reset=True)
        conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES ('Old', 'old content', 'devdocs_en_python_2025-01', 'A', 'old_page')"
        )
        docid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
            (docid, str(old_zim)),
        )
        conn.commit()
        conn.close()

        fake_articles = [
            {"namespace": "A", "url": "new1", "title": "New Page", "content": "New content"},
        ]

        with (
            patch("offline_search.updater.kiwix_manage_add", return_value=True),
            patch("offline_search.updater.kiwix_manage_remove", return_value=True),
            patch("offline_search.updater.restart_kiwix_server", return_value=True),
            patch("offline_search.indexer.iter_articles", return_value=fake_articles),
        ):
            result = ingest_zim(
                new_zim, library_xml=lib_xml, db_path=db_path, restart_kiwix=False,
            )

        assert result.success is True
        assert result.articles_indexed == 1
        assert result.articles_removed == 1
        assert result.replaced is not None
        assert result.replaced.base_name == "devdocs_en_python"

        # Verify: only new content remains
        import sqlite3
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        assert count == 1
        title = conn.execute("SELECT title FROM documents").fetchone()[0]
        assert title == "New Page"
        conn.close()

    def test_old_content_serves_during_indexing(self, tmp_path):
        """During indexing, both old and new rows coexist in the database."""
        old_zim = self._make_zim(tmp_path, "wiki_en_2025-01.zim")
        new_zim = self._make_zim(tmp_path, "wiki_en_2026-01.zim")
        lib_xml = self._make_library_xml(tmp_path, [old_zim.name])
        db_path = tmp_path / "idx.sqlite"

        # Pre-index old content
        conn = prepare_database(db_path, reset=True)
        conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES ('Old Article', 'old', 'wiki_en_2025-01', 'A', 'old')"
        )
        docid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
            (docid, str(old_zim)),
        )
        conn.commit()

        coexistence_verified = False

        original_index_zim = __import__("offline_search.indexer", fromlist=["index_zim"]).index_zim

        def spy_index_zim(conn, zim_path, zim_name, **kwargs):
            """During indexing, check that old content is still present."""
            nonlocal coexistence_verified
            # Insert a new row to simulate indexing
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO documents (title, content, zim_name, namespace, url) "
                "VALUES ('New Article', 'new', ?, 'A', 'new')",
                (zim_name,),
            )
            new_docid = cur.lastrowid
            cur.execute(
                "INSERT INTO metadata (docid, zim_path) VALUES (?, ?)",
                (new_docid, str(zim_path)),
            )
            conn.commit()
            # Both old and new should be present
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            coexistence_verified = count == 2
            return 1

        conn.close()

        with (
            patch("offline_search.updater.kiwix_manage_add", return_value=True),
            patch("offline_search.updater.kiwix_manage_remove", return_value=True),
            patch("offline_search.updater.restart_kiwix_server", return_value=True),
            patch("offline_search.updater.index_zim", side_effect=spy_index_zim),
        ):
            result = ingest_zim(
                new_zim, library_xml=lib_xml, db_path=db_path, restart_kiwix=False,
            )

        assert result.success is True
        assert coexistence_verified, "Old and new content should coexist during indexing"

    def test_invalid_zim_rejected(self, tmp_path):
        """Invalid ZIM files should be rejected with an error."""
        bad = tmp_path / "bad_2025-01.zim"
        bad.write_bytes(b"\x00" * 100)

        result = ingest_zim(bad, db_path=tmp_path / "idx.sqlite")
        assert result.success is False
        assert any("Invalid ZIM" in e for e in result.errors)

    def test_unparseable_version_rejected(self, tmp_path):
        """ZIM files without a parseable version should be rejected."""
        zim = tmp_path / "noversion.zim"
        zim.write_bytes(ZIM_MAGIC + b"\x00" * 100)

        result = ingest_zim(zim, db_path=tmp_path / "idx.sqlite")
        assert result.success is False
        assert any("Cannot parse version" in e for e in result.errors)

    def test_old_file_deleted_when_flag_set(self, tmp_path):
        """When delete_old=True, the replaced ZIM file should be removed from disk."""
        old_zim = self._make_zim(tmp_path, "test_en_2025-01.zim")
        new_zim = self._make_zim(tmp_path, "test_en_2026-01.zim")
        lib_xml = self._make_library_xml(tmp_path, [old_zim.name])
        db_path = tmp_path / "idx.sqlite"

        # Pre-index old
        conn = prepare_database(db_path, reset=True)
        conn.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) "
            "VALUES ('Old', 'c', 'test_en_2025-01', 'A', 'old')"
        )
        docid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO metadata (docid, zim_path) VALUES (?, ?)", (docid, str(old_zim)))
        conn.commit()
        conn.close()

        with (
            patch("offline_search.updater.kiwix_manage_add", return_value=True),
            patch("offline_search.updater.kiwix_manage_remove", return_value=True),
            patch("offline_search.updater.restart_kiwix_server", return_value=True),
            patch("offline_search.indexer.iter_articles", return_value=[]),
        ):
            result = ingest_zim(
                new_zim, library_xml=lib_xml, db_path=db_path,
                delete_old=True, restart_kiwix=False,
            )

        assert result.success is True
        assert not old_zim.exists(), "Old ZIM file should be deleted"


# ---------------------------------------------------------------------------
# Manifest export
# ---------------------------------------------------------------------------

class TestExportManifest:
    def test_manifest_round_trip(self, tmp_path):
        """Manifest export should produce a JSON-serialisable list."""
        lib_xml = tmp_path / "library.xml"
        lib_xml.write_text(
            '<?xml version="1.0"?><library>'
            '<book path="devdocs_en_python_2026-01.zim"/>'
            '</library>',
            encoding="utf-8",
        )

        manifest = export_manifest(lib_xml)
        assert isinstance(manifest, list)
        assert len(manifest) == 1
        assert manifest[0]["base_name"] == "devdocs_en_python"
        assert manifest[0]["version"] == "2026-01"
