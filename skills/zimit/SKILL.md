---
name: zimit
description: >
  Crawl a website and package it as a ZIM archive for offline search.
  Uses Zimit (Docker) to crawl any URL, then optionally ingests the
  resulting ZIM into the offline-search index. Use this to add internal
  docs, wikis, or any website to your offline search library.
allowed-tools: Bash(*)
argument-hint: "<url> [--name NAME] [--limit N] [--ingest]"
---

# Zimit — Crawl & Package Websites as ZIM

This skill uses [Zimit](https://github.com/openzim/zimit) to crawl a website
and create a ZIM archive that can be searched offline.

**Requires Docker** — Zimit runs as a Docker container.

## Usage

```bash
# Crawl a site and create a ZIM
bash skills/zimit/scripts/zimit.sh https://docs.example.com --name example-docs

# Crawl with a page limit (useful for large sites)
bash skills/zimit/scripts/zimit.sh https://docs.example.com --name example-docs --limit 200

# Crawl and immediately ingest into the search index
bash skills/zimit/scripts/zimit.sh https://docs.example.com --name example-docs --ingest

# Exclude certain URL patterns
bash skills/zimit/scripts/zimit.sh https://docs.example.com --name example-docs \
  --exclude "/api/v1|/blog/"
```

If invoked with arguments (e.g. `/zimit https://docs.example.com`), pass them
through to the script.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--name NAME` | from hostname | ZIM filename |
| `--limit N` | unlimited | Max pages to crawl |
| `--workers N` | 2 | Parallel crawl workers |
| `--output DIR` | `data/zims/` | Output directory |
| `--ingest` | off | Auto-rebuild search index after creation |
| `--exclude REGEX` | none | Skip URLs matching regex |
| `--wait-until EVENT` | `load` | Page load event (`load` or `domcontentloaded`) |

## Tips

- **Start small** — use `--limit 50` first to test, then remove the limit for a full crawl
- **Internal docs** — great for Confluence, GitBook, Docusaurus, MkDocs, etc.
- **Large sites** — crawling Stack Overflow or Wikipedia is slow; prefer downloading
  pre-built ZIMs from the Kiwix catalog instead (`/setup --zims "..."`)
- **After crawling** — if you didn't use `--ingest`, rebuild the index with:
  ```bash
  bash skills/setup/scripts/setup.sh --index-only
  ```
