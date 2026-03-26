"""Server-side ZIM update management — zero-downtime ingest pipeline.

Handles ZIM file validation, version parsing, library.xml integration,
and the atomic index-then-swap strategy that keeps old content serving
while new content is being indexed.

CLI: ``offline-search-update``
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import settings
from .indexer import (
    get_index_stats,
    index_zim,
    load_library,
    prepare_database,
    remove_by_zim_path,
)
from .kiwix import restart_kiwix_server

logger = logging.getLogger(__name__)

# ZIM magic bytes: 0x44 0x49 0x4D 0x04  (ASCII "DIM" + 0x04)
ZIM_MAGIC = b"\x44\x49\x4d\x04"

# Regex to parse versioned ZIM filenames: basename_YYYY-MM
_VERSION_RE = re.compile(r"^(.+?)_(\d{4}-\d{2})$")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ZimInfo:
    base_name: str
    version: str
    filename: str
    zim_path: Path
    article_count: int = 0


@dataclass
class IngestResult:
    success: bool
    zim_info: ZimInfo
    replaced: ZimInfo | None = None
    articles_indexed: int = 0
    articles_removed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

def parse_zim_version(filename: str) -> tuple[str, str]:
    """Extract ``(base_name, version)`` from a ZIM filename stem.

    >>> parse_zim_version("devdocs_en_python_2026-01")
    ('devdocs_en_python', '2026-01')

    Raises ``ValueError`` if the filename doesn't match the expected pattern.
    """
    stem = Path(filename).stem
    m = _VERSION_RE.match(stem)
    if not m:
        raise ValueError(
            f"Cannot parse version from {filename!r}. "
            f"Expected pattern: <name>_YYYY-MM.zim"
        )
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_zim_file(path: Path) -> bool:
    """Check that *path* looks like a valid ZIM file (extension + magic bytes)."""
    if not path.is_file():
        return False
    if path.suffix.lower() != ".zim":
        return False
    try:
        with open(path, "rb") as f:
            header = f.read(4)
        return header == ZIM_MAGIC
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Installed ZIM queries
# ---------------------------------------------------------------------------

def get_installed_zims(library_xml: Path | None = None) -> list[ZimInfo]:
    """Parse library.xml and return a list of installed ZIMs with metadata."""
    lib_path = library_xml or Path(settings.library_xml)
    if not lib_path.exists():
        return []

    results: list[ZimInfo] = []
    stats = get_index_stats()
    source_counts = {s["name"]: s["count"] for s in stats.get("sources", [])}

    for entry in load_library(lib_path):
        zim_path: Path = entry["zim_path"]
        filename = zim_path.name
        try:
            base_name, version = parse_zim_version(filename)
        except ValueError:
            base_name = zim_path.stem
            version = "unknown"
        results.append(ZimInfo(
            base_name=base_name,
            version=version,
            filename=filename,
            zim_path=zim_path,
            article_count=source_counts.get(zim_path.stem, 0),
        ))
    return results


def find_older_version(
    base_name: str,
    library_xml: Path | None = None,
) -> ZimInfo | None:
    """Find an installed ZIM with the same base_name (i.e. an older version)."""
    for zim in get_installed_zims(library_xml):
        if zim.base_name == base_name:
            return zim
    return None


# ---------------------------------------------------------------------------
# kiwix-manage helpers
# ---------------------------------------------------------------------------

def _run_kiwix_manage(library_xml: Path, *args: str) -> subprocess.CompletedProcess:
    """Run kiwix-manage with the given arguments."""
    cmd = [settings.kiwix_manage, str(library_xml), *args]
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def kiwix_manage_add(library_xml: Path, zim_path: Path) -> bool:
    """Add a ZIM to library.xml via kiwix-manage."""
    result = _run_kiwix_manage(library_xml, "add", str(zim_path))
    if result.returncode != 0:
        logger.error("kiwix-manage add failed: %s", result.stderr)
        return False
    return True


def kiwix_manage_remove(library_xml: Path, zim_id: str) -> bool:
    """Remove a ZIM from library.xml via kiwix-manage."""
    result = _run_kiwix_manage(library_xml, "remove", zim_id)
    if result.returncode != 0:
        logger.error("kiwix-manage remove failed: %s", result.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Zero-downtime ingest pipeline
# ---------------------------------------------------------------------------

def ingest_zim(
    zim_path: Path,
    *,
    replace: bool = True,
    delete_old: bool = True,
    restart_kiwix: bool = True,
    library_xml: Path | None = None,
    db_path: Path | None = None,
) -> IngestResult:
    """Zero-downtime ZIM ingestion pipeline.

    1. Parse version info, find any existing older version
    2. Add new ZIM to library.xml (old + new coexist)
    3. Index the new ZIM into the database (old still serves searches)
    4. Atomic swap: remove old ZIM's rows from the database
    5. Remove old ZIM from library.xml
    6. Optionally delete old .zim file from disk
    7. Optionally restart kiwix-serve
    """
    lib_xml = library_xml or Path(settings.library_xml)
    db = db_path or settings.db_path
    errors: list[str] = []

    # --- Validate ---
    if not validate_zim_file(zim_path):
        return IngestResult(
            success=False,
            zim_info=ZimInfo("", "", zim_path.name, zim_path),
            errors=["Invalid ZIM file: bad magic bytes or extension"],
        )

    # --- Parse version ---
    try:
        base_name, version = parse_zim_version(zim_path.name)
    except ValueError as exc:
        return IngestResult(
            success=False,
            zim_info=ZimInfo("", "", zim_path.name, zim_path),
            errors=[str(exc)],
        )

    zim_info = ZimInfo(
        base_name=base_name,
        version=version,
        filename=zim_path.name,
        zim_path=zim_path,
    )

    # --- Find older version ---
    old_zim: ZimInfo | None = None
    if replace:
        old_zim = find_older_version(base_name, lib_xml)

    # --- Step 1: Add new ZIM to library.xml ---
    if not kiwix_manage_add(lib_xml, zim_path):
        errors.append("kiwix-manage add failed (continuing with indexing)")

    # --- Step 2: Index new ZIM (this is the slow part) ---
    conn = prepare_database(db, reset=False)
    try:
        articles_indexed = index_zim(
            conn, zim_path, zim_path.stem,
        )
        zim_info.article_count = articles_indexed

        # --- Step 3: Atomic swap — remove old rows ---
        articles_removed = 0
        if old_zim is not None and old_zim.zim_path != zim_path:
            articles_removed = remove_by_zim_path(conn, str(old_zim.zim_path))

            # --- Step 4: Remove old from library.xml ---
            # kiwix-manage remove uses the book ID, which is typically the stem
            if not kiwix_manage_remove(lib_xml, old_zim.zim_path.stem):
                errors.append("kiwix-manage remove of old ZIM failed")

            # --- Step 5: Delete old file ---
            if delete_old and old_zim.zim_path.exists():
                try:
                    old_zim.zim_path.unlink()
                    logger.info("Deleted old ZIM: %s", old_zim.zim_path)
                except OSError as exc:
                    errors.append(f"Failed to delete old ZIM: {exc}")
    finally:
        conn.close()

    # --- Step 6: Restart kiwix-serve ---
    if restart_kiwix:
        if not restart_kiwix_server():
            errors.append("kiwix-serve restart failed")

    return IngestResult(
        success=True,
        zim_info=zim_info,
        replaced=old_zim,
        articles_indexed=articles_indexed,
        articles_removed=articles_removed,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Manifest export
# ---------------------------------------------------------------------------

def export_manifest(library_xml: Path | None = None) -> list[dict]:
    """Export installed ZIMs as a JSON-serialisable manifest."""
    zims = get_installed_zims(library_xml)
    return [
        {
            "base_name": z.base_name,
            "version": z.version,
            "filename": z.filename,
            "article_count": z.article_count,
        }
        for z in zims
    ]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI: ``offline-search-update``"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Manage ZIM files in the offline search system.")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Ingest a ZIM file (zero-downtime)")
    p_ingest.add_argument("zim_path", type=Path, nargs="+", help="ZIM file(s) to ingest")
    p_ingest.add_argument("--no-replace", action="store_true", help="Don't replace older versions")
    p_ingest.add_argument("--keep-old", action="store_true", help="Keep old ZIM file on disk")
    p_ingest.add_argument("--no-restart", action="store_true", help="Don't restart kiwix-serve")

    # list
    sub.add_parser("list", help="List installed ZIMs")

    # remove
    p_remove = sub.add_parser("remove", help="Remove a ZIM from the library and index")
    p_remove.add_argument("filename", help="ZIM filename to remove")
    p_remove.add_argument("--keep-file", action="store_true", help="Keep the .zim file on disk")

    # manifest
    p_manifest = sub.add_parser("manifest", help="Export a JSON manifest of installed ZIMs")
    p_manifest.add_argument("--output", type=Path, help="Write manifest to file (default: stdout)")

    args = parser.parse_args()

    if args.command == "ingest":
        for zp in args.zim_path:
            result = ingest_zim(
                zp,
                replace=not args.no_replace,
                delete_old=not args.keep_old,
                restart_kiwix=not args.no_restart,
            )
            if result.success:
                logger.info(
                    "Ingested %s: %d articles indexed, %d removed",
                    result.zim_info.filename,
                    result.articles_indexed,
                    result.articles_removed,
                )
            else:
                logger.error("Failed to ingest %s: %s", zp, result.errors)

    elif args.command == "list":
        zims = get_installed_zims()
        if not zims:
            print("No ZIMs installed.")
            return
        for z in zims:
            print(f"  {z.filename}  (base={z.base_name}, version={z.version}, articles={z.article_count})")

    elif args.command == "remove":
        lib_xml = Path(settings.library_xml)
        db = settings.db_path
        # Find the ZIM
        zims = get_installed_zims(lib_xml)
        target = next((z for z in zims if z.filename == args.filename), None)
        if not target:
            logger.error("ZIM %s not found in library", args.filename)
            return
        # Remove from index
        conn = prepare_database(db, reset=False)
        try:
            removed = remove_by_zim_path(conn, str(target.zim_path))
            logger.info("Removed %d documents from index", removed)
        finally:
            conn.close()
        # Remove from library.xml
        kiwix_manage_remove(lib_xml, target.zim_path.stem)
        # Delete file
        if not args.keep_file and target.zim_path.exists():
            target.zim_path.unlink()
            logger.info("Deleted %s", target.zim_path)

    elif args.command == "manifest":
        manifest = export_manifest()
        output = json.dumps(manifest, indent=2)
        if args.output:
            args.output.write_text(output, encoding="utf-8")
            logger.info("Manifest written to %s", args.output)
        else:
            print(output)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
