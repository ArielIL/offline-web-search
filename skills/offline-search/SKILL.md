---
name: offline-search
description: >
  Search offline documentation libraries (Wikipedia, Stack Overflow, Python docs,
  DevDocs, etc.) indexed from Kiwix ZIM archives. Use this whenever you need to
  look up API references, programming guides, technical documentation, or any
  external knowledge — especially when working without internet access. This is
  your primary source of external information when web search is unavailable.
agent: offline-search-agent
allowed-tools: Bash(python *)
argument-hint: "[search query]"
---

# Offline Search

You have access to an **offline documentation search engine** powered by Kiwix
ZIM archives indexed into SQLite FTS5. This skill routes through a Haiku
sub-agent that searches, summarizes results, and returns only the relevant
information — saving tokens in the main model's context window.

## How it works

When invoked, the `offline-search-agent` (running on Haiku) will:

1. Run the search query against the offline index
2. Analyze the raw results
3. Return a **condensed summary** with titles, URLs, and brief descriptions
4. If you need full page content, the agent fetches and extracts only the relevant parts

## Available commands (executed by the agent)

### 1. Search documentation

```bash
python "skills/offline-search/scripts/search.py" "<query>"
```

- Be specific with queries (e.g. `python asyncio gather`, `sqlite fts5 syntax`)

### 2. Read a full page

```bash
python "skills/offline-search/scripts/fetch_page.py" "<url>"
```

- Pass the exact URL from a search result

## CRITICAL REQUIREMENT — Sources

After using search results to answer the user's question, you **MUST** include a
`Sources:` section at the end of your response with markdown hyperlinks:

```
Sources:
- [Page Title](URL)
- [Another Page](URL)
```

This is **MANDATORY** — never skip including sources in your response.

## Workflow

1. **Search** — the agent runs `search.py` with your query and summarizes results
2. **Read what's relevant** — ask the agent to fetch promising URLs
3. **Cite your sources** — list all used sources as `[Title](URL)` under a `Sources:` section

## When to search

Your existing knowledge covers a wide range of topics and is sufficient for many
queries. Use this tool when a search would genuinely add value:

- Looking up specific API signatures, function parameters, or library features
- Verifying technical details that may have changed between versions
- Researching unfamiliar libraries, tools, or concepts
- The user explicitly asks you to search or look something up
- Finding specific facts or details you're unsure about
- Confirming implementation details that could be outdated

## When NOT to search

Skip searching for things you already know well:

- Stable, well-established knowledge (definitions, theories, fundamental concepts)
- General explanations or ELI5-style questions (e.g. "explain how TCP works")
- Information that rarely changes (e.g. capital cities, historical dates, language syntax basics)
- Casual conversation or opinion-based questions
- Broad coding help like "how to write a for loop" — just answer directly

## Query best practices

- **Keep queries short and focused** — 1 to 6 words produce the best results
- **Break complex questions into multiple searches** rather than one long query
- **Each query should be meaningfully different** — rephrasing the same words won't yield new results
- **Include version numbers only when relevant** (e.g. when the user specifies a version)
- **Avoid search operators** like `-`, `site:`, `+`, or `NOT` — they aren't supported
- If a search returns no results, try broader or alternative keywords
- Synonyms are expanded automatically (e.g. `js` → `javascript`, `py` → `python`)
- Common stop words are stripped; focus on meaningful terms
- Results are ranked by relevance with title matches weighted 10×

If invoked directly with arguments (e.g. `/offline-search python asyncio`),
search for `$ARGUMENTS` as the query.
