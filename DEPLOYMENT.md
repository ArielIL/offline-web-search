# Offline Search Deployment Guide

This repository supports three deployment modes:

1.  **Claude Code Skill** — Fastest setup. Claude Code CLI gets `google_search` + `visit_page` tools.
2.  **Claude Desktop (Local MCP)** — All-in-one mode for the Claude Desktop app.
3.  **Distributed (Remote)** — Heavy ZIM files on a server; Claude connects over the network.

---

## 🟥 Phase 1: Installation (Required for ALL modes)

### 1. Install the Package

```bash
pip install -e ".[dev]"
```

### 2. Build the SQLite Index

Run the indexer to extract text from your ZIM library:

```bash
offline-search-index --library path/to/library.xml --output data/offline_index.sqlite
```

*Tip: Add `--limit 50` for a quick 1-minute test run.*

---

## 🟦 Phase 2: Choose Your Deployment Mode

### Option A: Claude Code CLI Skill ⭐ (Recommended)

*Use this if:* You use the **Claude Code** terminal-based tool.

**1. Quick Install**

```bash
# Linux / macOS
./scripts/install_claude_code.sh

# Windows (PowerShell)
.\scripts\install_claude_code.ps1
```

**2. Manual Install**

```bash
claude mcp add offline-search -- python -m offline_search.mcp
```

**3. What you get**

After registration, Claude Code has two new tools everywhere:
- `google_search(query)` — full-text search across offline docs
- `visit_page(url)` — read the full content of any result

---

### Option B: Claude Desktop (Local / All-in-One)

*Use this if:* Claude Desktop and ZIM files are on the **same** computer.

**1. Configure Claude Desktop**

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "offline-search": {
      "command": "python",
      "args": ["-m", "offline_search.mcp"]
    }
  }
}
```

**2. How it works**
- Claude starts the MCP server automatically.
- The server starts `kiwix-serve` in the background (port 8081).
- Search queries go directly to the local SQLite index.

---

### Option C: Distributed (Remote Server + Client)

*Use this if:* ZIM files are on a **dedicated server**, and Claude is on your **laptop**.

#### Server Side

**1. Start Kiwix (Document Server)**

```bash
kiwix-serve --port 8081 --library path/to/library.xml
```

**2. Start the Search API**

```bash
offline-search-server
# Starts FastAPI on port 8082 with auto-docs at /docs
```

#### Client Side

**1. Configure Connection**

Set the server IP via environment variable or `.env` file:

```bash
export OFFLINE_SEARCH_REMOTE_HOST=192.168.1.50
```

Or create a `.env` file:

```env
OFFLINE_SEARCH_REMOTE_HOST=192.168.1.50
OFFLINE_SEARCH_REMOTE_SEARCH_PORT=8082
OFFLINE_SEARCH_REMOTE_KIWIX_PORT=8081
```

**2. Register with Claude**

For Claude Code:
```bash
OFFLINE_SEARCH_REMOTE_HOST=192.168.1.50 claude mcp add offline-search -- python -m offline_search.mcp
```

Or set the env var permanently and register:
```bash
claude mcp add offline-search -- python -m offline_search.mcp
```

For Claude Desktop, add to config:
```json
{
  "mcpServers": {
    "offline-search": {
      "command": "python",
      "args": ["-m", "offline_search.mcp"]
    }
  }
}
```

---

## 🟩 Troubleshooting & Health Checks

### Health Check (Server API)

```bash
curl http://127.0.0.1:8082/health
```

Returns index stats and server status. If using the distributed mode, replace `127.0.0.1` with your server IP.

### Interactive API Docs

When running the server, open `http://127.0.0.1:8082/docs` for the Swagger UI — lets you test search, index pages, and manage content visually.

### Quick Search Test

```bash
curl "http://127.0.0.1:8082/search?q=python+asyncio"
```

### Firewall Notes

For distributed mode, ensure ports **8081** (Kiwix) and **8082** (Search API) are open on the server.

### Packaging for Air-Gap Transfer

If moving to a fully disconnected machine, ensure you package:

1. The full `offline-search` project (or the built wheel)
2. `data/offline_index.sqlite` (the pre-built index)
3. The Kiwix Tools binary (`kiwix-serve`)
4. Your `library.xml` file
5. All `.zim` files referenced in the library
6. Python wheel dependencies (use `pip download -r requirements.txt`)
