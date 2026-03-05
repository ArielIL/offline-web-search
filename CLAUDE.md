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
├── mcp_local.py       # MCP server for local/all-in-one mode
├── mcp_client.py      # MCP client adapter for remote/distributed mode
└── server.py          # FastAPI HTTP search API + content management
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

# Start the MCP server (local mode — used by Claude Desktop & Claude Code)
offline-search-mcp

# Start the HTTP API server (distributed mode)
offline-search-server

# Start the MCP client adapter (connects to remote HTTP API)
offline-search-client
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
| `OFFLINE_SEARCH_DB_PATH` | `data/offline_index.sqlite` | Path to the FTS5 index |
| `OFFLINE_SEARCH_KIWIX_PORT` | `8081` | Port for kiwix-serve |
| `OFFLINE_SEARCH_SERVER_PORT` | `8082` | Port for the HTTP API |
| `OFFLINE_SEARCH_REMOTE_HOST` | `127.0.0.1` | Server IP for distributed mode |

Or place them in a `.env` file at the project root.

## Coding Conventions

- Python 3.11+ with type hints everywhere.
- Use `logging` (never bare `print()` in library code).
- All shared search logic lives in `search_engine.py` — never duplicate it.
- Tests use `pytest` with fixtures from `tests/conftest.py`.
- Format with `ruff`.

## Important Notes

- The tool is named `google_search` on purpose — this makes Claude call it naturally as a drop-in for the real web search tool.
- The `visit_page` tool is the companion that lets Claude read full article content.
- In the `.claude/settings.json`, `WebFetch` and `WebSearch` are **denied** to force Claude to use the offline tools instead.
