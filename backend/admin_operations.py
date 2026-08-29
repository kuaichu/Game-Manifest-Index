"""Single active asynchronous admin discovery/probe operation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
from uuid import uuid4

from backend.admin_probe import ADMIN_PROBE_LOCK, candidates, probe_records, selected_records
from backend.admin_state import AdminStateError, AdminStateStore
from backend.indexes import rebuild_index
from url_adapters.service import DISCOVERERS, PC_DISCOVERERS, discover_games


Clock = Callable[[], datetime]
JOB_FIELDS = {
    "job_id", "status", "phase", "actions", "game_ids", "scope",
    "completed", "total", "phase_completed", "phase_total", "succeeded", "failed",
    "current", "started_at", "finished_at", "result", "error", "logs",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(clock: Clock) -> str:
    value = clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_discover_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_id": item.get("game_id"), "platform": item.get("platform"),
        "scope": item.get("scope"), "ok": bool(item.get("ok")),
        "supported": item.get("supported"), "status": item.get("status"),
        "skipped": item.get("skipped", False), "version": item.get("version"),
        "new": bool(item.get("new")), "available": item.get("available"),
        "path": None, "error": "discovery_failed" if item.get("error") else None,
    }


def _valid_job_snapshot(value: dict[str, Any]) -> bool:
    counters = ("completed", "total", "phase_completed", "phase_total", "succeeded", "failed")
    actions = value.get("actions")
    games = value.get("game_ids")
    current = value.get("current")
    logs = value.get("logs")
    return (
        set(value) == JOB_FIELDS
        and isinstance(value.get("job_id"), str) and 0 < len(value["job_id"]) <= 128
        and value.get("status") in {"running", "cancelling", "cancelled", "finished", "failed"}
        and value.get("phase") in {None, "discover", "probe"}
        and isinstance(actions, list) and 0 < len(actions) <= 2
        and all(isinstance(action, str) and action in {"discover", "probe"} for action in actions)
        and len(set(actions)) == len(actions)
        and isinstance(games, list) and all(isinstance(game, str) and game for game in games)
        and len(set(games)) == len(games)
        and value.get("scope") in {"all", "android", "pc"}
        and all(isinstance(value.get(name), int) and not isinstance(value.get(name), bool) and value[name] >= 0 for name in counters)
        and (
            current is None
            or isinstance(current, dict)
            and set(current) <= {"action", "game_id", "version"}
            and current.get("action") in {"discover", "probe"}
            and all(current.get(name) is None or isinstance(current.get(name), str) for name in ("game_id", "version"))
        )
        and isinstance(value.get("started_at"), str) and bool(value["started_at"])
        and (value.get("finished_at") is None or isinstance(value.get("finished_at"), str))
        and (value.get("result") is None or isinstance(value.get("result"), dict))
        and (value.get("error") is None or isinstance(value.get("error"), str))
        and isinstance(logs, list) and all(isinstance(line, str) and len(line) <= 500 for line in logs)
    )


class OperationManager:
    def __init__(self, store: AdminStateStore, data_root: Path, *, discovery: Callable[..., dict[str, Any]] = discover_games, probe_fn: Callable[..., dict[str, Any]] | None = None, apply_fn: Callable[..., dict[str, Any]] | None = None, clock: Clock = utc_now) -> None:
        self.store = store
        self.data_root = Path(data_root)
        self.discovery = discovery
        self.probe_fn = probe_fn
        self.apply_fn = apply_fn
        self.clock = clock
        self._lock = RLock()
        self._cancel = Event()
        self._job: dict[str, Any] | None = None
        self._restore()

    def _restore(self) -> None:
        try:
            value = self.store.read("latest_operation")
        except AdminStateError:
            return
        if not isinstance(value, dict) or not _valid_job_snapshot(value):
            return
        if value.get("status") in {"running", "cancelling"}:
            value["status"] = "failed"
            value["phase"] = None
            value["finished_at"] = _timestamp(self.clock)
            value["current"] = None
            value["error"] = "operation_interrupted_by_restart"
            value.setdefault("logs", []).append("服务重启，未完成任务已标记失败")
            self.store.write("latest_operation", value)
        self._job = value

    def _save(self) -> None:
        if self._job is not None:
            value = deepcopy(self._job)
            value.pop("_phase_failed", None)
            self.store.write("latest_operation", value)

    def _view(self, after: int | None = None) -> dict[str, Any]:
        if self._job is None:
            raise KeyError("latest")
        value = deepcopy(self._job)
        value.pop("_phase_failed", None)
        logs = value.get("logs") if isinstance(value.get("logs"), list) else []
        value["log_total"] = len(logs)
        if after is not None:
            if after < 0 or after > len(logs):
                raise ValueError("log cursor out of range")
            value["logs"] = logs[after:]
            value["log_offset"] = after
        return value

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return self._view()

    def status(self, job_id: str, after: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._job is None or self._job.get("job_id") != job_id:
                raise KeyError(job_id)
            return self._view(after)

    def start(self, actions: list[str], game_ids: list[str], scope: str, timeout: int, workers: int) -> dict[str, Any]:
        with self._lock:
            if self._job is not None and self._job.get("status") in {"running", "cancelling"}:
                raise RuntimeError("operation_already_running")
            self._cancel = Event()
            discover_total = sum(len([g for g in game_ids if g in registry]) for registry in ((DISCOVERERS,) if scope == "android" else (PC_DISCOVERERS,) if scope == "pc" else (DISCOVERERS, PC_DISCOVERERS))) if "discover" in actions else 0
            records = selected_records(self.data_root, game_ids, scope) if "probe" in actions else []
            probe_total = sum(sum(1 for _ in candidates(record)) for _, record in records)
            self._job = {
                "job_id": uuid4().hex[:16], "status": "running",
                "phase": actions[0], "actions": list(actions), "game_ids": list(game_ids), "scope": scope,
                "completed": 0, "total": discover_total + probe_total,
                "phase_completed": 0, "phase_total": discover_total if actions[0] == "discover" else probe_total,
                "succeeded": 0, "failed": 0, "current": None,
                "started_at": _timestamp(self.clock), "finished_at": None,
                "result": None, "error": None, "logs": [f"任务启动 scope={scope}"],
            }
            self._save()
            job_id = self._job["job_id"]
            Thread(target=self._run, args=(job_id, actions, game_ids, scope, timeout, workers), daemon=True).start()
            return self._view()

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if self._job is None or self._job.get("job_id") != job_id:
                raise KeyError(job_id)
            if self._job["status"] == "running":
                self._cancel.set()
                self._job["status"] = "cancelling"
                self._log("已请求取消；当前网络请求结束后停止")
                self._save()
            return self._view()

    def _log(self, message: str) -> None:
        if self._job is not None:
            logs = self._job.setdefault("logs", [])
            logs.append(str(message)[:500])

    def _phase(self, job_id: str, name: str, base: int, total: int) -> None:
        with self._lock:
            if self._job is None or self._job["job_id"] != job_id:
                return
            self._job.update({"phase": name, "phase_completed": 0, "phase_total": total, "completed": base})
            self._log(f"开始 {name}，共 {total} 项")
            self._save()

    @staticmethod
    def _probe_outcome(item: dict[str, Any]) -> str:
        if not item.get("ok"):
            return f"探活失败:{item.get('error') or 'unknown'}"
        if item.get("available") is True:
            return "可用"
        if item.get("available") is False:
            return "失效"
        return "未判定"

    def _progress(self, job_id: str, phase: str, base_completed: int, base_failed: int, item: dict[str, Any], done: int, total: int) -> None:
        with self._lock:
            if self._job is None or self._job["job_id"] != job_id:
                return
            phase_failed = self._job.get("_phase_failed", 0) + int(not item.get("ok"))
            self._job["_phase_failed"] = phase_failed
            self._job.update({
                "phase": phase, "phase_completed": done, "phase_total": total,
                "completed": base_completed + done, "failed": base_failed + phase_failed,
                "succeeded": base_completed + done - base_failed - phase_failed,
                "current": {"action": phase, "game_id": item.get("game_id"), "version": item.get("version")},
            })
            target = item.get("game_id") or "-"
            platform = item.get("platform") or "-"
            if phase == "probe":
                head = f"[{phase}/{platform}] {target}"
                if item.get("version"):
                    head += f" v{item['version']}"
                if item.get("kind"):
                    head += f" {item['kind']}"
                self._log(f"{head} {self._probe_outcome(item)}")
            else:
                outcome = "成功" if item.get("ok") else f"失败:{item.get('error') or 'unknown'}"
                self._log(f"[{phase}/{platform}] {target} {outcome}")
            self._save()

    def _discover_scope(self, scope: str, game_ids: list[str], timeout: int, workers: int, progress: Callable[[dict[str, Any], int, int], None]) -> dict[str, Any]:
        selected = [game for game in game_ids if game in (DISCOVERERS if scope == "android" else PC_DISCOVERERS)]
        if not selected:
            return {"selected": 0, "succeeded": 0, "failed": 0, "new_versions": 0, "cancelled": self._cancel.is_set(), "items": []}
        # Discovery adapters persist canonical records internally.  Hold the
        # same admin mutation boundary used by manual and batch probe writes.
        with ADMIN_PROBE_LOCK:
            return self.discovery(selected, self.data_root, timeout, workers, scope=scope, progress=progress, cancelled=self._cancel.is_set)

    def _rebuild_discovered(self, items: list[dict[str, Any]]) -> None:
        successful = {(item.get("game_id"), item.get("platform")) for item in items if item.get("ok")}
        domains: set[tuple[str, str, str]] = set()
        for _path, record in selected_records(self.data_root, [game for game, _ in successful if isinstance(game, str)], "all"):
            if (record.get("game_id"), record.get("platform")) in successful:
                domains.add((record["vendor"], record["game_id"], record["platform"]))
        for vendor, game_id, platform in sorted(domains):
            try:
                with ADMIN_PROBE_LOCK:
                    rebuild_index(self.data_root, vendor, game_id, platform)
            except (OSError, TypeError, ValueError):
                for item in items:
                    if item.get("game_id") == game_id and item.get("platform") == platform:
                        item.update({"ok": False, "status": "failed", "error": "index_rebuild_failed"})

    def _run(self, job_id: str, actions: list[str], game_ids: list[str], scope: str, timeout: int, workers: int) -> None:
        result = {"actions": actions, "game_ids": game_ids, "scope": scope, "discover": None, "probe": None}
        completed = failed = 0
        try:
            if "discover" in actions:
                scopes = [scope] if scope != "all" else ["android", "pc"]
                total = sum(len([game for game in game_ids if game in (DISCOVERERS if part == "android" else PC_DISCOVERERS)]) for part in scopes)
                self._phase(job_id, "discover", completed, total)
                raw_items: list[dict[str, Any]] = []
                offset = 0
                for part in scopes:
                    if self._cancel.is_set():
                        break
                    selected = [game for game in game_ids if game in (DISCOVERERS if part == "android" else PC_DISCOVERERS)]
                    try:
                        summary = self._discover_scope(part, game_ids, timeout, workers, lambda item, done, subtotal, o=offset: self._progress(job_id, "discover", completed, failed, item, o + done, total))
                    except Exception:
                        summary = {"items": [{"game_id": game, "platform": "android" if part == "android" else "windows", "ok": False, "supported": True, "status": "failed", "version": None, "new": False, "available": None, "error": "discovery_scope_failed"} for game in selected]}
                        for item_index, item in enumerate(summary["items"], start=1):
                            self._progress(job_id, "discover", completed, failed, item, offset + item_index, total)
                    raw_items.extend(summary.get("items", []))
                    offset += len(summary.get("items", []))
                self._rebuild_discovered(raw_items)
                safe_items = [_safe_discover_item(item) for item in raw_items]
                result["discover"] = {"selected": total, "succeeded": sum(item["ok"] for item in safe_items), "failed": sum(not item["ok"] for item in safe_items), "new_versions": sum(item["new"] for item in safe_items), "cancelled": self._cancel.is_set(), "items": safe_items}
                completed += len(safe_items)
                failed += result["discover"]["failed"]
            if self._cancel.is_set():
                self._finish(job_id, "cancelled", result)
                return
            if "probe" in actions:
                records = selected_records(self.data_root, game_ids, scope)
                probe_total = sum(sum(1 for _ in candidates(record)) for _, record in records)
                with self._lock:
                    if self._job and self._job["job_id"] == job_id:
                        self._job["total"] = completed + probe_total
                        self._job["_phase_failed"] = 0
                self._phase(job_id, "probe", completed, probe_total)
                kwargs: dict[str, Any] = {"progress": lambda item, done, total: self._progress(job_id, "probe", completed, failed, item, done, total), "cancelled": self._cancel.is_set}
                if self.probe_fn is not None:
                    kwargs["probe_fn"] = self.probe_fn
                if self.apply_fn is not None:
                    kwargs["apply_fn"] = self.apply_fn
                result["probe"] = probe_records(self.data_root, records, timeout, workers, **kwargs)
                for item in result["probe"].get("items", []):
                    item.pop("url", None)
                    if "http://" in str(item.get("reason", "")) or "https://" in str(item.get("reason", "")):
                        item["reason"] = "probe_result"
                completed += result["probe"]["checked"]
                failed += result["probe"]["failed"]
            self._finish(job_id, "cancelled" if self._cancel.is_set() else "finished", result)
        except Exception as error:
            self._finish(job_id, "failed", result, type(error).__name__)

    def _finish(self, job_id: str, status: str, result: dict[str, Any], error: str | None = None) -> None:
        with self._lock:
            if self._job is None or self._job["job_id"] != job_id:
                return
            discover = result.get("discover") if isinstance(result.get("discover"), dict) else {}
            probe = result.get("probe") if isinstance(result.get("probe"), dict) else {}
            completed = len(discover.get("items", [])) + int(probe.get("checked", 0) or 0)
            failed = int(discover.get("failed", 0) or 0) + int(probe.get("failed", 0) or 0)
            self._job.update({"status": status, "phase": None, "completed": completed,
                              "succeeded": completed - failed, "failed": failed,
                              "finished_at": _timestamp(self.clock), "result": result,
                              "error": error, "current": None})
            self._job.pop("_phase_failed", None)
            self._log("任务已取消" if status == "cancelled" else "任务完成" if status == "finished" else "任务失败")
            self._save()


__all__ = ["OperationManager", "utc_now"]
