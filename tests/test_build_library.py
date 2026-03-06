"""End-to-end tests for scripts/build_library.sh and scripts/build_library.ps1.

Strategy
--------
- A stub ``kiwix-manage`` (a tiny shell script that just exits 0) is placed
  in a temp ``bin/`` directory that is prepended to PATH.  This lets us run
  the real script end-to-end without needing a real Kiwix binary or real ZIM
  files.
- Empty ``*.zim`` files are sufficient because the stub never reads them.
- The bash script tests are skipped on Windows.
- The PowerShell script tests use ``pwsh`` (PowerShell Core), which is
  pre-installed on GitHub Actions ``ubuntu-latest``, so both script types are
  exercised in CI on the same runner.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_SH = REPO_ROOT / "scripts" / "build_library.sh"
SCRIPT_PS1 = REPO_ROOT / "scripts" / "build_library.ps1"

# Use only pwsh (PowerShell Core).
# Windows PowerShell 5.1 ('powershell') is excluded: it can't execute the Unix
# kiwix-manage stub (a shebang script with no extension).  pwsh is pre-installed
# on GitHub Actions ubuntu-latest so the PS tests always run in CI.
PWSH = shutil.which("pwsh")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def zim_dir(tmp_path: Path) -> Path:
    """Temp directory with two dummy *.zim files."""
    d = tmp_path / "zims"
    d.mkdir()
    (d / "python-docs.zim").touch()
    (d / "stackoverflow.zim").touch()
    return d


@pytest.fixture()
def mock_kiwix_env(tmp_path: Path) -> dict:
    """Environment with a no-op kiwix-manage stub prepended to PATH.

    The stub is a plain shell script that accepts any arguments and exits 0,
    mimicking a successful ``kiwix-manage library.xml add <zim>`` call.
    On Linux, pwsh invokes it as a native process (shebang is honoured), so
    the same stub works for both the bash and PowerShell script tests.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if sys.platform == "win32":
        # .cmd is in PATHEXT so Get-Command finds it without an explicit extension.
        stub = bin_dir / "kiwix-manage.cmd"
        stub.write_text("@echo off\nexit /b 0\n")
    else:
        stub = bin_dir / "kiwix-manage"
        stub.write_text("#!/usr/bin/env bash\nexit 0\n")
        stub.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["KIWIX_MANAGE"] = str(stub)
    return env


# ---------------------------------------------------------------------------
# build_library.sh
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="bash script — skip on Windows")
class TestBuildLibrarySh:
    def _run(
        self,
        *args: str,
        env: dict | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT_SH), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd) if cwd else None,
            timeout=15,
        )

    def test_no_args_exits_1(self, tmp_path: Path) -> None:
        r = self._run(cwd=tmp_path)
        assert r.returncode == 1
        assert "Usage:" in r.stderr

    def test_missing_dir_exits_1(self, tmp_path: Path) -> None:
        r = self._run(str(tmp_path / "nonexistent"), cwd=tmp_path)
        assert r.returncode == 1
        assert "not found" in r.stderr

    def test_empty_dir_exits_1(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        r = self._run(str(empty), cwd=tmp_path)
        assert r.returncode == 1
        assert "No .zim files" in r.stderr

    def test_missing_kiwix_manage_exits_1(self, tmp_path: Path, zim_dir: Path) -> None:
        # Point KIWIX_MANAGE at a nonexistent path to bypass REPO_ROOT discovery.
        env = os.environ.copy()
        env["KIWIX_MANAGE"] = str(tmp_path / "no-such-kiwix-manage")
        r = self._run(str(zim_dir), cwd=tmp_path, env=env)
        assert r.returncode == 1
        assert "not found" in r.stderr

    def test_happy_path(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        library = tmp_path / "library.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "2 ZIM file(s)" in r.stdout
        assert "python-docs.zim" in r.stdout
        assert "stackoverflow.zim" in r.stdout
        assert "[OK]" in r.stdout

    def test_custom_library_path_reported(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        library = tmp_path / "my_custom_lib.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "my_custom_lib.xml" in r.stdout

    def test_each_zim_passed_to_kiwix_manage(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        """Both ZIM basenames must appear in the progress output."""
        library = tmp_path / "library.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "python-docs.zim" in r.stdout
        assert "stackoverflow.zim" in r.stdout


# ---------------------------------------------------------------------------
# build_library.ps1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(PWSH is None, reason="pwsh not available")
class TestBuildLibraryPs1:
    def _run(
        self,
        *args: str,
        env: dict | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NonInteractive", "-File", str(SCRIPT_PS1), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd) if cwd else None,
            timeout=30,
        )

    def test_missing_dir_exits_nonzero(self, tmp_path: Path) -> None:
        r = self._run(str(tmp_path / "nonexistent"), cwd=tmp_path)
        assert r.returncode != 0

    def test_empty_dir_exits_nonzero(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        r = self._run(str(empty), cwd=tmp_path)
        assert r.returncode != 0

    def test_missing_kiwix_manage_exits_nonzero(
        self, tmp_path: Path, zim_dir: Path
    ) -> None:
        env = os.environ.copy()
        # Point KIWIX_MANAGE at a nonexistent path to bypass REPO_ROOT discovery.
        env["KIWIX_MANAGE"] = str(tmp_path / "no-such-kiwix-manage")
        r = self._run(str(zim_dir), cwd=tmp_path, env=env)
        assert r.returncode != 0

    def test_happy_path(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        library = tmp_path / "library.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "2 ZIM file(s)" in r.stdout
        assert "python-docs.zim" in r.stdout
        assert "stackoverflow.zim" in r.stdout
        assert "[OK]" in r.stdout

    def test_custom_library_path_reported(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        library = tmp_path / "my_custom_lib.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "my_custom_lib.xml" in r.stdout

    def test_each_zim_passed_to_kiwix_manage(
        self, tmp_path: Path, zim_dir: Path, mock_kiwix_env: dict
    ) -> None:
        """Both ZIM basenames must appear in the progress output."""
        library = tmp_path / "library.xml"
        r = self._run(str(zim_dir), str(library), env=mock_kiwix_env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "python-docs.zim" in r.stdout
        assert "stackoverflow.zim" in r.stdout
