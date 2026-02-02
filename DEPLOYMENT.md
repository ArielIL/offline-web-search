# Offline Search Deployment Guide

This repository supports two deployment modes for offline ZIM searching:
1.  **Local (All-in-One):** Everything runs on the same machine as Claude.
2.  **Remote (Distributed):** Heavy ZIM files stay on a central server; Claude connects via a lightweight adapter.

---

## 🟥 Phase 1: Preparation (Required for BOTH modes)

Before deploying, you must build the search index on the machine that holds the `.zim` files.

### 1. Build the SQLite Index
Run the crawler to extract text from your ZIM library into a local database.

```powershell
# Go to project root
Set-Location C:\Users\relz6\Documents\repos\offline-search

# Build index (Indexing 27k articles takes ~10-15 mins)
python build_local_index.py --library D:\Downloads\library.xml --output data\offline_index.sqlite
```
*Tip: Add `--limit 50` to the end of the command for a quick 1-minute test.*

---

## 🟦 Phase 2: Choose Your Deployment Mode

### Option A: Local Mode (All-in-One)
*Use this if:* Claude and the ZIM files are on the **same** computer.

**1. Configure Claude**
Add this to your Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "offline-search": {
      "command": "python",
      "args": ["C:\\Users\\relz6\\Documents\\repos\\offline-search\\offline_search_adapter.py"]
    }
  }
}
```

**2. How it works**
*   Claude starts `offline_search_adapter.py`.
*   The adapter automatically starts `kiwix-serve` in the background (Port 8081).
*   The adapter queries the local SQLite DB directly.

---

### Option B: Remote Mode (Distributed)
*Use this if:* ZIM files are on a **dedicated server**, and Claude is on your **laptop**.

#### Server Side (The machine with files)
You need to run two services physically on the server.

**1. Start Document Server (Kiwix)**
```powershell
# Serves content on Port 8081
Start-Process -FilePath "D:\Downloads\kiwix-tools_win-i686-3.7.0-2\kiwix-serve.exe" -ArgumentList "--port 8081 --library D:\Downloads\library.xml" -WindowStyle Hidden
```

**2. Start Search API**
```powershell
# Serves search results on Port 8082
Set-Location C:\Users\relz6\Documents\repos\offline-search
Start-Process -FilePath "python" -ArgumentList "search_server.py" -WindowStyle Hidden
```

#### Client Side (The machine with Claude)
**1. Configure Connection**
Edit `client_mcp_adapter.py` on your laptop and set the Server IP:
```python
# client_mcp_adapter.py
CENTRAL_HOST = "192.168.1.50"  # <--- Replace with your SERVER'S IP address
```

**2. Configure Claude**
Add this to the laptop's Claude config:
```json
{
  "mcpServers": {
    "offline-search": {
      "command": "python",
      "args": ["C:\\path\\to\\client_mcp_adapter.py"]
    }
  }
}
```

---

## 🟩 Troubleshooting & Health Checks

### Check if it's working (Local)
Run this manual script to see if the search returns results:
```powershell
Set-Location C:\Users\relz6\Documents\repos\offline-search
python test_search.py "python"
```

### Check if it's working (Remote)
On the client machine (laptop), try to ping the server's search API:
```powershell
# Replace 127.0.0.1 with your Server IP
curl "http://127.0.0.1:8082/search?q=python"
```
*If this fails: Check Windows Firewall on the Server (Allow Ports 8081 and 8082).*

### Packaging Checklist
If moving files to an air-gapped machine, ensure you have:
1.  `build_local_index.py`, `offline_search_adapter.py`, `search_server.py`
2.  `data/offline_index.sqlite` (The built index)
3.  The **Kiwix Tools** folder (kiwix-serve.exe)
4.  Your `library.xml` file
5.  All `.zim` files referenced in the library
