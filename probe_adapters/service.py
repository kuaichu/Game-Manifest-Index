"""Probe an existing direct URL and project evidence into current fields."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from backend.android_record_compat import (
    AndroidRecordCompatibilityError,
    android_v2_current_from_result,
)
from probe_adapters.common import (
    ProbeError,
    ProbeObservation,
    classify_oss_archive_response,
    content_md5,
    content_size,
    file_time,
    probe_head,
    probe_url,
    validate_timeout,
)
from probe_adapters.registry import PC_ADAPTERS, adapter_for


def _url_filename(url: str) -> str:
    return unquote(Path(urlsplit(url).path).name)


def _preflight_result(
    adapter: Any, url: str, *, platform: str | None, vendor: str | None,
    game_id: str | None, expected_size: int | None, context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    preflight = getattr(adapter, "preflight", None) if adapter else None
    if not preflight:
        return None
    static = preflight(url, platform=platform, vendor=vendor, game_id=game_id, context=context)
    return _static_result(adapter, url, platform, expected_size, static) if static is not None else None


def _probe_range(
    url: str, timeout: int,
) -> tuple[int, dict[str, str], str, bytes, int | None, int, bytes]:
    try:
        observation = probe_url(url, timeout)
    except ProbeError as error:
        if error.status != 403:
            raise
        # An HTTP 403 already establishes unavailability, even when the
        # transport fails while reading its response body.
        observation = ProbeObservation(
            403, error.headers, error.final_url or url, error.prefix,
            transport_returncode=error.returncode,
            bytes_received=len(error.body or error.prefix), body=error.body,
        )
    status, headers, final_url, prefix = observation
    transport_returncode = getattr(observation, "transport_returncode", 0)
    bytes_received = getattr(observation, "bytes_received", len(prefix))
    response_body = getattr(observation, "body", prefix)
    return status, headers, final_url, prefix, transport_returncode, bytes_received, response_body


def _classify_head_fallback(
    adapter: Any, status: int, url: str, headers: dict[str, str], *,
    expected_size: int | None, error: ProbeError,
) -> dict[str, Any] | None:
    classify_head = getattr(adapter, "classify_head_fallback", None)
    if not classify_head:
        return None
    return classify_head(
        status, _url_filename(url), headers, expected_size=expected_size, error=error,
    )


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
    static_result = _preflight_result(
        adapter, url,
        platform=platform, vendor=vendor, game_id=game_id,
        expected_size=expected_size, context=context,
    )
    if static_result is not None:
        return static_result

    fallback_decision: dict[str, Any] | None = None
    try:
        (
            status, headers, final_url, prefix,
            transport_returncode, bytes_received, response_body,
        ) = _probe_range(url, timeout)
    except ProbeError as error:
        fallback = getattr(adapter, "allows_head_fallback", None) if adapter else None
        if not fallback or not fallback(url, error):
            if adapter:
                setattr(error, "adapter", adapter.NAME)
            raise
        try:
            status, headers, final_url = probe_head(url, timeout)
        except ProbeError as head_error:
            status = error.status or 0
            headers = error.headers
            final_url = error.final_url or url
            if _classify_head_fallback(
                adapter, status, final_url, headers,
                expected_size=expected_size, error=error,
            ) is None:
                setattr(head_error, "adapter", adapter.NAME)
                raise
        redirected_adapter = adapter_for(vendor, game_id, final_url, platform)
        static_result = _preflight_result(
            redirected_adapter, final_url,
            platform=platform, vendor=vendor, game_id=game_id,
            expected_size=expected_size, context=context,
        )
        if static_result is not None:
            return static_result
        fallback_decision = _classify_head_fallback(
            redirected_adapter, status, final_url, headers,
            expected_size=expected_size, error=error,
        )
        if fallback_decision is None:
            fallback_error = ProbeError(
                f"HEAD fallback 无法确认资源（HTTP {status}）",
                status=status, headers=headers, final_url=final_url,
            )
            setattr(fallback_error, "adapter", adapter.NAME)
            raise fallback_error
        prefix = b""
        adapter = redirected_adapter
        transport_returncode = getattr(error, "returncode", None)
        bytes_received = 0
        response_body = b""
    else:
        adapter = adapter_for(vendor, game_id, final_url, platform)
        if status != 403:
            static_result = _preflight_result(
                adapter, final_url,
                platform=platform, vendor=vendor, game_id=game_id,
                expected_size=expected_size, context=context,
            )
            if static_result is not None:
                return static_result

    filename = _url_filename(final_url)
    content_type = headers.get("content-type", "")
    observed_size = content_size(status, headers)
    response_decision = classify_oss_archive_response(status, headers, response_body)
    availability = getattr(adapter, "availability", None)
    if status == 403:
        available = False
    elif fallback_decision is not None:
        available = fallback_decision["available"]
    elif response_decision is not None:
        available = response_decision["available"]
    elif availability:
        available = availability(
            status,
            filename,
            prefix,
            observed_size=observed_size,
            expected_size=expected_size,
            transport_returncode=transport_returncode,
            bytes_received=bytes_received,
        )
    else:
        confirmed = status in {200, 206} and filename.lower().endswith(".apk") and "html" not in content_type.lower()
        available = True if confirmed else False if status in {404, 410} else None

    decision_meta = (
        fallback_decision
        if fallback_decision is not None
        else response_decision
        if response_decision is not None
        else {}
    )
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = {
        "adapter": adapter.NAME,
        "platform": platform or ("windows" if adapter in PC_ADAPTERS else "android"),
        "url": final_url,
        "filename": filename,
        "http_code": (
            None
            if fallback_decision is not None
            and fallback_decision.get("source_kind") == "official_storage_metadata"
            else status
        ),
        "metadata_http_code": status if fallback_decision is not None else None,
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
        "reason": decision_meta.get("reason", f"HTTP {status}"),
        "confidence": decision_meta.get("confidence", "high"),
        "source_kind": decision_meta.get("source_kind", "live_probe"),
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
    filename = _url_filename(url)
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


def current_from_result(
    identity: dict[str, str], target_url: str, result: dict[str, Any],
) -> dict[str, Any]:
    """Project evidence into current; target selection and persistence belong to the caller."""
    if not isinstance(result, dict):
        raise ProbeError("探活结果必须是对象")
    if not isinstance(target_url, str) or not target_url:
        raise ProbeError("探活目标 URL 必须是非空字符串")
    try:
        if identity.get("platform") == "windows":
            return pc_v2_current_from_result(identity, target_url, result)
        if identity.get("platform") == "android":
            return android_v2_current_from_result(result, target_url)
    except (PCRecordCompatibilityError, AndroidRecordCompatibilityError) as error:
        raise ProbeError(str(error)) from error
    raise ProbeError("探活状态仅支持 Android 或 Windows 平台")


class PCRecordCompatibilityError(ValueError):
    """A Windows v2 record/result cannot be represented safely."""


def pc_v2_current_from_result(
    identity: dict[str, str], target_url: str, result: dict[str, Any],
) -> dict[str, Any]:
    """Convert PC evidence without receiving or rewriting archive contents."""
    if not isinstance(result, dict):
        raise PCRecordCompatibilityError("PC 探活结果必须是对象")
    if not isinstance(target_url, str) or not target_url:
        raise PCRecordCompatibilityError("PC 探活结果缺少 target_url")
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
            adapter_for(identity.get("vendor"), identity.get("game_id"), final_url, "windows")
        except (ProbeError, ValueError) as error:
            raise PCRecordCompatibilityError("PC 探活结果 final_url 不属于原记录允许的官方适配器") from error
        current["final_url"] = final_url
    return current
