"""Honkai Impact 3 Android download adapter."""

import argparse
from pathlib import Path

from url_adapters.android.mihoyo_apk_organizer import MihoyoApkCollection
from url_adapters.android.mihoyo_download_porter import discover_collection
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> MihoyoApkCollection:
    """Collect the BH3 official download_porter observation in flat shape."""
    source_url = endpoint("mihoyo", game_id)
    record = fetch_record(
        "mihoyo", game_id, source_url,
        version=version, version_code=version_code, timeout=timeout, platform=None,
    )
    if record.get("platform") is None:
        record = {**record, "platform": "android"}
    return MihoyoApkCollection(
        source_url=source_url,
        record=record,
        source_name="MiHoYo official BH3 Android download_porter",
    )


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="崩坏3 Android 适配器")
    add_options(parser)
    args = parser.parse_args()
    try:
        path = discover("bh3", args.output_root, args.timeout, args.version, args.version_code)
        print(path.resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
