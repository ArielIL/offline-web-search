import sqlite3
import os

db_path = "data/offline_index.sqlite"

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "if", "in", 
    "into", "is", "it", "no", "not", "of", "on", "or", "such", "that", "the", 
    "their", "then", "there", "these", "they", "this", "to", "was", "will", 
    "with", "between"
}

def is_garbage(url):
    return "analytics.python.org" in url

def is_english(url):
    # Heuristic: if it contains /ja/, /zh-cn/, /ko/, /fr/ it's likely not english
    # relative to the base ZIM which is en.
    # docs.python.org_en ZIM contains localized subfolders.
    markers = ["/ja/", "/zh-cn/", "/ko/", "/fr/", "/pt-br/", "/es/"]
    for m in markers:
        if m in url:
            return False
    return True

def test_query(q):
    print(f"\n--- Testing query: '{q}' ---")
    if not os.path.exists(db_path):
        print("DB not found")
        return

    # Filter stop words
    terms = [t for t in q.strip().split() if t.lower() not in STOP_WORDS]
    safe_query = " ".join(f'"{term.replace("\"", "\"\"")}"' for term in terms)
    print(f"Safe Query (No Stopwords): {safe_query}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        
        # Using Weighted BM25 (Boost Title 10x)
        cursor.execute(
            "SELECT title, url, bm25(documents, 10.0, 1.0, 0.0, 0.0, 0.0) as score FROM documents WHERE documents MATCH ? LIMIT 100",
            (safe_query,)
        )
        
        # Fetch all results then rank in Python
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} raw hits. Ranking...")
        
        ranked_hits = []
        for row in rows:
            url = row['url']
            if is_garbage(url):
                continue
                
            score = row['score']
            
            # Penalize non-english
            # In SQLite FTS5 BM25, the returned score is NEGATIVE if using order='DESC'?
            # Actually, standard FTS5 BM25 is just a number.
            # Let's inspect the math.
            # Documentation says: "The value returned is the BM25 score".
            # Usually users do ORDER BY bm25(documents).
            # If the engine returns negative, then ASC sort puts most relevant (most negative) first.
            # Let's assume most negative is best based on previous output (-8.95 best vs -3.10 worst).
            
            if not is_english(url):
                score += 10.0 # Make it "larger" (worse) by adding positive number
            
            ranked_hits.append((score, row['title'], url))

        # Sort by score (ascending)
        ranked_hits.sort(key=lambda x: x[0])
        
        for score, title, url in ranked_hits[:10]:
            print(f"  {score:.4f} | {title} | {url}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    test_query("differences between python 3.12 and python 3.13")
    test_query("python 3.13")
