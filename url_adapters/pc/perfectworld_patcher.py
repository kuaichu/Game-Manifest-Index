"""Official Perfect World PatcherSDK file manifests for Windows PC games."""
from __future__ import annotations

import io
import json
import os
import re
import stat
import struct
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from backend.schema_v2 import artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError, print_error

MAGIC = b"PatcherXML0\0"
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
OBJECT_RE = re.compile(r"^([0-9a-fA-F]{32})\.([0-9]+)$")
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_MEMBER_BYTES = 256 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024


class PerfectWorldError(ValueError):
    pass


# Stable names retained for callers that used the protocol helper while it
# lived in the old project.  They do not expose any legacy record shape.
PerfectWorldManifestError = PerfectWorldError


@dataclass(frozen=True)
class Profile:
    game_id: str
    domain_id: str
    host: str
    base_path: str
    key_seed: str
    root_url: str

    @property
    def config_url(self) -> str:
        return f"https://{self.host}{self.base_path}/Version/Windows/config.xml"

    def reslist_url(self, version: str) -> str:
        if not VERSION_RE.fullmatch(version):
            raise PerfectWorldError("版本号不安全")
        return f"https://{self.host}{self.base_path}/Version/Windows/version/{version}/ResList.bin.zip"

    def object_path(self, object_name: str) -> str:
        match = OBJECT_RE.fullmatch(object_name)
        if not match:
            raise PerfectWorldError("对象名无效")
        digest = match.group(1).lower()
        return f"{digest[0]}/{digest}.{int(match.group(2))}"


PROFILES = {
    "nte": Profile("nte", "nte-pc", "yhcdn1.wmupd.com", "/clientRes/publish_PC", "1289@Patcher", "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/"),
    "p5x": Profile("p5x", "p5x-pc", "nsywl-client-dev1.wmupd.com", "/clientRes/CN_OB_OFFICIAL", "1264@Patcher", "https://nsywl-client-dev1.wmupd.com/clientRes/CN_OB_OFFICIAL/Res/"),
    "tof": Profile("tof", "tof-pc", "htcdn1.wmupd.com", "/clientRes/Windows55", "1256@Patcher", "https://htcdn1.wmupd.com/clientRes/Windows55/Res/"),
}
GAMES = tuple(PROFILES)


@dataclass(frozen=True)
class Collection:
    game_id: str
    version: str
    config: dict[str, Any]
    files: list[dict[str, Any]]
    patch_objects: list[dict[str, Any]]
    config_url: str
    reslist_url: str
    root_url: str
    config_size: int
    reslist_size: int


def _pad16(value: str) -> bytes:
    raw = value.encode("utf-8")
    if not raw:
        raise PerfectWorldError("PatcherSDK seed 不能为空")
    return raw[:16].ljust(16, b"0")


def decode_patcherxml0(data: bytes, key_seed: str, iv_seed: str = "PatcherSDK") -> bytes:
    if not data.startswith(MAGIC):
        return data
    if len(data) < 32 or (len(data) - 16) % 16:
        raise PerfectWorldError("PatcherXML0 长度或分块无效")
    expected = struct.unpack_from("<I", data, 12)[0]
    if expected > MAX_MEMBER_BYTES:
        raise PerfectWorldError("PatcherXML0 解码大小超限")
    try:
        decrypted = AES.new(_pad16(key_seed), AES.MODE_CBC, _pad16(iv_seed)).decrypt(data[16:])
        try:
            compressed_options = (unpad(decrypted, 16),)
        except ValueError:
            compressed_options = (decrypted,)
        decoded = None
        for compressed in compressed_options:
            stream = zlib.decompressobj()
            try:
                candidate = stream.decompress(compressed, expected + 1)
            except zlib.error:
                continue
            if len(candidate) == expected and stream.eof and not stream.unconsumed_tail and not stream.unused_data:
                decoded = candidate
                break
        if decoded is None:
            raise PerfectWorldError("PatcherXML0 压缩数据无效")
        return decoded
    except (ValueError, zlib.error) as error:
        raise PerfectWorldError("PatcherSDK seed/压缩数据校验失败") from error


