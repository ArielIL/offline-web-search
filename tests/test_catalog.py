"""Tests for the catalog module — OPDS parsing, version comparison, checksum, manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from offline_search.catalog import (
    CatalogEntry,
    WatchConfig,
    _parse_opds_feed,
    check_updates_for_installed,
    compare_versions,
    download_zim,
    export_manifest,
    fetch_catalog,
    load_manifest,
    verify_checksum,
)
from offline_search.updater import ZimInfo


# ---------------------------------------------------------------------------
# OPDS parsing
# ---------------------------------------------------------------------------

SAMPLE_OPDS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Python DevDocs</title>
    <summary>Python documentation from DevDocs</summary>
    <link type="application/x-zim"
          href="https://mirror.example.com/devdocs_en_python_2026-01.zim"
          length="52428800"/>
  </entry>
  <entry>
    <title>Wikipedia English</title>
    <summary>English Wikipedia</summary>
    <link type="application/x-zim"
          href="https://mirror.example.com/wikipedia_en_2025-11.zim"
          length="104857600"/>
  </entry>
</feed>
"""


class TestParseCatalog:
    def test_parses_entries(self):
        entries = _parse_opds_feed(SAMPLE_OPDS)
        assert len(entries) == 2

    def test_entry_fields(self):
        entries = _parse_opds_feed(SAMPLE_OPDS)
        e = entries[0]
        assert e.name == "devdocs_en_python"
        assert e.version == "2026-01"
        assert e.title == "Python DevDocs"
        assert e.description == "Python documentation from DevDocs"
        assert "devdocs_en_python_2026-01.zim" in e.url
        assert e.size == 52428800

    def test_second_entry(self):
        entries = _parse_opds_feed(SAMPLE_OPDS)
        e = entries[1]
        assert e.name == "wikipedia_en"
        assert e.version == "2025-11"

    def test_empty_feed(self):
        xml = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        assert _parse_opds_feed(xml) == []

    def test_entry_without_zim_link(self):
        xml = """\
<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>No ZIM</title>
    <link type="text/html" href="https://example.com"/>
  </entry>
</feed>"""
        entries = _parse_opds_feed(xml)
        assert len(entries) == 1
        assert entries[0].url == ""


class TestFetchCatalog:
    def test_fetches_and_parses(self):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_OPDS
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("offline_search.catalog.httpx.Client", return_value=mock_client):
            entries = fetch_catalog(query="python", catalog_url="https://example.com/catalog")

        assert len(entries) == 2
        mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

class TestCompareVersions:
    def test_finds_newer_version(self):
        installed = [
            ZimInfo("devdocs_en_python", "2025-01", "devdocs_en_python_2025-01.zim", Path("/z")),
        ]
        catalog = [
            CatalogEntry("devdocs_en_python", "2026-01", "Python DevDocs", "", "url", 0, "en", ""),
        ]
        updates = compare_versions(installed, catalog)
        assert len(updates) == 1
        assert updates[0].available.version == "2026-01"

    def test_no_update_when_same_version(self):
        installed = [
            ZimInfo("wiki_en", "2025-03", "wiki_en_2025-03.zim", Path("/z")),
        ]
        catalog = [
            CatalogEntry("wiki_en", "2025-03", "Wikipedia", "", "url", 0, "en", ""),
        ]
        assert compare_versions(installed, catalog) == []

    def test_no_update_when_older_in_catalog(self):
        installed = [
            ZimInfo("wiki_en", "2026-01", "wiki_en_2026-01.zim", Path("/z")),
        ]
        catalog = [
            CatalogEntry("wiki_en", "2025-01", "Wikipedia", "", "url", 0, "en", ""),
        ]
        assert compare_versions(installed, catalog) == []

    def test_ignores_uninstalled(self):
        """Catalog entries for ZIMs not installed locally should be ignored."""
        installed = [
            ZimInfo("wiki_en", "2025-01", "wiki_en_2025-01.zim", Path("/z")),
        ]
        catalog = [
            CatalogEntry("devdocs_python", "2026-01", "Python", "", "url", 0, "en", ""),
        ]
        assert compare_versions(installed, catalog) == []


# ---------------------------------------------------------------------------
# Update checking (bug fix: single-page truncation)
# ---------------------------------------------------------------------------

