"""Probe an existing direct URL and merge probe-owned fields into a record."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from backend.android_record_compat import (
    AndroidRecordCompatibilityError,
    apply_android_v2_result,
    is_android_v2_record,
)
from probe_adapters.common import ProbeError, content_md5, content_size, file_time, probe_head, probe_url, validate_timeout
from probe_adapters.registry import adapter_for


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
        "platform": platform or "android",
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
        "crc64": headers.get("x-oss-hash-crc64ecma"),
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
        "adapter": adapter.NAME, "platform": platform or "android", "url": url,
        "filename": filename, "http_code": None, "available": static["available"],
        "checked_at": checked_at, "content_type": None, "size": None,
        "observed_size": None, "expected_size": expected_size, "etag": None,
        "crc64": None, "md5": None, "last_modified": None, "file_time": None,
        "reason": static.get("reason"), "confidence": static.get("confidence"),
        "source_kind": static.get("source_kind", "adapter_policy"),
    }


def apply_result(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not is_android_v2_record(record):
        raise ProbeError("APK 探活写回仅支持 schema_version=2 的 Android 记录")
    try:
        return apply_android_v2_result(record, result)
    except AndroidRecordCompatibilityError as error:
        raise ProbeError(str(error)) from error
