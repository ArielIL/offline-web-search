<#
.SYNOPSIS
Registers the Offline Search MCP server as a tool in Claude Code.

.DESCRIPTION
Runs `claude mcp add` so that Claude Code can call `google_search` and
`visit_page` against your local ZIM documentation index.

.EXAMPLE
.\scripts\install_claude_code.ps1
#>

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

Write-Host "=== Offline Search — Claude Code Skill Installer ===" -ForegroundColor Cyan
Write-Host ""

# Check that claude CLI is available
if (-not (Get-Command "claude" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] 'claude' CLI not found in PATH." -ForegroundColor Red
    Write-Host "Install it first: https://docs.anthropic.com/claude-code" -ForegroundColor Yellow
    exit 1
}

# Register the MCP server
Write-Host "Registering offline-search MCP server with Claude Code..."
claude mcp add offline-search -- python -m offline_search.mcp_local

Write-Host ""
Write-Host "[OK] 'offline-search' skill added to Claude Code!" -ForegroundColor Green
Write-Host ""
Write-Host "Tools now available in Claude Code:" -ForegroundColor White
Write-Host "  - google_search(query)  : Search offline documentation" -ForegroundColor Gray
Write-Host "  - visit_page(url)       : Read full page content" -ForegroundColor Gray
Write-Host ""
Write-Host "Start Claude Code in any directory and try: /search python asyncio" -ForegroundColor Cyan
