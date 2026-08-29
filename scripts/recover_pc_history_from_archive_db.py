"""Recover provable PC history from a legacy archive SQLite database.

The database is opened read-only.  This is an explicitly offline historical
import: it never performs discovery, probing, or network access.  The default
mode only builds and validates a report.  ``--apply`` stages the same output,
adds only missing records, and rebuilds the affected PC indexes.

The old database stores a normalized relational projection, not schema-v2
records.  Only immutable version/artifact/url facts are copied.  Legacy probe
observations, interpretations, and mutable current pointers are intentionally
discarded.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from typing import Any

# Allow direct invocation from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.indexes import _rebuild_locked, index_path
from backend.schema_v2 import SchemaValidationError, artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import v2_record_path


class RecoveryError(ValueError):
    """The selected database projection cannot be converted safely."""


def rebuild_index(root: Path, vendor: str, game_id: str, platform: str, domain_id: str | None = None) -> Path:
    """Compatibility hook for the locked recovery-local index rebuild."""

    return _rebuild_locked(root, vendor, game_id, platform, domain_id)


VENDOR_BY_GAME = {
    "arknights": "hypergryph",
    "bh3": "mihoyo",
    "endfield": "hypergryph",
    "hk4e": "mihoyo",
    "hkrpg": "mihoyo",
    "nap": "mihoyo",
    "nte": "perfectworld",
    "p5x": "perfectworld",
    "tof": "perfectworld",
    "wuwa": "kuro",
}
# Endfield resources are a registered secondary PC domain.  Keep this list
# explicit instead of treating every archive domain as importable: the
# domain-aware storage layer gives this one domain its isolated path.
SUPPORTED_DOMAINS = frozenset(f"{game}-pc" for game in VENDOR_BY_GAME) | frozenset({"endfield-resources"})
HEX_MD5 = re.compile(r"^[0-9a-fA-F]{32}$")

# The source is an explicitly approved historical snapshot.  Keep this
# allowlist narrow: a source-root without this exact commit must never turn
# the recovery command into a general Git importer.
NTE_LEGACY_COMMIT = "8609a814dd8eebfde66a32fd464ed4d1bc8db6a2"
NTE_LEGACY_TREE = "b59b2cd6c8867f63189170547ef2977902b2b497"
NTE_LEGACY_RECORD_PATH = "data/perfectworld/nte/pc/1.3.12.json"
NTE_LEGACY_MANIFEST_PATH = "data/perfectworld/nte/pc/manifests/1.3.12.json"
NTE_LEGACY_RECORD_BLOB = "743993f478bdb7cd0a358080a3e75e6d28a7e2c3"
NTE_LEGACY_MANIFEST_BLOB = "05ed224c32f98cd59d5ad27e8586bd7e664a008e"
NTE_LEGACY_RECORD_BYTES = 4188
NTE_LEGACY_MANIFEST_BYTES = 160530
NTE_LEGACY_CONFIG_BYTES = 3584
NTE_LEGACY_FILE_COUNT = 73
NTE_LEGACY_PATCH_COUNT = 390
NTE_LEGACY_FILE_SIZE = 85475171295
NTE_LEGACY_HOST = "yhcdn1.wmupd.com"
NTE_LEGACY_SOURCE_URL = "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/config.xml"
GIT_TIMEOUT_SECONDS = 15


def _json(value: Any, field: str, *, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        result = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"{field} is not valid JSON") from error
    return result


def _text(value: Any, field: str, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise RecoveryError(f"{field} must be a non-empty string")
    return value


def _nonnegative(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RecoveryError(f"{field} must be a non-negative integer")
    return value


def _safe_manifest_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or ":" in value
    ):
        raise RecoveryError("manifest path is unsafe")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise RecoveryError("manifest path is unsafe")
    return value


def _compact_provenance(
    game_id: str,
    domain_id: str,
    version: str,
    revision_attributes: Mapping[str, Any],
    capture_source_url: Any,
) -> dict[str, str]:
    """Map legacy source labels without claiming the database is official."""

    nested = revision_attributes.get("provenance")
    nested = nested if isinstance(nested, Mapping) else {}
    source_kind = nested.get("source_kind") or revision_attributes.get("source_kind")
    if source_kind == "hoyofiles-split-archive":
        result: dict[str, str] = {
            "source_kind": "third_party_history",
            "source_name": "HoyoFiles/Amarea",
        }
        source_url = nested.get("source_url")
        if isinstance(source_url, str) and source_url.strip():
            result["source_url"] = source_url
        return result

    if domain_id == "endfield-resources":
        name = "Game-Manifest-Index legacy Endfield resources archive"
    elif source_kind in {"legacy_patchersdk_catalog_list", "official_reslist"}:
        name = "Game-Manifest-Index legacy PatcherSDK archive"
    elif source_kind == "legacy_endfield_launcher_aggregate":
        name = "Game-Manifest-Index legacy Endfield archive"
    elif game_id == "arknights":
        name = "Game-Manifest-Index legacy Arknights archive"
    elif game_id == "wuwa":
        name = "Game-Manifest-Index legacy WuWa archive"
    elif game_id == "nte":
        name = "Game-Manifest-Index legacy NTE archive"
    else:
        name = "Game-Manifest-Index legacy PC archive"
    result = {
        "source_kind": "legacy_migration",
        "source_name": name,
        "source_repo": "Game-Manifest-Index",
    }
    # Do not persist a machine-local file:// path.  The archive database is
    # already identified by source_repo/source_name.
    if isinstance(capture_source_url, str) and capture_source_url.startswith(("http://", "https://")):
        result["source_url"] = capture_source_url
    return result


def _url_candidates(
    db: sqlite3.Connection,
    artifact_row_id: int,
    attributes: Mapping[str, Any],
    *,
    strict: bool = False,
) -> list[dict[str, Any]]:
    providers = attributes.get("url_providers")
    providers = providers if isinstance(providers, Mapping) else {}
    result: list[dict[str, Any]] = []
    rows = db.execute(
        "SELECT url, priority, source_kind FROM artifact_urls "
        "WHERE artifact_id = ? ORDER BY priority, id",
        (artifact_row_id,),
    ).fetchall()
    for index, row in enumerate(rows):
        url = row[0]
        if not isinstance(url, str) or not url.strip():
            raise RecoveryError(f"artifact {artifact_row_id} has an invalid URL")
        original_url = url
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RecoveryError(f"artifact {artifact_row_id} has a non-HTTP URL")
        if strict:
            try:
                port = parsed.port
            except ValueError as error:
                raise RecoveryError(f"artifact {artifact_row_id} resource URL host is invalid") from error
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or port is not None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise RecoveryError(f"artifact {artifact_row_id} resource URL is unsafe")
        # Endfield's archive rows contain short-lived auth_key signatures.
        # They are credentials rather than durable historical facts; retain
        # the official path and remove only that query parameter.
        if (parsed.hostname or "").casefold() == "beyond.hycdn.cn" and parsed.query:
            # Keep every non-auth query byte intact.  Re-encoding the query
            # could change signed values or otherwise mutate a historical URL.
            query_parts = []
            for part in parsed.query.split("&"):
                key = unquote_plus(part.split("=", 1)[0])
                if key.casefold() != "auth_key":
                    query_parts.append(part)
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(query_parts), parsed.fragment))
        if strict:
            if isinstance(row[1], bool) or not isinstance(row[1], int) or row[1] < 0:
                raise RecoveryError(f"artifact {artifact_row_id} resource URL priority is invalid")
            if not isinstance(row[2], str) or not row[2].strip():
                raise RecoveryError(f"artifact {artifact_row_id} resource URL source_kind is invalid")
            priority = row[1]
            source_kind = row[2]
            # A provider is the actual URL authority.  Do not trust optional
            # legacy attribute maps to relabel a resource candidate.
            provider = parsed.hostname
        else:
            priority = row[1] if isinstance(row[1], int) and row[1] >= 0 else index
            source_kind = row[2] if isinstance(row[2], str) and row[2].strip() else "historical"
            provider = providers.get(original_url) or providers.get(url)
            if not isinstance(provider, str) or not provider.strip():
                provider = parsed.hostname or "historical"
        result.append({
            "url": url,
            "provider": provider,
            "source_kind": source_kind,
            "priority": priority,
        })
    return result


def _checksum(checksum_type: Any, checksum_value: Any, field: str) -> dict[str, str] | None:
    if checksum_type is None and checksum_value is None:
        return None
    if not isinstance(checksum_type, str) or checksum_type.casefold() not in {"md5", "sha256", "crc64"}:
        raise RecoveryError(f"{field} has an unsupported checksum type")
    if not isinstance(checksum_value, str) or not checksum_value.strip():
        raise RecoveryError(f"{field} has an incomplete checksum")
    return {checksum_type.casefold(): checksum_value.lower()}


def _artifact_source(provenance: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value for key, value in provenance.items()
        if key in {"source_kind", "source_name", "source_url", "source_repo", "source_commit"}
    }


def _ordinary_artifact(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    record_identity: Mapping[str, str],
    provenance: Mapping[str, str],
    game_id: str,
) -> dict[str, Any] | None:
    kind = row["kind"]
    if kind == "chunk":
        return None
    if kind == "manifest":
        # Perfect World manifests are folded into one file_manifest package
        # below; the old manifest row is not itself a downloadable artifact.
        return None
    attributes = _json(row["attributes_json"], f"artifact {row['id']}", default={})
    if not isinstance(attributes, Mapping):
        raise RecoveryError(f"artifact {row['id']} attributes must be an object")
    name = _text(row["name"], f"artifact {row['id']}.name")
    size = _nonnegative(row["size"], f"artifact {row['id']}.size")
    urls = _url_candidates(db, row["id"], attributes)
    if not urls:
        raise RecoveryError(f"artifact {row['id']} has no URL candidates")
    component = attributes.get("component", "game")
    if component == "optional":
        # Older HoYo rows used ``optional`` for resource/chunk slots.
        component = "other"
    if component not in {"game", "voice", "launcher", "other"}:
        raise RecoveryError(f"artifact {row['id']} has an unsupported component")
    old_package_type = attributes.get("package_type")
    package_type = {
        "optional_component": "optional",
        "differential_optional_component": "differential",
    }.get(old_package_type, old_package_type)
    if package_type is None:
        package_type = "differential" if kind == "patch" else "full"
    if package_type not in {"full", "segment", "optional", "differential"}:
        raise RecoveryError(f"artifact {row['id']} has an unsupported package type")
    result: dict[str, Any] = {
        "kind": "patch" if kind == "patch" else "package",
        "component": component,
        "package_type": package_type,
        "delivery_mode": "archive",
        "name": name,
        "size": size,
        "urls": urls,
        "source": _artifact_source(provenance),
    }
    checksum = _checksum(row["checksum_type"], row["checksum_value"], f"artifact {row['id']}")
    if checksum:
        result["checksum"] = checksum
    if kind == "package" and re.search(r"\.\d{3}$", name):
        result["package_type"] = "segment"
        result["part"] = attributes.get("route_part", row["part"])
        if result["part"] is None:
            raise RecoveryError(f"artifact {row['id']} segment has no part")
    if kind == "patch":
        route_from = attributes.get("route_from")
        route_to = attributes.get("route_to")
        if not isinstance(route_from, str) or not route_from.strip() or not isinstance(route_to, str) or not route_to.strip() or route_from == route_to:
            raise RecoveryError(f"artifact {row['id']} patch route is incomplete")
        result.update(route_from=route_from, route_to=route_to)
    language = attributes.get("language")
    if language is not None:
        if component != "voice" or not isinstance(language, str) or not language.strip():
            raise RecoveryError(f"artifact {row['id']} has an invalid language")
        result["language"] = language
    if game_id == "endfield" and kind == "package":
        result["package_type"] = "segment"
        result["part"] = row["part"]
    return result


def _resource_artifact(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    record_identity: Mapping[str, str],
    provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Convert one Endfield resource using the strict resource contract.

    Resource artifacts intentionally have no package/delivery/manifest or
    legacy ``attributes`` fields.  The archive's resource-kind/type metadata
    is audit evidence only and is not part of the canonical record.
    """

    name = _safe_manifest_path(row["name"])
    size = _nonnegative(row["size"], f"artifact {row['id']}.size")
    if row["checksum_type"] != "md5":
        raise RecoveryError(f"artifact {row['id']} resource checksum type must be md5")
    md5 = row["checksum_value"]
    if not isinstance(md5, str) or HEX_MD5.fullmatch(md5) is None:
        raise RecoveryError(f"artifact {row['id']} resource md5 is invalid")
    urls = _url_candidates(db, row["id"], {}, strict=True)
    if len(urls) != 1:
        raise RecoveryError(f"artifact {row['id']} resource must have exactly one URL")
    result: dict[str, Any] = {
        "kind": "resource",
        "component": "resource",
        "name": name,
        "size": size,
        "checksum": {"md5": md5.lower()},
        "urls": urls,
        "source": _artifact_source(provenance),
    }
    return result


