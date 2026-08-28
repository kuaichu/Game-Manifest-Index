"""Probe an existing direct URL and merge probe-owned fields into a record."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from backend.android_record_compat import (
    AndroidRecordCompatibilityError,
    apply_android_v2_result,
    is_android_v2_record,
)
from backend.schema_v2 import SchemaValidationError, validate_v2_record
from probe_adapters.common import (
    ProbeError,
    content_md5,
    content_size,
    file_time,
    probe_head,
    probe_url,
    validate_timeout,
)
from probe_adapters.registry import PC_ADAPTERS, adapter_for


def probe(
    url: str,
    *,
    vendor: str | None = None,
    game_id: str | None = None,
    timeout: int = 10,
    platform: str | None = None,
    expected_size: int | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeout = validate_timeout(timeout)
    if platform == "pc":
        platform = "windows"
    try:
        adapter = adapter_for(vendor, game_id, url, platform)
    except ProbeError:
        # Discovery endpoints often have no APK suffix.  Probe them first,
        # then dispatch the actual vendor adapter from the redirected URL.
        if platform is not None:
            raise
        adapter = None
    preflight = getattr(adapter, "preflight", None) if adapter else None
    static = preflight(
        url, platform=platform, vendor=vendor, game_id=game_id, context=context,
    ) if preflight else None
    if static is not None:
        return _static_result(adapter, url, platform, expected_size, static)
    try:
        observation = probe_url(url, timeout)
        status, headers, final_url, prefix = observation
        transport_returncode = getattr(observation, "transport_returncode", 0)
        bytes_received = getattr(observation, "bytes_received", len(prefix))
    except ProbeError as error:
        fallback = getattr(adapter, "allows_head_fallback", None) if adapter else None
        if not fallback or not fallback(url, error):
            if adapter:
                setattr(error, "adapter", adapter.NAME)
            raise
        try:
            status, headers, final_url = probe_head(url, timeout)
        except ProbeError as head_error:
            classify_head = getattr(adapter, "classify_head_fallback", None)
            original_filename = unquote(Path(urlsplit(error.final_url or url).path).name)
            fallback_decision = classify_head(
                error.status or 0,
                original_filename,
                error.headers,
                expected_size=expected_size,
                error=error,
            ) if classify_head else None
            if fallback_decision is None:
                setattr(head_error, "adapter", adapter.NAME)
                raise
            status = error.status or 0
            headers = error.headers
            final_url = error.final_url or url
        redirected_adapter = adapter_for(vendor, game_id, final_url, platform)
        final_static = getattr(redirected_adapter, "preflight", None)
        if final_static:
            decision = final_static(
                final_url, platform=platform, vendor=vendor, game_id=game_id, context=context,
            )
            if decision is not None:
                return _static_result(redirected_adapter, final_url, platform, expected_size, decision)
        filename = unquote(Path(urlsplit(final_url).path).name)
        classify_head = getattr(redirected_adapter, "classify_head_fallback", None)
        fallback_decision = classify_head(
            status,
            filename,
            headers,
            expected_size=expected_size,
            error=error,
        ) if classify_head else None
        if fallback_decision is None:
            error = ProbeError(
                f"HEAD fallback 无法确认资源（HTTP {status}）",
                status=status, headers=headers, final_url=final_url,
            )
            setattr(error, "adapter", adapter.NAME)
            raise error
        prefix = b""
        adapter = redirected_adapter
        transport_returncode = getattr(error, "returncode", None)
        bytes_received = 0
    else:
        adapter = adapter_for(vendor, game_id, final_url, platform)
        final_static = getattr(adapter, "preflight", None)
        if final_static:
            decision = final_static(
                final_url, platform=platform, vendor=vendor, game_id=game_id, context=context,
            )
            if decision is not None:
                return _static_result(adapter, final_url, platform, expected_size, decision)
    filename = unquote(Path(urlsplit(final_url).path).name)
    content_type = headers.get("content-type", "")
    observed_size = content_size(status, headers)
    availability = getattr(adapter, "availability", None)
    if 'fallback_decision' in locals():
        available = fallback_decision["available"]
    elif availability:
        try:
            available = availability(
                status,
                filename,
                prefix,
                observed_size=observed_size,
                expected_size=expected_size,
                transport_returncode=transport_returncode,
                bytes_received=bytes_received,
            )
        except TypeError as error:
            # Keep existing vendor adapters with the original three-argument
            # contract working while HoYo adapters consume size evidence.
            if "unexpected keyword argument" not in str(error):
                raise
            available = availability(status, filename, prefix)
    else:
        confirmed = status in {200, 206} and filename.lower().endswith(".apk") and "html" not in content_type.lower()
        available = True if confirmed else False if status in {404, 410} else None
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = {
        "adapter": adapter.NAME,
        "platform": platform or ("windows" if adapter in PC_ADAPTERS else "android"),
        "url": final_url,
        "filename": filename,
        "http_code": (
            None if 'fallback_decision' in locals()
            and fallback_decision.get("source_kind") == "official_storage_metadata"
            else status
        ),
        "metadata_http_code": status if 'fallback_decision' in locals() else None,
        "available": available,
        "checked_at": checked_at,
        "content_type": content_type or None,
        "size": observed_size,
        "observed_size": observed_size,
        "expected_size": expected_size,
        "etag": headers.get("etag", "").strip('"') or None,
        "crc64": headers.get("x-oss-hash-crc64ecma") or headers.get("x-cos-hash-crc64ecma"),
        "md5": content_md5(headers.get("content-md5")),
        "last_modified": headers.get("last-modified"),
        "file_time": file_time(final_url, headers, adapter.URL_TIME),
        "reason": (
            fallback_decision.get("reason", f"HTTP {status}")
            if 'fallback_decision' in locals() else f"HTTP {status}"
        ),
        "confidence": (
            fallback_decision.get("confidence", "high")
            if 'fallback_decision' in locals() else "high"
        ),
        "source_kind": (
            fallback_decision.get("source_kind", "live_probe")
            if 'fallback_decision' in locals() else "live_probe"
        ),
        "transport_returncode": transport_returncode,
        "bytes_received": bytes_received,
    }
    candidate_factory = getattr(adapter, "file_time_candidate", None)
    if candidate_factory is not None:
        candidate = candidate_factory(
            status,
            headers,
            context=context or {},
            available=available,
        )
        if candidate is not None:
            result["file_time_candidate"] = candidate
    return result


def _static_result(
    adapter: Any, url: str, platform: str | None, expected_size: int | None,
    static: dict[str, object],
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    filename = unquote(Path(urlsplit(url).path).name)
    return {
        "adapter": adapter.NAME,
        "platform": platform or ("windows" if adapter in PC_ADAPTERS else "android"),
        "url": url,
        "filename": filename, "http_code": None, "available": static["available"],
        "checked_at": checked_at, "content_type": None, "size": None,
        "observed_size": None, "expected_size": expected_size, "etag": None,
        "crc64": None, "md5": None, "last_modified": None, "file_time": None,
        "reason": static.get("reason"), "confidence": static.get("confidence"),
        "source_kind": static.get("source_kind", "adapter_policy"),
    }


def apply_result(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, dict) and record.get("platform") == "windows":
        try:
            return apply_pc_v2_result(record, result)
        except (PCRecordCompatibilityError, SchemaValidationError) as error:
            raise ProbeError(str(error)) from error
    if not is_android_v2_record(record):
        raise ProbeError("APK 探活写回仅支持 schema_version=2 的 Android 记录")
    try:
        return apply_android_v2_result(record, result)
    except AndroidRecordCompatibilityError as error:
        raise ProbeError(str(error)) from error


class PCRecordCompatibilityError(ValueError):
    """A Windows v2 record/result cannot be represented safely."""


def apply_pc_v2_result(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise PCRecordCompatibilityError("PC 探活结果必须是对象")
    if record.get("schema_version") != 2 or record.get("platform") != "windows":
        raise PCRecordCompatibilityError("PC 探活写回仅支持 schema_version=2 的 Windows 记录")
    target_url = result.get("target_url")
    if not isinstance(target_url, str) or not target_url:
        raise PCRecordCompatibilityError("PC 探活结果缺少 target_url")
    validate_v2_record(record)
    updated = deepcopy(record)
    artifact_index = result.get("artifact_index")
    url_index = result.get("url_index")
    if (not isinstance(artifact_index, int) or isinstance(artifact_index, bool) or artifact_index < 0
            or not isinstance(url_index, int) or isinstance(url_index, bool) or url_index < 0):
        raise PCRecordCompatibilityError("PC 探活结果缺少有效 artifact_index/url_index")
    try:
        artifact = updated["artifacts"][artifact_index]
        candidate = artifact["urls"][url_index]
    except (IndexError, KeyError, TypeError):
        raise PCRecordCompatibilityError("PC 探活结果索引超出记录范围") from None
    if not isinstance(artifact, dict) or not isinstance(candidate, dict) or candidate.get("url") != target_url:
        raise PCRecordCompatibilityError("schema v2 PC 探活结果与索引目标 URL 不一致")
    available = result.get("available")
    if available is not None and not isinstance(available, bool):
        raise PCRecordCompatibilityError("PC 探活结果 available 必须是 boolean 或 null")
    state = "available" if available is True else "unavailable" if available is False else "unknown"
    current: dict[str, Any] = {"state": state}
    http_code = result.get("http_code")
    if http_code is not None and (not isinstance(http_code, int) or isinstance(http_code, bool) or http_code < 0):
        raise PCRecordCompatibilityError("PC 探活结果 http_code 必须是非负整数或 null")
    if http_code is not None:
        current["http_code"] = http_code
    checked_at = result.get("checked_at")
    if checked_at is not None:
        if not isinstance(checked_at, str) or not checked_at.endswith("Z"):
            raise PCRecordCompatibilityError("PC 探活结果 checked_at 必须是 ISO-8601 UTC 字符串")
        try:
            datetime.fromisoformat(checked_at[:-1] + "+00:00")
        except ValueError as error:
            raise PCRecordCompatibilityError("PC 探活结果 checked_at 必须是有效 ISO-8601 UTC 字符串") from error
        current["checked_at"] = checked_at
    for key in ("etag", "crc64", "last_modified"):
        value = result.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise PCRecordCompatibilityError(f"PC 探活结果 {key} 必须是非空字符串或 null")
        if value is not None:
            current[key] = value
    size = result.get("observed_size")
    if size is None:
        size = result.get("size")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        raise PCRecordCompatibilityError("PC 探活结果 response_size 必须是非负整数或 null")
    if size is not None:
        current["response_size"] = size
    final_url = result.get("url")
    if final_url is not None and (not isinstance(final_url, str) or not final_url):
        raise PCRecordCompatibilityError("PC 探活结果 final_url 必须是字符串或 null")
    if final_url and final_url != target_url:
        try:
            parsed_final = urlsplit(final_url)
            if (parsed_final.scheme not in {"http", "https"} or parsed_final.username is not None
                    or parsed_final.password is not None or parsed_final.query or parsed_final.fragment):
                raise ValueError("unsafe URL")
            adapter_for(record.get("vendor"), record.get("game_id"), final_url, "windows")
        except (ProbeError, ValueError) as error:
            raise PCRecordCompatibilityError("PC 探活结果 final_url 不属于原记录允许的官方适配器") from error
        current["final_url"] = final_url
    candidate["current"] = current
    validate_v2_record(updated)
    return updated
