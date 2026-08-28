"""Collect official MiHoYo PC game packages from HoYoPlay."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError, print_error, read_small
from url_adapters.pc.mihoyo_package_organizer import (
    GAME_IDENTITIES,
    MihoyoPackageCollection,
    MihoyoPackageOrganizationError,
    organize_packages_and_patches,
    package_source_url,
)


GAMES = tuple(GAME_IDENTITIES)


def collect(game_id: str, timeout: int) -> MihoyoPackageCollection:
    """Fetch one bounded HoYoPlay package response without downloading packages."""
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise AdapterError("timeout 必须是正整数")
    try:
        source_url = package_source_url(game_id)
    except MihoyoPackageOrganizationError as error:
        raise AdapterError(str(error)) from error
    hoyoplay_game_id, _ = GAME_IDENTITIES[game_id]

    raw = read_small(source_url, timeout)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AdapterError("getGamePackages 返回了无效 JSON") from error
    if not isinstance(payload, Mapping):
        raise AdapterError("getGamePackages 响应必须是 JSON 对象")
    return MihoyoPackageCollection(
        game_id=game_id,
        hoyoplay_game_id=hoyoplay_game_id,
        source_url=source_url,
        payload=payload,
    )


def discover_collection(collection: MihoyoPackageCollection, output_root: Path) -> Path:
    """Persist packages and game patches from one HoYoPlay response atomically."""
    try:
        return persist_v2_record(organize_packages_and_patches(collection), output_root)
    except (MihoyoPackageOrganizationError, VersionStoreError) as error:
        raise AdapterError(str(error)) from error


def discover(game_id: str, output_root: Path, timeout: int = 30) -> Path:
    """Collect, organize, validate, and persist one canonical package record."""
    return discover_collection(collect(game_id, timeout), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="米哈游 HoYoPlay PC 完整包适配器")
    parser.add_argument("game_id", choices=GAMES)
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        path = discover(args.game_id, args.output_root, args.timeout)
        print(path.resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
