"""Kuro Wuthering Waves Android JSON adapter."""

import argparse
import json
import time
from pathlib import Path

from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.android.kuro_apk_organizer import (
    KuroApkCollection,
    KuroApkOrganizationError,
    organize_kuro_apk,
)
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error, read_small


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> KuroApkCollection:
    """Collect one official Wuthering Waves APK without writing a record."""
    manifest_url = endpoint("kuro", game_id)
    data = json.loads(read_small(f"{manifest_url}?_t={int(time.time() // 60)}", timeout))
    resolved_version = version or data.get("version")
    errors = []
    for url in (data.get("primary"), data.get("secondary"), data.get("third")):
        if not isinstance(url, str):
            continue
        try:
            record = fetch_record(
                "kuro", game_id, url, version=resolved_version,
                version_code=version_code, timeout=timeout,
            )
            if record.get("platform") is None:
                record = {**record, "platform": "android"}
            return KuroApkCollection(
                source_url=manifest_url,
                record=record,
                source_name="Kuro official Wuthering Waves Android manifest",
            )
        except AdapterError as error:
            errors.append(str(error))
    raise AdapterError("；".join(errors) or "清单中没有 APK URL")


def discover_collection(collection: KuroApkCollection, output_root: Path) -> Path:
    """Organize, validate, and safely persist one collected APK."""
    try:
        record = organize_kuro_apk(collection)
        return persist_v2_record(record, output_root)
    except (KuroApkOrganizationError, VersionStoreError) as error:
        raise AdapterError(str(error)) from error


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="鸣潮 Android JSON 适配器")
    add_options(parser)
    args = parser.parse_args()
    try:
        path = discover("wuwa", args.output_root, args.timeout, args.version, args.version_code)
        print(path.resolve())
        return 0
    except (AdapterError, json.JSONDecodeError) as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
