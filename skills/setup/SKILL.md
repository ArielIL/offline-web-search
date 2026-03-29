---
name: setup
description: >
  Set up the offline-search environment: install kiwix-tools binaries, download
  ZIM documentation archives, build the library.xml catalog, create the FTS5
  search index, and write the .env config. Use this when setting up a new machine,
  adding new ZIM content, or rebuilding the index after changes.
allowed-tools: Bash(*)
argument-hint: "[--zims 'python,javascript,...'] [--kiwix-only] [--index-only]"
---

# Offline Search Setup

This skill automates the full setup of the offline-search environment.

## What it does

1. **Installs kiwix-tools** — detects your platform (macOS ARM/x86, Linux, Windows) and downloads `kiwix-serve` + `kiwix-manage` to `bin/`
2. **Downloads ZIM files** — fetches documentation archives from the Kiwix catalog
3. **Builds library.xml** — registers all ZIMs with kiwix-manage
4. **Builds the FTS5 index** — indexes all ZIM content into SQLite for fast search
5. **Writes .env** — configures paths so all tools find each other

## Usage

Run the setup script:

```bash
# Full setup with specific ZIMs
bash skills/setup/scripts/setup.sh --zims "python,javascript,bash"

# Just install kiwix-tools (no ZIMs)
bash skills/setup/scripts/setup.sh --kiwix-only

# Rebuild index only (after manually adding ZIMs to data/zims/)
bash skills/setup/scripts/setup.sh --index-only
```

If invoked with arguments (e.g. `/setup --zims "python,react"`), pass them through
to the script.

If invoked without arguments, run:

```bash
bash skills/setup/scripts/setup.sh
```

This installs kiwix-tools and guides the user on downloading ZIMs.

## Finding ZIM names

To search for available ZIMs before downloading:

```bash
uv run offline-search-catalog search <topic>
```

Common ZIM names for `--zims`:
- `python`, `javascript`, `typescript`, `react`, `node`, `bash`, `git`
- `django`, `flask`, `fastapi`, `express`, `angular`, `vue`
- `rust`, `go`, `cpp`, `java`, `kotlin`, `swift`

Use short topic names — the catalog search handles matching.

## After setup

Verify everything works:

```bash
uv run python skills/offline-search/scripts/search.py "test query"
```
