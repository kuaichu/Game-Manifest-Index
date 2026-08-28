"""Perfect World gameDownload.js Android adapter."""

import argparse
import json
import re
from pathlib import Path

from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.apk_manifest import remote_apk_version
from url_adapters.android.perfectworld_apk_organizer import (
    PerfectWorldApkCollection,
    PerfectWorldApkOrganizationError,
    organize_perfectworld_apk,
)
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error, read_small


GAMES = ("tof", "p5x", "nte")
APK_PACKAGES = {
    "nte": "com.hottagames.yh.laohu",
    "tof": "com.pwrd.hotta.laohu",
    "p5x": "com.pwrd.persona5x.laohu",
}


def dated_version(filename: str) -> str | None:
    matches = re.findall(r"(?<!\d)(20\d{6})(?!\d)", filename)
    return matches[-1] if matches else None


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> PerfectWorldApkCollection:
    """Collect one official gameDownload APK without writing a record."""
    source_url = endpoint("perfectworld", game_id)
    body = read_small(source_url, timeout)
    match = re.match(r"(?s)^\s*var\s+\w+_download_json\s*=\s*(\{.*\})\s*;\s*$", body)
    if not match:
        raise AdapterError("下载 JS 格式与预期不符")
    url = json.loads(match.group(1)).get("android")
    if not isinstance(url, str):
        raise AdapterError("下载 JS 中没有 Android URL")
    resolved_version = version
    resolved_version_code = version_code
    version_parser = dated_version
    if game_id in APK_PACKAGES and not resolved_version:
        resolved_version, manifest_code = remote_apk_version(
            url,
            timeout,
            expected_package=APK_PACKAGES[game_id],
        )
        if resolved_version_code is None:
            resolved_version_code = manifest_code
        version_parser = None
    record = fetch_record(
        "perfectworld", game_id, url, version=resolved_version,
        version_code=resolved_version_code, timeout=timeout,
        version_parser=version_parser,
    )
    if record.get("platform") is None:
        record = {**record, "platform": "android"}
    return PerfectWorldApkCollection(
        source_url=source_url,
        record=record,
        source_name=f"Perfect World official {game_id} gameDownload Android page",
    )


def discover_collection(collection: PerfectWorldApkCollection, output_root: Path) -> Path:
    """Organize, validate, and safely persist one collected APK."""
    try:
        record = organize_perfectworld_apk(collection)
        return persist_v2_record(record, output_root)
    except (PerfectWorldApkOrganizationError, VersionStoreError) as error:
        raise AdapterError(str(error)) from error


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="完美世界 gameDownload.js Android 适配器")
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
    except (AdapterError, json.JSONDecodeError) as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
