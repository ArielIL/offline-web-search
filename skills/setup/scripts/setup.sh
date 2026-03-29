#!/usr/bin/env bash
# Setup script for offline-search: install kiwix-tools, download ZIMs, build index.
#
# Usage:
#   ./setup.sh                    # Interactive: detect platform, prompt for ZIMs
#   ./setup.sh --zims "python,javascript,bash"  # Download specific ZIMs
#   ./setup.sh --kiwix-only       # Only install kiwix-tools
#   ./setup.sh --index-only       # Only rebuild the index (assumes ZIMs + library.xml exist)
set -euo pipefail

_tmpdir=""
trap 'rm -rf "$_tmpdir"' EXIT

PROJECT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
BIN_DIR="$PROJECT_DIR/bin"
DATA_DIR="$PROJECT_DIR/data"
ZIM_DIR="$DATA_DIR/zims"
LIBRARY_XML="$DATA_DIR/library.xml"
DB_PATH="$DATA_DIR/offline_index.sqlite"
KIWIX_TOOLS_BASE_URL="https://download.kiwix.org/release/kiwix-tools/"

# ---------- helpers ----------

info()  { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; exit 1; }

detect_platform() {
    local os arch
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Darwin)
            case "$arch" in
                arm64) echo "macos-arm64" ;;
                *)     echo "macos-x86_64" ;;
            esac ;;
        Linux)
            case "$arch" in
                x86_64)  echo "linux-x86_64" ;;
                aarch64) echo "linux-aarch64" ;;
                *)       error "Unsupported Linux architecture: $arch" ;;
            esac ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "win-x86_64" ;;
        *)
            error "Unsupported OS: $os" ;;
    esac
}

latest_kiwix_version() {
    local platform="$1"
    curl -sL "$KIWIX_TOOLS_BASE_URL" \
        | grep -oE "kiwix-tools_${platform}-[0-9]+\.[0-9]+\.[0-9]+\.tar\.gz" \
        | sort -V | tail -1
}

# ---------- install kiwix-tools ----------

install_kiwix_tools() {
    if [ -x "$BIN_DIR/kiwix-serve" ] && [ -x "$BIN_DIR/kiwix-manage" ]; then
        info "kiwix-tools already installed in $BIN_DIR"
        return 0
    fi

    local platform tarball url tmpdir
    platform="$(detect_platform)"
    info "Detected platform: $platform"

    tarball="$(latest_kiwix_version "$platform")"
    [ -n "$tarball" ] || error "Could not find kiwix-tools release for $platform"

    url="${KIWIX_TOOLS_BASE_URL}${tarball}"
    info "Downloading $url ..."

    _tmpdir="$(mktemp -d)"

    curl -L "$url" -o "$_tmpdir/kiwix-tools.tar.gz"
    tar xzf "$_tmpdir/kiwix-tools.tar.gz" -C "$_tmpdir"

    mkdir -p "$BIN_DIR"
    # The tarball extracts into a named directory
    local extracted
    extracted="$(find "$_tmpdir" -name 'kiwix-serve' -type f | head -1)"
    [ -n "$extracted" ] || error "kiwix-serve not found in archive"
    local src_dir
    src_dir="$(dirname "$extracted")"

    cp "$src_dir/kiwix-serve" "$src_dir/kiwix-manage" "$BIN_DIR/"
    chmod +x "$BIN_DIR/kiwix-serve" "$BIN_DIR/kiwix-manage"
    info "Installed kiwix-serve and kiwix-manage to $BIN_DIR/"
}

# ---------- download ZIMs ----------

download_zims() {
    local zim_list="$1"
    mkdir -p "$ZIM_DIR"

    IFS=',' read -ra ZIMS <<< "$zim_list"
    for zim_name in "${ZIMS[@]}"; do
        zim_name="$(echo "$zim_name" | xargs)"  # trim whitespace
        [ -n "$zim_name" ] || continue

        # Check if already downloaded
        if ls "$ZIM_DIR"/*"${zim_name}"*.zim 1>/dev/null 2>&1; then
            info "ZIM for '$zim_name' already exists, skipping"
            continue
        fi

        info "Downloading ZIM: $zim_name ..."
        uv run offline-search-catalog download "$zim_name" --dest "$ZIM_DIR" || {
            echo "  Warning: failed to download '$zim_name' — try a broader name (e.g. 'python' instead of 'devdocs_en_python')"
        }
    done
}

# ---------- build library.xml ----------

build_library() {
    local kiwix_manage="$BIN_DIR/kiwix-manage"
    [ -x "$kiwix_manage" ] || error "kiwix-manage not found at $kiwix_manage"

    # Remove stale library.xml — kiwix-manage add fails if the file references missing ZIMs
    rm -f "$LIBRARY_XML"

    local count=0
    for zim in "$ZIM_DIR"/*.zim; do
        [ -f "$zim" ] || continue
        info "Adding to library: $(basename "$zim")"
        "$kiwix_manage" "$LIBRARY_XML" add "$zim" 2>/dev/null || true
        count=$((count + 1))
    done

    [ "$count" -gt 0 ] || error "No ZIM files found in $ZIM_DIR"
    info "library.xml built with $count ZIM(s)"
}

# ---------- build index ----------

build_index() {
    [ -f "$LIBRARY_XML" ] || error "library.xml not found at $LIBRARY_XML — run setup first"

    info "Building FTS5 search index ..."
    OFFLINE_SEARCH_KIWIX_MANAGE="$BIN_DIR/kiwix-manage" \
        uv run offline-search-index --library "$LIBRARY_XML" --output "$DB_PATH"
    info "Index built at $DB_PATH"
}

# ---------- write .env ----------

write_env() {
    local env_file="$PROJECT_DIR/.env"
    if [ -f "$env_file" ]; then
        info ".env already exists, not overwriting"
        return 0
    fi

    cat > "$env_file" <<EOF
OFFLINE_SEARCH_DB_PATH=$DB_PATH
OFFLINE_SEARCH_KIWIX_SERVE=$BIN_DIR/kiwix-serve
OFFLINE_SEARCH_KIWIX_MANAGE=$BIN_DIR/kiwix-manage
OFFLINE_SEARCH_ZIM_DIR=$ZIM_DIR
EOF
    info "Wrote .env with default paths"
}

# ---------- main ----------

main() {
    local zims="" kiwix_only=false index_only=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --zims)        zims="$2"; shift 2 ;;
            --kiwix-only)  kiwix_only=true; shift ;;
            --index-only)  index_only=true; shift ;;
            -h|--help)
                echo "Usage: setup.sh [--zims 'python,javascript,...'] [--kiwix-only] [--index-only]"
                exit 0 ;;
            *) error "Unknown option: $1" ;;
        esac
    done

    if $index_only; then
        build_library
        build_index
        return
    fi

    install_kiwix_tools

    if $kiwix_only; then
        return
    fi

    if [ -n "$zims" ]; then
        download_zims "$zims"
    fi

    # Only build library/index if we have ZIM files
    if ls "$ZIM_DIR"/*.zim 1>/dev/null 2>&1; then
        build_library
        build_index
        write_env
        info "Setup complete! Run 'uv run offline-search-mcp' to start."
    else
        write_env
        info "Kiwix tools installed. Download ZIMs with:"
        echo "  uv run offline-search-catalog search <topic>"
        echo "  uv run offline-search-catalog download <name> --dest $ZIM_DIR"
        echo "Then re-run: ./skills/setup/scripts/setup.sh --index-only"
    fi
}

main "$@"
