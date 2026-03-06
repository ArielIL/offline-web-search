---
name: offline-search
description: >
  Search offline documentation libraries (Wikipedia, Stack Overflow, Python docs,
  DevDocs, etc.) indexed from Kiwix ZIM archives. Use this whenever you need to
  look up API references, programming guides, technical documentation, or any
  external knowledge — especially when working without internet access. This is
  your primary source of external information when web search is unavailable.
allowed-tools: Bash(python *)
argument-hint: "[search query]"
---

# Offline Search

You have access to an **offline documentation search engine** powered by Kiwix
ZIM archives indexed into SQLite FTS5. Use it as your drop-in replacement for
web search.

## Available commands

### 1. Search documentation

Run this to search across all indexed docs:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/search.py" "<query>"
```

- Be specific with queries (e.g. `python asyncio gather`, `sqlite fts5 syntax`)
- Returns: title, URL, and snippet for each result
- The URL in each result can be passed to the fetch script below

### 2. Read a full page

After finding a relevant result, fetch its full content:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/fetch_page.py" "<url>"
```

- Pass the exact URL from a search result
- Returns: clean Markdown text of the full page (capped at 15,000 chars)
- Starts kiwix-serve automatically if not already running

## Workflow

1. **Search first** — run `search.py` with your query
2. **Read what's relevant** — run `fetch_page.py` on promising URLs
3. **Cite your source** — mention the page title when using information

## When to use this

- You need to look up an API, function signature, or library feature
- You're asked about a topic and want to verify your knowledge
- The user asks you to research something
- You encounter an unfamiliar library, tool, or concept
- Any time you would normally use web search

## Tips

- If a search returns no results, try broader or different keywords
- Synonyms are expanded automatically (e.g. `js` → `javascript`, `py` → `python`)
- Common stop words are stripped; focus on meaningful terms
- Results are ranked by relevance with title matches weighted 10×

If invoked directly with arguments (e.g. `/offline-search python asyncio`),
run the search script with `$ARGUMENTS` as the query.
