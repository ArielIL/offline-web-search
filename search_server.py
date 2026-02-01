import http.server
import socketserver
import json
import sqlite3
import urllib.parse
from pathlib import Path

# Config
PORT = 8082
DB_PATH = Path("data/offline_index.sqlite")

class SearchRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Parse URL
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if path == "/search":
            self.handle_search(query_params)
        else:
            self.send_error(404, "Endpoint not found")

    def handle_search(self, params):
        query = params.get('q', [''])[0]
        limit = int(params.get('limit', ['10'])[0])
        
        if not query:
            self.send_response(400)
            self.end_headers()
            return

        results = search_index(query, limit)
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(results).encode('utf-8'))

    def log_message(self, format, *args):
        return # Silence logs

def search_index(query, limit):
    if not DB_PATH.exists():
        return []

    STOP_WORDS = {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", "in", 
        "into", "is", "it", "no", "not", "of", "on", "or", "such", "that", "the", 
        "their", "then", "there", "these", "they", "this", "to", "was", "will", 
        "with", "between"
    }

    raw_terms = query.strip().split()
    terms = [t for t in raw_terms if t.lower() not in STOP_WORDS]
    if not terms and raw_terms: terms = raw_terms
    if not terms: return []

    safe_query = " ".join(f'"{term.replace("\"", "\"\"")}"' for term in terms)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, url, bm25(documents, 10.0, 1.0, 0.0, 0.0, 0.0) AS score, snippet(documents, 1, '[', ']', ' … ', 10) AS snippet, zim_name, namespace "
            "FROM documents WHERE documents MATCH ? ORDER BY score LIMIT ?",
            (safe_query, limit * 2) # Fetch extra for filtering
        )
        
        results = []
        rows = cursor.fetchall()
        
        # Simple client-side re-ranking/filtering
        candidates = []
        for row in rows:
            url = row['url']
            if "analytics.python.org" in url: continue
            
            # Penalize non-english
            score = row['score']
            if any(m in url for m in ["/ja/", "/zh-cn/", "/ko/", "/fr/", "/pt-br/", "/es/"]):
               pass # Could penalize here or just rely on sort order if user prefers English
            
            # Construct full kiwix URL path parts (client will assemble base URL)
            candidates.append({
                "title": row['title'],
                "url": url,
                "snippet": row['snippet'],
                "zim_name": row['zim_name'],
                "namespace": row['namespace']
            })

        return candidates[:limit]

    except Exception as e:
        print(f"Search error: {e}")
        return []
    finally:
        conn.close()

if __name__ == "__main__":
    print(f"Starting Search API on port {PORT}...")
    with socketserver.TCPServer(("", PORT), SearchRequestHandler) as httpd:
        print("Serving forever.")
        httpd.serve_forever()
