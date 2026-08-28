"""Hypergryph launcher Android adapter."""

import argparse
import re
from pathlib import Path

from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.android.hypergryph_apk_organizer import (
    HypergryphApkCollection,
    HypergryphApkOrganizationError,
    organize_hypergryph_apk,
)
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error


GAMES = ("endfield", "arknights")


def arknights_version(filename: str) -> str | None:
    match = re.search(r"arknights-hg-(\d{4})\.apk$", filename, re.I)
    if not match:
        return None
    code = match.group(1)
    return f"{code[0]}.{code[1]}.{code[2:]}"


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> HypergryphApkCollection:
    """Collect one official Hypergryph launcher APK without writing a record."""
    source_url = endpoint("hypergryph", game_id)
    record = fetch_record(
        "hypergryph", game_id, source_url,
        version=version, version_code=version_code, timeout=timeout,
        platform=None,
        version_parser=arknights_version if game_id == "arknights" else None,
    )
    if record.get("platform") is None:
        record = {**record, "platform": "android"}
    return HypergryphApkCollection(source_url=source_url, record=record)


def discover_collection(collection: HypergryphApkCollection, output_root: Path) -> Path:
    """Organize, validate, and safely persist one collected APK."""
    try:
        record = organize_hypergryph_apk(collection)
        return persist_v2_record(record, output_root)
    except (HypergryphApkOrganizationError, VersionStoreError) as error:
        raise AdapterError(str(error)) from error


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="鹰角 launcher Android 适配器")
    parser.add_argument("game_id", choices=GAMES)
    add_options(parser)
    args = parser.parse_args()
    try:
        path = discover(
            args.game_id, args.output_root, args.timeout,
            args.version, args.version_code,
        )
        print(path.resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