def _perfectworld_record(
    db: sqlite3.Connection,
    *,
    revision_id: int,
    record: dict[str, Any],
    provenance: Mapping[str, str],
) -> dict[str, Any]:
    rows = db.execute(
        "SELECT id, kind, name, part, size, checksum_type, checksum_value, attributes_json "
        "FROM artifacts WHERE revision_id = ? ORDER BY part, id",
        (revision_id,),
    ).fetchall()
    manifest = next((row for row in rows if row["kind"] == "manifest"), None)
    files = [row for row in rows if row["kind"] == "file"]
    patches = [row for row in rows if row["kind"] == "patch"]
    if manifest is None or not files:
        raise RecoveryError("Perfect World version has no manifest and file set")
    manifest_attributes = _json(manifest["attributes_json"], f"manifest {manifest['id']}", default={})
    if not isinstance(manifest_attributes, Mapping):
        raise RecoveryError("Perfect World manifest attributes are invalid")
    manifest_urls = _url_candidates(db, manifest["id"], manifest_attributes)
    if not manifest_urls:
        raise RecoveryError("Perfect World manifest has no URL")
    first_file_attributes = _json(files[0]["attributes_json"], f"artifact {files[0]['id']}", default={})
    first_file_urls = _url_candidates(db, files[0]["id"], first_file_attributes)
    if not first_file_urls:
        raise RecoveryError("Perfect World file has no URL")
    parsed_file_url = urlsplit(first_file_urls[0]["url"])
    path_parts = parsed_file_url.path.rstrip("/").split("/")
    if len(path_parts) < 2:
        raise RecoveryError("Perfect World file URL cannot establish a resource root")
    base_path = "/".join(path_parts[:-2]) + "/"
    base_url = parsed_file_url._replace(path=base_path, query="", fragment="").geturl()
    if not base_url.endswith("/"):
        base_url += "/"

    document: dict[str, Any] = {
        "schema_version": 1,
        "vendor": "perfectworld",
        "game_id": record["game_id"],
        "domain_id": record["domain_id"],
        "platform": "windows",
        "version": record["version"],
        "files": [],
        "patch_objects": [],
        "config": {"version": record["version"], "base_version": ""},
        "provenance": dict(provenance),
    }
    for row in files:
        attributes = _json(row["attributes_json"], f"artifact {row['id']}", default={})
        if not isinstance(attributes, Mapping):
            raise RecoveryError(f"artifact {row['id']} attributes are invalid")
        dest = _safe_manifest_path(attributes.get("relative_path") or row["name"])
        md5 = row["checksum_value"]
        size = _nonnegative(row["size"], f"artifact {row['id']}.size")
        if not isinstance(md5, str) or not HEX_MD5.fullmatch(md5):
            raise RecoveryError(f"artifact {row['id']} file md5 is invalid")
        object_name = attributes.get("object")
        expected_object = f"{md5.lower()[0]}/{md5.lower()}.{size}"
        bare_object = f"{md5.lower()}.{size}"
        if object_name is not None and str(object_name).lower() not in {expected_object, bare_object}:
            raise RecoveryError(f"artifact {row['id']} file object identity is invalid")
        document["files"].append({"dest": dest, "size": size, "md5": md5.lower(), "object": expected_object})
    for row in patches:
        attributes = _json(row["attributes_json"], f"artifact {row['id']}", default={})
        if not isinstance(attributes, Mapping):
            raise RecoveryError(f"artifact {row['id']} attributes are invalid")
        old_object = _text(attributes.get("old_object"), f"artifact {row['id']}.old_object")
        new_object = _text(attributes.get("new_object"), f"artifact {row['id']}.new_object")
        patch_object = _text(attributes.get("patch_object"), f"artifact {row['id']}.patch_object")
        size = _nonnegative(row["size"], f"artifact {row['id']}.size")
        md5 = row["checksum_value"]
        if not isinstance(md5, str) or not HEX_MD5.fullmatch(md5) or not patch_object.lower().startswith(md5.lower() + "."):
            raise RecoveryError(f"artifact {row['id']} patch object identity is invalid")
        document["patch_objects"].append({
            "old_object": old_object, "new_object": new_object,
            "patch": patch_object, "object": f"{md5.lower()[0]}/{patch_object}", "size": size,
        })
    full_size = sum(item["size"] for item in document["files"])
    document["config"]["res_size"] = full_size
    document["config"]["reslist_response_size"] = _nonnegative(manifest["size"], f"manifest {manifest['id']}.size")
    artifact = {
        "kind": "package", "component": "game", "package_type": "full",
        "delivery_mode": "file_manifest", "name": "ResList.bin.zip", "size": full_size,
        "manifest": {
            "path": f"manifests/{record['version']}/files.json",
            "base_urls": [{"url": base_url, "provider": "perfectworld", "source_kind": "official", "priority": 0}],
        },
        "urls": manifest_urls,
        "source": _artifact_source(provenance),
    }
    identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    artifact["artifact_id"] = artifact_id(artifact, identity)
    record["artifacts"] = [artifact]
    return document


def _chunk_document(
    db: sqlite3.Connection,
    *,
    revision_id: int,
    record: Mapping[str, Any],
    provenance: Mapping[str, str],
) -> dict[str, Any] | None:
    rows = db.execute(
        "SELECT id, kind, name, size, attributes_json FROM artifacts "
        "WHERE revision_id = ? AND kind = 'chunk' ORDER BY part, id",
        (revision_id,),
    ).fetchall()
    if not rows:
        return None
    first_attributes = _json(rows[0]["attributes_json"], f"artifact {rows[0]['id']}", default={})
    if not isinstance(first_attributes, Mapping):
        raise RecoveryError("chunk attributes are invalid")
    build_id = first_attributes.get("build_id")
    if not isinstance(build_id, str) or not build_id.strip():
        raise RecoveryError("chunk build_id is missing")
    document: dict[str, Any] = {
        "schema_version": 1,
        "vendor": record["vendor"], "game_id": record["game_id"],
        "domain_id": record["domain_id"], "platform": "windows", "version": record["version"],
        "tag": record["version"], "build_id": build_id, "diff_tags": [], "manifests": [],
        "provenance": dict(provenance),
    }
    for row in rows:
        attributes = _json(row["attributes_json"], f"artifact {row['id']}", default={})
        if not isinstance(attributes, Mapping):
            raise RecoveryError(f"artifact {row['id']} attributes are invalid")
        component = attributes.get("component")
        if component == "optional":
            component = "resource"
        if component not in {"game", "voice", "resource"}:
            raise RecoveryError(f"artifact {row['id']} chunk component is invalid")
        language = attributes.get("language")
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise RecoveryError(f"artifact {row['id']} chunk language is invalid")
        urls = _url_candidates(db, row["id"], attributes)
        if not urls:
            raise RecoveryError(f"artifact {row['id']} chunk has no URL")
        manifest_id = _text(attributes.get("manifest_id"), f"artifact {row['id']}.manifest_id")
        matching = _text(attributes.get("matching_field"), f"artifact {row['id']}.matching_field")
        parsed = urlsplit(urls[0]["url"])
        prefix = parsed._replace(path=parsed.path.rsplit("/", 1)[0], query="", fragment="").geturl().rstrip("/")
        chunk_prefix = prefix.replace("/manifests", "/chunks", 1)
        checksum = manifest_id.rsplit("_", 1)[-1]
        if not HEX_MD5.fullmatch(checksum):
            checksum = manifest_id
        compressed_size = _nonnegative(row["size"], f"artifact {row['id']}.size")
        uncompressed_size = attributes.get("uncompressed_size")
        if uncompressed_size is not None:
            uncompressed_size = _nonnegative(uncompressed_size, f"artifact {row['id']}.uncompressed_size")
        stats = {
            "compressed_size": compressed_size,
            "uncompressed_size": uncompressed_size if uncompressed_size is not None else compressed_size,
            "file_count": _nonnegative(attributes.get("file_count"), f"artifact {row['id']}.file_count") if attributes.get("file_count") is not None else 0,
            "chunk_count": _nonnegative(attributes.get("chunk_count"), f"artifact {row['id']}.chunk_count") if attributes.get("chunk_count") is not None else 0,
        }
        document["manifests"].append({
            "category": {"id": None, "name": attributes.get("category_name")},
            "manifest": {"id": manifest_id, "checksum": checksum},
            "component": component, "language": language, "matching_field": matching,
            "stats": stats, "deduplicated_stats": dict(stats),
            "manifest_download": {"url_prefix": prefix, "url_suffix": "", "compression": 1, "encryption": 0},
            "chunk_download": {"url_prefix": chunk_prefix, "url_suffix": "", "compression": 1, "encryption": 0},
        })
    return document


