"""Small, hardened JSON state store for admin schedules and job snapshots."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from backend.fs_safety import UnsafePathError, atomic_write_bytes, ensure_directory, is_ordinary


MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_RESULT_ITEM_BYTES = 512 * 1024


class BoundedItems:
    """Keep complete result items within a byte budget, with explicit omissions."""

    def __init__(self, budget: int = MAX_RESULT_ITEM_BYTES) -> None:
        self.budget = budget
        self.items: list[dict[str, Any]] = []
        self.total = 0
        self._bytes = 2

    def append(self, item: dict[str, Any]) -> None:
        self.total += 1
        if self.total != len(self.items) + 1:
            return
        size = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        # Preserve a prefix so displayed detail order remains meaningful.
        if self._bytes + size <= self.budget:
            self.items.append(item)
            self._bytes += size

    def result(self) -> dict[str, Any]:
        value: dict[str, Any] = {"items": self.items}
        if self.total > len(self.items):
            value.update(items_truncated=True, items_total=self.total,
                         items_omitted=self.total - len(self.items))
        return value


DEFAULT_SCHEDULES = {
    "sync": {"enabled": False, "times": []},
    "probe": {"enabled": False, "interval_hours": 24, "mode": "normal"},
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AdminStateError(RuntimeError):
    """Admin state cannot be read or written safely."""


class AdminStateStore:
    """Thread-safe, bounded, atomic persistence below a dedicated state root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self._lock = RLock()

    def _path(self, name: str) -> Path:
        if name not in {"schedules", "latest_operation", "probe_scheduler"}:
            raise ValueError("unknown admin state document")
        try:
            directory = ensure_directory(self.root / "admin")
        except UnsafePathError as error:
            raise AdminStateError("admin state path contains a symlink/reparse point") from error
        except OSError as error:
            raise AdminStateError("cannot create admin state directory") from error
        return directory / f"{name}.json"

    def read(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            path = self._path(name)
            if not is_ordinary(path):
                try:
                    os.lstat(path)
                except FileNotFoundError:
                    return None
                except OSError as error:
                    raise AdminStateError("cannot inspect admin state file") from error
                raise AdminStateError("admin state file is not an ordinary file")
            try:
                if path.stat().st_size > MAX_STATE_BYTES:
                    raise AdminStateError("admin state file is too large")
                value = json.loads(path.read_text(encoding="utf-8"))
            except AdminStateError:
                raise
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise AdminStateError("admin state file is invalid") from error
            if not isinstance(value, dict):
                raise AdminStateError("admin state document must be an object")
            return value

    def write(self, name: str, value: Mapping[str, Any]) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = raw.encode("utf-8")
        if len(encoded) > MAX_STATE_BYTES:
            raise AdminStateError("admin state document is too large")
        with self._lock:
            path = self._path(name)
            if not is_ordinary(path):
                try:
                    os.lstat(path)
                except FileNotFoundError:
                    pass
                except OSError as error:
                    raise AdminStateError("cannot inspect admin state file") from error
                else:
                    raise AdminStateError("admin state file is not an ordinary file")
            try:
                atomic_write_bytes(path, encoded)
            except OSError as error:
                raise AdminStateError("cannot persist admin state") from error

    def schedules(self) -> dict[str, Any]:
        stored = self.read("schedules") or {}
        if any(name not in DEFAULT_SCHEDULES for name in stored):
            raise AdminStateError("admin schedules contain unknown fields")
        result = deepcopy(DEFAULT_SCHEDULES)
        for name in ("sync", "probe"):
            if name not in stored:
                continue
            value = stored[name]
            if not isinstance(value, dict) or set(value) != set(DEFAULT_SCHEDULES[name]):
                raise AdminStateError("admin schedule has an invalid shape")
            result[name].update(value)
        sync = result["sync"]
        times = sync.get("times")
        if (
            not isinstance(sync.get("enabled"), bool)
            or not isinstance(times, list)
            or len(times) > 2
            or any(not isinstance(item, str) or TIME_RE.fullmatch(item) is None for item in times)
            or times != sorted(set(times))
            or (sync["enabled"] and not times)
        ):
            raise AdminStateError("admin sync schedule is invalid")
        probe = result["probe"]
        interval = probe.get("interval_hours")
        if (
            not isinstance(probe.get("enabled"), bool)
            or isinstance(interval, bool)
            or not isinstance(interval, int)
            or not 1 <= interval <= 168
            or probe.get("mode") not in {"normal", "full"}
        ):
            raise AdminStateError("admin probe schedule is invalid")
        return result

    def write_schedule(self, name: str, value: Mapping[str, Any]) -> dict[str, Any]:
        if name not in DEFAULT_SCHEDULES:
            raise ValueError("unknown schedule")
        with self._lock:
            schedules = self.schedules()
            schedules[name] = dict(value)
            self.write("schedules", schedules)
        return deepcopy(schedules[name])


__all__ = ["AdminStateError", "AdminStateStore", "BoundedItems", "DEFAULT_SCHEDULES", "MAX_STATE_BYTES"]
