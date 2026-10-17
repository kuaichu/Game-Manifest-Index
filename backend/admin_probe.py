"""Canonical schema-v2 probe orchestration used by admin routes and jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from backend.activity_store import ActivityStore
from backend.admin_state import BoundedItems
from backend.catalog_admin import configured_nondefault_pc_domains, is_configured_nondefault_pc_domain
from backend.domain_registry import is_nondefault_pc_domain, nondefault_pc_domains
from backend.schema_v2 import record_identity, validate_v2_record
from backend.version_store import record_index_transaction, write_v2_record
from probe_adapters.common import ProbeError
from probe_adapters.service import current_from_result as default_current
from probe_adapters.service import probe as default_probe


ProbeCallable = Callable[..., dict[str, Any]]
CurrentCallable = Callable[[dict[str, str], str, dict[str, Any]], dict[str, Any]]
CandidateFilter = Callable[[dict[str, Any], int, int, dict[str, Any], dict[str, Any]], bool]
ADMIN_PROBE_LOCK = RLock()
LOGGER = logging.getLogger(__name__)


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
    default_path = len(relative.parts) == 4
    secondary_path = (
        len(relative.parts) == 6
        and relative.parts[2:4] == ("pc", "domains")
        and (
            is_nondefault_pc_domain(
                relative.parts[0], relative.parts[1], relative.parts[4],
            )
            or is_configured_nondefault_pc_domain(
                root, relative.parts[0], relative.parts[1], relative.parts[4],
            )
        )
    )
    if not default_path and not secondary_path:
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
        paths = list(root.glob(f"*/*/{disk}/*.json"))
        if disk == "pc":
            for game_dir in root.glob("*/*"):
                vendor = game_dir.parent.name
                game_id = game_dir.name
                for domain_id in (
                    *nondefault_pc_domains(vendor, game_id),
                    *configured_nondefault_pc_domains(root, vendor, game_id),
                ):
                    paths.extend(
                        (game_dir / "pc" / "domains" / domain_id).glob("*.json")
                    )
        for path in paths:
            if path.name == "index.json":
                continue
            if not _safe_record_path(root, path):
                raise AdminProbeDataError("canonical record path is unsafe")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                validate_v2_record(value)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                raise AdminProbeDataError("canonical record is invalid") from error
            relative = path.relative_to(root)
            expected_platform = "android" if disk == "android" else "windows"
            expected = {
                "vendor": relative.parts[0],
                "game_id": relative.parts[1],
                "platform": expected_platform,
                "domain_id": (
                    relative.parts[4]
                    if len(relative.parts) == 6
                    else f"{relative.parts[1]}-{'android' if disk == 'android' else 'pc'}"
                ),
                "version": path.stem,
            }
            if any(value.get(key) != wanted for key, wanted in expected.items()):
                raise AdminProbeDataError("canonical record identity does not match its path")
            yield path, value


def candidates(record: dict[str, Any]):
    # Azur Promilia's launcher CDN has no registered PC probe adapter yet.
    # Keep its checked-in URLs browsable without scheduling unsupported probes.
    if record.get("vendor") == "manjuu" and record.get("game_id") == "azurpromilia":
        return
    endfield_pc = (
        record.get("vendor") == "hypergryph"
        and record.get("game_id") == "endfield"
        and record.get("platform") == "windows"
    )
    for artifact_index, artifact in enumerate(record.get("artifacts", [])):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("artifact_id"), str):
            continue
        # Endfield runtime VFS files (.chk/.blc) are historical resources,
        # not downloadable archives. Keep them visible in the archive but
        # never enqueue them for URL probing.
        if endfield_pc and (
            record.get("domain_id") == "endfield-resources"
            or artifact.get("kind") not in {"package", "patch"}
            or artifact.get("component") == "resource"
        ):
            continue
        for url_index, candidate in enumerate(artifact.get("urls", [])):
            if (
                isinstance(candidate, dict)
                and candidate.get("source_kind") != "mirror"
                and isinstance(candidate.get("url"), str)
            ):
                if endfield_pc:
                    try:
                        path = urlsplit(candidate["url"]).path.lower()
                    except ValueError:
                        continue
                    if not re.search(r"\.(?:zip|7z)(?:\.\d+)?$", path) or "/resource/windows/" in path:
                        continue
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


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in candidate.items() if key != "current"}


def _artifact_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in artifact.items() if key != "urls"}


@dataclass(frozen=True)
class _ProbeSelection:
    record: dict[str, Any]
    identity: dict[str, str]
    artifact_id: str
    artifact: dict[str, Any]
    candidate: dict[str, Any]
    provenance: Any

    def resolve(self, latest: dict[str, Any]) -> tuple[int, int]:
        """Rebind list positions only when ownership and probe inputs still match."""
        if record_identity(latest) != self.identity or latest.get("provenance") != self.provenance:
            raise ValueError("probe record identity changed")
        for ai, artifact in enumerate(latest["artifacts"]):
            if artifact["artifact_id"] != self.artifact_id:
                continue
            if _artifact_metadata(artifact) != self.artifact:
                break
            matches = [
                ui for ui, candidate in enumerate(artifact["urls"])
                if _candidate_identity(candidate) == self.candidate
            ]
            if len(matches) == 1:
                return ai, matches[0]
            break
        raise ValueError("probe target changed before commit")


def _run_probe(record: dict[str, Any], artifact_index: int, url_index: int, artifact: dict[str, Any], url: str, timeout: int, probe_fn: ProbeCallable) -> tuple[_ProbeSelection, dict[str, Any]]:
    selection = _ProbeSelection(
        record, record_identity(record), artifact["artifact_id"],
        _artifact_metadata(artifact),
        _candidate_identity(record["artifacts"][artifact_index]["urls"][url_index]),
        deepcopy(record.get("provenance")),
    )
    result = probe_fn(
        url, vendor=record.get("vendor"), game_id=record.get("game_id"),
        platform=record.get("platform"), timeout=timeout,
        expected_size=_expected_size(artifact), context=_context(artifact),
    )
    return selection, result


def _verified_current_state(candidate: dict[str, Any], state: str, now: datetime) -> bool:
    # api_contract imports this module for scheduled candidates, so load its
    # evidence parser only when a completed probe is being persisted.
    from backend.api_contract import _probe_checked_at

    current = candidate.get("current")
    if not isinstance(current, dict) or current.get("state") != state:
        return False
    checked = _probe_checked_at(current)
    # Freshness controls scheduling/display, not whether a known state changed.
    # Normal rounds recheck available URLs only after that freshness expires.
    return checked is not None and checked[1] <= now


def _has_url_state(record: dict[str, Any], state: str, now: datetime, *, every: bool) -> bool:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    found = False
    for artifact in artifacts:
        urls = artifact.get("urls") if isinstance(artifact, dict) else None
        if not isinstance(urls, list) or not urls:
            if every:
                return False
            continue
        for candidate in urls:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("url"), str) or not candidate["url"]:
                if every:
                    return False
                continue
            found = True
            matches = _verified_current_state(candidate, state, now)
            if every and not matches:
                return False
            if not every and matches:
                return True
    return found if every else False


def _record_unavailable_transition(before: dict[str, Any], after: dict[str, Any], activity_store: ActivityStore) -> None:
    now = datetime.now(timezone.utc)
    if not _has_url_state(after, "unavailable", now, every=True):
        return
    if not _has_url_state(before, "available", now, every=False):
        return
    activity_store.append(
        game_id=after["game_id"], domain_id=after["domain_id"],
        platform=after["platform"], version=after["version"],
        event_type="version_unavailable",
    )


def _commit_probe(
    root: Path, path: Path, selection: _ProbeSelection, result: dict[str, Any], current_fn: CurrentCallable,
    *, activity_store: ActivityStore | None = None,
) -> None:
    # Conversion cannot access archive contents or choose a different target.
    current = current_fn(dict(selection.identity), selection.candidate["url"], deepcopy(result))
    with ADMIN_PROBE_LOCK:
        with record_index_transaction(selection.record, root):
            latest = json.loads(path.read_text(encoding="utf-8"))
            validate_v2_record(latest)
            ai, ui = selection.resolve(latest)
            updated = {**latest, "artifacts": list(latest["artifacts"])}
            artifact = {**latest["artifacts"][ai], "urls": list(latest["artifacts"][ai]["urls"])}
            artifact["urls"][ui] = {**artifact["urls"][ui], "current": current}
            updated["artifacts"][ai] = artifact
            write_v2_record(updated, root, overwrite=True)
        # Publish activity only after the record and index have committed.
        if activity_store is not None:
            try:
                _record_unavailable_transition(latest, updated, activity_store)
            except Exception:  # activity history cannot fail a completed probe
                LOGGER.warning("Could not persist version-unavailable activity", exc_info=True)


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


def probe_public_url(root: Path, url: str, artifact_url_id: int, timeout: int, *, probe_fn: ProbeCallable = default_probe, current_fn: CurrentCallable = default_current, activity_store: ActivityStore | None = None) -> dict[str, Any]:
    path, record, ai, ui, artifact, target = locate_public_url(root, artifact_url_id)
    if target != url:
        raise ValueError("artifact_url_id does not identify the supplied URL")
    try:
        selection, result = _run_probe(record, ai, ui, artifact, target, timeout, probe_fn)
        _commit_probe(root, path, selection, result, current_fn, activity_store=activity_store)
    except (ProbeError, OSError, TypeError, ValueError) as error:
        return _public_result(url, None, error, persisted=False, artifact_url_id=artifact_url_id)
    return _public_result(url, result, None, persisted=True, artifact_url_id=artifact_url_id)


def _filtered_candidates(record: dict[str, Any], candidate_filter: CandidateFilter | None) -> list[tuple[int, int, dict[str, Any], dict[str, Any]]]:
    values = list(candidates(record))
    if candidate_filter is None:
        return values
    return [item for item in values if candidate_filter(record, *item)]


def _probe_record(root: Path, path: Path, record: dict[str, Any], timeout: int, probe_fn: ProbeCallable, current_fn: CurrentCallable, cancelled: Callable[[], bool], candidate_filter: CandidateFilter | None = None, activity_store: ActivityStore | None = None):
    for ai, ui, artifact, candidate in _filtered_candidates(record, candidate_filter):
        if cancelled():
            break
        url = candidate["url"]
        try:
            selection, result = _run_probe(record, ai, ui, artifact, url, timeout, probe_fn)
            _commit_probe(root, path, selection, result, current_fn, activity_store=activity_store)
            item = _public_result(url, result, None, persisted=True)
        except (ProbeError, OSError, TypeError, ValueError) as error:
            item = _public_result(url, None, error, persisted=False)
        yield {
            "game_id": record["game_id"], "version": record["version"],
            "platform": record["platform"], "kind": artifact.get("kind"),
            "artifact_index": ai, "url_index": ui, "adapter": item.get("adapter"),
            "url": _safe_url(url), "ok": item["ok"],
            "available": result.get("available") if item["ok"] else None,
            "error": item.get("error"), "reason": item.get("reason"),
        }


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


def probe_records(root: Path, records: list[tuple[Path, dict[str, Any]]], timeout: int, workers: int, *, probe_fn: ProbeCallable = default_probe, current_fn: CurrentCallable = default_current, progress: Callable[[dict[str, Any], int, int], None] | None = None, cancelled: Callable[[], bool] | None = None, candidate_filter: CandidateFilter | None = None, activity_store: ActivityStore | None = None) -> dict[str, Any]:
    is_cancelled = cancelled or (lambda: False)
    total = sum(len(_filtered_candidates(record, candidate_filter)) for _, record in records)
    details = BoundedItems()
    counts = {"checked": 0, "available": 0, "unavailable": 0, "unknown": 0, "failed": 0}
    result_lock = RLock()

    def consume(item: dict[str, Any]) -> None:
        with result_lock:
            counts["checked"] += 1
            counts["available"] += int(item.get("available") is True)
            counts["unavailable"] += int(item.get("available") is False)
            counts["unknown"] += int(bool(item.get("ok")) and item.get("available") is None)
            counts["failed"] += int(not item.get("ok"))
            details.append(item)
            if progress:
                progress(item, counts["checked"], total)

    def record_outcomes(path: Path, record: dict[str, Any]):
        done = 0
        try:
            for item in _probe_record(root, path, record, timeout, probe_fn, current_fn, is_cancelled, candidate_filter, activity_store):
                done += 1
                yield item
        except Exception as error:  # isolate one corrupt/custom adapter record
            for index, (artifact_index, url_index, artifact, candidate) in enumerate(_filtered_candidates(record, candidate_filter)):
                if index >= done:
                    yield {
                        "game_id": record["game_id"], "version": record["version"], "platform": record["platform"],
                        "kind": artifact.get("kind"), "artifact_index": artifact_index, "url_index": url_index,
                        "url": _safe_url(candidate["url"]), "ok": False, "available": None, "adapter": None,
                        "error": type(error).__name__, "reason": "record_probe_failed",
                    }

    def run_record(path: Path, record: dict[str, Any]) -> None:
        for item in record_outcomes(path, record):
            consume(item)

    worker_count = max(1, min(workers, len(records) or 1))
    remaining = iter(records)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = set()
        while True:
            while len(futures) < worker_count and not is_cancelled():
                selected = next(remaining, None)
                if selected is None:
                    break
                futures.add(pool.submit(run_record, *selected))
            if not futures:
                break
            completed, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                future.result()
    return {
        **counts, "selected": total,
        "available_urls": counts["available"],
        "cancelled": is_cancelled(), "checked_urls": counts["checked"], **details.result(),
    }


__all__ = ["ADMIN_PROBE_LOCK", "AdminProbeDataError", "candidates", "iter_records", "locate_public_url", "probe_direct", "probe_public_url", "probe_records", "selected_records", "stable_url_id", "valid_probe_url"]