class TestCheckUpdatesForInstalled:
    """check_updates_for_installed must find updates for ALL installed ZIMs,
    even those that would not appear on the catalog's default first page."""

    def _fake_catalog(self, catalog: dict[str, CatalogEntry]):
        """Return a fetch_catalog stub backed by a name→entry dict.

        A query matching an entry's name returns that entry.
        A parameterless call returns nothing — simulating the real catalog's
        first-page truncation that caused the original bug.
        """
        def fake_fetch(query=None, *, name=None, catalog_url=None, verify_tls=True, timeout=30.0):
            key = name or query
            if key and key in catalog:
                return [catalog[key]]
            return []
        return fake_fetch

    def test_finds_updates_for_all_installed_zims(self):
        """Updates are found for every installed ZIM, not just those on page 1."""
        installed = [
            ZimInfo("reverseengineering.stackexchange.com_en_all", "2025-12",
                    "reverseengineering.stackexchange.com_en_all_2025-12.zim", Path("/z")),
            ZimInfo("devdocs_en_python", "2025-06",
                    "devdocs_en_python_2025-06.zim", Path("/z")),
        ]
        catalog = {
            "reverseengineering.stackexchange.com_en_all": CatalogEntry(
                "reverseengineering.stackexchange.com_en_all", "2026-02",
                "RE Stack Exchange", "", "https://mirror/re_2026-02.zim", 1024, "en", "",
            ),
            "devdocs_en_python": CatalogEntry(
                "devdocs_en_python", "2026-01",
                "Python DevDocs", "", "https://mirror/devdocs_2026-01.zim", 1024, "en", "",
            ),
        }

        with patch("offline_search.catalog.fetch_catalog", side_effect=self._fake_catalog(catalog)):
            updates = check_updates_for_installed(installed)

        updated_names = {u.installed.base_name for u in updates}
        assert updated_names == {
            "reverseengineering.stackexchange.com_en_all",
            "devdocs_en_python",
        }

    def test_no_updates_when_all_current(self):
        installed = [
            ZimInfo("wiki_en", "2026-01", "wiki_en_2026-01.zim", Path("/z")),
        ]
        catalog = {
            "wiki_en": CatalogEntry("wiki_en", "2026-01", "Wiki", "", "url", 0, "en", ""),
        }

        with patch("offline_search.catalog.fetch_catalog", side_effect=self._fake_catalog(catalog)):
            updates = check_updates_for_installed(installed)

        assert updates == []

    def test_mixed_some_updated_some_current(self):
        """Only ZIMs with newer catalog versions appear in updates."""
        installed = [
            ZimInfo("alpha", "2025-01", "alpha_2025-01.zim", Path("/z")),
            ZimInfo("beta", "2026-01", "beta_2026-01.zim", Path("/z")),
            ZimInfo("gamma", "2025-06", "gamma_2025-06.zim", Path("/z")),
        ]
        catalog = {
            "alpha": CatalogEntry("alpha", "2026-01", "", "", "url", 0, "en", ""),
            "beta": CatalogEntry("beta", "2026-01", "", "", "url", 0, "en", ""),   # same
            "gamma": CatalogEntry("gamma", "2026-02", "", "", "url", 0, "en", ""),
        }

        with patch("offline_search.catalog.fetch_catalog", side_effect=self._fake_catalog(catalog)):
            updates = check_updates_for_installed(installed)

        updated_names = {u.installed.base_name for u in updates}
        assert updated_names == {"alpha", "gamma"}


# ---------------------------------------------------------------------------
# Checksum verification
# ---------------------------------------------------------------------------

class TestVerifyChecksum:
    def test_valid_checksum(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert verify_checksum(f, expected) is True

    def test_invalid_checksum(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        assert verify_checksum(f, "0" * 64) is False

    def test_empty_checksum_skips(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"data")
        assert verify_checksum(f, "") is True


# ---------------------------------------------------------------------------
# Download with checksum
# ---------------------------------------------------------------------------

class TestDownloadZim:
    def test_download_and_verify(self, tmp_path):
        """Successful download should write file and verify checksum."""
        content = b"fake zim content"
        sha = hashlib.sha256(content).hexdigest()
        entry = CatalogEntry("test", "2026-01", "Test", "", "https://example.com/test_2026-01.zim", len(content), "en", sha)

        # Mock streaming response
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_bytes.return_value = [content]
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("offline_search.catalog.httpx.Client", return_value=mock_client):
            path = download_zim(entry, tmp_path)

        assert path.exists()
        assert path.read_bytes() == content

    def test_download_checksum_mismatch_deletes_file(self, tmp_path):
        """If checksum fails, the downloaded file should be deleted."""
        content = b"fake zim content"
        entry = CatalogEntry("test", "2026-01", "Test", "", "https://example.com/test_2026-01.zim", len(content), "en", "bad_checksum")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_bytes.return_value = [content]
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("offline_search.catalog.httpx.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="Checksum verification failed"):
                download_zim(entry, tmp_path)

        # File should be cleaned up
        assert not (tmp_path / "test_2026-01.zim").exists()


# ---------------------------------------------------------------------------
# Manifest round-trip
# ---------------------------------------------------------------------------

class TestManifestRoundTrip:
    def test_export_and_load(self, tmp_path):
        zims = [
            ZimInfo("wiki_en", "2025-03", "wiki_en_2025-03.zim", Path("/z/wiki_en_2025-03.zim")),
            ZimInfo("devdocs_python", "2026-01", "devdocs_python_2026-01.zim", Path("/z/devdocs_python_2026-01.zim")),
        ]
        manifest_path = tmp_path / "manifest.json"
        export_manifest(zims, manifest_path)

        loaded = load_manifest(manifest_path)
        assert len(loaded) == 2
        assert loaded[0].base_name == "wiki_en"
        assert loaded[0].version == "2025-03"
        assert loaded[1].base_name == "devdocs_python"

    def test_load_empty_manifest(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("[]", encoding="utf-8")
        assert load_manifest(p) == []
