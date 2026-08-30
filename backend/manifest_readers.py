"""Read checked-in file manifests and bounded official Sophon resources.

The helpers in this module never write canonical data (or a cache).  Local
documents have already been authenticated by ``ApiContract`` before they are
passed here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote, urljoin, urlsplit

import httpx
import zstandard
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError


MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_DECOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_CHUNK_BYTES = 64 * 1024 * 1024
OFFICIAL_SOPHON_HOSTS = frozenset(
    {
        "autopatchcn.yuanshen.com",
        "autopatchcn.bhsr.com",
        "autopatchcn.juequling.com",
        "autopatchcn.bh3.com",
    }
)


class ManifestError(Exception):
    """Base class with messages safe for the public HTTP boundary."""


class ManifestBadRequest(ManifestError):
    pass


class ManifestNotFound(ManifestError):
    pass


class ManifestCorrupt(ManifestError):
    pass


class ManifestTimeout(ManifestError):
    pass


class ManifestUpstream(ManifestError):
    pass


class Upstream(Protocol):
    def get_bytes(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        max_bytes: int,
        expected_size: int | None = None,
    ) -> tuple[bytes, Mapping[str, str]]: ...


def _validated_https_url(url: str, allowed_hosts: frozenset[str]) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ManifestUpstream("官方资源地址无效") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise ManifestUpstream("官方资源地址无效")


class HttpUpstream:
    """Small no-retry client with checked redirects and response limits."""

    def __init__(self, timeout: float = 20.0, max_redirects: int = 3, transport: httpx.BaseTransport | None = None) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.transport = transport

    def get_bytes(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        max_bytes: int,
        expected_size: int | None = None,
    ) -> tuple[bytes, Mapping[str, str]]:
        _validated_https_url(url, allowed_hosts)
        original = urlsplit(url)
        allowed_query = original.query
        path_prefix = original.path.rsplit("/", 1)[0] + "/"
        current = url
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                for redirect_count in range(self.max_redirects + 1):
                    with client.stream("GET", current, headers={"Accept": "application/octet-stream"}) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count >= self.max_redirects:
                                raise ManifestUpstream("官方资源重定向过多")
                            location = response.headers.get("location")
                            if not location:
                                raise ManifestUpstream("官方资源重定向无效")
                            target = urljoin(current, location)
                            _validated_https_url(target, allowed_hosts)
                            parsed = urlsplit(target)
                            if parsed.query != allowed_query or not parsed.path.startswith(path_prefix):
                                raise ManifestUpstream("官方资源重定向越界")
                            current = target
                            continue
                        if response.status_code in {404, 410}:
                            raise ManifestNotFound("官方资源不存在")
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ManifestUpstream("官方资源请求失败")
                        length = response.headers.get("content-length")
                        if length is not None:
                            try:
                                declared = int(length)
                            except ValueError as error:
                                raise ManifestUpstream("官方资源长度无效") from error
                            if declared < 0 or declared > max_bytes:
                                raise ManifestUpstream("官方资源过大")
                            if expected_size is not None and declared != expected_size:
                                raise ManifestUpstream("官方资源长度不匹配")
                        body = bytearray()
                        for block in response.iter_bytes(64 * 1024):
                            body.extend(block)
                            if len(body) > max_bytes:
                                raise ManifestUpstream("官方资源过大")
                        if expected_size is not None and len(body) != expected_size:
                            raise ManifestUpstream("官方资源长度不匹配")
                        return bytes(body), dict(response.headers)
        except ManifestError:
            raise
        except httpx.TimeoutException as error:
            raise ManifestTimeout("官方资源请求超时") from error
        except httpx.HTTPError as error:
            raise ManifestUpstream("官方资源请求失败") from error
        raise ManifestUpstream("官方资源请求失败")

    def get_range(
        self,
        url: str,
        *,
        start: int,
        end: int,
        allowed_hosts: frozenset[str],
        max_bytes: int,
    ) -> tuple[bytes, Mapping[str, str]]:
        """Fetch one bounded byte range without following redirects."""
        _validated_https_url(url, allowed_hosts)
        if start < 0 or end < start or end - start + 1 > max_bytes:
            raise ManifestUpstream("官方资源 Range 无效")
        expected = end - start + 1
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, transport=self.transport, trust_env=False) as client:
                with client.stream("GET", url, headers={"Accept": "application/octet-stream", "Range": f"bytes={start}-{end}"}) as response:
                    if response.status_code in {404, 410}:
                        raise ManifestNotFound("官方资源不存在")
                    if response.status_code != 206:
                        raise ManifestUpstream("官方资源不支持 Range")
                    content_range = response.headers.get("content-range", "")
                    if not re.fullmatch(rf"bytes {start}-{end}/[1-9][0-9]*", content_range):
                        raise ManifestUpstream("官方资源 Content-Range 无效")
                    length = response.headers.get("content-length")
                    if length is not None:
                        try:
                            if int(length) != expected:
                                raise ManifestUpstream("官方资源 Range 长度无效")
                        except ValueError as error:
                            raise ManifestUpstream("官方资源 Range 长度无效") from error
                    body = bytearray()
                    for block in response.iter_bytes(64 * 1024):
                        body.extend(block)
                        if len(body) > expected or len(body) > max_bytes:
                            raise ManifestUpstream("官方资源 Range 过大")
                    if len(body) != expected:
                        raise ManifestUpstream("官方资源 Range 响应不完整")
                    return bytes(body), dict(response.headers)
        except ManifestError:
            raise
        except httpx.TimeoutException as error:
            raise ManifestTimeout("官方资源请求超时") from error
        except httpx.HTTPError as error:
            raise ManifestUpstream("官方资源请求失败") from error
        raise ManifestUpstream("官方资源请求失败")


def strict_relative_posix(value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ManifestBadRequest("path 无效")
    if value == "" and allow_empty:
        return ""
    if "\\" in value or ":" in value or value.startswith("/") or urlsplit(value).scheme:
        raise ManifestBadRequest("path 无效")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or "\x00" in part for part in parts):
        raise ManifestBadRequest("path 无效")
    return "/".join(parts)


def _page(items: list[dict[str, Any]], limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    if limit < 1 or limit > 500:
        raise ManifestBadRequest("limit 无效")
    if cursor is None:
        offset = 0
    elif not re.fullmatch(r"0|[1-9][0-9]*", cursor):
        raise ManifestBadRequest("cursor 无效")
    else:
        offset = int(cursor)
    page = items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(items) else None
    return page, next_cursor


def _directory_page(
    files: list[dict[str, Any]], path: str, q: str | None, limit: int, cursor: str | None
) -> dict[str, Any]:
    path = strict_relative_posix(path, allow_empty=True)
    prefix = path + "/" if path else ""
    if path and (any(item["path"] == path for item in files) or not any(item["path"].startswith(prefix) for item in files)):
        raise ManifestNotFound("path 不存在")
    if q:
        needle = q.casefold()
        selected = [item for item in files if item["path"].startswith(prefix) and needle in item["path"].casefold()]
        selected.sort(key=lambda item: (item["path"].casefold(), item["path"]))
        page, next_cursor = _page(selected, limit, cursor)
        return {
            "path": path,
            "q": q,
            "items": [{key: value for key, value in item.items() if key != "chunks"} for item in page],
            "total": len(selected),
            "next_cursor": next_cursor,
            "totals": {"files": len(selected), "directories": 0, "size": sum(item["size"] for item in selected)},
        }
    children: dict[str, dict[str, Any]] = {}
    for item in files:
        if not item["path"].startswith(prefix):
            continue
        remainder = item["path"][len(prefix) :]
        first, separator, _ = remainder.partition("/")
        child_path = prefix + first
        if separator:
            child = children.setdefault(
                child_path,
                {"type": "directory", "name": first, "path": child_path, "file_count": 0, "size": 0},
            )
            child["file_count"] += 1
            child["size"] += item["size"]
        else:
            children[child_path] = {"type": "file", **{key: value for key, value in item.items() if key != "chunks"}}
    ordered = sorted(children.values(), key=lambda item: (item["name"].casefold(), item["name"], item["type"]))
    page, next_cursor = _page(ordered, limit, cursor)
    return {
        "path": path,
        "q": None,
        "items": page,
        "total": len(ordered),
        "next_cursor": next_cursor,
        "totals": {
            "files": sum(item.get("file_count", 1) for item in ordered),
            "directories": sum(item["type"] == "directory" for item in ordered),
            "size": sum(item.get("size", 0) for item in ordered),
        },
    }


def _local_files(document: Mapping[str, Any], base_urls: list[str]) -> list[dict[str, Any]]:
    raw = document.get("resource") if isinstance(document.get("resource"), list) else document.get("files")
    if not isinstance(raw, list):
        raise ManifestCorrupt("文件 Manifest 数据损坏")
    result: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ManifestCorrupt("文件 Manifest 数据损坏")
        try:
            path = strict_relative_posix(entry.get("dest"))
        except ManifestBadRequest as error:
            raise ManifestCorrupt("文件 Manifest 路径无效") from error
        if path in seen_paths:
            raise ManifestCorrupt("文件 Manifest 路径重复")
        seen_paths.add(path)
        size = entry.get("size")
        md5 = entry.get("md5")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ManifestCorrupt("文件 Manifest 大小无效")
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
            raise ManifestCorrupt("文件 Manifest checksum 无效")
        md5 = md5.lower()
        object_path = path
        if document.get("vendor") == "perfectworld":
            try:
                object_path = strict_relative_posix(entry.get("object"))
            except ManifestBadRequest as error:
                raise ManifestCorrupt("Perfect World Manifest object 路径无效") from error
            expected_object = f"{md5[0]}/{md5}.{size}"
            if object_path.lower() != expected_object:
                raise ManifestCorrupt("Perfect World Manifest object 身份不匹配")
        download = base_urls[0].rstrip("/") + "/" + quote(object_path, safe="/") if base_urls else None
        result.append(
            {
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "size": size,
                "md5": md5,
                **({"download_url": download} if download else {}),
            }
        )
    result.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    return result


def list_local_files(
    document: Mapping[str, Any], base_urls: list[str], path: str = "", q: str | None = None,
    limit: int = 100, cursor: str | None = None,
) -> dict[str, Any]:
    return _directory_page(_local_files(document, base_urls), path, q, limit, cursor)


def local_files(document: Mapping[str, Any], base_urls: list[str] | None = None) -> list[dict[str, Any]]:
    return _local_files(document, base_urls or [])


def local_file_detail(document: Mapping[str, Any], base_urls: list[str], path: str) -> dict[str, Any]:
    wanted = strict_relative_posix(path)
    for item in _local_files(document, base_urls):
        if item["path"] == wanted:
            return item
    raise ManifestNotFound("文件不存在")


def _proto_class() -> type:
    file = descriptor_pb2.FileDescriptorProto(name="gmi_sophon_manifest.proto", package="gmi.sophon", syntax="proto3")
    root = file.message_type.add(name="SophonManifestProto")
    root.field.add(name="Assets", number=1, label=3, type=11, type_name=".gmi.sophon.SophonManifestAssetProperty")
    asset = file.message_type.add(name="SophonManifestAssetProperty")
    for name, number, field_type, label, type_name in (
        ("AssetName", 1, 9, 1, None),
        ("AssetChunks", 2, 11, 3, ".gmi.sophon.SophonManifestAssetChunk"),
        ("AssetType", 3, 5, 1, None),
        ("AssetSize", 4, 3, 1, None),
        ("AssetHashMd5", 5, 9, 1, None),
    ):
        field = asset.field.add(name=name, number=number, type=field_type, label=label)
        if type_name:
            field.type_name = type_name
    chunk = file.message_type.add(name="SophonManifestAssetChunk")
    for name, number, field_type in (
        ("ChunkName", 1, 9),
        ("ChunkDecompressedHashMd5", 2, 9),
        ("ChunkOnFileOffset", 3, 3),
        ("ChunkSize", 4, 3),
        ("ChunkSizeDecompressed", 5, 3),
    ):
        chunk.field.add(name=name, number=number, type=field_type, label=1)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("gmi.sophon.SophonManifestProto"))


def _find_chunk_entry(document: Mapping[str, Any], identity: str) -> Mapping[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identity):
        raise ManifestBadRequest("identity 无效")
    manifests = document.get("manifests")
    if not isinstance(manifests, list):
        raise ManifestCorrupt("Chunk Manifest 数据损坏")
    matches = [
        item for item in manifests
        if isinstance(item, Mapping) and (item.get("matching_field") == identity or item.get("manifest_id") == identity or (isinstance(item.get("manifest"), Mapping) and item["manifest"].get("id") == identity))
    ]
    if len(matches) != 1:
        raise ManifestNotFound("identity 不存在")
    return matches[0]


def _recipe_url(item: Mapping[str, Any], field: str, name: str) -> str:
    recipe = item.get(field)
    if not isinstance(recipe, Mapping) or "password" in recipe:
        raise ManifestUpstream("官方资源规则无效")
    prefix = recipe.get("url_prefix")
    suffix = recipe.get("url_suffix", "")
    if not isinstance(prefix, str) or not isinstance(suffix, str) or not isinstance(name, str) or not name:
        raise ManifestUpstream("官方资源规则无效")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in suffix) or (suffix and not suffix.startswith("?")):
        raise ManifestUpstream("官方资源规则无效")
    if urlsplit(prefix).query or urlsplit(prefix).fragment:
        raise ManifestUpstream("官方资源规则无效")
    url = prefix.rstrip("/") + "/" + quote(name, safe="") + suffix
    _validated_https_url(url, OFFICIAL_SOPHON_HOSTS)
    return url


def _chunk_files(item: Mapping[str, Any], upstream: Upstream) -> list[dict[str, Any]]:
    manifest = item.get("manifest")
    recipe = item.get("manifest_download")
    if not isinstance(manifest, Mapping) or not isinstance(recipe, Mapping):
        raise ManifestCorrupt("Chunk Manifest 数据损坏")
    if recipe.get("encryption", 0) != 0 or recipe.get("compression", 0) not in (0, 1) or "password" in recipe:
        raise ManifestUpstream("Manifest compression/encryption 不支持")
    manifest_id = manifest.get("id") or item.get("manifest_id")
    if not isinstance(manifest_id, str):
        raise ManifestCorrupt("Chunk Manifest 数据损坏")
    expected_compressed = manifest.get("compressed_size")
    if isinstance(expected_compressed, bool) or (expected_compressed is not None and not isinstance(expected_compressed, int)):
        raise ManifestCorrupt("Chunk Manifest 数据损坏")
    body, _ = upstream.get_bytes(
        _recipe_url(item, "manifest_download", manifest_id),
        allowed_hosts=OFFICIAL_SOPHON_HOSTS,
        max_bytes=MAX_MANIFEST_BYTES,
        expected_size=expected_compressed,
    )
    try:
        raw = zstandard.ZstdDecompressor().decompress(body, max_output_size=MAX_MANIFEST_DECOMPRESSED_BYTES + 1) if recipe.get("compression", 0) == 1 else body
    except (zstandard.ZstdError, ValueError) as error:
        raise ManifestUpstream("Manifest 解压失败") from error
    if len(raw) > MAX_MANIFEST_DECOMPRESSED_BYTES:
        raise ManifestUpstream("Manifest 解压后过大")
    checksum = manifest.get("checksum")
    if not isinstance(checksum, str) or hashlib.md5(raw).hexdigest() != checksum.lower():
        raise ManifestUpstream("Manifest checksum 校验失败")
    try:
        message = _proto_class()()
        message.ParseFromString(raw)
    except (DecodeError, ValueError, TypeError) as error:
        raise ManifestUpstream("Manifest protobuf 无效") from error
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for asset in message.Assets:
        if asset.AssetType != 0:
            continue
        try:
            path = strict_relative_posix(asset.AssetName)
        except ManifestBadRequest as error:
            raise ManifestUpstream("Manifest 文件路径无效") from error
        if path in seen_paths or asset.AssetSize < 0 or not asset.AssetHashMd5:
            raise ManifestUpstream("Manifest 文件字段无效")
        seen_paths.add(path)
        chunks = []
        for chunk in asset.AssetChunks:
            if (
                not chunk.ChunkName
                or "/" in chunk.ChunkName
                or "\\" in chunk.ChunkName
                or any(value < 0 for value in (chunk.ChunkOnFileOffset, chunk.ChunkSize, chunk.ChunkSizeDecompressed))
            ):
                raise ManifestUpstream("Manifest chunk 字段无效")
            chunks.append(
                {
                    "name": chunk.ChunkName,
                    "hash": chunk.ChunkDecompressedHashMd5,
                    "offset": chunk.ChunkOnFileOffset,
                    "size": chunk.ChunkSize,
                    "size_decompressed": chunk.ChunkSizeDecompressed,
                }
            )
        files.append(
            {
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "size": asset.AssetSize,
                "hash": asset.AssetHashMd5,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
        )
    stats = item.get("stats")
    if isinstance(stats, Mapping):
        actual = {
            "file_count": len(files),
            "chunk_count": sum(len(file["chunks"]) for file in files),
            "uncompressed_size": sum(file["size"] for file in files),
        }
        if any(stats.get(key) is not None and stats.get(key) != value for key, value in actual.items()):
            raise ManifestUpstream("Manifest 统计校验失败")
    files.sort(key=lambda entry: (entry["path"].casefold(), entry["path"]))
    return files


def list_chunk_files(
    document: Mapping[str, Any], identity: str, upstream: Upstream, path: str = "", q: str | None = None,
    limit: int = 100, cursor: str | None = None,
) -> dict[str, Any]:
    item = _find_chunk_entry(document, identity)
    result = _directory_page(_chunk_files(item, upstream), path, q, limit, cursor)
    result["identity"] = item.get("matching_field") or (item.get("manifest") or {}).get("id")
    result["fetch_mode"] = "upstream_manifest"
    return result


def chunk_file_detail(document: Mapping[str, Any], identity: str, upstream: Upstream, path: str) -> dict[str, Any]:
    wanted = strict_relative_posix(path)
    item = _find_chunk_entry(document, identity)
    for file in _chunk_files(item, upstream):
        if file["path"] == wanted:
            return {"identity": item.get("matching_field") or (item.get("manifest") or {}).get("id"), "fetch_mode": "upstream_manifest", **file}
    raise ManifestNotFound("文件不存在")


def chunk_content(document: Mapping[str, Any], identity: str, name: str, upstream: Upstream) -> tuple[bytes, Mapping[str, str]]:
    if not isinstance(name, str) or not re.fullmatch(r"[^/\\\x00-\x20\x7f]+", name):
        raise ManifestBadRequest("chunk name 无效")
    item = _find_chunk_entry(document, identity)
    sizes = {chunk["size"] for file in _chunk_files(item, upstream) for chunk in file["chunks"] if chunk["name"] == name}
    if not sizes:
        raise ManifestNotFound("Chunk 不存在")
    if len(sizes) != 1:
        raise ManifestUpstream("Manifest chunk 身份冲突")
    expected = sizes.pop()
    if expected > MAX_CHUNK_BYTES:
        raise ManifestUpstream("Chunk 过大")
    return upstream.get_bytes(
        _recipe_url(item, "chunk_download", name),
        allowed_hosts=OFFICIAL_SOPHON_HOSTS,
        max_bytes=MAX_CHUNK_BYTES,
        expected_size=expected,
    )


__all__ = [
    "HttpUpstream", "ManifestBadRequest", "ManifestCorrupt", "ManifestError", "ManifestNotFound",
    "ManifestTimeout", "ManifestUpstream", "chunk_content", "chunk_file_detail", "list_chunk_files",
    "list_local_files", "local_file_detail", "local_files", "strict_relative_posix",
]
