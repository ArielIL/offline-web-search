# CLAUDE.md — Project Instructions for Claude Code

> This file tells Claude Code how to work within this repository.  
> It is **automatically loaded** as project memory when using Claude Code.

## Project Overview

**Offline Search** is a drop-in replacement for web search tools (`google_search`, `visit_page`) designed for **air-gapped / offline environments**. It indexes ZIM archives (from Kiwix) into a local SQLite FTS5 database, then exposes the search through:

1. **MCP tools** — so Claude Desktop / Claude Code can call `google_search` and `visit_page` natively.
2. **HTTP API** — a FastAPI server for distributed deployments.

## Architecture

```
src/offline_search/
├── config.py          # Centralised settings (pydantic-settings, .env support)
├── search_engine.py   # Core FTS5 search: tokeniser, BM25, ranking, filtering
├── kiwix.py           # Kiwix-serve lifecycle + page fetching
├── indexer.py         # ZIM → SQLite indexer (CLI: offline-search-index)
├── mcp.py             # Unified MCP server — auto-detects local/remote mode
└── server.py          # FastAPI HTTP search API + content management

.claude/agents/
└── offline-search-agent.md  # Haiku sub-agent for token-efficient search

.claude/skills/offline-search/
├── SKILL.md           # Claude Code skill — routes through offline-search-agent
└── scripts/           # search.py + fetch_page.py CLI wrappers
```

## Key Commands

```bash
# Install the project (editable mode for development)
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=offline_search --cov-report=term-missing

# Build the search index from ZIM files
offline-search-index --library path/to/library.xml --output data/offline_index.sqlite

# Start the MCP server (auto-detects local/remote mode)
offline-search-mcp

# Start the HTTP API server (for distributed mode server-side)
offline-search-server

# Start MCP in explicit remote mode
OFFLINE_SEARCH_REMOTE_HOST=192.168.1.50 offline-search-mcp
```

## MCP Tools Provided

| Tool | Description |
|------|-------------|
| `google_search(query)` | Full-text search across the offline library. Named to match the built-in web search tool. |
| `visit_page(url)` | Fetch full page content from a search result URL. Returns clean Markdown. |

## Configuration

All settings can be overridden via environment variables prefixed with `OFFLINE_SEARCH_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OFFLINE_SEARCH_MODE` | auto-detect | `local` or `remote` (auto-detects from `REMOTE_HOST`) |
| `OFFLINE_SEARCH_DB_PATH` | `data/offline_index.sqlite` | Path to the FTS5 index |
| `OFFLINE_SEARCH_KIWIX_PORT` | `8081` | Port for kiwix-serve |
| `OFFLINE_SEARCH_SERVER_PORT` | `8082` | Port for the HTTP API |
| `OFFLINE_SEARCH_REMOTE_HOST` | `127.0.0.1` | Server IP for remote mode |
| `OFFLINE_SEARCH_COMPACT_FORMAT` | `false` | Use compact output for MCP tools (reduces tokens) |

Or place them in a `.env` file at the project root.

## Coding Conventions

- Python 3.11+ with type hints everywhere.
- Use `logging` (never bare `print()` in library code).
- All shared search logic lives in `search_engine.py` — never duplicate it.
- Tests use `pytest` with fixtures from `tests/conftest.py`.
- Format with `ruff`.

## Token Optimization

Two mechanisms reduce context window usage:

1. **Haiku sub-agent (SKILL path)**: The `/offline-search` skill routes through `.claude/agents/offline-search-agent.md`, which runs on Haiku. Raw search results and page content are processed by Haiku, and only a condensed summary is returned to the main model. This mirrors Claude Code's built-in WebFetch pattern.

2. **Compact format (MCP path)**: Set `OFFLINE_SEARCH_COMPACT_FORMAT=true` to switch MCP tool output to a minimal format — `{title, url}` JSON array + truncated one-line snippets. This reduces token usage when the MCP tools are called directly.

## Important Notes

- The tool is named `google_search` on purpose — this makes Claude call it naturally as a drop-in for the real web search tool.
- The `visit_page` tool is the companion that lets Claude read full article content.
- In the `.claude/settings.json`, `WebFetch` and `WebSearch` are **denied** to force Claude to use the offline tools instead.
