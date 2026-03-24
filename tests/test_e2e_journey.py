"""Full E2E integration test pipeline.

Avoids mocks as much as possible. Runs the indexer against real ZIM files,
boots up a real kiwix-serve process, searches the real SQLite database,
and makes real HTTP requests to the kiwix-serve process for content.
"""

import socket
from pathlib import Path

import pytest

from offline_search.indexer import index_zim, prepare_database
from offline_search.kiwix import fetch_page
from offline_search.search_engine import search_sync
from offline_search.config import settings


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def e2e_environment(tmp_path_factory):
    # 1. Setup paths
    tmp_path = tmp_path_factory.mktemp("e2e_data")
    db_path = tmp_path / "e2e_index.sqlite"
    xml_path = tmp_path / "library.xml"

    zim_path = Path(__file__).parent / "data" / \
        "devdocs_en_markdown_2026-01.zim"
    if not zim_path.exists():
        pytest.skip(f"Test fixture {zim_path} not found")

    # 2. Build Index using the actual indexer logic
    conn = prepare_database(db_path)
    zim_name = zim_path.stem
    index_zim(conn, zim_path, zim_name=zim_name)
    conn.close()

    # 3. Create library.xml for kiwix-serve
    # kiwix-serve uses the zim's physical file stem as the namespace regardless of the name attribute
    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<library>
  <book path="{zim_path.absolute()}" name="some_random_incorrect_name" id="dummy-id-1234"/>
</library>'''
    xml_path.write_text(xml_content, encoding="utf-8")

    # 4. Start kiwix-serve process
    import shutil
    if not shutil.which(settings.kiwix_exe) and not Path(settings.kiwix_exe).exists():
        pytest.skip(f"kiwix-serve binary not found at {settings.kiwix_exe}")

    port = find_free_port()

    from offline_search.kiwix import start_kiwix_server
    success = start_kiwix_server(
        port=port,
        library_xml=str(xml_path),
        timeout=10.0
    )

    if not success:
        pytest.fail(f"kiwix-serve failed to start on port {port}")

    target_url = f"http://127.0.0.1:{port}"

    # Patch config to use the temporary database and port
    # (kiwix_url is a computed property derived from kiwix_port)
    original_db = settings.db_path
    original_port = settings.kiwix_port

    settings.db_path = db_path
    settings.kiwix_port = port

    yield {"db_path": db_path, "url": target_url, "port": port}

    # Teardown
    settings.db_path = original_db
    settings.kiwix_port = original_port

    # Send a kill signal to kiwix-serve process on the port
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'connections']):
        try:
            for conn in proc.connections():
                if conn.laddr.port == port:
                    proc.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_search_and_fetch(e2e_environment):
    db_path = e2e_environment["db_path"]
    kiwix_url = e2e_environment["url"]

    # 1. Search DB for a realistic keyword
    results = search_sync("markdown", db_path=db_path, limit=5)
    assert len(
        results) > 0, "Indexer failed to retrieve any documents for 'markdown'"

    top_result = results[0]
    assert top_result.zim_name == "devdocs_en_markdown_2026-01"

    # Generate full URL based on the same logic used in our system
    fetch_url = top_result.format_full_url(kiwix_url)
    assert "devdocs_en_markdown_2026-01" in fetch_url

    # 2. Fetch page (actual HTTP request, NO MOCKS)
    content = await fetch_page(fetch_url)

    # 3. Assert content was successfully processed into Markdown
    assert content
    assert len(content) > 10
    # It shouldn't contain raw HTML bodies or script tags
    assert "<html>" not in content.lower()
    assert "<script>" not in content.lower()
