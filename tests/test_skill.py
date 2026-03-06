"""Tests for the Claude Code skill CLI scripts (search.py and fetch_page.py).

Strategy
--------
- **Argument validation** tests run the scripts as subprocesses so we exercise
  the full ``if __name__`` path including ``sys.exit(1)``.
- **Functional** tests import ``main()`` directly and mock the
  ``offline_search`` dependencies so we never need a live kiwix-serve,
  network access, or a real ZIM database.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Locate the skill scripts relative to the repo root.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "offline-search" / "scripts"
SEARCH_SCRIPT = SCRIPTS_DIR / "search.py"
FETCH_SCRIPT = SCRIPTS_DIR / "fetch_page.py"


def _import_script(script_path: Path, module_name: str) -> ModuleType:
    """Import a script file as a module so we can call ``main()``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a skill script as a subprocess and capture output."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# search.py — argument validation (subprocess, exercises sys.exit)
# ---------------------------------------------------------------------------

class TestSearchArgValidation:
    def test_no_args_shows_usage(self):
        result = _run_script(SEARCH_SCRIPT)
        assert result.returncode == 1
        assert "Usage:" in result.stdout

    def test_empty_arg_shows_usage(self):
        result = _run_script(SEARCH_SCRIPT, "   ")
        assert result.returncode == 1
        assert "Usage:" in result.stdout


# ---------------------------------------------------------------------------
# search.py — functional tests (import main, mock dependencies)
# ---------------------------------------------------------------------------

class TestSearchMain:
    """Call ``main()`` from search.py with mocked offline_search internals."""

    @pytest.fixture(autouse=True)
    def _load_search_module(self):
        """Import the search script before each test."""
        self.mod = _import_script(SEARCH_SCRIPT, "skill_search")

    # -- helpers for building mock SearchResult objects ----------------------

    @staticmethod
    def _make_result(title: str = "Python asyncio", snippet: str = "coroutines"):
        """Return a mock that behaves like ``SearchResult``."""
        r = MagicMock()
        r.format_for_llm.return_value = (
            f"Title: {title}\nURL: http://localhost:8081/content/x\nSnippet: {snippet}\n"
        )
        return r

    # -- tests --------------------------------------------------------------

    def test_fts5_results_printed(self, capsys, monkeypatch):
        """When the FTS5 search returns hits, they are printed to stdout."""
        monkeypatch.setattr(sys, "argv", ["search.py", "python", "asyncio"])

        mock_search = AsyncMock(return_value=[self._make_result()])
        mock_settings = MagicMock(kiwix_url="http://127.0.0.1:8081")

        with (
            patch.dict(sys.modules, {
                "offline_search": MagicMock(),
                "offline_search.config": MagicMock(settings=mock_settings),
                "offline_search.kiwix": MagicMock(),
                "offline_search.search_engine": MagicMock(search=mock_search),
            }),
        ):
            # Re-import so the patched modules take effect inside main()
            mod = _import_script(SEARCH_SCRIPT, "skill_search_fresh")
            mod.main()

        out = capsys.readouterr().out
        assert "Title: Python asyncio" in out
        mock_search.assert_awaited_once()

    def test_fallback_to_kiwix_html(self, capsys, monkeypatch):
        """If FTS5 returns nothing, search.py falls back to kiwix HTML search."""
        monkeypatch.setattr(sys, "argv", ["search.py", "react"])

        mock_search = AsyncMock(return_value=[])  # no FTS5 hits
        html_hits = [
            {"title": "React Hooks", "url": "http://localhost/react", "snippet": "hooks"},
        ]
        mock_html = AsyncMock(return_value=html_hits)
        mock_start = MagicMock()
        mock_settings = MagicMock(kiwix_url="http://127.0.0.1:8081")

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.config": MagicMock(settings=mock_settings),
            "offline_search.kiwix": MagicMock(
                search_kiwix_html=mock_html,
                start_kiwix_server=mock_start,
            ),
            "offline_search.search_engine": MagicMock(search=mock_search),
        }):
            mod = _import_script(SEARCH_SCRIPT, "skill_search_fb")
            mod.main()

        out = capsys.readouterr().out
        assert "React Hooks" in out
        mock_start.assert_called_once()
        mock_html.assert_awaited_once()

    def test_no_results_message(self, capsys, monkeypatch):
        """When both FTS5 and kiwix HTML return nothing, prints a helpful message."""
        monkeypatch.setattr(sys, "argv", ["search.py", "xyzzy_nonexistent"])

        mock_search = AsyncMock(return_value=[])
        mock_html = AsyncMock(return_value=[])
        mock_start = MagicMock()
        mock_settings = MagicMock(kiwix_url="http://127.0.0.1:8081")

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.config": MagicMock(settings=mock_settings),
            "offline_search.kiwix": MagicMock(
                search_kiwix_html=mock_html,
                start_kiwix_server=mock_start,
            ),
            "offline_search.search_engine": MagicMock(search=mock_search),
        }):
            mod = _import_script(SEARCH_SCRIPT, "skill_search_none")
            mod.main()

        out = capsys.readouterr().out
        assert "No results found" in out

    def test_multiple_args_joined(self, monkeypatch):
        """Multiple CLI args are joined into a single query string."""
        monkeypatch.setattr(sys, "argv", ["search.py", "python", "asyncio", "gather"])

        captured_query: list[str] = []

        async def _capture(q: str):
            captured_query.append(q)
            return []

        mock_settings = MagicMock(kiwix_url="http://127.0.0.1:8081")

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.config": MagicMock(settings=mock_settings),
            "offline_search.kiwix": MagicMock(
                search_kiwix_html=AsyncMock(return_value=[]),
                start_kiwix_server=MagicMock(),
            ),
            "offline_search.search_engine": MagicMock(search=_capture),
        }):
            mod = _import_script(SEARCH_SCRIPT, "skill_search_join")
            mod.main()

        assert captured_query == ["python asyncio gather"]