def _record_from_db(db: sqlite3.Connection, row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any] | None]:
    game_id = row["game_id"]
    domain_id = row["domain_id"]
    version = _text(row["version"], "game_versions.version")
    vendor = VENDOR_BY_GAME[game_id]
    revision_attributes = _json(row["revision_attributes_json"], f"revision {row['revision_id']}", default={})
    if not isinstance(revision_attributes, Mapping):
        raise RecoveryError(f"revision {row['revision_id']} attributes are invalid")
    provenance = _compact_provenance(game_id, domain_id, version, revision_attributes, row["capture_source_url"])
    record: dict[str, Any] = {
        "schema_version": 2, "vendor": vendor, "game_id": game_id,
        "domain_id": domain_id, "platform": "windows", "channel": "official",
        "version": version, "version_code": None, "file_time": None,
        "artifacts": [], "references": [], "provenance": provenance,
        "is_visible": bool(row["is_visible"]),
    }
    identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    if domain_id == "endfield-resources":
        # This is a secondary domain with a deliberately different artifact
        # contract.  Every row in its selected revision must be a resource;
        # do not let the generic package conversion reinterpret it.
        artifacts = db.execute(
            "SELECT id, kind, name, part, size, checksum_type, checksum_value, attributes_json "
            "FROM artifacts WHERE revision_id = ? ORDER BY part, id",
            (row["revision_id"],),
        ).fetchall()
        if not artifacts:
            raise RecoveryError("Endfield resource revision has no artifacts")
        for artifact_row in artifacts:
            if artifact_row["kind"] != "resource":
                raise RecoveryError(
                    f"artifact {artifact_row['id']} Endfield resource kind is not resource"
                )
            converted = _resource_artifact(
                db, artifact_row, record_identity=identity, provenance=provenance,
            )
            converted["artifact_id"] = artifact_id(converted, identity)
            record["artifacts"].append(converted)
        document = None
    elif game_id in {"nte", "tof", "p5x"}:
        document = _perfectworld_record(db, revision_id=row["revision_id"], record=record, provenance=provenance)
    else:
        artifacts = db.execute(
            "SELECT id, kind, name, part, size, checksum_type, checksum_value, attributes_json "
            "FROM artifacts WHERE revision_id = ? ORDER BY part, id",
            (row["revision_id"],),
        ).fetchall()
        for artifact_row in artifacts:
            converted = _ordinary_artifact(
                db, artifact_row, record_identity=identity, provenance=provenance, game_id=game_id,
            )
            if converted is not None:
                converted["artifact_id"] = artifact_id(converted, identity)
                record["artifacts"].append(converted)
        document = None
    chunk_document = _chunk_document(
        db, revision_id=row["revision_id"], record=record, provenance=provenance,
    )
    if chunk_document is not None:
        relative = f"chunk-manifests/{version}.json"
        record["references"].append({
            "kind": "chunk_manifest", "path": relative,
            "build_id": chunk_document["build_id"], "source": _artifact_source(provenance),
        })
        document = chunk_document
    try:
        validate_v2_record(record)
    except SchemaValidationError as error:
        raise RecoveryError(str(error)) from error
    if not record["artifacts"] and not record["references"]:
        raise RecoveryError("version has no representable package, patch, or chunk data")
    return record, document


def _query_rows(db: sqlite3.Connection, domains: set[str] | None) -> list[sqlite3.Row]:
    db.row_factory = sqlite3.Row
    query = (
        "SELECT v.id AS version_id, v.domain_id, v.game_id, v.version, v.is_visible, "
        "v.current_revision_id AS revision_id, r.attributes_json AS revision_attributes_json, "
        "c.source_url AS capture_source_url "
        "FROM game_versions v JOIN version_revisions r ON r.id = v.current_revision_id "
        "LEFT JOIN capture_events c ON c.id = r.capture_event_id "
        "JOIN games g ON g.id = v.game_id JOIN archive_domains d ON d.id = v.domain_id "
        "WHERE lower(d.platform) IN ('pc', 'windows') AND v.current_revision_id IS NOT NULL "
        "ORDER BY v.domain_id, v.id"
    )
    rows = list(db.execute(query))
    if domains is None:
        return rows
    return [row for row in rows if row["domain_id"] in domains]


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialized_json(value), encoding="utf-8", newline="\n")


