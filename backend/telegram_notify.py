"""Best-effort Telegram summaries for discovery and probe operations."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from backend.api_contract import GAME_CATALOG


LOGGER = logging.getLogger(__name__)
API_URL = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT_SECONDS = 10
MAX_MESSAGE_LENGTH = 3900
MAX_DETAIL_LINES = 12
DEFAULT_TRANSIENT_DELETE_SECONDS = 600
GAME_NAMES = {game_id: name for game_id, name, _sub_name in GAME_CATALOG}


def _split_chat_ids(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        item.strip()
        for item in value.replace("\n", ",").split(",")
        if item.strip()
    )


def _platform_label(value: object) -> str:
    if value in {"windows", "pc"}:
        return "PC"
    if value == "android":
        return "Android"
    return "unknown"


def _safe_version(value: object) -> str | None:
    # Versions are labels, never a channel for adapter exceptions, URLs or paths.
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+){0,5}(?:[-_+][A-Za-z0-9.]{1,24})?", value):
        return value
    return None


def _duration_label(started_at: object, finished_at: object) -> str:
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        finish = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
        seconds = max(0, int((finish - start).total_seconds()))
    except (TypeError, ValueError):
        seconds = 0
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}分{remainder:02d}秒" if minutes else f"{remainder}秒"


def _version_label(item: Mapping[str, Any]) -> str:
    previous = _safe_version(item.get("previous_version"))
    current = _safe_version(item.get("version"))
    if isinstance(previous, str) and previous and isinstance(current, str) and current:
        return f"{previous} -> {current}"
    if item.get("archived") and isinstance(current, str) and current:
        return f"新增归档版本 {current}"
    if isinstance(current, str) and current:
        return f"新版本 {current}"
    versions = item.get("versions")
    if isinstance(versions, list):
        values = [version for value in versions if (version := _safe_version(value))]
        if values:
            return f"官方包变动 ({', '.join(dict.fromkeys(values))})"
    return "官方包变动 (待定版本)"


def _version_line(item: Mapping[str, Any]) -> str:
    name = GAME_NAMES.get(str(item.get("game_id")), "unknown")
    platform = _platform_label(item.get("platform"))
    return f"• {name} ({platform}): {_version_label(item)}"


def _safe_detail(value: object) -> str | None:
    # Raw details can contain credentials even without a URL. Accept only a
    # fixed diagnostic vocabulary, rather than attempting text redaction.
    return "连接超时" if value == "连接超时" else None


def _probe_failure_label(item: Mapping[str, Any]) -> str:
    raw_error = item.get("error")
    error = raw_error if raw_error in {"ProbeError", "TimeoutError", "OSError", "ValueError", "TypeError", "ConnectionError"} else "ProbeError"
    status = item.get("status")
    detail = _safe_detail(item.get("detail"))
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        return f"{error} (HTTP {status})"
    if detail == "连接超时":
        return detail
    if detail:
        return f"{error} ({detail})"
    if error.lower() in {"timeouterror", "timeout", "readtimeout", "connecttimeout"}:
        return "连接超时"
    return error


def _probe_line(item: Mapping[str, Any]) -> str:
    name = GAME_NAMES.get(str(item.get("game_id")), "unknown")
    platform = _platform_label(item.get("platform"))
    version = _safe_version(item.get("version"))
    suffix = f" {version}" if isinstance(version, str) and version else ""
    return f"• {name} ({platform}{suffix}): {_probe_failure_label(item)}"


def _unavailable_line(item: Mapping[str, Any]) -> str:
    name = GAME_NAMES.get(str(item.get("game_id")), "unknown")
    platform = _platform_label(item.get("platform"))
    version = _safe_version(item.get("version"))
    suffix = f" {version}" if isinstance(version, str) and version else ""
    reason = str(item.get("reason") or "")
    status = re.fullmatch(r"HTTP (\d{3})", reason)
    known = {
        "oss_archive_not_restored": "OSS 归档未恢复",
        "retired_official_host": "旧官方域名已退役",
    }
    detail = f" (HTTP {status.group(1)})" if status else f" ({known[reason]})" if reason in known else ""
    return f"• {name} ({platform}{suffix}): 链接不可用{detail}"


def _limited_lines(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_DETAIL_LINES:
        return lines
    return [*lines[:MAX_DETAIL_LINES], f"• 另有 {len(lines) - MAX_DETAIL_LINES:,} 项已省略"]


def _probe_summary(probe: Mapping[str, Any]) -> tuple[int, int]:
    checked = max(0, int(probe.get("checked", 0) or 0))
    failed = max(0, int(probe.get("failed", 0) or 0))
    return checked, min(failed, checked)


def build_message(
    result: Mapping[str, Any], *, started_at: object, finished_at: object,
    scheduled: bool, status: str = "finished",
) -> tuple[str | None, int | None]:
    """Return ``(text, delete_after_seconds)`` for one finished operation."""
    discover = result.get("discover")
    discover = discover if isinstance(discover, Mapping) else {}
    probe = result.get("probe")
    probe = probe if isinstance(probe, Mapping) else {}
    updates = [
        item for item in discover.get("items", [])
        if isinstance(item, Mapping) and item.get("ok") and item.get("new")
    ]
    probe_items = [item for item in probe.get("items", []) if isinstance(item, Mapping)]
    failures = [item for item in probe_items if not item.get("ok")]
    unavailable_items = [item for item in probe_items if item.get("ok") and item.get("available") is False]
    checked, failed = _probe_summary(probe)
    available = max(0, int(probe.get("available", 0) or 0))
    unavailable = max(0, int(probe.get("unavailable", 0) or 0))
    unknown = max(0, int(probe.get("unknown", 0) or 0))
    duration = _duration_label(started_at, finished_at)
    discovery_failed = max(0, int(discover.get("failed", 0) or 0))

    lines: list[str]
    delete_after: int | None = None
    if updates:
        title = "[GMI 资源巡检] 发现新版本" if len(updates) == 1 and not scheduled else "[GMI 资源巡检] 检测到版本更新"
        if all(item.get("archived") for item in updates):
            title = "[GMI 资源巡检] 新增归档版本"
        elif any(item.get("archived") for item in updates):
            title = "[GMI 资源巡检] 检测到版本更新与归档补录"
        if failures or failed or unavailable_items or unavailable or discovery_failed or status != "finished":
            title += "（存在巡检异常）"
        lines = [title, "", *_limited_lines([_version_line(item) for item in updates])]
        if failures or unavailable_items:
            details = [_probe_line(item) for item in failures]
            details.extend(_unavailable_line(item) for item in unavailable_items)
            lines.extend(["", "探活异常：", *_limited_lines(details)])
        if len(updates) == 1 and not scheduled and checked and available == checked:
            lines.extend(["", f"耗时: {duration} | 探活正常"])
        elif checked:
            parts = [f"{available:,} 可用"]
            if unavailable:
                parts.append(f"{unavailable:,} 不可用")
            if unknown:
                parts.append(f"{unknown:,} 未判定")
            if failed:
                parts.append(f"{failed:,} 异常")
            lines.extend(["", f"耗时: {duration} | 探活: {checked:,} 项 ({' / '.join(parts)})"])
        else:
            lines.extend(["", f"耗时: {duration} | 未执行探活"])
    elif failures or failed or unavailable_items or unavailable:
        title = "[GMI 巡检异常] 检测到探活失败" if failures or failed else "[GMI 巡检异常] 检测到不可用链接"
        lines = [title, ""]
        details = [_probe_line(item) for item in failures]
        details.extend(_unavailable_line(item) for item in unavailable_items)
        if details:
            lines.extend(_limited_lines(details))
        elif failed:
            lines.append(f"• 探活失败: {failed:,} 项")
        else:
            lines.append(f"• 链接不可用: {unavailable:,} 项")
        counts = [f"总计: {checked:,} 项"]
        if failed:
            counts.append(f"失败: {failed:,} 项")
        if unavailable:
            counts.append(f"不可用: {unavailable:,} 项")
        lines.extend(["", " | ".join(counts)])
    elif status != "finished" or discovery_failed:
        lines = ["[GMI 巡检异常] 巡检未全部完成", "", f"耗时: {duration}"]
    elif scheduled:
        outcome = (
            "未执行探活" if not checked else "探活正常" if available == checked
            else f"探活: {checked:,} 项 ({available:,} 可用 / {unavailable:,} 不可用 / {unknown:,} 未判定)"
        )
        lines = [
            "[GMI 调度心跳] 巡检完成", "",
            "• 未检测到版本变动", "",
            f"• 耗时: {duration} | {outcome}", "",
            "(10 分钟后自动销毁)",
        ]
        delete_after = DEFAULT_TRANSIENT_DELETE_SECONDS
    else:
        return None, None

    if discovery_failed:
        lines.extend(["", f"• 官方发现失败: {discovery_failed:,} 项"])
    if status != "finished":
        lines.extend(["", "• 任务已取消" if status == "cancelled" else "• 任务失败"])
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 24].rstrip() + "\n...其余内容已省略"
    return text, delete_after


def _send_one(token: str, chat_id: str, text: str) -> int | None:
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        API_URL.format(token=token, method="sendMessage"),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read(64_000).decode("utf-8", "replace"))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Telegram sendMessage returned an unsuccessful response")
    message = payload.get("result")
    message_id = message.get("message_id") if isinstance(message, dict) else None
    return message_id if isinstance(message_id, int) else None


def _delete_one(token: str, chat_id: str, message_id: int) -> None:
    body = urllib.parse.urlencode({"chat_id": chat_id, "message_id": message_id}).encode("utf-8")
    request = urllib.request.Request(
        API_URL.format(token=token, method="deleteMessage"),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read(64_000).decode("utf-8", "replace"))
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("Telegram deleteMessage returned an unsuccessful response")


def _delete_later(token: str, chat_id: str, message_id: int, seconds: int) -> None:
    def worker() -> None:
        try:
            time.sleep(seconds)
            _delete_one(token, chat_id, message_id)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            LOGGER.warning("Telegram transient message deletion failed: %s", "request_error")

    threading.Thread(target=worker, name="gmi-telegram-delete", daemon=True).start()


def notify_operation(
    result: Mapping[str, Any], *, started_at: object, finished_at: object,
    scheduled: bool, status: str = "finished", environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Send one operation summary; missing configuration and failures are non-fatal."""
    text, delete_after = build_message(
        result, started_at=started_at, finished_at=finished_at,
        scheduled=scheduled, status=status,
    )
    if text is None:
        return []
    values = os.environ if environ is None else environ
    token = values.get("GMI_TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = _split_chat_ids(values.get("GMI_TELEGRAM_CHAT_ID"))
    if not token or not chat_ids:
        return []

    results: list[dict[str, Any]] = []
    for chat_id in chat_ids:
        try:
            message_id = _send_one(token, chat_id, text)
            if delete_after is not None and message_id is not None:
                _delete_later(token, chat_id, message_id, delete_after)
        except Exception:  # noqa: BLE001 - never log token-bearing request/exception text
            LOGGER.warning("Telegram notification failed for configured target: request_error")
            results.append({"chat_id": chat_id, "ok": False})
        else:
            results.append({"chat_id": chat_id, "ok": True})
    return results


__all__ = ["build_message", "notify_operation"]
