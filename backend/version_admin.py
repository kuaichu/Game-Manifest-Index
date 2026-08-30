"""Canonical helpers for protected version administration."""

from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from backend.admin_probe import ADMIN_PROBE_LOCK, stable_url_id, valid_probe_url
from backend.api_contract import (
    GAME_CATALOG,
    GAME_IDS,
    MAX_RECORD_BYTES,
    VENDORS,
    DomainData,
    _domain_projection,
    _summary as public_summary,
    _version_key,
    fail,
)
from backend.domain_registry import is_nondefault_pc_domain, nondefault_pc_domains
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import write_v2_record


IDENTITY_FIELDS = ("vendor", "game_id", "domain_id", "platform", "channel", "version")
CHECKSUM_KINDS = ("md5", "sha256", "crc64")
ARTIFACT_ATTRIBUTE_FIELDS = (
    "component",
    "package_type",
    "delivery_mode",
    "language",
    "route_from",
    "route_to",
    "decompressed_size",
    "manifest",
    "source",
)


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(value)
        and value not in {".", ".."}
        and not any(char in value for char in '<>:"/\\|?*')
        and not any(ord(char) < 32 for char in value)
    )


def _ordinary(path: Path, *, directory: bool = False) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    return (
        expected
        and not stat.S_ISLNK(info.st_mode)
        and not bool(getattr(info, "st_file_attributes", 0) & 0x400)
    )


