"""Canonical helpers for protected version administration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from backend import catalog_admin
from backend.admin_probe import ADMIN_PROBE_LOCK, stable_url_id, valid_probe_url
from backend.catalog_registry import GAME_IDS, VENDORS
from backend.domain_registry import is_nondefault_pc_domain
from backend.fs_safety import domain_directory, is_ordinary, is_safe_component
from backend.indexes import version_key
from backend.inventory_loader import MAX_RECORD_BYTES, fail
from backend.public_projection import version_summary as public_summary
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import record_index_transaction, write_v2_record


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


def _exists_or_link(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def domain_info(
    root: Path,
    domain_id: str,
    *,
    config: Mapping[str, Mapping[str, dict[str, Any]]] | None = None,
) -> tuple[str, str, str, Path]:
    if not is_safe_component(domain_id):
        fail(404, "domain_not_found", "归档域不存在")

    root = Path(root)
    if not is_ordinary(root, directory=True):
        fail(500, "unsafe_data_path", "数据目录不安全")
    loaded_config = catalog_admin.load_config(root) if config is None else config
    configured_domains = loaded_config["domains"]
    matches: list[tuple[str, str, str, Path]] = []
    valid_game_ids = set(GAME_IDS) | set(loaded_config["games"])
    if "-" in domain_id:
        game_id, suffix = domain_id.rsplit("-", 1)
        if game_id in valid_game_ids and suffix in {"android", "pc"}:
            platform = "android" if suffix == "android" else "windows"
            for vendor in VENDORS:
                candidate = domain_directory(root, vendor, game_id, platform, domain_id)
                if _exists_or_link(candidate):
                    matches.append((vendor, game_id, platform, candidate))
            if not matches:
                configured = configured_domains.get(domain_id)
                if configured is not None:
                    matches.append((
                        configured["vendor"],
                        configured["game_id"],
                        configured["platform"],
                        catalog_admin.domain_directory(root, configured),
                    ))
    if not matches:
        for vendor in VENDORS:
            for game_id in valid_game_ids:
                configured = catalog_admin.is_configured_nondefault_pc_domain(
                    root, vendor, game_id, domain_id, config=loaded_config,
                )
                if not (is_nondefault_pc_domain(vendor, game_id, domain_id) or configured):
                    continue
                domain = configured_domains.get(domain_id)
                candidate = (
                    catalog_admin.domain_directory(root, domain)
                    if configured and domain is not None
                    else domain_directory(root, vendor, game_id, "windows", domain_id)
                )
                if _exists_or_link(candidate):
                    matches.append((vendor, game_id, "windows", candidate))
                elif configured and domain is not None:
                    matches.append((vendor, game_id, "windows", candidate))
    if not matches:
        fail(404, "domain_not_found", "归档域不存在")
    if len(matches) != 1:
        fail(500, "unsafe_data_path", "归档域路径不唯一")

    vendor, game_id, platform, directory = matches[0]
    current = root
    for part in directory.relative_to(root).parts:
        current = current / part
        if not is_ordinary(current, directory=True):
            fail(500, "unsafe_data_path", "数据目录不安全")
    return vendor, game_id, platform, directory


def _read_record(path: Path) -> dict[str, Any]:
    if not is_ordinary(path):
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
    if not is_safe_component(version):
        fail(404, "version_not_found", "版本不存在")
    vendor, game_id, platform, directory = domain_info(root, domain_id)
    path = directory / f"{version}.json"
    if not _exists_or_link(path):
        fail(404, "version_not_found", "版本不存在")
    if not is_ordinary(path):
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
    root: Path,
    domain_id: str,
    *,
    config: Mapping[str, Mapping[str, dict[str, Any]]] | None = None,
) -> tuple[str, str, str, Path, list[dict[str, Any]]]:
    vendor, game_id, platform, directory = domain_info(root, domain_id, config=config)
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
        if path.name == "index.json":
            continue
        if not is_ordinary(path):
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
    records.sort(key=lambda item: version_key(item["version"]), reverse=True)
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


def _normalize_edited_artifacts(
    raw_artifacts: list[Mapping[str, Any]], old: Mapping[str, Any], identity: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Resolve ownership using the old identity, never the submitted list position."""
    old_by_id = {item["artifact_id"]: item for item in old["artifacts"]}
    used: set[str] = set()
    result = []
    for raw in raw_artifacts:
        previous_id = raw.get("artifact_id")
        if previous_id is not None:
            if not isinstance(previous_id, str) or previous_id not in old_by_id:
                fail(422, "validation_error", "artifact_id 不属于当前版本")
        else:
            # Older clients omit artifact_id. Normalize only to compute the full
            # canonical identity; URL, checksum and list order are not identities.
            previous_id = _normalize_artifact(raw, _record_identity(old))["artifact_id"]
        previous = old_by_id.get(previous_id)
        if previous is not None:
            if previous_id in used:
                fail(422, "validation_error", "artifact_id 重复")
            used.add(previous_id)
        result.append(_normalize_artifact(raw, identity, old=previous))
    return result


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
    if not is_safe_component(version) or not isinstance(raw_artifacts, list) or not raw_artifacts:
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
                "artifact_id": artifact["artifact_id"],
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


def create_version(root: Path, domain_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    with ADMIN_PROBE_LOCK, DATA_LOCK, data_file_lock(root):
        record = build_manual_record(root, domain_id, payload)
        with record_index_transaction(record, root):
            write_v2_record(record, root)
        return record


def update_version(
    root: Path, domain_id: str, version: str, payload: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    with ADMIN_PROBE_LOCK, DATA_LOCK, data_file_lock(root):
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
            updated["artifacts"] = _normalize_edited_artifacts(payload["artifacts"], old, identity)
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
        with record_index_transaction(updated, root):
            if changed:
                write_v2_record(updated, root, overwrite=True)
        return updated, changed


def set_visibility(root: Path, domain_id: str, version: str, visible: bool) -> bool:
    with ADMIN_PROBE_LOCK, DATA_LOCK, data_file_lock(root):
        record, _, _ = read_record(root, domain_id, version)
        updated = copy.deepcopy(record)
        updated["is_visible"] = visible
        with record_index_transaction(updated, root):
            if updated != record:
                write_v2_record(updated, root, overwrite=True)
        return visible


def delete_version(root: Path, domain_id: str, version: str) -> None:
    with ADMIN_PROBE_LOCK, DATA_LOCK, data_file_lock(root):
        record, path, _ = read_record(root, domain_id, version)
        with record_index_transaction(record, root):
            path.unlink()


from backend.admin_catalog_service import (  # noqa: E402
    catalog_config,
    catalog_projection,
    create_domain,
    create_game,
    delete_domain,
    delete_game,
    update_domain,
    update_game,
)

_catalog_config = catalog_config

__all__ = [
    "admin_summary",
    "build_manual_record",
    "catalog_config",
    "catalog_projection",
    "create_domain",
    "create_game",
    "create_version",
    "delete_domain",
    "delete_game",
    "delete_version",
    "domain_info",
    "editable_projection",
    "read_record",
    "scan_domain",
    "set_visibility",
    "update_domain",
    "update_game",
    "update_version",
    "version_summaries",
]
