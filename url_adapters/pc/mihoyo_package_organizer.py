"""Organize official HoYoPlay game packages as canonical schema v2 records."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from backend.schema_v2 import artifact_id, validate_v2_record


API_ORIGIN: Final = "https://hyp-api.mihoyo.com"
API_PATH: Final = "/hyp/hyp-connect/api/getGamePackages"
LAUNCHER_ID: Final = "jGHBHlcOq1"
GAME_IDENTITIES: Final = {
    "hk4e": ("1Z8W5NHUQb", "hk4e_cn"),
    "hkrpg": ("64kMb5iAWu", "hkrpg_cn"),
    "nap": ("x6znKlJ0xK", "nap_cn"),
    "bh3": ("osvnlOc0S8", "bh3_cn"),
}

_ARCHIVE_NAME = re.compile(r"\.(?:zip|7z)$", re.IGNORECASE)
_SEGMENT_NAME = re.compile(r"^(?P<archive>.+\.(?:zip|7z))\.(?P<part>[0-9]{3,})$", re.IGNORECASE)
_MD5 = re.compile(r"^[0-9a-fA-F]{32}$")


class MihoyoPackageOrganizationError(ValueError):
    """Raised when an official response cannot become one package record."""


@dataclass(frozen=True)
class MihoyoPackageCollection:
    """One raw response and its trusted official request identity."""

    game_id: str
    hoyoplay_game_id: str
    source_url: str
    payload: Mapping[str, Any]


def package_source_url(game_id: str) -> str:
    """Return the official CN HoYoPlay package endpoint for one V5 game."""
    try:
        hoyoplay_game_id, _ = GAME_IDENTITIES[game_id]
    except KeyError as error:
        raise MihoyoPackageOrganizationError(f"不支持米哈游 PC 游戏：{game_id}") from error
    query = urlencode((("launcher_id", LAUNCHER_ID), ("game_ids[]", hoyoplay_game_id)))
    return f"{API_ORIGIN}{API_PATH}?{query}"


def _validate_collection_identity(collection: MihoyoPackageCollection) -> tuple[str, str]:
    try:
        expected_hoyoplay_id, expected_biz = GAME_IDENTITIES[collection.game_id]
    except KeyError as error:
        raise MihoyoPackageOrganizationError(f"不支持米哈游 PC 游戏：{collection.game_id}") from error
    if collection.hoyoplay_game_id != expected_hoyoplay_id:
        raise MihoyoPackageOrganizationError("HoYoPlay game id 与 V5 游戏不匹配")

    parsed = urlsplit(collection.source_url)
    if parsed.scheme != "https" or parsed.netloc != "hyp-api.mihoyo.com" or parsed.path != API_PATH:
        raise MihoyoPackageOrganizationError("source_url 不是米哈游官方 getGamePackages endpoint")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query != {"launcher_id": [LAUNCHER_ID], "game_ids[]": [expected_hoyoplay_id]}:
        raise MihoyoPackageOrganizationError("source_url 的 launcher/game 参数与目标游戏不匹配")
    return expected_hoyoplay_id, expected_biz


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MihoyoPackageOrganizationError(f"{field} 必须是非负整数或纯十进制字符串")
    return value


def _package_name(url: Any, field: str) -> tuple[str, int | None, str | None]:
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        raise MihoyoPackageOrganizationError(f"{field}.url 必须是 https URL")
    name = PurePosixPath(unquote(parsed.path)).name
    if not name:
        raise MihoyoPackageOrganizationError(f"{field}.url 缺少文件名")
    segment = _SEGMENT_NAME.fullmatch(name)
    if segment:
        part = int(segment.group("part"))
        if part < 1:
            raise MihoyoPackageOrganizationError(f"{field}.url 的分卷编号必须从 1 开始")
        return name, part, segment.group("archive")
    if not _ARCHIVE_NAME.search(name):
        raise MihoyoPackageOrganizationError(f"{field}.url 不是已确认的 archive 或 archive segment")
    return name, None, None


def _select_game_package(payload: Mapping[str, Any], expected_id: str, expected_biz: str) -> Mapping[str, Any]:
    retcode = payload.get("retcode")
    if isinstance(retcode, bool) or retcode != 0:
        raise MihoyoPackageOrganizationError(f"getGamePackages 失败：retcode={payload.get('retcode')!r}")
    data = payload.get("data")
    packages = data.get("game_packages") if isinstance(data, Mapping) else None
    if not isinstance(packages, list) or not packages:
        raise MihoyoPackageOrganizationError("getGamePackages 缺少 data.game_packages")

    matches = []
    for item in packages:
        game = item.get("game") if isinstance(item, Mapping) else None
        if isinstance(game, Mapping) and game.get("id") == expected_id and game.get("biz") == expected_biz:
            matches.append(item)
    if len(matches) != 1:
        raise MihoyoPackageOrganizationError("getGamePackages 未返回唯一匹配的目标游戏")
    return matches[0]


def _artifacts(game_packages: Any, record_identity: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(game_packages, list) or not game_packages:
        raise MihoyoPackageOrganizationError("main.major.game_pkgs 必须是非空数组")

    artifacts: list[dict[str, Any]] = []
    segment_parts: dict[str, set[int]] = defaultdict(set)
    for index, package in enumerate(game_packages):
        field = f"main.major.game_pkgs[{index}]"
        if not isinstance(package, Mapping):
            raise MihoyoPackageOrganizationError(f"{field} 必须是对象")
        url = package.get("url")
        name, part, archive_name = _package_name(url, field)
        md5 = package.get("md5")
        if not isinstance(md5, str) or not _MD5.fullmatch(md5):
            raise MihoyoPackageOrganizationError(f"{field}.md5 必须是 32 位十六进制字符串")

        artifact: dict[str, Any] = {
            "kind": "package",
            "component": "game",
            "package_type": "segment" if part is not None else "full",
            "delivery_mode": "archive",
            "name": name,
            "size": _non_negative_int(package.get("size"), f"{field}.size"),
            "decompressed_size": _non_negative_int(
                package.get("decompressed_size"), f"{field}.decompressed_size"
            ),
            "checksum": {"md5": md5.lower()},
            "urls": [{"url": url, "provider": "mihoyo", "source_kind": "official", "priority": 0}],
        }
        if part is not None:
            artifact["part"] = part
            assert archive_name is not None
            archive_key = archive_name.casefold()
            if part in segment_parts[archive_key]:
                raise MihoyoPackageOrganizationError(f"{archive_name} 出现重复分卷 {part}")
            segment_parts[archive_key].add(part)
        artifact["artifact_id"] = artifact_id(artifact, record_identity)
        artifacts.append(artifact)

    for archive_name, parts in segment_parts.items():
        expected = set(range(1, max(parts) + 1))
        if parts != expected:
            raise MihoyoPackageOrganizationError(f"{archive_name} 分卷必须从 1 开始且连续")
    return artifacts


def organize_packages(collection: MihoyoPackageCollection) -> dict[str, Any]:
    """Build and strictly validate one official MiHoYo PC package record."""
    if not isinstance(collection, MihoyoPackageCollection):
        raise MihoyoPackageOrganizationError("采集结果必须是 MihoyoPackageCollection")
    if not isinstance(collection.payload, Mapping):
        raise MihoyoPackageOrganizationError("getGamePackages 响应必须是对象")
    expected_id, expected_biz = _validate_collection_identity(collection)
    game_package = _select_game_package(collection.payload, expected_id, expected_biz)

    main = game_package.get("main")
    major = main.get("major") if isinstance(main, Mapping) else None
    if not isinstance(major, Mapping):
        raise MihoyoPackageOrganizationError("getGamePackages 缺少 main.major")
    version = major.get("version")
    if not isinstance(version, str) or not version.strip():
        raise MihoyoPackageOrganizationError("main.major.version 必须是非空字符串")

    record: dict[str, Any] = {
        "schema_version": 2,
        "vendor": "mihoyo",
        "game_id": collection.game_id,
        "domain_id": f"{collection.game_id}-pc",
        "platform": "windows",
        "channel": "official",
        "version": version,
        "version_code": None,
        "file_time": None,
        "artifacts": [],
        "references": [],
        "provenance": {
            "source_kind": "official_sync",
            "source_name": "MiHoYo HoYoPlay getGamePackages",
            "source_url": collection.source_url,
        },
    }
    record["artifacts"] = _artifacts(major.get("game_pkgs"), record)
    validate_v2_record(record)
    return record


organize = organize_packages


__all__ = [
    "GAME_IDENTITIES",
    "MihoyoPackageCollection",
    "MihoyoPackageOrganizationError",
    "organize",
    "organize_packages",
    "package_source_url",
]
