"""Sidecar manifest, Kuro resource-pack, chunk, file-tree, and compare projections."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from backend.catalog_registry import (
    LOCAL_OFFICIAL_HOSTS,
    OFFICIAL_SOPHON_HOSTS,
    PACKAGE_HOSTS_BY_GAME,
)
from backend.fs_safety import SAFE_COMPONENT
from backend.inventory_loader import ApiFault, DomainData, fail
from backend.manifest_readers import ManifestError, normalize_file_time
from backend.probe_policy import stable_id
from backend.schema_v2 import artifact_identity_key


KURO_PACK_MANIFEST = re.compile(r"/packs/([a-z0-9]+)/full\.json")


def kuro_pack_name(artifact: dict[str, Any]) -> str | None:
    manifest = artifact.get("manifest")
    path = manifest.get("path") if isinstance(manifest, dict) else None
    match = KURO_PACK_MANIFEST.search(path) if isinstance(path, str) else None
    return match.group(1) if match and artifact.get("component") == "game" else None


def kuro_pack_index_url(artifact: dict[str, Any]) -> str | None:
    """First official index URL of a pack, for the raw index menu."""
    for candidate in artifact.get("urls") or []:
        url = safe_public_url(candidate.get("url") if isinstance(candidate, dict) else None, allow_query=False)
        if url is not None and urlsplit(url).hostname in LOCAL_OFFICIAL_HOSTS.get("kuro", frozenset()):
            return url
    return None


def kuro_common_pack(record: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Default selection for Kuro resource-pack records: the shared `common` pack."""
    if record.get("vendor") != "kuro":
        return None
    return next((item for item in artifacts if kuro_pack_name(item) == "common"), None)


def build_kuro_resource_packs(
    packs: dict[str, dict[str, Any]],
    selected: dict[str, Any],
    sidecar: dict[str, Any],
) -> dict[str, Any]:
    declared = sidecar.get("resourcePacks") if isinstance(sidecar.get("resourcePacks"), dict) else {}
    by_id = {item.get("artifact_id"): (name, item) for name, item in packs.items()}
    found: dict[str, dict[str, Any]] = {}
    for name, entry in declared.items():
        package = entry.get("package") if isinstance(entry, dict) else None
        hit = by_id.get(package.get("artifact_id")) if isinstance(package, dict) else None
        if hit is not None and hit[0] == name:
            found[name] = hit[1]
    order = ["common", "sd", "hd", "uhd"]
    names = sorted(found, key=lambda name: (order.index(name) if name in order else len(order), name))
    bundles = []
    raw_bundles = sidecar.get("bundles") if isinstance(sidecar.get("bundles"), dict) else {}
    for bundle_name in sorted(
        raw_bundles,
        key=lambda name: (order.index(name.lower()) if name.lower() in order else len(order), name),
    ):
        members = raw_bundles[bundle_name].get("resourcePacks") if isinstance(raw_bundles[bundle_name], dict) else None
        if isinstance(members, list) and members and all(isinstance(m, str) and m in found for m in members):
            bundles.append(
                {
                    "name": bundle_name,
                    "packs": members,
                    "size": sum(found[m].get("size", 0) for m in members),
                }
            )
    return {
        "selected": str(stable_id(selected.get("artifact_id"))),
        "packs": [
            {
                "pack": name,
                "identity": str(stable_id(found[name].get("artifact_id"))),
                "name": found[name].get("name"),
                "size": found[name].get("size", 0),
                "manifest_url": kuro_pack_index_url(found[name]),
            }
            for name in names
        ],
        "bundles": bundles,
    }


def file_artifacts(record: dict[str, Any], delivery: str | None = None) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in record.get("artifacts", [])
        if isinstance(item, dict)
        and item.get("component") == "game"
        and item.get("package_type") in {"full", "segment"}
        and item.get("delivery_mode") in ({delivery} if delivery else {"file_manifest", "archive"})
        and item.get("kind") == "package"
    ]
    manifests = [item for item in candidates if item.get("delivery_mode") == "file_manifest"]
    candidates = manifests or candidates
    full = [item for item in candidates if item.get("package_type") == "full"]
    # Ambiguous complete packages cannot share a reliable list-level timestamp.
    return full if len(full) == 1 else [] if full else candidates