def _exists_or_link(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _disk_platform(platform: str) -> str:
    if platform == "android":
        return "android"
    if platform == "windows":
        return "pc"
    raise ValueError("unsupported platform")


def domain_info(root: Path, domain_id: str) -> tuple[str, str, str, Path]:
    if not _safe_component(domain_id):
        fail(404, "domain_not_found", "归档域不存在")

    root = Path(root)
    if not _ordinary(root, directory=True):
        fail(500, "unsafe_data_path", "数据目录不安全")
    matches: list[tuple[str, str, str, Path]] = []
    if "-" in domain_id:
        game_id, suffix = domain_id.rsplit("-", 1)
        if game_id in GAME_IDS and suffix in {"android", "pc"}:
            platform = "android" if suffix == "android" else "windows"
            disk = _disk_platform(platform)
            for vendor in VENDORS:
                candidate = root / vendor / game_id / disk
                if _exists_or_link(candidate):
                    matches.append((vendor, game_id, platform, candidate))
    if not matches:
        for vendor in VENDORS:
            for game_id in GAME_IDS:
                if not is_nondefault_pc_domain(vendor, game_id, domain_id):
                    continue
                candidate = root / vendor / game_id / "pc" / "domains" / domain_id
                if _exists_or_link(candidate):
                    matches.append((vendor, game_id, "windows", candidate))
    if not matches:
        fail(404, "domain_not_found", "归档域不存在")
    if len(matches) != 1:
        fail(500, "unsafe_data_path", "归档域路径不唯一")

    vendor, game_id, platform, directory = matches[0]
    current = root
    for part in directory.relative_to(root).parts:
        current = current / part
        if not _ordinary(current, directory=True):
            fail(500, "unsafe_data_path", "数据目录不安全")
    return vendor, game_id, platform, directory


def _read_record(path: Path) -> dict[str, Any]:
    if not _ordinary(path):
        fail(500, "corrupt_data", "归档数据损坏")
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            fail(500, "corrupt_data", "归档数据损坏")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(500, "corrupt_data", "归档数据损坏")
    if not isinstance(value, dict):
        fail(500, "corrupt_data", "归档数据损坏")
    try:
        validate_v2_record(value)
    except ValueError:
        fail(500, "corrupt_data", "归档数据损坏")
    return value


def _check_path_identity(
    record: Mapping[str, Any],
    path: Path,
    *,
    vendor: str,
    game_id: str,
    platform: str,
    domain_id: str,
) -> None:
    expected = {
        "vendor": vendor,
        "game_id": game_id,
        "platform": platform,
        "domain_id": domain_id,
        "version": path.stem,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        fail(500, "record_identity_mismatch", "版本记录身份不匹配")


def read_record(
    root: Path, domain_id: str, version: str,
) -> tuple[dict[str, Any], Path, tuple[str, str, str]]:
    if not _safe_component(version):
        fail(404, "version_not_found", "版本不存在")
    vendor, game_id, platform, directory = domain_info(root, domain_id)
    path = directory / f"{version}.json"
    if not _exists_or_link(path):
        fail(404, "version_not_found", "版本不存在")
    if not _ordinary(path):
        fail(500, "unsafe_data_path", "版本路径不安全")
    record = _read_record(path)
    _check_path_identity(
        record,
        path,
        vendor=vendor,
        game_id=game_id,
        platform=platform,
        domain_id=domain_id,
    )
    return record, path, (vendor, game_id, platform)


def scan_domain(
    root: Path, domain_id: str,
) -> tuple[str, str, str, Path, list[dict[str, Any]]]:
    vendor, game_id, platform, directory = domain_info(root, domain_id)
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
        if path.name == "index.json":
            continue
        if not _ordinary(path):
            fail(500, "unsafe_data_path", "归档文件不安全")
        record = _read_record(path)
        _check_path_identity(
            record,
            path,
            vendor=vendor,
            game_id=game_id,
            platform=platform,
            domain_id=domain_id,
        )
        records.append(record)
    records.sort(key=lambda item: _version_key(item["version"]), reverse=True)
    return vendor, game_id, platform, directory, records


def _record_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in IDENTITY_FIELDS}


def _checksum_value(kind: str, value: Any) -> str:
    if kind not in CHECKSUM_KINDS or not isinstance(value, str) or not value.strip():
        fail(422, "validation_error", "checksum 无效")
    return value


def _normalize_artifact(
    raw: Mapping[str, Any],
    identity: Mapping[str, Any],
    *,
    old: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    kind = raw.get("kind")
    if kind == "file":
        if identity["platform"] != "android":
            fail(422, "validation_error", "PC artifact kind 无效")
        kind = "apk"
    if kind not in {"apk", "package", "patch"}:
        fail(422, "validation_error", "artifact kind 无效")

    name = raw.get("name")
    size = raw.get("size", 0)
    if not isinstance(name, str) or not name.strip():
        fail(422, "validation_error", "artifact name 无效")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        fail(422, "validation_error", "artifact size 无效")

    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), Mapping) else {}
    component = raw.get("component") or attributes.get("component") or "game"
    package_type = raw.get("package_type") or attributes.get("package_type")
    delivery_mode = raw.get("delivery_mode") or attributes.get("delivery_mode")
    if kind == "apk":
        package_type = package_type or "full"
        delivery_mode = delivery_mode or "direct"
    elif identity["platform"] == "windows":
        if not package_type or not delivery_mode:
            fail(422, "validation_error", "PC artifact 必须明确 package_type 和 delivery_mode")
    else:
        package_type = package_type or ("differential" if kind == "patch" else "full")
        delivery_mode = delivery_mode or "direct"

    artifact: dict[str, Any] = {
        "kind": kind,
        "component": component,
        "package_type": package_type,
        "delivery_mode": delivery_mode,
        "name": name,
        "size": size,
        "urls": [],
    }
    for key in ARTIFACT_ATTRIBUTE_FIELDS[3:]:
        value = raw.get(key, attributes.get(key))
        if value is not None:
            artifact[key] = copy.deepcopy(value)

    part = raw.get("part")
    if kind == "package" and package_type == "segment":
        if isinstance(part, bool) or not isinstance(part, int) or part < 1:
            fail(422, "validation_error", "segment part 无效")
        artifact["part"] = part
    elif part not in (None, 1):
        fail(422, "validation_error", "artifact part 无效")

    checksum = (
        copy.deepcopy(old.get("checksum", {}))
        if isinstance(old, Mapping) and isinstance(old.get("checksum"), Mapping)
        else {}
    )
    checksum_type = raw.get("checksum_type")
    checksum_value = raw.get("checksum_value")
    if checksum_type is not None or checksum_value is not None:
        if not isinstance(checksum_type, str):
            fail(422, "validation_error", "checksum 无效")
        checksum[checksum_type] = _checksum_value(checksum_type, checksum_value)
    for kind_name in CHECKSUM_KINDS:
        if attributes.get(kind_name) is not None:
            checksum[kind_name] = _checksum_value(kind_name, attributes[kind_name])
    if checksum:
        artifact["checksum"] = checksum

    old_candidates = old.get("urls", []) if isinstance(old, Mapping) else []
    old_urls = {
        candidate["url"]: candidate
        for candidate in old_candidates
        if isinstance(candidate, Mapping)
        and isinstance(candidate.get("url"), str)
    }
    raw_urls = raw.get("urls")
    if not isinstance(raw_urls, list) or not raw_urls:
        fail(422, "validation_error", "artifact 至少需要一个 URL")
    seen_urls: set[str] = set()
    seen_priorities: set[int] = set()
    for item in raw_urls:
        if not isinstance(item, Mapping):
            fail(422, "validation_error", "URL 无效")
        url = item.get("url")
        priority = item.get("priority", 0)
        source_kind = item.get("source_kind", "manual")
        if not isinstance(url, str) or not valid_probe_url(url) or url in seen_urls:
            fail(422, "validation_error", "URL 无效或重复")
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or priority < 0
            or priority in seen_priorities
        ):
            fail(422, "validation_error", "priority 无效或重复")
        if not isinstance(source_kind, str) or not source_kind.strip():
            fail(422, "validation_error", "source_kind 无效")
        previous = old_urls.get(url)
        candidate = {
            "url": url,
            "provider": (
                item.get("provider")
                or (previous.get("provider") if isinstance(previous, Mapping) else None)
                or "manual"
            ),
            "source_kind": source_kind,
            "priority": priority,
        }
        if isinstance(previous, Mapping) and "current" in previous:
            candidate["current"] = copy.deepcopy(previous["current"])
        artifact["urls"].append(candidate)
        seen_urls.add(url)
        seen_priorities.add(priority)

    artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
    return artifact


