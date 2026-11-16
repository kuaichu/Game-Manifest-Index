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
from copy import deepcopy
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
RESOURCE_PACKS_URL = (
    "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/game/"
    "10003_oLNgHF1CESo51DGHN2odtp40e3oI1HfZ/G152/official/index.json"
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
    resource_packs: dict[str, dict[str, object]] | None = None
    pack_documents: dict[str, list[tuple[str | None, dict[str, object]]]] | None = None
    bundles: dict[str, list[str]] | None = None


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
    _safe_target(clean_path, "Launcher 路径")
    if urlsplit(path).query or urlsplit(path).fragment:
        raise AdapterError("Launcher 路径不能包含 query 或 fragment")
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
    _safe_component(version, "version")
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
        _safe_component(patch["version"], "patchConfig.version")
        route_key = patch["version"].casefold()
        if route_key == version.casefold() or route_key in patch_versions:
            raise AdapterError("patchConfig version 必须唯一且不同于当前版本")
        patch_versions.add(route_key)
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
    for item in [config, *patches]:
        for base in cdns:
            _safe_url(base, item["indexFile"])
            _safe_url(base, item["baseUrl"])
    return version, dict(config), cdns


def _resource_launcher(payload: object) -> tuple[
    str, dict[str, dict[str, object]], list[str], dict[str, list[str]],
]:
    if not isinstance(payload, Mapping):
        raise AdapterError("Launcher 必须是对象")
    packs = payload.get("resourcePacks")
    if not isinstance(packs, Mapping) or not packs:
        raise AdapterError("Launcher resourcePacks 必须是非空对象")
    normalized = {}
    versions = set()
    names = set()
    for name, config in packs.items():
        _safe_component(_string(name, "resource pack"), "resource pack")
        if name.casefold() in names:
            raise AdapterError("resource pack 名称重复")
        names.add(name.casefold())
        version, config, cdns = _launcher({"default": {
            "config": config, "cdnList": payload.get("cdnList"),
        }})
        versions.add(version)
        normalized[name] = config
    if len(versions) != 1:
        raise AdapterError("resourcePacks version 必须一致")
    bundles = payload.get("bundles")
    if not isinstance(bundles, Mapping) or not bundles:
        raise AdapterError("Launcher bundles 必须是非空对象")
    combinations = {}
    for name, bundle in bundles.items():
        _safe_component(_string(name, "bundle"), "bundle")
        members = bundle.get("resourcePacks") if isinstance(bundle, Mapping) else None
        if (not isinstance(members, list) or not members
                or any(not isinstance(member, str) or member not in normalized for member in members)
                or len(set(members)) != len(members)):
            raise AdapterError("bundle resourcePacks 必须唯一且引用已有 pack")
        combinations[name] = list(members)
    return version, normalized, cdns, combinations


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
    # Launcher install groups are metadata, not a filter: retain every resource.
    if "tagGroups" in payload:
        if not isinstance(payload["tagGroups"], Mapping):
            raise AdapterError("tagGroups 必须是对象")
        try:
            json.dumps(payload["tagGroups"], allow_nan=False)
        except (TypeError, ValueError) as error:
            raise AdapterError("tagGroups 必须是 JSON 对象") from error
        result["tagGroups"] = deepcopy(dict(payload["tagGroups"]))
    return result


def _validate_collection(collection: KuroManifestCollection) -> None:
    if not isinstance(collection, KuroManifestCollection):
        raise AdapterError("采集结果类型无效")
    if collection.launcher_url not in {LAUNCHER_URL, RESOURCE_PACKS_URL}:
        raise AdapterError("launcher_url 不是官方 GameStarter endpoint")
    if collection.resource_packs is not None:
        if collection.config or collection.documents or collection.launcher_url != RESOURCE_PACKS_URL:
            raise AdapterError("resource pack collection 与旧式 collection 混用")
        if not isinstance(collection.bundles, dict):
            raise AdapterError("resource pack bundles 必须是对象")
        version, packs, cdns, bundles = _resource_launcher({
            "resourcePacks": collection.resource_packs,
            "cdnList": [{"url": url} for url in collection.cdns],
            "bundles": {name: {"resourcePacks": members}
                        for name, members in collection.bundles.items()},
        })
        if (version != collection.version or packs != collection.resource_packs
                or cdns != collection.cdns or bundles != collection.bundles):
            raise AdapterError("resource pack collection 与 launcher 不一致")
        if not isinstance(collection.pack_documents, dict) or set(collection.pack_documents) != set(packs):
            raise AdapterError("resource pack documents 不匹配")
        for name, config in packs.items():
            _validate_collection(KuroManifestCollection(
                version, config, cdns, collection.pack_documents[name], collection.launcher_url,
            ))
        return
    if collection.pack_documents is not None or collection.bundles is not None:
        raise AdapterError("旧式 collection 不应包含 resource pack metadata")
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
        if "tagGroups" in document:
            expected_keys.add("tagGroups")
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
        index_payload = {"resource": document["resource"], "deleteFiles": document["deleteFiles"]}
        if "tagGroups" in document:
            index_payload["tagGroups"] = document["tagGroups"]
        normalized = _index_document(
            index_payload,
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
    launcher, _ = _json(RESOURCE_PACKS_URL, timeout, "Launcher")
    if isinstance(launcher, Mapping) and "resourcePacks" in launcher:
        version, packs, cdns, bundles = _resource_launcher(launcher)
        documents = {name: _collect_documents(version, config, cdns, timeout)
                     for name, config in packs.items()}
        return KuroManifestCollection(
            version, {}, cdns, [], RESOURCE_PACKS_URL, packs, documents, bundles,
        )
    version, config, cdns = _launcher(launcher)
    return KuroManifestCollection(
        version, config, cdns, _collect_documents(version, config, cdns, timeout),
        RESOURCE_PACKS_URL,
    )


def _collect_documents(
    version: str, config: dict[str, object], cdns: list[str], timeout: int,
) -> list[tuple[str | None, dict[str, object]]]:
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
    return documents


def _manifest_path(version: str, pack: str | None, route: str | None) -> str:
    prefix = f"manifests/{version}/" + (f"packs/{pack}/" if pack is not None else "")
    return prefix + ("full.json" if route is None else f"patches/{route}.json")


def _artifact(
    collection: KuroManifestCollection,
    route_from: str | None,
    item: Mapping[str, object],
    pack: str | None = None,
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
        "source_url": collection.launcher_url,
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
                "path": _manifest_path(collection.version, pack, route_from),
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
                "path": _manifest_path(collection.version, pack, route_from),
                "base_urls": base_urls,
            },
            "urls": index_urls,
            "source": source,
        }
    if pack is not None:
        label = "common" if pack == "common" else pack.upper()
        obj["name"] = (f"WutheringWaves-{collection.version}-{label}-resource-pack (bundle component)"
                       if route_from is None else f"{label}-resource-pack:{route_from}->{collection.version}")
        if route_from is None:
            obj.update(package_type="segment", part=1)
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
    artifacts = [_artifact(collection, route, config, pack)
                 for pack, route, config, _ in _collection_entries(collection)]
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
            "source_url": collection.launcher_url,
        },
    }
    validate_v2_record(record)
    return record


