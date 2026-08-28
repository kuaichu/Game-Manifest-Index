"""Reproducibly migrate the fixed historical PC snapshot into schema v2.

This is intentionally source-specific.  It reads only Git objects from the
fixed source tree; it never copies files from a dirty checkout.  The script
does not perform network access.  A separate bounded invocation of
``url_adapters.service.discover_games(..., scope="pc")`` supplies current
official records after this migration.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

# Allow the script to be invoked directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import v2_record_path


SOURCE_COMMIT = "85e92d5b7f8868bb5c28901606c50132fe4705bf"
SOURCE_TREE = "7e64fddb974324b3aca39f1d50d31b20336bea81"
ALLOWED_PROVENANCE = {"third_party_history", "legacy_migration"}
GAMES = {
    ("mihoyo", "hk4e"), ("mihoyo", "hkrpg"), ("mihoyo", "nap"),
    ("mihoyo", "bh3"), ("kuro", "wuwa"),
    ("perfectworld", "tof"), ("perfectworld", "p5x"), ("perfectworld", "nte"),
}
RECORD_PATH = re.compile(r"^data/([^/]+)/([^/]+)/pc/([^/]+)\.json$")
MANIFEST_PATH = re.compile(r"^data/([^/]+)/([^/]+)/pc/(manifests|chunk-manifests)/([^/]+)\.json$")
SEGMENT_SUFFIX = re.compile(r"\.(\d{3})$")
MD5 = re.compile(r"^[0-9a-fA-F]{32}$")
SAFE_PART = re.compile(r"^[^/\\]+$")
CURRENT_KEYS = ("state", "http_code", "checked_at", "response_size", "etag", "crc64", "last_modified", "final_url")
RECORD_PROVENANCE_KEYS = ("source_kind", "source_name", "source_url", "source_repo", "source_commit", "imported_at")


class MigrationError(ValueError):
    """An old record cannot be converted without guessing."""


def _run_git(source_repo: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(["git", "-C", str(source_repo), *args], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        raise MigrationError(f"git object read failed: {' '.join(args)}") from error


def _check_source(source_repo: Path) -> None:
    actual = _run_git(source_repo, "rev-parse", f"{SOURCE_COMMIT}^{{tree}}").decode().strip()
    if actual != SOURCE_TREE:
        raise MigrationError(f"fixed source tree mismatch: expected {SOURCE_TREE}, got {actual}")


def _source_paths(source_repo: Path) -> list[str]:
    return _run_git(source_repo, "ls-tree", "-r", "--name-only", SOURCE_TREE).decode().splitlines()


def _read_json(source_repo: Path, path: str) -> Any:
    raw = _run_git(source_repo, "show", f"{SOURCE_TREE}:{path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise MigrationError(f"invalid JSON in Git object: {path}") from error


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: Any, field: str, *, optional: bool = True) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MigrationError(f"{field} must be a non-negative integer")
    return value


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or "://" in value:
        raise MigrationError("unsafe manifest path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MigrationError("unsafe manifest path")
    return value


def _compact_source(value: Any, *, include_imported_at: bool = False) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise MigrationError("provenance must be an object")
    kind = value.get("source_kind")
    if kind not in ALLOWED_PROVENANCE:
        raise MigrationError(f"source provenance kind is not migratable: {kind!r}")
    result: dict[str, str] = {}
    keys = RECORD_PROVENANCE_KEYS if include_imported_at else RECORD_PROVENANCE_KEYS[:-1]
    for key in keys:
        item = value.get(key)
        if key == "source_name" and item is None:
            # Older Game-Manifest-Index records called this field
            # ``source_project``; retain that real provenance label without
            # treating any CDN URL as the discovery source.
            item = value.get("source_project")
        if item is not None:
            if not _nonempty(item):
                raise MigrationError(f"provenance.{key} must be a non-empty string")
            result[key] = item
    return result


def _current_url_state(value: Any, candidate_url: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in CURRENT_KEYS:
        if key not in value:
            continue
        item = value[key]
        if key in {"http_code", "response_size"}:
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                continue
        elif key == "state":
            if item not in {"available", "unavailable", "unknown"}:
                continue
        elif item is not None and not _nonempty(item):
            continue
        if key == "final_url" and item == candidate_url:
            continue
        result[key] = item
    # The legacy probe called this field observed_size.  It is a response
    # size only when it is actually an integer; no legacy evidence fields are
    # copied into canonical current state.
    if "response_size" not in result and isinstance(value.get("observed_size"), int) and not isinstance(value.get("observed_size"), bool):
        result["response_size"] = value["observed_size"]
    return result or None


def _urls(old: Any) -> list[dict[str, Any]]:
    if old is None:
        return []
    if not isinstance(old, list):
        raise MigrationError("artifact.urls must be an array")
    result = []
    for index, item in enumerate(old):
        if not isinstance(item, Mapping) or not _nonempty(item.get("url")):
            raise MigrationError(f"artifact.urls[{index}] is incomplete")
        provider = item.get("provider", "historical")
        source_kind = item.get("source_kind", "historical")
        if not _nonempty(provider) or not _nonempty(source_kind):
            raise MigrationError(f"artifact.urls[{index}] has invalid source")
        priority = item.get("priority", index)
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
            raise MigrationError(f"artifact.urls[{index}] has invalid priority")
        candidate: dict[str, Any] = {
            "url": item["url"], "provider": provider,
            "source_kind": source_kind, "priority": priority,
        }
        current = _current_url_state(item.get("current"), item["url"])
        if current is not None:
            candidate["current"] = current
        result.append(candidate)
    return result


def _checksum(old: Mapping[str, Any]) -> dict[str, str] | None:
    kind = old.get("checksum_type")
    value = old.get("checksum_value")
    if kind is None and value is None:
        return None
    if not _nonempty(kind) or not _nonempty(value):
        raise MigrationError("checksum is incomplete")
    key = kind.casefold()
    if key not in {"md5", "sha256", "crc64"}:
        raise MigrationError(f"unsupported checksum type: {kind}")
    return {key: value.lower()}


def _base_urls(old: Any, provider: str) -> list[dict[str, Any]]:
    if old is None:
        return []
    if not isinstance(old, list):
        raise MigrationError("manifest base_urls must be an array")
    result = []
    for priority, url in enumerate(old):
        if not _nonempty(url):
            raise MigrationError("manifest base URL is invalid")
        result.append({"url": url, "provider": provider, "source_kind": "official", "priority": priority})
    return result


def _kuro_manifest(
    old: Mapping[str, Any], *, version: str, provenance: Mapping[str, str], route_from: str | None,
) -> dict[str, Any]:
    resource = old.get("resource")
    if not isinstance(resource, list):
        raise MigrationError("Kuro resource manifest has no resource array")
    resources = []
    destinations: set[str] = set()
    for index, item in enumerate(resource):
        if not isinstance(item, Mapping):
            raise MigrationError(f"Kuro resource[{index}] is invalid")
        dest = _safe_relative_path(item.get("dest"))
        if dest in destinations:
            raise MigrationError("Kuro resource destination is duplicated")
        destinations.add(dest)
        md5 = item.get("md5")
        if not _nonempty(md5) or not MD5.fullmatch(md5):
            raise MigrationError("Kuro resource md5 is invalid")
        size = _nonnegative_int(item.get("size"), "Kuro resource size", optional=False)
        resources.append({"dest": dest, "md5": md5.lower(), "size": size})
    deletes = old.get("deleteFiles", [])
    if not isinstance(deletes, list):
        raise MigrationError("Kuro deleteFiles is invalid")
    delete_files = []
    seen_deletes: set[str] = set()
    for item in deletes:
        path = _safe_relative_path(item)
        if path in seen_deletes:
            raise MigrationError("Kuro deleteFiles is duplicated")
        seen_deletes.add(path)
        delete_files.append(path)
    result: dict[str, Any] = {
        "schema_version": 1, "vendor": "kuro", "game_id": "wuwa",
        "platform": "windows", "version": version,
    }
    if route_from is not None:
        result.update(route_from=route_from, route_to=version)
    result.update(resource=resources, deleteFiles=delete_files, provenance=dict(provenance))
    return result


def _chunk_recipe(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _nonempty(value.get("url_prefix")):
        raise MigrationError("chunk recipe is incomplete")
    result: dict[str, Any] = {"url_prefix": value["url_prefix"], "url_suffix": value.get("url_suffix", "")}
    if not isinstance(result["url_suffix"], str):
        raise MigrationError("chunk recipe suffix is invalid")
    for key in ("compression", "encryption"):
        item = value.get(key, 0)
        if isinstance(item, bool) or not isinstance(item, int) or item not in {0, 1}:
            raise MigrationError("chunk recipe flag is invalid")
        result[key] = item
    return result


def _chunk_manifest(old: Mapping[str, Any], *, provenance: Mapping[str, str]) -> dict[str, Any]:
    if old.get("schema_version") != 1 or not isinstance(old.get("manifests"), list):
        raise MigrationError("unsupported chunk manifest schema")
    result: dict[str, Any] = {
        "schema_version": 1, "vendor": old.get("vendor"), "game_id": old.get("game_id"),
        "domain_id": old.get("domain_id"), "platform": "windows", "version": old.get("version"),
        "tag": old.get("tag"), "build_id": old.get("build_id"),
        "diff_tags": old.get("diff_tags", []), "manifests": [],
        "provenance": dict(provenance),
    }
    if not all(_nonempty(result.get(key)) for key in ("vendor", "game_id", "domain_id", "version", "tag", "build_id")):
        raise MigrationError("chunk manifest identity is incomplete")
    if not isinstance(result["diff_tags"], list) or not all(_nonempty(item) for item in result["diff_tags"]):
        raise MigrationError("chunk manifest diff_tags is invalid")
    for index, item in enumerate(old["manifests"]):
        if not isinstance(item, Mapping):
            raise MigrationError(f"chunk manifest item {index} is invalid")
        category = item.get("category", {})
        if not isinstance(category, Mapping):
            raise MigrationError("chunk manifest category is invalid")
        category_out = {"id": category.get("id"), "name": category.get("name")}
        if category_out["id"] is not None and (isinstance(category_out["id"], bool) or not isinstance(category_out["id"], int)):
            raise MigrationError("chunk manifest category id is invalid")
        if category_out["name"] is not None and not isinstance(category_out["name"], str):
            raise MigrationError("chunk manifest category name is invalid")
        raw_manifest = item.get("manifest")
        if not isinstance(raw_manifest, Mapping) or not _nonempty(raw_manifest.get("id")) or not _nonempty(raw_manifest.get("checksum")):
            raise MigrationError("chunk manifest identity is incomplete")
        manifest = {"id": raw_manifest["id"], "checksum": raw_manifest["checksum"]}
        for key in ("compressed_size", "uncompressed_size"):
            size = _nonnegative_int(raw_manifest.get(key), f"manifest.{key}")
            if size is not None:
                manifest[key] = size
        matching = item.get("matching_field")
        if not _nonempty(matching):
            raise MigrationError("chunk manifest matching_field is invalid")
        component = item.get("component")
        if component not in {"game", "voice", "resource"}:
            raise MigrationError("chunk manifest component is invalid")
        language = item.get("language")
        if language is not None and not _nonempty(language):
            raise MigrationError("chunk manifest language is invalid")
        out: dict[str, Any] = {
            "category": category_out, "manifest": manifest, "component": component,
            "language": language, "matching_field": matching,
        }
        for stats_key in ("stats", "deduplicated_stats"):
            stats = item.get(stats_key, {})
            if not isinstance(stats, Mapping):
                raise MigrationError(f"chunk manifest {stats_key} is invalid")
            normalized: dict[str, int] = {}
            for key in ("compressed_size", "uncompressed_size", "file_count", "chunk_count"):
                size = _nonnegative_int(stats.get(key), f"{stats_key}.{key}")
                if size is not None:
                    normalized[key] = size
            out[stats_key] = normalized
        out["manifest_download"] = _chunk_recipe(item.get("manifest_download"))
        out["chunk_download"] = _chunk_recipe(item.get("chunk_download"))
        result["manifests"].append(out)
    return result


def _artifact(
    old: Mapping[str, Any], *, record: Mapping[str, Any], vendor: str, game_id: str,
    source_repo: Path, old_paths: Mapping[str, Any], generated_manifests: dict[str, dict[str, Any]],
    exclusions: Counter[str],
) -> dict[str, Any] | None:
    attrs = old.get("attributes")
    if not isinstance(attrs, Mapping):
        raise MigrationError("artifact.attributes is missing")
    kind = old.get("kind")
    if kind not in {"package", "patch"}:
        raise MigrationError(f"unsupported artifact kind: {kind!r}")
    component = attrs.get("component")
    old_type = attrs.get("package_type")
    if component not in {"game", "voice", "launcher", "other"} or not _nonempty(old_type):
        raise MigrationError("artifact component/package_type is incomplete")
    language = attrs.get("language")
    if language is not None and not _nonempty(language):
        raise MigrationError("artifact language is invalid")
    route_from = attrs.get("route_from")
    route_to = attrs.get("route_to")
    if kind == "patch":
        if not _nonempty(route_from) or not _nonempty(route_to) or route_from == route_to:
            raise MigrationError("patch route is incomplete")
        if old_type not in {"differential", "differential_optional_component"}:
            raise MigrationError("patch package_type is invalid")
    elif old_type == "differential":
        raise MigrationError("package cannot be differential")
    if old_type in {"optional_component", "differential_optional_component"}:
        if component != "voice" or not _nonempty(language):
            raise MigrationError("voice optional component lacks component/language")
        package_type = "optional" if old_type == "optional_component" else "differential"
    elif old_type in {"full", "segment", "differential"}:
        package_type = old_type
    else:
        raise MigrationError(f"unsupported package_type: {old_type!r}")
    name = old.get("name")
    if not _nonempty(name):
        raise MigrationError("artifact name is missing")
    result: dict[str, Any] = {
        "kind": kind, "component": component, "package_type": package_type,
        "delivery_mode": attrs.get("delivery_mode", "archive"), "name": name,
    }
    if result["delivery_mode"] not in {"direct", "archive", "file_manifest"}:
        raise MigrationError("artifact delivery_mode is invalid")
    if language is not None:
        result["language"] = language
    if kind == "patch":
        result.update(route_from=route_from, route_to=route_to)
    size = _nonnegative_int(old.get("size"), "artifact.size")
    if size is not None:
        result["size"] = size
    decompressed = _nonnegative_int(old.get("decompressed_size", attrs.get("decompressed_size")), "artifact.decompressed_size")
    if decompressed is not None:
        result["decompressed_size"] = decompressed
    checksum = _checksum(old)
    if checksum is not None:
        result["checksum"] = checksum
    result["urls"] = _urls(old.get("urls"))

    if package_type == "segment":
        match = SEGMENT_SUFFIX.search(PurePosixPath(name).name)
        if match is None:
            raise MigrationError("segment name has no explicit .001-style suffix")
        result["part"] = int(match.group(1))

    # Kuro's historical resource.json is converted to the current independent
    # schema-1 document.  Legacy patches without a paired local manifest are
    # deliberately excluded rather than pointing at an invented document.
    if vendor == "kuro":
        local = attrs.get("local_manifest") or attrs.get("manifest_path")
        if local is None:
            if kind == "patch":
                exclusions["kuro_route_manifest_unpaired"] += 1
                return None
            raise MigrationError("Kuro full artifact has no local manifest")
        expected = f"kuro/wuwa/pc/manifests/{record['version']}.json"
        old_manifest_path = f"data/{local}"
        if local != expected or old_manifest_path not in old_paths:
            raise MigrationError("Kuro local manifest association is not one-to-one")
        if kind != "package" or package_type != "full":
            exclusions["kuro_route_manifest_unpaired"] += 1
            return None
        manifest_source = _compact_source(record["provenance"])
        document = _kuro_manifest(old_paths[old_manifest_path], version=record["version"], provenance=manifest_source, route_from=None)
        target = f"manifests/{record['version']}/full.json"
        manifest = {"path": target}
        bases = attrs.get("base_urls")
        if bases:
            manifest["base_urls"] = _base_urls(bases, "kuro")
        result["delivery_mode"] = "file_manifest"
        result["manifest"] = manifest
        generated_manifests[target] = document

    identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    result["artifact_id"] = artifact_id(result, identity)
    return result


def _record(
    source_repo: Path, source_path: str, old: Mapping[str, Any], all_paths: set[str],
    manifest_cache: dict[str, Any], exclusions: Counter[str],
    exclusion_details: Counter[tuple[str, str]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]] | None:
    vendor, game_id, _ = RECORD_PATH.fullmatch(source_path).groups()  # type: ignore[union-attr]
    if (vendor, game_id) not in GAMES:
        exclusions["unsupported_game"] += 1
        return None
    provenance = _compact_source(old.get("provenance"), include_imported_at=True)
    record: dict[str, Any] = {
        "schema_version": 2, "vendor": vendor, "game_id": game_id,
        "domain_id": old.get("domain_id", f"{game_id}-pc"), "platform": "windows",
        "channel": old.get("channel", "official"), "version": old.get("version"),
        "version_code": old.get("version_code"), "file_time": old.get("file_time"),
        "artifacts": [], "references": [], "provenance": provenance,
    }
    if not all(_nonempty(record.get(key)) for key in ("domain_id", "channel", "version")):
        raise MigrationError("record identity is incomplete")
    if old.get("is_visible") is not None:
        if not isinstance(old["is_visible"], bool):
            raise MigrationError("record is_visible is invalid")
        record["is_visible"] = old["is_visible"]
    generated: dict[str, dict[str, Any]] = {}
    artifacts = old.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise MigrationError("record artifacts is invalid")
    if game_id == "hkrpg" and any(
        isinstance(item, Mapping)
        and isinstance(item.get("attributes"), Mapping)
        and item["attributes"].get("language") == "zh-tw"
        for item in artifacts
    ):
        exclusions["hkrpg_zh_tw_without_semantics"] += 1
        exclusion_details[(source_path, "hkrpg_zh_tw_without_semantics")] += 1
        return None
    kuro_unpaired_before = exclusions["kuro_route_manifest_unpaired"]
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise MigrationError("record artifact is invalid")
        converted = _artifact(
            item, record=record, vendor=vendor, game_id=game_id, source_repo=source_repo,
            old_paths=manifest_cache, generated_manifests=generated, exclusions=exclusions,
        )
        if converted is not None:
            record["artifacts"].append(converted)
    kuro_unpaired = exclusions["kuro_route_manifest_unpaired"] - kuro_unpaired_before
    if kuro_unpaired:
        exclusion_details[(source_path, "kuro_route_manifest_unpaired")] += kuro_unpaired

    summary = old.get("chunk_summary")
    if summary is not None:
        if not isinstance(summary, Mapping):
            raise MigrationError("chunk_summary is invalid")
        relative = summary.get("path")
        manifest_path = f"data/{vendor}/{game_id}/pc/{relative}" if isinstance(relative, str) else ""
        target = f"chunk-manifests/{record['version']}.json"
        if manifest_path in all_paths and isinstance(summary.get("build_id"), str):
            old_manifest = manifest_cache[manifest_path]
            old_manifest_kind = old_manifest.get("provenance", {}).get("source_kind") if isinstance(old_manifest.get("provenance"), Mapping) else None
            if old_manifest_kind in ALLOWED_PROVENANCE:
                manifest_provenance = _compact_source(old_manifest.get("provenance"))
                document = _chunk_manifest(old_manifest, provenance=manifest_provenance)
                generated[target] = document
                record["references"].append({
                    "kind": "chunk_manifest", "path": target, "build_id": summary["build_id"],
                    "source": manifest_provenance,
                })
            else:
                exclusions["official_api_chunk_reference"] += 1
                exclusion_details[(source_path, "official_api_chunk_reference")] += 1
        else:
            exclusions["chunk_manifest_unpaired"] += 1
    if not record["artifacts"] and not record["references"]:
        exclusions["empty_after_conversion"] += 1
        exclusion_details[(source_path, "empty_after_conversion")] += 1
        return None
    validate_v2_record(record)
    return record, generated


def migrate(source_repo: Path, output_root: Path) -> dict[str, Any]:
    """Migrate the fixed tree and return a compact audit summary."""
    source_repo = Path(source_repo).resolve()
    output_root = Path(output_root)
    _check_source(source_repo)
    paths = _source_paths(source_repo)
    record_paths = sorted(path for path in paths if RECORD_PATH.fullmatch(path) and not path.endswith("/index.json"))
    manifest_paths = sorted(path for path in paths if MANIFEST_PATH.fullmatch(path))
    if (len(record_paths), len(manifest_paths), len([p for p in paths if p.endswith("/pc/index.json")])) != (185, 110, 8):
        raise MigrationError("fixed snapshot inventory changed")
    all_paths = set(paths)
    manifest_cache = {path: _read_json(source_repo, path) for path in manifest_paths}
    exclusions: Counter[str] = Counter()
    exclusion_details: Counter[tuple[str, str]] = Counter()
    written_records: list[dict[str, Any]] = []
    for source_path in record_paths:
        old = _read_json(source_repo, source_path)
        source_kind = old.get("provenance", {}).get("source_kind") if isinstance(old.get("provenance"), Mapping) else None
        if source_kind not in ALLOWED_PROVENANCE:
            exclusions[f"provenance_{source_kind or 'missing'}"] += 1
            exclusion_details[(source_path, f"provenance_{source_kind or 'missing'}")] += 1
            continue
        converted = _record(source_repo, source_path, old, all_paths, manifest_cache, exclusions, exclusion_details)
        if converted is None:
            continue
        record, generated = converted
        target = v2_record_path(record, output_root)
        # A current official collector may already have replaced the same
        # historical version.  Never let a rerun downgrade that record (or
        # its official manifest) back to historical provenance.
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise MigrationError(f"existing output record is unreadable: {target}") from error
            if isinstance(existing, Mapping) and existing.get("provenance", {}).get("source_kind") == "official_sync":
                exclusions["existing_official_record_preserved"] += 1
                continue
        _write_json(target, record)
        written_records.append(record)
        for relative, document in generated.items():
            _write_json(target.parent / relative, document)

    # Recalculate IDs after all records are transformed; this catches any
    # accidental collision introduced by route/part normalization.
    ids: set[str] = set()
    for record in written_records:
        validate_v2_record(record)
        identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
        for item in record["artifacts"]:
            expected = artifact_id(item, identity)
            if item.get("artifact_id") != expected or expected in ids:
                raise MigrationError("artifact identity is not globally unique")
            ids.add(expected)
    counts = Counter((record["vendor"], record["game_id"]) for record in written_records)
    return {
        "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE,
        "source_files": {"records": len(record_paths), "manifests": len(manifest_paths), "indexes": 8},
        "written_records": len(written_records), "written_artifacts": len(ids),
        "written_manifests": sum(1 for record in written_records for ref in record["references"] if ref["kind"] == "chunk_manifest") + sum(
            1 for record in written_records for artifact in record["artifacts"] if "manifest" in artifact
        ),
        "counts": {f"{vendor}/{game}": count for (vendor, game), count in sorted(counts.items())},
        "exclusions": dict(sorted(exclusions.items())),
        "exclusion_details": [
            {"source_path": path, "reason": reason, "count": count}
            for (path, reason), count in sorted(exclusion_details.items())
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    summary = migrate(args.source_repo, args.output_root)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.audit_output:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