def _apply_primary_compatibility(payload: Mapping[str, Any], artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    file_path = payload.get("file_path")
    if file_path is not None:
        if not isinstance(file_path, str) or not file_path.strip():
            fail(422, "validation_error", "file_path 无效")
        artifacts[0]["name"] = file_path
    if "unpacked_size" in payload:
        value = payload["unpacked_size"]
        if value is None:
            artifacts[0].pop("decompressed_size", None)
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail(422, "validation_error", "unpacked_size 无效")
        else:
            artifacts[0]["decompressed_size"] = value
    checksum_type = payload.get("files_checksum_type")
    checksum_value = payload.get("files_checksum_value")
    if checksum_type is not None or checksum_value is not None:
        if not isinstance(checksum_type, str):
            fail(422, "validation_error", "files checksum 无效")
        artifacts[0].setdefault("checksum", {})[checksum_type] = _checksum_value(
            checksum_type, checksum_value,
        )


def _validate_platform_artifacts(platform: str, artifacts: list[dict[str, Any]]) -> None:
    if platform != "android":
        return
    if (
        len(artifacts) != 1
        or artifacts[0].get("kind") != "apk"
        or not str(artifacts[0].get("name", "")).lower().endswith(".apk")
        or len(artifacts[0].get("urls", [])) != 1
    ):
        fail(422, "validation_error", "Android 版本必须包含一个 APK 和一条 URL")


def build_manual_record(root: Path, domain_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    vendor, game_id, platform, _ = domain_info(root, domain_id)
    version = payload.get("version")
    raw_artifacts = payload.get("artifacts")
    if not _safe_component(version) or not isinstance(raw_artifacts, list) or not raw_artifacts:
        fail(422, "validation_error", "version 和 artifacts 为必填项")
    attributes = payload.get("attributes") if isinstance(payload.get("attributes"), Mapping) else {}
    channel = payload.get("channel") or attributes.get("channel") or "official"
    identity = {
        "vendor": vendor,
        "game_id": game_id,
        "domain_id": domain_id,
        "platform": platform,
        "channel": channel,
        "version": version,
    }
    artifacts = [_normalize_artifact(item, identity) for item in raw_artifacts]
    _apply_primary_compatibility(payload, artifacts)
    for item in artifacts:
        item["artifact_id"] = artifact_id(item, record_identity=identity)
    _validate_platform_artifacts(platform, artifacts)

    if "file_created_at_override" in payload:
        file_time = payload.get("file_created_at_override")
    elif "observed_at" in payload:
        file_time = payload.get("observed_at")
    else:
        file_time = attributes.get("file_created_at")
    version_code = payload["version_code"] if "version_code" in payload else attributes.get("version_code")
    record = {
        "schema_version": 2,
        **identity,
        "version_code": version_code,
        "file_time": file_time,
        "artifacts": artifacts,
        "references": [],
        "is_visible": True,
        "provenance": {"source_kind": "manual", "source_name": "admin"},
    }
    try:
        validate_v2_record(record)
    except ValueError:
        fail(422, "validation_error", "版本记录校验失败")
    return record


def admin_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    result = public_summary(dict(record))
    result["attributes"] = {
        "channel": record.get("channel"),
        "version_code": record.get("version_code"),
    }
    result["is_visible"] = record.get("is_visible", True) is not False
    return result


def editable_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for artifact in record.get("artifacts", []):
        checksum = artifact.get("checksum") if isinstance(artifact.get("checksum"), Mapping) else {}
        checksum_type = next((kind for kind in CHECKSUM_KINDS if kind in checksum), None)
        attributes = {
            key: copy.deepcopy(artifact[key])
            for key in ARTIFACT_ATTRIBUTE_FIELDS
            if key in artifact
        }
        for kind, value in checksum.items():
            if kind in CHECKSUM_KINDS:
                attributes[kind] = value
        urls = [
            {
                "id": stable_url_id(artifact["artifact_id"], index, candidate["url"]),
                "url": candidate["url"],
                "priority": candidate["priority"],
                "source_kind": candidate["source_kind"],
            }
            for index, candidate in enumerate(artifact.get("urls", []))
        ]
        artifacts.append(
            {
                "kind": artifact["kind"],
                "name": artifact["name"],
                "part": artifact.get("part", 1),
                "size": artifact.get("size", 0),
                "checksum_type": checksum_type,
                "checksum_value": checksum.get(checksum_type) if checksum_type else None,
                "attributes": attributes,
                "urls": urls,
            }
        )
    return {
        "version": record["version"],
        "client_version": record["version"],
        "observed_at": record.get("file_time"),
        "file_created_at_override": record.get("file_time"),
        "file_path": artifacts[0]["name"] if artifacts else "",
        "unpacked_size": sum(
            artifact.get("decompressed_size", 0)
            for artifact in record.get("artifacts", [])
            if isinstance(artifact.get("decompressed_size", 0), int)
        ),
        "files_checksum_type": None,
        "files_checksum_value": None,
        "attributes": {
            "channel": record.get("channel"),
            "version_code": record.get("version_code"),
        },
        "is_visible": record.get("is_visible", True) is not False,
        "artifacts": artifacts,
    }


def version_summaries(root: Path, domain_id: str) -> list[dict[str, Any]]:
    return [admin_summary(record) for record in scan_domain(root, domain_id)[4]]


def catalog_projection(root: Path) -> dict[str, Any]:
    games = [
        {
            "id": game_id,
            "name": name,
            "sub_name": sub_name,
            "platform": "multi",
            "icon_source": f"builtin:{game_id}",
            "version_count": 0,
            "latest_version": None,
            "is_enabled": True,
            "sort_order": order,
        }
        for order, (game_id, name, sub_name) in enumerate(GAME_CATALOG)
    ]
    game_by_id = {game["id"]: game for game in games}
    game_platforms: dict[str, set[str]] = {game["id"]: set() for game in games}
    domains: list[dict[str, Any]] = []
    for game_order, (game_id, _, _) in enumerate(GAME_CATALOG):
        domain_ids = [
            f"{game_id}-{'android' if platform == 'android' else 'pc'}"
            for disk, platform in (("android", "android"), ("pc", "windows"))
            if any(
                _exists_or_link(Path(root) / vendor / game_id / disk)
                for vendor in VENDORS
            )
        ]
        for vendor in VENDORS:
            for domain_id in nondefault_pc_domains(vendor, game_id):
                directory = Path(root) / vendor / game_id / "pc" / "domains" / domain_id
                if _exists_or_link(directory):
                    domain_ids.append(domain_id)
        for domain_order, domain_id in enumerate(domain_ids):
            vendor, _, _, directory, records = scan_domain(root, domain_id)
            platform = records[0]["platform"] if records else domain_info(root, domain_id)[2]
            disk = _disk_platform(platform)
            domain = DomainData(vendor, game_id, disk, platform, domain_id, directory, tuple(records))
            if records:
                projection = _domain_projection(domain, game_order * 10 + domain_order)
            else:
                projection = {
                    "id": domain_id,
                    "game_id": game_id,
                    "kind": "apk" if platform == "android" else "packages",
                    "platform": platform,
                    "capabilities": [],
                    "capability_contract": {},
                    "adapter": "android" if platform == "android" else "generic",
                    "version_count": 0,
                    "latest_version": None,
                    "source_current_version": None,
                    "catalog_version_count": 0,
                    "is_enabled": True,
                    "sort_order": game_order * 10 + domain_order,
                }
            projection["is_enabled"] = True
            domains.append(projection)
            game = game_by_id[game_id]
            game["version_count"] += len(records)
            game_platforms[game_id].add(platform)
            versions = [record["version"] for record in records]
            if game["latest_version"] is not None:
                versions.append(game["latest_version"])
            game["latest_version"] = max(versions, key=_version_key) if versions else None
    for game in games:
        platforms = game_platforms[game["id"]]
        if len(platforms) == 1:
            game["platform"] = next(iter(platforms))
    return {"games": games, "domains": domains}


def create_version(root: Path, domain_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    with ADMIN_PROBE_LOCK:
        record = build_manual_record(root, domain_id, payload)
        write_v2_record(record, root)
        rebuild_index(
            root, record["vendor"], record["game_id"], record["platform"], record["domain_id"],
        )
        return record


def update_version(
    root: Path, domain_id: str, version: str, payload: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    with ADMIN_PROBE_LOCK:
        old, _, _ = read_record(root, domain_id, version)
        updated = copy.deepcopy(old)
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), Mapping) else {}
        if payload.get("channel") is not None or attributes.get("channel") is not None:
            updated["channel"] = payload.get("channel") or attributes.get("channel")
        if "version_code" in payload:
            updated["version_code"] = payload["version_code"]
        elif "version_code" in attributes:
            updated["version_code"] = attributes["version_code"]
        if "file_created_at_override" in payload:
            updated["file_time"] = payload["file_created_at_override"]
        elif "observed_at" in payload:
            updated["file_time"] = payload["observed_at"]

        if payload.get("artifacts") is not None:
            identity = _record_identity(updated)
            updated["artifacts"] = [
                _normalize_artifact(
                    raw,
                    identity,
                    old=old["artifacts"][index] if index < len(old.get("artifacts", [])) else None,
                )
                for index, raw in enumerate(payload["artifacts"])
            ]
        _apply_primary_compatibility(payload, updated["artifacts"])
        identity = _record_identity(updated)
        for artifact in updated["artifacts"]:
            artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
        _validate_platform_artifacts(updated["platform"], updated["artifacts"])
        try:
            validate_v2_record(updated)
        except ValueError:
            fail(422, "validation_error", "版本记录校验失败")
        changed = updated != old
        if changed:
            write_v2_record(updated, root, overwrite=True)
            rebuild_index(
                root, updated["vendor"], updated["game_id"], updated["platform"], updated["domain_id"],
            )
        return updated, changed


def set_visibility(root: Path, domain_id: str, version: str, visible: bool) -> bool:
    with ADMIN_PROBE_LOCK:
        record, _, _ = read_record(root, domain_id, version)
        updated = copy.deepcopy(record)
        updated["is_visible"] = visible
        if updated != record:
            write_v2_record(updated, root, overwrite=True)
            rebuild_index(
                root, updated["vendor"], updated["game_id"], updated["platform"], updated["domain_id"],
            )
        return visible


def delete_version(root: Path, domain_id: str, version: str) -> None:
    with ADMIN_PROBE_LOCK:
        with DATA_LOCK, data_file_lock(root):
            _, path, identity = read_record(root, domain_id, version)
            path.unlink()
        rebuild_index(root, identity[0], identity[1], identity[2], domain_id)


__all__ = [
    "admin_summary",
    "build_manual_record",
    "catalog_projection",
    "create_version",
    "delete_version",
    "domain_info",
    "editable_projection",
    "read_record",
    "scan_domain",
    "set_visibility",
    "update_version",
    "version_summaries",
]
