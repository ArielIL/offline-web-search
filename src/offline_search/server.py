"""HTTP search API server — FastAPI-based replacement for the stdlib server.

Exposes ``/search``, ``/health``, and content-management endpoints.

Usage (standalone)::

    python -m offline_search.server

Or via the entry-point::

    offline-search-server
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .config import settings
from .indexer import (
    get_index_stats,
    index_html_page,
    prepare_database,
    remove_by_url,
    remove_by_zim_path,
)
from .search_engine import SearchResult, search_sync
from .updater import (
    ZIM_MAGIC,
    export_manifest,
    get_installed_zims,
    ingest_zim,
    validate_zim_file,
)

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
):
    """Full-text search across the offline index."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Empty query")

    results = search_sync(q, limit=limit, zim_filter=zim)
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
# ZIM management — auth & endpoints
# ---------------------------------------------------------------------------


def _require_api_key(authorization: str | None = Header(None)) -> None:
    """Dependency that enforces Bearer token auth for ZIM mutation endpoints.

    If ``OFFLINE_SEARCH_API_KEY`` is empty, all mutations are **disabled**
    (fail-closed).
    """
    configured_key = settings.api_key
    if not configured_key:
        raise HTTPException(
            status_code=403,
            detail="ZIM management endpoints are disabled (no API key configured)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != configured_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


class IngestRequest(BaseModel):
    zim_path: str
    replace: bool = True
    delete_old: bool = True
    restart_kiwix: bool = True


@app.get("/zim/list")
async def zim_list():
    """List installed ZIMs with version info."""
    zims = get_installed_zims()
    return [
        {
            "base_name": z.base_name,
            "version": z.version,
            "filename": z.filename,
            "article_count": z.article_count,
        }
        for z in zims
    ]


@app.get("/zim/manifest")
async def zim_manifest():
    """Export a JSON manifest of installed ZIMs."""
    return export_manifest()


@app.post("/zim/upload", dependencies=[Depends(_require_api_key)])
async def zim_upload(file: UploadFile):
    """Upload a ZIM file, validate it, and run the zero-downtime ingest pipeline."""
    if not file.filename or not file.filename.endswith(".zim"):
        raise HTTPException(status_code=400, detail="File must have a .zim extension")

    # Read first 4 bytes to validate magic
    header = await file.read(4)
    if header != ZIM_MAGIC:
        raise HTTPException(status_code=400, detail="Invalid ZIM file (bad magic bytes)")
    # Seek back so we can write the full file
    await file.seek(0)

    # Check size limit
    max_bytes = int(settings.upload_max_size_gb * 1024 * 1024 * 1024)
    if file.size and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.upload_max_size_gb} GB)",
        )

    # Stream to zim_dir
    zim_dir = settings.zim_dir
    zim_dir.mkdir(parents=True, exist_ok=True)
    dest = zim_dir / file.filename

    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")

    result = ingest_zim(dest)
    return {
        "success": result.success,
        "filename": result.zim_info.filename,
        "articles_indexed": result.articles_indexed,
        "articles_removed": result.articles_removed,
        "replaced": result.replaced.filename if result.replaced else None,
        "errors": result.errors,
    }


@app.post("/zim/ingest", dependencies=[Depends(_require_api_key)])
async def zim_ingest(req: IngestRequest):
    """Ingest a ZIM file already present on disk."""
    zim_path = Path(req.zim_path)
    if not zim_path.exists():
        raise HTTPException(status_code=404, detail=f"ZIM file not found: {req.zim_path}")
    if not validate_zim_file(zim_path):
        raise HTTPException(status_code=400, detail="Invalid ZIM file")

    result = ingest_zim(
        zim_path,
        replace=req.replace,
        delete_old=req.delete_old,
        restart_kiwix=req.restart_kiwix,
    )
    return {
        "success": result.success,
        "filename": result.zim_info.filename,
        "articles_indexed": result.articles_indexed,
        "articles_removed": result.articles_removed,
        "replaced": result.replaced.filename if result.replaced else None,
        "errors": result.errors,
    }


@app.delete("/zim/{filename}", dependencies=[Depends(_require_api_key)])
async def zim_delete(filename: str, keep_file: bool = Query(False)):
    """Remove a ZIM from the library, index, and optionally disk."""
    zims = get_installed_zims()
    target = next((z for z in zims if z.filename == filename), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"ZIM {filename} not found")

    conn = prepare_database(settings.db_path, reset=False)
    try:
        removed = remove_by_zim_path(conn, str(target.zim_path))
    finally:
        conn.close()

    if not keep_file and target.zim_path.exists():
        target.zim_path.unlink()

    return {"status": "ok", "documents_removed": removed, "file_deleted": not keep_file}


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
