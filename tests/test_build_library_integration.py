"""Integration tests for scripts/build_library.sh and scripts/build_library.ps1.

These tests run the REAL kiwix-manage binary against REAL ZIM fixture files
committed to tests/data/.  They are marked ``integration`` and excluded from
the default pytest run (see pyproject.toml ``addopts``).  They execute in CI
inside the ``integration`` job, which downloads kiwix-tools first.

Requirements
------------
- ``kiwix-manage`` must be on PATH or in ``kiwix-tools/`` next to the repo root.
- ZIM fixtures must be present at ``tests/data/*.zim``.
- ``bash`` is required for the .sh tests (Linux/macOS only).
- ``pwsh`` (PowerShell Core) is required for the .ps1 tests.

Both conditions are met on GitHub Actions ``ubuntu-latest`` after the
kiwix-tools download step in ci.yml.  Locally, skip these gracefully.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
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

ZIMS = sorted(FIXTURES_DIR.glob("*.zim"))


def _assert_valid_library(library: Path, expected_count: int) -> None:
    """Parse library.xml and assert it has the expected number of <book> entries
    with non-empty id and title attributes — proving kiwix-manage actually read
    the ZIM metadata, not just created placeholder entries.
    """
    assert library.exists(), f"library.xml was not created at {library}"
    tree = ET.parse(library)
    books = tree.findall("book")
    assert len(books) == expected_count, (
        f"Expected {expected_count} <book> entries, got {len(books)}"
    )
    for book in books:
        assert book.get("id"), "Every <book> must have a non-empty id attribute"
        assert book.get("title"), "Every <book> must have a non-empty title attribute"
        assert book.get("path"), "Every <book> must have a non-empty path attribute"


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
        - library.xml is valid XML with correct <book> count and metadata
        """
        library = tmp_path / "library.xml"
        r = self._run(str(FIXTURES_DIR), str(library), cwd=tmp_path)

        assert r.returncode == 0, f"Script failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        assert f"{len(ZIMS)} ZIM file(s)" in r.stdout
        assert "[OK]" in r.stdout
        for zim in ZIMS:
            assert zim.name in r.stdout, f"{zim.name} not mentioned in output"

        _assert_valid_library(library, len(ZIMS))


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
            [PWSH, "-NonInteractive", "-File", str(SCRIPT_PS1), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60,
        )

    def test_happy_flow(self, tmp_path: Path) -> None:
        """Run build_library.ps1 against real ZIM fixtures with real kiwix-manage.

        Asserts:
        - exit code 0
        - each ZIM filename appears in stdout
        - library.xml is valid XML with correct <book> count and metadata
        """
        library = tmp_path / "library.xml"
        r = self._run(str(FIXTURES_DIR), str(library), cwd=tmp_path)

        assert r.returncode == 0, f"Script failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
        assert f"{len(ZIMS)} ZIM file(s)" in r.stdout
        assert "[OK]" in r.stdout
        for zim in ZIMS:
            assert zim.name in r.stdout, f"{zim.name} not mentioned in output"

        _assert_valid_library(library, len(ZIMS))
