<#
.SYNOPSIS
Installs Offline Search for Claude Code — skill (recommended) or MCP server.

.DESCRIPTION
Offers two installation modes:
  - skill: Copies the skill to ~/.claude/skills/ (no background server needed)
  - mcp:   Registers an MCP server via `claude mcp add`

.EXAMPLE
.\scripts\install_claude_code.ps1           # interactive
.\scripts\install_claude_code.ps1 skill     # install skill only
.\scripts\install_claude_code.ps1 mcp       # install MCP server only
#>

param(
    [string]$Mode = ""
)

$ErrorActionPreference = "Stop"
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = Split-Path -Parent $scriptDir
$skillSrc   = Join-Path $repoRoot "skills\offline-search"
$skillDst   = Join-Path $env:USERPROFILE ".claude\skills\offline-search"

Write-Host "=== Offline Search — Claude Code Installer ===" -ForegroundColor Cyan
Write-Host ""

if (-not $Mode) {
    Write-Host "Choose installation mode:"
    Write-Host ""
    Write-Host "  1) skill  — Claude Code skill (recommended)"         -ForegroundColor White
    Write-Host "     Claude runs search via Bash scripts. No background server." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  2) mcp    — MCP server"                               -ForegroundColor White
    Write-Host "     Registers an MCP server that exposes google_search + visit_page tools." -ForegroundColor Gray
    Write-Host ""
    $choice = Read-Host "Enter 1 or 2 [1]"
    if (-not $choice) { $choice = "1" }
    switch ($choice) {
        { $_ -in "1", "skill" } { $Mode = "skill" }
        { $_ -in "2", "mcp" }   { $Mode = "mcp" }
        default { Write-Host "Invalid choice." -ForegroundColor Red; exit 1 }
    }
}

switch ($Mode) {
    "skill" {
        Write-Host "Installing Claude Code skill..."
        if (-not (Test-Path $skillDst)) { New-Item -ItemType Directory -Path $skillDst -Force | Out-Null }
        Copy-Item -Path "$skillSrc\*" -Destination $skillDst -Recurse -Force
        Write-Host ""
        Write-Host "[OK] Skill installed to $skillDst" -ForegroundColor Green
        Write-Host ""
        Write-Host "Claude Code now has:" -ForegroundColor White
        Write-Host "  /offline-search <query>  — search offline docs" -ForegroundColor Gray
        Write-Host "  Auto-triggers when Claude needs to look something up" -ForegroundColor Gray
    }
    "mcp" {
        if (-not (Get-Command "claude" -ErrorAction SilentlyContinue)) {
            Write-Host "[ERROR] 'claude' CLI not found in PATH." -ForegroundColor Red
            Write-Host "Install it first: https://docs.anthropic.com/claude-code" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "Registering offline-search MCP server with Claude Code..."
        claude mcp add offline-search -- python -m offline_search.mcp
        Write-Host ""
        Write-Host "[OK] MCP server registered." -ForegroundColor Green
        Write-Host ""
        Write-Host "Tools available:" -ForegroundColor White
        Write-Host "  google_search(query)  — search offline documentation" -ForegroundColor Gray
        Write-Host "  visit_page(url)       — read full page content" -ForegroundColor Gray
    }
    default {
        Write-Host "Usage: .\install_claude_code.ps1 [skill|mcp]" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""
Write-Host "Start Claude Code in any directory and try searching for something." -ForegroundColor Cyan
