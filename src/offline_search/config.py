"""Centralised configuration — all paths, ports, and constants in one place.

Values are loaded from environment variables, a ``.env`` file, or fall back
to sensible defaults.  Every other module imports from here instead of
hard-coding its own constants.
"""

from __future__ import annotations

import platform
import shutil
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_base_dir() -> Path:
    """Return the project root (directory that contains ``src/`` or ``data/``)."""
    here = Path(__file__).resolve().parent          # src/offline_search/
    project = here.parent.parent                     # repo root
    if (project / "data").is_dir() or (project / "pyproject.toml").is_file():
        return project
    return Path.cwd()


def _detect_kiwix_exe() -> str:
    """Best-effort auto-detection of the kiwix-serve binary."""
    is_windows = platform.system() == "Windows"
    bin_name = "kiwix-serve.exe" if is_windows else "kiwix-serve"

    # 1. Bundled kiwix-tools next to the project
    base = _detect_base_dir()
    local = base / "kiwix-tools" / bin_name
    if local.exists():
        return str(local)

    # 2. System PATH
    found = shutil.which("kiwix-serve")
    if found:
        return found

    # 3. Fallback — hope it's in PATH at runtime
    return bin_name


def _detect_library_xml() -> str:
    base = _detect_base_dir()
    if (base / "library.xml").exists():
        return str(base / "library.xml")
    if (base / "library_test.xml").exists():
        return str(base / "library_test.xml")
    return str(base / "library.xml")


class Settings(BaseSettings):
    """Application settings with env-var / ``.env`` overrides."""

    model_config = SettingsConfigDict(
        env_prefix="OFFLINE_SEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths ---
    base_dir: Path = _detect_base_dir()
    db_path: Path = _detect_base_dir() / "data" / "offline_index.sqlite"
    library_xml: str = _detect_library_xml()

    # --- Kiwix ---
    kiwix_exe: str = _detect_kiwix_exe()
    kiwix_port: int = 8081
    kiwix_url: str = ""  # computed in model_post_init

    # --- Search API server ---
    server_host: str = "0.0.0.0"
    server_port: int = 8082

    # --- Remote mode (client adapter) ---
    remote_host: str = "127.0.0.1"
    remote_search_port: int = 8082
    remote_kiwix_port: int = 8081

    # --- Search tuning ---
    search_default_limit: int = 10
    search_overfetch_factor: int = 5
    snippet_tokens: int = 16

    def model_post_init(self, __context: object) -> None:
        if not self.kiwix_url:
            self.kiwix_url = f"http://127.0.0.1:{self.kiwix_port}"

    # Convenience helpers -------------------------------------------------------

    @property
    def remote_search_url(self) -> str:
        return f"http://{self.remote_host}:{self.remote_search_port}"

    @property
    def remote_kiwix_url(self) -> str:
        return f"http://{self.remote_host}:{self.remote_kiwix_port}"


# Module-level singleton — import ``settings`` everywhere.
settings = Settings()