def file_metadata(
    record: dict[str, Any],
    *,
    artifact: dict[str, Any] | None = None,
    document: dict[str, Any] | None = None,
    upstream: Any = None,
    delivery: str | None = None,
) -> dict[str, Any]:
    """Project source timestamps; optional HEAD is only used on actual file-list routes."""
    missing = {"file_time": None, "file_time_source": None}
    selected = [artifact] if artifact is not None else file_artifacts(record, delivery)
    if not selected or record.get("platform") != "windows":
        return missing
    source = "manifest" if selected[0].get("delivery_mode") == "file_manifest" else "package"
    hosts = LOCAL_OFFICIAL_HOSTS.get(record["vendor"], frozenset())
    if record["vendor"] == "mihoyo":
        hosts = PACKAGE_HOSTS_BY_GAME.get(record["game_id"], frozenset())
    segmented = source == "package" and len(selected) > 1 and all(item.get("package_type") == "segment" for item in selected)
    if segmented:
        parts = [item.get("part") for item in selected]
        if any(isinstance(part, bool) or not isinstance(part, int) for part in parts) or sorted(parts) != list(range(1, len(parts) + 1)):
            return missing
    part_times: list[str | None] = []
    read_time = getattr(upstream, "file_modified_at", None)
    dates: set[str] = set()
    urls: list[str] = []
    invalid_evidence = False
    nte = (record.get("vendor"), record.get("game_id")) == ("perfectworld", "nte") and source == "manifest"
    for item in selected:
        item_dates: set[str] = set()
        item_urls: list[str] = []
        for candidate in item.get("urls", []):
            if not isinstance(candidate, dict) or candidate.get("source_kind") not in {"official", "legacy"}:
                continue
            url = safe_public_url(candidate.get("url"), allow_query=not nte)
            if not url or urlsplit(url).hostname not in hosts:
                continue
            if nte:
                parsed = urlsplit(url)
                suffix = f"/Version/Windows/version/{record['version']}/ResList.bin.zip"
                if (
                    item.get("name") != "ResList.bin.zip"
                    or parsed.hostname != "yhcdn1.wmupd.com"
                    or not parsed.path.startswith("/clientRes/")
                    or not parsed.path.endswith(suffix)
                ):
                    continue
            urls.append(url)
            item_urls.append(url)
            current = candidate.get("current")
            if not isinstance(current, dict):
                continue
            if current.get("http_code") not in {200, 206}:
                invalid_evidence = True
                continue
            modified = normalize_file_time(current.get("last_modified"), http_header=True)
            if modified is not None:
                dates.add(modified)
                item_dates.add(modified)
            elif "last_modified" in current:
                invalid_evidence = True
        if segmented:
            # Separate volumes have separate modification clocks; alternate URLs
            # for the same volume must still agree before using its evidence.
            if len(item_dates) > 1:
                return missing
            modified = next(iter(item_dates), None)
            if modified is None and item_urls and callable(read_time):
                modified = read_time(item_urls[0], allowed_hosts=hosts)
            part_times.append(modified)
    if segmented:
        if all(part_times):
            modified = max(value for value in part_times if value is not None)
        else:
            modified = normalize_file_time(record.get("file_time")) if not invalid_evidence else None
        return {"file_time": modified, "file_time_source": "package" if modified is not None else None}
    if len(dates) > 1:
        return missing
    if dates:
        return {"file_time": dates.pop(), "file_time_source": source}
    # Metadata-only reads can recover an absent header, but never download an archive.
    if callable(read_time):
        if urls:
            modified = read_time(urls[0], allowed_hosts=hosts)
            if modified is not None:
                return {"file_time": modified, "file_time_source": source}
        elif source == "manifest":
            provenance = document.get("provenance") if isinstance(document, dict) else None
            artifact_source = selected[0].get("source")
            provenance = (
                provenance
                if isinstance(provenance, dict)
                else artifact_source
                if isinstance(artifact_source, dict)
                else record.get("provenance")
            )
            source_url = provenance.get("source_url") if isinstance(provenance, dict) else None
            document_url = document.get("manifest_url") if isinstance(document, dict) else None
            if (record["vendor"], record["game_id"]) == ("mihoyo", "abc") and document_url == source_url:
                source_url = document_url
            # ABC's already authenticated CBT source is metadata-only: do not expand
            # the Sophon content-download allowlist for this historical inventory.
            provenance_hosts = (
                frozenset({"autopatchcn-beta.bhyyjl.com"})
                if (record["vendor"], record["game_id"]) == ("mihoyo", "abc")
                else hosts
            )
            try:
                parsed = urlsplit(source_url) if isinstance(source_url, str) else None
                recognized = (record["vendor"], record["game_id"]) == ("mihoyo", "abc") or (
                    record["vendor"] == "kuro" and parsed is not None and parsed.path.endswith("/indexFile.json")
                )
                if recognized and parsed is not None and parsed.hostname in provenance_hosts:
                    modified = read_time(source_url, allowed_hosts=provenance_hosts)
                    return {"file_time": modified, "file_time_source": "manifest" if modified is not None else None}
            except (ValueError, ManifestError):
                pass
    # Existing canonical file_time is usable for historical package records. NTE
    # specifically promises an authenticated ResList date, so retain its strictness.
    is_complete_game = all(
        item.get("component") == "game" and item.get("package_type") in {"full", "segment"} for item in selected
    )
    modified = (
        normalize_file_time(record.get("file_time"))
        if is_complete_game and not nte and not invalid_evidence
        else None
    )
    return {"file_time": modified, "file_time_source": source if modified is not None else None}


