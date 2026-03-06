#!/usr/bin/env bash
# Installs Offline Search for Claude Code — skill (recommended) or MCP server.
#
# Usage:
#   ./scripts/install_claude_code.sh          # interactive — asks which mode
#   ./scripts/install_claude_code.sh skill    # install skill only
#   ./scripts/install_claude_code.sh mcp      # install MCP server only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SKILL_SRC="$REPO_ROOT/skills/offline-search"
SKILL_DST="$HOME/.claude/skills/offline-search"

echo "=== Offline Search — Claude Code Installer ==="
echo ""

MODE="${1:-}"

if [ -z "$MODE" ]; then
    echo "Choose installation mode:"
    echo ""
    echo "  1) skill  — Claude Code skill (recommended)"
    echo "     Claude runs search via Bash scripts. No background server."
    echo ""
    echo "  2) mcp    — MCP server"
    echo "     Registers an MCP server that exposes google_search + visit_page tools."
    echo ""
    read -rp "Enter 1 or 2 [1]: " choice
    case "${choice:-1}" in
        1|skill)  MODE="skill" ;;
        2|mcp)    MODE="mcp" ;;
        *)        echo "Invalid choice."; exit 1 ;;
    esac
fi

case "$MODE" in
    skill)
        echo "Installing Claude Code skill..."
        mkdir -p "$SKILL_DST"
        cp -r "$SKILL_SRC/"* "$SKILL_DST/"
        echo ""
        echo "[OK] Skill installed to $SKILL_DST"
        echo ""
        echo "Claude Code now has:"
        echo "  /offline-search <query>  — search offline docs"
        echo "  Auto-triggers when Claude needs to look something up"
        ;;
    mcp)
        if ! command -v claude &> /dev/null; then
            echo "[ERROR] 'claude' CLI not found in PATH."
            echo "Install it first: https://docs.anthropic.com/claude-code"
            exit 1
        fi
        echo "Registering offline-search MCP server with Claude Code..."
        claude mcp add offline-search -- python -m offline_search.mcp
        echo ""
        echo "[OK] MCP server registered."
        echo ""
        echo "Tools available:"
        echo "  google_search(query)  — search offline documentation"
        echo "  visit_page(url)       — read full page content"
        ;;
    *)
        echo "Usage: $0 [skill|mcp]"
        exit 1
        ;;
esac

echo ""
echo "Start Claude Code in any directory and try searching for something."