def read_zip_members(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_ZIP_BYTES:
        raise PerfectWorldError("ResList ZIP 超过大小限制")
    allowed = {"ResList.bin", "PatchList.bin", "lastdiff.bin", "ResList.xml", "PatchList.xml"}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            result: dict[str, bytes] = {}
            total = 0
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if name not in allowed or name in result or info.is_dir() or name.startswith("/") or ".." in name.split("/"):
                    raise PerfectWorldError("ResList ZIP member 不被允许或重复")
                if info.file_size > MAX_MEMBER_BYTES or total + info.file_size > MAX_TOTAL_MEMBER_BYTES:
                    raise PerfectWorldError("ResList ZIP 解压大小超限")
                payload = archive.read(info)
                if len(payload) != info.file_size:
                    raise PerfectWorldError("ResList ZIP member 长度不匹配")
                result[name] = payload
                total += len(payload)
    except zipfile.BadZipFile as error:
        raise PerfectWorldError("ResList ZIP 无效") from error
    if "ResList.bin" not in result and "ResList.xml" not in result:
        raise PerfectWorldError("ResList ZIP 缺少 ResList.bin")
    return result


def _official_path(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or port not in (None, 443):
        return False
    for profile in PROFILES.values():
        if parsed.hostname != profile.host:
            continue
        config_path = profile.base_path + "/Version/Windows/config.xml"
        prefix = profile.base_path + "/Version/Windows/version/"
        if parsed.path == config_path:
            return True
        if parsed.path.startswith(prefix) and parsed.path.endswith("/ResList.bin.zip"):
            return bool(VERSION_RE.fullmatch(parsed.path[len(prefix):-len("/ResList.bin.zip")]))
    return False


def fetch_bounded(url: str, timeout: int, *, max_bytes: int) -> tuple[bytes, dict[str, str], int, str]:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise PerfectWorldError("timeout 必须是正整数")
    if not _official_path(url):
        raise PerfectWorldError("仅允许完美世界官方清单 URL")
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "GMI-perfectworld-patcher/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final = str(response.geturl())
            if final != url or status not in {200, 206} or not _official_path(final):
                raise PerfectWorldError(f"官方响应无效：HTTP {status}")
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise PerfectWorldError("官方响应超过大小限制")
            body = bytearray()
            while True:
                chunk = response.read(min(65536, max_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise PerfectWorldError("官方响应超过大小限制")
            return bytes(body), {str(k).lower(): str(v) for k, v in response.headers.items()}, status, final
    except PerfectWorldError:
        raise
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise PerfectWorldError(f"官方请求失败或超时：{error}") from error


def _text(root: ET.Element, name: str) -> str:
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == name.lower() and node.text:
            return node.text.strip()
    return ""


def parse_config(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_CONFIG_BYTES:
        raise PerfectWorldError("config.xml 超过 2MiB 限制")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered or b"<![" in lowered:
        raise PerfectWorldError("config.xml XML 特性不被允许")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise PerfectWorldError("config.xml XML 无效") from error
    version = _text(root, "ResVersion")
    if not VERSION_RE.fullmatch(version):
        raise PerfectWorldError("config.xml ResVersion 无效")
    values: dict[str, Any] = {"version": version}
    for key in ("ResSize", "Hash", "Compressed", "Encrypt", "Section", "diffHash", "listHash"):
        raw = _text(root, key)
        if key == "ResSize":
            try:
                values["res_size"] = int(raw or 0)
            except ValueError as error:
                raise PerfectWorldError("config.xml ResSize 无效") from error
            if values["res_size"] < 0:
                raise PerfectWorldError("config.xml ResSize 无效")
        else:
            values[key[0].lower() + key[1:]] = raw
    values["baseVersion"] = _text(root, "BaseVerson") or _text(root, "BaseVersion")
    return values


def _safe_path(value: Any, label: str = "清单文件路径") -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value) or "://" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise PerfectWorldError(f"{label}不安全")
    return value


def _object(value: Any, label: str) -> tuple[str, int]:
    if not isinstance(value, str):
        raise PerfectWorldError(f"{label}对象名无效")
    clean = value.rsplit("/", 1)[-1] if value.count("/") == 1 else value
    match = OBJECT_RE.fullmatch(clean)
    if not match:
        raise PerfectWorldError(f"{label}对象名无效")
    if "/" in value and value != f"{match.group(1)[0].lower()}/{match.group(1).lower()}.{int(match.group(2))}":
        raise PerfectWorldError(f"{label}对象路径无效")
    return match.group(1).lower(), int(match.group(2))


def _identity(value: Any, label: str) -> tuple[str, int]:
    if not isinstance(value, str):
        raise PerfectWorldError(f"{label}对象名无效")
    match = OBJECT_RE.fullmatch(value)
    if not match or str(int(match.group(2))) != match.group(2):
        raise PerfectWorldError(f"{label}对象名不规范")
    return match.group(1).lower(), int(match.group(2))


def _size(value: Any) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError) as error:
        raise PerfectWorldError("清单文件大小无效") from error
    if result < 0:
        raise PerfectWorldError("清单文件大小无效")
    return result


def parse_reslist(data: bytes, profile: Profile) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    members = read_zip_members(data)
    res_xml = decode_patcherxml0(members.get("ResList.bin", members.get("ResList.xml", b"")), profile.key_seed)
    if len(res_xml) > MAX_XML_BYTES:
        raise PerfectWorldError("ResList XML 超过大小限制")
    if any(token in res_xml.lower() for token in (b"<!doctype", b"<!entity", b"<![")):
        raise PerfectWorldError("ResList XML 特性不被允许")
    try:
        root = ET.fromstring(res_xml)
    except ET.ParseError as error:
        raise PerfectWorldError("ResList XML 无效") from error
    if root.tag.rsplit("}", 1)[-1] != "ResList":
        raise PerfectWorldError("ResList XML 根节点无效")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "Res":
            continue
        dest = _safe_path(item.attrib.get("filename"), "ResList filename")
        md5 = item.attrib.get("md5", "").lower()
        if not MD5_RE.fullmatch(md5):
            raise PerfectWorldError("ResList md5 无效")
        if dest in seen:
            raise PerfectWorldError("ResList 文件路径重复")
        seen.add(dest)
        size = _size(item.attrib.get("filesize"))
        files.append({"dest": dest, "md5": md5, "size": size, "object": profile.object_path(f"{md5}.{size}")})
    if not files:
        raise PerfectWorldError("ResList 没有文件")
    patches: list[dict[str, Any]] = []
    patch_blob = members.get("PatchList.bin") or members.get("lastdiff.bin") or members.get("PatchList.xml")
    if patch_blob:
        patch_xml = decode_patcherxml0(patch_blob, profile.key_seed)
        if len(patch_xml) > MAX_XML_BYTES:
            raise PerfectWorldError("PatchList XML 超过大小限制")
        if any(token in patch_xml.lower() for token in (b"<!doctype", b"<!entity", b"<![")):
            raise PerfectWorldError("PatchList XML 特性不被允许")
        try:
            patch_root = ET.fromstring(patch_xml)
        except ET.ParseError as error:
            raise PerfectWorldError("PatchList XML 无效") from error
        if patch_root.tag.rsplit("}", 1)[-1] != "PatchList":
            raise PerfectWorldError("PatchList XML 根节点无效")
        for item in patch_root.iter():
            if item.tag.rsplit("}", 1)[-1] != "Patch":
                continue
            oldfile, newfile, patch = (item.attrib.get(key, "") for key in ("oldfile", "newfile", "patch"))
            old_hash, old_size = _identity(oldfile, "PatchList oldfile")
            new_hash, new_size = _identity(newfile, "PatchList newfile")
            patch_hash, patch_size = _identity(patch, "PatchList patch")
            v = item.attrib.get("v", "")
            if not re.fullmatch(r"[0-9a-fA-F]+", v):
                raise PerfectWorldError("PatchList v 无效")
            patches.append({
                "oldfile": f"{old_hash}.{old_size}",
                "newfile": f"{new_hash}.{new_size}",
                "patch": f"{patch_hash}.{patch_size}",
                "object": profile.object_path(f"{patch_hash}.{patch_size}"),
                "v": v,
                "size": patch_size,
            })
    return files, patches


def _collection(game_id: str, config: Mapping[str, Any], files: list[dict[str, Any]], patches: list[dict[str, Any]], *, config_url: str, reslist_url: str, root_url: str, config_size: int, reslist_size: int) -> Collection:
    if game_id not in PROFILES:
        raise AdapterError("完美世界 PC 适配器只支持 nte/p5x/tof")
    version = config.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise AdapterError("版本号不安全")
    if not isinstance(config_url, str) or config_url != PROFILES[game_id].config_url or not isinstance(reslist_url, str) or reslist_url != PROFILES[game_id].reslist_url(version) or root_url != PROFILES[game_id].root_url:
        raise AdapterError("采集结果 URL 与官方 profile 不一致")
    return Collection(game_id, version, dict(config), list(files), list(patches), config_url, reslist_url, root_url, config_size, reslist_size)


def _document(collection: Collection) -> dict[str, Any]:
    files = [{"dest": item["dest"], "size": item["size"], "md5": item["md5"], "object": item["object"]} for item in collection.files]
    patches = [{key: item[key] for key in ("oldfile", "newfile", "patch", "object", "v", "size")} for item in collection.patch_objects]
    return {
        "schema_version": 1,
        "vendor": "perfectworld",
        "game_id": collection.game_id,
        "domain_id": PROFILES[collection.game_id].domain_id,
        "platform": "windows",
        "version": collection.version,
        "files": files,
        "patch_objects": patches,
        "config": {
            "version": collection.config["version"],
            "res_size": collection.config["res_size"],
            "hash": collection.config["hash"],
            "compressed": collection.config["compressed"],
            "encrypt": collection.config["encrypt"],
            "section": collection.config["section"],
            "diff_hash": collection.config["diffHash"],
            "list_hash": collection.config["listHash"],
            "base_version": collection.config["baseVersion"],
            "config_response_size": collection.config_size,
            "reslist_response_size": collection.reslist_size,
        },
        "provenance": {"source_kind": "official_sync", "source_name": "Perfect World PatcherSDK", "source_url": collection.config_url},
    }


def _validate_collection(collection: Collection) -> None:
    if not isinstance(collection, Collection):
        raise AdapterError("采集结果类型无效")
    profile = PROFILES.get(collection.game_id)
    if profile is None:
        raise AdapterError("完美世界 PC 适配器只支持 nte/p5x/tof")
    if not isinstance(collection.version, str) or not VERSION_RE.fullmatch(collection.version):
        raise AdapterError("版本号不安全")
    if collection.config_url != profile.config_url or collection.reslist_url != profile.reslist_url(collection.version) or collection.root_url != profile.root_url:
        raise AdapterError("采集结果 URL 与官方 profile 不一致")
    config = collection.config
    expected_config = {"version", "res_size", "hash", "compressed", "encrypt", "section", "diffHash", "listHash", "baseVersion"}
    if not isinstance(config, Mapping):
        raise AdapterError("config metadata 必须是对象")
    if set(config) != expected_config or config.get("version") != collection.version:
        raise AdapterError("config metadata 不规范")
    if isinstance(config["res_size"], bool) or not isinstance(config["res_size"], int) or config["res_size"] < 0:
        raise AdapterError("config res_size 无效")
    for key in expected_config - {"version", "res_size"}:
        if not isinstance(config[key], str):
            raise AdapterError(f"config {key} 必须是字符串")
    for key in ("config_size", "reslist_size"):
        value = getattr(collection, key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AdapterError(f"{key} 无效")
    if not isinstance(collection.files, list) or not collection.files:
        raise AdapterError("ResList files 必须是非空数组")
    destinations: set[str] = set()
    for index, item in enumerate(collection.files):
        if not isinstance(item, Mapping):
            raise AdapterError(f"files[{index}] 必须是对象")
        if set(item) != {"dest", "md5", "size", "object"}:
            raise AdapterError(f"files[{index}] 字段不规范")
        dest = _safe_path(item.get("dest"), f"files[{index}].dest")
        md5 = item.get("md5")
        if not isinstance(md5, str) or not MD5_RE.fullmatch(md5):
            raise AdapterError(f"files[{index}].md5 无效")
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise AdapterError(f"files[{index}].size 无效")
        object_name = item.get("object")
        object_hash, object_size = _object(object_name, f"files[{index}].object")
        if object_hash != md5.lower() or object_size != size:
            raise AdapterError(f"files[{index}].object 与文件元数据不一致")
        if object_name != profile.object_path(f"{md5}.{size}"):
            raise AdapterError(f"files[{index}].object 路径不规范")
        if dest in destinations:
            raise AdapterError("ResList 文件路径重复")
        destinations.add(dest)
    if not isinstance(collection.patch_objects, list):
        raise AdapterError("patch_objects 必须是数组")
    for index, item in enumerate(collection.patch_objects):
        if not isinstance(item, Mapping):
            raise AdapterError(f"patch_objects[{index}] 必须是对象")
        if set(item) != {"oldfile", "newfile", "patch", "object", "v", "size"}:
            raise AdapterError(f"patch_objects[{index}] 字段不规范")
        for key in ("oldfile", "newfile", "patch"):
            value = item.get(key)
            digest, size = _identity(value, f"patch_objects[{index}].{key}")
            if value != f"{digest}.{size}":
                raise AdapterError(f"patch_objects[{index}].{key} identity 不规范")
        patch_digest, patch_size = _identity(item["patch"], f"patch_objects[{index}].patch")
        object_digest, object_size = _object(item["object"], f"patch_objects[{index}].object")
        if (object_digest, object_size) != (patch_digest, patch_size) or item["object"] != profile.object_path(item["patch"]):
            raise AdapterError(f"patch_objects[{index}].object 路径不规范")
        if not isinstance(item.get("v"), str) or not re.fullmatch(r"[0-9a-fA-F]+", item["v"]):
            raise AdapterError(f"patch_objects[{index}].v 无效")
        if isinstance(item.get("size"), bool) or item.get("size") != patch_size:
            raise AdapterError(f"patch_objects[{index}].size 与 patch 对象不一致")


def organize(collection: Collection) -> dict[str, Any]:
    _validate_collection(collection)
    try:
        document = _document(collection)
        artifact = {
            "kind": "package", "component": "game", "package_type": "full", "delivery_mode": "file_manifest",
            "name": "ResList.bin.zip",
            "size": sum(item["size"] for item in collection.files),
            "manifest": {"path": f"manifests/{collection.version}/files.json", "base_urls": [{"url": collection.root_url, "provider": "perfectworld", "source_kind": "official", "priority": 0}]},
            "urls": [{"url": collection.reslist_url, "provider": "perfectworld", "source_kind": "official", "priority": 0}],
            "source": {"source_kind": "official_sync", "source_name": "Perfect World PatcherSDK", "source_url": collection.config_url},
        }
        identity = {"vendor": "perfectworld", "game_id": collection.game_id, "domain_id": PROFILES[collection.game_id].domain_id, "platform": "windows", "channel": "official", "version": collection.version}
        artifact["artifact_id"] = artifact_id(artifact, identity)
        record = {"schema_version": 2, **identity, "version_code": None, "file_time": None, "artifacts": [artifact], "references": [], "provenance": artifact["source"]}
        validate_v2_record(record)
        return record
    except (PerfectWorldError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, AdapterError):
            raise
        raise AdapterError(f"完美世界清单整理失败：{error}") from error


def _write_document(target: Path, document: Mapping[str, Any]) -> None:
    if target.exists() or target.is_symlink():
        info = os.lstat(target)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AdapterError("目标文档不安全")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _safe_dir(parent: Path, name: str) -> Path:
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if (not name or name in {".", ".."} or name[-1] in " ." or any(ord(ch) < 32 for ch in name)
            or name.upper().split(".", 1)[0] in reserved or any(ch in name for ch in '<>:"/\\|?*')):
        raise AdapterError("输出目录不安全")
    path = parent / name
    try:
        path.mkdir()
    except FileExistsError:
        pass
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise AdapterError("输出目录不安全")
    return path


def discover_collection(collection: Collection, output_root: Path) -> Path:
    record = organize(collection)
    document = _document(collection)
    root = Path(output_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with DATA_LOCK, data_file_lock(root):
            directory = root
            for name in ("perfectworld", collection.game_id, "pc", "manifests", collection.version):
                directory = _safe_dir(directory, name)
            _write_document(directory / "files.json", document)
    except (OSError, ValueError) as error:
        raise AdapterError("无法安全写入 Perfect World manifest") from error
    try:
        return persist_v2_record(record, root, preserve_references=True)
    except (VersionStoreError, OSError, ValueError) as error:
        raise AdapterError(str(error)) from error


def _fetch_one(url: str, timeout: int, max_bytes: int) -> tuple[bytes, dict[str, str]]:
    try:
        body, headers, _status, _final = fetch_bounded(url, timeout, max_bytes=max_bytes)
        return body, headers
    except PerfectWorldError as error:
        raise AdapterError(str(error)) from error


def collect(game_id: str, timeout: int = 30, *, fetcher: Callable[[str, int], bytes] | None = None) -> Collection:
    if game_id not in PROFILES:
        raise AdapterError("完美世界 PC 适配器只支持 nte/p5x/tof")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise AdapterError("timeout 必须是正整数")
    profile = PROFILES[game_id]
    if fetcher is None:
        config_body, config_headers = _fetch_one(profile.config_url, timeout, MAX_CONFIG_BYTES)
    else:
        config_body, config_headers = fetcher(profile.config_url, timeout), {}
    try:
        config = parse_config(config_body)
        reslist_url = profile.reslist_url(config["version"])
        if fetcher is None:
            archive, archive_headers = _fetch_one(reslist_url, timeout, MAX_ZIP_BYTES)
        else:
            archive, archive_headers = fetcher(reslist_url, timeout), {}
        files, patches = parse_reslist(archive, profile)
    except PerfectWorldError as error:
        raise AdapterError(f"{game_id} 官方 PatcherSDK：{error}") from error
    def header_size(headers: Mapping[str, str], fallback: int) -> int:
        value = headers.get("content-length", "")
        return int(value) if isinstance(value, str) and value.isdigit() else fallback
    return _collection(game_id, config, files, patches, config_url=profile.config_url, reslist_url=reslist_url, root_url=profile.root_url, config_size=header_size(config_headers, len(config_body)), reslist_size=header_size(archive_headers, len(archive)))


def discover(game_id: str, output_root: Path = Path("data"), timeout: int = 30, *, fetcher: Callable[[str, int], bytes] | None = None) -> Path:
    return discover_collection(collect(game_id, timeout, fetcher=fetcher), output_root)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("game_id", choices=GAMES)
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        print(discover(args.game_id, args.output_root, args.timeout))
    except AdapterError as error:
        raise SystemExit(print_error(error))
