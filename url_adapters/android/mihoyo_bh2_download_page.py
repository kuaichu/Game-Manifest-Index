"""Houkai Gakuen 2 Android download adapter."""

import argparse
import re
from pathlib import Path

from url_adapters.android.mihoyo_apk_organizer import MihoyoApkCollection
from url_adapters.android.mihoyo_download_porter import discover_collection
from url_adapters.common import AdapterError, add_options, endpoint, fetch_record, print_error


def version_from_filename(filename: str) -> str | None:
    match = re.search(
        r"Original\.StripResource[_-](\d+[._]\d+[._]\d+)[_-]",
        filename,
        re.IGNORECASE,
    )
    return match.group(1).replace("_", ".") if match else None


def collect(
    game_id: str, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> MihoyoApkCollection:
    """Collect the BH2 official benghuai.com page observation in flat shape."""
    source_url = endpoint("mihoyo", game_id)
    record = fetch_record(
        "mihoyo", game_id, source_url,
        version=version, version_code=version_code, timeout=timeout,
        platform=None, version_parser=version_from_filename,
    )
    if record.get("platform") is None:
        record = {**record, "platform": "android"}
    return MihoyoApkCollection(
        source_url=source_url,
        record=record,
        source_name="MiHoYo official BH2 Android download page",
    )


def discover(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    return discover_collection(collect(game_id, timeout, version, version_code), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="崩坏学园2 Android 适配器")
    add_options(parser)
    args = parser.parse_args()
    try:
        path = discover("bh2", args.output_root, args.timeout, args.version, args.version_code)
        print(path.resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
