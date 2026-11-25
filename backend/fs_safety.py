"""Shared filesystem safety, atomic persistence, and canonical domain paths."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any


FILE_ATTRIBUTE_REPARSE_POINT = 0x400
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class UnsafePathError(OSError):
    """A filesystem target or ancestor is a symlink, reparse point, or wrong file type."""


def stat_is_ordinary(info: os.stat_result, *, directory: bool = False) -> bool:
    """Validate an ``os.lstat`` result without performing a second syscall."""
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    return (
        expected
        and not stat.S_ISLNK(info.st_mode)
        and not bool(getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    )


def is_ordinary(path: Path, *, directory: bool = False) -> bool:
    """Return whether ``path`` is an ordinary file/directory, never a link or reparse point."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat_is_ordinary(info, directory=directory)


def ensure_directory(path: Path) -> Path:
    """Create ``path`` if needed while verifying every ancestor is an ordinary directory."""
    resolved = Path(path).absolute()
    current = Path(resolved.anchor)
    parts = resolved.parts[1:] if resolved.anchor else resolved.parts
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            current.mkdir()
            info = os.lstat(current)
        if not stat_is_ordinary(info, directory=True):
            raise UnsafePathError(f"unsafe directory path: {current}")
    return resolved


def atomic_write_bytes(target: Path, payload: bytes) -> None:
    """Atomically write ``payload`` to ``target`` via a synced sibling temp file."""
    target = Path(target)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    closed = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            closed = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if not closed:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def atomic_write_text(target: Path, text: str) -> None:
    """Atomically write UTF-8 ``text`` to ``target`` preserving ``\\n`` newlines."""
    atomic_write_bytes(target, text.encode("utf-8"))


def is_safe_component(value: Any) -> bool:
    """Return whether ``value`` is a safe canonical path/API identifier component."""
    return isinstance(value, str) and SAFE_COMPONENT.fullmatch(value) is not None


def require_safe_component(
    value: Any,
    field: str,
    error_cls: type[Exception] = ValueError,
) -> str:
    """Validate and return ``value`` as a safe path component or raise ``error_cls``."""
    if not is_safe_component(value):
        raise error_cls(f"{field} 必须是安全的非空路径组件")
    return value


def disk_platform(platform: Any, *, allow_pc: bool = False) -> str:
    """Map canonical platform names (``android`` / ``windows``) to on-disk directory names."""
    if platform == "android":
        return "android"
    if platform == "windows" or (allow_pc and platform == "pc"):
        return "pc"
    if allow_pc:
        raise ValueError("platform must be android, pc, or windows")
    raise ValueError("platform must be android or windows")


def domain_directory(
    root: Path,
    vendor: str,
    game_id: str,
    platform: str,
    domain_id: str | None = None,
    *,
    allow_pc: bool = False,
) -> Path:
    """Return the canonical directory for a default or secondary PC domain."""
    disk = disk_platform(platform, allow_pc=allow_pc)
    vendor = require_safe_component(vendor, "vendor")
    game_id = require_safe_component(game_id, "game_id")
    base = Path(root) / vendor / game_id / disk
    default_domain = f"{game_id}-{'android' if disk == 'android' else 'pc'}"
    if domain_id is None or domain_id == default_domain:
        return base
    domain_id = require_safe_component(domain_id, "domain_id")
    if disk != "pc":
        raise ValueError("Android domain must use default domain_id")
    return base / "domains" / domain_id


__all__ = [
    "FILE_ATTRIBUTE_REPARSE_POINT",
    "SAFE_COMPONENT",
    "UnsafePathError",
    "atomic_write_bytes",
    "atomic_write_text",
    "disk_platform",
    "domain_directory",
    "ensure_directory",
    "is_ordinary",
    "is_safe_component",
    "require_safe_component",
    "stat_is_ordinary",
]
