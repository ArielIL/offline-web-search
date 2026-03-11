"""Tests for config module — defaults, env var overrides, mode detection, and helpers."""

from __future__ import annotations

import sys
from unittest.mock import patch

from offline_search.config import Settings, _detect_kiwix_exe


class TestSettings:
    def test_default_ports(self):
        s = Settings()
        assert s.kiwix_port == 8081
        assert s.server_port == 8082

    def test_kiwix_url_local_mode(self):
        """In local mode, kiwix_url derives from kiwix_port."""
        s = Settings(mode="local", kiwix_port=9999)
        assert s.kiwix_url == "http://127.0.0.1:9999"

    def test_kiwix_url_remote_mode(self):
        """In remote mode, kiwix_url derives from remote_host + remote_kiwix_port."""
        s = Settings(mode="remote", remote_host="10.0.0.5", remote_kiwix_port=6000)
        assert s.kiwix_url == "http://10.0.0.5:6000"

    def test_remote_urls(self):
        s = Settings(mode="remote", remote_host="10.0.0.5", remote_search_port=5000, remote_kiwix_port=6000)
        assert s.remote_search_url == "http://10.0.0.5:5000"
        assert s.remote_kiwix_url == "http://10.0.0.5:6000"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OFFLINE_SEARCH_SERVER_PORT", "9999")
        s = Settings()
        assert s.server_port == 9999

    # --- Mode detection ---

    def test_default_mode_is_local(self):
        s = Settings()
        assert s.mode == "local"
        assert s.is_local is True
        assert s.is_remote is False

    def test_auto_detect_remote_from_host(self):
        """Setting remote_host to a non-localhost value auto-selects remote mode."""
        s = Settings(remote_host="192.168.1.50")
        assert s.mode == "remote"
        assert s.is_remote is True

    def test_explicit_mode_overrides_auto(self):
        """An explicit mode='local' stays local even with a non-localhost remote_host."""
        s = Settings(mode="local", remote_host="192.168.1.50")
        assert s.mode == "local"
        assert s.is_local is True

    def test_explicit_remote_mode(self):
        s = Settings(mode="remote")
        assert s.is_remote is True

    def test_search_api_url(self):
        s = Settings(remote_host="10.0.0.5", remote_search_port=5000)
        assert s.search_api_url == "http://10.0.0.5:5000"


class TestDetectKiwixExe:
    """Tests for kiwix-serve binary auto-detection."""

    def test_detects_kiwix_inside_repo(self, tmp_path):
        """kiwix-serve inside the project root takes priority."""
        kiwix_tools = tmp_path / "kiwix-tools"
        kiwix_tools.mkdir()
        bin_name = "kiwix-serve.exe" if sys.platform == "win32" else "kiwix-serve"
        kiwix_bin = kiwix_tools / bin_name
        kiwix_bin.touch()

        with patch("offline_search.config._detect_base_dir", return_value=tmp_path):
            result = _detect_kiwix_exe()

        assert result == str(kiwix_bin)

    def test_detects_kiwix_next_to_repo(self, tmp_path):
        """kiwix-serve next to the project (sibling directory) is detected as fallback."""
        repo_dir = tmp_path / "offline-web-search"
        repo_dir.mkdir()
        sibling_tools = tmp_path / "kiwix-tools"
        sibling_tools.mkdir()
        bin_name = "kiwix-serve.exe" if sys.platform == "win32" else "kiwix-serve"
        kiwix_bin = sibling_tools / bin_name
        kiwix_bin.touch()

        with patch("offline_search.config._detect_base_dir", return_value=repo_dir):
            result = _detect_kiwix_exe()

        assert result == str(kiwix_bin)

    def test_inside_repo_takes_priority_over_sibling(self, tmp_path):
        """When kiwix-serve exists both inside and next to repo, inside wins."""
        repo_dir = tmp_path / "offline-web-search"
        repo_dir.mkdir()
        bin_name = "kiwix-serve.exe" if sys.platform == "win32" else "kiwix-serve"

        inner_tools = repo_dir / "kiwix-tools"
        inner_tools.mkdir()
        inner_bin = inner_tools / bin_name
        inner_bin.touch()

        sibling_tools = tmp_path / "kiwix-tools"
        sibling_tools.mkdir()
        (sibling_tools / bin_name).touch()

        with patch("offline_search.config._detect_base_dir", return_value=repo_dir):
            result = _detect_kiwix_exe()

        assert result == str(inner_bin)

    def test_falls_back_to_path(self, tmp_path):
        """Falls back to PATH when kiwix-serve is not found in either local location."""
        repo_dir = tmp_path / "offline-web-search"
        repo_dir.mkdir()

        with patch("offline_search.config._detect_base_dir", return_value=repo_dir), \
             patch("offline_search.config.shutil.which", return_value="/usr/bin/kiwix-serve"):
            result = _detect_kiwix_exe()

        assert result == "/usr/bin/kiwix-serve"

    def test_fallback_binary_name_when_not_found(self, tmp_path):
        """Returns bare binary name as last resort when not found anywhere."""
        repo_dir = tmp_path / "offline-web-search"
        repo_dir.mkdir()

        with patch("offline_search.config._detect_base_dir", return_value=repo_dir), \
             patch("offline_search.config.shutil.which", return_value=None):
            result = _detect_kiwix_exe()

        bin_name = "kiwix-serve.exe" if sys.platform == "win32" else "kiwix-serve"
        assert result == bin_name