def _serialized_json(value: Mapping[str, Any]) -> str:
    """Return the exact deterministic representation used for published JSON."""

    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _git_output(source_root: Path, args: tuple[str, ...], *, binary: bool = False) -> bytes:
    """Run one bounded, read-only Git operation against ``source_root``.

    The command shape is deliberately fixed to ``git -C <root>`` plus the
    caller's allowlisted operation.  In particular, this helper never invokes
    a shell and never reads a path from the source checkout directly.
    """

    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RecoveryError(f"legacy Git operation failed: {' '.join(args)}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RecoveryError(f"legacy Git operation failed: {' '.join(args)}{(': ' + detail) if detail else ''}")
    return completed.stdout if binary else completed.stdout.strip()


def _safe_source_root(source_root: Path) -> Path:
    """Return an absolute source root after rejecting links/reparse points."""

    source_root = Path(os.path.abspath(os.fspath(source_root)))
    # Check the complete existing path, not only the final component.  A
    # junction/symlink in a parent would otherwise let ``git -C`` operate on a
    # checkout outside the explicitly selected source tree.
    current = source_root
    while True:
        try:
            info = os.lstat(current)
        except OSError as error:
            raise RecoveryError(f"legacy Git source root cannot be inspected: {source_root}") from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RecoveryError(f"legacy Git source root contains a symlink or reparse point: {current}")
        if current == current.parent:
            break
        current = current.parent
    try:
        info = os.lstat(source_root)
    except OSError as error:
        raise RecoveryError(f"legacy Git source root cannot be inspected: {source_root}") from error
    if not stat.S_ISDIR(info.st_mode):
        raise RecoveryError(f"legacy Git source root is not a safe directory: {source_root}")
    return source_root


def _git_id(value: bytes, field: str) -> str:
    result = value.decode("ascii", errors="strict")
    if not re.fullmatch(r"[0-9a-f]{40}", result):
        raise RecoveryError(f"legacy Git {field} is not a complete SHA-1")
    return result


def _git_tree_entry(source_root: Path, commit: str, path: str, expected_blob: str) -> None:
    """Validate the exact committed tree entry before reading its blob.

    ``rev-parse COMMIT:path`` resolves through tree entries and can therefore
    hide a mode such as ``120000`` (a committed symlink).  The recovery is
    allowlisted to two regular-file blobs, so inspect the tree mode and path as
    well as the object id.
    """

    raw = _git_output(source_root, ("ls-tree", "-z", "-l", commit, "--", path), binary=True)
    entries = raw.split(b"\0") if raw else []
    entries = [entry for entry in entries if entry]
    if len(entries) != 1:
        raise RecoveryError(f"legacy Git tree entry is missing or ambiguous for {path}")
    try:
        header, actual_path = entries[0].split(b"\t", 1)
        mode, object_type, blob, _size = header.split()
        actual_path = actual_path.decode("utf-8", errors="strict")
        mode = mode.decode("ascii", errors="strict")
        object_type = object_type.decode("ascii", errors="strict")
        blob = blob.decode("ascii", errors="strict")
    except (ValueError, UnicodeDecodeError) as error:
        raise RecoveryError(f"legacy Git tree entry is malformed for {path}") from error
    if actual_path != path or mode != "100644" or object_type != "blob" or blob != expected_blob:
        raise RecoveryError(f"legacy Git tree entry is not the approved regular blob for {path}")


def _legacy_url(value: Any, field: str, *, object_name: str | None = None, expected_path: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryError(f"legacy NTE {field} URL is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise RecoveryError(f"legacy NTE {field} URL host or scheme is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != NTE_LEGACY_HOST
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise RecoveryError(f"legacy NTE {field} URL host or scheme is invalid")
    if expected_path is None:
        expected_path = (
            "/clientRes/publish_PC/Version/Windows/config.xml"
            if object_name is None
            else f"/clientRes/publish_PC/Res/{object_name[0]}/{object_name}"
        )
    if parsed.path != expected_path:
        raise RecoveryError(f"legacy NTE {field} URL object identity is invalid")
    return value


def _legacy_url_entry(value: Any, field: str, *, object_name: str | None = None, expected_path: str | None = None) -> str:
    if not isinstance(value, Mapping):
        raise RecoveryError(f"legacy NTE {field} URL candidate is invalid")
    if value.get("provider") != NTE_LEGACY_HOST or value.get("source_kind") != "official":
        raise RecoveryError(f"legacy NTE {field} URL provenance is invalid")
    return _legacy_url(value.get("url"), field, object_name=object_name, expected_path=expected_path)


def _legacy_object_name(value: Any, field: str, *, md5: str | None = None) -> tuple[str, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}\.[0-9]+", value):
        raise RecoveryError(f"legacy NTE {field} object identity is invalid")
    digest, raw_size = value.rsplit(".", 1)
    size = int(raw_size)
    if md5 is not None and digest != md5:
        raise RecoveryError(f"legacy NTE {field} object identity is invalid")
    return value, size


def _legacy_source_provenance(source_commit: str) -> dict[str, str]:
    return {
        "source_kind": "legacy_migration",
        "source_name": "official launcher legacy Git",
        "source_url": NTE_LEGACY_SOURCE_URL,
        "source_repo": "Game-Manifest-Index",
        "source_commit": source_commit,
    }


def _read_nte_legacy_source(
    source_root: Path, source_commit: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read and convert the two approved NTE objects from a pinned commit."""

    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RecoveryError("legacy Git source commit must be a complete lowercase SHA-1")
    if source_commit != NTE_LEGACY_COMMIT:
        raise RecoveryError("legacy Git source commit is not approved")
    source_root = _safe_source_root(source_root)

    resolved_commit = _git_id(
        _git_output(source_root, ("rev-parse", "--verify", f"{source_commit}^{{commit}}")), "commit"
    )
    if resolved_commit != source_commit:
        raise RecoveryError("legacy Git commit resolution changed the approved commit")
    if _git_output(source_root, ("cat-file", "-t", resolved_commit)).decode("ascii", errors="strict") != "commit":
        raise RecoveryError("legacy Git commit object has the wrong type")
    tree = _git_id(_git_output(source_root, ("rev-parse", "--verify", f"{resolved_commit}^{{tree}}")), "tree")
    if tree != NTE_LEGACY_TREE:
        raise RecoveryError(f"legacy Git tree mismatch: expected {NTE_LEGACY_TREE}, got {tree}")
    if _git_output(source_root, ("cat-file", "-t", tree)).decode("ascii", errors="strict") != "tree":
        raise RecoveryError("legacy Git tree object has the wrong type")

    blob_ids: dict[str, str] = {}
    blob_bytes: dict[str, bytes] = {}
    expected_blobs = {
        NTE_LEGACY_RECORD_PATH: (NTE_LEGACY_RECORD_BLOB, NTE_LEGACY_RECORD_BYTES),
        NTE_LEGACY_MANIFEST_PATH: (NTE_LEGACY_MANIFEST_BLOB, NTE_LEGACY_MANIFEST_BYTES),
    }
    for path, (expected_blob, expected_size) in expected_blobs.items():
        _git_tree_entry(source_root, resolved_commit, path, expected_blob)
        blob = _git_id(_git_output(source_root, ("rev-parse", "--verify", f"{resolved_commit}:{path}")), "blob")
        if blob != expected_blob:
            raise RecoveryError(f"legacy Git blob mismatch for {path}: expected {expected_blob}, got {blob}")
        if _git_output(source_root, ("cat-file", "-t", blob)).decode("ascii", errors="strict") != "blob":
            raise RecoveryError(f"legacy Git object for {path} is not a blob")
        size_text = _git_output(source_root, ("cat-file", "-s", blob)).decode("ascii", errors="strict")
        if not size_text.isdigit() or int(size_text) != expected_size:
            raise RecoveryError(f"legacy Git blob size mismatch for {path}")
        content = _git_output(source_root, ("cat-file", "blob", blob), binary=True)
        if len(content) != expected_size:
            raise RecoveryError(f"legacy Git blob byte count mismatch for {path}")
        blob_ids[path] = blob
        blob_bytes[path] = content

    try:
        legacy_record = json.loads(blob_bytes[NTE_LEGACY_RECORD_PATH].decode("utf-8"))
        legacy_manifest = json.loads(blob_bytes[NTE_LEGACY_MANIFEST_PATH].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError("legacy NTE Git blobs are not valid UTF-8 JSON") from error
    if not isinstance(legacy_record, Mapping) or not isinstance(legacy_manifest, Mapping):
        raise RecoveryError("legacy NTE Git objects must be JSON objects")

    # Validate the legacy identity and the one official launcher/config URL.
    identity = {
        "vendor": "perfectworld", "game_id": "nte", "domain_id": "nte-pc",
        "platform": "windows", "channel": "official", "version": "1.3.12",
    }
    for key, expected in {**identity, "adapter": "perfectworld_patcher"}.items():
        if legacy_record.get(key) != expected:
            raise RecoveryError(f"legacy NTE record identity mismatch: {key}")
    legacy_provenance = legacy_record.get("provenance")
    if not isinstance(legacy_provenance, Mapping) or legacy_provenance.get("source_kind") != "official_launcher":
        raise RecoveryError("legacy NTE provenance is not official launcher history")
    if legacy_provenance.get("source_url") != NTE_LEGACY_SOURCE_URL:
        raise RecoveryError("legacy NTE provenance source URL is not the official launcher URL")
    artifacts = legacy_record.get("artifacts")
    if not isinstance(artifacts, list):
        raise RecoveryError("legacy NTE record artifacts are invalid")
    config_artifacts = [item for item in artifacts if isinstance(item, Mapping) and item.get("kind") == "manifest"]
    package_artifacts = [item for item in artifacts if isinstance(item, Mapping) and item.get("kind") == "package"]
    if len(config_artifacts) != 1 or len(package_artifacts) != 1 or len(artifacts) != 2:
        raise RecoveryError("legacy NTE record must contain one config and one package artifact")
    config_artifact = config_artifacts[0]
    package_artifact = package_artifacts[0]
    if config_artifact.get("name") != "config.xml" or config_artifact.get("size") != NTE_LEGACY_CONFIG_BYTES:
        raise RecoveryError("legacy NTE config artifact identity is invalid")
    config_urls = config_artifact.get("urls")
    if not isinstance(config_urls, list) or len(config_urls) != 1:
        raise RecoveryError("legacy NTE config artifact URL set is invalid")
    config_url = _legacy_url_entry(config_urls[0], "config")
    if package_artifact.get("name") != "ResList.bin.zip":
        raise RecoveryError("legacy NTE package identity is invalid")
    package_attrs = package_artifact.get("attributes")
    if not isinstance(package_attrs, Mapping):
        raise RecoveryError("legacy NTE package attributes are invalid")
    if package_attrs.get("component") != "game" or package_attrs.get("package_type") != "full" or package_attrs.get("delivery_mode") != "file_manifest":
        raise RecoveryError("legacy NTE package classification is invalid")
    if package_attrs.get("local_manifest") not in {NTE_LEGACY_MANIFEST_PATH, "perfectworld/nte/pc/manifests/1.3.12.json"}:
        raise RecoveryError("legacy NTE package manifest association is invalid")
    manifest_urls = package_attrs.get("manifest_urls")
    if not isinstance(manifest_urls, list) or len(manifest_urls) != 1:
        raise RecoveryError("legacy NTE package manifest URL set is invalid")
    package_url = manifest_urls[0]
    expected_package_url = "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/version/1.3.12/ResList.bin.zip"
    if package_url != expected_package_url:
        raise RecoveryError("legacy NTE package manifest URL is invalid")
    _legacy_url(
        package_url, "package",
        expected_path="/clientRes/publish_PC/Version/Windows/version/1.3.12/ResList.bin.zip",
    )
    package_record_urls = package_artifact.get("urls")
    if not isinstance(package_record_urls, list) or len(package_record_urls) != 1:
        raise RecoveryError("legacy NTE package URL set is invalid")
    package_record_url = _legacy_url_entry(
        package_record_urls[0], "package",
        expected_path="/clientRes/publish_PC/Version/Windows/version/1.3.12/ResList.bin.zip",
    )
    if package_record_url != package_url:
        raise RecoveryError("legacy NTE package URL candidates disagree")

    # The fixed counts and full size are part of the evidence contract.  Do
    # not use the mutable status/current fields from the legacy record.
    for key in ("decoded_file_count", "patch_object_count", "full_size", "config_res_size", "reslist_size"):
        value = package_attrs.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RecoveryError(f"legacy NTE package {key} is invalid")
    if package_attrs["decoded_file_count"] != NTE_LEGACY_FILE_COUNT or package_attrs["patch_object_count"] != NTE_LEGACY_PATCH_COUNT:
        raise RecoveryError("legacy NTE package counts do not match the approved snapshot")
    if package_artifact.get("size") != NTE_LEGACY_FILE_SIZE or package_attrs["full_size"] != NTE_LEGACY_FILE_SIZE:
        raise RecoveryError("legacy NTE package full size does not match the approved snapshot")
    flags = package_attrs.get("flags")
    if not isinstance(flags, Mapping) or flags.get("compressed") not in {"0", "1"} or flags.get("encrypt") not in {"0", "1"}:
        raise RecoveryError("legacy NTE package flags are invalid")
    if not isinstance(package_attrs.get("config_hash"), str) or not package_attrs["config_hash"].strip():
        raise RecoveryError("legacy NTE package config hash is invalid")
    if not isinstance(package_attrs.get("base_versions"), str):
        raise RecoveryError("legacy NTE package base_versions is invalid")

    if legacy_manifest.get("schema") != "perfectworld-patcher-files-v1" or legacy_manifest.get("version") != "1.3.12":
        raise RecoveryError("legacy NTE file manifest identity is invalid")
    files = legacy_manifest.get("files")
    patches = legacy_manifest.get("patch_objects")
    if not isinstance(files, list) or len(files) != NTE_LEGACY_FILE_COUNT or not isinstance(patches, list) or len(patches) != NTE_LEGACY_PATCH_COUNT:
        raise RecoveryError("legacy NTE file manifest counts are invalid")
    # These files are installed on Windows, where destination names are
    # case-insensitive.  Preserve the original spelling in output but reject
    # case-only collisions as duplicate destinations.
    seen_destinations: set[str] = set()
    seen_file_objects: set[str] = set()
    normalized_files: list[dict[str, Any]] = []
    for index, item in enumerate(files):
        if not isinstance(item, Mapping):
            raise RecoveryError(f"legacy NTE file {index} is invalid")
        dest = _safe_manifest_path(item.get("dest"))
        destination_key = dest.casefold()
        if destination_key in seen_destinations:
            raise RecoveryError("legacy NTE file destinations are duplicated")
        seen_destinations.add(destination_key)
        size = _nonnegative(item.get("size"), f"legacy NTE file {index}.size")
        md5 = item.get("md5")
        if not isinstance(md5, str) or not re.fullmatch(r"[0-9a-f]{32}", md5):
            raise RecoveryError(f"legacy NTE file {index} md5 is invalid")
        object_name, object_size = _legacy_object_name(f"{md5}.{size}", f"file {index}", md5=md5)
        if object_name in seen_file_objects or object_size != size:
            raise RecoveryError("legacy NTE file objects are duplicated or inconsistent")
        seen_file_objects.add(object_name)
        urls = item.get("urls")
        if not isinstance(urls, list) or len(urls) != 1:
            raise RecoveryError(f"legacy NTE file {index} URL set is invalid")
        _legacy_url(urls[0], f"file {index}", object_name=object_name)
        normalized_files.append({"dest": dest, "size": size, "md5": md5, "object": f"{md5[0]}/{object_name}"})
    if sum(item["size"] for item in normalized_files) != NTE_LEGACY_FILE_SIZE:
        raise RecoveryError("legacy NTE file sizes do not match the approved package size")

    seen_patches: set[str] = set()
    normalized_patches: list[dict[str, Any]] = []
    for index, item in enumerate(patches):
        if not isinstance(item, Mapping):
            raise RecoveryError(f"legacy NTE patch {index} is invalid")
        old_object = item.get("oldfile")
        new_object = item.get("newfile")
        patch_object = item.get("patch")
        if not isinstance(old_object, str) or not isinstance(new_object, str) or old_object == new_object:
            raise RecoveryError(f"legacy NTE patch {index} route is invalid")
        _legacy_object_name(old_object, f"patch {index}.oldfile")
        _legacy_object_name(new_object, f"patch {index}.newfile")
        patch_name, patch_size_from_name = _legacy_object_name(patch_object, f"patch {index}.patch")
        size = _nonnegative(item.get("size"), f"legacy NTE patch {index}.size")
        if patch_size_from_name != size or patch_name in seen_patches:
            raise RecoveryError("legacy NTE patch objects are duplicated or inconsistent")
        seen_patches.add(patch_name)
        if not isinstance(item.get("v"), str) or not item["v"].strip():
            raise RecoveryError(f"legacy NTE patch {index} version marker is invalid")
        _legacy_url(item.get("url"), f"patch {index}", object_name=patch_name)
        normalized_patches.append({
            "oldfile": old_object, "newfile": new_object, "patch": patch_name,
            "object": f"{patch_name[0]}/{patch_name}", "v": item["v"], "size": size,
        })

    source_metadata = {
        "source_commit": source_commit, "source_tree": tree,
        "blobs": {
            NTE_LEGACY_RECORD_PATH: {"object": blob_ids[NTE_LEGACY_RECORD_PATH], "type": "blob", "bytes": NTE_LEGACY_RECORD_BYTES},
            NTE_LEGACY_MANIFEST_PATH: {"object": blob_ids[NTE_LEGACY_MANIFEST_PATH], "type": "blob", "bytes": NTE_LEGACY_MANIFEST_BYTES},
        },
    }
    provenance = _legacy_source_provenance(source_commit)
    config: dict[str, Any] = {
        "version": "1.3.12", "res_size": package_attrs["config_res_size"],
        "hash": package_attrs["config_hash"], "compressed": flags["compressed"],
        "encrypt": flags["encrypt"], "base_version": package_attrs["base_versions"],
        "config_response_size": config_artifact["size"], "reslist_response_size": package_attrs["reslist_size"],
    }
    # Unknown package/config attributes are intentionally not copied.
    document: dict[str, Any] = {
        "schema_version": 1, "vendor": "perfectworld", "game_id": "nte",
        "domain_id": "nte-pc", "platform": "windows", "version": "1.3.12",
        "files": normalized_files, "patch_objects": normalized_patches,
        "config": config, "provenance": provenance,
    }
    artifact: dict[str, Any] = {
        "kind": "package", "component": "game", "package_type": "full",
        "delivery_mode": "file_manifest", "name": "ResList.bin.zip", "size": NTE_LEGACY_FILE_SIZE,
        "manifest": {
            "path": "manifests/1.3.12/files.json",
            "base_urls": [{"url": "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/", "provider": "perfectworld", "source_kind": "official", "priority": 0}],
        },
        "urls": [{"url": package_url, "provider": "perfectworld", "source_kind": "official", "priority": 0}],
        "source": _artifact_source(provenance),
    }
    record: dict[str, Any] = {
        **identity, "schema_version": 2, "version_code": None, "file_time": None,
        "artifacts": [artifact], "references": [], "provenance": provenance,
    }
    artifact["artifact_id"] = artifact_id(artifact, identity)
    try:
        validate_v2_record(record)
    except SchemaValidationError as error:
        raise RecoveryError(str(error)) from error
    return record, document, source_metadata


def _source_stats(db: sqlite3.Connection, revision_id: int) -> tuple[Counter[str], Counter[str]]:
    """Return source artifact-kind and URL-source-kind distributions."""

    artifact_kinds: Counter[str] = Counter(
        (row[0] if isinstance(row[0], str) and row[0].strip() else "unknown") for row in db.execute(
            "SELECT kind FROM artifacts WHERE revision_id = ? ORDER BY id", (revision_id,)
        )
    )
    url_source_kinds: Counter[str] = Counter(
        (row[0] if isinstance(row[0], str) and row[0].strip() else "historical")
        for row in db.execute(
            "SELECT u.source_kind FROM artifact_urls u "
            "JOIN artifacts a ON a.id = u.artifact_id "
            "WHERE a.revision_id = ? ORDER BY u.id",
            (revision_id,),
        )
    )
    return artifact_kinds, url_source_kinds


def _resource_audit(
    db: sqlite3.Connection,
    revision_id: int,
    revision_attributes: Mapping[str, Any],
) -> dict[str, Any]:
    """Summarize resource evidence for the human/machine audit report.

    ``revision_attributes`` is deliberately copied only into this report
    object.  The canonical record has no metadata/attributes slot, so these
    archive hints must never be smuggled into the v2 record.
    """

    rows = db.execute(
        "SELECT id, kind, checksum_type, checksum_value, attributes_json "
        "FROM artifacts WHERE revision_id = ? ORDER BY part, id",
        (revision_id,),
    ).fetchall()
    initial = 0
    main = 0
    for row in rows:
        attributes = _json(row["attributes_json"], f"artifact {row['id']}", default={})
        if isinstance(attributes, Mapping):
            resource_kind = attributes.get("resource_kind")
            if resource_kind == "initial":
                initial += 1
            elif resource_kind == "main":
                main += 1
    url_rows = db.execute(
        "SELECT u.source_kind FROM artifact_urls u "
        "JOIN artifacts a ON a.id = u.artifact_id "
        "WHERE a.revision_id = ? ORDER BY u.id",
        (revision_id,),
    ).fetchall()
    official = sum(1 for row in url_rows if row[0] == "official")
    mirror = sum(1 for row in url_rows if row[0] == "mirror")
    md5 = sum(
        1 for row in rows
        if row["checksum_type"] == "md5"
        and isinstance(row["checksum_value"], str)
        and HEX_MD5.fullmatch(row["checksum_value"]) is not None
    )
    metadata = {
        key: revision_attributes[key]
        for key in ("initial_file_count", "main_file_count", "resource_version")
        if key in revision_attributes
    }
    return {
        "revision": revision_id,
        "total": len(rows),
        "initial": initial,
        "main": main,
        "urls": {
            "total": len(url_rows),
            "official": official,
            "mirror": mirror,
            "md5": md5,
        },
        "metadata": metadata,
    }


def _read_existing_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read an existing target without ever treating it as writable input."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, None
    except OSError as error:
        return None, f"existing V5 record cannot be inspected: {error}"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        return None, "existing V5 record is not a regular file"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"existing V5 record cannot be read as JSON: {error}"
    if not isinstance(value, dict):
        return None, "existing V5 record is not a JSON object"
    return value, None


def _read_existing_json(path: Path) -> tuple[Any | None, str | None, str]:
    """Read an existing JSON target and classify missing/conflict hazards."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, None, "missing"
    except OSError as error:
        return None, f"existing target cannot be inspected: {error}", "unreadable"
    is_link = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
    if is_link or not stat.S_ISREG(info.st_mode):
        return None, "existing target is not a regular file", "symlink" if is_link else "unreadable"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"existing target cannot be read as JSON: {error}", "unreadable"
    return value, None, "present"


def _path_text(path: Path, root: Path) -> str:
    """Use stable, repository-relative paths in reports when possible."""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _database_source(database: Path) -> dict[str, str | None]:
    """Return a portable identity without overstating arbitrary fixtures."""

    parts = database.parts
    approved_tail = ("Game-Manifest-Index", "var", "db", "archive.sqlite")
    if len(parts) >= len(approved_tail) and tuple(part.casefold() for part in parts[-4:]) == tuple(
        part.casefold() for part in approved_tail
    ):
        return {
            "kind": "approved_legacy_repository_database",
            "repository": "Game-Manifest-Index",
            "path": "var/db/archive.sqlite",
            "identity": "Game-Manifest-Index/var/db/archive.sqlite",
            "file": "archive.sqlite",
        }
    return {
        "kind": "generic_database_file",
        "repository": None,
        "path": database.name,
        "identity": database.name,
        "file": database.name,
    }


def _snapshot_file(path: Path) -> bytes | None:
    """Return ordinary-file bytes, preserving missing state for rollback."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RecoveryError("affected index cannot be inspected for rollback") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RecoveryError("affected index cannot be snapshotted safely")
    try:
        return path.read_bytes()
    except OSError as error:
        raise RecoveryError("affected index cannot be read for rollback") from error


def _restore_file(path: Path, original: bytes | None) -> None:
    """Atomically restore one snapshotted file during rollback."""

    if original is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.rollback-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _publish_new_file(staged: Path, target: Path) -> tuple[int, int, bytes]:
    """Publish without replacing a target that may appear concurrently."""

    expected = staged.read_bytes()
    linked = False
    try:
        os.link(staged, target)
        linked = True
        info = os.lstat(target)
        staged_info = os.lstat(staged)
        if (
            not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(staged_info.st_mode) or stat.S_ISLNK(staged_info.st_mode)
            or (int(info.st_dev), int(info.st_ino)) != (int(staged_info.st_dev), int(staged_info.st_ino))
            or target.read_bytes() != expected
        ):
            raise RecoveryError(f"published target is not a regular file: {target}")
        return (int(info.st_dev), int(info.st_ino), expected)
    except Exception as error:
        if linked:
            try:
                info = os.lstat(target)
                staged_info = os.lstat(staged)
                if ((int(info.st_dev), int(info.st_ino)) == (int(staged_info.st_dev), int(staged_info.st_ino))
                        and target.read_bytes() == expected):
                    target.unlink()
                elif hasattr(error, "add_note"):
                    error.add_note(f"publication target changed during cleanup: {target}")
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                if hasattr(error, "add_note"):
                    error.add_note(f"publication cleanup failed for {target}: {cleanup_error}")
        raise


def _owned_publication(path: Path, ownership: tuple[int, int, bytes]) -> bool:
    try:
        info = os.lstat(path)
        return (
            stat.S_ISREG(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and (int(info.st_dev), int(info.st_ino)) == ownership[:2]
            and path.read_bytes() == ownership[2]
        )
    except OSError:
        return False


@contextmanager
def _cleanup_stage(stage: Path):
    try:
        yield
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _android_snapshot(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    snapshot: dict[str, bytes] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if len(relative.parts) < 3 or relative.parts[2] != "android":
            continue
        try:
            info = os.lstat(path)
        except OSError as error:
            raise RecoveryError(f"Android data cannot be inspected: {path}") from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RecoveryError(f"Android data contains a symlink or reparse point: {path}")
        if stat.S_ISREG(info.st_mode):
            try:
                snapshot[relative.as_posix()] = path.read_bytes()
            except OSError as error:
                raise RecoveryError(f"Android data cannot be read: {path}") from error
    return snapshot


def _safe_directory(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400)


def _absolute_path(path: Path) -> Path:
    """Make a path absolute without resolving symlinks or reparse points."""

    return Path(os.path.abspath(os.fspath(path)))


def _ensure_safe_output_root(root: Path) -> None:
    """Create/check an output directory without traversing links or junctions."""

    root = _absolute_path(root)
    current = Path(root.anchor) if root.anchor else Path(root.parts[0])
    parts = root.parts[1:] if root.anchor else root.parts[1:]
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                current.mkdir()
                info = os.lstat(current)
            except OSError as error:
                raise RecoveryError(f"output root cannot be created safely: {current}") from error
        except OSError as error:
            raise RecoveryError(f"output root cannot be inspected: {current}") from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
            raise RecoveryError(f"output root contains an unsafe directory: {current}")


def _validate_existing_output_root(root: Path) -> None:
    """Check existing output path components without creating a dry-run root."""

    root = _absolute_path(root)
    current = Path(root.anchor) if root.anchor else Path(root.parts[0])
    parts = root.parts[1:] if root.anchor else root.parts[1:]
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as error:
            raise RecoveryError(f"output root cannot be inspected: {current}") from error
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
            raise RecoveryError(f"output root contains an unsafe directory: {current}")


def _ensure_safe_parent(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise RecoveryError(f"publication path escapes output root: {path}") from error
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if not current.exists():
            try:
                current.mkdir()
            except OSError as error:
                raise RecoveryError(f"publication parent cannot be created safely: {current}") from error
        if not _safe_directory(current):
            raise RecoveryError(f"publication parent is not a safe directory: {current}")


def recover(
    database: Path,
    output_root: Path,
    *,
    apply: bool = False,
    domains: set[str] | None = None,
    source_root: Path | None = None,
    source_commit: str | None = None,
    report: Path | None = None,
) -> dict[str, Any]:
    """Build a validated recovery plan and optionally publish it.

    The optional source root enables the explicitly approved NTE 1.3.12
    commit-pinned legacy Git candidate.  Omitting it keeps this function a
    database-only recovery and does not inspect any Git checkout.
    """

    database = Path(database).resolve()
    database_source = _database_source(database)
    # Keep links/reparse points visible to the output safety checks.  Using
    # Path.resolve() here would silently canonicalize a user-provided symlink
    # and allow publication outside the requested root.
    output_root = _absolute_path(Path(output_root))
    if not database.is_file():
        raise RecoveryError(f"database does not exist: {database}")
    _validate_existing_output_root(output_root)
    # immutable prevents SQLite from creating a journal or otherwise writing
    # to the archive.  Keep the URI form (rather than opening ``database`` as
    # a normal path) so read-only mode is explicit on Windows too.
    uri = f"file:{database.as_posix()}?mode=ro&immutable=1"
    db = sqlite3.connect(uri, uri=True)
    try:
        rows = _query_rows(db, domains)
        skipped: Counter[str] = Counter()
        blocked: Counter[str] = Counter()
        skipped_details: list[dict[str, Any]] = []
        blocked_details: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        plans: dict[Path, dict[str, Any]] = {}
        documents: dict[Path, dict[str, Any]] = {}
        guarded_existing: dict[Path, tuple[dict[str, Any], str]] = {}
        planned_affected: set[tuple[str, str, str]] = set()
        domain_counts: Counter[str] = Counter()
        target_counts: Counter[Path] = Counter()
        target_by_row: dict[int, Path] = {}
        source_plan_target: Path | None = None
        for row in rows:
            if row["domain_id"] not in SUPPORTED_DOMAINS or row["game_id"] not in VENDOR_BY_GAME:
                continue
            try:
                target = v2_record_path(
                    {"vendor": VENDOR_BY_GAME[row["game_id"]], "game_id": row["game_id"],
                     "domain_id": row["domain_id"], "platform": "windows", "version": row["version"]},
                    output_root,
                )
            except (ValueError, TypeError):
                continue
            target_by_row[row["version_id"]] = target
            target_counts[target] += 1

        def finish_report(summary: dict[str, Any]) -> dict[str, Any]:
            if report is not None:
                _write_json(Path(report).resolve(), summary)
            return summary

        for row in rows:
            domain_id = row["domain_id"]
            game_id = row["game_id"]
            version = row["version"]
            artifact_kinds, url_source_kinds = _source_stats(db, row["revision_id"])
            provenance: dict[str, Any] = {}
            resource_audit: dict[str, Any] | None = None
            revision_attributes_for_audit: Mapping[str, Any] = {}
            try:
                revision_attributes = _json(
                    row["revision_attributes_json"],
                    f"revision {row['revision_id']}",
                    default={},
                )
                if isinstance(revision_attributes, Mapping):
                    revision_attributes_for_audit = revision_attributes
                if isinstance(revision_attributes, Mapping) and isinstance(version, str):
                    provenance = _compact_provenance(
                        game_id, domain_id, version, revision_attributes, row["capture_source_url"]
                    )
            except RecoveryError:
                # The conversion attempt below owns the precise diagnostic.
                provenance = {}
            if domain_id == "endfield-resources":
                try:
                    resource_audit = _resource_audit(
                        db, row["revision_id"], revision_attributes_for_audit
                    )
                except RecoveryError as error:
                    # Preserve a useful report even when conversion is later
                    # blocked for malformed revision/artifact metadata.
                    resource_audit = {
                        "revision": row["revision_id"],
                        "total": None,
                        "initial": None,
                        "main": None,
                        "urls": {"total": None, "official": None, "mirror": None, "md5": None},
                        "metadata": {},
                        "error": str(error),
                    }

            candidate: dict[str, Any] = {
                "domain": domain_id,
                "version": version,
                "source_db": database_source["identity"],
                "source_file": database_source["path"],
                "source": dict(database_source),
                "current_revision": row["revision_id"],
                "artifact_count": sum(artifact_kinds.values()),
                "artifact_kinds": dict(sorted(artifact_kinds.items())),
                "url_count": sum(url_source_kinds.values()),
                "url_source_kinds": dict(sorted(url_source_kinds.items())),
                "canonical_provenance": provenance,
                "provenance": provenance,
                "safe_conversion": None,
                "safe_conversion_status": "not_attempted",
                "existing_v5_record": False,
                "existing_v5": False,
                "existing_v5_content": "none",
                "content_conflict": False,
                "decision": None,
                "reason": None,
                "expected_record_path": None,
                "expected_manifest_paths": [],
                "record_path": None,
                "manifest_paths": [],
                "expected_paths": {"record": None, "manifests": []},
                "expected_record_bytes": None,
                "expected_manifest_bytes": [],
                "expected_record_serialized_bytes": None,
                "expected_manifest_serialized_bytes": [],
                "serialized_bytes": {"record": None, "manifests": []},
                # Keep target-state categories explicit in every candidate so
                # the audit report remains machine-readable for missing,
                # identical, conflicting, and link/reparse targets.
                "existing": {"record": "missing", "manifest": "not_applicable"},
                "existing_missing": [], "existing_identical": [],
                "existing_conflict": [], "existing_symlink": [],
                # Endfield resource counts/metadata are audit evidence only;
                # they are intentionally not copied to the v2 record.
                "resource_audit": resource_audit,
                "resource_metadata": resource_audit.get("metadata", {}) if resource_audit else {},
            }

            if domain_id not in SUPPORTED_DOMAINS or game_id not in VENDOR_BY_GAME:
                skipped["unsupported_pc_domain"] += 1
                candidate.update(
                    decision="skip", reason="unsupported_pc_domain",
                    safe_conversion=False, safe_conversion_status="unsupported",
                )
                skipped_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue

            try:
                target = target_by_row[row["version_id"]]
            except KeyError:
                blocked["unsafe_target_path"] += 1
                candidate.update(
                    decision="block", reason="unsafe_target_path",
                    safe_conversion=False, safe_conversion_status="blocked",
                )
                blocked_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue
            candidate["expected_record_path"] = _path_text(target, output_root)
            candidate["expected_paths"] = {"record": _path_text(target, output_root), "manifests": []}
            candidate["record_path"] = _path_text(target, output_root)
            candidate["manifest_paths"] = []
            if target_counts[target] > 1:
                blocked["duplicate_recovery_target"] += 1
                candidate.update(
                    decision="block", reason="duplicate_recovery_target",
                    safe_conversion=False, safe_conversion_status="blocked",
                )
                blocked_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue
            try:
                record, document = _record_from_db(db, row)
            except (RecoveryError, ValueError, TypeError, KeyError) as error:
                blocked["unsafe_conversion"] += 1
                candidate.update(
                    decision="block", reason=str(error),
                    safe_conversion=False, safe_conversion_status="unsafe",
                )
                blocked_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue

            record_bytes = len(_serialized_json(record).encode("utf-8"))
            canonical_artifact_kinds = Counter(item.get("kind", "unknown") for item in record["artifacts"])
            candidate["canonical_artifact_count"] = len(record["artifacts"])
            candidate["canonical_artifact_kinds"] = dict(sorted(canonical_artifact_kinds.items()))
            candidate["canonical_url_count"] = sum(len(item.get("urls", [])) for item in record["artifacts"])
            manifest_paths: list[Path] = []
            manifest_bytes: list[int] = []
            if document is not None:
                if any(ref.get("kind") == "chunk_manifest" for ref in record["references"]):
                    document_path = target.parent / record["references"][0]["path"]
                else:
                    document_path = target.parent / record["artifacts"][0]["manifest"]["path"]
                manifest_paths.append(document_path)
                manifest_bytes.append(len(_serialized_json(document).encode("utf-8")))

            existing, existing_error = _read_existing_record(target)
            candidate["existing_v5_record"] = existing is not None or existing_error is not None
            candidate["existing_v5"] = candidate["existing_v5_record"]
            if existing_error is not None:
                state = "symlink" if (target.is_symlink() or "not a regular file" in existing_error) else "unreadable"
            elif existing is None:
                state = "missing"
            else:
                state = "present"
            candidate["existing"]["record"] = state
            if state == "missing":
                candidate["existing_missing"].append("record")
            elif state == "symlink":
                candidate["existing_symlink"].append("record")
            candidate["serialized_bytes"] = {
                "record": record_bytes,
                "manifests": manifest_bytes,
                "total": record_bytes + sum(manifest_bytes),
            }
            candidate["expected_manifest_paths"] = [_path_text(path, output_root) for path in manifest_paths]
            candidate["expected_paths"] = {
                "record": _path_text(target, output_root),
                "manifests": [_path_text(path, output_root) for path in manifest_paths],
            }
            candidate["manifest_paths"] = list(candidate["expected_paths"]["manifests"])
            candidate["expected_record_bytes"] = record_bytes
            candidate["expected_manifest_bytes"] = manifest_bytes
            candidate["expected_record_serialized_bytes"] = record_bytes
            candidate["expected_manifest_serialized_bytes"] = manifest_bytes
            candidate["safe_conversion"] = True
            candidate["safe_conversion_status"] = "safe"
            if existing_error is not None:
                blocked["existing_record_unreadable"] += 1
                candidate.update(
                    decision="block", reason=existing_error,
                    existing_v5_content="unreadable", content_conflict=True,
                )
                blocked_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue
            if existing is not None and existing != record:
                skipped["existing_record_conflict"] += 1
                skipped["existing_record_preserved"] += 1
                candidate.update(
                    decision="skip", reason="existing_v5_record_conflict",
                    existing_v5_content="conflict", content_conflict=True,
                )
                skipped_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue
            if existing is not None:
                candidate["existing_identical"].append("record")
                candidate["existing_v5_content"] = "identical"

            # A manifest is part of the candidate's canonical content.  Keep
            # an identical existing manifest, but block a conflicting one.
            manifest_conflict = False
            manifest_unreadable = False
            for document_path, expected_document in zip(manifest_paths, [document] if document is not None else []):
                if not (document_path.exists() or document_path.is_symlink()):
                    candidate["existing_missing"].append("manifest")
                    candidate["existing"]["manifest"] = "missing"
                    continue
                info = None
                try:
                    info = os.lstat(document_path)
                except OSError:
                    manifest_unreadable = True
                    candidate["existing_conflict"].append("manifest")
                    candidate["existing"]["manifest"] = "unreadable"
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    candidate["existing_symlink"].append("manifest")
                    candidate["existing"]["manifest"] = "symlink"
                    manifest_unreadable = True
                    continue
                try:
                    existing_document = json.loads(document_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    existing_document = None
                    manifest_unreadable = True
                    candidate["existing_conflict"].append("manifest")
                    candidate["existing"]["manifest"] = "unreadable"
                    continue
                candidate["existing"]["manifest"] = "present"
                if existing_document != expected_document:
                    candidate["existing_conflict"].append("manifest")
                    manifest_conflict = True
                else:
                    candidate["existing_identical"].append("manifest")
            if manifest_conflict or manifest_unreadable:
                blocked["existing_manifest_conflict"] += 1
                candidate.update(decision="block", reason="existing_manifest_conflict", content_conflict=True,
                                 existing_v5_content="conflict")
                blocked_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
                candidates.append(candidate)
                continue

            if existing is None:
                plans[target] = record
            domain_counts[domain_id] += 1
            missing_manifest = document is not None and not manifest_paths[0].exists()
            if existing is not None and missing_manifest:
                guarded_existing[target] = (record, "record")
            elif existing is None and document is not None and "manifest" in candidate["existing_identical"]:
                guarded_existing[manifest_paths[0]] = (document, "manifest")
            if existing is not None and not missing_manifest:
                skipped["existing_record_identical"] += 1
                skipped["existing_record_preserved"] += 1
                candidate.update(decision="skip", reason="existing_v5_record_identical")
                skipped_details.append({"domain_id": domain_id, "version": version, "reason": candidate["reason"]})
            else:
                candidate.update(
                    decision="plan",
                    reason="missing_manifest_for_identical_record" if existing is not None else "missing_v5_record",
                )
                planned_affected.add((record["vendor"], record["game_id"], record["domain_id"]))
            candidates.append(candidate)
            if missing_manifest and manifest_paths[0] not in documents:
                documents[manifest_paths[0]] = document

        source_candidate: dict[str, Any] | None = None
        source_requested = source_root is not None
        source_path = "provided_legacy_git_checkout" if source_root is not None else None
        source_status = "not_requested"
        source_reason: str | None = None
        source_decision: str | None = None
        # A domain filter applies to the source candidate as it does to DB
        # rows.  Crucially, an omitted source root does not cause any Git
        # operation at all.
        if source_requested and (domains is None or "nte-pc" in domains):
            source_candidate = {
                "kind": "legacy_git", "domain": "nte-pc", "version": "1.3.12",
                "source_root": source_path, "source_commit": source_commit or NTE_LEGACY_COMMIT,
                "source_tree": None, "source_url": NTE_LEGACY_SOURCE_URL,
                "canonical_provenance": None,
                "source_paths": {"record": NTE_LEGACY_RECORD_PATH, "manifest": NTE_LEGACY_MANIFEST_PATH},
                "source_blobs": {}, "counts": {"files": None, "patches": None},
                "validation": {}, "ignored_fields": ["adapter", "status", "current", "etag", "unknown_config_fields"],
                "expected_record_path": None, "expected_manifest_paths": [],
                "expected_paths": {"record": None, "manifests": []},
                "record_path": None, "manifest_paths": [],
                "expected_record_bytes": None, "expected_manifest_bytes": [],
                "serialized_bytes": {"record": None, "manifests": [], "total": None},
                "safe_conversion": None, "safe_conversion_status": "not_attempted",
                "existing": {"record": "missing", "manifest": "missing"},
                "existing_missing": [], "existing_identical": [], "existing_conflict": [], "existing_symlink": [],
                "decision": None, "reason": None,
            }
            try:
                source_record, source_document, source_metadata = _read_nte_legacy_source(
                    Path(source_root), source_commit or NTE_LEGACY_COMMIT
                )
                source_target = v2_record_path(source_record, output_root)
                source_manifest_target = source_target.parent / source_record["artifacts"][0]["manifest"]["path"]
                source_plan_target = source_target
                source_candidate.update(
                    source_tree=source_metadata["source_tree"], source_blobs=source_metadata["blobs"],
                    canonical_provenance=dict(source_record["provenance"]),
                    counts={"files": NTE_LEGACY_FILE_COUNT, "patches": NTE_LEGACY_PATCH_COUNT},
                    validation={
                        "status": "passed", "commit": True, "tree": True, "blobs": True,
                        "identity": True, "official_urls": True, "counts": True,
                        "file_size": True, "manifest_consistency": True,
                    },
                    expected_record_path=_path_text(source_target, output_root),
                    expected_manifest_paths=[_path_text(source_manifest_target, output_root)],
                    expected_record_bytes=len(_serialized_json(source_record).encode("utf-8")),
                    expected_manifest_bytes=[len(_serialized_json(source_document).encode("utf-8"))],
                )
                source_candidate["serialized_bytes"] = {
                    "record": source_candidate["expected_record_bytes"],
                    "manifests": source_candidate["expected_manifest_bytes"],
                    "total": source_candidate["expected_record_bytes"] + source_candidate["expected_manifest_bytes"][0],
                }
                source_candidate["expected_paths"] = {
                    "record": _path_text(source_target, output_root),
                    "manifests": [_path_text(source_manifest_target, output_root)],
                }
                source_candidate["record_path"] = _path_text(source_target, output_root)
                source_candidate["manifest_paths"] = [_path_text(source_manifest_target, output_root)]
                source_candidate["safe_conversion"] = True
                source_candidate["safe_conversion_status"] = "safe"
                record_existing, record_error, record_state = _read_existing_json(source_target)
                manifest_existing, manifest_error, manifest_state = _read_existing_json(source_manifest_target)
                source_candidate["existing"] = {"record": record_state, "manifest": manifest_state}
                for label, state in (("record", record_state), ("manifest", manifest_state)):
                    if state == "missing":
                        source_candidate["existing_missing"].append(label)
                    elif state == "symlink":
                        source_candidate["existing_symlink"].append(label)
                if record_state == "symlink" or manifest_state == "symlink":
                    source_decision, source_reason = "block", "existing_source_target_symlink"
                elif record_error or manifest_error:
                    source_decision, source_reason = "block", record_error or manifest_error
                    source_candidate["existing_conflict"] = [label for label, error in (("record", record_error), ("manifest", manifest_error)) if error]
                elif record_state == "present" and record_existing != source_record:
                    source_decision, source_reason = "skip", "existing_source_record_conflict"
                    source_candidate["existing_conflict"].append("record")
                elif manifest_state == "present" and manifest_existing != source_document:
                    source_decision, source_reason = "block", "existing_source_manifest_conflict"
                    source_candidate["existing_conflict"].append("manifest")
                elif source_target in plans:
                    source_decision, source_reason = "block", "duplicate_recovery_target"
                else:
                    if record_state == "present":
                        source_candidate["existing_identical"].append("record")
                    if manifest_state == "present":
                        source_candidate["existing_identical"].append("manifest")
                    if record_state == "missing":
                        plans[source_target] = source_record
                    else:
                        guarded_existing[source_target] = (source_record, "record")
                    if manifest_state == "missing":
                        documents[source_manifest_target] = source_document
                    else:
                        guarded_existing[source_manifest_target] = (source_document, "manifest")
                    source_decision, source_reason = (
                        ("plan", "missing_source_record_or_manifest")
                        if record_state == "missing" or manifest_state == "missing"
                        else ("skip", "existing_source_record_identical")
                    )
                    if source_decision == "plan":
                        domain_counts["nte-pc"] += 1
                        planned_affected.add((source_record["vendor"], source_record["game_id"], source_record["domain_id"]))
            except (RecoveryError, ValueError, TypeError, KeyError) as error:
                source_decision, source_reason = "block", str(error)
                source_candidate["validation"] = {"status": "failed"}
            candidate_reason = source_reason
            source_candidate.update(decision=source_decision, reason=candidate_reason)
            source_status = "ready" if source_decision in {"plan", "skip"} else "blocked"
            if source_decision == "plan":
                source_reason = "pinned_source_candidate_planned"
            if source_decision == "skip":
                skipped_details.append({"domain_id": "nte-pc", "version": "1.3.12", "reason": source_reason})
            elif source_decision == "block":
                blocked_details.append({"domain_id": "nte-pc", "version": "1.3.12", "reason": source_reason})
            candidates.append(source_candidate)
        elif source_requested:
            source_status = "filtered"
            source_reason = "domain_filter_excludes_nte-pc"

        candidates.sort(key=lambda item: (str(item.get("domain")), str(item.get("version")), int(item.get("current_revision") or 0)))
        skipped_details.sort(key=lambda item: (str(item["domain_id"]), str(item["version"]), str(item["reason"])))
        blocked_details.sort(key=lambda item: (str(item["domain_id"]), str(item["version"]), str(item["reason"])))
        decision_counts = Counter(item["decision"] for item in candidates)
        summary: dict[str, Any] = {
            "report_version": 1,
            "database": database_source["identity"], "database_source": database_source,
            "output_root": "data", "apply": apply,
            "source_root": {
                "path": source_path, "commit": source_commit or (NTE_LEGACY_COMMIT if source_requested else None),
                "status": source_status, "decision": source_decision, "used": source_requested and source_candidate is not None,
                "reason": source_reason,
            },
            "source_candidate": source_candidate,
            "candidate_rows": len(rows), "planned_records": len(plans),
            "planned_manifests": len(documents), "written_records": 0,
            "written_manifests": 0, "domains": dict(sorted(domain_counts.items())),
            "skipped": dict(sorted(skipped.items())), "skipped_details": skipped_details,
            "blocked": dict(sorted(blocked.items())), "blocked_details": blocked_details,
            "decision_counts": {key: decision_counts.get(key, 0) for key in ("plan", "skip", "block")},
            "planned": decision_counts.get("plan", 0), "skip": decision_counts.get("skip", 0), "block": decision_counts.get("block", 0),
            "summary": {"planned": decision_counts.get("plan", 0), "skip": decision_counts.get("skip", 0), "block": decision_counts.get("block", 0)},
            "candidates": candidates,
        }
        if not apply or (not plans and not documents):
            return finish_report(summary)

        _ensure_safe_output_root(output_root)
        stage = Path(tempfile.mkdtemp(prefix=".pc-recovery-", dir=output_root.parent))
        affected = set(planned_affected)
        # Hold both repository locks from the final preflight through rollback.
        # The lock file itself is persistent runtime synchronization state.
        with _cleanup_stage(stage), ExitStack() as locks:
            locks.enter_context(DATA_LOCK)
            locks.enter_context(data_file_lock(output_root))
            # Read-only boundary/concurrency sentinel: recovery never writes Android.
            android_before = _android_snapshot(output_root)
            published: list[tuple[Path, tuple[int, int, bytes]]] = []
            index_snapshots: dict[Path, bytes | None] = {}
            try:
                for target, record in plans.items():
                    staged = stage / target.relative_to(output_root)
                    _write_json(staged, record)
                    affected.add((record["vendor"], record["game_id"], record["domain_id"]))
                for target, document in documents.items():
                    staged = stage / target.relative_to(output_root)
                    _write_json(staged, document)
                for guarded_path, (expected, label) in guarded_existing.items():
                    actual, read_error, state = _read_existing_json(guarded_path)
                    if state != "present" or read_error or actual != expected:
                        raise RecoveryError(f"guarded existing {label} changed during recovery: {guarded_path}")
                # Preflight every final path before publishing the first file.
                for target in (*plans, *documents):
                    _ensure_safe_parent(output_root, target)
                    if target.exists() or target.is_symlink():
                        raise RecoveryError(f"publication target appeared during staging: {target}")
                # Validate the staged graph before any publication.
                for target, record in plans.items():
                    validate_v2_record(json.loads((stage / target.relative_to(output_root)).read_text(encoding="utf-8")))
                for target, document in documents.items():
                    if document.get("schema_version") != 1:
                        raise RecoveryError(f"staged manifest is not schema 1: {target}")
                for vendor, game_id, domain_id in sorted(affected):
                    default_domain = f"{game_id}-pc"
                    rebuild_domain = None if domain_id == default_domain else domain_id
                    affected_index = index_path(output_root, vendor, game_id, "windows", rebuild_domain)
                    index_snapshots[affected_index] = _snapshot_file(affected_index)
                # Publish referenced documents first, then records without overwrite.
                for target in (*sorted(documents), *sorted(plans)):
                    staged = stage / target.relative_to(output_root)
                    _ensure_safe_parent(output_root, target)
                    ownership = _publish_new_file(staged, target)
                    published.append((target, ownership))
                    staged.unlink()
                summary["written_records"] = len(plans)
                summary["written_manifests"] = len(documents)
                for vendor, game_id, domain_id in sorted(affected):
                    default_domain = f"{game_id}-pc"
                    rebuild_domain = None if domain_id == default_domain else domain_id
                    rebuild_path = index_path(output_root, vendor, game_id, "windows", rebuild_domain)
                    current = output_root
                    for part in rebuild_path.parent.relative_to(output_root).parts:
                        current = current / part
                        if not _safe_directory(current):
                            current.mkdir()
                        if not _safe_directory(current):
                            raise OSError(f"unsafe index directory: {current}")
                    rebuild_index(output_root, vendor, game_id, "windows", rebuild_domain)
                if _android_snapshot(output_root) != android_before:
                    raise RecoveryError("Android data changed during PC recovery")
            except Exception as error:
                rollback_errors: list[str] = []
                for target, ownership in reversed(published):
                    try:
                        if _owned_publication(target, ownership):
                            target.unlink()
                        elif target.exists() or target.is_symlink():
                            rollback_errors.append(f"leave replaced publication {_path_text(target, output_root)}")
                    except OSError as rollback_error:
                        rollback_errors.append(f"remove {_path_text(target, output_root)}: {rollback_error}")
                for path, original in index_snapshots.items():
                    try:
                        _restore_file(path, original)
                    except OSError as rollback_error:
                        rollback_errors.append(f"restore {_path_text(path, output_root)}: {rollback_error}")
                if rollback_errors and hasattr(error, "add_note"):
                    error.add_note("rollback encountered errors: " + "; ".join(rollback_errors))
                raise
        return finish_report(summary)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", "--database", dest="database", type=Path, required=True, help="legacy archive.sqlite (opened read-only)")
    parser.add_argument("--source-root", type=Path, help="approved legacy Git source root (read-only)")
    parser.add_argument("--source-commit", default=NTE_LEGACY_COMMIT, help="approved complete legacy Git commit SHA")
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--domains", nargs="+", action="append", dest="domain_groups", help="recover only these domains (one or more; repeatable or comma-separated)")
    parser.add_argument("--domain", action="append", dest="domain_values", help="recover only this domain (repeatable)")
    parser.add_argument("--apply", action="store_true", help="publish missing records after staging and validation")
    parser.add_argument("--report", "--audit-output", dest="report", type=Path, help="write the deterministic JSON recovery report")
    args = parser.parse_args()
    selected_domains = None
    raw_domains = [item for group in (args.domain_groups or []) for item in group]
    raw_domains.extend(args.domain_values or [])
    if raw_domains:
        selected_domains = {item.strip() for value in raw_domains for item in value.split(",") if item.strip()}
    summary = recover(
        args.database, args.output_root, apply=args.apply, domains=selected_domains,
        source_root=args.source_root, source_commit=args.source_commit, report=args.report,
    )
    rendered = _serialized_json(summary)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
