"""Tests for config module — defaults, env var overrides, mode detection, and helpers."""

from __future__ import annotations

from pathlib import Path

from offline_search.config import Settings


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
