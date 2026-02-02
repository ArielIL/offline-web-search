import asyncio
import sys
from offline_search_adapter import start_kiwix_server, google_search

def run_test():
    print("Starting Kiwix Server...")
    start_kiwix_server()
    
    # Allow command line arg for query
    query = sys.argv[1] if len(sys.argv) > 1 else 'python.'  # Default to a "dangerous" query
    print(f"\nSearching for: '{query}'...")
    
    try:
        # google_search is an async function in the adapter (decorated with @mcp.tool)
        result = asyncio.run(google_search(query))
        
        print("\n--- Search Results ---")
        print(result[:2000] + "\n..." if len(result) > 2000 else result)
        print("\n----------------------")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_test()
