"""Canonical schema-v2 probe orchestration used by admin routes and jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from backend.indexes import rebuild_index
from backend.schema_v2 import validate_v2_record
from backend.storage_locks import DATA_LOCK
from backend.version_store import persist_v2_record
from probe_adapters.common import ProbeError
from probe_adapters.service import apply_result as default_apply_result
from probe_adapters.service import probe as default_probe


ProbeCallable = Callable[..., dict[str, Any]]
ApplyCallable = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
ADMIN_PROBE_LOCK = RLock()


class AdminProbeDataError(Exception):
    """Canonical data cannot be safely selected for an admin mutation."""


def stable_url_id(artifact_id: str, url_index: int, url: str) -> int:
    material = "\x1f".join(str(part) for part in (artifact_id, url_index, url)).encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:12], 16)


def valid_probe_url(value: str) -> bool:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 8192:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _ordinary(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_record_path(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    if len(relative.parts) != 4:
        return False
    current = root.absolute()
    for part in relative.parts[:-1]:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            return False
    return _ordinary(path)


def iter_records(root: Path, *, scopes: Iterable[str] = ("android", "pc")):
    root = Path(root).absolute()
    for disk in scopes:
        for path in root.glob(f"*/*/{disk}/*.json"):
            if path.name == "index.json":
                continue
            if not _safe_record_path(root, path):
                raise AdminProbeDataError("canonical record path is unsafe")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                validate_v2_record(value)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                raise AdminProbeDataError("canonical record is invalid") from error
            expected_platform = "android" if disk == "android" else "windows"
            expected = {
                "vendor": path.parent.parent.parent.name,
                "game_id": path.parent.parent.name,
                "platform": expected_platform,
                "domain_id": f"{path.parent.parent.name}-{'android' if disk == 'android' else 'pc'}",
                "version": path.stem,
            }
            if any(value.get(key) != wanted for key, wanted in expected.items()):
                raise AdminProbeDataError("canonical record identity does not match its path")
            yield path, value


def candidates(record: dict[str, Any]):
    for artifact_index, artifact in enumerate(record.get("artifacts", [])):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact_id"), str):
            continue
        for url_index, candidate in enumerate(artifact.get("urls", [])):
            if isinstance(candidate, dict) and isinstance(candidate.get("url"), str):
                yield artifact_index, url_index, artifact, candidate


def _expected_size(artifact: dict[str, Any]) -> int | None:
    # A file-manifest artifact's size describes the expanded resource set,
    # not the manifest/index candidate itself. Archive/direct candidates use
    # their canonical artifact size as the expected response size.
    value = None if artifact.get("delivery_mode") == "file_manifest" else artifact.get("size")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _context(artifact: dict[str, Any]) -> dict[str, Any]:
    attributes = artifact.get("attributes") if isinstance(artifact.get("attributes"), dict) else {}
    return {
        "kind": artifact.get("kind"), "part": artifact.get("part"),
        "component": artifact.get("component") or attributes.get("component"),
        "package_type": artifact.get("package_type") or attributes.get("package_type"),
    }


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return "invalid-url"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return "invalid-url"
    host = parsed.hostname
    if port:
        host += f":{port}"
    safe = urlunsplit((parsed.scheme, host, parsed.path[:512], "", ""))
    return safe[:768]


def _safe_reason(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)[:1000]
    return re.sub(r"https?://[^\s]+", lambda match: _safe_url(match.group(0)), text)


def _public_result(requested_url: str, result: dict[str, Any] | None, error: Exception | None, *, persisted: bool, artifact_url_id: int | None = None) -> dict[str, Any]:
    public_url = _safe_url(requested_url)
    if error is not None:
        return {
            "url": public_url, "ok": False,
            "status": getattr(error, "status", None),
            "error": type(error).__name__, "reason": "probe_failed",
            "persisted": False, "adapter": getattr(error, "adapter", None),
            **({"artifact_url_id": artifact_url_id} if artifact_url_id is not None else {}),
        }
    assert result is not None
    return {
        "url": public_url, "ok": True,
        "status": result.get("http_code"), "error": None,
        "reason": _safe_reason(result.get("reason")), "content_type": result.get("content_type"),
        "size": result.get("observed_size", result.get("size")),
        "etag": result.get("etag"), "last_modified": result.get("last_modified"),
        "checked_at": result.get("checked_at"), "persisted": persisted,
        "adapter": result.get("adapter"),
        **({"artifact_url_id": artifact_url_id} if artifact_url_id is not None else {}),
    }


def _run_probe(record: dict[str, Any], artifact_index: int, url_index: int, artifact: dict[str, Any], url: str, timeout: int, probe_fn: ProbeCallable) -> dict[str, Any]:
    result = probe_fn(
        url, vendor=record.get("vendor"), game_id=record.get("game_id"),
        platform=record.get("platform"), timeout=timeout,
        expected_size=_expected_size(artifact), context=_context(artifact),
    )
    return {**result, "target_url": url, "artifact_index": artifact_index, "url_index": url_index}


def _domain(record: dict[str, Any]) -> tuple[str, str, str]:
    return record["vendor"], record["game_id"], record["platform"]


def _apply_and_persist(root: Path, path: Path, result: dict[str, Any], apply_fn: ApplyCallable) -> dict[str, Any]:
    # All admin mutations share one process boundary; VersionStore supplies
    # the cross-process lock and preserves the existing is_visible field.
    with ADMIN_PROBE_LOCK, DATA_LOCK:
        latest = json.loads(path.read_text(encoding="utf-8"))
        validate_v2_record(latest)
        updated = apply_fn(latest, result)
        persist_v2_record(updated, root)
        return updated


def locate_public_url(root: Path, artifact_url_id: int) -> tuple[Path, dict[str, Any], int, int, dict[str, Any], str]:
    matches = []
    for path, record in iter_records(root):
        if record.get("is_visible") is False:
            continue
        for ai, ui, artifact, candidate in candidates(record):
            url = candidate["url"]
            if stable_url_id(artifact["artifact_id"], ui, url) == artifact_url_id:
                matches.append((path, record, ai, ui, artifact, url))
    if not matches:
        raise KeyError(artifact_url_id)
    if len(matches) != 1:
        raise LookupError(artifact_url_id)
    return matches[0]


def probe_direct(url: str, timeout: int, *, probe_fn: ProbeCallable = default_probe) -> dict[str, Any]:
    try:
        result = probe_fn(url, timeout=timeout)
    except (ProbeError, OSError, TypeError, ValueError) as error:
        return _public_result(url, None, error, persisted=False)
    return _public_result(url, result, None, persisted=False)


def probe_public_url(root: Path, url: str, artifact_url_id: int, timeout: int, *, probe_fn: ProbeCallable = default_probe, apply_fn: ApplyCallable = default_apply_result) -> dict[str, Any]:
    path, record, ai, ui, artifact, target = locate_public_url(root, artifact_url_id)
    if target != url:
        raise ValueError("artifact_url_id does not identify the supplied URL")
    try:
        result = _run_probe(record, ai, ui, artifact, target, timeout, probe_fn)
        _apply_and_persist(root, path, result, apply_fn)
        with ADMIN_PROBE_LOCK:
            rebuild_index(root, *_domain(record))
    except (ProbeError, OSError, TypeError, ValueError) as error:
        return _public_result(url, None, error, persisted=False, artifact_url_id=artifact_url_id)
    return _public_result(url, result, None, persisted=True, artifact_url_id=artifact_url_id)


def _probe_record(root: Path, path: Path, record: dict[str, Any], timeout: int, probe_fn: ProbeCallable, apply_fn: ApplyCallable, cancelled: Callable[[], bool]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current = deepcopy(record)
    for ai, ui, artifact, candidate in list(candidates(record)):
        if cancelled():
            break
        url = candidate["url"]
        try:
            result = _run_probe(current, ai, ui, artifact, url, timeout, probe_fn)
            current = _apply_and_persist(root, path, result, apply_fn)
            item = _public_result(url, result, None, persisted=True)
        except (ProbeError, OSError, TypeError, ValueError) as error:
            item = _public_result(url, None, error, persisted=False)
        items.append({
            "game_id": record["game_id"], "version": record["version"],
            "platform": record["platform"], "kind": artifact.get("kind"),
            "artifact_index": ai, "url_index": ui, "adapter": item.get("adapter"),
            "url": _safe_url(url), "ok": item["ok"],
            "available": result.get("available") if item["ok"] else None,
            "error": item.get("error"), "reason": item.get("reason"),
        })
    return items


def selected_records(root: Path, game_ids: list[str], scope: str, *, domain_id: str | None = None, version: str | None = None):
    scopes = ("android", "pc") if scope == "all" else (scope,)
    chosen = set(game_ids)
    result = []
    for path, record in iter_records(root, scopes=scopes):
        if record["game_id"] not in chosen:
            continue
        if domain_id is not None and record.get("domain_id") != domain_id:
            continue
        if version is not None and record.get("version") != version:
            continue
        result.append((path, record))
    return result


def probe_records(root: Path, records: list[tuple[Path, dict[str, Any]]], timeout: int, workers: int, *, probe_fn: ProbeCallable = default_probe, apply_fn: ApplyCallable = default_apply_result, progress: Callable[[dict[str, Any], int, int], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
    is_cancelled = cancelled or (lambda: False)
    total = sum(sum(1 for _ in candidates(record)) for _, record in records)
    items: list[dict[str, Any]] = []
    affected: set[tuple[str, str, str]] = set()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(records) or 1))) as pool:
        futures = {
            pool.submit(_probe_record, root, path, record, timeout, probe_fn, apply_fn, is_cancelled): record
            for path, record in records if not is_cancelled()
        }
        for future in as_completed(futures):
            record = futures[future]
            try:
                batch = future.result()
            except Exception as error:  # isolate one corrupt/custom adapter record
                failed_candidates = list(candidates(record))
                batch = [
                    {
                        "game_id": record["game_id"], "version": record["version"], "platform": record["platform"],
                        "kind": artifact.get("kind"), "artifact_index": artifact_index, "url_index": url_index,
                        "url": _safe_url(candidate["url"]), "ok": False, "available": None, "adapter": None,
                        "error": type(error).__name__, "reason": "record_probe_failed",
                    }
                    for artifact_index, url_index, artifact, candidate in failed_candidates
                ]
            for item in batch:
                items.append(item)
                if item.get("ok"):
                    affected.add(_domain(record))
                if progress:
                    progress(item, len(items), total)
    for vendor, game_id, platform in affected:
        with ADMIN_PROBE_LOCK:
            rebuild_index(root, vendor, game_id, platform)
    return {
        "checked": len(items), "selected": total,
        "available": sum(item.get("available") is True for item in items),
        "available_urls": sum(item.get("available") is True for item in items),
        "unavailable": sum(item.get("available") is False for item in items),
        "unknown": sum(item.get("ok") and item.get("available") is None for item in items),
        "failed": sum(not item.get("ok") for item in items),
        "cancelled": is_cancelled(), "checked_urls": len(items), "items": items,
    }


__all__ = ["ADMIN_PROBE_LOCK", "AdminProbeDataError", "candidates", "iter_records", "locate_public_url", "probe_direct", "probe_public_url", "probe_records", "selected_records", "stable_url_id", "valid_probe_url"]
