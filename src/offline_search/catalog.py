"""Online Kiwix catalog client — check for updates, download, and push ZIMs.

Supports one-shot CLI commands and a configurable watch/daemon mode.

CLI: ``offline-search-catalog``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import httpx

from .config import settings
from .updater import ZimInfo, parse_zim_version

logger = logging.getLogger(__name__)

# OPDS Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPDS_NS = "urn:opds:catalog:2016"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CatalogEntry:
    name: str
    version: str
    title: str
    description: str
    url: str
    size: int
    language: str
    sha256: str


@dataclass
class UpdateAvailable:
    installed: ZimInfo
    available: CatalogEntry


@dataclass
class WatchConfig:
    interval_hours: float = 24
    auto_download: bool = False
    auto_push: bool = False
    push_url: str | None = None
    push_api_key: str | None = None
    dest_dir: Path = field(default_factory=lambda: Path("./downloads"))
    notify_command: str | None = None
    catalog_url: str = "https://library.kiwix.org/catalog/search"
    verify_tls: bool = True
    dry_run: bool = False


# ---------------------------------------------------------------------------
# OPDS catalog parsing
# ---------------------------------------------------------------------------

def fetch_catalog(
    query: str | None = None,
    *,
    name: str | None = None,
    catalog_url: str | None = None,
    verify_tls: bool = True,
    timeout: float = 30.0,
) -> list[CatalogEntry]:
    """Fetch and parse the Kiwix OPDS catalog. Returns a list of entries.

    Use *query* for free-text search (``q=`` param) or *name* for exact
    ZIM base-name lookup (``name=`` param).  The Kiwix OPDS endpoint only
    matches base-names via ``name=``; ``q=`` performs full-text search and
    may return zero results for dotted base-names.
    """
    base_url = catalog_url or settings.catalog_url
    params = {}
    if name:
        params["name"] = name
    elif query:
        params["q"] = query

    with httpx.Client(verify=verify_tls, timeout=timeout) as client:
        resp = client.get(base_url, params=params)
        resp.raise_for_status()

    return _parse_opds_feed(resp.text)


def _parse_opds_feed(xml_text: str) -> list[CatalogEntry]:
    """Parse an OPDS Atom feed into CatalogEntry objects."""
    root = ElementTree.fromstring(xml_text)
    entries: list[CatalogEntry] = []

    for entry_el in root.findall(f"{{{_ATOM_NS}}}entry"):
        title = _atom_text(entry_el, "title") or ""
        summary = _atom_text(entry_el, "summary") or ""
        language = _atom_text(entry_el, f"{{{_OPDS_NS}}}language") or _atom_text(
            entry_el, "language") or ""

        # Find the ZIM download link
        url = ""
        size = 0
        sha256 = ""
        for link in entry_el.findall(f"{{{_ATOM_NS}}}link"):
            link_type = link.get("type", "")
            if "application/x-zim" in link_type or link.get("href", "").endswith(".zim"):
                url = link.get("href", "")
                try:
                    size = int(link.get("length", "0"))
                except ValueError:
                    size = 0
                break

        # Extract name/version from the URL filename or entry ID
        name = ""
        version = ""
        if url:
            filename_stem = Path(url.split("?")[0]).stem
            try:
                name, version = parse_zim_version(filename_stem)
            except ValueError:
                name = filename_stem
                version = ""

        # Look for checksum in various places
        for link in entry_el.findall(f"{{{_ATOM_NS}}}link"):
            if link.get("rel") == "http://opds-spec.org/acquisition" or "checksum" in link.get("rel", ""):
                sha256 = link.get("sha256", "")

        entries.append(CatalogEntry(
            name=name,
            version=version,
            title=title,
            description=summary,
            url=url,
            size=size,
            language=language,
            sha256=sha256,
        ))

    return entries


def _atom_text(el: ElementTree.Element, tag: str) -> str | None:
    """Get text content of a child element."""
    # Try with namespace first, then without
    child = el.find(f"{{{_ATOM_NS}}}{tag}")
    if child is None:
        child = el.find(tag)
    return child.text if child is not None else None


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

def compare_versions(
    installed: list[ZimInfo],
    catalog: list[CatalogEntry],
) -> list[UpdateAvailable]:
    """Find catalog entries that are newer than installed versions."""
    installed_map = {z.base_name: z for z in installed}
    updates: list[UpdateAvailable] = []

    for entry in catalog:
        if not entry.name or not entry.version:
            continue
        if entry.name in installed_map:
            current = installed_map[entry.name]
            if entry.version > current.version:
                updates.append(UpdateAvailable(
                    installed=current, available=entry))

    return updates


def check_updates_for_installed(
    installed: list[ZimInfo],
    *,
    catalog_url: str | None = None,
    verify_tls: bool = True,
) -> list[UpdateAvailable]:
    """Query the catalog per installed ZIM and return available updates.

    Instead of a single parameterless fetch (which only returns the first page
    of ~50 results), this queries the catalog individually for each installed
    ZIM's base_name, ensuring updates are found even if they've fallen off
    the first page.
    """
    updates: list[UpdateAvailable] = []
    for zim in installed:
        entries = fetch_catalog(
            name=zim.base_name,
            catalog_url=catalog_url,
            verify_tls=verify_tls,
        )
        for entry in entries:
            if entry.name == zim.base_name and entry.version > zim.version:
                updates.append(UpdateAvailable(installed=zim, available=entry))
                break
    return updates


# ---------------------------------------------------------------------------
# Download & integrity
# ---------------------------------------------------------------------------

def verify_checksum(path: Path, expected_sha256: str) -> bool:
    """Verify SHA-256 checksum of a file."""
    if not expected_sha256:
        logger.warning(
            "No checksum provided for %s, skipping verification", path.name)
        return True

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    actual = h.hexdigest()
    if actual != expected_sha256.lower():
        logger.error(
            "Checksum mismatch for %s: expected %s, got %s",
            path.name, expected_sha256, actual,
        )
        return False
    return True


def _resolve_metalink(url: str, *, verify_tls: bool = True, timeout: float = 30.0) -> tuple[str, str]:
    """Resolve a .meta4 metalink URL to (direct_zim_url, sha256).

    Parses the Metalink XML and returns the highest-priority mirror URL
    and the SHA-256 hash if present.
    """
    _METALINK_NS = "urn:ietf:params:xml:ns:metalink"

    resp = httpx.get(url, verify=verify_tls, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()

    root = ElementTree.fromstring(resp.text)
    file_el = root.find(f"{{{_METALINK_NS}}}file")
    if file_el is None:
        raise ValueError(f"No <file> element in metalink: {url}")

    # Extract SHA-256 hash
    sha256 = ""
    for hash_el in file_el.findall(f"{{{_METALINK_NS}}}hash"):
        if hash_el.get("type") == "sha-256":
            sha256 = (hash_el.text or "").strip()

    # Pick the highest-priority (lowest number) mirror URL
    mirrors: list[tuple[int, str]] = []
    for url_el in file_el.findall(f"{{{_METALINK_NS}}}url"):
        priority = int(url_el.get("priority", "99"))
        mirrors.append((priority, (url_el.text or "").strip()))

    if not mirrors:
        raise ValueError(f"No mirror URLs in metalink: {url}")

    mirrors.sort(key=lambda x: x[0])
    return mirrors[0][1], sha256


def download_zim(
    entry: CatalogEntry,
    dest_dir: Path,
    *,
    progress_cb: object | None = None,
    verify_tls: bool = True,
    verify_checksum_flag: bool = True,
    timeout: float = 300.0,
) -> Path:
    """Stream-download a ZIM file with optional SHA-256 verification.

    Returns the path to the downloaded file.
    Raises ``ValueError`` on checksum mismatch, ``httpx.HTTPError`` on network failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    download_url = entry.url
    sha256 = entry.sha256

    # Resolve metalink (.meta4) URLs to actual ZIM mirror URLs
    if download_url.endswith(".meta4"):
        logger.info("Resolving metalink %s", download_url)
        download_url, metalink_sha256 = _resolve_metalink(
            download_url, verify_tls=verify_tls)
        if metalink_sha256 and not sha256:
            sha256 = metalink_sha256
        logger.info("Resolved to %s", download_url)

    filename = download_url.split("/")[-1].split("?")[0]
    if not filename.endswith(".zim"):
        filename = f"{entry.name}_{entry.version}.zim"
    dest = dest_dir / filename

    logger.info("Downloading %s -> %s", download_url, dest)

    with httpx.Client(verify=verify_tls, timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)

    if verify_checksum_flag and sha256:
        if not verify_checksum(dest, sha256):
            dest.unlink(missing_ok=True)
            raise ValueError(f"Checksum verification failed for {filename}")

    logger.info("Download complete: %s", dest)
    return dest


