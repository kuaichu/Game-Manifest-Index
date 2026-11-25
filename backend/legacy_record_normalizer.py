"""V4 legacy record normalization into canonical schema v2."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Final


_ATTRIBUTE_PROMOTIONS: Final = {
    "kind",
    "component",
    "package_type",
    "delivery_mode",
    "name",
    "part",
    "language",
    "route_from",
    "route_to",
    "size",
    "decompressed_size",
    "checksum",
    "manifest",
    "source",
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _legacy_provenance(value: Any, diagnostics: list[Diagnostic]) -> Any:
    if not isinstance(value, Mapping):
        diagnostics.append(Diagnostic("$.provenance", "must be an object"))
        return value
    output: dict[str, Any] = {}
    aliases = {"source_project": "source_name"}
    for key, item in value.items():
        target = aliases.get(key, key)
        if target not in PROVENANCE_FIELDS:
            diagnostics.append(Diagnostic(f"$.provenance.{key}", "cannot be safely represented in schema v2"))
        elif target in output and output[target] != item:
            diagnostics.append(Diagnostic(f"$.provenance.{key}", f"conflicts with {target}"))
        else:
            output[target] = copy.deepcopy(item)
    return output


def _legacy_current(value: Any, path: str, diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        diagnostics.append(Diagnostic(path, "must be an object"))
        return None
    output: dict[str, Any] = {}
    aliases = {"last_checked_at": "checked_at"}
    for key, item in value.items():
        target = aliases.get(key, key)
        if target in LEGACY_CURRENT_FIELDS or target not in CURRENT_FIELDS:
            diagnostics.append(Diagnostic(f"{path}.{key}", "cannot be safely represented in schema v2 current"))
        elif target in output and output[target] != item:
            diagnostics.append(Diagnostic(f"{path}.{key}", f"conflicts with {target}"))
        else:
            output[target] = copy.deepcopy(item)
    return output


def _legacy_urls(value: Any, vendor: Any, path: str, diagnostics: list[Diagnostic]) -> list[dict[str, Any]]:
    if value is None:
        diagnostics.append(Diagnostic(path, "must be an array"))
        return []
    if not isinstance(value, list):
        diagnostics.append(Diagnostic(path, "must be an array"))
        return []
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(candidate, Mapping):
            diagnostics.append(Diagnostic(item_path, "must be an object"))
            continue
        item: dict[str, Any] = {}
        for key, raw in candidate.items():
            if key in URL_FIELDS:
                if key == "current":
                    if raw is not None:
                        current = _legacy_current(raw, item_path + ".current", diagnostics)
                        if current is not None:
                            item[key] = current
                else:
                    item[key] = copy.deepcopy(raw)
            else:
                diagnostics.append(Diagnostic(f"{item_path}.{key}", "unknown or legacy URL-candidate field"))
        item.setdefault("provider", vendor if _non_empty_string(vendor) else "legacy")
        item.setdefault("source_kind", "legacy")
        item.setdefault("priority", 0)
        output.append(item)
    return output


def _legacy_base_urls(value: Any, vendor: Any, path: str, diagnostics: list[Diagnostic]) -> list[dict[str, Any]]:
    """Convert legacy string/object base URLs to canonical candidates."""

    if not isinstance(value, list):
        diagnostics.append(Diagnostic(path, "must be an array"))
        return []
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(value):
        item_path = f"{path}[{index}]"
        if isinstance(candidate, str):
            item: dict[str, Any] = {"url": copy.deepcopy(candidate)}
        elif isinstance(candidate, Mapping):
            item = {}
            for key, raw in candidate.items():
                if key in BASE_URL_FIELDS:
                    item[key] = copy.deepcopy(raw)
                else:
                    diagnostics.append(Diagnostic(f"{item_path}.{key}", "unknown or legacy manifest base-url field"))
        else:
            diagnostics.append(Diagnostic(item_path, "must be a URL string or object"))
            continue
        item.setdefault("provider", vendor if _non_empty_string(vendor) else "legacy")
        item.setdefault("source_kind", "legacy")
        item.setdefault("priority", 0)
        output.append(item)
    return output


def _promote_manifest(
    artifact: dict[str, Any],
    attributes: Mapping[str, Any],
    vendor: Any,
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    raw_manifest = artifact.get("manifest") if "manifest" in artifact else None
    if raw_manifest is not None and not isinstance(raw_manifest, Mapping):
        diagnostics.append(Diagnostic(path + ".manifest", "must be an object"))
        return
    manifest = copy.deepcopy(dict(raw_manifest)) if isinstance(raw_manifest, Mapping) else {}

    if "base_urls" in manifest:
        manifest["base_urls"] = _legacy_base_urls(
            manifest["base_urls"], vendor, path + ".manifest.base_urls", diagnostics
        )

    for source in ("local_manifest", "manifest_path"):
        if source not in attributes:
            continue
        if "path" in manifest and manifest["path"] != attributes[source]:
            diagnostics.append(Diagnostic(f"{path}.attributes.{source}", "conflicts with manifest.path"))
        else:
            manifest["path"] = copy.deepcopy(attributes[source])

    for source in ("base_urls", "manifest_urls"):
        if source not in attributes:
            continue
        base_urls = _legacy_base_urls(
            attributes[source], vendor, f"{path}.attributes.{source}", diagnostics
        )
        if "base_urls" in manifest and manifest["base_urls"] != base_urls:
            diagnostics.append(Diagnostic(f"{path}.attributes.{source}", "conflicts with manifest.base_urls"))
        else:
            manifest["base_urls"] = base_urls
    if manifest:
        artifact["manifest"] = manifest


def _legacy_artifacts(
    value: Any,
    vendor: Any,
    path: str,
    record_identity: Mapping[str, Any],
    diagnostics: list[Diagnostic],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        diagnostics.append(Diagnostic(path, "must be an array"))
        return []
    output: list[dict[str, Any]] = []
    for index, legacy in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(legacy, Mapping):
            diagnostics.append(Diagnostic(item_path, "must be an object"))
            continue
        artifact: dict[str, Any] = {}
        for key, raw in legacy.items():
            if key in ARTIFACT_FIELDS and key != "artifact_id":
                if key == "part" and raw is None:
                    continue
                artifact[key] = copy.deepcopy(raw)
            elif key == "artifact_id":
                artifact[key] = copy.deepcopy(raw)
            elif key == "attributes":
                continue
            elif key in {"checksum_type", "checksum_value"}:
                continue
            elif key in {"base_urls", "manifest_urls"}:
                continue
            elif key in LEGACY_ARTIFACT_FIELDS:
                diagnostics.append(Diagnostic(f"{item_path}.{key}", "cannot be safely represented in schema v2"))
            else:
                diagnostics.append(Diagnostic(f"{item_path}.{key}", "unknown or legacy artifact field"))

        attributes = legacy.get("attributes", {})
        if attributes is None:
            attributes = {}
        if not isinstance(attributes, Mapping):
            diagnostics.append(Diagnostic(item_path + ".attributes", "must be an object"))
            attributes = {}
        manifest_attributes = dict(attributes)
        for key in ("base_urls", "manifest_urls"):
            if key not in legacy:
                continue
            if key in manifest_attributes and manifest_attributes[key] != legacy[key]:
                diagnostics.append(Diagnostic(f"{item_path}.{key}", f"conflicts with attributes.{key}"))
            else:
                manifest_attributes[key] = copy.deepcopy(legacy[key])

        for key, raw in attributes.items():
            if key == "route_part":
                diagnostics.append(Diagnostic(f"{item_path}.attributes.route_part", "cannot prove this is a real split part; migration is blocked"))
                continue
            target = key
            if target in _ATTRIBUTE_PROMOTIONS:
                if target in artifact and artifact[target] != raw:
                    diagnostics.append(Diagnostic(f"{item_path}.attributes.{key}", f"conflicts with artifact.{target}"))
                else:
                    artifact[target] = copy.deepcopy(raw)
            elif key in {"local_manifest", "manifest_path", "base_urls", "manifest_urls"}:
                continue
            else:
                diagnostics.append(Diagnostic(f"{item_path}.attributes.{key}", "cannot be safely represented in schema v2"))
        if "part" in artifact and artifact["part"] is None:
            del artifact["part"]
        if "part" in manifest_attributes and manifest_attributes["part"] is None:
            del manifest_attributes["part"]
        _promote_manifest(artifact, manifest_attributes, vendor, item_path, diagnostics)

        for key in ("manifest", "source", "language", "route_from", "route_to", "size", "decompressed_size"):
            if artifact.get(key, object()) is None:
                del artifact[key]
        if isinstance(artifact.get("checksum"), Mapping):
            artifact["checksum"] = {
                algorithm: copy.deepcopy(digest)
                for algorithm, digest in artifact["checksum"].items()
                if digest is not None
            }
            if not artifact["checksum"]:
                del artifact["checksum"]

        if "checksum_type" in legacy or "checksum_value" in legacy:
            checksum_type = legacy.get("checksum_type")
            checksum_value = legacy.get("checksum_value")
            if checksum_type in (None, "") and checksum_value in (None, ""):
                pass
            elif checksum_type in CHECKSUM_FIELDS and _non_empty_string(checksum_value):
                if "checksum" in artifact and artifact["checksum"] != {checksum_type: checksum_value}:
                    diagnostics.append(Diagnostic(item_path + ".checksum", "conflicts with legacy checksum pair"))
                else:
                    artifact["checksum"] = {checksum_type: copy.deepcopy(checksum_value)}
            elif checksum_type == "etag" and _non_empty_string(checksum_value):
                urls = artifact.get("urls")
                if isinstance(urls, list) and len(urls) == 1 and isinstance(urls[0], Mapping):
                    current = dict(urls[0].get("current") or {})
                    if "etag" in current and current["etag"] != checksum_value:
                        diagnostics.append(Diagnostic(item_path + ".checksum_value", "conflicts with URL current.etag"))
                    else:
                        current["etag"] = copy.deepcopy(checksum_value)
                        urls[0] = dict(urls[0])
                        urls[0]["current"] = current
                else:
                    diagnostics.append(Diagnostic(item_path + ".checksum_type", "etag needs exactly one URL candidate to migrate to current.etag"))
            else:
                diagnostics.append(Diagnostic(item_path + ".checksum_type", "checksum pair is invalid or cannot be safely migrated"))

        artifact.setdefault("delivery_mode", "direct")
        if "urls" in artifact:
            artifact["urls"] = _legacy_urls(artifact["urls"], vendor, item_path + ".urls", diagnostics)
        else:
            artifact["urls"] = []
        try:
            generated_id = artifact_id(artifact, record_identity=record_identity)
            existing_id = artifact.get("artifact_id")
            if existing_id is not None and existing_id != generated_id:
                diagnostics.append(Diagnostic(item_path + ".artifact_id", "does not match regenerated identity"))
            artifact["artifact_id"] = generated_id
        except (TypeError, ValueError) as exc:
            diagnostics.append(Diagnostic(item_path, str(exc)))
        output.append(artifact)
    return output


def _android_artifact(
    source: Mapping[str, Any],
    vendor: Any,
    record_identity: Mapping[str, Any],
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    filename = source.get("filename")
    url = source.get("url")
    if not _non_empty_string(filename):
        diagnostics.append(Diagnostic("$.filename", "is required to migrate the Android APK"))
    if not _non_empty_string(url):
        diagnostics.append(Diagnostic("$.url", "is required to migrate the Android APK"))
    if not _non_empty_string(filename) or not _non_empty_string(url):
        return None
    artifact: dict[str, Any] = {
        "kind": "apk",
        "component": "game",
        "package_type": "full",
        "delivery_mode": "direct",
        "name": filename,
        "urls": [{"url": url, "provider": vendor if _non_empty_string(vendor) else "legacy", "source_kind": "legacy", "priority": 0}],
    }
    if source.get("size") is not None:
        artifact["size"] = copy.deepcopy(source["size"])

    status = source.get("status")
    if status is not None:
        if not isinstance(status, Mapping):
            diagnostics.append(Diagnostic("$.status", "must be an object"))
        else:
            current: dict[str, Any] = {}
            for key, target in (("http_code", "http_code"), ("last_checked_at", "checked_at")):
                if key in status and status[key] is not None:
                    current[target] = copy.deepcopy(status[key])
            if "available" in status and status["available"] is not None:
                if not isinstance(status["available"], bool):
                    diagnostics.append(Diagnostic("$.status.available", "must be boolean to map to current.state"))
                else:
                    current["state"] = "available" if status["available"] else "unavailable"
            for key in status:
                if key not in {"http_code", "available", "last_checked_at"}:
                    diagnostics.append(Diagnostic(f"$.status.{key}", "cannot be safely represented in schema v2"))
            if current:
                artifact["urls"][0]["current"] = current

    checksum = source.get("checksum")
    if checksum is not None:
        if not isinstance(checksum, Mapping):
            diagnostics.append(Diagnostic("$.checksum", "must be an object"))
        else:
            canonical: dict[str, Any] = {}
            for key, raw in checksum.items():
                if key in CHECKSUM_FIELDS:
                    if raw is not None:
                        canonical[key] = copy.deepcopy(raw)
                elif key == "etag":
                    if raw is not None:
                        artifact["urls"][0].setdefault("current", {})["etag"] = copy.deepcopy(raw)
                else:
                    diagnostics.append(Diagnostic(f"$.checksum.{key}", "cannot be safely represented in schema v2"))
            if canonical:
                artifact["checksum"] = canonical
    try:
        artifact["artifact_id"] = artifact_id(artifact, record_identity=record_identity)
    except (TypeError, ValueError) as exc:
        diagnostics.append(Diagnostic("$", str(exc)))
    return artifact


def normalize_legacy_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new canonical v2 record migrated from a legacy mapping.

    The input is never modified.  Ambiguous or unsupported legacy data raises
    ``LegacyNormalizationError`` with path-aware diagnostics instead of being
    silently discarded.
    """

    if not isinstance(record, Mapping):
        raise LegacyNormalizationError([Diagnostic("$", "record must be an object")])

    is_v2 = record.get("schema_version") == SCHEMA_VERSION
    if is_v2:
        strict_errors = validate_v2_record(record, raise_on_error=False)
        if strict_errors:
            raise SchemaValidationError(strict_errors)
        return copy.deepcopy(dict(record))

    source = copy.deepcopy(dict(record))
    diagnostics: list[Diagnostic] = []
    output: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if "schema_version" in source and (
        not _is_int(source["schema_version"]) or source["schema_version"] != 1
    ):
        diagnostics.append(Diagnostic("$.schema_version", "unsupported legacy schema version"))
    for key in ("vendor", "game_id", "platform", "channel", "version", "is_visible"):
        if key in source:
            output[key] = copy.deepcopy(source[key])
    for key in ("version_code", "file_time"):
        output[key] = copy.deepcopy(source[key]) if key in source else None
    if "domain_id" in source:
        output["domain_id"] = copy.deepcopy(source["domain_id"])
    elif _non_empty_string(source.get("game_id")) and source.get("platform") in {"android", "windows"}:
        output["domain_id"] = f"{source['game_id']}-{'android' if source['platform'] == 'android' else 'pc'}"

    record_identity = {field: output.get(field) for field in RECORD_IDENTITY_FIELDS}

    for key in source:
        if key not in RECORD_FIELDS and key not in LEGACY_RECORD_FIELDS and key != "artifacts" and key != "references" and key != "provenance":
            diagnostics.append(Diagnostic(f"$.{key}", "unknown field cannot be migrated"))
    if "adapter" in source:
        diagnostics.append(Diagnostic("$.adapter", "adapter is legacy-reader-only and cannot enter canonical v2"))
    if "source_released_at" in source:
        diagnostics.append(Diagnostic("$.source_released_at", "cannot be safely represented in canonical v2"))

    if "provenance" in source:
        output["provenance"] = _legacy_provenance(source["provenance"], diagnostics)

    is_android_flat = source.get("platform") == "android" and (
        any(key in source for key in ("url", "filename"))
        or ("status" in source and "artifacts" not in source)
    )
    if is_android_flat:
        if source.get("platform") != "android":
            diagnostics.append(Diagnostic("$.url", "flat root URL contract is only supported for platform=android"))
        if "artifacts" in source:
            diagnostics.append(Diagnostic("$.artifacts", "cannot combine Android flat fields with artifacts[]"))
        artifact = _android_artifact(source, source.get("vendor"), record_identity, diagnostics)
        output["artifacts"] = [] if artifact is None else [artifact]
    else:
        output["artifacts"] = _legacy_artifacts(
            source.get("artifacts", []),
            source.get("vendor"),
            "$.artifacts",
            record_identity,
            diagnostics,
        )

    output["references"] = copy.deepcopy(source.get("references", []))
    if "status" in source and not is_android_flat:
        status = source["status"]
        if not isinstance(status, Mapping):
            diagnostics.append(Diagnostic("$.status", "must be an object"))
        elif (
            any(key not in {"http_code", "available", "last_checked_at"} for key in status)
            or any(value is not None for value in status.values())
        ):
            diagnostics.append(Diagnostic("$.status", "record-level status cannot be assigned to an artifact URL without guessing"))

    # These fields were consumed above.  Root legacy values not handled by a
    # platform-specific adapter are deliberately diagnosed, never discarded.
    if "url" in source and not is_android_flat:
        diagnostics.append(Diagnostic("$.url", "cannot be represented for a non-Android record"))
    for key in ("filename", "size", "checksum"):
        if key in source and not is_android_flat:
            diagnostics.append(Diagnostic(f"$.{key}", "cannot be represented for a non-Android record"))

    try:
        validate_v2_record(output)
    except SchemaValidationError as exc:
        diagnostics.extend(Diagnostic(error.split(":", 1)[0], error.split(": ", 1)[1] if ": " in error else error) for error in exc.errors)
    if diagnostics:
        raise LegacyNormalizationError(diagnostics)
    return output


from backend.schema_v2 import (  # noqa: E402
    ARTIFACT_FIELDS,
    BASE_URL_FIELDS,
    CHECKSUM_FIELDS,
    CURRENT_FIELDS,
    LEGACY_ARTIFACT_FIELDS,
    LEGACY_CURRENT_FIELDS,
    LEGACY_RECORD_FIELDS,
    PROVENANCE_FIELDS,
    RECORD_FIELDS,
    RECORD_IDENTITY_FIELDS,
    SCHEMA_VERSION,
    URL_FIELDS,
    Diagnostic,
    LegacyNormalizationError,
    SchemaValidationError,
    artifact_id,
    validate_v2_record,
)

__all__ = [
    "Diagnostic",
    "LegacyNormalizationError",
    "normalize_legacy_record",
]
