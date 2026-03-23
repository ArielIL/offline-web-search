"""Structural tests for the offline-search agent and skill configuration."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse simple YAML frontmatter into a flat dict (no external deps)."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name} must start with YAML frontmatter"
    _, fm_block, _ = text.split("---", 2)
    result: dict[str, str] = {}
    for line in fm_block.strip().splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.+)$", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


class TestAgentDefinition:
    agent_path = REPO_ROOT / ".claude" / "agents" / "offline-search-agent.md"

    def test_agent_file_exists(self):
        assert self.agent_path.exists(), "offline-search-agent.md not found"

    def test_model_is_haiku(self):
        fm = _parse_frontmatter(self.agent_path)
        assert fm.get("model") == "haiku", "Agent model must be 'haiku'"

    def test_tools_include_bash_python(self):
        fm = _parse_frontmatter(self.agent_path)
        tools = fm.get("tools", "")
        assert "Bash" in tools and "python" in tools, (
            "Agent tools must include Bash(python *)"
        )


class TestSkillDefinition:
    skill_path = REPO_ROOT / "skills" / "offline-search" / "SKILL.md"

    def test_skill_file_exists(self):
        assert self.skill_path.exists(), "SKILL.md not found"

    def test_agent_field_present(self):
        fm = _parse_frontmatter(self.skill_path)
        assert fm.get("agent") == "offline-search-agent", (
            "SKILL.md must route to offline-search-agent"
        )

    def test_name_is_offline_search(self):
        fm = _parse_frontmatter(self.skill_path)
        assert fm.get("name") == "offline-search"