# ---------------------------------------------------------------------------
# Push to server
# ---------------------------------------------------------------------------

def push_to_server(
    zim_path: Path,
    server_url: str,
    *,
    api_key: str | None = None,
    verify_tls: bool = True,
    timeout: float = 1800.0,
) -> bool:
    """Upload a ZIM file to a remote offline-search server."""
    upload_url = f"{server_url.rstrip('/')}/zim/upload"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.info("Pushing %s -> %s", zim_path.name, upload_url)

    with httpx.Client(verify=verify_tls, timeout=timeout) as client:
        with open(zim_path, "rb") as f:
            resp = client.post(
                upload_url,
                files={"file": (zim_path.name, f, "application/octet-stream")},
                headers=headers,
            )

    if resp.status_code != 200:
        logger.error("Push failed (%d): %s", resp.status_code, resp.text)
        return False

    logger.info("Push successful: %s", resp.json())
    return True


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def export_manifest(installed: list[ZimInfo], path: Path) -> None:
    """Write a JSON manifest of installed ZIMs."""
    data = [
        {"base_name": z.base_name, "version": z.version, "filename": z.filename}
        for z in installed
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Manifest written to %s", path)


def load_manifest(path: Path) -> list[ZimInfo]:
    """Load a JSON manifest into ZimInfo objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        ZimInfo(
            base_name=e["base_name"],
            version=e["version"],
            filename=e.get("filename", ""),
            zim_path=Path(e.get("filename", "")),
        )
        for e in data
    ]


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

def watch(config: WatchConfig, manifest_path: Path) -> None:
    """Long-running loop: check for updates, download, and optionally push."""
    logger.info(
        "Watch mode started (interval=%sh, dry_run=%s)",
        config.interval_hours, config.dry_run,
    )

    while True:
        try:
            _watch_tick(config, manifest_path)
        except Exception:
            logger.exception("Watch tick failed")

        interval_seconds = config.interval_hours * 3600
        logger.info("Sleeping %.0f seconds until next check \u2026",
                    interval_seconds)
        time.sleep(interval_seconds)


def _watch_tick(config: WatchConfig, manifest_path: Path) -> None:
    """Single iteration of the watch loop."""
    # Load current state
    if manifest_path.exists():
        installed = load_manifest(manifest_path)
    else:
        installed = []

    # Fetch catalog per installed ZIM (avoids first-page truncation)
    updates = check_updates_for_installed(
        installed,
        catalog_url=config.catalog_url,
        verify_tls=config.verify_tls,
    )

    if not updates:
        logger.info("No updates available.")
        return

    logger.info("Found %d update(s):", len(updates))
    for u in updates:
        logger.info(
            "  %s: %s -> %s", u.installed.base_name, u.installed.version, u.available.version,
        )

    if config.dry_run:
        logger.info("[DRY RUN] Would download %d update(s)", len(updates))
        return

    if not config.auto_download:
        logger.info("Auto-download disabled. Run 'catalog download' manually.")
        return

    for u in updates:
        try:
            dest = download_zim(
                u.available,
                config.dest_dir,
                verify_tls=config.verify_tls,
            )
        except Exception:
            logger.exception("Failed to download %s", u.available.name)
            continue

        if config.auto_push and config.push_url:
            push_to_server(
                dest, config.push_url, api_key=config.push_api_key, verify_tls=config.verify_tls)

    # Run notify command if configured
    if config.notify_command:
        import subprocess
        try:
            subprocess.run(config.notify_command, shell=True,
                           check=False, timeout=30)
        except Exception:
            logger.exception("Notify command failed")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI: ``offline-search-catalog``"""
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Kiwix catalog client for offline-search.")
    sub = parser.add_subparsers(dest="command")

    # check
    p_check = sub.add_parser("check", help="Check for available updates")
    p_check.add_argument("--manifest", type=Path, help="Path to manifest file")
    p_check.add_argument("--server", type=str,
                         help="Server URL to query manifest from")
    p_check.add_argument("--catalog-url", type=str,
                         help="Override catalog URL")

    # search
    p_search = sub.add_parser("search", help="Search the Kiwix catalog")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--catalog-url", type=str,
                          help="Override catalog URL")

    # download
    p_download = sub.add_parser(
        "download", help="Download a ZIM from the catalog")
    p_download.add_argument("name", help="ZIM name to download")
    p_download.add_argument(
        "--dest", type=Path, default=Path("./downloads"), help="Download directory")
    p_download.add_argument(
        "--no-verify", action="store_true", help="Skip checksum verification")
    p_download.add_argument("--catalog-url", type=str,
                            help="Override catalog URL")

    # update
    p_update = sub.add_parser("update", help="Download all available updates")
    p_update.add_argument("--manifest", type=Path,
                          help="Path to manifest file")
    p_update.add_argument(
        "--dest", type=Path, default=Path("./downloads"), help="Download directory")
    p_update.add_argument("--push", type=str,
                          help="Push to server URL after download")
    p_update.add_argument("--api-key", type=str, help="API key for push")
    p_update.add_argument("--dry-run", action="store_true",
                          help="Show what would be done")
    p_update.add_argument("--catalog-url", type=str,
                          help="Override catalog URL")

    # watch
    p_watch = sub.add_parser("watch", help="Watch for updates (daemon mode)")
    p_watch.add_argument("--config", type=Path,
                         help="JSON config file for watch mode")
    p_watch.add_argument("--interval", type=float,
                         default=24, help="Check interval in hours")
    p_watch.add_argument("--auto-download", action="store_true")
    p_watch.add_argument("--auto-push", type=str,
                         help="Auto-push to server URL")
    p_watch.add_argument("--api-key", type=str)
    p_watch.add_argument("--notify-command", type=str)
    p_watch.add_argument("--manifest", type=Path)
    p_watch.add_argument("--dry-run", action="store_true")
    p_watch.add_argument("--catalog-url", type=str)

    args = parser.parse_args()

    if args.command == "check":
        manifest_path = args.manifest or settings.manifest_path
        if manifest_path.exists():
            installed = load_manifest(manifest_path)
        else:
            from .updater import get_installed_zims
            installed = get_installed_zims()

        catalog_url = getattr(args, "catalog_url", None)
        updates = check_updates_for_installed(
            installed, catalog_url=catalog_url)

        if not updates:
            print("All ZIMs are up to date.")
        else:
            print(f"Found {len(updates)} update(s):")
            for u in updates:
                print(
                    f"  {u.installed.base_name}: {u.installed.version} -> {u.available.version}")

    elif args.command == "search":
        catalog_url = getattr(args, "catalog_url", None)
        entries = fetch_catalog(query=args.query, catalog_url=catalog_url)
        if not entries:
            print("No results found.")
        else:
            for e in entries:
                print(f"  {e.name} ({e.version}) \u2014 {e.title}")
                if e.description:
                    print(f"    {e.description[:100]}")

    elif args.command == "download":
        catalog_url = getattr(args, "catalog_url", None)
        entries = fetch_catalog(query=args.name, catalog_url=catalog_url)
        match = next((e for e in entries if e.name == args.name), None)
        if not match:
            match = entries[0] if entries else None
        if not match:
            logger.error("No catalog entry found for %s", args.name)
            return
        download_zim(match, args.dest, verify_checksum_flag=not args.no_verify)

    elif args.command == "update":
        manifest_path = args.manifest or settings.manifest_path
        if manifest_path.exists():
            installed = load_manifest(manifest_path)
        else:
            from .updater import get_installed_zims
            installed = get_installed_zims()

        catalog_url = getattr(args, "catalog_url", None)
        updates = check_updates_for_installed(
            installed, catalog_url=catalog_url)

        if not updates:
            print("All ZIMs are up to date.")
            return

        if args.dry_run:
            print(f"[DRY RUN] Would download {len(updates)} update(s):")
            for u in updates:
                print(
                    f"  {u.installed.base_name}: {u.installed.version} -> {u.available.version}")
            return

        for u in updates:
            try:
                dest = download_zim(u.available, args.dest)
            except Exception:
                logger.exception("Failed to download %s", u.available.name)
                continue

            if args.push:
                push_to_server(dest, args.push, api_key=args.api_key)

    elif args.command == "watch":
        manifest_path = args.manifest or settings.manifest_path
        config = WatchConfig(
            interval_hours=args.interval,
            auto_download=args.auto_download,
            auto_push=bool(args.auto_push),
            push_url=args.auto_push,
            push_api_key=args.api_key,
            notify_command=args.notify_command,
            dry_run=args.dry_run,
            catalog_url=args.catalog_url or settings.catalog_url,
        )
        watch(config, manifest_path)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
