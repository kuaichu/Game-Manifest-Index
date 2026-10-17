"""Small, schema-v2-only helpers for Android probe results."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

class AndroidRecordCompatibilityError(ValueError):
    """A record/result cannot be represented safely in schema v2."""

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

__all__ = ["AndroidRecordCompatibilityError", "android_v2_current_from_result"]
