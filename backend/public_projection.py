"""Public HTTP projection mappers over validated canonical schema-v2 records."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from backend.admin_probe import candidates as scheduled_probe_candidates
from backend.catalog_registry import (
    AVAILABILITY_STATES,
    LOCAL_OFFICIAL_HOSTS,
    OFFICIAL_SOPHON_HOSTS,
    PACKAGE_HOSTS_BY_GAME,
)
from backend.fs_safety import SAFE_COMPONENT
from backend.indexes import version_key
from backend.inventory_loader import ApiFault, DomainData, fail
from backend.manifest_readers import ManifestError, normalize_file_time
from backend.probe_policy import PROBE_EVIDENCE_TTL, parse_probe_checked_at, stable_id
from backend.schema_v2 import artifact_identity_key
from url_adapters.service import DISCOVERERS, PC_DISCOVERERS


KURO_PACK_MANIFEST = re.compile(r"/packs/([a-z0-9]+)/full\.json")


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


def kuro_pack_name(artifact: dict[str, Any]) -> str | None:
    manifest = artifact.get("manifest")
    path = manifest.get("path") if isinstance(manifest, dict) else None
    match = KURO_PACK_MANIFEST.search(path) if isinstance(path, str) else None
    return match.group(1) if match and artifact.get("component") == "game" else None


_kuro_pack_name = kuro_pack_name


def kuro_pack_index_url(artifact: dict[str, Any]) -> str | None:
    """First official index URL of a pack, for the raw index menu."""
    for candidate in artifact.get("urls") or []:
        url = safe_public_url(candidate.get("url") if isinstance(candidate, dict) else None, allow_query=False)
        if url is not None and urlsplit(url).hostname in LOCAL_OFFICIAL_HOSTS.get("kuro", frozenset()):
            return url
    return None


_kuro_pack_index_url = kuro_pack_index_url


def kuro_common_pack(record: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Default selection for Kuro resource-pack records: the shared `common` pack."""
    if record.get("vendor") != "kuro":
        return None
    return next((item for item in artifacts if kuro_pack_name(item) == "common"), None)


_kuro_common_pack = kuro_common_pack


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


_file_artifacts = file_artifacts


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


_file_metadata = file_metadata


def nte_manifest_modified_at(record: dict[str, Any]) -> str | None:
    if (record.get("vendor"), record.get("game_id"), record.get("platform")) != ("perfectworld", "nte", "windows"):
        return None
    return file_metadata(record, delivery="file_manifest")["file_time"]


_nte_manifest_modified_at = nte_manifest_modified_at


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


def compare_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    public = public_artifact({}, artifact)
    return {
        key: public[key]
        for key in ("name", "part", "kind", "size", "checksum_type", "checksum_value", "attributes")
    }


_compare_artifact = compare_artifact


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
