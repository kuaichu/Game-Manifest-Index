"""Collect and persist official CN HoYoPlay/Sophon chunk manifests."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from backend.schema_v2 import validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError, read_small
from url_adapters.pc.mihoyo_package_organizer import GAME_IDENTITIES

BRANCHES_URL = "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGameBranches"
BUILD_URL = "https://api-takumi.mihoyo.com/downloader/sophon_chunk/api/getBuild"
LAUNCHER_ID = "jGHBHlcOq1"
_LANGUAGES = {"zh-cn", "en-us", "ja-jp", "ko-kr"}


@dataclass(frozen=True)
class MihoyoChunkCollection:
    game_id: str
    hoyoplay_game_id: str
    branch: str
    package_id: str
    tag: str
    diff_tags: list[str]
    build_id: str
    manifests: list[dict[str, object]] = field(repr=False)
    source_url: str = BUILD_URL


def _object(value: object, field: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise AdapterError(f"{field} 必须是对象")
    return value


def _retcode(payload: Mapping, endpoint: str) -> None:
    if isinstance(payload.get("retcode"), bool) or not isinstance(payload.get("retcode"), int) or payload["retcode"] != 0:
        raise AdapterError(f"{endpoint} 返回 retcode={payload.get('retcode')!r}")


def _data(payload: Mapping) -> Mapping:
    if "data" not in payload:
        raise AdapterError("响应缺少 data")
    return _object(payload["data"], "data")


def _find_branches(data: Mapping, game_id: str) -> dict[str, object]:
    raw = data.get("game_branches")
    if not isinstance(raw, list):
        raise AdapterError("getGameBranches 缺少 game_branches")
    expected, biz = GAME_IDENTITIES[game_id]
    games = [
        item
        for item in raw
        if isinstance(item, Mapping)
        and isinstance(item.get("game"), Mapping)
        and item["game"].get("id") == expected
        and item["game"].get("biz") == biz
    ]
    if len(games) != 1 or not isinstance(games[0].get("main"), Mapping):
        raise AdapterError("getGameBranches 未找到唯一 main branch")
    branch = games[0]["main"]
    vals = {key: branch.get(key) for key in ("branch", "package_id", "password", "tag")}
    if not all(isinstance(vals[k], str) and vals[k] for k in ("branch", "package_id", "password", "tag")):
        raise AdapterError("main branch 缺少 branch/package_id/password/tag")
    diff = branch.get("diff_tags", [])
    if not isinstance(diff, list) or not all(isinstance(x, str) and x for x in diff):
        raise AdapterError("main branch.diff_tags 必须是字符串数组")
    vals["diff_tags"] = diff
    return vals


def _build_url(branch: str, package_id: str, password: str, tag: str) -> str:
    return BUILD_URL + "?" + urlencode({
        "branch": branch,
        "package_id": package_id,
        "password": password,
        "plat_app": "ddxf5qt290cg",
        "tag": tag,
    })


def _build_parts(data: Mapping) -> tuple[str, list[dict[str, object]]]:
    build_id = data.get("build_id")
    tag = data.get("tag")
    manifests = data.get("manifests")
    if not isinstance(build_id, str) or not build_id.strip() or not isinstance(tag, str) or not tag.strip():
        raise AdapterError("getBuild 缺少非空 build_id/tag")
    if not isinstance(manifests, list) or not manifests:
        raise AdapterError("getBuild manifests 不能为空")
    return build_id, manifests


def _without_passwords(value: object) -> object:
    """Copy official JSON metadata while dropping every password field."""
    if isinstance(value, Mapping):
        return {
            key: _without_passwords(item)
            for key, item in value.items()
            if not isinstance(key, str) or key.casefold() != "password"
        }
    if isinstance(value, list):
        return [_without_passwords(item) for item in value]
    return value


def _safe_tag(tag: object) -> bool:
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update({f"COM{index}" for index in range(1, 10)})
    reserved.update({f"LPT{index}" for index in range(1, 10)})
    return (isinstance(tag, str) and bool(tag) and tag not in {".", ".."}
            and tag[-1] not in " ." and not any(ord(c) < 32 for c in tag)
            and not any(c in tag for c in '<>:"/\\|?*')
            and tag.upper().split(".")[0] not in reserved)


def _validate_collection(collection: MihoyoChunkCollection) -> None:
    if not isinstance(collection, MihoyoChunkCollection):
        raise AdapterError("采集结果类型无效")
    if collection.game_id not in GAME_IDENTITIES:
        raise AdapterError("不支持米哈游 PC 游戏")
    if collection.hoyoplay_game_id != GAME_IDENTITIES[collection.game_id][0]:
        raise AdapterError("HoYoPlay game id 与 V5 游戏不匹配")
    for name in ("branch", "package_id", "tag", "build_id"):
        if not isinstance(getattr(collection, name), str) or not getattr(collection, name).strip():
            raise AdapterError(f"{name} 必须是非空字符串")
    if not _safe_tag(collection.tag):
        raise AdapterError("tag 不是安全的路径组件")
    if collection.source_url != BUILD_URL:
        raise AdapterError("source_url 不是官方 getBuild endpoint")
    if not isinstance(collection.diff_tags, list) or not all(isinstance(x, str) and x for x in collection.diff_tags):
        raise AdapterError("diff_tags 必须是字符串数组")
    if not isinstance(collection.manifests, list) or not collection.manifests:
        raise AdapterError("manifests 不能为空")


def collect(game_id: str, timeout: int = 30) -> MihoyoChunkCollection:
    if game_id not in GAME_IDENTITIES:
        raise AdapterError(f"不支持米哈游 PC 游戏：{game_id}")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise AdapterError("timeout 必须是正整数")
    branches_url = BRANCHES_URL + "?" + urlencode({
        "launcher_id": LAUNCHER_ID,
        "game_ids[]": GAME_IDENTITIES[game_id][0],
    })
    try:
        branches_payload = json.loads(read_small(branches_url, timeout))
    except json.JSONDecodeError as error:
        raise AdapterError("getGameBranches 返回了无效 JSON") from error
    _object(branches_payload, "getGameBranches 响应")
    _retcode(branches_payload, "getGameBranches")
    branch = _find_branches(_data(branches_payload), game_id)
    build_url = _build_url(branch["branch"], branch["package_id"], branch["password"], branch["tag"])
    try:
        build_payload = json.loads(read_small(build_url, timeout))
    except json.JSONDecodeError as error:
        raise AdapterError("getBuild 返回了无效 JSON") from error
    _object(build_payload, "getBuild 响应")
    _retcode(build_payload, "getBuild")
    build_data = _data(build_payload)
    if build_data.get("tag") != branch["tag"]:
        raise AdapterError("getBuild tag 与 branch tag 不一致")
    build_id, raw_manifests = _build_parts(build_data)
    manifests = _without_passwords(raw_manifests)
    assert isinstance(manifests, list)
    return MihoyoChunkCollection(
        game_id=game_id,
        hoyoplay_game_id=GAME_IDENTITIES[game_id][0],
        branch=branch["branch"],
        package_id=branch["package_id"],
        tag=branch["tag"],
        diff_tags=branch["diff_tags"],
        build_id=build_id,
        manifests=manifests,
    )


def _int(value: object, field: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise AdapterError(f"{field} 必须是非负整数或数字字符串")


def _stats(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise AdapterError("stats 必须是对象")
    return {k: _int(value[k], k) for k in ("compressed_size", "uncompressed_size", "file_count", "chunk_count") if k in value}


def _url_info(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AdapterError("recipe 必须是对象")
    prefix = value.get("url_prefix")
    parsed = urlsplit(prefix) if isinstance(prefix, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AdapterError("recipe.url_prefix 必须是 https URL")
    suffix = value.get("url_suffix", "")
    if not isinstance(suffix, str):
        raise AdapterError("recipe.url_suffix 必须是字符串")
    result = {"url_prefix": prefix, "url_suffix": suffix}
    for key in ("compression", "encryption"):
        item = value.get(key, 0)
        if isinstance(item, bool) or not isinstance(item, int) or item not in (0, 1):
            raise AdapterError(f"recipe.{key} 必须是 0 或 1")
        result[key] = item
    return result


def organize(collection: MihoyoChunkCollection) -> dict:
    _validate_collection(collection)
    items = []
    for index, raw in enumerate(collection.manifests):
        item = _object(raw, f"manifests[{index}]")
        category_id = item.get("category_id")
        if category_id is not None:
            category_id = _int(category_id, "category_id")
        category_name = item.get("category_name")
        if category_name is not None and not isinstance(category_name, str):
            raise AdapterError("category.name 必须是字符串或 null")
        category = {"id": category_id, "name": category_name}
        manifest_raw = item.get("manifest")
        if not isinstance(manifest_raw, Mapping):
            raise AdapterError(f"manifests[{index}].manifest 必须是对象")
        manifest_id = manifest_raw.get("id")
        checksum = manifest_raw.get("checksum")
        if not isinstance(manifest_id, str) or not manifest_id.strip() or not isinstance(checksum, str) or not checksum.strip():
            raise AdapterError(f"manifests[{index}] 缺少 manifest id/checksum")
        manifest = {"id": manifest_id, "checksum": checksum}
        for key in ("compressed_size", "uncompressed_size"):
            if key in manifest_raw:
                manifest[key] = _int(manifest_raw[key], key)
        matching = item.get("matching_field")
        if not isinstance(matching, str) or not matching.strip():
            raise AdapterError(f"manifests[{index}].matching_field 必须是非空字符串")
        if matching == "game":
            component, language = "game", None
        elif matching in _LANGUAGES:
            component, language = "voice", matching
        else:
            component, language = "resource", None
        out = {
            "category": category,
            "manifest": manifest,
            "component": component,
            "language": language,
            "matching_field": matching,
            "stats": _stats(item.get("stats")),
            "deduplicated_stats": _stats(item.get("deduplicated_stats", {})),
        }
        for key in ("manifest_download", "chunk_download"):
            if key not in item:
                raise AdapterError(f"manifests[{index}] 缺少 {key}")
            out[key] = _url_info(item[key])
        items.append(out)
    return {
        "schema_version": 1,
        "vendor": "mihoyo",
        "game_id": collection.game_id,
        "domain_id": f"{collection.game_id}-pc",
        "platform": "windows",
        "version": collection.tag,
        "tag": collection.tag,
        "build_id": collection.build_id,
        "diff_tags": collection.diff_tags,
        "manifests": items,
        "provenance": {
            "source_kind": "official_sync",
            "source_name": "HoYoPlay/Sophon",
            "source_url": BUILD_URL,
        },
    }


def _record(collection: MihoyoChunkCollection) -> dict:
    _validate_collection(collection)
    return {
        "schema_version": 2,
        "vendor": "mihoyo",
        "game_id": collection.game_id,
        "domain_id": f"{collection.game_id}-pc",
        "platform": "windows",
        "channel": "official",
        "version": collection.tag,
        "version_code": None,
        "file_time": None,
        "artifacts": [],
        "references": [{
            "kind": "chunk_manifest",
            "path": f"chunk-manifests/{collection.tag}.json",
            "build_id": collection.build_id,
            "source": {
                "source_kind": "official_sync",
                "source_name": "HoYoPlay/Sophon",
                "source_url": BUILD_URL,
            },
        }],
        "provenance": {
            "source_kind": "official_sync",
            "source_name": "HoYoPlay/Sophon",
            "source_url": BUILD_URL,
        },
    }


def _is_reparse_or_link(path: Path, mode: int) -> bool:
    return stat.S_ISLNK(mode) or bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)


def _safe_directory(parent: Path, name: str) -> Path:
    path = parent / name
    try:
        path.mkdir()
    except FileExistsError:
        pass
    except OSError as error:
        raise AdapterError(f"无法准备输出目录：{path}") from error
    try:
        info = os.lstat(path)
    except OSError as error:
        raise AdapterError(f"无法检查输出目录：{path}") from error
    if _is_reparse_or_link(path, info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AdapterError(f"输出目录不安全：{path}")
    return path


def discover_collection(collection: MihoyoChunkCollection, output_root: Path) -> Path:
    _validate_collection(collection)
    document = organize(collection)
    record = _record(collection)
    validate_v2_record(record)
    root = Path(output_root)
    raw = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        with DATA_LOCK:
            root.mkdir(parents=True, exist_ok=True)
            with data_file_lock(root):
                directory = root
                for name in ("mihoyo", collection.game_id, "pc", "chunk-manifests"):
                    directory = _safe_directory(directory, name)
                target = directory / f"{collection.tag}.json"
                if target.exists() or target.is_symlink():
                    info = os.lstat(target)
                    if _is_reparse_or_link(target, info.st_mode) or not stat.S_ISREG(info.st_mode):
                        raise AdapterError(f"目标文件不安全：{target}")
                fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
    except OSError as error:
        raise AdapterError("无法安全写入 chunk manifest") from error
    try:
        record_path = persist_v2_record(record, root, preserve_artifacts=True, preserve_provenance=True)
    except (VersionStoreError, OSError) as error:
        raise AdapterError(str(error)) from error
    return record_path


def discover(game_id: str, output_root: Path, timeout: int = 30) -> Path:
    return discover_collection(collect(game_id, timeout), output_root)


__all__ = ["BRANCHES_URL", "BUILD_URL", "MihoyoChunkCollection", "collect", "organize", "discover_collection", "discover"]
