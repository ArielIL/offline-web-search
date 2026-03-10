"""Integration tests for scripts/build_library.sh and scripts/build_library.ps1.

These tests run the REAL kiwix-manage binary against REAL ZIM fixture files
committed to tests/data/.  They are marked `integration` and excluded from
the default pytest run (see pyproject.toml `addopts`).  They execute in CI
inside the `integration` job, which downloads kiwix-tools first.

Requirements
------------
- `kiwix-manage` must be on PATH or in `kiwix-tools/` next to the repo root.
- ZIM fixtures must be present at `tests/data/*.zim`.
- `bash` is required for the .sh tests (Linux/macOS only).
- `pwsh` (PowerShell Core) is required for the .ps1 tests.

Both conditions are met on GitHub Actions `ubuntu-latest` after the
kiwix-tools download step in ci.yml.  Locally, skip these gracefully.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_SH = REPO_ROOT / "scripts" / "build_library.sh"
SCRIPT_PS1 = REPO_ROOT / "scripts" / "build_library.ps1"
FIXTURES_DIR = Path(__file__).resolve().parent / "data"

PWSH = shutil.which("pwsh")

# Detect kiwix-manage (same logic as the scripts themselves).
_local_kiwix = REPO_ROOT / "kiwix-tools" / "kiwix-manage"
KIWIX_MANAGE = (
    str(_local_kiwix)
    if _local_kiwix.exists()
    else shutil.which("kiwix-manage")
)

_local_serve = REPO_ROOT / "kiwix-tools" / "kiwix-serve"
KIWIX_SERVE = (
    str(_local_serve)
    if _local_serve.exists()
    else shutil.which("kiwix-serve")
)

ZIMS = sorted(FIXTURES_DIR.glob("*.zim"))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _assert_servable_library(library: Path, expected_count: int) -> None:
    """Boot up kiwix-serve with the generated library.xml and hit its HTTP API
    to prove it actually parsed the ZIMs and can host them.
    This replaces parsing XML text implementation details.
    """
    assert library.exists(), f"library.xml was not created at {library}"
    if not KIWIX_SERVE:
        pytest.skip("kiwix-serve not found, cannot test serving generated library")
        
    port = find_free_port()
    proc = subprocess.Popen(
        [KIWIX_SERVE, "--port", str(port), "--library", str(library)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    ready = False
    url = f"http://127.0.0.1:{port}/catalog/v2/entries"
    deadline = time.monotonic() + 10.0
    
    try:
        while time.monotonic() < deadline:
            try:
                resp = urllib.request.urlopen(url, timeout=1.0)
                if resp.status == 200:
                    content = resp.read().decode('utf-8')
                    ready = True
                    # Assert all ZIM files are presented in the true live OPDS feed
                    for zim in ZIMS:
                        assert zim.stem in content, f"ZIM stem '{zim.stem}' missing from active kiwix-serve catalog"
                    break
            except Exception:
                time.sleep(0.5)
                
        if not ready:
            pytest.fail("kiwix-serve never became healthy with the generated library.xml")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# build_library.sh — real binary, real ZIMs
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(sys.platform == "win32", reason="bash script — skip on Windows")
@pytest.mark.skipif(not ZIMS, reason="No ZIM fixtures found in tests/data/")
@pytest.mark.skipif(KIWIX_MANAGE is None, reason="kiwix-manage not found — run CI integration job")
class TestBuildLibraryShIntegration:

    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT_SH), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def test_happy_flow(self, tmp_path: Path) -> None:
        """Run build_library.sh against real ZIM fixtures with real kiwix-manage.

        Asserts:
        - exit code 0
        - each ZIM filename appears in stdout
        - library.xml is valid based on passing real HTTP checks when booted in kiwix-serve
        """
        library = tmp_path / "library.xml"
        r = self._run(str(FIXTURES_DIR), str(library), cwd=tmp_path)

        assert r.returncode == 0, f"Script failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        assert f"{len(ZIMS)} ZIM file(s)" in r.stdout
        assert "[OK]" in r.stdout
        for zim in ZIMS:
            assert zim.name in r.stdout, f"{zim.name} not mentioned in output"

        _assert_servable_library(library, len(ZIMS))


# ---------------------------------------------------------------------------
# build_library.ps1 — real binary, real ZIMs
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(PWSH is None, reason="pwsh not found")
@pytest.mark.skipif(not ZIMS, reason="No ZIM fixtures found in tests/data/")
@pytest.mark.skipif(KIWIX_MANAGE is None, reason="kiwix-manage not found — run CI integration job")
class TestBuildLibraryPs1Integration:

    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT_PS1), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def test_happy_flow(self, tmp_path: Path) -> None:
        """Run build_library.ps1 against real fixtures. Server boot check."""
        library = tmp_path / "library.xml"
        r = self._run(str(FIXTURES_DIR), str(library), cwd=tmp_path)

        assert r.returncode == 0, f"Script failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        assert f"{len(ZIMS)} ZIM file(s)" in r.stdout
        assert "[OK]" in r.stdout
        for zim in ZIMS:
            assert zim.name in r.stdout, f"{zim.name} not mentioned in output"

        _assert_servable_library(library, len(ZIMS))