def nte_manifest_modified_at(record: dict[str, Any]) -> str | None:
    if (record.get("vendor"), record.get("game_id"), record.get("platform")) != ("perfectworld", "nte", "windows"):
        return None
    return file_metadata(record, delivery="file_manifest")["file_time"]


def compare_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    public = public_artifact({}, artifact)
    return {
        key: public[key]
        for key in ("name", "part", "kind", "size", "checksum_type", "checksum_value", "attributes")
    }


def compare_file(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["path"].rsplit("/", 1)[-1],
        "part": 1,
        "kind": "file",
        "size": item["size"],
        "checksum_type": "md5",
        "checksum_value": item["md5"],
        "attributes": {"path": item["path"]},
    }


def artifact_compare_identity(artifact: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    key = artifact_identity_key(
        artifact["name"],
        artifact["component"],
        part=artifact.get("part"),
        language=artifact.get("language"),
        route_from=artifact.get("route_from"),
        route_to=artifact.get("route_to"),
    )
    value = json.loads(key)
    if not isinstance(value, dict) or any(
        not isinstance(item, (str, int, bool, type(None))) for item in value.values()
    ):
        fail(500, "identity_projection_failed", "资源身份无法公开")
    return key, value


def public_chunk_document(domain_id: str, document: dict[str, Any]) -> dict[str, Any]:
    manifests = []
    for entry in document["manifests"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("manifest"), dict):
            fail(500, "corrupt_manifest", "Chunk Manifest 数据损坏")
        manifest = entry["manifest"]
        public: dict[str, Any] = {
            "manifest_id": manifest.get("id"),
            "manifest": {
                key: manifest.get(key)
                for key in ("id", "checksum", "compressed_size", "uncompressed_size")
            },
            "component": entry.get("component"),
            "language": entry.get("language"),
            "matching_field": entry.get("matching_field"),
            "stats": {
                key: (entry.get("stats") or {}).get(key, 0)
                for key in ("compressed_size", "uncompressed_size", "file_count", "chunk_count")
            },
        }
        if isinstance(entry.get("category"), dict):
            public["category"] = {key: entry["category"].get(key) for key in ("id", "name")}
        if isinstance(entry.get("deduplicated_stats"), dict):
            public["deduplicated_stats"] = {
                key: entry["deduplicated_stats"].get(key, 0)
                for key in ("compressed_size", "uncompressed_size", "file_count", "chunk_count")
            }
        for field in ("manifest_download", "chunk_download"):
            recipe = entry.get(field)
            if isinstance(recipe, dict) and "password" not in recipe:
                prefix = safe_public_url(recipe.get("url_prefix"), allow_query=False)
                suffix = recipe.get("url_suffix", "")
                sensitive_suffix = bool(
                    re.search(
                        r"(?i)(?:^|[?&])(token|password|passwd|secret|auth(?:_key)?|signature|sign|key)=",
                        suffix,
                    )
                )
                if (
                    prefix
                    and urlsplit(prefix).hostname in OFFICIAL_SOPHON_HOSTS
                    and isinstance(suffix, str)
                    and (not suffix or suffix.startswith("?"))
                    and not sensitive_suffix
                ):
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
        "provenance": public_provenance(document.get("provenance")),
    }


