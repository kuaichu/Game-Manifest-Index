"""Small, schema-v2-only helpers for Android probe results."""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from backend.schema_v2 import SchemaValidationError, validate_v2_record

class AndroidRecordCompatibilityError(ValueError):
    """A record/result cannot be represented safely in schema v2."""

def is_android_v2_record(record: Any) -> bool:
    return isinstance(record, Mapping) and record.get("schema_version") == 2 and record.get("platform") == "android"

def android_v2_current_from_result(result: Mapping[str, Any], target_url: str) -> dict[str, Any]:
    available = result.get("available")
    if available is not None and not isinstance(available, bool):
        raise AndroidRecordCompatibilityError("Android 探活结果 available 必须是 boolean 或 null")
    current: dict[str, Any] = {"state": "available" if available is True else "unavailable" if available is False else "unknown"}
    for key in ("http_code", "checked_at", "etag", "crc64", "last_modified"):
        if result.get(key) is not None:
            current[key] = result[key]
    response_size = result.get("observed_size")
    if response_size is None:
        response_size = result.get("size")
    if isinstance(response_size, int) and not isinstance(response_size, bool) and response_size >= 0:
        current["response_size"] = response_size
    final_url = result.get("url")
    if isinstance(final_url, str) and final_url and final_url != target_url:
        current["final_url"] = final_url
    return current

def apply_android_v2_result(record: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    if not is_android_v2_record(record):
        raise AndroidRecordCompatibilityError("Android 探活写回仅支持 schema_version=2 的 Android 记录")
    if not isinstance(result, Mapping):
        raise AndroidRecordCompatibilityError("Android 探活结果必须是对象")
    target_url = result.get("target_url")
    if not isinstance(target_url, str) or not target_url:
        raise AndroidRecordCompatibilityError("Android 探活结果缺少 target_url")
    try:
        validate_v2_record(record)
    except SchemaValidationError as error:
        raise AndroidRecordCompatibilityError(f"schema v2 Android 记录无效：{error}") from error
    updated = deepcopy(dict(record))
    matches = [candidate for artifact in updated.get("artifacts", []) if isinstance(artifact, dict)
               for candidate in artifact.get("urls", [])
               if isinstance(candidate, dict) and candidate.get("url") == target_url]
    if len(matches) != 1:
        raise AndroidRecordCompatibilityError("schema v2 Android 探活结果与原始 URL 不一致")
    matches[0]["current"] = android_v2_current_from_result(result, target_url)
    try:
        validate_v2_record(updated)
    except SchemaValidationError as error:
        raise AndroidRecordCompatibilityError(f"schema v2 Android 探活结果无效：{error}") from error
    return updated

__all__ = ["AndroidRecordCompatibilityError", "android_v2_current_from_result", "apply_android_v2_result", "is_android_v2_record"]
