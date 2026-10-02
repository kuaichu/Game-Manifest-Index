"""Collect latest complete Windows packages from the official Hypergryph launcher."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.schema_v2 import artifact_id, record_identity, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import (
    VersionStoreError, _persist_v2_record_locked, _prepare_output_root,
    _prepare_v2_target_directory_locked, _read_existing_record, v2_record_path,
)
from url_adapters.common import AdapterError, curl, print_error


SOURCE_URL = "https://launcher.hypergryph.com/api/proxy/batch_proxy"
LAUNCHER_APPCODE = "abYeZZ16BPluCFyT"
GAME_IDENTITIES = {
    "arknights": ("GzD1CpaWgmSq1wew", "ak.hycdn.cn", "production_"),
    "endfield": ("6LL0KJuqHBVz33WK", "beyond.hycdn.cn", "Beyond_Release_"),
}
GAMES = tuple(GAME_IDENTITIES)
_AUTH_QUERY = re.compile(r"auth_key=[0-9]{10}-[0-9a-fA-F]{32}-[0-9]+-[0-9a-fA-F]{32}")


@dataclass(frozen=True)
class HypergryphPackageCollection:
    game_id: str
    source_url: str
    payload: Mapping[str, Any]


def collect(game_id: str, timeout: int = 30) -> HypergryphPackageCollection:
    """Fetch bounded official metadata; never request archive contents."""
    if game_id not in GAME_IDENTITIES:
        raise AdapterError(f"不支持鹰角 PC 游戏：{game_id}")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise AdapterError("timeout 必须是正整数")
    request = {"seq": "5", "proxy_reqs": [{
        "kind": "get_latest_game", "get_latest_game_req": {
            "appcode": GAME_IDENTITIES[game_id][0], "channel": "1", "sub_channel": "1",
            "version": "", "launcher_appcode": LAUNCHER_APPCODE,
        },
    }]}
    raw = curl([
        "--fail", "--proto", "=https", "--max-filesize", "1048576",
        "--header", "Content-Type: application/json", "--data", json.dumps(request),
        SOURCE_URL,
    ], timeout)
    if len(raw) > 1048576:
        raise AdapterError("batch_proxy 响应超过 1 MiB")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise AdapterError("batch_proxy 返回无效 JSON") from error
    if not isinstance(payload, Mapping):
        raise AdapterError("batch_proxy 响应必须是对象")
    return HypergryphPackageCollection(game_id, SOURCE_URL, payload)


def _size(value: Any, field: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterError(f"{field} 必须是非负整数或十进制字符串")
    return value


def _package_identity(url: Any, game_id: str, version: str) -> tuple[str, int]:
    if not isinstance(url, str) or any(ord(char) <= 32 for char in url):
        raise AdapterError("完整包 URL 无效")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise AdapterError("完整包 URL 无效") from error
    appcode, host, prefix = GAME_IDENTITIES[game_id]
    major = ".".join(version.split(".")[:2])
    path_pattern = (
        rf"/{appcode}/{re.escape(major)}/update/1/1/Windows/"
        rf"{re.escape(version)}_[A-Za-z0-9]+/packs/"
        rf"(?P<name>{prefix}[A-Za-z0-9._-]+\.zip\.(?P<part>[0-9]{{3}}))"
    )
    match = re.fullmatch(path_pattern, parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != host or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment
            or match is None or (parsed.query and (
                game_id != "endfield" or _AUTH_QUERY.fullmatch(parsed.query) is None))):
        raise AdapterError("完整包必须使用目标游戏的官方 Windows CDN 路径")
    name, part = match.group("name"), int(match.group("part"))
    if part < 1:
        raise AdapterError("完整包分卷必须从 1 开始")
    return name, part


def organize(collection: HypergryphPackageCollection) -> dict[str, Any]:
    """Only pkg.packs is a complete package; patches and resources stay separate."""
    if (not isinstance(collection, HypergryphPackageCollection)
            or collection.game_id not in GAME_IDENTITIES or collection.source_url != SOURCE_URL
            or not isinstance(collection.payload, Mapping)):
        raise AdapterError("采集结果不是目标游戏的官方 batch_proxy 响应")
    payload = collection.payload
    for key in ("code", "retcode"):
        if key in payload and (isinstance(payload[key], bool) or payload[key] != 0):
            raise AdapterError(f"batch_proxy 失败：{key}={payload[key]!r}")
    responses = payload.get("proxy_rsps")
    if not isinstance(responses, list):
        raise AdapterError("batch_proxy 缺少 proxy_rsps")
    matches = [item for item in responses if isinstance(item, Mapping)
               and item.get("kind") == "get_latest_game"]
    if len(matches) != 1:
        raise AdapterError("batch_proxy 未返回唯一 get_latest_game 响应")
    response = matches[0]
    for key in ("code", "retcode"):
        if key in response and (isinstance(response[key], bool) or response[key] != 0):
            raise AdapterError("get_latest_game 失败")
    latest = response.get("get_latest_game_rsp")
    if not isinstance(latest, Mapping):
        raise AdapterError("batch_proxy 缺少 get_latest_game_rsp")
    version = latest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise AdapterError("官方主版本必须是数字版本号")
    pkg = latest.get("pkg")
    packs = pkg.get("packs") if isinstance(pkg, Mapping) else None
    if not isinstance(packs, list) or not packs:
        raise AdapterError("官方主版本缺少完整包 pkg.packs")
    if "total_size" in pkg:
        _size(pkg["total_size"], "pkg.total_size")
    record = {
        "schema_version": 2, "vendor": "hypergryph", "game_id": collection.game_id,
        "domain_id": f"{collection.game_id}-pc", "platform": "windows", "channel": "official",
        "version": version, "version_code": None, "file_time": None,
        "artifacts": [], "references": [],
        "provenance": {"source_kind": "official_sync", "source_name": "Hypergryph launcher get_latest_game",
                       "source_url": SOURCE_URL},
    }
    archive_parts: dict[str, set[int]] = {}
    names: set[str] = set()
    for pack in packs:
        if not isinstance(pack, Mapping):
            raise AdapterError("pkg.packs 分卷必须是对象")
        name, part = _package_identity(pack.get("url"), collection.game_id, version)
        archive = name.rsplit(".", 1)[0].casefold()
        parts = archive_parts.setdefault(archive, set())
        if name.casefold() in names or part in parts:
            raise AdapterError("pkg.packs 出现重复分卷")
        names.add(name.casefold())
        parts.add(part)
        md5 = pack.get("md5")
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", md5):
            raise AdapterError("完整包 md5 必须是 32 位十六进制字符串")
        artifact = {
            "kind": "package", "component": "game", "package_type": "segment",
            "delivery_mode": "archive", "name": name, "part": part,
            "size": _size(pack.get("package_size"), "package_size"),
            "checksum": {"md5": md5.lower()},
            "urls": [{"url": pack["url"], "provider": "hypergryph", "source_kind": "official", "priority": 0}],
            "source": deepcopy(record["provenance"]),
        }
        artifact["artifact_id"] = artifact_id(artifact, record)
        record["artifacts"].append(artifact)
    for parts in archive_parts.values():
        if parts != set(range(1, max(parts) + 1)):
            raise AdapterError("完整包分卷必须从 1 开始且连续")
    record["artifacts"].sort(key=lambda item: (item["name"].casefold(), item["part"]))
    validate_v2_record(record)
    return record


def _merge_existing(record: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Refresh discovered metadata while retaining unrelated manual/history content."""
    if existing.get("schema_version") != 2:
        return record  # The shared writer handles legacy and identity conflicts.
    validate_v2_record(existing)
    if record_identity(existing) != record_identity(record):
        raise AdapterError("已有记录与官方完整包 identity 冲突")
    updated = deepcopy(existing)
    # Existing record and artifact provenance describe their original acquisition.
    updated.setdefault("provenance", record["provenance"])
    artifacts = {item["artifact_id"]: item for item in updated["artifacts"]}
    for fresh in record["artifacts"]:
        previous = artifacts.get(fresh["artifact_id"])
        if previous is None:
            updated["artifacts"].append(deepcopy(fresh))
            continue
        candidate = fresh["urls"][0]
        new_path = urlsplit(candidate["url"])
        retained = []
        same_url = None
        for old in previous["urls"]:
            old_path = urlsplit(old["url"])
            official_slot = (old["provider"] == "hypergryph" and old["source_kind"] == "official"
                             and (old_path.scheme, old_path.netloc, old_path.path)
                             == (new_path.scheme, new_path.netloc, new_path.path))
            if official_slot:
                if old["url"] == candidate["url"]:
                    same_url = deepcopy(old)
            else:
                retained.append(old)
        for key, value in fresh.items():
            if key not in {"urls", "source"}:
                previous[key] = deepcopy(value)
        previous.setdefault("source", fresh["source"])
        previous["urls"] = [same_url or deepcopy(candidate), *retained]
    validate_v2_record(updated)
    return updated


def discover_collection(collection: HypergryphPackageCollection, output_root: Path) -> Path:
    record = organize(collection)  # Fail all metadata validation before touching storage.
    root = Path(output_root)
    try:
        with DATA_LOCK:
            _prepare_output_root(root)
            target = v2_record_path(record, root)
            with data_file_lock(root):
                _prepare_v2_target_directory_locked(root, target)
                try:
                    existing = _read_existing_record(target)
                except FileNotFoundError:
                    existing = None
                if existing is not None:
                    record = _merge_existing(record, existing)
                return _persist_v2_record_locked(record, root, target, preserve_references=True,
                                                 preserve_provenance=True, preserve_url_current=True)
    except (VersionStoreError, OSError, ValueError) as error:
        raise AdapterError(str(error)) from error


def discover(game_id: str, output_root: Path, timeout: int = 30) -> Path:
    return discover_collection(collect(game_id, timeout), output_root)


discover_v2 = discover
output_v2 = discover


def main() -> int:
    parser = argparse.ArgumentParser(description="鹰角官方 PC 完整包适配器")
    parser.add_argument("game_id", choices=GAMES)
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        print(discover(args.game_id, args.output_root, args.timeout).resolve())
        return 0
    except AdapterError as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
