"""Canonical on-disk domain, record, and index loader with stat-snapshot fingerprinting."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from backend import catalog_admin
from backend.catalog_admin import CatalogConfigError
from backend.catalog_registry import GAME_CATALOG, PLATFORMS, VENDORS
from backend.domain_registry import nondefault_pc_domains
from backend.fs_safety import is_ordinary, stat_is_ordinary
from backend.indexes import IndexReadError, index_entry, read_index, version_key
from backend.manifest_readers import ManifestBadRequest, strict_relative_posix
from backend.schema_v2 import SchemaValidationError, validate_v2_record


MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
InventorySnapshot = tuple[tuple[str, tuple[int, ...] | None], ...]


class ApiFault(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def fail(status: int, code: str, message: str, details: Any = None) -> NoReturn:
    raise ApiFault(status, code, message, details)


@dataclass(frozen=True)
class DomainData:
    vendor: str
    game_id: str
    disk_platform: str
    platform: str
    domain_id: str
    root: Path
    records: tuple[dict[str, Any], ...]


def path_present(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ApiFault(500, "unsafe_data_path", "数据路径无法检查") from error


def read_json_object(path: Path, limit: int, code: str) -> dict[str, Any]:
    if not is_ordinary(path, directory=False):
        fail(500, code, "归档数据损坏")
    try:
        if path.stat().st_size > limit:
            fail(500, code, "归档数据超过大小限制")
        value = json.loads(path.read_text(encoding="utf-8"))
    except ApiFault:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ApiFault(500, code, "归档数据损坏") from error
    if not isinstance(value, dict):
        fail(500, code, "归档数据损坏")
    return value


def safe_manifest_target(base: Path, relative: str) -> Path:
    try:
        relative = strict_relative_posix(relative)
    except ManifestBadRequest as error:
        raise ApiFault(500, "corrupt_manifest", "Manifest 路径无效") from error
    current = base
    if not is_ordinary(current, directory=True):
        fail(500, "corrupt_manifest", "Manifest 路径不安全")
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = current / part
        if not is_ordinary(current, directory=index < len(parts) - 1):
            fail(500, "corrupt_manifest", "Manifest 路径不安全")
    try:
        if base.resolve() not in current.resolve().parents:
            fail(500, "corrupt_manifest", "Manifest 路径越界")
    except OSError as error:
        raise ApiFault(500, "corrupt_manifest", "Manifest 路径损坏") from error
    return current


def load_manifest_document(
    domain: DomainData,
    record: dict[str, Any],
    relative: str,
    *,
    max_bytes: int,
    read_json: Callable[[Path, int, str], dict[str, Any]] = read_json_object,
) -> dict[str, Any]:
    path = safe_manifest_target(domain.root, relative)
    document = read_json(path, max_bytes, "corrupt_manifest")
    expected = {key: record[key] for key in ("vendor", "game_id", "platform", "version")}
    if document.get("schema_version") != 1 or any(document.get(key) != value for key, value in expected.items()):
        fail(500, "manifest_identity_mismatch", "Manifest 身份不匹配")
    if "domain_id" in document and document["domain_id"] != record["domain_id"]:
        fail(500, "manifest_identity_mismatch", "Manifest 身份不匹配")
    return document


def index_entry_matches(item: dict[str, Any], record: dict[str, Any] | None, platform: str) -> bool:
    expected = index_entry(record, platform) if record is not None else None
    if expected is None or set(item) != set(expected):
        return False
    if item == expected:
        return True
    if any(item[key] != value for key, value in expected.items() if key != "available"):
        return False
    # Accept only the exact pre-403-policy summary of this canonical record.
    # This keeps historical indexes readable without rewriting server data.
    legacy_record = deepcopy(record)
    for artifact in legacy_record.get("artifacts", []):
        for candidate in artifact.get("urls", []):
            current = candidate.get("current")
            if isinstance(current, dict) and current.get("http_code") == 403:
                del current["http_code"]
    legacy = index_entry(legacy_record, platform)
    return legacy != expected and item == legacy


_index_entry_matches = index_entry_matches


def load_catalog_config(data_root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        return catalog_admin.load_config(data_root)
    except CatalogConfigError as error:
        raise ApiFault(500, "corrupt_catalog_config", "目录配置损坏") from error


def load_domain_records(
    vendor: str,
    game_id: str,
    disk_platform: str,
    platform: str,
    domain_id: str,
    directory: Path,
    *,
    allow_subdirectories: bool = True,
    read_json: Callable[[Path, int, str], dict[str, Any]] = read_json_object,
) -> DomainData | None:
    """Validate and load visible canonical records and index for one domain directory."""
    if not path_present(directory):
        return None
    if not is_ordinary(directory, directory=True):
        fail(500, "unsafe_data_path", "数据目录不安全")
    expected_identity = {
        "vendor": vendor,
        "game_id": game_id,
        "platform": platform,
        "domain_id": domain_id,
    }
    index_path = directory / "index.json"
    if not is_ordinary(index_path, directory=False):
        if path_present(index_path):
            fail(500, "corrupt_index", "版本索引损坏")
        index = None
    else:
        try:
            if index_path.stat().st_size > MAX_INDEX_BYTES:
                fail(500, "corrupt_index", "版本索引超过大小限制")
            index = read_index(index_path)
        except ApiFault:
            raise
        except IndexReadError as error:
            raise ApiFault(500, "corrupt_index", "版本索引损坏") from error
        if index is None:
            fail(500, "missing_index", "版本索引缺失")
        if set(index) != {*expected_identity, "versions"}:
            fail(500, "corrupt_index", "版本索引字段不符合契约")
        if any(index.get(key) != expected for key, expected in expected_identity.items()):
            fail(500, "index_mismatch", "版本索引身份不匹配")

    try:
        children = list(directory.iterdir())
    except OSError as error:
        raise ApiFault(500, "corrupt_data", "归档目录无法读取") from error

    records: list[dict[str, Any]] = []
    for path in children:
        if path.name == "index.json":
            continue
        if allow_subdirectories and is_ordinary(path, directory=True):
            continue
        if path.suffix != ".json" or not is_ordinary(path, directory=False):
            fail(500, "unsafe_data_path", "归档文件不安全")
        record = read_json(path, MAX_RECORD_BYTES, "corrupt_record")
        try:
            validate_v2_record(record)
        except SchemaValidationError as error:
            raise ApiFault(500, "corrupt_record", "版本记录校验失败") from error
        expected_record = {**expected_identity, "version": path.stem}
        if any(record.get(key) != expected for key, expected in expected_record.items()):
            fail(500, "record_identity_mismatch", "版本记录身份不匹配")
        if record.get("is_visible") is not False:
            records.append(record)

    if index is None:
        # Core intentionally removes an index when every canonical record is
        # hidden. Omit the domain only after verifying no visible record exists.
        if records:
            fail(500, "missing_index", "版本索引缺失")
        return None

    entries = index.get("versions")
    if not isinstance(entries, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("version"), str) for item in entries
    ):
        fail(500, "corrupt_index", "版本索引损坏")
    indexed_versions = [item["version"] for item in entries]
    eligible_versions = [record["version"] for record in records if index_entry(record, platform) is not None]
    if len(set(indexed_versions)) != len(indexed_versions) or sorted(indexed_versions) != sorted(eligible_versions):
        fail(500, "index_mismatch", "版本索引与记录不一致")
    by_version = {record["version"]: record for record in records}
    for item in entries:
        if item["version"] not in by_version:
            fail(500, "index_mismatch", "版本索引指向缺失记录")
        if not index_entry_matches(item, by_version[item["version"]], platform):
            fail(500, "index_mismatch", "版本索引摘要不匹配")
    ordered = sorted(records, key=lambda item: version_key(item["version"]), reverse=True)
    if not ordered:
        return None
    return DomainData(vendor, game_id, disk_platform, platform, domain_id, directory, tuple(ordered))


def load_inventory(
    data_root: Path,
    *,
    requested_domain: str | None = None,
    read_json: Callable[[Path, int, str], dict[str, Any]] = read_json_object,
) -> dict[str, DomainData]:
    """Load and validate all enabled public domains (or one requested domain)."""
    root = Path(data_root)
    if not is_ordinary(root, directory=True):
        fail(500, "data_root_invalid", "数据目录不可用")
    config = load_catalog_config(root)
    all_game_ids = catalog_admin.game_ids(root, GAME_CATALOG, config=config)
    configured_domains = config["domains"]

    result: dict[str, DomainData] = {}
    for vendor in VENDORS:
        vendor_root = root / vendor
        if not path_present(vendor_root):
            continue
        if not is_ordinary(vendor_root, directory=True):
            fail(500, "unsafe_data_path", "数据目录不安全")
        for game_id in all_game_ids:
            game_root = vendor_root / game_id
            if not path_present(game_root):
                continue
            if not is_ordinary(game_root, directory=True):
                fail(500, "unsafe_data_path", "数据目录不安全")
            for disk_platform, platform in PLATFORMS:
                domain_id = f"{game_id}-{'android' if platform == 'android' else 'pc'}"
                if requested_domain is not None and domain_id != requested_domain:
                    continue
                directory = game_root / disk_platform
                if not path_present(directory):
                    continue
                if not is_ordinary(directory, directory=True):
                    fail(500, "unsafe_data_path", "数据目录不安全")
                if domain_id in result:
                    fail(500, "duplicate_domain", "归档域归属冲突")
                domain = load_domain_records(
                    vendor,
                    game_id,
                    disk_platform,
                    platform,
                    domain_id,
                    directory,
                    allow_subdirectories=True,
                    read_json=read_json,
                )
                domain_config = configured_domains.get(domain_id)
                if domain_config is not None and domain_config.get("is_enabled") is False:
                    continue
                if domain is not None:
                    result[domain_id] = domain

    for vendor in VENDORS:
        for game_id in all_game_ids:
            domains_root = root / vendor / game_id / "pc" / "domains"
            if not path_present(domains_root):
                continue
            if not is_ordinary(domains_root, directory=True):
                fail(500, "unsafe_data_path", "数据目录不安全")
            candidate_domains = dict.fromkeys(
                (
                    *nondefault_pc_domains(vendor, game_id),
                    *catalog_admin.configured_nondefault_pc_domains(
                        root, vendor, game_id, config=config,
                    ),
                )
            )
            for domain_id in candidate_domains:
                if requested_domain is not None and domain_id != requested_domain:
                    continue
                domain_config = configured_domains.get(domain_id)
                if domain_config is not None and domain_config.get("is_enabled") is False:
                    continue
                domain = load_domain_records(
                    vendor,
                    game_id,
                    "pc",
                    "windows",
                    domain_id,
                    domains_root / domain_id,
                    allow_subdirectories=False,
                    read_json=read_json,
                )
                if domain is not None:
                    if domain_id in result:
                        fail(500, "duplicate_domain", "归档域归属冲突")
                    result[domain_id] = domain
    return result


def _snapshot_domain_dir(
    directory: Path,
    rel_prefix: str,
    entries: list[tuple[str, tuple[int, ...] | None]],
    *,
    allow_subdirectories: bool,
) -> bool:
    try:
        dir_info = os.lstat(directory)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat_is_ordinary(dir_info, directory=True):
        return False
    entries.append((rel_prefix, (dir_info.st_mode, dir_info.st_mtime_ns, dir_info.st_size)))
    try:
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: item.name)
    except OSError:
        return False
    for child in children:
        rel_path = f"{rel_prefix}/{child.name}"
        try:
            info = os.lstat(child.path) if child.name == "index.json" else child.stat(follow_symlinks=False)
        except OSError:
            return False
        if child.name == "index.json":
            if not stat_is_ordinary(info, directory=False):
                return False
            entries.append(
                (rel_path, (info.st_mode, info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino))
            )
            continue
        if allow_subdirectories and stat_is_ordinary(info, directory=True):
            continue
        if not child.name.endswith(".json") or not stat_is_ordinary(info, directory=False):
            return False
        entries.append((rel_path, (info.st_mode, info.st_mtime_ns, info.st_ctime_ns, info.st_size)))
    return True


def snapshot_data_root(data_root: Path) -> InventorySnapshot | None:
    """Compute a stat-only fingerprint of canonical records, indexes, and catalog config.

    Returns ``None`` whenever any inspected path is missing ``data_root`` or fails
    ordinary-file/directory checks so the caller falls through to authoritative
    validation and raises the exact ``ApiFault``.
    """
    root = Path(data_root)
    try:
        root_info = os.lstat(root)
    except OSError:
        return None
    if not stat_is_ordinary(root_info, directory=True):
        return None

    entries: list[tuple[str, tuple[int, ...] | None]] = [
        (".", (root_info.st_mode, root_info.st_mtime_ns, root_info.st_size))
    ]
    catalog_path = root / catalog_admin.CATALOG_CONFIG_NAME
    try:
        cfg_info = os.lstat(catalog_path)
    except FileNotFoundError:
        entries.append((catalog_admin.CATALOG_CONFIG_NAME, None))
    except OSError:
        return None
    else:
        if not stat_is_ordinary(cfg_info, directory=False):
            return None
        entries.append(
            (
                catalog_admin.CATALOG_CONFIG_NAME,
                (cfg_info.st_mode, cfg_info.st_mtime_ns, cfg_info.st_ctime_ns, cfg_info.st_size, cfg_info.st_ino),
            )
        )

    for vendor in VENDORS:
        vendor_root = root / vendor
        try:
            vendor_info = os.lstat(vendor_root)
        except FileNotFoundError:
            continue
        except OSError:
            return None
        if not stat_is_ordinary(vendor_info, directory=True):
            return None
        entries.append((vendor, (vendor_info.st_mode, vendor_info.st_mtime_ns, vendor_info.st_size)))
        try:
            with os.scandir(vendor_root) as iterator:
                game_entries = sorted(iterator, key=lambda item: item.name)
        except OSError:
            return None
        for game_entry in game_entries:
            try:
                game_info = game_entry.stat(follow_symlinks=False)
            except OSError:
                return None
            if not stat_is_ordinary(game_info, directory=True):
                return None
            game_id = game_entry.name
            game_path = Path(game_entry.path)
            entries.append((f"{vendor}/{game_id}", (game_info.st_mode, game_info.st_mtime_ns, game_info.st_size)))
            for disk_platform, _platform in PLATFORMS:
                if not _snapshot_domain_dir(
                    game_path / disk_platform,
                    f"{vendor}/{game_id}/{disk_platform}",
                    entries,
                    allow_subdirectories=True,
                ):
                    return None
            domains_root = game_path / "pc" / "domains"
            try:
                domains_info = os.lstat(domains_root)
            except FileNotFoundError:
                continue
            except OSError:
                return None
            if not stat_is_ordinary(domains_info, directory=True):
                return None
            entries.append(
                (f"{vendor}/{game_id}/pc/domains", (domains_info.st_mode, domains_info.st_mtime_ns, domains_info.st_size))
            )
            try:
                with os.scandir(domains_root) as iterator:
                    domain_entries = sorted(iterator, key=lambda item: item.name)
            except OSError:
                return None
            for sub in domain_entries:
                if not _snapshot_domain_dir(
                    Path(sub.path),
                    f"{vendor}/{game_id}/pc/domains/{sub.name}",
                    entries,
                    allow_subdirectories=False,
                ):
                    return None
    return tuple(entries)


__all__ = [
    "ApiFault", "DomainData", "InventorySnapshot", "MAX_INDEX_BYTES", "MAX_RECORD_BYTES",
    "fail", "index_entry_matches", "load_catalog_config", "load_domain_records",
    "load_inventory", "load_manifest_document", "path_present", "read_json_object",
    "safe_manifest_target", "snapshot_data_root",
]
