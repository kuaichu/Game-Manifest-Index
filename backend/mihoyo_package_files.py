"""Bounded, read-only file listing for official HoYo PC packages.

HoYo's PC packages contain a small ``pkg_version`` NDJSON member.  The
member is fetched from the game's official scattered-file directory when it
is available, and otherwise extracted from an archive with bounded HTTP
Range requests.  This module consumes canonical schema-v2 records only.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import stat
import struct
import tempfile
import threading
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from backend.manifest_readers import (
    ManifestBadRequest,
    ManifestError,
    ManifestNotFound,
    ManifestTimeout,
    ManifestUpstream,
    strict_relative_posix,
)
from backend.storage_locks import CACHE_LOCK


MAX_CENTRAL_BYTES = 16 * 1024 * 1024
MAX_MEMBER_COMPRESSED_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_DIRECT_BYTES = 32 * 1024 * 1024
MAX_RANGE_BYTES = MAX_CENTRAL_BYTES
MAX_TOTAL_RANGE_BYTES = 64 * 1024 * 1024
MAX_FILES = 200_000
TAIL_BYTES = 128 * 1024
CACHE_SCHEMA_VERSION = 1

SCATTERED_ROOTS = {
    "hk4e": "ScatteredFiles",
    "hkrpg": "PC/unzip",
    "nap": "SplitAudioZip",
    "bh3": "PC/extract",
}
PACKAGE_DIRS = {"hkrpg": "/PC/download", "nap": "/VolumeZip", "bh3": "/PC"}
OFFICIAL_PACKAGE_HOSTS = frozenset(
    {
        "autopatchcn.yuanshen.com",
        "autopatchcn.bhsr.com",
        "autopatchcn.juequling.com",
        "autopatchcn.bh3.com",
        "bundle.bh3.com",
    }
)
PACKAGE_HOSTS_BY_GAME = {
    "hk4e": frozenset({"autopatchcn.yuanshen.com"}),
    "hkrpg": frozenset({"autopatchcn.bhsr.com"}),
    "nap": frozenset({"autopatchcn.juequling.com"}),
    "bh3": frozenset({"autopatchcn.bh3.com", "bundle.bh3.com"}),
}


class PackageFilesError(ManifestError):
    """Base class for errors safe to expose through the API envelope."""


class PackageFilesNotFound(PackageFilesError):
    pass


class PackageFilesBadRequest(PackageFilesError):
    pass


class PackageFilesTimeout(PackageFilesError):
    pass


class PackageFilesUpstream(PackageFilesError):
    pass


class PackageFilesUnsupported(PackageFilesError):
    pass


class PackageFilesCacheError(PackageFilesError):
    pass


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def _official_url(value: Any, game_id: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in OFFICIAL_PACKAGE_HOSTS
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        return None
    return value if parsed.hostname in PACKAGE_HOSTS_BY_GAME.get(game_id, frozenset()) else None


def _record_identity(record: Mapping[str, Any], game_id: str, version: str) -> None:
    if (
        record.get("vendor") != "mihoyo"
        or record.get("game_id") != game_id
        or record.get("platform") != "windows"
        or record.get("domain_id") != f"{game_id}-pc"
        or record.get("version") != version
    ):
        raise PackageFilesNotFound("官方 package 身份不存在")
    if game_id not in SCATTERED_ROOTS:
        raise PackageFilesNotFound("官方 package 游戏不支持")
    try:
        strict_relative_posix(version)
    except ManifestBadRequest as error:
        raise PackageFilesNotFound("官方 package 版本不存在") from error


def _candidate_groups(record: Mapping[str, Any], game_id: str, version: str, identity: str) -> list[list[dict[str, Any]]]:
    _record_identity(record, game_id, version)
    if identity != "game":
        raise PackageFilesBadRequest("identity 无效")
    raw_artifacts = record.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise PackageFilesUpstream("版本记录资源损坏")
    artifacts = [
        item for item in raw_artifacts
        if isinstance(item, Mapping)
        and item.get("kind") == "package"
        and item.get("component") == "game"
        and item.get("delivery_mode") == "archive"
        and item.get("package_type") in {"full", "segment"}
    ]
    full = [item for item in artifacts if item.get("package_type") == "full"]
    selected = full or [item for item in artifacts if item.get("package_type") == "segment"]
    if not selected:
        raise PackageFilesNotFound("官方 archive package 不存在")
    if full and len(full) != 1:
        raise PackageFilesUpstream("官方 full package 数量不明确")
    if not full:
        parts = [item.get("part") for item in selected]
        if any(isinstance(part, bool) or not isinstance(part, int) or part < 1 for part in parts):
            raise PackageFilesUpstream("官方 package 分卷编号无效")
        if len(set(parts)) != len(parts) or sorted(parts) != list(range(1, len(parts) + 1)):
            raise PackageFilesUpstream("官方 package 分卷不连续")
        selected.sort(key=lambda item: item["part"])

    groups: list[list[dict[str, Any]]] = []
    for artifact in selected:
        size = artifact.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise PackageFilesUpstream("官方 package 大小无效")
        checksum = artifact.get("checksum")
        md5 = checksum.get("md5") if isinstance(checksum, Mapping) else None
        if md5 is not None and (not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5)):
            raise PackageFilesUpstream("官方 package checksum 无效")
        urls = artifact.get("urls")
        if not isinstance(urls, list):
            raise PackageFilesNotFound("官方 package URL 不存在")
        choices: list[tuple[int, int, str, dict[str, Any]]] = []
        for index, candidate in enumerate(urls):
            if not isinstance(candidate, Mapping):
                continue
            if candidate.get("provider") != "mihoyo" or candidate.get("source_kind") != "official":
                continue
            url = _official_url(candidate.get("url"), game_id)
            if url is None:
                continue
            priority = candidate.get("priority")
            if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
                continue
            current = candidate.get("current")
            available = isinstance(current, Mapping) and current.get("state") == "available"
            choices.append((0 if available else 1, priority, index, {"url": url, "size": size, "md5": md5}))
        choices.sort(key=lambda item: item[:3])
        if not choices:
            raise PackageFilesNotFound("官方 package URL 不存在")
        groups.append([item[3] for item in choices])
    return groups


def _download_base(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rsplit("/", 1)[0] or "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _scattered_root(game_id: str, artifact_url: str) -> str:
    base = _download_base(artifact_url)
    suffix = "/" + SCATTERED_ROOTS[game_id].strip("/")
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    if path.casefold().endswith(suffix.casefold()):
        return base
    package_dir = PACKAGE_DIRS.get(game_id)
    if package_dir and path.casefold().endswith(package_dir.casefold()):
        path = path[: -len(package_dir)] + suffix
    else:
        path += suffix
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _direct_bases(groups: list[list[dict[str, Any]]], game_id: str) -> list[str]:
    result: list[str] = []
    for candidate in itertools.chain.from_iterable(groups):
        base = _scattered_root(game_id, candidate["url"])
        if base not in result:
            result.append(base)
    return result


class _PackageFilesMissing(PackageFilesError):
    """A candidate was explicitly reported as unavailable by the upstream."""


def _upstream_error(error: Exception, message: str) -> PackageFilesError:
    if isinstance(error, (ManifestTimeout, TimeoutError)) or "timed out" in str(error).lower():
        return PackageFilesTimeout(message)
    if isinstance(error, ManifestNotFound):
        return _PackageFilesMissing(message)
    return PackageFilesUpstream(message)


def _header(headers: Any, name: str) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    wanted = name.casefold()
    for key, value in headers.items():
        if isinstance(key, str) and key.casefold() == wanted:
            return value if isinstance(value, str) else str(value)
    return None


def _download_direct(upstream: Any, url: str) -> bytes:
    try:
        body, headers = upstream.get_bytes(url, allowed_hosts=OFFICIAL_PACKAGE_HOSTS, max_bytes=MAX_DIRECT_BYTES)
    except Exception as error:  # the public boundary maps only our safe error types
        if isinstance(error, PackageFilesError):
            raise
        raise _upstream_error(error, "pkg_version 请求失败") from error
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_DIRECT_BYTES:
        raise PackageFilesUpstream("pkg_version 过大")
    length = _header(headers, "content-length")
    if length is not None:
        try:
            if int(length) != len(body) or int(length) > MAX_DIRECT_BYTES:
                raise PackageFilesUpstream("pkg_version 长度无效")
        except ValueError as error:
            raise PackageFilesUpstream("pkg_version 长度无效") from error
    return bytes(body)


class _ArchiveReader:
    def __init__(self, groups: list[list[dict[str, Any]]], upstream: Any):
        self.groups = groups
        self.upstream = upstream
        self.network_bytes = 0
        self._sizes = [self._size(group[0]) for group in groups]

    @staticmethod
    def _size(candidate: Mapping[str, Any]) -> int:
        size = candidate.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise PackageFilesUpstream("package 分卷大小无效")
        return size

    def _range(self, candidate: Mapping[str, Any], start: int, end: int) -> bytes:
        length = end - start + 1
        if start < 0 or end < start or length > MAX_RANGE_BYTES:
            raise PackageFilesUpstream("package Range 超限")
        url = candidate.get("url")
        if not isinstance(url, str):
            raise PackageFilesUpstream("package URL 无效")
        get_range = getattr(self.upstream, "get_range", None)
        if not callable(get_range):
            raise PackageFilesUpstream("官方 upstream 不支持 bounded Range")
        try:
            body, headers = get_range(
                url, start=start, end=end, allowed_hosts=OFFICIAL_PACKAGE_HOSTS,
                max_bytes=MAX_RANGE_BYTES,
            )
        except Exception as error:
            if isinstance(error, PackageFilesError):
                raise
            raise _upstream_error(error, "package Range 请求失败") from error
        if not isinstance(body, (bytes, bytearray)) or len(body) != length:
            raise PackageFilesUpstream("package Range 响应不完整")
        if self.network_bytes + len(body) > MAX_TOTAL_RANGE_BYTES:
            raise PackageFilesUpstream("package Range 总量超限")
        content_range = _header(headers, "content-range") or ""
        match = re.fullmatch(rf"bytes {start}-{end}/([1-9][0-9]*)", content_range)
        if match is None or int(match.group(1)) != int(candidate["size"]):
            raise PackageFilesUpstream("package Content-Range 无效")
        self.network_bytes += len(body)
        return bytes(body)

    def _map(self, offset: int) -> tuple[int, int]:
        if offset < 0:
            raise PackageFilesUpstream("package 偏移无效")
        remaining = offset
        for index, size in enumerate(self._sizes):
            if remaining < size:
                return index, remaining
            remaining -= size
        raise PackageFilesUpstream("package 偏移越界")

    def read_archive(self, offset: int, length: int) -> bytes:
        if length < 0 or length > MAX_RANGE_BYTES:
            raise PackageFilesUpstream("package Range 超限")
        result = bytearray()
        current = offset
        left = length
        while left:
            index, local = self._map(current)
            take = min(left, self._sizes[index] - local)
            errors: list[PackageFilesError] = []
            for candidate in self.groups[index]:
                try:
                    result.extend(self._range(candidate, local, local + take - 1))
                    break
                except PackageFilesError as exc:
                    errors.append(exc)
            else:
                non_missing = next((error for error in errors if not isinstance(error, _PackageFilesMissing)), None)
                if non_missing is not None:
                    raise non_missing
                if errors:
                    if self.network_bytes:
                        raise PackageFilesUpstream("package Range 请求失败")
                    raise PackageFilesNotFound("官方历史资源不可用")
                raise PackageFilesUpstream("package Range 请求失败")
            current += take
            left -= take
        return bytes(result)

    def tail(self) -> bytes:
        index = len(self.groups) - 1
        start = max(0, self._sizes[index] - TAIL_BYTES)
        errors: list[PackageFilesError] = []
        for candidate in self.groups[index]:
            try:
                return self._range(candidate, start, self._sizes[index] - 1)
            except PackageFilesError as exc:
                errors.append(exc)
        non_missing = next((error for error in errors if not isinstance(error, _PackageFilesMissing)), None)
        if non_missing is not None:
            raise non_missing
        if errors:
            raise PackageFilesNotFound("官方历史资源不可用")
        raise PackageFilesUpstream("package 尾部读取失败")

    def extract_pkg_version(self) -> bytes:
        tail = self.tail()
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0 or len(tail) - eocd < 22:
            head = self.read_archive(0, min(8, self._sizes[0]))
            if not head.startswith(b"PK"):
                raise PackageFilesUnsupported("该完整包格式暂不支持读取文件列表")
            raise PackageFilesUpstream("package EOCD 不存在")
        _, _, _, entries_disk, entries, cd_size, cd_offset, _ = struct.unpack_from("<4s4H2LH", tail, eocd)
        if 0xFFFF in (entries_disk, entries) or 0xFFFFFFFF in (cd_size, cd_offset):
            locator = tail.rfind(b"PK\x06\x07", 0, eocd)
            if locator < 0 or len(tail) - locator < 20:
                raise PackageFilesUpstream("package ZIP64 locator 不存在")
            _, _, zip64_offset, _ = struct.unpack_from("<4sLQL", tail, locator)
            header = self.read_archive(zip64_offset, 56)
            if header[:4] != b"PK\x06\x06":
                raise PackageFilesUpstream("package ZIP64 EOCD 无效")
            values = struct.unpack_from("<4sQ2H2L2Q2Q", header)
            entries, cd_size, cd_offset = values[7], values[8], values[9]
        if cd_size > MAX_CENTRAL_BYTES or entries > MAX_FILES:
            raise PackageFilesUpstream("package central directory 过大")
        central = self.read_archive(cd_offset, cd_size)
        return self._read_member(self._find_entry(central, entries))

    @staticmethod
    def _find_entry(central: bytes, expected_entries: int) -> dict[str, Any]:
        cursor = 0
        found = None
        count = 0
        while cursor < len(central):
            if cursor + 46 > len(central) or central[cursor : cursor + 4] != b"PK\x01\x02":
                raise PackageFilesUpstream("package central directory 损坏")
            fields = struct.unpack_from("<4s6H3L5H2L", central, cursor)
            _, _, _, flags, method, _, _, crc, compressed, uncompressed, name_len, extra_len, comment_len, disk_start, _, _, local_offset = fields
            end = cursor + 46 + name_len + extra_len + comment_len
            if end > len(central):
                raise PackageFilesUpstream("package central entry 越界")
            try:
                name = central[cursor + 46 : cursor + 46 + name_len].decode("utf-8", "strict")
            except UnicodeDecodeError as error:
                raise PackageFilesUpstream("package central entry 名称无效") from error
            extra = central[cursor + 46 + name_len : cursor + 46 + name_len + extra_len]
            compressed, uncompressed, local_offset, disk_start = _zip64_values(extra, compressed, uncompressed, local_offset, disk_start)
            if name == "pkg_version":
                if found is not None:
                    raise PackageFilesUpstream("package pkg_version 重复")
                found = {"flags": flags, "method": method, "crc": crc, "compressed": compressed, "uncompressed": uncompressed, "offset": local_offset, "disk": disk_start}
            count += 1
            if count > MAX_FILES:
                raise PackageFilesUpstream("package central entry 过多")
            cursor = end
        if expected_entries and count != expected_entries:
            raise PackageFilesUpstream("package central entry 数量不一致")
        if found is None:
            raise PackageFilesNotFound("package pkg_version 不存在")
        return found

    def _read_member(self, entry: Mapping[str, Any]) -> bytes:
        if entry["flags"] & 1 or entry["method"] not in (0, 8):
            raise PackageFilesUpstream("package pkg_version 压缩/加密方式不支持")
        compressed = entry["compressed"]
        uncompressed = entry["uncompressed"]
        if compressed > MAX_MEMBER_COMPRESSED_BYTES or uncompressed > MAX_MEMBER_BYTES:
            raise PackageFilesUpstream("package pkg_version 过大")
        offset = entry["offset"] + sum(self._sizes[: entry["disk"]]) if entry["disk"] else entry["offset"]
        local = self.read_archive(offset, 30)
        if local[:4] != b"PK\x03\x04":
            raise PackageFilesUpstream("package local header 无效")
        _, _, _, method, _, _, _, _, _, name_len, extra_len = struct.unpack_from("<4s5H3L2H", local)
        if method != entry["method"]:
            raise PackageFilesUpstream("package local header 压缩方式不一致")
        body = self.read_archive(offset + 30 + name_len + extra_len, compressed)
        try:
            result = zlib.decompress(body, -15) if method == 8 else body
        except zlib.error as error:
            raise PackageFilesUpstream("package pkg_version 解压失败") from error
        if len(result) != uncompressed or (zlib.crc32(result) & 0xFFFFFFFF) != entry["crc"]:
            raise PackageFilesUpstream("package pkg_version CRC 校验失败")
        return result


def _zip64_values(extra: bytes, compressed: int, uncompressed: int, offset: int, disk: int) -> tuple[int, int, int, int]:
    if not any(value in (0xFFFFFFFF, 0xFFFF) for value in (compressed, uncompressed, offset, disk)):
        return compressed, uncompressed, offset, disk
    cursor = 0
    while cursor + 4 <= len(extra):
        field_id, length = struct.unpack_from("<HH", extra, cursor)
        data = extra[cursor + 4 : cursor + 4 + length]
        if field_id == 1:
            position = 0
            values = [uncompressed, compressed, offset, disk]
            formats = ["Q", "Q", "Q", "L"]
            for index, sentinel in enumerate((uncompressed, compressed, offset, disk)):
                if sentinel in (0xFFFFFFFF, 0xFFFF):
                    size = struct.calcsize("<" + formats[index])
                    if position + size > len(data):
                        raise PackageFilesUpstream("package ZIP64 extra 无效")
                    values[index] = struct.unpack_from("<" + formats[index], data, position)[0]
                    position += size
            return values[1], values[0], values[2], values[3]
        cursor += 4 + length
    raise PackageFilesUpstream("package ZIP64 extra 不存在")


def _parse_pkg_version(raw: bytes, download_base: str | None = None) -> list[dict[str, Any]]:
    if len(raw) > MAX_MEMBER_BYTES:
        raise PackageFilesUpstream("pkg_version 过大")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackageFilesUpstream("pkg_version NDJSON 无效") from error
        if not isinstance(value, Mapping) or not isinstance(value.get("remoteName"), str):
            raise PackageFilesUpstream("pkg_version 条目无效")
        try:
            path = strict_relative_posix(value["remoteName"])
        except ManifestBadRequest as error:
            raise PackageFilesUpstream("pkg_version 路径无效") from error
        if path in seen:
            raise PackageFilesUpstream("pkg_version 路径重复")
        seen.add(path)
        size = value.get("fileSize")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PackageFilesUpstream("pkg_version 文件大小无效")
        md5 = value.get("md5")
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
            raise PackageFilesUpstream("pkg_version MD5 无效")
        base = download_base.rstrip("/") if isinstance(download_base, str) else None
        download_url = base + "/" + "/".join(quote(part, safe="") for part in path.split("/")) if base else None
        files.append({
            "type": "file", "name": path.rsplit("/", 1)[-1], "path": path, "size": size,
            "hash": md5.lower(), "md5": md5.lower(), "chunk_count": None, "chunks": [],
            **({"download_url": download_url} if download_url else {}),
        })
        if len(files) > MAX_FILES:
            raise PackageFilesUpstream("pkg_version 条目过多")
    if not files:
        raise PackageFilesUpstream("pkg_version 为空")
    files.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    return files


def _valid_cached_file(value: Any) -> bool:
    if not isinstance(value, Mapping) or value.get("type") != "file":
        return False
    try:
        strict_relative_posix(value.get("path"))
    except ManifestBadRequest:
        return False
    return (
        isinstance(value.get("name"), str)
        and isinstance(value.get("size"), int) and not isinstance(value.get("size"), bool) and value["size"] >= 0
        and isinstance(value.get("md5"), str) and re.fullmatch(r"[0-9a-f]{32}", value["md5"]) is not None
        and value.get("chunk_count") is None and value.get("chunks") == []
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(64 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _ordinary_cache_file(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _cache_dir(state_root: Path, game_id: str, version: str, groups: list[list[dict[str, Any]]]) -> Path:
    material = [
        [{key: candidate.get(key) for key in ("url", "size", "md5")} for candidate in group]
        for group in groups
    ]
    key = hashlib.sha256(json.dumps({"schema": CACHE_SCHEMA_VERSION, "artifacts": material}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return Path(state_root) / "cache" / "package-files" / game_id / version / key


def _load_files(state_root: Path, record: Mapping[str, Any], game_id: str, version: str, identity: str, upstream: Any) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    groups = _candidate_groups(record, game_id, version, identity)
    cache = _cache_dir(Path(state_root), game_id, version, groups)
    index_path, raw_path = cache / "files.json", cache / "pkg_version"
    lock = _lock_for(str(cache))
    with CACHE_LOCK, lock:
        both = _ordinary_cache_file(index_path) and _ordinary_cache_file(raw_path)
        either = index_path.exists() or raw_path.exists()
        if both:
            try:
                value = json.loads(index_path.read_text(encoding="utf-8"))
                files = value.get("files") if isinstance(value, Mapping) else None
                mode = value.get("fetch_mode") if isinstance(value, Mapping) else None
                raw_size = raw_path.stat().st_size
                download_base = value.get("download_base") if isinstance(value, Mapping) else None
                if value.get("schema_version") != CACHE_SCHEMA_VERSION:
                    raise ValueError("invalid cache schema")
                if mode == "official_scattered_files" and (
                    not isinstance(download_base, str) or _official_url(download_base, game_id) is None
                ):
                    raise ValueError("invalid cached download base")
                if mode == "package_zip_member" and download_base is not None:
                    raise ValueError("invalid cached download base")
                if (
                    mode in {"official_scattered_files", "package_zip_member"}
                    and isinstance(files, list) and 0 < len(files) <= MAX_FILES
                    and all(_valid_cached_file(item) for item in files)
                    and raw_size <= MAX_MEMBER_BYTES
                    and value.get("raw_sha256") == _file_sha256(raw_path)
                ):
                    cached = _parse_pkg_version(raw_path.read_bytes(), download_base if mode == "official_scattered_files" else None)
                    if cached == files:
                        return files, 0, {"fetch_mode": mode, "download_base": download_base}
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, PackageFilesError):
                pass
            raise PackageFilesCacheError("package 文件缓存损坏")
        if either:
            raise PackageFilesCacheError("package 文件缓存损坏")
        for base in _direct_bases(groups, game_id):
            try:
                raw = _download_direct(upstream, base + "/pkg_version")
                files = _parse_pkg_version(raw, base)
                _atomic_write(raw_path, raw)
                _atomic_json(index_path, {"schema_version": CACHE_SCHEMA_VERSION, "fetch_mode": "official_scattered_files", "download_base": base, "network_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest(), "files": files})
                return files, len(raw), {"fetch_mode": "official_scattered_files", "download_base": base}
            except _PackageFilesMissing:
                continue
        reader = _ArchiveReader(groups, upstream)
        raw = reader.extract_pkg_version()
        files = _parse_pkg_version(raw)
        _atomic_write(raw_path, raw)
        _atomic_json(index_path, {"schema_version": CACHE_SCHEMA_VERSION, "fetch_mode": "package_zip_member", "download_base": None, "network_bytes": reader.network_bytes, "raw_sha256": hashlib.sha256(raw).hexdigest(), "files": files})
        return files, reader.network_bytes, {"fetch_mode": "package_zip_member", "download_base": None}


def _page(items: list[dict[str, Any]], limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 500:
        raise PackageFilesBadRequest("limit 无效")
    if cursor is None:
        offset = 0
    elif not re.fullmatch(r"0|[1-9][0-9]*", cursor):
        raise PackageFilesBadRequest("cursor 无效")
    else:
        offset = int(cursor)
    page = items[offset : offset + limit]
    return page, str(offset + limit) if offset + limit < len(items) else None


def _directory_page(files: list[dict[str, Any]], path: str, q: str | None, limit: int, cursor: str | None) -> dict[str, Any]:
    try:
        path = strict_relative_posix(path, allow_empty=True)
    except ManifestBadRequest as error:
        raise PackageFilesBadRequest("path 无效") from error
    prefix = path + "/" if path else ""
    if path and (any(item["path"] == path for item in files) or not any(item["path"].startswith(prefix) for item in files)):
        raise PackageFilesNotFound("path 不存在")
    if q:
        selected = [item for item in files if item["path"].startswith(prefix) and q.casefold() in item["path"].casefold()]
        selected.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    else:
        children: dict[str, dict[str, Any]] = {}
        for item in files:
            if not item["path"].startswith(prefix):
                continue
            remainder = item["path"][len(prefix) :]
            if not remainder:
                continue
            name, separator, _ = remainder.partition("/")
            child_path = prefix + name
            if separator:
                child = children.setdefault(child_path, {"type": "directory", "name": name, "path": child_path, "file_count": 0, "size": 0})
                child["file_count"] += 1
                child["size"] += item["size"]
            else:
                children[child_path] = {key: value for key, value in item.items() if key != "chunks"}
        selected = sorted(children.values(), key=lambda item: (item["type"] != "directory", item["name"].casefold(), item["name"]))
    page, next_cursor = _page(selected, limit, cursor)
    return {
        "path": path, "q": q, "items": [{key: value for key, value in item.items() if key != "chunks"} for item in page],
        "total": len(selected), "next_cursor": next_cursor,
        "totals": {"files": sum(item.get("type") == "file" for item in selected), "directories": sum(item.get("type") == "directory" for item in selected), "size": sum(item.get("size", 0) for item in selected)},
    }


def list_files(state_root: Path, record: Mapping[str, Any], game_id: str, version: str, identity: str = "game", path: str = "", q: str | None = None, limit: int = 100, cursor: str | None = None, upstream: Any | None = None) -> dict[str, Any]:
    files, network_bytes, meta = _load_files(Path(state_root), record, game_id, version, identity, upstream)
    result = _directory_page(files, path, q, limit, cursor)
    result.update({"source": "package_pkg_version", "fetch_mode": meta["fetch_mode"], "identity": identity, "network_bytes": network_bytes, "range_bytes": network_bytes})
    return result


def file_detail(state_root: Path, record: Mapping[str, Any], game_id: str, version: str, identity: str, path: str, upstream: Any | None = None) -> dict[str, Any]:
    try:
        wanted = strict_relative_posix(path)
    except ManifestBadRequest as error:
        raise PackageFilesBadRequest("path 无效") from error
    files, network_bytes, meta = _load_files(Path(state_root), record, game_id, version, identity, upstream)
    for item in files:
        if item["path"] == wanted:
            result = {key: value for key, value in item.items() if key != "type" and key != "chunks"}
            result.update({"source": "package_pkg_version", "fetch_mode": meta["fetch_mode"], "identity": identity, "chunk_count": None, "chunks": [], "network_bytes": network_bytes, "range_bytes": network_bytes})
            return result
    raise PackageFilesNotFound("文件不存在")


__all__ = [
    "PackageFilesBadRequest", "PackageFilesCacheError", "PackageFilesError", "PackageFilesNotFound", "PackageFilesTimeout", "PackageFilesUnsupported", "PackageFilesUpstream", "file_detail", "list_files",
]