def chunk_summary(domain_id: str, document: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    entries = [item for item in document["manifests"] if isinstance(item, dict)]
    stats = [
        item.get("deduplicated_stats") if isinstance(item.get("deduplicated_stats"), dict) else item.get("stats", {})
        for item in entries
    ]
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
        "imported_at": (public_provenance(document.get("provenance")).get("imported_at") or record.get("file_time") or ""),
    }


def tree_artifact(source_id: str, item: dict[str, Any]) -> dict[str, Any]:
    url = safe_public_url(item.get("download_url"))
    return {
        "id": stable_id(source_id, item["path"]),
        "kind": "file",
        "name": item["path"],
        "part": 1,
        "size": item.get("size", 0),
        "checksum_type": "md5" if item.get("md5") else None,
        "checksum_value": item.get("md5"),
        "attributes": {},
        "urls": (
            [{"id": stable_id(source_id, item["path"], url), "url": url, "priority": 0, "source_kind": "official", "evidence_status": "unverified", "current": None}]
            if url else []
        ),
    }


def validate_chunk_document(
    domain: DomainData,
    record: dict[str, Any],
    load_document: Callable[[DomainData, dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    references = [item for item in record.get("references", []) if isinstance(item, dict) and item.get("kind") == "chunk_manifest"]
    if not references:
        fail(404, "manifest_not_found", "Chunk Manifest 不存在")
    if len(references) != 1 or not isinstance(references[0].get("path"), str):
        fail(500, "corrupt_reference", "Chunk Manifest 引用损坏")
    reference = references[0]
    document = load_document(domain, record, reference["path"])
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
            prefix = safe_public_url(recipe.get("url_prefix"), allow_query=False)
            if prefix is None or urlsplit(prefix).hostname not in OFFICIAL_SOPHON_HOSTS:
                fail(500, "corrupt_manifest", "Chunk Manifest recipe 不安全")
    return document


def resolve_package_document(
    domain: DomainData,
    record: dict[str, Any],
    identity: str,
    load_document: Callable[[DomainData, dict[str, Any], str], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if not isinstance(identity, str) or SAFE_COMPONENT.fullmatch(identity) is None:
        fail(400, "bad_identity", "identity 无效")
    candidates = [
        item for item in record.get("artifacts", [])
        if isinstance(item, dict) and item.get("delivery_mode") == "file_manifest" and isinstance(item.get("manifest"), dict)
    ]
    if identity == "game":
        selected = kuro_common_pack(record, candidates) or next(
            (item for item in candidates if item.get("component") == "game" and item.get("package_type") == "full"),
            next((item for item in candidates if item.get("component") == "game"), None),
        )
    else:
        selected = next(
            (item for item in candidates if identity in {item.get("artifact_id"), item.get("name"), str(stable_id(item.get("artifact_id")))}),
            None,
        )
    if selected is None:
        fail(404, "manifest_not_found", "文件 Manifest 不存在")
    relative = selected["manifest"].get("path")
    if not isinstance(relative, str):
        fail(500, "corrupt_manifest", "文件 Manifest 引用损坏")
    document = load_document(domain, record, relative)
    raw_urls = selected["manifest"].get("base_urls")
    if raw_urls is None:
        raw_urls = []
    elif not isinstance(raw_urls, list):
        fail(500, "corrupt_manifest", "文件 Manifest base URL 损坏")
    base_urls: list[str] = []
    allowed_hosts = LOCAL_OFFICIAL_HOSTS.get(record["vendor"], frozenset())
    for item in raw_urls:
        url = safe_public_url(item.get("url") if isinstance(item, dict) else None, allow_query=False)
        if url is None or urlsplit(url).hostname not in allowed_hosts:
            fail(500, "corrupt_manifest", "文件 Manifest base URL 不安全")
        base_urls.append(url)
    return selected, document, base_urls


def resolve_kuro_resource_packs(
    domain: DomainData,
    record: dict[str, Any],
    selected: dict[str, Any],
    load_document: Callable[[DomainData, dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any] | None:
    packs = (
        {name: item for item in record.get("artifacts", []) if isinstance(item, dict) and (name := kuro_pack_name(item)) is not None}
        if record.get("vendor") == "kuro" else {}
    )
    if not packs:
        return None
    try:
        sidecar = load_document(domain, record, f"manifests/{record['version']}/resource-packs.json")
    except ApiFault:
        return None
    return build_kuro_resource_packs(packs, selected, sidecar)


def compare_artifact_rows(
    before_record: dict[str, Any], after_record: dict[str, Any], kind: str | None,
) -> list[dict[str, Any]]:
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}
    identities: dict[str, dict[str, Any]] = {}
    for record, target in ((before_record, before), (after_record, after)):
        for artifact in record["artifacts"]:
            if kind is not None and artifact["kind"] != kind:
                continue
            key, identity = artifact_compare_identity(artifact)
            target[key] = artifact
            identities[key] = identity
    rows = []
    for key in sorted(set(before) | set(after)):
        old = compare_artifact(before[key]) if key in before else None
        new = compare_artifact(after[key]) if key in after else None
        row_change = "added" if old is None else "removed" if new is None else "changed" if old != new else None
        if row_change:
            rows.append({"change": row_change, "identity": identities[key], "before": old, "after": new})
    return rows


def record_artifact_tree_entries(
    record: dict[str, Any],
    *,
    kind: str,
    prefix: str,
    availability_state: str | None,
    q: str | None,
) -> list[dict[str, Any]]:
    indices = scheduled_probe_indices(record)
    public = [
        public_artifact(record, item, index, indices)
        for index, item in enumerate(record["artifacts"])
        if kind == "all" or item["kind"] == kind
    ]
    if availability_state:
        public = [item for item in public if artifact_state(item) == availability_state]
    if q:
        public = [item for item in public if q.casefold() in item["name"].casefold()]
    direct = [
        item
        for item in public
        if (not prefix and "/" not in item["name"])
        or (prefix and item["name"].startswith(prefix + "/") and "/" not in item["name"][len(prefix) + 1 :])
    ]
    direct.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    if kind != "resource":
        return direct
    folder_stats: dict[str, dict[str, Any]] = {}
    for item in public:
        relative = (
            item["name"]
            if not prefix
            else item["name"][len(prefix) + 1 :]
            if item["name"].startswith(prefix + "/")
            else ""
        )
        if not relative or "/" not in relative:
            continue
        segment = relative.split("/", 1)[0]
        path = f"{prefix}/{segment}" if prefix else segment
        folder = folder_stats.setdefault(path, {"name": segment, "path": path, "artifact_count": 0, "total_size": 0})
        folder["artifact_count"] += 1
        folder["total_size"] += item["size"]
    return sorted(folder_stats.values(), key=lambda item: item["name"].casefold()) + direct


from backend.public_projection import (  # noqa: E402
    artifact_availability,
    artifact_state,
    public_artifact,
    public_provenance,
    safe_public_url,
    scheduled_probe_indices,
)

__all__ = [
    "KURO_PACK_MANIFEST",
    "artifact_availability",
    "artifact_compare_identity",
    "build_kuro_resource_packs",
    "chunk_summary",
    "compare_artifact",
    "compare_artifact_rows",
    "compare_file",
    "file_artifacts",
    "file_metadata",
    "kuro_common_pack",
    "kuro_pack_index_url",
    "kuro_pack_name",
    "nte_manifest_modified_at",
    "public_chunk_document",
    "record_artifact_tree_entries",
    "resolve_kuro_resource_packs",
    "resolve_package_document",
    "tree_artifact",
    "validate_chunk_document",
]