# ---------------------------------------------------------------------------
# fetch_page.py — argument validation (subprocess, exercises sys.exit)
# ---------------------------------------------------------------------------

class TestFetchArgValidation:
    def test_no_args_shows_usage(self):
        result = _run_script(FETCH_SCRIPT)
        assert result.returncode == 1
        assert "Usage:" in result.stdout

    def test_empty_arg_shows_usage(self):
        result = _run_script(FETCH_SCRIPT, "   ")
        assert result.returncode == 1
        assert "Usage:" in result.stdout


# ---------------------------------------------------------------------------
# fetch_page.py — functional tests (import main, mock dependencies)
# ---------------------------------------------------------------------------

class TestFetchMain:
    """Call ``main()`` from fetch_page.py with mocked offline_search internals."""

    def test_successful_fetch(self, capsys, monkeypatch):
        """When fetch_page returns content, it's printed to stdout."""
        monkeypatch.setattr(sys, "argv", ["fetch_page.py", "http://localhost/page"])

        mock_fetch = AsyncMock(return_value="# Hello World\n\nSome content.")
        mock_start = MagicMock()

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.kiwix": MagicMock(
                fetch_page=mock_fetch,
                start_kiwix_server=mock_start,
            ),
        }):
            mod = _import_script(FETCH_SCRIPT, "skill_fetch_ok")
            mod.main()

        out = capsys.readouterr().out
        assert "# Hello World" in out
        assert "Some content." in out
        mock_start.assert_called_once()
        mock_fetch.assert_awaited_once_with("http://localhost/page")

    def test_empty_content(self, capsys, monkeypatch):
        """When fetch_page returns empty/None, prints the empty-content notice."""
        monkeypatch.setattr(sys, "argv", ["fetch_page.py", "http://localhost/empty"])

        mock_fetch = AsyncMock(return_value="")
        mock_start = MagicMock()

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.kiwix": MagicMock(
                fetch_page=mock_fetch,
                start_kiwix_server=mock_start,
            ),
        }):
            mod = _import_script(FETCH_SCRIPT, "skill_fetch_empty")
            mod.main()

        out = capsys.readouterr().out
        assert "Page returned empty content." in out

    def test_none_content(self, capsys, monkeypatch):
        """When fetch_page returns None, prints the empty-content notice."""
        monkeypatch.setattr(sys, "argv", ["fetch_page.py", "http://localhost/none"])

        mock_fetch = AsyncMock(return_value=None)
        mock_start = MagicMock()

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.kiwix": MagicMock(
                fetch_page=mock_fetch,
                start_kiwix_server=mock_start,
            ),
        }):
            mod = _import_script(FETCH_SCRIPT, "skill_fetch_none")
            mod.main()

        out = capsys.readouterr().out
        assert "Page returned empty content." in out

    def test_url_passed_correctly(self, monkeypatch):
        """The URL from sys.argv[1] is forwarded to fetch_page()."""
        target_url = "http://127.0.0.1:8081/content/devdocs/A/react/hooks"
        monkeypatch.setattr(sys, "argv", ["fetch_page.py", target_url])

        mock_fetch = AsyncMock(return_value="content")
        mock_start = MagicMock()

        with patch.dict(sys.modules, {
            "offline_search": MagicMock(),
            "offline_search.kiwix": MagicMock(
                fetch_page=mock_fetch,
                start_kiwix_server=mock_start,
            ),
        }):
            mod = _import_script(FETCH_SCRIPT, "skill_fetch_url")
            mod.main()

        mock_fetch.assert_awaited_once_with(target_url)


# ---------------------------------------------------------------------------
# SKILL.md structure
# ---------------------------------------------------------------------------

class TestSkillStructure:
    """Verify the skill directory has the expected layout and frontmatter."""

    SKILL_DIR = REPO_ROOT / "skills" / "offline-search"

    def test_skill_md_exists(self):
        assert (self.SKILL_DIR / "SKILL.md").is_file()

    def test_scripts_exist(self):
        assert (self.SKILL_DIR / "scripts" / "search.py").is_file()
        assert (self.SKILL_DIR / "scripts" / "fetch_page.py").is_file()

    def test_skill_md_has_frontmatter(self):
        text = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---"), "SKILL.md must begin with YAML frontmatter"
        # Must have a closing --- after the opening one
        parts = text.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing --- for frontmatter"

    def test_skill_md_frontmatter_fields(self):
        text = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        assert "name:" in frontmatter
        assert "description:" in frontmatter
        assert "allowed-tools:" in frontmatter

    def test_skill_md_references_scripts(self):
        """SKILL.md should tell Claude how to call the bundled scripts."""
        text = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert "search.py" in text
        assert "fetch_page.py" in text
        assert "CLAUDE_SKILL_DIR" in text
