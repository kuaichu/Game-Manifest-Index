"""MiHoYo download_porter adapter shared by Genshin, HSR and ZZZ."""

import argparse
from pathlib import Path

from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error
from url_adapters.android.mihoyo_apk_organizer import (
    MihoyoApkCollection,
    MihoyoApkOrganizationError,
    organize_apk,
)


GAMES = ("hk4e", "hkrpg", "nap")


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> MihoyoApkCollection:
    """Collect one official APK observation without writing a record."""
    source_url = endpoint("mihoyo", game_id)
    record = fetch_record(
        "mihoyo", game_id, source_url,
        version=version, version_code=version_code, timeout=timeout, platform=None,
    )
    # ``fetch_record`` keeps the transport's inferred platform separate from
    # the optional request hint.  The entry URL needs inference, but the
    # collected legacy record must retain the old Android shape.
    if record.get("platform") is None:
        record = {**record, "platform": "android"}
    return MihoyoApkCollection(source_url=source_url, record=record)


def discover_collection(collection: MihoyoApkCollection, output_root: Path) -> Path:
    """Persist one collected MiHoYo APK through the canonical v2 pipeline."""
    try:
        record = organize_apk(collection)
        return persist_v2_record(record, output_root)
    except (MihoyoApkOrganizationError, VersionStoreError) as error:
        raise AdapterError(str(error)) from error


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    """Collect, organize, validate, and write one canonical v2 APK record."""
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover


output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="米哈游 download_porter Android 适配器")
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