def _collection_entries(collection: KuroManifestCollection):
    packs = collection.resource_packs or {None: collection.config}
    for pack, config in packs.items():
        patches = {patch["version"]: patch for patch in config["patchConfig"]}
        documents = collection.documents if pack is None else collection.pack_documents[pack]
        for route, document in documents:
            yield pack, route, config if route is None else patches[route], document


def _bundle_document(collection: KuroManifestCollection, record: dict[str, object]) -> dict[str, object]:
    packs = {name: {"package": None, "patches": {}} for name in collection.resource_packs}
    for (pack, route, _, _), artifact in zip(_collection_entries(collection), record["artifacts"]):
        entry = {"artifact_id": artifact["artifact_id"], "manifest": artifact["manifest"]["path"]}
        if route is None:
            packs[pack]["package"] = entry
        else:
            packs[pack]["patches"][route] = entry
    return {
        "schema_version": 1, "vendor": "kuro", "game_id": "wuwa", "platform": "windows",
        "version": collection.version, "resourcePacks": packs,
        "bundles": {name: {"resourcePacks": members} for name, members in collection.bundles.items()},
        "provenance": deepcopy(record["provenance"]),
    }


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
                documents = [(_manifest_path(collection.version, pack, route), document)
                             for pack, route, _, document in _collection_entries(collection)]
                if collection.resource_packs is not None:
                    documents.append((f"manifests/{collection.version}/resource-packs.json",
                                      _bundle_document(collection, record)))
                for relative, document in documents:
                    parts = PurePosixPath(relative).parts[2:]
                    target_dir = directory
                    for part in parts[:-1]:
                        target_dir = _safe_dir(target_dir, part)
                    filename = parts[-1]
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
        return persist_v2_record(record, root, preserve_references=True, preserve_url_current=True)
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
