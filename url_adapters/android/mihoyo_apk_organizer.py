"""MiHoYo Android APK collection to canonical schema v2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from backend.schema_v2 import normalize_legacy_record, validate_v2_record


class MihoyoApkOrganizationError(ValueError):
    """Raised when a collection cannot be represented as one v2 APK record."""


@dataclass(frozen=True)
class MihoyoApkCollection:
    """The official entry URL plus the probe-owned legacy observation."""

    source_url: str
    record: Mapping[str, Any]
    source_name: str = "MiHoYo official Android download_porter"


def _http_url(value: Any, field: str) -> str:
    parsed = urlsplit(value) if isinstance(value, str) else None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MihoyoApkOrganizationError(f"{field} 必须是 http 或 https URL")
    return value


def organize_apk(collection: MihoyoApkCollection) -> dict[str, Any]:
    """Build and strictly validate one official MiHoYo Android APK record."""
    if not isinstance(collection, MihoyoApkCollection):
        raise MihoyoApkOrganizationError("采集结果必须是 MihoyoApkCollection")
    source_url = _http_url(collection.source_url, "source_url")
    if not isinstance(collection.record, Mapping):
        raise MihoyoApkOrganizationError("采集结果 record 必须是对象")

    source = deepcopy(dict(collection.record))
    if source.get("vendor") != "mihoyo":
        raise MihoyoApkOrganizationError("只支持 vendor=mihoyo 的 APK 采集结果")
    if source.get("platform") != "android":
        raise MihoyoApkOrganizationError("只支持 platform=android 的 APK 采集结果")
    if source.get("channel") != "official":
        raise MihoyoApkOrganizationError("只支持 channel=official 的米哈游 APK 采集结果")
    if not isinstance(source.get("filename"), str) or not source["filename"].lower().endswith(".apk"):
        raise MihoyoApkOrganizationError("采集结果缺少有效 APK filename")
    final_url = _http_url(source.get("url"), "url")
    status = source.get("status")
    if not isinstance(status, Mapping) or status.get("available") is not True:
        raise MihoyoApkOrganizationError("采集结果未确认 APK 可用")
    if "references" in source and source["references"] != []:
        raise MihoyoApkOrganizationError("MiHoYo APK 采集结果不支持 references")

    source["provenance"] = {
        "source_kind": "official_sync",
        "source_name": collection.source_name,
        "source_url": source_url,
    }
    try:
        output = normalize_legacy_record(source)
    except (TypeError, ValueError) as error:
        raise MihoyoApkOrganizationError(f"MiHoYo APK 无法整理为 schema v2：{error}") from error

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise MihoyoApkOrganizationError("MiHoYo Android 记录必须恰好包含一个 APK artifact")
    artifact = artifacts[0]
    if not isinstance(artifact, dict):
        raise MihoyoApkOrganizationError("MiHoYo APK artifact 格式无效")
    urls = artifact.get("urls")
    if not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], dict):
        raise MihoyoApkOrganizationError("MiHoYo APK 必须恰好包含一个 URL candidate")

    # The direct URL is the downloadable identity.  The official entry URL is
    # retained only in provenance; current contains response evidence.
    candidate = urls[0]
    candidate["url"] = final_url
    candidate["provider"] = "mihoyo"
    candidate["source_kind"] = "official"
    candidate["priority"] = 0
    current = dict(candidate.get("current") or {})
    current["state"] = "available"
    if status.get("http_code") is not None:
        current["http_code"] = status["http_code"]
    if status.get("last_checked_at") is not None:
        current["checked_at"] = status["last_checked_at"]
    size = source.get("size")
    if size is not None:
        artifact["size"] = size
        current["response_size"] = size
    checksum = source.get("checksum")
    if isinstance(checksum, Mapping):
        if checksum.get("etag") is not None:
            current["etag"] = checksum["etag"]
        if checksum.get("crc64") is not None:
            current["crc64"] = checksum["crc64"]
    candidate["current"] = current
    output["references"] = []
    validate_v2_record(output)
    return output


organize = organize_apk


__all__ = [
    "MihoyoApkCollection",
    "MihoyoApkOrganizationError",
    "organize",
    "organize_apk",
]
