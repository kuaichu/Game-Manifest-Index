"""Public HTTP projection mappers over validated canonical schema-v2 records."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from backend.admin_probe import candidates as scheduled_probe_candidates
from backend.catalog_registry import AVAILABILITY_STATES
from backend.indexes import version_key
from backend.inventory_loader import DomainData, fail
from backend.probe_policy import PROBE_EVIDENCE_TTL, parse_probe_checked_at, stable_id
from url_adapters.service import DISCOVERERS, PC_DISCOVERERS


def safe_public_url(value: Any, *, allow_query: bool = True, allow_http: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in ({"http", "https"} if allow_http else {"https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 80 if parsed.scheme == "http" else 443)
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        return None
    return value


_safe_public_url = safe_public_url


def public_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        key: value[key]
        for key in ("source_kind", "source_name", "source_repo", "source_commit", "imported_at")
        if isinstance(value.get(key), str)
    }
    source_url = safe_public_url(value.get("source_url"), allow_query=False)
    if source_url:
        result["source_url"] = source_url
    return result


_public_provenance = public_provenance


def primary_artifact(record: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = [item for item in record.get("artifacts", []) if isinstance(item, dict)]
    if record["platform"] == "android":
        selected = next((item for item in artifacts if item.get("kind") == "apk"), None)
    else:
        selected = kuro_common_pack(record, artifacts) or next(
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


_primary_artifact = primary_artifact


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_utc_now = utc_now


def _current_utc_now() -> datetime:
    contract_mod = sys.modules.get("backend.api_contract")
    override = getattr(contract_mod, "_utc_now", None) if contract_mod is not None else None
    if callable(override) and override is not utc_now:
        return override()
    return _utc_now()


def public_current(current: Any, *, rotation_eligible: bool = True) -> dict[str, Any] | None:
    if not isinstance(current, dict):
        return None
    state = current.get("state") if current.get("state") in AVAILABILITY_STATES else "unknown"
    checked_at = current.get("checked_at") if isinstance(current.get("checked_at"), str) else None
    http_code = (
        current.get("http_code")
        if isinstance(current.get("http_code"), int) and not isinstance(current.get("http_code"), bool)
        else None
    )
    if http_code == 403:
        state = "unavailable"
    probe = parse_probe_checked_at(current)
    now = _current_utc_now()
    evidence_status = "unverified"
    source_kind = "canonical_current"
    expires_at = None
    # A future checked_at cannot prove a completed probe; treat it as unverified.
    if probe is not None and probe[1] <= now:
        age = now - probe[1]
        if state == "available" and rotation_eligible:
            evidence_status = "verified" if age < PROBE_EVIDENCE_TTL else "stale"
        elif state == "available" and age >= PROBE_EVIDENCE_TTL:
            # URLs outside the scheduled rotation cannot refresh this evidence;
            # keep them non-actionable without presenting a stale timer badge.
            evidence_status = "unverified"
        else:
            # A confirmed unavailable/unknown result is terminal for the
            # scheduled rotation, so keep its real state visible after TTL.
            evidence_status = "verified"
        source_kind = "live_probe"
        if state == "available" and rotation_eligible:
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


_public_current = public_current


def scheduled_probe_indices(record: dict[str, Any]) -> set[tuple[int, int]] | None:
    if not record:
        return None
    if record.get("game_id") not in DISCOVERERS and record.get("game_id") not in PC_DISCOVERERS:
        return set()
    return {
        (artifact_index, url_index)
        for artifact_index, url_index, _artifact, candidate in scheduled_probe_candidates(record)
        if candidate.get("source_kind") in {"official", "legacy"}
    }


_scheduled_probe_indices = scheduled_probe_indices


def artifact_state(artifact: dict[str, Any]) -> str:
    derived = artifact.get("availability")
    if isinstance(derived, dict) and derived.get("state") in AVAILABILITY_STATES:
        return derived["state"]
    states = []
    for url in artifact["urls"]:
        if not isinstance(url, dict) or not isinstance(url.get("current"), dict):
            continue
        current = url["current"]
        evidence_status = url.get("evidence_status") or current.get("evidence_status")
        if evidence_status not in {"verified", "stale", "unverified"}:
            current = public_current(current)
            if current is None:
                continue
            evidence_status = current["evidence_status"]
        if evidence_status != "verified" and not (
            current.get("state") == "unavailable" and current.get("reason") == "HTTP 403"
        ):
            continue
        state = current.get("state")
        if state in AVAILABILITY_STATES:
            states.append(state)
    if "available" in states:
        return "available"
    if states and all(state == "unavailable" for state in states):
        return "unavailable"
    return "unknown"


_artifact_state = artifact_state


def artifact_availability(
    artifact: dict[str, Any],
    *,
    scheduled_indices: set[tuple[int, int]] | None = None,
    artifact_index: int = 0,
) -> dict[str, str]:
    candidates = [
        item
        for item in artifact.get("urls", [])
        if isinstance(item, dict) and safe_public_url(item.get("url"), allow_http=True)
    ]
    currents = [
        public_current(
            item.get("current"),
            rotation_eligible=scheduled_indices is None or (artifact_index, index) in scheduled_indices,
        )
        for index, item in enumerate(artifact.get("urls", []))
        if isinstance(item, dict) and safe_public_url(item.get("url"), allow_http=True)
    ]
    state = artifact_state({"urls": [{"current": current} for current in currents]})
    if state != "unknown":
        return {"state": state, "reason": ""}
    if not candidates:
        return {"state": state, "reason": "没有可探活的下载 URL"}
    has_fresh_unknown = any(
        current and current["evidence_status"] == "verified" and current["state"] == "unknown"
        for current in currents
    )
    reasons = []
    for candidate, current in zip(candidates, currents):
        if has_fresh_unknown and (current is None or current["evidence_status"] != "verified"):
            continue
        if current is None or current["evidence_status"] == "unverified":
            reason = "尚无有效探活记录"
        elif current["evidence_status"] == "stale":
            reason = "探活证据已过期"
        elif current["state"] != "unknown":
            continue
        else:
            code = candidate["current"].get("http_code")
            if code == 401:
                reason = f"上游拒绝访问（HTTP {code}）"
            elif code in {200, 206}:
                reason = f"已响应，但未取得有效文件证据（HTTP {code}）"
            elif isinstance(code, int) and not isinstance(code, bool):
                reason = f"上游响应无法确认资源状态（HTTP {code}）"
            else:
                reason = "未取得有效文件证据"
        if reason not in reasons:
            reasons.append(reason)
    return {"state": state, "reason": "；".join(reasons) or "未取得有效文件证据"}


_artifact_availability = artifact_availability


def public_artifact(
    record: dict[str, Any],
    artifact: dict[str, Any],
    artifact_index: int = 0,
    scheduled_indices: set[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    artifact_id = artifact["artifact_id"]
    checksum = artifact.get("checksum") if isinstance(artifact.get("checksum"), dict) else {}
    checksum_type = next((kind for kind in ("md5", "sha256", "crc64") if isinstance(checksum.get(kind), str)), None)
    attributes = {
        key: artifact[key]
        for key in (
            "component",
            "package_type",
            "delivery_mode",
            "language",
            "route_from",
            "route_to",
            "decompressed_size",
        )
        if artifact.get(key) is not None and isinstance(artifact.get(key), (str, int, bool))
    }
    if scheduled_indices is None:
        scheduled_indices = scheduled_probe_indices(record)
    urls = []
    for index, candidate in enumerate(artifact.get("urls", [])):
        if not isinstance(candidate, dict):
            continue
        url = safe_public_url(candidate.get("url"))
        if url is None:
            continue
        source_kind = candidate.get("source_kind") if isinstance(candidate.get("source_kind"), str) else "unknown"
        rotation_eligible = scheduled_indices is None or (artifact_index, index) in scheduled_indices
        current = public_current(candidate.get("current"), rotation_eligible=rotation_eligible)
        urls.append(
            {
                "id": stable_id(artifact_id, index, url),
                "url": url,
                "priority": candidate.get("priority") if isinstance(candidate.get("priority"), int) else index,
                "source_kind": source_kind,
                **({"provider": candidate["provider"]} if isinstance(candidate.get("provider"), str) else {}),
                "evidence_status": current["evidence_status"] if current is not None else "unverified",
                "current": current,
            }
        )
    return {
        "id": stable_id(artifact_id),
        "kind": artifact["kind"],
        "name": artifact["name"],
        "part": artifact.get("part") if isinstance(artifact.get("part"), int) else 1,
        "size": artifact.get("size") if isinstance(artifact.get("size"), int) else 0,
        "checksum_type": checksum_type,
        "checksum_value": checksum.get(checksum_type) if checksum_type else None,
        "attributes": attributes,
        "urls": urls,
        # Link publication remains HTTPS-only; probe evidence for legacy HTTP
        # candidates still belongs to this artifact and must not be discarded.
        "availability": artifact_availability(
            artifact, scheduled_indices=scheduled_indices, artifact_index=artifact_index,
        ),
    }


_public_artifact = public_artifact


def public_version(record: dict[str, Any]) -> dict[str, Any]:
    artifact = primary_artifact(record)
    # Some audited PC history records contain only a canonical chunk-manifest
    # reference. The legacy public VersionRecord shape still requires flat
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
    candidate_index, candidate = next(
        (
            (index, item)
            for index, item in enumerate(artifact.get("urls", []))
            if isinstance(item, dict) and safe_public_url(item.get("url"))
        ),
        (None, {}),
    )
    current = (
        candidate.get("current")
        if isinstance(candidate, dict) and isinstance(candidate.get("current"), dict)
        else {}
    )
    checksum = artifact.get("checksum") if isinstance(artifact.get("checksum"), dict) else {}
    artifact_index = next(index for index, item in enumerate(record["artifacts"]) if item is artifact)
    scheduled_indices = scheduled_probe_indices(record)
    projected_current = public_current(
        current,
        rotation_eligible=scheduled_indices is None or (artifact_index, candidate_index) in scheduled_indices,
    )
    state = artifact_state({"urls": [{"current": projected_current}]})
    return {
        "vendor": record["vendor"],
        "game_id": record["game_id"],
        "platform": record["platform"],
        "channel": record["channel"],
        "version": record["version"],
        "version_code": (
            record.get("version_code")
            if isinstance(record.get("version_code"), int) and not isinstance(record.get("version_code"), bool)
            else None
        ),
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


_public_version = public_version


def version_summary(record: dict[str, Any]) -> dict[str, Any]:
    scheduled_indices = scheduled_probe_indices(record)
    artifacts = [
        public_artifact(record, item, index, scheduled_indices)
        for index, item in enumerate(record.get("artifacts", []))
        if isinstance(item, dict)
    ]
    has_chunk = any(
        isinstance(reference, dict) and reference.get("kind") == "chunk_manifest"
        for reference in record.get("references", [])
    )
    kinds: dict[str, dict[str, Any]] = {}
    states = {state: 0 for state in AVAILABILITY_STATES}
    reasons: dict[str, int] = {}
    for artifact in artifacts:
        state = artifact_state(artifact)
        states[state] += 1
        bucket = kinds.setdefault(
            artifact["kind"],
            {
                "count": 0,
                "size": 0,
                "availability_states": {name: 0 for name in AVAILABILITY_STATES},
                "availability_reasons": {},
            },
        )
        bucket["count"] += 1
        bucket["size"] += artifact["size"]
        bucket["availability_states"][state] += 1
        if state == "unknown":
            reason = artifact["availability"]["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
            bucket["availability_reasons"][reason] = bucket["availability_reasons"].get(reason, 0) + 1
    attributes = {"has_chunk": True} if has_chunk else {}
    modified_at = nte_manifest_modified_at(record)
    if modified_at is not None:
        attributes["manifest_modified_at"] = modified_at
    # The default files source is Sophon when present; archive dates belong to the
    # explicit package source, not to the selected chunk manifest.
    metadata = file_metadata(record) if not has_chunk else {"file_time": None}
    if metadata["file_time"] is not None:
        attributes["file_modified_at"] = metadata["file_time"]
        attributes["file_time_source"] = metadata["file_time_source"]
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
        "availability_reasons": reasons,
        "attributes": attributes,
        "provenance": public_provenance(record.get("provenance")),
        "is_visible": True,
    }


_summary = version_summary


def domain_adapter(domain: DomainData) -> str:
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


_domain_adapter = domain_adapter


def domain_projection(domain: DomainData, sort_order: int) -> dict[str, Any]:
    artifacts = [item for record in domain.records for item in record.get("artifacts", []) if isinstance(item, dict)]
    kinds = {item.get("kind") for item in artifacts}
    has_chunk = any(
        any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", []))
        for record in domain.records
    )
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
            key
            for item in artifacts
            for key in (item.get("checksum") or {})
            if key in {"md5", "sha256", "crc64"}
        }
    )
    adapter = domain_adapter(domain)
    metadata_only_availability = domain.vendor == "manjuu" and domain.game_id == "azurpromilia"
    return {
        "id": domain.domain_id,
        "game_id": domain.game_id,
        "kind": (
            "apk"
            if domain.platform == "android"
            else "resources"
            if kinds == {"resource"}
            else "files"
            if has_files
            else "packages"
        ),
        "platform": domain.platform,
        "capabilities": capabilities,
        "capability_contract": {
            "version_fields": {"observed_at": "supported", "source_released_at": "unsupported"},
            "artifact_fields": {"size": "supported", "checksum": "supported", "availability": "supported"},
            "url_source_kinds": sorted(
                {
                    candidate.get("source_kind")
                    for item in artifacts
                    for candidate in item.get("urls", [])
                    if isinstance(candidate, dict) and isinstance(candidate.get("source_kind"), str)
                }
            ),
            "checksum_algorithms": checksums,
            # Azur Promilia is a checked-in launcher archive without a probe
            # adapter. Its official URLs remain directly usable from metadata;
            # other domains keep the default probe-gated contract.
            "availability_source_kinds": ["metadata_inference"] if metadata_only_availability else [],
            "url_providers": providers,
            "features": {
                "compare": "supported" if len(domain.records) > 1 else "unsupported",
                "chunks": "supported" if has_chunk else "unsupported",
            },
            "actions": {"download": "conditional"},
            "live_probe": False,
        },
        "adapter": adapter,
        "version_count": len(domain.records),
        "latest_version": max((record["version"] for record in domain.records), key=version_key),
        "source_current_version": None,
        "catalog_version_count": len(domain.records),
        "is_enabled": True,
        "sort_order": sort_order,
    }


_domain_projection = domain_projection

from backend.manifest_projection import (  # noqa: E402
    KURO_PACK_MANIFEST,
    artifact_compare_identity,
    build_kuro_resource_packs,
    chunk_summary,
    compare_artifact,
    compare_artifact_rows,
    compare_file,
    file_artifacts,
    file_metadata,
    kuro_common_pack,
    kuro_pack_index_url,
    kuro_pack_name,
    nte_manifest_modified_at,
    public_chunk_document,
    record_artifact_tree_entries,
    resolve_kuro_resource_packs,
    resolve_package_document,
    tree_artifact,
    validate_chunk_document,
)

_kuro_pack_name = kuro_pack_name
_kuro_pack_index_url = kuro_pack_index_url
_kuro_common_pack = kuro_common_pack
_file_artifacts = file_artifacts
_file_metadata = file_metadata
_nte_manifest_modified_at = nte_manifest_modified_at
_compare_artifact = compare_artifact

__all__ = [
    "KURO_PACK_MANIFEST", "artifact_availability", "artifact_compare_identity", "artifact_state",
    "build_kuro_resource_packs", "chunk_summary", "compare_artifact", "compare_artifact_rows",
    "compare_file", "domain_adapter", "domain_projection", "file_artifacts", "file_metadata",
    "kuro_common_pack", "kuro_pack_index_url", "kuro_pack_name", "nte_manifest_modified_at",
    "primary_artifact", "public_artifact", "public_chunk_document", "public_current",
    "public_provenance", "public_version", "record_artifact_tree_entries", "resolve_kuro_resource_packs",
    "resolve_package_document", "safe_public_url", "scheduled_probe_indices", "tree_artifact",
    "utc_now", "validate_chunk_document", "version_summary",
]
