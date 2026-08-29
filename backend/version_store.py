"""Safe persistence for canonical schema v2 version records.

This writer intentionally does not rebuild the legacy index.json.  Existing
readers still consume that index and the v2 trial must remain isolated.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.schema_v2 import RECORD_IDENTITY_FIELDS, record_identity, validate_v2_record
from backend.domain_registry import is_nondefault_pc_domain
from backend.storage_locks import DATA_LOCK, data_file_lock


class VersionStoreError(ValueError):
    """Raised when a v2 record cannot be safely written."""


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VersionStoreError(f"{field} 必须是非空路径组件")
    forbidden = set('<>:"/\\|?*')
    if value in {".", ".."} or any(char in value for char in forbidden) or any(ord(char) < 32 for char in value):
        raise VersionStoreError(f"{field} 不是安全的路径组件")
    return value


def _is_reparse_or_link(path: Path, mode: int) -> bool:
    return stat.S_ISLNK(mode) or bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)


def _directory(parent: Path, name: str) -> Path:
    path = parent / name
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        path.mkdir()
        info = os.lstat(path)
    except OSError as error:
        raise VersionStoreError(f"无法检查输出目录：{path}") from error
    if _is_reparse_or_link(path, info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise VersionStoreError(f"输出目录不安全：{path}")
    return path


def v2_record_path(record: Mapping[str, Any], root: Path) -> Path:
    """Return the canonical on-disk path for one schema v2 record."""
    vendor = _safe_component(record.get("vendor"), "vendor")
    game_id = _safe_component(record.get("game_id"), "game_id")
    version = _safe_component(record.get("version"), "version")
    disk_platform = {"android": "android", "windows": "pc"}.get(record.get("platform"))
    if disk_platform is None:
        raise VersionStoreError("platform 不是支持的 v2 平台")
    domain_id = _safe_component(record.get("domain_id"), "domain_id")
    default_domain = f"{game_id}-{'android' if disk_platform == 'android' else 'pc'}"
    base = Path(root) / vendor / game_id / disk_platform
    if domain_id == default_domain:
        return base / f"{version}.json"
    if disk_platform == "pc" and is_nondefault_pc_domain(vendor, game_id, domain_id):
        return base / "domains" / domain_id / f"{version}.json"
    # Preserve the legacy/default location for every other identity.  Only an
    # explicitly registered secondary domain changes the on-disk layout.
    return base / f"{version}.json"


_LEGACY_IDENTITY_FIELDS = ("vendor", "game_id", "platform", "version")


def legacy_identity_matches(existing: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    """Return whether two records share the minimum generic legacy identity."""
    return all(
        field in existing and field in expected and existing[field] == expected[field]
        for field in _LEGACY_IDENTITY_FIELDS
    )


def _identity_conflict_field(existing: Mapping[str, Any], expected: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        if field not in existing:
            return f"{field} 缺失"
        if existing.get(field) != expected.get(field):
            return f"{field}={existing.get(field)!r}，期望 {expected.get(field)!r}"
    return "未知字段"


def _read_existing_record(path: Path) -> dict[str, Any]:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise VersionStoreError(f"无法检查 v2 目标路径：{path}") from error
    if _is_reparse_or_link(path, info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise VersionStoreError(f"v2 目标路径不是普通文件：{path}")
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise VersionStoreError(f"已有 v2 记录无法读取或 JSON 损坏：{path}") from error
    if not isinstance(existing, dict):
        raise VersionStoreError(f"已有 v2 记录必须是 JSON 对象：{path}")
    return existing


def _prepare_output_root(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        root_info = os.lstat(root)
    except OSError as error:
        raise VersionStoreError(f"无法准备 v2 输出根目录：{root}") from error
    if _is_reparse_or_link(root, root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise VersionStoreError(f"v2 输出根目录不安全：{root}")
    try:
        (root / ".cache").mkdir(exist_ok=True)
    except OSError as error:
        raise VersionStoreError(f"无法准备 v2 文件锁目录：{root / '.cache'}") from error


def _write_v2_record_locked(
    record: Mapping[str, Any], root: Path, target: Path, *, overwrite: bool,
) -> Path:
    """Write one record while the caller holds both storage locks."""
    platform_dir = _prepare_v2_target_directory_locked(root, target)
    path = target
    if path.exists() or path.is_symlink():
        if not overwrite:
            raise FileExistsError(f"v2 记录已存在（默认不覆盖）：{path}")
        try:
            target_info = os.lstat(path)
        except OSError as error:
            raise VersionStoreError(f"无法检查目标文件：{path}") from error
        if _is_reparse_or_link(path, target_info.st_mode) or not stat.S_ISREG(target_info.st_mode):
            raise VersionStoreError(f"目标文件不安全：{path}")

    raw = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=platform_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def _prepare_v2_target_directory_locked(root: Path, target: Path) -> Path:
    """Check the canonical directory chain while the caller holds the locks."""
    root_info = os.lstat(root)
    if _is_reparse_or_link(root, root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise VersionStoreError(f"v2 输出根目录不安全：{root}")
    relative_parts = target.relative_to(root).parts
    current = root
    for part in relative_parts[:-1]:
        current = _directory(current, part)
    return current


def _persist_v2_record_locked(
    record: Mapping[str, Any], root: Path, target: Path, *,
    preserve_artifacts: bool = False,
    preserve_references: bool = False,
    preserve_provenance: bool = False,
) -> Path:
    """Persist one record while preserving selected fields from an existing v2 record."""
    _prepare_v2_target_directory_locked(root, target)
    try:
        existing = _read_existing_record(target)
    except FileNotFoundError:
        return _write_v2_record_locked(record, root, target, overwrite=False)

    if "schema_version" not in existing:
        if not legacy_identity_matches(existing, record):
            detail = _identity_conflict_field(existing, record, _LEGACY_IDENTITY_FIELDS)
            raise VersionStoreError(f"legacy 记录 identity 冲突：{detail}")
        return target

    if existing.get("schema_version") != 2:
        raise VersionStoreError(
            f"已有 v2 记录使用不支持的 schema_version：{existing.get('schema_version')!r}"
        )
    try:
        validate_v2_record(existing)
    except ValueError as error:
        raise VersionStoreError(f"已有 schema v2 记录无效：{error}") from error

    if record_identity(existing) != record_identity(record):
        detail = _identity_conflict_field(existing, record, RECORD_IDENTITY_FIELDS)
        raise VersionStoreError(f"schema v2 记录 identity 冲突：{detail}")

    updated = dict(record)
    if preserve_artifacts:
        updated["artifacts"] = existing["artifacts"]
    if preserve_references:
        updated["references"] = existing["references"]
    if preserve_provenance and "provenance" in existing:
        updated["provenance"] = existing["provenance"]
    if "is_visible" in existing:
        updated["is_visible"] = existing["is_visible"]
    try:
        validate_v2_record(updated)
    except ValueError as error:
        raise VersionStoreError(f"合并后的 schema v2 记录无效：{error}") from error
    return _write_v2_record_locked(updated, root, target, overwrite=True)


def persist_v2_record(
    record: Mapping[str, Any], output_root: Path, *,
    preserve_artifacts: bool = False,
    preserve_references: bool = False,
    preserve_provenance: bool = False,
) -> Path:
    """Persist a record, optionally retaining selected existing v2 fields.

    Preservation happens inside both storage locks and is deliberately limited
    to fields whose producers can run independently.  This is not a generic
    merge framework.
    """
    validate_v2_record(record)
    for name, value in (
        ("preserve_artifacts", preserve_artifacts),
        ("preserve_references", preserve_references),
        ("preserve_provenance", preserve_provenance),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name} 必须显式使用 bool")
    root = Path(output_root)
    target = v2_record_path(record, root)
    with DATA_LOCK:
        _prepare_output_root(root)
        with data_file_lock(root):
            return _persist_v2_record_locked(
                record,
                root,
                target,
                preserve_artifacts=preserve_artifacts,
                preserve_references=preserve_references,
                preserve_provenance=preserve_provenance,
            )


def write_v2_record(
    record: Mapping[str, Any], root: Path, *, overwrite: bool = False,
) -> Path:
    """Validate and atomically write one v2 record below ``root``.

    Android uses ``android`` on disk; a future Windows record uses ``pc``
    while retaining ``platform=windows`` in its JSON.  No index is rebuilt.
    """
    validate_v2_record(record)
    if not isinstance(overwrite, bool):
        raise TypeError("overwrite 必须显式使用 bool")
    root = Path(root)
    target = v2_record_path(record, root)
    with DATA_LOCK:
        _prepare_output_root(root)
        with data_file_lock(root):
            return _write_v2_record_locked(record, root, target, overwrite=overwrite)


__all__ = [
    "VersionStoreError",
    "legacy_identity_matches",
    "persist_v2_record",
    "v2_record_path",
    "write_v2_record",
]
