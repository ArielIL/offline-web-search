# Offline ZIM Search for MCP

This project provides a Model Context Protocol (MCP) server that allows AI agents (like Claude) to search offline documentation hosted in ZIM archives. It supports complex full-text search across thousands of offline articles using a local SQLite index over Kiwix.

## Features

-   **Offline First**: Designed for air-gapped environments.
-   **Dual Search**: Combines instant full-text search (SQLite FTS5) with Kiwix's native server.
-   **Distributed Ready**: Run the heavy ZIM server on a centralized machine and connect lightweight clients via MCP.
-   **Smart Ranking**: Enhanced ranking algorithms to prioritize English documentation and core API references.
-   **Extensible**: Inject external local content (e.g., Confluence, Artifactory) into the same search index.

## Quick Start

### 1. Installation
**Requirements:** Python 3.11+
```bash
pip install -r requirements.txt
```

### 2. Build Index
```bash
python build_local_index.py --library path/to/library.xml --output data/offline_index.sqlite
```

### 3. Run
Local mode (all-in-one):
```bash
python offline_search_adapter.py
```

For detailed deployment instructions, including distributed setup, please refer to [DEPLOYMENT.md](DEPLOYMENT.md).

## Project Structure

-   `offline_search_adapter.py`: Main MCP server for local deployments.
-   `build_local_index.py`: Crawler that indexes ZIM files into SQLite.
-   `search_server.py`: Lightweight API for the distributed server component.
-   `client_mcp_adapter.py`: Thin MCP client for distributed setups.
-   `add_external_source.py`: Utility to index external/intranet websites.
-   `test_search.py`: Diagnostic script to verify search results.

## Requirements
-   Python 3.10+
-   `kiwix-tools` (downloaded separately)
-   ZIM archives (e.g., from [download.kiwix.org](https://download.kiwix.org/zim/))
