"""Read-only FastAPI contract over canonical schema-v2 data.

Canonical records are validated at the disk boundary, then projected through
explicit public mappers.  Local paths, schema internals and source recipes are
never returned directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import catalog_admin
from backend.catalog_admin import CatalogConfigError
from backend.indexes import IndexReadError, _entry as index_entry, read_index
from backend.domain_registry import nondefault_pc_domains
from backend.manifest_readers import (
    HttpUpstream,
    ManifestBadRequest,
    ManifestCorrupt,
    ManifestError,
    ManifestNotFound,
    ManifestTimeout,
    ManifestUpstream,
    OFFICIAL_SOPHON_HOSTS,
    chunk_content,
    chunk_file_detail,
    local_file_detail,
    local_files,
    list_chunk_files,
    list_local_files,
    strict_relative_posix,
)
from backend.mihoyo_package_files import (
    PackageFilesBadRequest,
    PackageFilesCacheError,
    PackageFilesNotFound,
    PackageFilesTimeout,
    PackageFilesUnsupported,
    PackageFilesUpstream,
    list_files as list_mihoyo_package_files,
    file_detail as mihoyo_package_file_detail,
    package_files as mihoyo_package_files,
)
from backend.schema_v2 import SchemaValidationError, artifact_identity_key, validate_v2_record


MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
VENDORS = ("mihoyo", "hypergryph", "kuro", "perfectworld")
PLATFORMS = (("android", "android"), ("pc", "windows"))
ARTIFACT_KINDS = frozenset({"apk", "package", "patch", "resource"})
TREE_KINDS = ARTIFACT_KINDS | {"all", "file"}
AVAILABILITY_STATES = frozenset({"available", "unavailable", "unknown"})
COMPARE_SCOPES = frozenset({"artifacts", "files"})
LOCAL_OFFICIAL_HOSTS = {
    "kuro": frozenset(
        {
            "pcdownload-aliyun.aki-game.com",
            "pcdownload-huoshan.aki-game.com",
            "pcdownload-qcloud.aki-game.com",
        }
    ),
    "perfectworld": frozenset({"yhcdn1.wmupd.com", "nsywl-client-dev1.wmupd.com", "htcdn1.wmupd.com"}),
}

GAME_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("hk4e", "原神", "Genshin Impact"),
    ("hkrpg", "崩坏：星穹铁道", "Honkai: Star Rail"),
    ("nap", "绝区零", "Zenless Zone Zero"),
    ("bh3", "崩坏3", "Honkai Impact 3rd"),
    ("bh2", "崩坏学园2", "Houkai Gakuen 2"),
    ("arknights", "明日方舟", "Arknights"),
    ("endfield", "明日方舟：终末地", "Arknights: Endfield"),
    ("wuwa", "鸣潮", "Wuthering Waves"),
    ("pns", "战双帕弥什", "Punishing: Gray Raven"),
    ("nte", "异环", "Neverness to Everness"),
    ("tof", "幻塔", "Tower of Fantasy"),
    ("p5x", "女神异闻录：夜幕魅影", "Persona 5: The Phantom X"),
)
GAME_IDS = frozenset(item[0] for item in GAME_CATALOG)


class ApiFault(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def fail(status: int, code: str, message: str, details: Any = None) -> None:
    raise ApiFault(status, code, message, details)


def _ordinary(path: Path, *, directory: bool) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    return expected and not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ApiFault(500, "unsafe_data_path", "数据路径无法检查") from error


def _version_key(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value))
    return numbers or (0,)


def _stable_id(*parts: object) -> int:
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:12], 16)


def _safe_component(value: str, *, not_found: bool = False) -> str:
    if not isinstance(value, str) or SAFE_COMPONENT.fullmatch(value) is None:
        if not_found:
            fail(404, "not_found", "资源不存在")
        fail(400, "bad_path", "路径参数无效")
    return value


def _cursor(value: str | None) -> int:
    if value is None:
        return 0
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        fail(400, "bad_cursor", "cursor 无效")
    return int(value)


def _paginate(items: list[Any], limit: int, cursor: str | None) -> tuple[list[Any], str | None]:
    offset = _cursor(cursor)
    return items[offset : offset + limit], str(offset + limit) if offset + limit < len(items) else None


def _safe_public_url(value: Any, *, allow_query: bool = True) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        return None
    return value


def _public_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        key: value[key]
        for key in ("source_kind", "source_name", "source_repo", "source_commit", "imported_at")
        if isinstance(value.get(key), str)
    }
    source_url = _safe_public_url(value.get("source_url"), allow_query=False)
    if source_url:
        result["source_url"] = source_url
    return result


@dataclass(frozen=True)
class DomainData:
    vendor: str
    game_id: str
    disk_platform: str
    platform: str
    domain_id: str
    root: Path
    records: tuple[dict[str, Any], ...]


class ApiContract:
    def __init__(self, data_root: Path, upstream: Any | None = None, state_root: Path | None = None) -> None:
        self.data_root = Path(data_root)
        self.upstream = upstream or HttpUpstream()
        self.state_root = (
            Path(state_root)
            if state_root is not None
            else Path(os.environ.get("GMI_STATE_ROOT") or Path(__file__).resolve().parents[1] / ".cache")
        )

    def _catalog_games(self) -> list[dict[str, Any]]:
        try:
            return catalog_admin.game_catalog(self.data_root, GAME_CATALOG)
        except CatalogConfigError as error:
            raise ApiFault(500, "corrupt_catalog_config", "目录配置损坏") from error

    def _game_ids(self) -> tuple[str, ...]:
        return tuple(game["id"] for game in self._catalog_games())

    def _catalog_domains(self) -> dict[str, dict[str, Any]]:
        try:
            return catalog_admin.configured_domains(self.data_root)
        except CatalogConfigError as error:
            raise ApiFault(500, "corrupt_catalog_config", "目录配置损坏") from error

    def _read_json(self, path: Path, limit: int, code: str) -> dict[str, Any]:
        if not _ordinary(path, directory=False):
            fail(500, code, "归档数据损坏")
        try:
            if path.stat().st_size > limit:
                fail(500, code, "归档数据超过大小限制")
            value = json.loads(path.read_text(encoding="utf-8"))
        except ApiFault:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ApiFault(500, code, "归档数据损坏") from error
        if not isinstance(value, dict):
            fail(500, code, "归档数据损坏")
        return value

    def _safe_target(self, base: Path, relative: str) -> Path:
        try:
            relative = strict_relative_posix(relative)
        except ManifestBadRequest as error:
            raise ApiFault(500, "corrupt_manifest", "Manifest 路径无效") from error
        current = base
        if not _ordinary(current, directory=True):
            fail(500, "corrupt_manifest", "Manifest 路径不安全")
        parts = relative.split("/")
        for index, part in enumerate(parts):
            current = current / part
            is_last = index == len(parts) - 1
            if not _ordinary(current, directory=not is_last):
                fail(500, "corrupt_manifest", "Manifest 路径不安全")
        try:
            if base.resolve() not in current.resolve().parents:
                fail(500, "corrupt_manifest", "Manifest 路径越界")
        except OSError as error:
            raise ApiFault(500, "corrupt_manifest", "Manifest 路径损坏") from error
        return current

    def _registered_domain(
        self, vendor: str, game_id: str, domain_id: str, directory: Path,
    ) -> DomainData | None:
        """Load one explicitly registered non-default PC domain."""
        if not _present(directory):
            return None
        if not _ordinary(directory, directory=True):
            fail(500, "unsafe_data_path", "数据目录不安全")
        try:
            children = list(directory.iterdir())
        except OSError as error:
            raise ApiFault(500, "corrupt_data", "归档目录无法读取") from error
        records: list[dict[str, Any]] = []
        for path in children:
            if path.name == "index.json":
                continue
            if path.suffix != ".json" or not _ordinary(path, directory=False):
                fail(500, "unsafe_data_path", "归档文件不安全")
            record = self._read_json(path, MAX_RECORD_BYTES, "corrupt_record")
            try:
                validate_v2_record(record)
            except SchemaValidationError as error:
                raise ApiFault(500, "corrupt_record", "版本记录校验失败") from error
            expected = {
                "vendor": vendor,
                "game_id": game_id,
                "platform": "windows",
                "domain_id": domain_id,
                "version": path.stem,
            }
            if any(record.get(key) != value for key, value in expected.items()):
                fail(500, "record_identity_mismatch", "版本记录身份不匹配")
            if record.get("is_visible") is not False:
                records.append(record)
        index_path = directory / "index.json"
        if not _ordinary(index_path, directory=False):
            if _present(index_path):
                fail(500, "corrupt_index", "版本索引损坏")
            if records:
                fail(500, "missing_index", "版本索引缺失")
            return None
        try:
            if index_path.stat().st_size > MAX_INDEX_BYTES:
                fail(500, "corrupt_index", "版本索引超过大小限制")
            index = read_index(index_path)
        except ApiFault:
            raise
        except IndexReadError as error:
            raise ApiFault(500, "corrupt_index", "版本索引损坏") from error
        expected_index = {
            "vendor": vendor,
            "game_id": game_id,
            "platform": "windows",
            "domain_id": domain_id,
        }
        if index is None or set(index) != {*expected_index, "versions"}:
            fail(500, "corrupt_index", "版本索引字段不符合契约")
        if any(index.get(key) != value for key, value in expected_index.items()):
            fail(500, "index_mismatch", "版本索引身份不匹配")
        entries = index.get("versions")
        if not isinstance(entries, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("version"), str) for item in entries
        ):
            fail(500, "corrupt_index", "版本索引损坏")
        by_version = {record["version"]: record for record in records}
        indexed_versions = [item["version"] for item in entries]
        eligible_versions = [record["version"] for record in records if index_entry(record, "windows") is not None]
        if len(set(indexed_versions)) != len(indexed_versions) or sorted(indexed_versions) != sorted(eligible_versions):
            fail(500, "index_mismatch", "版本索引与记录不一致")
        for item in entries:
            record = by_version.get(item["version"])
            expected_entry = index_entry(record, "windows") if record is not None else None
            if expected_entry is None or set(item) != set(expected_entry) or any(
                item.get(key) != value for key, value in expected_entry.items()
            ):
                fail(500, "index_mismatch", "版本索引摘要不匹配")
        indexed = set(indexed_versions)
        ordered = [by_version[version] for version in indexed_versions]
        ordered.extend(sorted((record for record in records if record["version"] not in indexed), key=lambda item: _version_key(item["version"]), reverse=True))
        ordered.sort(key=lambda item: _version_key(item["version"]), reverse=True)
        if not ordered:
            return None
        return DomainData(vendor, game_id, "pc", "windows", domain_id, directory, tuple(ordered))

    def inventory(self) -> dict[str, DomainData]:
        if not _ordinary(self.data_root, directory=True):
            fail(500, "data_root_invalid", "数据目录不可用")
        result: dict[str, DomainData] = {}
        for vendor in VENDORS:
            vendor_root = self.data_root / vendor
            if not _present(vendor_root):
                continue
            if not _ordinary(vendor_root, directory=True):
                fail(500, "unsafe_data_path", "数据目录不安全")
            for game_id in self._game_ids():
                game_root = vendor_root / game_id
                if not _present(game_root):
                    continue
                if not _ordinary(game_root, directory=True):
                    fail(500, "unsafe_data_path", "数据目录不安全")
                for disk_platform, platform in PLATFORMS:
                    directory = game_root / disk_platform
                    if not _present(directory):
                        continue
                    if not _ordinary(directory, directory=True):
                        fail(500, "unsafe_data_path", "数据目录不安全")
                    domain_id = f"{game_id}-{'android' if platform == 'android' else 'pc'}"
                    if domain_id in result:
                        fail(500, "duplicate_domain", "归档域归属冲突")
                    index_path = directory / "index.json"
                    if not _ordinary(index_path, directory=False):
                        if _present(index_path):
                            fail(500, "corrupt_index", "版本索引损坏")
                        # Core intentionally removes an index when every
                        # canonical record is hidden.  Validate that state
                        # strictly, then omit the domain from the public
                        # inventory instead of treating it as corruption.
                        try:
                            children = list(directory.iterdir())
                        except OSError as error:
                            raise ApiFault(500, "corrupt_data", "归档目录无法读取") from error
                        has_visible_record = False
                        for path in children:
                            if _ordinary(path, directory=True):
                                continue
                            if path.suffix != ".json" or not _ordinary(path, directory=False):
                                fail(500, "unsafe_data_path", "归档文件不安全")
                            record = self._read_json(path, MAX_RECORD_BYTES, "corrupt_record")
                            try:
                                validate_v2_record(record)
                            except SchemaValidationError as error:
                                raise ApiFault(500, "corrupt_record", "版本记录校验失败") from error
                            expected_record = {
                                "vendor": vendor,
                                "game_id": game_id,
                                "platform": platform,
                                "domain_id": domain_id,
                                "version": path.stem,
                            }
                            if any(record.get(key) != expected for key, expected in expected_record.items()):
                                fail(500, "record_identity_mismatch", "版本记录身份不匹配")
                            has_visible_record = has_visible_record or record.get("is_visible") is not False
                        if has_visible_record:
                            fail(500, "missing_index", "版本索引缺失")
                        continue
                    try:
                        if index_path.stat().st_size > MAX_INDEX_BYTES:
                            fail(500, "corrupt_index", "版本索引超过大小限制")
                        index = read_index(index_path)
                    except ApiFault:
                        raise
                    except IndexReadError as error:
                        raise ApiFault(500, "corrupt_index", "版本索引损坏") from error
                    if index is None:
                        fail(500, "missing_index", "版本索引缺失")
                    expected_identity = {
                        "vendor": vendor,
                        "game_id": game_id,
                        "platform": platform,
                        "domain_id": domain_id,
                    }
                    if set(index) != {*expected_identity, "versions"}:
                        fail(500, "corrupt_index", "版本索引字段不符合契约")
                    if any(index.get(key) != expected for key, expected in expected_identity.items()):
                        fail(500, "index_mismatch", "版本索引身份不匹配")
                    records: list[dict[str, Any]] = []
                    visible_versions: list[str] = []
                    try:
                        children = list(directory.iterdir())
                    except OSError as error:
                        raise ApiFault(500, "corrupt_data", "归档目录无法读取") from error
                    for path in children:
                        if path.name == "index.json":
                            continue
                        if _ordinary(path, directory=True):
                            continue
                        if path.suffix != ".json" or not _ordinary(path, directory=False):
                            fail(500, "unsafe_data_path", "归档文件不安全")
                        record = self._read_json(path, MAX_RECORD_BYTES, "corrupt_record")
                        try:
                            validate_v2_record(record)
                        except SchemaValidationError as error:
                            raise ApiFault(500, "corrupt_record", "版本记录校验失败") from error
                        expected_record = {
                            "vendor": vendor,
                            "game_id": game_id,
                            "platform": platform,
                            "domain_id": domain_id,
                            "version": path.stem,
                        }
                        if any(record.get(key) != expected for key, expected in expected_record.items()):
                            fail(500, "record_identity_mismatch", "版本记录身份不匹配")
                        if record.get("is_visible") is not False:
                            visible_versions.append(record["version"])
                            records.append(record)
                    entries = index.get("versions")
                    if not isinstance(entries, list) or any(not isinstance(item, dict) or not isinstance(item.get("version"), str) for item in entries):
                        fail(500, "corrupt_index", "版本索引损坏")
                    indexed_versions = [item["version"] for item in entries]
                    eligible_versions = [record["version"] for record in records if index_entry(record, platform) is not None]
                    if len(set(indexed_versions)) != len(indexed_versions) or sorted(indexed_versions) != sorted(eligible_versions):
                        fail(500, "index_mismatch", "版本索引与记录不一致")
                    by_version = {record["version"]: record for record in records}
                    for item in entries:
                        if item["version"] not in by_version:
                            fail(500, "index_mismatch", "版本索引指向缺失记录")
                        expected_entry = index_entry(by_version[item["version"]], platform)
                        if expected_entry is None or set(item) != set(expected_entry) or any(item.get(key) != value for key, value in expected_entry.items()):
                            fail(500, "index_mismatch", "版本索引摘要不匹配")
                    unindexed_versions = [version for version in visible_versions if version not in set(indexed_versions)]
                    records = [by_version[version] for version in indexed_versions + sorted(unindexed_versions, key=_version_key, reverse=True)]
                    records.sort(key=lambda item: _version_key(item["version"]), reverse=True)
                    domain_config = self._catalog_domains().get(domain_id)
                    if domain_config is not None and domain_config.get("is_enabled") is False:
                        continue
                    if records:
                        result[domain_id] = DomainData(vendor, game_id, disk_platform, platform, domain_id, directory, tuple(records))
        for (vendor, game_id) in ((vendor, game_id) for vendor in VENDORS for game_id in self._game_ids()):
            domains_root = self.data_root / vendor / game_id / "pc" / "domains"
            if not _present(domains_root):
                continue
            if not _ordinary(domains_root, directory=True):
                fail(500, "unsafe_data_path", "数据目录不安全")
            for domain_id in (
                *nondefault_pc_domains(vendor, game_id),
                *catalog_admin.configured_nondefault_pc_domains(self.data_root, vendor, game_id),
            ):
                domain_config = self._catalog_domains().get(domain_id)
                if domain_config is not None and domain_config.get("is_enabled") is False:
                    continue
                domain = self._registered_domain(
                    vendor,
                    game_id,
                    domain_id,
                    domains_root / domain_id,
                )
                if domain is not None:
                    if domain_id in result:
                        fail(500, "duplicate_domain", "归档域归属冲突")
                    result[domain_id] = domain
        return result

    def domain(self, domain_id: str) -> DomainData:
        _safe_component(domain_id, not_found=True)
        domain = self.inventory().get(domain_id)
        if domain is None:
            fail(404, "domain_not_found", "归档域不存在")
        return domain

    def record(self, domain: DomainData, version: str) -> dict[str, Any]:
        _safe_component(version, not_found=True)
        for record in domain.records:
            if record["version"] == version:
                return record
        fail(404, "version_not_found", "版本不存在")

    def _load_document(self, domain: DomainData, record: dict[str, Any], relative: str) -> dict[str, Any]:
        path = self._safe_target(domain.root, relative)
        document = self._read_json(path, MAX_DOCUMENT_BYTES, "corrupt_manifest")
        expected = {
            "vendor": record["vendor"],
            "game_id": record["game_id"],
            "platform": record["platform"],
            "version": record["version"],
        }
        if document.get("schema_version") != 1 or any(document.get(key) != value for key, value in expected.items()):
            fail(500, "manifest_identity_mismatch", "Manifest 身份不匹配")
        if "domain_id" in document and document["domain_id"] != record["domain_id"]:
            fail(500, "manifest_identity_mismatch", "Manifest 身份不匹配")
        return document

    def chunk_document(self, domain: DomainData, record: dict[str, Any]) -> dict[str, Any]:
        references = [item for item in record.get("references", []) if isinstance(item, dict) and item.get("kind") == "chunk_manifest"]
        if not references:
            fail(404, "manifest_not_found", "Chunk Manifest 不存在")
        if len(references) != 1 or not isinstance(references[0].get("path"), str):
            fail(500, "corrupt_reference", "Chunk Manifest 引用损坏")
        reference = references[0]
        document = self._load_document(domain, record, reference["path"])
        if reference.get("build_id") != document.get("build_id") or not isinstance(document.get("manifests"), list):
            fail(500, "manifest_identity_mismatch", "Chunk Manifest 引用不匹配")
        reference_source = reference.get("source") if isinstance(reference.get("source"), dict) else {}
        document_source = document.get("provenance") if isinstance(document.get("provenance"), dict) else {}
        for field in ("source_kind", "source_name", "source_url"):
            if field in reference_source and reference_source[field] != document_source.get(field):
                fail(500, "manifest_identity_mismatch", "Chunk Manifest 来源不匹配")
        for entry in document["manifests"]:
            if not isinstance(entry, dict):
                fail(500, "corrupt_manifest", "Chunk Manifest 数据损坏")
            for recipe_name in ("manifest_download", "chunk_download"):
                recipe = entry.get(recipe_name)
                if not isinstance(recipe, dict):
                    fail(500, "corrupt_manifest", "Chunk Manifest recipe 损坏")
                prefix = _safe_public_url(recipe.get("url_prefix"), allow_query=False)
                if prefix is None or urlsplit(prefix).hostname not in OFFICIAL_SOPHON_HOSTS:
                    fail(500, "corrupt_manifest", "Chunk Manifest recipe 不安全")
        return document

    def package_document(
        self, domain: DomainData, record: dict[str, Any], identity: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        if not isinstance(identity, str) or SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        candidates = [
            item for item in record.get("artifacts", [])
            if isinstance(item, dict) and item.get("delivery_mode") == "file_manifest" and isinstance(item.get("manifest"), dict)
        ]
        selected: dict[str, Any] | None = None
        if identity == "game":
            selected = next(
                (item for item in candidates if item.get("component") == "game" and item.get("package_type") == "full"),
                next((item for item in candidates if item.get("component") == "game"), None),
            )
        else:
            selected = next(
                (item for item in candidates if identity in {item.get("artifact_id"), item.get("name"), str(_stable_id(item.get("artifact_id"))) }),
                None,
            )
        if selected is None:
            fail(404, "manifest_not_found", "文件 Manifest 不存在")
        relative = selected["manifest"].get("path")
        if not isinstance(relative, str):
            fail(500, "corrupt_manifest", "文件 Manifest 引用损坏")
        document = self._load_document(domain, record, relative)
        base_urls: list[str] = []
        raw_urls = selected["manifest"].get("base_urls")
        if raw_urls is None:
            raw_urls = []
        elif not isinstance(raw_urls, list):
            fail(500, "corrupt_manifest", "文件 Manifest base URL 损坏")
        for item in raw_urls:
            url = _safe_public_url(item.get("url") if isinstance(item, dict) else None, allow_query=False)
            allowed_hosts = LOCAL_OFFICIAL_HOSTS.get(record["vendor"], frozenset())
            if url is None or urlsplit(url).hostname not in allowed_hosts:
                fail(500, "corrupt_manifest", "文件 Manifest base URL 不安全")
            base_urls.append(url)
        return selected, document, base_urls


def _primary_artifact(record: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = [item for item in record.get("artifacts", []) if isinstance(item, dict)]
    if record["platform"] == "android":
        selected = next((item for item in artifacts if item.get("kind") == "apk"), None)
    else:
        selected = next(
            (item for item in artifacts if item.get("component") == "game" and item.get("package_type") == "full"),
            next((item for item in artifacts if item.get("component") == "game" and item.get("package_type") == "segment"), None),
        )
    if selected is None and record["platform"] == "windows" and any(
        isinstance(reference, dict) and reference.get("kind") == "chunk_manifest"
        for reference in record.get("references", [])
    ):
        return None
    if selected is None and record["platform"] == "windows" and artifacts and all(
        item.get("kind") == "resource" for item in artifacts
    ):
        return None
    if selected is None:
        fail(500, "record_projection_failed", "版本记录缺少可公开资源")
    return selected


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Live-probe evidence counts as verified for 20 hours after checked_at
# (the current probe rotation rule), then stays visible as stale.
PROBE_EVIDENCE_TTL = timedelta(hours=20)


def _probe_checked_at(current: dict[str, Any]) -> tuple[str, datetime] | None:
    # Only a UTC ISO-8601 timestamp, exactly the shape the probe adapters
    # persist, proves this current was written by a completed live probe.
    value = current.get("checked_at")
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return value, parsed


def _public_current(current: Any) -> dict[str, Any] | None:
    if not isinstance(current, dict):
        return None
    state = current.get("state") if current.get("state") in AVAILABILITY_STATES else "unknown"
    checked_at = current.get("checked_at") if isinstance(current.get("checked_at"), str) else None
    http_code = current.get("http_code") if isinstance(current.get("http_code"), int) and not isinstance(current.get("http_code"), bool) else None
    probe = _probe_checked_at(current)
    now = _utc_now()
    evidence_status = "unverified"
    source_kind = "canonical_current"
    expires_at = None
    # A future checked_at cannot prove a completed probe; treat it as unverified.
    if probe is not None and probe[1] <= now:
        evidence_status = "verified" if now - probe[1] < PROBE_EVIDENCE_TTL else "stale"
        source_kind = "live_probe"
        expires_at = (probe[1] + PROBE_EVIDENCE_TTL).isoformat().replace("+00:00", "Z")
    return {
        "state": state,
        "reason": f"HTTP {http_code}" if http_code is not None else "",
        "confidence": "low",
        "retained": False,
        "checked_at": checked_at,
        "source_kind": source_kind,
        "source_confidence": "low",
        "observed_at": checked_at,
        "expires_at": expires_at,
        "evidence_status": evidence_status,
    }


def _public_artifact(record: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    artifact_id = artifact["artifact_id"]
    checksum = artifact.get("checksum") if isinstance(artifact.get("checksum"), dict) else {}
    checksum_type = next((kind for kind in ("md5", "sha256", "crc64") if isinstance(checksum.get(kind), str)), None)
    attributes = {
        key: artifact[key]
        for key in ("component", "package_type", "delivery_mode", "language", "route_from", "route_to", "decompressed_size")
        if artifact.get(key) is not None and isinstance(artifact.get(key), (str, int, bool))
    }
    urls = []
    for index, candidate in enumerate(artifact.get("urls", [])):
        if not isinstance(candidate, dict):
            continue
        url = _safe_public_url(candidate.get("url"))
        if url is None:
            continue
        source_kind = candidate.get("source_kind") if isinstance(candidate.get("source_kind"), str) else "unknown"
        current = _public_current(candidate.get("current"))
        urls.append(
            {
                "id": _stable_id(artifact_id, index, url),
                "url": url,
                "priority": candidate.get("priority") if isinstance(candidate.get("priority"), int) else index,
                "source_kind": source_kind,
                **({"provider": candidate["provider"]} if isinstance(candidate.get("provider"), str) else {}),
                "evidence_status": current["evidence_status"] if current is not None else "unverified",
                "current": current,
            }
        )
    return {
        "id": _stable_id(artifact_id),
        "kind": artifact["kind"],
        "name": artifact["name"],
        "part": artifact.get("part") if isinstance(artifact.get("part"), int) else 1,
        "size": artifact.get("size") if isinstance(artifact.get("size"), int) else 0,
        "checksum_type": checksum_type,
        "checksum_value": checksum.get(checksum_type) if checksum_type else None,
        "attributes": attributes,
        "urls": urls,
    }


def _artifact_state(artifact: dict[str, Any]) -> str:
    states = []
    for url in artifact["urls"]:
        if not isinstance(url, dict) or not isinstance(url.get("current"), dict):
            continue
        current = url["current"]
        evidence_status = url.get("evidence_status") or current.get("evidence_status")
        if evidence_status not in {"verified", "stale", "unverified"}:
            current = _public_current(current)
            if current is None:
                continue
            evidence_status = current["evidence_status"]
        if evidence_status != "verified":
            continue
        state = current.get("state")
        if state in AVAILABILITY_STATES:
            states.append(state)
    if "available" in states:
        return "available"
    if states and all(state == "unavailable" for state in states):
        return "unavailable"
    return "unknown"


def _public_version(record: dict[str, Any]) -> dict[str, Any]:
    artifact = _primary_artifact(record)
    # Some audited PC history records contain only a canonical chunk-manifest
    # reference.  The legacy public VersionRecord shape still requires flat
    # package fields, so return explicit empty values instead of fabricating a
    # package URL or rejecting an otherwise valid version.
    if artifact is None:
        return {
            "vendor": record["vendor"],
            "game_id": record["game_id"],
            "platform": record["platform"],
            "channel": record["channel"],
            "version": record["version"],
            "version_code": None,
            "filename": "",
            "url": "",
            "size": 0,
            "checksum": {"etag": None, "crc64": None, "md5": None},
            "file_time": record.get("file_time") if isinstance(record.get("file_time"), str) else None,
            "status": {"http_code": None, "available": None, "last_checked_at": None},
        }
    candidate = next((item for item in artifact.get("urls", []) if isinstance(item, dict) and _safe_public_url(item.get("url"))), {})
    current = candidate.get("current") if isinstance(candidate, dict) and isinstance(candidate.get("current"), dict) else {}
    checksum = artifact.get("checksum") if isinstance(artifact.get("checksum"), dict) else {}
    state = current.get("state")
    return {
        "vendor": record["vendor"],
        "game_id": record["game_id"],
        "platform": record["platform"],
        "channel": record["channel"],
        "version": record["version"],
        "version_code": record.get("version_code") if isinstance(record.get("version_code"), int) and not isinstance(record.get("version_code"), bool) else None,
        "filename": artifact["name"],
        "url": candidate.get("url") if isinstance(candidate, dict) else "",
        "size": artifact.get("size") if isinstance(artifact.get("size"), int) else 0,
        "checksum": {
            "etag": current.get("etag") if isinstance(current.get("etag"), str) else None,
            "crc64": checksum.get("crc64") if isinstance(checksum.get("crc64"), str) else None,
            "md5": checksum.get("md5") if isinstance(checksum.get("md5"), str) else None,
        },
        "file_time": record.get("file_time") if isinstance(record.get("file_time"), str) else None,
        "status": {
            "http_code": current.get("http_code") if isinstance(current.get("http_code"), int) else None,
            "available": True if state == "available" else False if state == "unavailable" else None,
            "last_checked_at": current.get("checked_at") if isinstance(current.get("checked_at"), str) else None,
        },
    }


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    artifacts = [_public_artifact(record, item) for item in record.get("artifacts", []) if isinstance(item, dict)]
    has_chunk = any(
        isinstance(reference, dict) and reference.get("kind") == "chunk_manifest"
        for reference in record.get("references", [])
    )
    kinds: dict[str, dict[str, Any]] = {}
    states = {state: 0 for state in AVAILABILITY_STATES}
    for artifact in artifacts:
        state = _artifact_state(artifact)
        states[state] += 1
        bucket = kinds.setdefault(artifact["kind"], {"count": 0, "size": 0, "availability_states": {name: 0 for name in AVAILABILITY_STATES}})
        bucket["count"] += 1
        bucket["size"] += artifact["size"]
        bucket["availability_states"][state] += 1
    return {
        "version": record["version"],
        "current_revision_id": 1,
        "revision_count": 1,
        "observed_at": record.get("file_time") if isinstance(record.get("file_time"), str) else None,
        "source_released_at": None,
        "packed_size": sum(item["size"] for item in artifacts),
        "unpacked_size": sum(item["attributes"].get("decompressed_size", 0) for item in artifacts),
        "artifact_count": len(artifacts),
        "artifact_kinds": kinds,
        "availability_states": states,
        "attributes": {"has_chunk": True} if has_chunk else {},
        "provenance": _public_provenance(record.get("provenance")),
        "is_visible": True,
    }


def _domain_adapter(domain: DomainData) -> str:
    if domain.domain_id == "endfield-resources":
        return "endfield-resources"
    if domain.platform == "android":
        return "android"
    source_names = {
        source["source_name"]
        for record in domain.records
        for source in (
            [record.get("provenance")]
            + [item.get("source") for item in record.get("artifacts", []) if isinstance(item, dict)]
            + [item.get("source") for item in record.get("references", []) if isinstance(item, dict)]
        )
        if isinstance(source, dict) and isinstance(source.get("source_name"), str)
    }
    if any("Kuro GameStarter" in name for name in source_names):
        return "wuwa"
    if any("Perfect World PatcherSDK" in name for name in source_names):
        return "perfectworld_patcher"
    if any("HoYoPlay" in name or "Sophon" in name for name in source_names):
        return "hoyo"
    return "generic"


def _domain_projection(domain: DomainData, sort_order: int) -> dict[str, Any]:
    artifacts = [item for record in domain.records for item in record.get("artifacts", []) if isinstance(item, dict)]
    kinds = {item.get("kind") for item in artifacts}
    has_chunk = any(any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", [])) for record in domain.records)
    has_files = any(item.get("delivery_mode") == "file_manifest" for item in artifacts)
    capabilities: list[str] = []
    if "apk" in kinds:
        capabilities.append("apk")
    if any(item.get("kind") == "package" and item.get("delivery_mode") != "file_manifest" for item in artifacts):
        capabilities.append("packages")
    if "patch" in kinds:
        capabilities.append("patches")
    if "resource" in kinds:
        capabilities.append("resources")
    if has_chunk:
        capabilities.append("chunks")
    if has_chunk or has_files:
        capabilities.append("files")
    if kinds != {"resource"} and any(item.get("urls") for item in artifacts):
        capabilities.append("archive")
    if len(domain.records) > 1:
        capabilities.append("compare")
    providers = sorted(
        {
            candidate["provider"]
            for item in artifacts
            for candidate in item.get("urls", [])
            if isinstance(candidate, dict) and isinstance(candidate.get("provider"), str)
        }
    )
    checksums = sorted(
        {
            key for item in artifacts for key in (item.get("checksum") or {})
            if key in {"md5", "sha256", "crc64"}
        }
    )
    adapter = _domain_adapter(domain)
    return {
        "id": domain.domain_id,
        "game_id": domain.game_id,
        "kind": "apk" if domain.platform == "android" else "resources" if kinds == {"resource"} else "files" if has_files else "packages",
        "platform": domain.platform,
        "capabilities": capabilities,
        "capability_contract": {
            "version_fields": {"observed_at": "supported", "source_released_at": "unsupported"},
            "artifact_fields": {"size": "supported", "checksum": "supported", "availability": "supported"},
            "url_source_kinds": sorted({candidate.get("source_kind") for item in artifacts for candidate in item.get("urls", []) if isinstance(candidate, dict) and isinstance(candidate.get("source_kind"), str)}),
            "checksum_algorithms": checksums,
            "availability_source_kinds": [],
            "url_providers": providers,
            "features": {"compare": "supported" if len(domain.records) > 1 else "unsupported", "chunks": "supported" if has_chunk else "unsupported"},
            "actions": {"download": "conditional"},
            "live_probe": False,
        },
        "adapter": adapter,
        "version_count": len(domain.records),
        "latest_version": max((record["version"] for record in domain.records), key=_version_key),
        "source_current_version": None,
        "catalog_version_count": len(domain.records),
        "is_enabled": True,
        "sort_order": sort_order,
    }


def _compare_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    public = _public_artifact({}, artifact)
    return {key: public[key] for key in ("name", "part", "kind", "size", "checksum_type", "checksum_value", "attributes")}


def _compare_file(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["path"].rsplit("/", 1)[-1],
        "part": 1,
        "kind": "file",
        "size": item["size"],
        "checksum_type": "md5",
        "checksum_value": item["md5"],
        "attributes": {"path": item["path"]},
    }


def _identity(artifact: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    key = artifact_identity_key(
        artifact["name"], artifact["component"], part=artifact.get("part"), language=artifact.get("language"),
        route_from=artifact.get("route_from"), route_to=artifact.get("route_to"),
    )
    value = json.loads(key)
    if not isinstance(value, dict) or any(not isinstance(item, (str, int, bool, type(None))) for item in value.values()):
        fail(500, "identity_projection_failed", "资源身份无法公开")
    return key, value


def _manifest_error(error: Exception) -> ApiFault:
    if isinstance(error, (ManifestBadRequest, PackageFilesBadRequest)):
        return ApiFault(400, "bad_request", str(error))
    if isinstance(error, (ManifestNotFound, PackageFilesNotFound)):
        return ApiFault(404, "file_not_found", str(error))
    if isinstance(error, (ManifestCorrupt, PackageFilesCacheError)):
        return ApiFault(500, "corrupt_manifest", str(error))
    if isinstance(error, (ManifestTimeout, PackageFilesTimeout)):
        return ApiFault(504, "upstream_timeout", str(error))
    if isinstance(error, PackageFilesUnsupported):
        return ApiFault(422, "package_format_unsupported", str(error))
    if isinstance(error, (ManifestUpstream, PackageFilesUpstream)):
        return ApiFault(502, "upstream_error", str(error))
    return ApiFault(500, "internal_error", "服务器内部错误")


def _public_chunk_document(domain_id: str, document: dict[str, Any]) -> dict[str, Any]:
    manifests = []
    for entry in document["manifests"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("manifest"), dict):
            fail(500, "corrupt_manifest", "Chunk Manifest 数据损坏")
        manifest = entry["manifest"]
        public: dict[str, Any] = {
            "manifest_id": manifest.get("id"),
            "manifest": {key: manifest.get(key) for key in ("id", "checksum", "compressed_size", "uncompressed_size")},
            "component": entry.get("component"),
            "language": entry.get("language"),
            "matching_field": entry.get("matching_field"),
            "stats": {key: (entry.get("stats") or {}).get(key, 0) for key in ("compressed_size", "uncompressed_size", "file_count", "chunk_count")},
        }
        if isinstance(entry.get("category"), dict):
            public["category"] = {key: entry["category"].get(key) for key in ("id", "name")}
        if isinstance(entry.get("deduplicated_stats"), dict):
            public["deduplicated_stats"] = {key: entry["deduplicated_stats"].get(key, 0) for key in ("compressed_size", "uncompressed_size", "file_count", "chunk_count")}
        for field in ("manifest_download", "chunk_download"):
            recipe = entry.get(field)
            if isinstance(recipe, dict) and "password" not in recipe:
                prefix = _safe_public_url(recipe.get("url_prefix"), allow_query=False)
                suffix = recipe.get("url_suffix", "")
                sensitive_suffix = bool(re.search(r"(?i)(?:^|[?&])(token|password|passwd|secret|auth(?:_key)?|signature|sign|key)=", suffix))
                if prefix and urlsplit(prefix).hostname in OFFICIAL_SOPHON_HOSTS and isinstance(suffix, str) and (not suffix or suffix.startswith("?")) and not sensitive_suffix:
                    public[field] = {
                        "url_prefix": prefix,
                        "url_suffix": suffix,
                        "compression": recipe.get("compression", 0),
                        "encryption": recipe.get("encryption", 0),
                    }
        manifests.append(public)
    return {
        "vendor": document["vendor"],
        "game_id": document["game_id"],
        "platform": document["platform"],
        "domain_id": domain_id,
        "version": document["version"],
        "build_id": document["build_id"],
        **({"tag": document["tag"]} if isinstance(document.get("tag"), str) else {}),
        **({"diff_tags": document["diff_tags"]} if isinstance(document.get("diff_tags"), list) else {}),
        "manifests": manifests,
        "provenance": _public_provenance(document.get("provenance")),
    }


def _chunk_summary(domain_id: str, document: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    entries = [item for item in document["manifests"] if isinstance(item, dict)]
    stats = [item.get("deduplicated_stats") if isinstance(item.get("deduplicated_stats"), dict) else item.get("stats", {}) for item in entries]
    return {
        "version": document["version"],
        "path": f"/api/v1/domains/{domain_id}/versions/{document['version']}/chunk-manifests",
        "build_id": document["build_id"],
        "manifest_count": len(entries),
        "file_count": sum(item.get("file_count", 0) for item in stats),
        "chunk_count": sum(item.get("chunk_count", 0) for item in stats),
        "compressed_size": sum(item.get("compressed_size", 0) for item in stats),
        "uncompressed_size": sum(item.get("uncompressed_size", 0) for item in stats),
        "components": sorted({item.get("component") for item in entries if isinstance(item.get("component"), str)}),
        "languages": sorted({item.get("language") for item in entries if isinstance(item.get("language"), str)}),
        "imported_at": (_public_provenance(document.get("provenance")).get("imported_at") or record.get("file_time") or ""),
    }


def create_api_app(data_root: Path, upstream: Any | None = None, *, state_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Game Manifest Index API", version="0.1.0")
    app.state.contract = ApiContract(data_root, upstream, state_root)

    @app.exception_handler(ApiFault)
    async def api_fault_handler(_: Request, error: ApiFault) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message, "details": error.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"location": ".".join(str(part) for part in item.get("loc", ())), "type": item.get("type", "invalid")}
            for item in error.errors()
        ]
        is_admin = request.url.path.startswith("/api/v1/admin/")
        return JSONResponse(status_code=422 if is_admin else 400, content={"error": {"code": "validation_error" if is_admin else "bad_request", "message": "请求参数无效", "details": details}})

    @app.exception_handler(StarletteHTTPException)
    async def framework_error_handler(_: Request, error: StarletteHTTPException) -> JSONResponse:
        status = error.status_code
        return JSONResponse(status_code=status, content={"error": {"code": "not_found" if status == 404 else "http_error", "message": "资源不存在" if status == 404 else "请求失败", "details": None}})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "服务器内部错误", "details": None}})

    def service() -> ApiContract:
        return app.state.contract

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/games")
    def games() -> list[dict[str, Any]]:
        inventory = service().inventory()
        result = []
        for game in service()._catalog_games():
            if game.get("is_enabled") is False:
                continue
            game_id = game["id"]
            domains = [item for item in inventory.values() if item.game_id == game_id]
            versions = [record["version"] for domain in domains for record in domain.records]
            if domains:
                result.append({"id": game_id, "name": game["name"], "sub_name": game["sub_name"], "platform": "multi" if len(domains) > 1 else domains[0].platform, "icon_source": game["icon_source"], "version_count": len(versions), "latest_version": max(versions, key=_version_key), "is_enabled": True, "sort_order": game["sort_order"]})
        result.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
        return result

    @app.get("/api/v1/games/{game_id}/domains")
    def game_domains(game_id: str) -> list[dict[str, Any]]:
        game_by_id = {item["id"]: item for item in service()._catalog_games()}
        if game_id not in game_by_id or game_by_id[game_id].get("is_enabled") is False:
            fail(404, "game_not_found", "游戏不存在")
        inventory = service().inventory()
        domains = [item for item in inventory.values() if item.game_id == game_id]
        if not domains:
            fail(404, "game_not_found", "游戏不存在")
        domains.sort(key=lambda item: 0 if item.platform == "android" else 1)
        configured = service()._catalog_domains()
        result = []
        for index, domain in enumerate(domains):
            projection = _domain_projection(domain, game_by_id[game_id].get("sort_order", 0) * 10 + index)
            projection.update({
                key: value
                for key, value in configured.get(domain.domain_id, {}).items()
                if key not in {"vendor"}
            })
            if projection.get("is_enabled") is not False:
                result.append(projection)
        result.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
        return result

    @app.get("/api/v1/domains/{domain_id}/versions")
    def versions(domain_id: str) -> dict[str, Any]:
        return {"items": [_summary(record) for record in service().domain(domain_id).records]}

    @app.get("/api/v1/domains/{domain_id}/versions/{version}")
    def version_detail(domain_id: str, version: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        return _public_version(service().record(domain, version))

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/artifacts")
    def artifacts(
        domain_id: str, version: str, limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
        q: str | None = None, availability_state: str | None = None, kind: str | None = None,
    ) -> dict[str, Any]:
        _cursor(cursor)
        if kind is not None and kind not in ARTIFACT_KINDS:
            fail(400, "bad_kind", "kind 无效")
        if availability_state is not None and availability_state not in AVAILABILITY_STATES:
            fail(400, "bad_availability", "availability_state 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        items = [_public_artifact(record, item) for item in record["artifacts"]]
        if kind:
            items = [item for item in items if item["kind"] == kind]
        if availability_state:
            items = [item for item in items if _artifact_state(item) == availability_state]
        if q:
            needle = q.casefold()
            items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).casefold()]
        items.sort(key=lambda item: (item["kind"], item["name"].casefold(), item["part"], item["id"]))
        page, next_cursor = _paginate(items, limit, cursor)
        return {"items": page, "next_cursor": next_cursor}

    def file_compare_rows(
        domain: DomainData, before_record: dict[str, Any], after_record: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            try:
                _, before_document, before_base_urls = service().package_document(domain, before_record, "game")
                _, after_document, after_base_urls = service().package_document(domain, after_record, "game")
                before = {item["path"]: _compare_file(item) for item in local_files(before_document, before_base_urls)}
                after = {item["path"]: _compare_file(item) for item in local_files(after_document, after_base_urls)}
            except ApiFault as error:
                if error.status != 404 or domain.vendor != "mihoyo" or domain.platform != "windows":
                    raise
                before = {
                    item["path"]: _compare_file(item)
                    for item in mihoyo_package_files(
                        service().state_root, before_record, before_record["game_id"], before_record["version"],
                        "game", service().upstream,
                    )
                }
                after = {
                    item["path"]: _compare_file(item)
                    for item in mihoyo_package_files(
                        service().state_root, after_record, after_record["game_id"], after_record["version"],
                        "game", service().upstream,
                    )
                }
        except ManifestError as error:
            raise _manifest_error(error) from error
        rows = []
        for path in sorted(set(before) | set(after), key=lambda value: (value.casefold(), value)):
            old = before.get(path)
            new = after.get(path)
            row_change = "added" if old is None else "removed" if new is None else "changed" if old != new else None
            if row_change:
                rows.append({"change": row_change, "identity": {"path": path}, "before": old, "after": new})
        return rows

    @app.get("/api/v1/domains/{domain_id}/compare")
    def compare(
        domain_id: str, from_version: str, to_version: str, change: str = "all", kind: str | None = None,
        compare_scope: str = "artifacts", limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        _cursor(cursor)
        if change not in {"all", "added", "removed", "changed"}:
            fail(400, "bad_change", "change 无效")
        if compare_scope not in COMPARE_SCOPES:
            fail(400, "bad_compare_scope", "compare_scope 无效")
        if kind is not None and kind not in ARTIFACT_KINDS and not (compare_scope == "files" and kind == "file"):
            fail(400, "bad_kind", "kind 无效")
        domain = service().domain(domain_id)
        before_record = service().record(domain, from_version)
        after_record = service().record(domain, to_version)
        if compare_scope == "files":
            if kind is not None and kind != "file":
                fail(400, "bad_kind", "文件级对比只支持 kind=file")
            rows = file_compare_rows(domain, before_record, after_record)
            summary = {name: sum(row["change"] == name for row in rows) for name in ("added", "removed", "changed")}
            summary["size_delta"] = sum((row["after"] or {}).get("size", 0) - (row["before"] or {}).get("size", 0) for row in rows)
            filtered = rows if change == "all" else [row for row in rows if row["change"] == change]
            page, next_cursor = _paginate(filtered, limit, cursor)
            return {
                "from_version": from_version,
                "to_version": to_version,
                "compare_scope": compare_scope,
                "summary": summary,
                "items": page,
                "next_cursor": next_cursor,
            }
        before = {}
        after = {}
        identities: dict[str, dict[str, Any]] = {}
        for record, target in ((before_record, before), (after_record, after)):
            for artifact in record["artifacts"]:
                if kind is not None and artifact["kind"] != kind:
                    continue
                key, identity = _identity(artifact)
                target[key] = artifact
                identities[key] = identity
        rows = []
        for key in sorted(set(before) | set(after)):
            old = _compare_artifact(before[key]) if key in before else None
            new = _compare_artifact(after[key]) if key in after else None
            row_change = "added" if old is None else "removed" if new is None else "changed" if old != new else None
            if row_change:
                rows.append({"change": row_change, "identity": identities[key], "before": old, "after": new})
        summary = {
            name: sum(row["change"] == name for row in rows) for name in ("added", "removed", "changed")
        }
        summary["size_delta"] = sum((row["after"] or {}).get("size", 0) - (row["before"] or {}).get("size", 0) for row in rows)
        filtered = rows if change == "all" else [row for row in rows if row["change"] == change]
        page, next_cursor = _paginate(filtered, limit, cursor)
        return {"from_version": from_version, "to_version": to_version, "compare_scope": compare_scope, "summary": summary, "items": page, "next_cursor": next_cursor}

    @app.get("/api/v1/domains/{domain_id}/leads")
    def leads(domain_id: str) -> dict[str, list[Any]]:
        service().domain(domain_id)
        return {"items": []}

    @app.get("/api/v1/domains/{domain_id}/chunk-manifests")
    def chunk_collection(domain_id: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        items = []
        for record in domain.records:
            if any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", [])):
                items.append(_chunk_summary(domain_id, service().chunk_document(domain, record), record))
        if not items:
            fail(404, "manifest_not_found", "Chunk Manifest 不存在")
        return {"items": items}

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests")
    def chunk_manifest_detail(domain_id: str, version: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        return _public_chunk_document(domain_id, service().chunk_document(domain, record))

    def selected_source(domain_id: str, version: str, source: str, identity: str) -> tuple[str, DomainData, dict[str, Any], Any]:
        if source not in {"auto", "chunk", "package"}:
            fail(400, "bad_source", "source 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        has_chunk = any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", []))
        if source == "chunk":
            return "chunk", domain, record, service().chunk_document(domain, record)
        if source == "auto" and has_chunk:
            document = service().chunk_document(domain, record)
            manifests = document.get("manifests", [])
            matching = [
                item for item in manifests
                if isinstance(item, dict) and (
                    item.get("matching_field") == identity
                    or item.get("manifest_id") == identity
                    or (isinstance(item.get("manifest"), dict) and item["manifest"].get("id") == identity)
                )
            ]
            if len(matching) == 1:
                return "chunk", domain, record, document
        if domain.vendor == "mihoyo" and domain.platform == "windows" and any(
            isinstance(item, dict)
            and item.get("kind") == "package"
            and item.get("component") == "game"
            and item.get("package_type") in {"full", "segment"}
            and item.get("delivery_mode") == "archive"
            for item in record.get("artifacts", [])
        ):
            return "mihoyo_package", domain, record, None
        artifact, document, base_urls = service().package_document(domain, record, identity)
        return "package", domain, record, (artifact, document, base_urls)

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/files")
    def version_files(
        domain_id: str, version: str, source: str = "auto", identity: str = "game", path: str = "",
        q: str | None = None, limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            strict_relative_posix(path, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        _cursor(cursor)
        selected, domain, record, payload = selected_source(domain_id, version, source, identity)
        try:
            if selected == "chunk":
                return {"source": "chunk", **list_chunk_files(payload, identity, service().upstream, path, q, limit, cursor)}
            if selected == "mihoyo_package":
                return list_mihoyo_package_files(
                    service().state_root, record, record["game_id"], record["version"], identity,
                    path, q, limit, cursor, service().upstream,
                )
            artifact, document, base_urls = payload
            return {"source": "package", "fetch_mode": "checked_in_manifest", "identity": str(_stable_id(artifact["artifact_id"])), **list_local_files(document, base_urls, path, q, limit, cursor)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/file")
    def version_file(domain_id: str, version: str, path: str, source: str = "auto", identity: str = "game") -> dict[str, Any]:
        try:
            strict_relative_posix(path)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        selected, domain, record, payload = selected_source(domain_id, version, source, identity)
        try:
            if selected == "chunk":
                return {"source": "chunk", **chunk_file_detail(payload, identity, service().upstream, path)}
            if selected == "mihoyo_package":
                return mihoyo_package_file_detail(
                    service().state_root, record, record["game_id"], record["version"], identity, path,
                    service().upstream,
                )
            artifact, document, base_urls = payload
            return {"source": "package", "fetch_mode": "checked_in_manifest", "identity": str(_stable_id(artifact["artifact_id"])), **local_file_detail(document, base_urls, path)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests/{identity}/files")
    def chunk_files_route(
        domain_id: str, version: str, identity: str, path: str = "", q: str | None = None,
        limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            strict_relative_posix(path, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        _cursor(cursor)
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        document = service().chunk_document(domain, record)
        try:
            return {"source": "chunk", **list_chunk_files(document, identity, service().upstream, path, q, limit, cursor)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests/{identity}/file")
    def chunk_file_route(domain_id: str, version: str, identity: str, path: str) -> dict[str, Any]:
        try:
            strict_relative_posix(path)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        document = service().chunk_document(domain, record)
        try:
            return {"source": "chunk", **chunk_file_detail(document, identity, service().upstream, path)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    def tree_artifact(source_id: str, item: dict[str, Any]) -> dict[str, Any]:
        url = _safe_public_url(item.get("download_url"))
        return {
            "id": _stable_id(source_id, item["path"]), "kind": "file", "name": item["path"], "part": 1,
            "size": item.get("size", 0), "checksum_type": "md5" if item.get("md5") else None,
            "checksum_value": item.get("md5"), "attributes": {},
            "urls": ([{"id": _stable_id(source_id, item["path"], url), "url": url, "priority": 0, "source_kind": "official", "evidence_status": "unverified", "current": None}] if url else []),
        }

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/artifact-tree")
    def artifact_tree(
        domain_id: str, version: str, kind: str = "file", prefix: str = "", limit: int = Query(100, ge=1, le=500),
        cursor: str | None = None, availability_state: str | None = None, q: str | None = None,
    ) -> dict[str, Any]:
        _cursor(cursor)
        if kind not in TREE_KINDS:
            fail(400, "bad_kind", "kind 无效")
        if availability_state is not None and availability_state not in AVAILABILITY_STATES:
            fail(400, "bad_availability", "availability_state 无效")
        try:
            prefix = strict_relative_posix(prefix, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "prefix 无效") from error
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        if kind == "file":
            if availability_state not in (None, "unknown"):
                _cursor(cursor)
                return {"prefix": prefix, "folders": [], "items": [], "next_cursor": None}
            try:
                artifact, document, base_urls = service().package_document(domain, record, "game")
                page = list_local_files(document, base_urls, prefix, q, limit, cursor)
            except ApiFault as error:
                if error.status == 404:
                    _cursor(cursor)
                    return {"prefix": prefix, "folders": [], "items": [], "next_cursor": None}
                raise
            except ManifestError as error:
                raise _manifest_error(error) from error
            folders = [
                {"name": item["name"], "path": item["path"], "artifact_count": item.get("file_count", 0), "total_size": item.get("size", 0)}
                for item in page["items"] if item.get("type") == "directory"
            ]
            items = [tree_artifact(artifact["artifact_id"], item) for item in page["items"] if item.get("type") == "file"]
            return {"prefix": prefix, "folders": folders, "items": items, "next_cursor": page["next_cursor"], "base_url": base_urls[0] if base_urls else None, "base_urls": base_urls}
        public = [_public_artifact(record, item) for item in record["artifacts"] if kind == "all" or item["kind"] == kind]
        if availability_state:
            public = [item for item in public if _artifact_state(item) == availability_state]
        if q:
            public = [item for item in public if q.casefold() in item["name"].casefold()]
        if kind == "resource":
            folder_stats: dict[str, dict[str, Any]] = {}
            for item in public:
                relative = item["name"] if not prefix else item["name"][len(prefix) + 1 :] if item["name"].startswith(prefix + "/") else ""
                if not relative or "/" not in relative:
                    continue
                segment = relative.split("/", 1)[0]
                path = f"{prefix}/{segment}" if prefix else segment
                folder = folder_stats.setdefault(path, {"name": segment, "path": path, "artifact_count": 0, "total_size": 0})
                folder["artifact_count"] += 1
                folder["total_size"] += item["size"]
            direct = [item for item in public if (not prefix and "/" not in item["name"]) or (prefix and item["name"].startswith(prefix + "/") and "/" not in item["name"][len(prefix) + 1 :])]
            direct.sort(key=lambda item: (item["name"].casefold(), item["id"]))
            combined = sorted(folder_stats.values(), key=lambda item: item["name"].casefold()) + direct
            page, next_cursor = _paginate(combined, limit, cursor)
            return {
                "prefix": prefix,
                "folders": [item for item in page if "artifact_count" in item],
                "items": [item for item in page if "artifact_count" not in item],
                "next_cursor": next_cursor,
            }
        direct = [item for item in public if (not prefix and "/" not in item["name"]) or (prefix and item["name"].startswith(prefix + "/") and "/" not in item["name"][len(prefix) + 1 :])]
        direct.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        page, next_cursor = _paginate(direct, limit, cursor)
        return {"prefix": prefix, "folders": [], "items": page, "next_cursor": next_cursor}

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-content")
    def chunk_content_route(domain_id: str, version: str, identity: str, name: str) -> Response:
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        if re.fullmatch(r"[^/\\\x00-\x20\x7f]+", name) is None:
            fail(400, "bad_name", "chunk name 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        document = service().chunk_document(domain, record)
        try:
            body, headers = chunk_content(document, identity, name, service().upstream)
        except ManifestError as error:
            raise _manifest_error(error) from error
        output_headers = {"Content-Length": str(len(body))}
        for key in ("content-type", "etag"):
            if isinstance(headers.get(key), str):
                output_headers[key.title()] = headers[key]
        return Response(body, status_code=200, headers=output_headers, media_type=None)

    return app


__all__ = ["ApiContract", "ApiFault", "GAME_CATALOG", "create_api_app"]
