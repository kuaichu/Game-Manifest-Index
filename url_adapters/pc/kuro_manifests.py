"""Official Kuro GameStarter file manifests for Wuthering Waves PC."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

from backend.schema_v2 import artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError, curl, print_error

LAUNCHER_URL = (
    "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/game/"
    "G152/10003_Y8xXrXk65DqFHEDgApn3cpK5lfczpFx5/index.json"
)
MAX_JSON_BYTES = 2 * 1024 * 1024
_MD5 = re.compile(r"^[0-9a-fA-F]{32}$")


def read_small(url: str, timeout: int) -> str:
    """Read one bounded launcher/index response as latin-1-preserved text."""
    return curl(["--fail", "--max-filesize", str(MAX_JSON_BYTES), url], timeout)


@dataclass(frozen=True)
class KuroManifestCollection:
    version: str
    config: dict[str, object]
    cdns: list[str]
    documents: list[tuple[str | None, dict[str, object]]]
    launcher_url: str = LAUNCHER_URL


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"库洛 Launcher {field} 必须是非空字符串")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterError(f"库洛 Launcher {field} 必须是非负整数")
    return value


def _safe_component(value: str, field: str) -> None:
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
    if (
        not value
        or value in {".", ".."}
        or value[-1] in " ."
        or any(ord(c) < 32 for c in value)
        or any(c in value for c in '<>:"/\\|?*')
        or value.upper().split(".")[0] in reserved
    ):
        raise AdapterError(f"{field} 不是安全的路径组件")


def _safe_target(value: object, field: str = "dest") -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise AdapterError(f"{field} 不是安全的相对 POSIX 路径")
    parts = value.split("/")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise AdapterError(f"{field} 不是安全的相对 POSIX 路径")
    return "/".join(parts)


def _safe_url(base: str, path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")) or "\\" in path:
        raise AdapterError("Launcher 路径必须是安全的相对路径")
    clean_path = path.rstrip("/")
    if not clean_path or any(part in {"", ".", ".."} for part in PurePosixPath(clean_path).parts):
        raise AdapterError("Launcher 路径必须是安全的相对路径")
    joined = urljoin(base.rstrip("/") + "/", path)
    if not joined.startswith(base.rstrip("/") + "/"):
        raise AdapterError("Launcher 路径越出 CDN 根目录")
    return joined


def _json_bytes(url: str, timeout: int) -> bytes:
    try:
        raw = read_small(url, timeout)
    except Exception as error:
        raise AdapterError(f"请求失败：{url}") from error
    data = raw.encode("latin-1")
    if len(data) > MAX_JSON_BYTES:
        raise AdapterError("JSON 超过 2MiB 限制")
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data = stream.read(MAX_JSON_BYTES + 1)
        except (EOFError, OSError) as error:
            raise AdapterError("响应包含无效 gzip 数据") from error
        if len(data) > MAX_JSON_BYTES:
            raise AdapterError("JSON 超过 2MiB 限制")
    return data


def _json(url: str, timeout: int, label: str) -> tuple[object, bytes]:
    data = _json_bytes(url, timeout)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterError(f"{label} 返回了无效 JSON") from error
    return value, data


def _launcher(payload: object) -> tuple[str, dict[str, object], list[str]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("default"), Mapping):
        raise AdapterError("Launcher default 必须是对象")
    default = payload["default"]
    config = default.get("config")
    if not isinstance(config, Mapping):
        raise AdapterError("Launcher default.config 必须是对象")
    version = _string(config.get("version"), "config.version")
    for key in ("indexFile", "baseUrl", "indexFileMd5", "patchType"):
        _string(config.get(key), f"config.{key}")
    if not _MD5.fullmatch(config["indexFileMd5"]):
        raise AdapterError("config.indexFileMd5 必须是 32 位十六进制")
    _integer(config.get("size"), "config.size")
    _integer(config.get("unCompressSize"), "config.unCompressSize")
    patches = config.get("patchConfig")
    if not isinstance(patches, list):
        raise AdapterError("config.patchConfig 必须是数组")
    patch_versions = set()
    for i, patch in enumerate(patches):
        if not isinstance(patch, Mapping):
            raise AdapterError(f"patchConfig[{i}] 必须是对象")
        for key in ("version", "indexFile", "baseUrl", "indexFileMd5"):
            _string(patch.get(key), f"patchConfig[{i}].{key}")
        if patch["version"] == version or patch["version"] in patch_versions:
            raise AdapterError("patchConfig version 必须唯一且不同于当前版本")
        patch_versions.add(patch["version"])
        if not _MD5.fullmatch(patch["indexFileMd5"]):
            raise AdapterError(f"patchConfig[{i}].indexFileMd5 无效")
        _integer(patch.get("size"), f"patchConfig[{i}].size")
        _integer(patch.get("unCompressSize"), f"patchConfig[{i}].unCompressSize")
    cdn_list = default.get("cdnList")
    if not isinstance(cdn_list, list) or not cdn_list:
        raise AdapterError("Launcher default.cdnList 必须是非空数组")
    cdns = []
    for i, item in enumerate(cdn_list):
        if not isinstance(item, Mapping):
            raise AdapterError(f"cdnList[{i}] 必须是对象")
        url = item.get("url")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            parsed is None or parsed.scheme != "https" or not parsed.netloc
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise AdapterError(f"cdnList[{i}].url 必须是 https base URL")
        if url in cdns:
            raise AdapterError("cdnList URL 重复")
        cdns.append(url)
    return version, dict(config), cdns


def _index_document(
    payload: object, *, version: str, route_from: str | None, selected_url: str,
) -> dict[str, object]:
    parsed_source = urlsplit(selected_url) if isinstance(selected_url, str) else None
    if (
        parsed_source is None or parsed_source.scheme != "https" or not parsed_source.netloc
        or parsed_source.username or parsed_source.password
    ):
        raise AdapterError("selected index URL 必须是无凭证的 https URL")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("resource"), list):
        raise AdapterError("index resource 必须是数组")
    resources = []
    seen = set()
    for i, item in enumerate(payload["resource"]):
        if not isinstance(item, Mapping):
            raise AdapterError(f"resource[{i}] 必须是对象")
        dest = _safe_target(item.get("dest"), f"resource[{i}].dest")
        if dest in seen:
            raise AdapterError("resource dest 重复")
        seen.add(dest)
        md5 = item.get("md5")
        if not isinstance(md5, str) or not _MD5.fullmatch(md5):
            raise AdapterError(f"resource[{i}].md5 无效")
        size = _integer(item.get("size"), f"resource[{i}].size")
        resources.append({"dest": dest, "md5": md5.lower(), "size": size})
    deletes = payload.get("deleteFiles", [])
    if not isinstance(deletes, list):
        raise AdapterError("deleteFiles 必须是数组")
    normalized = []
    seen.clear()
    for item in deletes:
        path = _safe_target(item, "deleteFiles")
        if path in seen:
            raise AdapterError("deleteFiles 重复")
        seen.add(path)
        normalized.append(path)
    result: dict[str, object] = {
        "schema_version": 1, "vendor": "kuro", "game_id": "wuwa",
        "platform": "windows", "version": version,
    }
    if route_from is not None:
        result.update(route_from=route_from, route_to=version)
    result.update(
        resource=resources,
        deleteFiles=normalized,
        provenance={"source_kind": "official_sync", "source_url": selected_url},
    )
    return result


def _validate_collection(collection: KuroManifestCollection) -> None:
    if not isinstance(collection, KuroManifestCollection):
        raise AdapterError("采集结果类型无效")
    if collection.launcher_url != LAUNCHER_URL:
        raise AdapterError("launcher_url 不是官方 GameStarter endpoint")
    _safe_component(collection.version, "version")
    version, config, cdns = _launcher({
        "default": {"config": collection.config, "cdnList": [{"url": url} for url in collection.cdns]}
    })
    if version != collection.version or config != collection.config or cdns != collection.cdns:
        raise AdapterError("采集结果与 launcher 配置不一致")
    expected_routes = [None] + [patch["version"] for patch in collection.config["patchConfig"]]
    patch_configs = {patch["version"]: patch for patch in collection.config["patchConfig"]}
    if not isinstance(collection.documents, list) or len(collection.documents) != len(expected_routes):
        raise AdapterError("manifest documents 与 launcher routes 不一致")
    for index, (expected_route, entry) in enumerate(zip(expected_routes, collection.documents)):
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise AdapterError(f"documents[{index}] 格式无效")
        route, document = entry
        if route != expected_route or not isinstance(document, Mapping):
            raise AdapterError("manifest document route 不匹配")
        expected_keys = {"schema_version", "vendor", "game_id", "platform", "version",
                         "resource", "deleteFiles", "provenance"}
        if route is not None:
            expected_keys.update({"route_from", "route_to"})
        if set(document) != expected_keys:
            raise AdapterError("manifest document 字段无效")
        if (document.get("schema_version") != 1 or document.get("vendor") != "kuro"
                or document.get("game_id") != "wuwa" or document.get("platform") != "windows"
                or document.get("version") != collection.version):
            raise AdapterError("manifest document identity 不匹配")
        if route is not None and (document.get("route_from"), document.get("route_to")) != (route, collection.version):
            raise AdapterError("manifest document route identity 不匹配")
        item_config = collection.config if route is None else patch_configs[route]
        allowed_sources = {_safe_url(base, item_config["indexFile"]) for base in collection.cdns}
        provenance = document.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("source_url") not in allowed_sources:
            raise AdapterError("manifest document source 不是官方 index candidate")
        normalized = _index_document(
            {"resource": document["resource"], "deleteFiles": document["deleteFiles"]},
            version=collection.version, route_from=route,
            selected_url=provenance["source_url"],
        )
        if normalized != document:
            raise AdapterError("manifest document 未规范化")


def collect(game_id: str = "wuwa", timeout: int = 30) -> KuroManifestCollection:
    if game_id != "wuwa":
        raise AdapterError("库洛 PC 适配器只支持 wuwa")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise AdapterError("timeout 必须是正整数")
    launcher, _ = _json(LAUNCHER_URL, timeout, "Launcher")
    version, config, cdns = _launcher(launcher)
    jobs = [(None, config)] + [(str(p["version"]), dict(p)) for p in config["patchConfig"]]
    documents = []
    for route_from, item in jobs:
        expected = item["indexFileMd5"].lower()
        selected = None
        parsed = None
        for base in cdns:
            candidate = _safe_url(base, item["indexFile"])
            try:
                value, raw = _json(candidate, timeout, "index")
            except AdapterError:
                continue
            if hashlib.md5(raw).hexdigest() != expected:
                continue
            parsed, selected = value, candidate
            break
        if selected is None:
            raise AdapterError("官方 index 候选全部失败或 MD5 不匹配")
        documents.append((route_from, _index_document(
            parsed,
            version=version,
            route_from=route_from,
            selected_url=selected,
        )))
    return KuroManifestCollection(version, config, cdns, documents)


def _artifact(
    collection: KuroManifestCollection,
    route_from: str | None,
    item: Mapping[str, object],
) -> dict[str, object]:
    base_urls = [
        {
            "url": _safe_url(base, item["baseUrl"]),
            "provider": "kuro",
            "source_kind": "official",
            "priority": priority,
        }
        for priority, base in enumerate(collection.cdns)
    ]
    index_urls = [
        {
            "url": _safe_url(base, item["indexFile"]),
            "provider": "kuro",
            "source_kind": "official",
            "priority": priority,
        }
        for priority, base in enumerate(collection.cdns)
    ]
    source = {
        "source_kind": "official_sync",
        "source_name": "Kuro GameStarter",
        "source_url": LAUNCHER_URL,
    }
    if route_from is None:
        obj = {
            "kind": "package",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "file_manifest",
            "name": f"WutheringWaves-{collection.version}-full",
            "size": item["size"],
            "decompressed_size": item["unCompressSize"],
            "manifest": {
                "path": f"manifests/{collection.version}/full.json",
                "base_urls": base_urls,
            },
            "urls": index_urls,
            "source": source,
        }
    else:
        obj = {
            "kind": "patch",
            "component": "game",
            "package_type": "differential",
            "delivery_mode": "file_manifest",
            "name": f"{route_from}->{collection.version}",
            "route_from": route_from,
            "route_to": collection.version,
            "size": item["size"],
            "decompressed_size": item["unCompressSize"],
            "manifest": {
                "path": f"manifests/{collection.version}/patches/{route_from}.json",
                "base_urls": base_urls,
            },
            "urls": index_urls,
            "source": source,
        }
    identity = {
        "vendor": "kuro",
        "game_id": "wuwa",
        "domain_id": "wuwa-pc",
        "platform": "windows",
        "channel": "official",
        "version": collection.version,
    }
    obj["artifact_id"] = artifact_id(obj, identity)
    return obj


def organize(collection: KuroManifestCollection) -> dict[str, object]:
    _validate_collection(collection)
    patches = {patch["version"]: patch for patch in collection.config["patchConfig"]}
    artifacts = [
        _artifact(collection, route, collection.config if route is None else patches[route])
        for route, _ in collection.documents
    ]
    record = {
        "schema_version": 2,
        "vendor": "kuro",
        "game_id": "wuwa",
        "domain_id": "wuwa-pc",
        "platform": "windows",
        "channel": "official",
        "version": collection.version,
        "version_code": None,
        "file_time": None,
        "artifacts": artifacts,
        "references": [],
        "provenance": {
            "source_kind": "official_sync",
            "source_name": "Kuro GameStarter",
            "source_url": LAUNCHER_URL,
        },
    }
    validate_v2_record(record)
    return record


def _safe_dir(parent: Path, name: str) -> Path:
    _safe_component(name, "目录")
    path = parent / name
    try:
        path.mkdir()
    except FileExistsError:
        pass
    info = os.lstat(path)
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
    ):
        raise AdapterError("输出目录不安全")
    return path


def discover_collection(collection: KuroManifestCollection, output_root: Path) -> Path:
    _validate_collection(collection)
    record = organize(collection)
    root = Path(output_root)
    try:
        with DATA_LOCK:
            root.mkdir(parents=True, exist_ok=True)
            with data_file_lock(root):
                directory = root
                for part in ("kuro", "wuwa", "pc", "manifests", collection.version):
                    directory = _safe_dir(directory, part)
                for route, document in collection.documents:
                    target_dir = directory if route is None else _safe_dir(directory, "patches")
                    filename = "full.json" if route is None else f"{route}.json"
                    target = target_dir / filename
                    if target.exists() or target.is_symlink():
                        info = os.lstat(target)
                        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                                or getattr(info, "st_file_attributes", 0) & 0x400):
                            raise AdapterError("目标文档不安全")
                    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target_dir)
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
    except (OSError, ValueError) as error:
        raise AdapterError("无法安全写入 Kuro manifest") from error
    try:
        return persist_v2_record(record, root, preserve_references=True)
    except (VersionStoreError, OSError) as error:
        raise AdapterError(str(error)) from error


def discover(
    game_id: str = "wuwa", output_root: Path = Path("data"), timeout: int = 30,
) -> Path:
    return discover_collection(collect(game_id, timeout), output_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("game_id", choices=["wuwa"])
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        print(discover(args.game_id, args.output_root, args.timeout))
    except AdapterError as error:
        raise SystemExit(print_error(error))
