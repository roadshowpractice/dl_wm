#!/usr/bin/env python
"""Remove stale metadata/index entries and partial downloads for a URL."""

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure local imports work when script is run directly
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
LIB_DIR = ROOT_DIR / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.append(str(LIB_DIR))

from tasks_lib import load_app_config  # noqa: E402




def resolve_repo_path(path_value: str) -> str:
    """Resolve a relative path from repository root."""
    if not path_value:
        return str(ROOT_DIR)
    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        return expanded
    return str((ROOT_DIR / expanded).resolve())

PARTIAL_SUFFIXES = (
    ".part",
    ".ytdl",
    ".tmp",
)


def load_platform_output_dir() -> Path | None:
    """Read output_dir for current OS from conf/config.json."""
    config_path = ROOT_DIR / "conf" / "config.json"
    if not config_path.exists():
        return None

    with config_path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)

    os_name = platform.system()
    platform_cfg = config.get(os_name, {})
    output_dir = platform_cfg.get("output_dir") or platform_cfg.get("target_usb")
    if not output_dir:
        return None
    return Path(resolve_repo_path(output_dir)).resolve()


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    return parts[-1] if parts else ""


def remove_matching_index_lines(index_path: Path, url: str, dry_run: bool) -> tuple[int, list[dict]]:
    if not index_path.exists():
        return 0, []

    kept: list[str] = []
    removed_records: list[dict] = []

    with index_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            record_text = line.strip()
            if not record_text:
                continue
            try:
                record = json.loads(record_text)
            except json.JSONDecodeError:
                kept.append(line)
                continue

            if record.get("url") == url:
                removed_records.append(record)
            else:
                kept.append(line)

    if removed_records and not dry_run:
        with index_path.open("w", encoding="utf-8") as fh:
            fh.writelines(kept)

    return len(removed_records), removed_records


def find_metadata_files_for_url(metadata_dir: Path, url: str) -> tuple[list[Path], list[dict]]:
    candidates: list[Path] = []
    metadata_records: list[dict] = []
    for path in metadata_dir.glob("*.json"):
        if path.name == "index.jsonl":
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(data, dict) and data.get("url") == url:
            candidates.append(path)
            metadata_records.append(data)

    return candidates, metadata_records


def collect_tokens_from_records(records: list[dict]) -> set[str]:
    tokens: set[str] = set()
    token_fields = (
        "id",
        "display_id",
        "shortcode",
        "webpage_url_basename",
        "upload_date",
        "uploader",
        "uploader_id",
        "uploader_url",
        "title",
        "fulltitle",
    )

    for record in records:
        for field in token_fields:
            value = record.get(field)
            if not value:
                continue
            token = str(value).strip()
            if token:
                tokens.add(token)
                tokens.add(token.replace(" ", "_"))

    return tokens


def find_output_json_files_for_url(output_dir: Path, url: str) -> list[Path]:
    matches: list[Path] = []
    if not output_dir.exists():
        return matches

    for path in output_dir.rglob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(data, dict) and data.get("url") == url:
            matches.append(path)

    return matches


def remove_paths(paths: list[Path], dry_run: bool) -> list[Path]:
    removed: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if dry_run:
            removed.append(path)
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed


def collect_partial_candidates(output_dir: Path, tokens: set[str]) -> list[Path]:
    matches: list[Path] = []
    if not output_dir.exists() or not tokens:
        return matches

    lowered_tokens = {token.lower() for token in tokens if token}

    for root, _, files in os.walk(output_dir):
        for filename in files:
            lowered_name = filename.lower()
            if not lowered_name.endswith(PARTIAL_SUFFIXES):
                continue
            if any(token in lowered_name for token in lowered_tokens):
                matches.append(Path(root) / filename)

    return matches


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean metadata/index and partial downloads for a failed URL"
    )
    parser.add_argument("url", help="Source URL to clean")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without deleting files",
    )
    parser.add_argument(
        "--skip-partials",
        action="store_true",
        help="Skip searching/removing partial download files",
    )
    args = parser.parse_args()

    app_config = load_app_config()
    metadata_dir = Path(resolve_repo_path(app_config.get("metadata_dir", "./metadata"))).resolve()
    metadata_dir.mkdir(parents=True, exist_ok=True)

    index_path = metadata_dir / "index.jsonl"
    removed_count, removed_records = remove_matching_index_lines(index_path, args.url, args.dry_run)

    metadata_files, metadata_records = find_metadata_files_for_url(metadata_dir, args.url)

    # Include metadata files named by index entries even if unreadable.
    for record in removed_records:
        metadata_name = record.get("metadata_file")
        if metadata_name:
            metadata_path = metadata_dir / metadata_name
            if metadata_path not in metadata_files:
                metadata_files.append(metadata_path)

    removed_metadata_files = remove_paths(metadata_files, args.dry_run)

    raw_dir = metadata_dir / "raw"
    raw_tokens = {slug_from_url(args.url)}
    raw_tokens.update(collect_tokens_from_records(metadata_records))
    for record in removed_records:
        for key in ("id", "shortcode"):
            value = record.get(key)
            if value:
                raw_tokens.add(str(value))

    if raw_dir.exists():
        raw_candidates = [
            p
            for p in raw_dir.iterdir()
            if p.is_file() and any(token and token in p.name for token in raw_tokens)
        ]
    else:
        raw_candidates = []

    removed_raw_files = remove_paths(raw_candidates, args.dry_run)

    output_sidecars: list[Path] = []
    removed_partials: list[Path] = []
    if not args.skip_partials:
        output_dir = load_platform_output_dir()
        partial_tokens = set(raw_tokens)

        # Add stem names so a metadata filename token can match partial files.
        for metadata_path in removed_metadata_files:
            partial_tokens.add(metadata_path.stem)

        if output_dir:
            output_sidecars = find_output_json_files_for_url(output_dir, args.url)
            for sidecar in output_sidecars:
                partial_tokens.add(sidecar.stem)

            partial_candidates = collect_partial_candidates(output_dir, partial_tokens)
            removed_partials = remove_paths(partial_candidates, args.dry_run)
            output_sidecars = remove_paths(output_sidecars, args.dry_run)

    action = "Would remove" if args.dry_run else "Removed"
    print(f"{action} {removed_count} index entry(ies) from {index_path}")
    print(f"{action} {len(removed_metadata_files)} metadata file(s)")
    print(f"{action} {len(removed_raw_files)} raw metadata file(s)")
    if args.skip_partials:
        print("Skipped partial download cleanup (--skip-partials)")
    else:
        print(f"{action} {len(output_sidecars)} output metadata sidecar file(s)")
        print(f"{action} {len(removed_partials)} partial download file(s)")

    for label, items in (
        ("metadata", removed_metadata_files),
        ("raw", removed_raw_files),
        ("output-json", output_sidecars),
        ("partial", removed_partials),
    ):
        for path in items:
            print(f"  - {label}: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
