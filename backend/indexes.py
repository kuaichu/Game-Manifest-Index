"""Build and read the small per-game indexes for canonical v2 records."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.storage_locks import DATA_LOCK, data_file_lock


class IndexReadError(ValueError):
    """The index exists but is not a readable index object."""


def _disk_platform(platform: str) -> str:
    if platform == "android":
        return "android"
    if platform in {"pc", "windows"}:
        return "pc"
    raise ValueError("platform must be android, pc, or windows")


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty path component")
    forbidden = set('<>:"/\\|?*')
    if value in {".", ".."} or any(char in forbidden or ord(char) < 32 for char in value):
        raise ValueError(f"{field} is not a safe path component")
    return value


def index_path(root: Path, vendor: str, game_id: str, platform: str) -> Path:
    """Return the index path; ``windows`` is the JSON platform spelling."""
    disk = _disk_platform(platform)
    return Path(root) / _safe_component(vendor, "vendor") / _safe_component(game_id, "game_id") / disk / "index.json"


def _version_key(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value))
    return numbers or (0,)


def _availability(artifact: Mapping[str, Any]) -> bool | None:
    urls = artifact.get("urls")
    if not isinstance(urls, list) or not urls or not isinstance(urls[0], Mapping):
        return None
    current = urls[0].get("current")
    if not isinstance(current, Mapping):
        return None
    state = current.get("state")
    return True if state == "available" else False if state == "unavailable" else None


def _has_browsable_reference(record: Mapping[str, Any]) -> bool:
    references = record.get("references")
    if not isinstance(references, list):
        return False
    for reference in references:
        if not isinstance(reference, Mapping) or reference.get("kind") != "chunk_manifest":
            continue
        path = reference.get("path")
        if not isinstance(path, str) or not path or "\\" in path or "\x00" in path or ":" in path:
            continue
        if path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
            continue
        return True
    return False


def _entry(record: Mapping[str, Any], platform: str) -> dict[str, Any] | None:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    chosen: list[Mapping[str, Any]]
    if platform == "android":
        chosen = [a for a in artifacts if isinstance(a, Mapping) and a.get("kind") == "apk"]
        if not chosen:
            return None
    else:
        game = [a for a in artifacts if isinstance(a, Mapping) and a.get("component") == "game"]
        full = [a for a in game if a.get("package_type") == "full"]
        chosen = full or [a for a in game if a.get("package_type") == "segment"]
        if not chosen and not _has_browsable_reference(record):
            return None
    sizes = [a.get("size") for a in chosen]
    if any(isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in sizes):
        size: int | None = None
    elif platform == "windows" and len(chosen) > 1:
        size = sum(sizes)
    else:
        size = sizes[0] if sizes else None
    states = [_availability(a) for a in chosen]
    if not states:
        available = None
    elif len(states) == 1:
        available = states[0]
    elif any(state is False for state in states):
        available = False
    elif all(state is True for state in states):
        available = True
    else:
        available = None
    return {
        "version": record["version"],
        "updated_at": record.get("updated_at", record.get("file_time")),
        "available": available,
        "size": size,
    }


def _ordinary(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)


def _safe_directory(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)


def _scan(directory: Path, vendor: str, game_id: str, platform: str) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    records: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for path in directory.glob("*.json"):
        if path.name == "index.json" or not _ordinary(path):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping) or value.get("is_visible") is False:
            continue
        if any(value.get(key) != expected for key, expected in (("vendor", vendor), ("game_id", game_id), ("platform", platform))):
            continue
        if not isinstance(value.get("version"), str) or not value["version"]:
            continue
        item = _entry(value, platform)
        if item is not None:
            records.append((value, item))
    records.sort(key=lambda pair: _version_key(pair[0]["version"]), reverse=True)
    return records


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix="index.json.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _rebuild_locked(root: Path, vendor: str, game_id: str, platform: str) -> Path:
    path = index_path(root, vendor, game_id, platform)
    directory = path.parent
    scanned = _scan(directory, vendor, game_id, platform)
    versions = [item for _, item in scanned]
    if not versions:
        if path.exists() or path.is_symlink():
            if not _ordinary(path):
                raise OSError(f"unsafe index path: {path}")
            path.unlink()
        return path
    domain_ids = [record["domain_id"] for record, _ in scanned
                  if isinstance(record.get("domain_id"), str) and record["domain_id"]]
    result: dict[str, Any] = {"vendor": vendor, "game_id": game_id, "platform": "windows" if platform == "windows" else "android", "versions": versions}
    if len(domain_ids) == len(scanned) and domain_ids and len(set(domain_ids)) == 1:
        result["domain_id"] = domain_ids[0]
    _write_atomic(path, result)
    return path


def rebuild_index(root: Path, vendor: str, game_id: str, platform: str) -> Path:
    vendor = _safe_component(vendor, "vendor")
    game_id = _safe_component(game_id, "game_id")
    canonical = "windows" if platform in {"pc", "windows"} else platform
    _disk_platform(canonical)
    root = Path(root)
    if not _safe_directory(root):
        root.mkdir(exist_ok=True)
    if not _safe_directory(root):
        raise OSError(f"unsafe data root: {root}")
    path = index_path(root, vendor, game_id, platform)
    with DATA_LOCK:
        with data_file_lock(root):
            current = root
            for part in (vendor, game_id, "pc" if canonical == "windows" else canonical):
                current = current / part
                if not _safe_directory(current):
                    current.mkdir()
                if not _safe_directory(current):
                    raise OSError(f"unsafe index directory: {current}")
            return _rebuild_locked(root, vendor, game_id, canonical)


def rebuild_indexes(root: Path) -> list[Path]:
    root = Path(root)
    result: list[Path] = []
    if not _safe_directory(root):
        return result
    with DATA_LOCK:
        with data_file_lock(root):
            for vendor_dir in root.iterdir():
                if not _safe_directory(vendor_dir):
                    continue
                for game_dir in vendor_dir.iterdir():
                    if not _safe_directory(game_dir):
                        continue
                    for disk, platform in (("android", "android"), ("pc", "windows")):
                        directory = game_dir / disk
                        if _safe_directory(directory):
                            result.append(_rebuild_locked(root, vendor_dir.name, game_dir.name, platform))
    return result


def read_index(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise IndexReadError(f"invalid index: {path}") from error
    if not _ordinary(path) or not stat.S_ISREG(info.st_mode):
        raise IndexReadError(f"invalid index: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IndexReadError(f"invalid index: {path}") from error
    if not isinstance(value, Mapping) or not isinstance(value.get("versions"), list):
        raise IndexReadError(f"invalid index: {path}")
    return dict(value)


__all__ = ["IndexReadError", "index_path", "rebuild_index", "rebuild_indexes", "read_index"]
