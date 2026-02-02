from typing import Any
import asyncio
import sqlite3
from pathlib import Path
import httpx
from mcp.server.fastmcp import FastMCP
from bs4 import BeautifulSoup
import urllib.parse
import subprocess
import socket
import time

# Initialize FastMCP server
mcp = FastMCP("offline-search")

KIWIX_EXE = r"D:\\Downloads\\kiwix-tools_win-i686-3.7.0-2\\kiwix-serve.exe"
LIBRARY_XML = str(Path(__file__).resolve().parent / "library_test.xml")
KIWIX_PORT = 8081
KIWIX_URL = f"http://127.0.0.1:{KIWIX_PORT}"
LOCAL_INDEX_DB = Path(__file__).resolve().parent / "data" / "offline_index.sqlite"

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_kiwix_server():
    if is_port_open(KIWIX_PORT):
        print(f"Kiwix server already running on port {KIWIX_PORT}")
        return

    print(f"Starting Kiwix server on port {KIWIX_PORT}...")
    try:
        # Use Popen to run in background. stdin=DEVNULL avoids blocking/issues.
        # On Windows, we might want CREATE_NO_WINDOW if running as GUI, 
        # but here we just want it to persist.
        subprocess.Popen(
            [KIWIX_EXE, "--port", str(KIWIX_PORT), "--library", LIBRARY_XML],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # shell=False is default
        )
        # Wait a bit for startup
        for _ in range(10):
            if is_port_open(KIWIX_PORT):
                print("Kiwix server started successfully.")
                return
            time.sleep(0.5)
        print("Warning: Kiwix server might have failed to start.")
    except Exception as e:
        print(f"Failed to start Kiwix server: {e}")


def _search_local_index_sync(query: str, limit: int = 10) -> list[tuple[str, str, str]]:
    if not LOCAL_INDEX_DB.exists():
        return []

    STOP_WORDS = {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", "in", 
        "into", "is", "it", "no", "not", "of", "on", "or", "such", "that", "the", 
        "their", "then", "there", "these", "they", "this", "to", "was", "will", 
        "with", "between"
    }

    # Tokenize and filter stop words
    # Wraps each term in quotes to treat as literal tokens, ensuring stability.
    raw_terms = query.strip().split()
    terms = [t for t in raw_terms if t.lower() not in STOP_WORDS]
    
    # Fallback: if all terms were stop words (e.g. "to be"), use original
    if not terms and raw_terms:
        terms = raw_terms
        
    if not terms:
        return []

    safe_terms = [f'"{term.replace("\"", "\"\"")}"' for term in terms]
    safe_query = " ".join(safe_terms)

    conn = sqlite3.connect(LOCAL_INDEX_DB)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        # Fetch more candidates (limit * 5) to allow for post-filtering
        # Weighting: 10.0 for title (col 0), 1.0 for content (col 1), 0.0 for others
        cursor.execute(
            "SELECT title, url, zim_name, namespace, "
            "snippet(documents, 1, '[', ']', ' … ', 10) AS snippet, "
            "bm25(documents, 10.0, 1.0, 0.0, 0.0, 0.0) AS score "
            "FROM documents WHERE documents MATCH ? ORDER BY score LIMIT ?",
            (safe_query, limit * 5),
        )
        rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            url_fragment = row["url"] or ""
            
            # 1. Filter Garbage
            if "analytics.python.org" in url_fragment:
                continue

            # 2. Score Adjustment (Penalize non-English)
            score = row["score"] # Note: FTS5 BM25 returns negative values usually? 
            # Or depends on order. Let's rely on Relative order.
            # If we assume the DB returned them sorted best-to-worst...
            # We want to push non-English items down.
            # Heuristic: Check common non-English markers
            is_non_english = any(m in url_fragment for m in ["/ja/", "/zh-cn/", "/ko/", "/fr/", "/pt-br/", "/es/"])
            
            # Since we don't know the exact range of BM25 scores (it's unbounded),
            # adding a penalty might be tricky if we don't know the sign.
            # However, simpler approach: Split into two lists.
            
            safe_fragment = urllib.parse.quote(url_fragment, safe="/:?=&%._-#")
            namespace = row["namespace"] or "A"
            zim_name = row["zim_name"]
            full_url = f"{KIWIX_URL}/content/{zim_name}/{namespace}/{safe_fragment}"
            snippet = row["snippet"] or ""
            
            candidates.append({
                "title": row["title"],
                "url": full_url,
                "snippet": snippet.strip(),
                "score": score,
                "is_non_english": is_non_english
            })

        # Sort: English first (False < True), then by Score (ascending per SQLite standard if that's what we got)
        # Wait, if we use ORDER BY score in SQL, we get them in order.
        # So we just need to stable-sort by is_non_english.
        candidates.sort(key=lambda x: x["is_non_english"])
        
        # Take top N
        results = [(c["title"], c["url"], c["snippet"]) for c in candidates[:limit]]
        return results
    finally:
        conn.close()


async def search_local_index(query: str, limit: int = 10) -> list[tuple[str, str, str]]:
    return await asyncio.to_thread(_search_local_index_sync, query, limit)

@mcp.tool()
async def google_search(query: str) -> str:
    """
    Performs a full-text search across the offline documentation library.
    Use this tool whenever you need to look up documentation, API references, or technical guides regarding Python, programming, or any other topic present in the local library.
    
    This tool is your primary source of external information since you do not have internet access.
    
    Args:
        query: The search keywords. Try to be specific (e.g., 'python 3.11 new features', 'sqlite fts5 syntax').
    """
    # Uses 'pattern' for text search across the library or within books
    search_url = f"{KIWIX_URL}/search?pattern={urllib.parse.quote(query)}"
    
    try:
        local_hits = await search_local_index(query)
        if local_hits:
            lines = [
                f"Title: {title}\nURL: {url}\nSnippet: {snippet or 'No preview available.'}\n"
                for title, url, snippet in local_hits
            ]
            return "\n".join(lines)

        async with httpx.AsyncClient() as client:
            response = await client.get(search_url)
            response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        results = []
        
        # Kiwix serve usually returns results in a list
        # We look for links within the result container
        for result_div in soup.select("li.result, div.result_row, div.result, tr.result"): 
            link = result_div.find("a")
            if not link:
                continue
                
            title = link.get_text(strip=True)
            url = link.get('href')
            
            if url and not url.startswith('http'):
                url = f"{KIWIX_URL}{url}"
                
            # Snippet extraction
            snippet_div = result_div.find("p") or result_div.find("div", class_="snippet")
            snippet = snippet_div.get_text(strip=True) if snippet_div else "No preview available."
            
            results.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}\n")
            
        if not results:
             return "No results found or parsing failed. Please refine query."

        return "\n".join(results[:10]) # Return top 10

    except Exception as e:
        return f"Error executing offline search: {str(e)}"

if __name__ == "__main__":
    start_kiwix_server()
    mcp.run()
