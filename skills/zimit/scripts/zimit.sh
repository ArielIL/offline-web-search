#!/usr/bin/env bash
# Crawl a website and package it as a ZIM file using Zimit (Docker).
# Optionally ingest the resulting ZIM into the offline-search index.
#
# Usage:
#   ./zimit.sh <url> [options]
#   ./zimit.sh https://docs.example.com --name example-docs
#   ./zimit.sh https://docs.example.com --name example-docs --limit 100 --ingest
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
ZIM_DIR="$PROJECT_DIR/data/zims"

# ---------- helpers ----------

info()  { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: zimit.sh <url> [options]

Crawl a website and create a ZIM file using Zimit (requires Docker).

Arguments:
  <url>                     URL to crawl (required)

Options:
  --name NAME               ZIM filename (default: derived from URL hostname)
  --limit N                 Max pages to crawl (default: unlimited)
  --workers N               Parallel crawl workers (default: 2)
  --output DIR              Output directory (default: data/zims/)
  --ingest                  Auto-ingest into offline-search index after creation
  --exclude REGEX           Skip URLs matching this regex
  --wait-until EVENT        Page load event: load, domcontentloaded (default: load)
  -h, --help                Show this help
EOF
    exit 0
}

# ---------- parse args ----------

URL=""
NAME=""
LIMIT=""
WORKERS="2"
OUTPUT_DIR="$ZIM_DIR"
INGEST=false
EXCLUDE=""
WAIT_UNTIL="load"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)     usage ;;
        --name)        NAME="$2"; shift 2 ;;
        --limit)       LIMIT="$2"; shift 2 ;;
        --workers)     WORKERS="$2"; shift 2 ;;
        --output)      OUTPUT_DIR="$2"; shift 2 ;;
        --ingest)      INGEST=true; shift ;;
        --exclude)     EXCLUDE="$2"; shift 2 ;;
        --wait-until)  WAIT_UNTIL="$2"; shift 2 ;;
        -*)            error "Unknown option: $1" ;;
        *)
            [ -z "$URL" ] || error "Multiple URLs not supported; got '$URL' and '$1'"
            URL="$1"; shift ;;
    esac
done

[ -n "$URL" ] || { echo "Error: URL is required"; echo; usage; }

# Derive name from hostname if not provided
if [ -z "$NAME" ]; then
    NAME="$(echo "$URL" | sed -E 's|https?://||; s|/.*||; s|[^a-zA-Z0-9]|_|g')"
fi

# ---------- preflight ----------

if ! command -v docker &>/dev/null; then
    error "Docker is required but not found. Install from https://docs.docker.com/get-docker/"
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker daemon is not running. Please start Docker and try again."
fi

mkdir -p "$OUTPUT_DIR"

# ---------- run zimit ----------

info "Crawling $URL -> $NAME.zim"
info "Output directory: $OUTPUT_DIR"
[ -n "$LIMIT" ] && info "Page limit: $LIMIT"

DOCKER_ARGS=(
    run --rm
    --dns 8.8.8.8
    -v "$OUTPUT_DIR:/output"
    ghcr.io/openzim/zimit
    zimit
    --seeds "$URL"
    --name "$NAME"
    --output /output
    --workers "$WORKERS"
    --waitUntil "$WAIT_UNTIL"
)

[ -n "$LIMIT" ] && DOCKER_ARGS+=(--pageLimit "$LIMIT")
[ -n "$EXCLUDE" ] && DOCKER_ARGS+=(--scopeExcludeRx "$EXCLUDE")

info "Running: docker ${DOCKER_ARGS[*]}"
docker "${DOCKER_ARGS[@]}"

# Find the output ZIM (zimit adds a date suffix)
ZIM_FILE="$(ls -t "$OUTPUT_DIR"/${NAME}*.zim 2>/dev/null | head -1)"
[ -n "$ZIM_FILE" ] || error "ZIM file not found in $OUTPUT_DIR after crawl"

info "Created: $ZIM_FILE ($(du -h "$ZIM_FILE" | cut -f1))"

# ---------- optional ingest ----------

if $INGEST; then
    info "Ingesting into offline-search index..."
    bash "$PROJECT_DIR/skills/setup/scripts/setup.sh" --index-only
    info "Done! ZIM is now searchable."
else
    info "To add to your search index, run:"
    echo "  bash skills/setup/scripts/setup.sh --index-only"
fi
