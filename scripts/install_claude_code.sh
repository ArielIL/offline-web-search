#!/usr/bin/env bash
# Registers the Offline Search MCP server as a tool in Claude Code.
#
# Usage:
#   ./scripts/install_claude_code.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Offline Search — Claude Code Skill Installer ==="
echo ""

# Check that claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "[ERROR] 'claude' CLI not found in PATH."
    echo "Install it first: https://docs.anthropic.com/claude-code"
    exit 1
fi

# Register the MCP server
echo "Registering offline-search MCP server with Claude Code..."
claude mcp add offline-search -- python -m offline_search.mcp

echo ""
echo "[OK] 'offline-search' skill added to Claude Code!"
echo ""
echo "Tools now available in Claude Code:"
echo "  - google_search(query)  : Search offline documentation"
echo "  - visit_page(url)       : Read full page content"
echo ""
echo "Start Claude Code in any directory and try asking it to search something."
