"""Build and read the small per-game indexes for canonical v2 records."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.catalog_admin import configured_nondefault_pc_domains, is_configured_nondefault_pc_domain
from backend.domain_registry import is_nondefault_pc_domain, nondefault_pc_domains
from backend.fs_safety import (
    atomic_write_text,
    disk_platform,
    domain_directory,
    is_ordinary,
    require_safe_component,
    stat_is_ordinary,
)
from backend.storage_locks import DATA_LOCK, data_file_lock


class IndexReadError(ValueError):
    """The index exists but is not a readable index object."""


def index_path(root: Path, vendor: str, game_id: str, platform: str, domain_id: str | None = None) -> Path:
    """Return the index path; ``windows`` is the JSON platform spelling."""
    disk = disk_platform(platform, allow_pc=True)
    vendor = require_safe_component(vendor, "vendor")
    game_id = require_safe_component(game_id, "game_id")
    default_domain = f"{game_id}-{'android' if disk == 'android' else 'pc'}"
    if domain_id is not None and domain_id != default_domain:
        domain_id = require_safe_component(domain_id, "domain_id")
        if disk != "pc" or not (
            is_nondefault_pc_domain(vendor, game_id, domain_id)
            or is_configured_nondefault_pc_domain(root, vendor, game_id, domain_id)
        ):
            raise ValueError("domain_id must be a registered non-default PC domain")
    return domain_directory(root, vendor, game_id, platform, domain_id, allow_pc=True) / "index.json"


def version_key(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value))
    return numbers or (0,)


_version_key = version_key


def _availability(artifact: Mapping[str, Any]) -> bool | None:
    urls = artifact.get("urls")
    if not isinstance(urls, list) or not urls or not isinstance(urls[0], Mapping):
        return None
    current = urls[0].get("current")
    if not isinstance(current, Mapping):
        return None
    if current.get("http_code") == 403:
        return False
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


KURO_PACK_MANIFEST = re.compile(r"/packs/([a-z0-9]+)/full\.json")


def _kuro_common_pack(record: Mapping[str, Any], artifacts: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if record.get("vendor") != "kuro":
        return None
    for artifact in artifacts:
        if artifact.get("component") != "game":
            continue
        manifest = artifact.get("manifest")
        path = manifest.get("path") if isinstance(manifest, Mapping) else None
        match = KURO_PACK_MANIFEST.search(path) if isinstance(path, str) else None
        if match and match.group(1) == "common":
            return artifact
    return None


def index_entry(record: Mapping[str, Any], platform: str) -> dict[str, Any] | None:
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
        common_pack = _kuro_common_pack(record, game)
        if common_pack is not None:
            chosen = [common_pack]
        else:
            full = [a for a in game if a.get("package_type") == "full"]
            chosen = full or [a for a in game if a.get("package_type") == "segment"]
        if not chosen:
            chosen = [a for a in artifacts if isinstance(a, Mapping) and a.get("kind") == "resource"]
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


_entry = index_entry


def _scan(directory: Path, vendor: str, game_id: str, platform: str) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    records: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for path in directory.glob("*.json"):
        if path.name == "index.json" or not is_ordinary(path):
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
        item = index_entry(value, platform)
        if item is not None:
            records.append((value, item))
    records.sort(key=lambda pair: version_key(pair[0]["version"]), reverse=True)
    return records


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, raw)


def _rebuild_locked(root: Path, vendor: str, game_id: str, platform: str, domain_id: str | None = None) -> Path:
    path = index_path(root, vendor, game_id, platform, domain_id)
    directory = path.parent
    scanned = _scan(directory, vendor, game_id, platform)
    if domain_id is not None:
        scanned = [pair for pair in scanned if pair[0].get("domain_id") == domain_id]
    versions = [item for _, item in scanned]
    if not versions:
        if path.exists() or path.is_symlink():
            if not is_ordinary(path):
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


def rebuild_index(root: Path, vendor: str, game_id: str, platform: str, domain_id: str | None = None) -> Path:
    vendor = require_safe_component(vendor, "vendor")
    game_id = require_safe_component(game_id, "game_id")
    canonical = "windows" if platform in {"pc", "windows"} else platform
    disk_platform(canonical)
    root = Path(root)
    if not is_ordinary(root, directory=True):
        root.mkdir(exist_ok=True)
    if not is_ordinary(root, directory=True):
        raise OSError(f"unsafe data root: {root}")
    path = index_path(root, vendor, game_id, platform, domain_id)
    with DATA_LOCK:
        with data_file_lock(root):
            current = root
            for part in path.parent.relative_to(root).parts:
                current = current / part
                if not is_ordinary(current, directory=True):
                    current.mkdir()
                if not is_ordinary(current, directory=True):
                    raise OSError(f"unsafe index directory: {current}")
            return _rebuild_locked(root, vendor, game_id, canonical, domain_id)


def rebuild_indexes(root: Path) -> list[Path]:
    root = Path(root)
    result: list[Path] = []
    if not is_ordinary(root, directory=True):
        return result
    with DATA_LOCK:
        with data_file_lock(root):
            for vendor_dir in root.iterdir():
                if not is_ordinary(vendor_dir, directory=True):
                    continue
                for game_dir in vendor_dir.iterdir():
                    if not is_ordinary(game_dir, directory=True):
                        continue
                    for disk, platform in (("android", "android"), ("pc", "windows")):
                        directory = game_dir / disk
                        if is_ordinary(directory, directory=True):
                            result.append(_rebuild_locked(root, vendor_dir.name, game_dir.name, platform))
                            if platform == "windows":
                                domains_dir = directory / "domains"
                                if is_ordinary(domains_dir, directory=True):
                                    for domain_id in (
                                        *nondefault_pc_domains(vendor_dir.name, game_dir.name),
                                        *configured_nondefault_pc_domains(root, vendor_dir.name, game_dir.name),
                                    ):
                                        domain_dir = domains_dir / domain_id
                                        if is_ordinary(domain_dir, directory=True):
                                            result.append(_rebuild_locked(root, vendor_dir.name, game_dir.name, platform, domain_id))
    return result


def read_index(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise IndexReadError(f"invalid index: {path}") from error
    if not stat_is_ordinary(info):
        raise IndexReadError(f"invalid index: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IndexReadError(f"invalid index: {path}") from error
    if not isinstance(value, Mapping) or not isinstance(value.get("versions"), list):
        raise IndexReadError(f"invalid index: {path}")
    return dict(value)


__all__ = [
    "IndexReadError",
    "index_entry",
    "index_path",
    "read_index",
    "rebuild_index",
    "rebuild_indexes",
    "version_key",
]
