"""Tests for config module — defaults, env var overrides, and helpers."""

from __future__ import annotations

from pathlib import Path

from offline_search.config import Settings


class TestSettings:
    def test_default_ports(self):
        s = Settings()
        assert s.kiwix_port == 8081
        assert s.server_port == 8082

    def test_kiwix_url_computed(self):
        s = Settings(kiwix_port=9999)
        assert s.kiwix_url == "http://127.0.0.1:9999"

    def test_remote_urls(self):
        s = Settings(remote_host="10.0.0.5", remote_search_port=5000, remote_kiwix_port=6000)
        assert s.remote_search_url == "http://10.0.0.5:5000"
        assert s.remote_kiwix_url == "http://10.0.0.5:6000"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OFFLINE_SEARCH_SERVER_PORT", "9999")
        s = Settings()
        assert s.server_port == 9999
