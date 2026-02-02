from typing import Any
import asyncio
import httpx
from mcp.server.fastmcp import FastMCP
import urllib.parse

# --- CONFIGURATION (Client Side) ---
# Point these to your central machine's IP address
CENTRAL_HOST = "127.0.0.1" 
SEARCH_API_URL = f"http://{CENTRAL_HOST}:8082" 
KIWIX_BASE_URL = f"http://{CENTRAL_HOST}:8081"

mcp = FastMCP("offline-search-client")

@mcp.tool()
async def google_search(query: str) -> str:
    """
    Search the offline documentation library.
    Returns a list of results with titles and snippets.
    
    Args:
        query: The search text query.
    """
    try:
        async with httpx.AsyncClient() as client:
            # 1. Helper Search API (Fast FTS5)
            # The search_server.py on the central machine handles tokenization/stopwords/ranking
            response = await client.get(
                f"{SEARCH_API_URL}/search", 
                params={"q": query, "limit": 10},
                timeout=5.0
            )
            
            if response.status_code == 200:
                results = response.json()
                if results:
                    lines = []
                    for r in results:
                        # Reconstruct full Kiwix URL on the client
                        # URL stored in DB is relative path inside ZIM (or partial)
                        # We need: KIWIX_BASE / content / zim_name / namespace / url
                        
                        # Note: The DB 'url' field from build_local_index might be just the path sans zim/namespace, 
                        # or it might be inconsistent. Let's look at search_server.py output.
                        # Output has: title, url, snippet, zim_name, namespace.
                        
                        zim = r.get("zim_name")
                        ns = r.get("namespace", "A")
                        partial_url = r.get("url")
                        
                        # Handle External/Absolute URLs (Confluence, Artifactory, etc.)
                        if partial_url and (partial_url.startswith("http://") or partial_url.startswith("https://")):
                            full_link = partial_url
                        else:
                            # Construct Kiwix URL for ZIM content
                            encoded_url = urllib.parse.quote(partial_url, safe="/:?=&%._-#")
                            full_link = f"{KIWIX_BASE_URL}/content/{zim}/{ns}/{encoded_url}"
                        
                        lines.append(f"Title: {r['title']}\nURL: {full_link}\nSnippet: {r['snippet']}\n")
                    
                    return "\n".join(lines)
            
            # 2. Fallback to direct Kiwix Search if API fails or returns nothing
            # (Optional, but good for redundancy)
            kiwix_search_url = f"{KIWIX_BASE_URL}/search?pattern={urllib.parse.quote(query)}"
            # ... (omitted for brevity in this client script, keeping it reliable)
            
            return "No results found."

    except Exception as e:
        return f"Error executing search: {str(e)}"

if __name__ == "__main__":
    mcp.run()
