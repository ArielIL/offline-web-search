#!/usr/bin/env bash
# build_library.sh — Scan a directory for ZIM files and add them all to library.xml.
#
# Usage:
#   ./scripts/build_library.sh <zim_dir> [library.xml]
#
# Examples:
#   ./scripts/build_library.sh ~/zims
#   ./scripts/build_library.sh /mnt/usb/zims  /data/library.xml
#
# The library file is created if it does not already exist.
# ZIM files already present in the library are updated in place (kiwix-manage
# handles duplicates by overwriting the existing entry).

set -euo pipefail

ZIM_DIR="${1:-}"
LIBRARY="${2:-library.xml}"

if [ -z "$ZIM_DIR" ]; then
    echo "Usage: $0 <zim_dir> [library.xml]" >&2
    exit 1
fi

if [ ! -d "$ZIM_DIR" ]; then
    echo "Error: directory not found: $ZIM_DIR" >&2
    exit 1
fi

mapfile -t ZIMS < <(find "$ZIM_DIR" -maxdepth 1 -name "*.zim" | sort)

if [ ${#ZIMS[@]} -eq 0 ]; then
    echo "No .zim files found in $ZIM_DIR" >&2
    exit 1
fi

# Locate kiwix-manage: prefer ./kiwix-tools/, then PATH.
if [ -x "kiwix-tools/kiwix-manage" ]; then
    KIWIX_MANAGE="kiwix-tools/kiwix-manage"
elif command -v kiwix-manage &>/dev/null; then
    KIWIX_MANAGE="kiwix-manage"
else
    echo "Error: kiwix-manage not found. Add it to PATH or place kiwix-tools/ next to this repo." >&2
    exit 1
fi

echo "Building $LIBRARY from ${#ZIMS[@]} ZIM file(s) in $ZIM_DIR ..."
echo ""

for zim in "${ZIMS[@]}"; do
    echo "  + $(basename "$zim")"
    "$KIWIX_MANAGE" "$LIBRARY" add "$zim"
done

echo ""
echo "[OK] $LIBRARY updated — ${#ZIMS[@]} ZIM file(s) registered."
