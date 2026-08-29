"""Small, hardened JSON state store for admin schedules and job snapshots."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping


MAX_STATE_BYTES = 2 * 1024 * 1024
DEFAULT_SCHEDULES = {
    "sync": {"enabled": False, "times": []},
    "probe": {"enabled": False, "interval_hours": 24, "mode": "normal"},
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class AdminStateError(RuntimeError):
    """Admin state cannot be read or written safely."""


def _unsafe(path: Path, mode: int) -> bool:
    return stat.S_ISLNK(mode) or bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)


def _ensure_directory(path: Path) -> Path:
    path = path.absolute()
    current = Path(path.anchor)
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                current.mkdir()
                info = os.lstat(current)
            except OSError as error:
                raise AdminStateError("cannot create admin state directory") from error
        except OSError as error:
            raise AdminStateError("admin state root is unavailable") from error
        if _unsafe(current, info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise AdminStateError("admin state path contains a symlink/reparse point")
    return path


def _ordinary(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise AdminStateError("cannot inspect admin state file") from error
    return stat.S_ISREG(info.st_mode) and not _unsafe(path, info.st_mode)


class AdminStateStore:
    """Thread-safe, bounded, atomic persistence below a dedicated state root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self._lock = RLock()

    def _path(self, name: str) -> Path:
        if name not in {"schedules", "latest_operation"}:
            raise ValueError("unknown admin state document")
        directory = _ensure_directory(self.root / "admin")
        return directory / f"{name}.json"

    def read(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            path = self._path(name)
            if not path.exists() and not path.is_symlink():
                return None
            if not _ordinary(path):
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
            if (path.exists() or path.is_symlink()) and not _ordinary(path):
                raise AdminStateError("admin state file is not an ordinary file")
            descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except OSError as error:
                raise AdminStateError("cannot persist admin state") from error
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

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


__all__ = ["AdminStateError", "AdminStateStore", "DEFAULT_SCHEDULES", "MAX_STATE_BYTES"]
