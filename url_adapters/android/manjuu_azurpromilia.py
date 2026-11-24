"""Collect the official Azur Promilia CN Android APK."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from time import time_ns
from urllib.parse import urlsplit

from backend.android_record_compat import android_v2_current_from_result
from backend.schema_v2 import artifact_id
from backend.version_store import persist_v2_record
from probe_adapters.common import ProbeError, content_md5, content_size, file_time, probe_url
from url_adapters.common import AdapterError, curl, print_error

_SOURCE_URL = "https://api-grp.manjuu.com/activity/web/download/info"
_DOWNLOAD_QUERY = "gameId=35"
_DOWNLOAD_URL = f"{_SOURCE_URL}?{_DOWNLOAD_QUERY}"
_OFFICIAL_SITE = "https://azurpromilia.manjuu.com"
_APK_PREFIX = "/azurpromilia/android/c000/"
_APK_NAME = re.compile(r"AzurPromilia_(\d+\.\d+\.\d+\.\d+)_SC000_\d{14}_[0-9a-f]+\.apk", re.I)


def _apk_url(timeout: int) -> tuple[str, str, str]:
    # The public website SDK signs its GET query with the current millisecond timestamp.
    stamp = str(time_ns() // 1_000_000)
    sign = hashlib.md5(f"{stamp}{_DOWNLOAD_QUERY}".encode("ascii"), usedforsecurity=False).hexdigest()
    raw = curl([
        "--fail", "--max-filesize", "65536",
        "-H", f"Origin: {_OFFICIAL_SITE}", "-H", f"Referer: {_OFFICIAL_SITE}/home",
        "-H", "grp-app-id: 350010", "-H", "grp-channel-code: C000",
        "-H", "grp-sub-channel-code: SC000", "-H", "device-id;",
        "-H", f"timestamp: {stamp}", "-H", f"sign: {sign}", _DOWNLOAD_URL,
    ], timeout)
    try:
        response = json.loads(raw)
        if type(response["code"]) is not int or response["code"] != 0:
            raise ValueError
        url = response["data"]["nativeAndroidDownloadUrl"]
        parsed = urlsplit(url) if isinstance(url, str) else None
    except (KeyError, TypeError, ValueError):
        parsed = None
    if (
        parsed is None or parsed.scheme != "https" or parsed.netloc != "syncstation.manjuu.com"
        or not parsed.path.startswith(_APK_PREFIX) or parsed.query or parsed.fragment
    ):
        raise AdapterError("蛮啾官网没有返回有效的蓝色星原国服 Android APK 链接")
    filename = PurePosixPath(parsed.path).name
    match = _APK_NAME.fullmatch(filename)
    if match is None:
        raise AdapterError("无法从蛮啾官方 APK 文件名确认完整版本号")
    return url, filename, match[1]


def discover_v2(
    game_id: str, output_root: Path, timeout: int,
    version: str | None = None, version_code: int | None = None,
) -> Path:
    if game_id != "azurpromilia":
        raise AdapterError(f"蓝色星原 Android 适配器不支持：{game_id}")
    url, filename, discovered_version = _apk_url(timeout)
    if version is not None and version != discovered_version:
        raise AdapterError(f"指定版本与蛮啾官方 APK 版本不一致：{discovered_version}")
    try:
        status, headers, final_url, prefix = probe_url(url, timeout)
    except ProbeError as error:
        raise AdapterError(f"无法读取蛮啾官方 APK 元数据：{error}") from error
    size = content_size(status, headers)
    if final_url != url or status not in {200, 206} or not prefix.startswith(b"PK\x03\x04") or not size:
        raise AdapterError("蛮啾 CDN 未返回可确认的 Android APK")
    checksum = {
        key: value for key, value in {
            "crc64": headers.get("x-oss-hash-crc64ecma"),
            "md5": content_md5(headers.get("content-md5")),
        }.items() if value
    }
    current = android_v2_current_from_result({
        "available": True, "http_code": status,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "etag": headers.get("etag", "").strip('"') or None,
        "crc64": checksum.get("crc64"), "last_modified": headers.get("last-modified"),
        "response_size": size,
    }, url)
    artifact = {
        "kind": "apk", "component": "game", "package_type": "full", "delivery_mode": "direct",
        "name": filename, "size": size,
        "urls": [{"url": url, "provider": "manjuu", "source_kind": "official", "priority": 0, "current": current}],
    }
    if checksum:
        artifact["checksum"] = checksum
    record = {
        "schema_version": 2, "vendor": "manjuu", "game_id": game_id,
        "domain_id": "azurpromilia-android", "platform": "android", "channel": "official",
        "version": discovered_version, "version_code": version_code,
        "file_time": file_time(url, headers, url_time=False) or file_time(url, headers, url_time=True),
        "provenance": {
            "source_kind": "official_sync",
            "source_name": "Manjuu official Azur Promilia download API",
            "source_url": _SOURCE_URL,
        },
        "artifacts": [artifact], "references": [],
    }
    artifact["artifact_id"] = artifact_id(artifact, record)
    return persist_v2_record(
        record, output_root, preserve_artifacts=True, preserve_references=True, preserve_provenance=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="蓝色星原：旅谣 国服 Android 官网采集")
    parser.add_argument("--output-root", type=Path, required=True, help="写入目标数据目录")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须是正整数")
    try:
        print(discover_v2("azurpromilia", args.output_root, args.timeout).resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
