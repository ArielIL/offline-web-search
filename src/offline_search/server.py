"""HTTP search API server — FastAPI-based replacement for the stdlib server.

Exposes ``/search``, ``/health``, and content-management endpoints.

Usage (standalone)::

    python -m offline_search.server

Or via the entry-point::

    offline-search-server
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .config import settings
from .indexer import (
    get_index_stats,
    index_html_page,
    prepare_database,
    remove_by_url,
)
from .search_engine import SearchResult, search_sync

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Offline Search API",
    description="Full-text search API for offline ZIM documentation.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Health / stats
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — confirms the API is running and the index is accessible."""
    stats = get_index_stats()
    return {"status": "ok", "index": stats}


@app.get("/stats")
async def stats():
    """Return detailed index statistics."""
    return get_index_stats()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.get("/search")
async def search_endpoint(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    zim: str | None = Query(None, description="Filter by ZIM source name"),
    allowed_zims: list[str] | None = Query(None, description="Restrict to these ZIM sources (allowlist)"),
    blocked_zims: list[str] | None = Query(None, description="Exclude these ZIM sources (blocklist)"),
):
    """Full-text search across the offline index."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    results = search_sync(q, limit=limit, zim_filter=zim, allowed_zims=allowed_zims, blocked_zims=blocked_zims)
    return [r.to_dict() for r in results]


# ---------------------------------------------------------------------------
# Content management
# ---------------------------------------------------------------------------

class IndexPageRequest(BaseModel):
    title: str
    content: str
    url: str
    source_name: str = "external"


class IndexCrawlRequest(BaseModel):
    base_url: str
    source_name: str = "crawl"
    max_pages: int = 50


@app.post("/index/page")
async def index_page(req: IndexPageRequest):
    """Index a single HTML/text page into the database."""
    conn = prepare_database(settings.db_path)
    try:
        docid = index_html_page(
            conn,
            title=req.title,
            content=req.content,
            url=req.url,
            source_name=req.source_name,
        )
        return {"status": "ok", "docid": docid}
    finally:
        conn.close()


@app.post("/index/crawl")
async def index_crawl(req: IndexCrawlRequest):
    """Crawl a website and index all discovered pages.

    This does a lightweight breadth-first crawl starting from *base_url*.
    """
    visited: set[str] = set()
    queue = [req.base_url]
    indexed = 0

    conn = prepare_database(settings.db_path)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            while queue and len(visited) < req.max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception:
                    logger.debug("Crawl: failed to fetch %s", url)
                    continue

                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                title = soup.title.get_text(strip=True) if soup.title else url
                text = soup.get_text("\n", strip=True)

                if text:
                    index_html_page(
                        conn,
                        title=title,
                        content=text,
                        url=url,
                        source_name=req.source_name,
                    )
                    indexed += 1

                # Discover links
                base_domain = urlparse(req.base_url).netloc
                for a_tag in soup.find_all("a", href=True):
                    href = urljoin(url, a_tag["href"])
                    if urlparse(href).netloc == base_domain and href not in visited:
                        queue.append(href)

        return {"status": "ok", "pages_indexed": indexed, "pages_visited": len(visited)}
    finally:
        conn.close()


@app.delete("/index")
async def delete_by_url(
    url: str = Query(..., description="URL of the document to remove"),
):
    """Remove a document from the index by URL."""
    conn = prepare_database(settings.db_path)
    try:
        deleted = remove_by_url(conn, url)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"status": "ok", "deleted": deleted}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI: ``offline-search-server``"""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info(
        "Starting Offline Search API on %s:%d …",
        settings.server_host,
        settings.server_port,
    )
    uvicorn.run(
        "offline_search.server:app",
        host=settings.server_host,
        port=settings.server_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
