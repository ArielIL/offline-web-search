import sqlite3
import os

db_path = "data/offline_index.sqlite"

def test_query(q):
    print(f"Testing query: '{q}'")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Raw bind
        cursor.execute("SELECT count(*) FROM documents WHERE documents MATCH ?", (q,))
        print("  Success (Raw)")
    except Exception as e:
        print(f"  Error (Raw): {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if not os.path.exists(db_path):
        print("DB not found")
        exit()
        
    queries = [
        "python",
        "python.",
        "python 3.12",
        "node.js",
        '"quoted"',
        "unclosed quote \"",
        "doc.python.org",
        ".",
        "foo. bar"
    ]
    
    for q in queries:
        test_query(q)
