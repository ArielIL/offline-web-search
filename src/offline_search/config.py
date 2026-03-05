"""Centralised configuration — all paths, ports, and constants in one place.

Values are loaded from environment variables, a ``.env`` file, or fall back
to sensible defaults.  Every other module imports from here instead of
hard-coding its own constants.

Mode detection
--------------
The ``mode`` field controls how the MCP server operates:

* ``"local"`` (default) — searches the local SQLite FTS5 index and manages a
  local kiwix-serve process.
* ``"remote"`` — proxies search and page-fetch requests to a remote HTTP API
  + Kiwix server over the network.

When ``mode`` is left blank the system **auto-detects**: if ``remote_host`` is
set to anything other than ``127.0.0.1`` / ``localhost``, mode is ``"remote"``;
otherwise ``"local"``.
"""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

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


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", ""}


class Settings(BaseSettings):
    """Application settings with env-var / ``.env`` overrides.

    Set ``OFFLINE_SEARCH_MODE=remote`` (or just ``OFFLINE_SEARCH_REMOTE_HOST``
    to a non-localhost value) to switch to remote/distributed mode.
    """

    model_config = SettingsConfigDict(
        env_prefix="OFFLINE_SEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Mode (auto-detected if blank) ---
    mode: str = ""  # "local" or "remote"; blank = auto-detect

    # --- Paths ---
    base_dir: Path = _detect_base_dir()
    db_path: Path = _detect_base_dir() / "data" / "offline_index.sqlite"
    library_xml: str = _detect_library_xml()

    # --- Kiwix ---
    kiwix_exe: str = _detect_kiwix_exe()
    kiwix_port: int = 8081

    # --- Search API server ---
    server_host: str = "0.0.0.0"
    server_port: int = 8082

    # --- Remote mode ---
    remote_host: str = "127.0.0.1"
    remote_search_port: int = 8082
    remote_kiwix_port: int = 8081

    # --- Search tuning ---
    search_default_limit: int = 10
    search_overfetch_factor: int = 5
    snippet_tokens: int = 16

    def model_post_init(self, __context: object) -> None:
        # Auto-detect mode when not explicitly set
        if not self.mode:
            if self.remote_host in _LOCAL_HOSTS:
                self.mode = "local"
            else:
                self.mode = "remote"

    # Convenience helpers -------------------------------------------------------

    @property
    def is_local(self) -> bool:
        """True when running in local / all-in-one mode."""
        return self.mode == "local"

    @property
    def is_remote(self) -> bool:
        """True when running as a thin proxy to a remote server."""
        return self.mode == "remote"

    @property
    def kiwix_url(self) -> str:
        """Base URL of the Kiwix server (local or remote)."""
        if self.is_remote:
            return f"http://{self.remote_host}:{self.remote_kiwix_port}"
        return f"http://127.0.0.1:{self.kiwix_port}"

    @property
    def search_api_url(self) -> str:
        """Base URL of the HTTP search API (only meaningful in remote mode)."""
        return f"http://{self.remote_host}:{self.remote_search_port}"

    # Legacy aliases for backwards compatibility --------------------------------

    @property
    def remote_search_url(self) -> str:
        return self.search_api_url

    @property
    def remote_kiwix_url(self) -> str:
        return f"http://{self.remote_host}:{self.remote_kiwix_port}"


# Module-level singleton — import ``settings`` everywhere.
settings = Settings()
