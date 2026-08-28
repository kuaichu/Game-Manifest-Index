"""Hypergryph official Android APK collection and canonical organization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from backend.schema_v2 import normalize_legacy_record, validate_v2_record


class HypergryphApkOrganizationError(ValueError):
    """Raised when a Hypergryph APK observation is not a valid v2 record."""


@dataclass(frozen=True)
class HypergryphApkCollection:
    source_url: str
    record: Mapping[str, Any]
    source_name: str = "Hypergryph official Android launcher"


def _http_url(value: Any, field: str) -> str:
    parsed = urlsplit(value) if isinstance(value, str) else None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HypergryphApkOrganizationError(f"{field} 必须是 http 或 https URL")
    return value


def organize_hypergryph_apk(collection: HypergryphApkCollection) -> dict[str, Any]:
    """Turn one Hypergryph launcher observation into one valid v2 record."""
    if not isinstance(collection, HypergryphApkCollection):
        raise HypergryphApkOrganizationError("采集结果必须是 HypergryphApkCollection")
    source_url = _http_url(collection.source_url, "source_url")
    if not isinstance(collection.record, Mapping):
        raise HypergryphApkOrganizationError("采集结果 record 必须是对象")

    source = deepcopy(dict(collection.record))
    if source.get("vendor") != "hypergryph":
        raise HypergryphApkOrganizationError("只支持 vendor=hypergryph 的 APK 采集结果")
    if source.get("game_id") not in {"arknights", "endfield"}:
        raise HypergryphApkOrganizationError("只支持鹰角 Android 游戏的 APK 采集结果")
    if source.get("platform") != "android":
        raise HypergryphApkOrganizationError("只支持 platform=android 的 APK 采集结果")
    if source.get("channel") != "official":
        raise HypergryphApkOrganizationError("只支持 channel=official 的 APK 采集结果")
    if not isinstance(source.get("filename"), str) or not source["filename"].lower().endswith(".apk"):
        raise HypergryphApkOrganizationError("采集结果缺少有效 APK filename")
    final_url = _http_url(source.get("url"), "url")
    status = source.get("status")
    if not isinstance(status, Mapping) or status.get("available") is not True:
        raise HypergryphApkOrganizationError("采集结果未确认 APK 可用")
    if "references" in source and source["references"] != []:
        raise HypergryphApkOrganizationError("Hypergryph APK 采集结果不支持 references")

    source["provenance"] = {
        "source_kind": "official_sync",
        "source_name": collection.source_name,
        "source_url": source_url,
    }
    try:
        output = normalize_legacy_record(source)
    except (TypeError, ValueError) as error:
        raise HypergryphApkOrganizationError(f"Hypergryph APK 无法整理为 schema v2：{error}") from error

    artifacts = output.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise HypergryphApkOrganizationError("Hypergryph Android 记录必须恰好包含一个 APK artifact")
    artifact = artifacts[0]
    if not isinstance(artifact, dict):
        raise HypergryphApkOrganizationError("Hypergryph APK artifact 格式无效")
    urls = artifact.get("urls")
    if not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], dict):
        raise HypergryphApkOrganizationError("Hypergryph APK 必须恰好包含一个 URL candidate")

    candidate = urls[0]
    candidate["url"] = final_url
    candidate["provider"] = "hypergryph"
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


organize = organize_hypergryph_apk
organize_apk = organize_hypergryph_apk


__all__ = [
    "HypergryphApkCollection",
    "HypergryphApkOrganizationError",
    "organize",
    "organize_apk",
    "organize_hypergryph_apk",
]
