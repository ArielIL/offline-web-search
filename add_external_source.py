import sqlite3
import argparse
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- Configuration ---
DB_PATH = Path("data/offline_index.sqlite")

def index_external_site(url, name, limit=50):
    """
    Simple crawler for a local site (Proof of Concept).
    In reality, for Confluence/Artifactory you'd likely use their REST APIs
    to get cleaner content than scraping HTML.
    """
    print(f"Indexing {name} ({url})...")
    conn = sqlite3.connect(DB_PATH)
    
    # Ensure DB exists (it should if you ran build_local_index.py)
    if not DB_PATH.exists():
        print("Error: Database not found. Run build_local_index.py first.")
        return

    # Mock content for demonstration since we can't actually crawl your intranet
    # Replace this loop with actual requests.get() and soup parsing
    
    # Schema: title, content, zim_name, namespace, url
    # We will use:
    #   zim_name = name (e.g. "Confluence")
    #   namespace = 'W' (Web) or 'A'
    #   url = Full Absolute URL
    
    # Pseudocode for real crawling:
    # pages = fetch_confluence_pages(api_url, credentials)
    # for page in pages:
    
    print("Injecting sample external data...")
    fake_pages = [
        {
            "title": f"Welcome to {name}",
            "url": url,
            "content": f"This is the main page of our local {name} instance. It contains many artifacts."
        },
        {
            "title": f"{name} Deployment Guide", 
            "url": urljoin(url, "/docs/deployment"),
            "content": "To deploy artifacts to Artifactory, use the gradle plugin or npm publish."
        },
        {
            "title": f"Project X Documentation ({name})",
            "url": urljoin(url, "/spaces/PROJX"),
            "content": "Project X is our top secret offline AI initiative. It uses Python 3.14."
        }
    ]

    count = 0
    for p in fake_pages:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO documents (title, content, zim_name, namespace, url) VALUES (?, ?, ?, ?, ?)",
            (p["title"], p["content"], name, "W", p["url"])
        )
        count += 1
    
    conn.commit()
    conn.close()
    print(f"Indexed {count} pages from {name}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Base URL of the service", required=True)
    parser.add_argument("--name", help="Name of the service (e.g. Artifactory)", required=True)
    args = parser.parse_args()
    
    index_external_site(args.url, args.name)
