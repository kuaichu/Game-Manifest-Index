"""Shared canonical schema v2 builder for official Android APK observations."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from copy import deepcopy
from typing import Any, Final
from urllib.parse import urlsplit

from backend.schema_v2 import (
    CHECKSUM_FIELDS,
    SCHEMA_VERSION,
    artifact_id,
    validate_v2_record,
)


_ALLOWED_OBSERVATION_FIELDS: Final = frozenset({
    "schema_version",
    "vendor",
    "game_id",
    "domain_id",
    "platform",
    "channel",
    "version",
    "version_code",
    "file_time",
    "is_visible",
    "provenance",
    "references",
    "filename",
    "url",
    "size",
    "checksum",
    "status",
})
_ALLOWED_STATUS_FIELDS: Final = frozenset({"available", "http_code", "last_checked_at"})


def _http_url(value: Any, field: str, error_cls: type[ValueError]) -> str:
    parsed = urlsplit(value) if isinstance(value, str) else None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise error_cls(f"{field} 必须是 http 或 https URL")
    return value


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_observation_status(status: Mapping[str, Any]) -> None:
    for key in status:
        if key not in _ALLOWED_STATUS_FIELDS:
            raise ValueError(f"$.status.{key}: cannot be safely represented in schema v2")
    http_code = status.get("http_code")
    if http_code is not None:
        if isinstance(http_code, bool) or not isinstance(http_code, int) or http_code < 0:
            raise ValueError("$.status.http_code: must be a non-negative integer or null")
    checked_at = status.get("last_checked_at")
    if checked_at is not None and not isinstance(checked_at, str):
        raise ValueError("$.status.last_checked_at: must be a string or null")


def _extract_checksum(checksum: Any) -> tuple[dict[str, Any], str | None]:
    if checksum is None:
        return {}, None
    if not isinstance(checksum, Mapping):
        raise ValueError("$.checksum: must be an object")
    canonical: dict[str, Any] = {}
    etag: str | None = None
    for key, raw in checksum.items():
        if key in CHECKSUM_FIELDS:
            if raw is not None:
                canonical[key] = raw
        elif key == "etag":
            if raw is not None:
                if not isinstance(raw, str):
                    raise ValueError("$.checksum.etag: must be a string or null")
                etag = raw
        else:
            raise ValueError(f"$.checksum.{key}: cannot be safely represented in schema v2")
    return canonical, etag


def _build_current(
    *,
    status: Mapping[str, Any],
    size: Any,
    etag: str | None,
    crc64: Any,
) -> dict[str, Any]:
    current: dict[str, Any] = {}
    if status.get("http_code") is not None:
        current["http_code"] = status["http_code"]
    if status.get("last_checked_at") is not None:
        current["checked_at"] = status["last_checked_at"]
    current["state"] = "available"
    if etag is not None:
        current["etag"] = etag
    if size is not None:
        current["response_size"] = size
    if crc64 is not None:
        current["crc64"] = crc64
    return current


def build_official_apk_v2_record(
    collection: Any,
    *,
    collection_cls: type[Any],
    error_cls: type[ValueError],
    vendor: str,
    vendor_label: str,
    allowed_game_ids: Collection[str] | None = None,
    game_id_error: str | None = None,
    channel_error: str = "只支持 channel=official 的 APK 采集结果",
    canonical_url_resolver: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Validate an official Android APK observation and build a canonical v2 record."""
    if not isinstance(collection, collection_cls):
        raise error_cls(f"采集结果必须是 {collection_cls.__name__}")
    source_url = _http_url(collection.source_url, "source_url", error_cls)
    if not isinstance(collection.record, Mapping):
        raise error_cls("采集结果 record 必须是对象")

    source = deepcopy(dict(collection.record))
    if source.get("vendor") != vendor:
        raise error_cls(f"只支持 vendor={vendor} 的 APK 采集结果")
    if allowed_game_ids is not None and source.get("game_id") not in allowed_game_ids:
        raise error_cls(game_id_error or f"只支持 {vendor_label} Android 游戏的 APK 采集结果")
    if source.get("platform") != "android":
        raise error_cls("只支持 platform=android 的 APK 采集结果")
    if source.get("channel") != "official":
        raise error_cls(channel_error)
    filename = source.get("filename")
    if not isinstance(filename, str) or not filename.lower().endswith(".apk"):
        raise error_cls("采集结果缺少有效 APK filename")
    final_url = _http_url(source.get("url"), "url", error_cls)
    status = source.get("status")
    if not isinstance(status, Mapping) or status.get("available") is not True:
        raise error_cls("采集结果未确认 APK 可用")
    if "references" in source and source["references"] != []:
        raise error_cls(f"{vendor_label} APK 采集结果不支持 references")

    try:
        for key in source:
            if key not in _ALLOWED_OBSERVATION_FIELDS:
                raise ValueError(f"$.{key}: unknown field cannot be migrated")
        if "schema_version" in source and (
            isinstance(source["schema_version"], bool) or source["schema_version"] != 1
        ):
            raise ValueError("$.schema_version: unsupported legacy schema version")

        _validate_observation_status(status)
        canonical_checksum, etag = _extract_checksum(source.get("checksum"))

        game_id = source.get("game_id")
        output: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "vendor": vendor,
        }
        if "game_id" in source:
            output["game_id"] = game_id
        output["platform"] = "android"
        output["channel"] = "official"
        if "version" in source:
            output["version"] = source["version"]
        if "is_visible" in source:
            output["is_visible"] = source["is_visible"]
        output["version_code"] = source["version_code"] if "version_code" in source else None
        output["file_time"] = source["file_time"] if "file_time" in source else None
        if "domain_id" in source:
            output["domain_id"] = source["domain_id"]
        elif _is_non_empty_str(game_id):
            output["domain_id"] = f"{game_id}-android"

        output["provenance"] = {
            "source_kind": "official_sync",
            "source_name": deepcopy(collection.source_name),
            "source_url": source_url,
        }

        canonical_url = (
            canonical_url_resolver(game_id, final_url)
            if canonical_url_resolver is not None and isinstance(game_id, str)
            else final_url
        )
        size = source.get("size")
        candidate: dict[str, Any] = {
            "url": canonical_url,
            "provider": vendor,
            "source_kind": "official",
            "priority": 0,
        }
        if canonical_url == final_url:
            # Direct URL matches the probed URL; retain response evidence.
            # When canonicalized (e.g. signed launcher URL -> stable vendor OSS),
            # omit current so signed-URL evidence is not attached to the OSS URL.
            candidate["current"] = _build_current(
                status=status,
                size=size,
                etag=etag,
                crc64=canonical_checksum.get("crc64"),
            )

        artifact: dict[str, Any] = {
            "kind": "apk",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "direct",
            "name": filename,
            "urls": [candidate],
        }
        if size is not None:
            artifact["size"] = size
        if canonical_checksum:
            artifact["checksum"] = canonical_checksum
        artifact["artifact_id"] = artifact_id(artifact, output)

        output["artifacts"] = [artifact]
        output["references"] = []
        validate_v2_record(output)
    except (TypeError, ValueError) as error:
        raise error_cls(f"{vendor_label} APK 无法整理为 schema v2：{error}") from error

    return output


__all__ = [
    "build_official_apk_v2_record",
]
