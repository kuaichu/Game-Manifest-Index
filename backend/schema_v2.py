"""Canonical schema v2 validation and artifact identity primitives.

This module is deliberately independent from the storage, API, and writer
layers.  It describes the boundary between the existing records and the v2
canonical shape; it does not migrate files on disk.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final


SCHEMA_VERSION: Final = 2
IDENTITY_ALGORITHM: Final = "artifact_identity_key_v1"
ARTIFACT_ID_PREFIX: Final = "a1_"

RECORD_FIELDS: Final = {
    "schema_version",
    "vendor",
    "game_id",
    "domain_id",
    "platform",
    "channel",
    "version",
    "version_code",
    "file_time",
    "artifacts",
    "references",
    "is_visible",
    "provenance",
}
_RECORD_FIELDS: Final = RECORD_FIELDS

ARTIFACT_FIELDS: Final = {
    "artifact_id",
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
    "urls",
    "source",
}
_ARTIFACT_FIELDS: Final = ARTIFACT_FIELDS

CHECKSUM_FIELDS: Final = {"md5", "sha256", "crc64"}
_CHECKSUM_FIELDS: Final = CHECKSUM_FIELDS

URL_FIELDS: Final = {"url", "provider", "source_kind", "priority", "current"}
_URL_FIELDS: Final = URL_FIELDS

BASE_URL_FIELDS: Final = {"url", "provider", "source_kind", "priority"}
_BASE_URL_FIELDS: Final = BASE_URL_FIELDS

CURRENT_FIELDS: Final = {
    "state",
    "http_code",
    "checked_at",
    "response_size",
    "etag",
    "crc64",
    "last_modified",
    "final_url",
}
_CURRENT_FIELDS: Final = CURRENT_FIELDS

_REFERENCE_FIELDS: Final = {"kind", "path", "build_id", "source"}

PROVENANCE_FIELDS: Final = {
    "source_kind",
    "source_name",
    "source_url",
    "source_repo",
    "source_commit",
    "imported_at",
}
_PROVENANCE_FIELDS: Final = PROVENANCE_FIELDS

_RECORD_IDENTITY_FIELDS: Final = (
    "vendor",
    "game_id",
    "domain_id",
    "platform",
    "channel",
    "version",
)
# Public schema contract used by storage and other v2 consumers.  Keep this
# tuple in one place so callers do not grow their own identity definitions.
RECORD_IDENTITY_FIELDS: Final = _RECORD_IDENTITY_FIELDS

_REFERENCE_SOURCE_FIELDS: Final = {
    "source_kind",
    "source_name",
    "source_url",
    "source_repo",
    "source_commit",
}
_ALLOWED_KINDS: Final = {"apk", "package", "patch", "resource"}
_ALLOWED_COMPONENTS: Final = {"game", "voice", "launcher", "other", "resource"}
_ALLOWED_PACKAGE_TYPES: Final = {"full", "segment", "optional", "differential"}
_ALLOWED_DELIVERY_MODES: Final = {"direct", "archive", "file_manifest"}
_ALLOWED_CURRENT_STATES: Final = {"available", "unavailable", "unknown"}
_ALLOWED_PROVENANCE_SOURCE_KINDS: Final = {
    "official_sync",
    "third_party_history",
    "legacy_migration",
    "manual",
}
_ARTIFACT_ID_PATTERN: Final = re.compile(r"^a1_[0-9a-f]{32}$")

LEGACY_RECORD_FIELDS: Final = {
    "url",
    "filename",
    "size",
    "checksum",
    "status",
    "adapter",
    "source_released_at",
}
_LEGACY_RECORD_FIELDS: Final = LEGACY_RECORD_FIELDS

LEGACY_ARTIFACT_FIELDS: Final = {
    "attributes",
    "checksum_type",
    "checksum_value",
    "chunk_summary",
    "kuro_manifest",
    "evidence",
}
_LEGACY_ARTIFACT_FIELDS: Final = LEGACY_ARTIFACT_FIELDS

LEGACY_CURRENT_FIELDS: Final = {
    "reason",
    "confidence",
    "retained",
    "expected_size",
    "observed_size",
    "evidence_status",
    "md5",
}
_LEGACY_CURRENT_FIELDS: Final = LEGACY_CURRENT_FIELDS


@dataclass(frozen=True)
class Diagnostic:
    """A path-aware migration or validation diagnostic."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class SchemaValidationError(ValueError):
    """Raised when a record is not a strict canonical v2 record."""

    def __init__(self, errors: Sequence[str | Diagnostic]):
        self.errors = tuple(str(error) for error in errors)
        super().__init__("schema v2 validation failed: " + "; ".join(self.errors))


class LegacyNormalizationError(ValueError):
    """Raised when legacy data cannot be migrated without guessing."""

    def __init__(self, diagnostics: Sequence[str | Diagnostic]):
        self.diagnostics = tuple(str(diagnostic) for diagnostic in diagnostics)
        super().__init__("legacy normalization failed: " + "; ".join(self.diagnostics))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int)) and not isinstance(value, bool)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _add(errors: list[str], path: str, message: str) -> None:
    errors.append(str(Diagnostic(path, message)))


def _check_unknown(errors: list[str], value: Mapping[str, Any], allowed: set[str], path: str, forbidden: set[str] | None = None) -> None:
    forbidden = forbidden or set()
    for key in value:
        if key not in allowed:
            if key in forbidden:
                _add(errors, f"{path}.{key}", "legacy field is forbidden in schema v2")
            else:
                _add(errors, f"{path}.{key}", "unknown field")


def _validate_checksum(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _CHECKSUM_FIELDS, path)
    for algorithm, digest in value.items():
        if algorithm not in _CHECKSUM_FIELDS:
            continue
        if not _non_empty_string(digest):
            _add(errors, f"{path}.{algorithm}", "must be a non-empty string")


def _validate_current(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _CURRENT_FIELDS, path, _LEGACY_CURRENT_FIELDS)
    for key, item in value.items():
        if key == "state":
            if not isinstance(item, str) or item not in _ALLOWED_CURRENT_STATES:
                _add(errors, f"{path}.state", f"must be one of {sorted(_ALLOWED_CURRENT_STATES)}")
        elif key in {"checked_at", "etag", "last_modified", "final_url", "crc64"}:
            if item is not None and not isinstance(item, str):
                _add(errors, f"{path}.{key}", "must be a string or null")
        elif key in {"http_code", "response_size"}:
            if item is not None and not _is_int(item):
                _add(errors, f"{path}.{key}", "must be an integer or null")
            elif _is_int(item) and item < 0:
                _add(errors, f"{path}.{key}", "must not be negative")


def _validate_manifest(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, {"path", "base_urls"}, path)
    if "path" not in value:
        _add(errors, path, "must contain path")
    elif not _safe_relative_posix_path(value["path"]):
        _add(errors, f"{path}.path", "must be a safe relative POSIX path")
    if "base_urls" in value:
        items = value["base_urls"]
        if not isinstance(items, list):
            _add(errors, f"{path}.base_urls", "must be an array")
        else:
            for index, item in enumerate(items):
                _validate_base_url(item, f"{path}.base_urls[{index}]", errors)


def _validate_compact_source(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allow_null: bool = True,
    allowed_fields: set[str] = _REFERENCE_SOURCE_FIELDS,
) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, Mapping):
        _add(errors, path, "must be a compact provenance object" + (" or null" if allow_null else ""))
        return
    _check_unknown(errors, value, allowed_fields, path)
    for key, item in value.items():
        if key == "source_kind":
            if not isinstance(item, str) or item not in _ALLOWED_PROVENANCE_SOURCE_KINDS:
                _add(errors, f"{path}.source_kind", f"must be one of {sorted(_ALLOWED_PROVENANCE_SOURCE_KINDS)}")
        elif key in allowed_fields and item is not None and not _non_empty_string(item):
            _add(errors, f"{path}.{key}", "must be a non-empty string or null")


def _validate_url(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _URL_FIELDS, path)
    for key in ("url", "provider", "source_kind"):
        if key not in value:
            _add(errors, f"{path}.{key}", "is required")
        elif not _non_empty_string(value[key]):
            _add(errors, f"{path}.{key}", "must be a non-empty string")
    if "priority" not in value:
        _add(errors, f"{path}.priority", "is required")
    elif not _is_int(value["priority"]) or value["priority"] < 0:
        _add(errors, f"{path}.priority", "must be a non-negative integer")
    if "current" in value:
        _validate_current(value["current"], f"{path}.current", errors)
        current = value["current"]
        if isinstance(current, Mapping) and current.get("final_url") is not None and current.get("final_url") == value.get("url"):
            _add(errors, f"{path}.current.final_url", "must differ from candidate.url when non-null")


def _validate_base_url(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _BASE_URL_FIELDS, path)
    for key in ("url", "provider", "source_kind"):
        if key not in value:
            _add(errors, f"{path}.{key}", "is required")
        elif not _non_empty_string(value[key]):
            _add(errors, f"{path}.{key}", "must be a non-empty string")
    if "priority" not in value:
        _add(errors, f"{path}.priority", "is required")
    elif not _is_int(value["priority"]) or value["priority"] < 0:
        _add(errors, f"{path}.priority", "must be a non-negative integer")


def _validate_artifact(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _ARTIFACT_FIELDS, path, _LEGACY_ARTIFACT_FIELDS)
    is_resource = value.get("kind") == "resource"
    required = ("artifact_id", "kind", "component", "name") if is_resource else (
        "artifact_id", "kind", "component", "package_type", "delivery_mode", "name"
    )
    for key in required:
        if key not in value:
            _add(errors, f"{path}.{key}", "is required")
        elif not _non_empty_string(value[key]):
            _add(errors, f"{path}.{key}", "must be a non-empty string")
    if "artifact_id" in value and isinstance(value["artifact_id"], str) and not _ARTIFACT_ID_PATTERN.fullmatch(value["artifact_id"]):
        _add(errors, f"{path}.artifact_id", "must match a1_ followed by 32 lowercase hexadecimal characters")
    for key, allowed in (
        ("kind", _ALLOWED_KINDS),
        ("component", _ALLOWED_COMPONENTS),
        ("package_type", _ALLOWED_PACKAGE_TYPES),
        ("delivery_mode", _ALLOWED_DELIVERY_MODES),
    ):
        if key in value and isinstance(value[key], str) and value[key] not in allowed:
            _add(errors, f"{path}.{key}", f"must be one of {sorted(allowed)}")
    if is_resource:
        if value.get("component") != "resource":
            _add(errors, f"{path}.component", "must be resource for resource artifacts")
        for key in ("package_type", "delivery_mode", "part", "language", "route_from", "route_to", "decompressed_size", "manifest"):
            if key in value:
                _add(errors, f"{path}.{key}", "is not allowed for resource artifacts")
        if "name" in value and not _safe_relative_posix_path(value["name"]):
            _add(errors, f"{path}.name", "must be a safe relative POSIX path for resource artifacts")
        if "size" not in value:
            _add(errors, f"{path}.size", "is required for resource artifacts")
        checksum = value.get("checksum")
        if not isinstance(checksum, Mapping) or set(checksum) != {"md5"}:
            _add(errors, f"{path}.checksum", "must contain exactly md5 for resource artifacts")
        elif not isinstance(checksum.get("md5"), str) or re.fullmatch(r"[0-9a-f]{32}", checksum["md5"]) is None:
            _add(errors, f"{path}.checksum.md5", "must be 32 lowercase hexadecimal characters for resource artifacts")
    elif value.get("component") == "resource":
        _add(errors, f"{path}.component", "is only allowed for resource artifacts")
    if "language" in value:
        language = value["language"]
        if not _non_empty_string(language):
            _add(errors, f"{path}.language", "must be a non-empty string")
        if value.get("component") != "voice":
            _add(errors, f"{path}.language", "is only allowed for voice artifacts")
    for key in ("route_from", "route_to"):
        if key in value:
            route = value[key]
            if not _non_empty_string(route):
                _add(errors, f"{path}.{key}", "must be a non-empty string")
            if value.get("kind") != "patch":
                _add(errors, f"{path}.{key}", "is only allowed for patch artifacts")
    if "part" in value:
        if not _is_int(value["part"]) or value["part"] < 1:
            _add(errors, f"{path}.part", "must be a positive integer when present")
        if value.get("kind") != "package" or value.get("package_type") != "segment":
            _add(errors, f"{path}.part", "is only allowed for package segment artifacts")
    elif value.get("package_type") == "segment":
        _add(errors, f"{path}.part", "is required for package segment artifacts")
    for key in ("size", "decompressed_size"):
        if key in value:
            item = value[key]
            if not _is_int(item) or item < 0:
                _add(errors, f"{path}.{key}", "must be a non-negative integer")
    if "checksum" in value:
        _validate_checksum(value["checksum"], f"{path}.checksum", errors)
    if "manifest" in value:
        _validate_manifest(value["manifest"], f"{path}.manifest", errors)
        if value.get("delivery_mode") != "file_manifest":
            _add(errors, f"{path}.manifest", "is only allowed for file_manifest artifacts")
    if value.get("delivery_mode") == "file_manifest":
        manifest = value.get("manifest")
        if not isinstance(manifest, Mapping) or "path" not in manifest:
            _add(errors, f"{path}.manifest.path", "is required for file_manifest artifacts")
    if value.get("kind") == "patch":
        if value.get("package_type") != "differential":
            _add(errors, f"{path}.package_type", "must be differential for patch artifacts")
        for key in ("route_from", "route_to"):
            if key not in value or not _non_empty_string(value[key]):
                _add(errors, f"{path}.{key}", "is required for patch artifacts")
    elif value.get("package_type") == "differential":
        _add(errors, f"{path}.kind", "must be patch for differential artifacts")
    if "urls" in value:
        if not isinstance(value["urls"], list):
            _add(errors, f"{path}.urls", "must be an array")
        else:
            for index, item in enumerate(value["urls"]):
                _validate_url(item, f"{path}.urls[{index}]", errors)
            if is_resource and not value["urls"]:
                _add(errors, f"{path}.urls", "must not be empty for resource artifacts")
    else:
        _add(errors, f"{path}.urls", "is required")
    if "source" in value:
        _validate_compact_source(value["source"], f"{path}.source", errors)


def _validate_reference(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, Mapping):
        _add(errors, path, "must be an object")
        return
    _check_unknown(errors, value, _REFERENCE_FIELDS, path)
    if value.get("kind") != "chunk_manifest":
        _add(errors, f"{path}.kind", "must be chunk_manifest")
    if "path" not in value:
        _add(errors, f"{path}.path", "is required")
    elif not _safe_relative_posix_path(value["path"]):
        _add(errors, f"{path}.path", "must be a safe relative POSIX path")
    if "build_id" in value and value["build_id"] is not None and not _non_empty_string(value["build_id"]):
        _add(errors, f"{path}.build_id", "must be a non-empty string or null")
    if "source" in value:
        _validate_compact_source(value["source"], f"{path}.source", errors)


def _validate_provenance(value: Any, path: str, errors: list[str]) -> None:
    _validate_compact_source(value, path, errors, allow_null=False, allowed_fields=_PROVENANCE_FIELDS)


def validate_v2_record(record: Any, *, raise_on_error: bool = True) -> tuple[str, ...]:
    """Validate a canonical record and return diagnostics.

    The default is strict: any diagnostic raises ``SchemaValidationError``.
    Callers that need to display or aggregate errors can pass
    ``raise_on_error=False``.
    """

    errors: list[str] = []
    if not isinstance(record, Mapping):
        errors.append("$: must be an object")
        if raise_on_error:
            raise SchemaValidationError(errors)
        return tuple(errors)

    _check_unknown(errors, record, _RECORD_FIELDS, "$", _LEGACY_RECORD_FIELDS)
    if not _is_int(record.get("schema_version")) or record.get("schema_version") != SCHEMA_VERSION:
        _add(errors, "$.schema_version", "must be integer 2")
    for key in ("vendor", "game_id", "domain_id", "channel", "version"):
        if key not in record:
            _add(errors, f"$.{key}", "is required")
        elif not _non_empty_string(record[key]):
            _add(errors, f"$.{key}", "must be a non-empty string")
    if not isinstance(record.get("platform"), str) or record.get("platform") not in {"android", "windows"}:
        _add(errors, "$.platform", "must be android or windows")
    for key in ("version_code", "file_time"):
        if key not in record:
            _add(errors, f"$.{key}", "is required")
    if "version_code" in record and record["version_code"] is not None and not _is_scalar(record["version_code"]):
        _add(errors, "$.version_code", "must be a string, integer, or null")
    if "file_time" in record and record["file_time"] is not None and not isinstance(record["file_time"], str):
        _add(errors, "$.file_time", "must be a string or null")
    if "is_visible" in record and not isinstance(record["is_visible"], bool):
        _add(errors, "$.is_visible", "must be a boolean")

    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list):
        _add(errors, "$.artifacts", "must be an array")
        artifacts = []
    artifact_ids: dict[str, int] = {}
    identity_keys: dict[str, int] = {}
    record_identity_map = {field: record.get(field) for field in _RECORD_IDENTITY_FIELDS}
    for index, artifact in enumerate(artifacts):
        path = f"$.artifacts[{index}]"
        _validate_artifact(artifact, path, errors)
        if not isinstance(artifact, Mapping):
            continue
        artifact_id_value = artifact.get("artifact_id")
        if isinstance(artifact_id_value, str):
            if artifact_id_value in artifact_ids:
                _add(errors, path + ".artifact_id", f"duplicates artifacts[{artifact_ids[artifact_id_value]}]")
            artifact_ids[artifact_id_value] = index
        try:
            identity_key = artifact_identity_key(
                artifact.get("name"),
                artifact.get("component"),
                part=artifact.get("part"),
                language=artifact.get("language"),
                route_from=artifact.get("route_from"),
                route_to=artifact.get("route_to"),
            )
            if identity_key in identity_keys:
                _add(errors, path, f"identity duplicates artifacts[{identity_keys[identity_key]}]")
            identity_keys[identity_key] = index
            if artifact_id_value != artifact_id(artifact, record_identity=record_identity_map):
                _add(errors, path + ".artifact_id", "does not match artifact_identity_key_v1")
        except (TypeError, ValueError) as exc:
            _add(errors, path, str(exc))

    references = record.get("references")
    if not isinstance(references, list):
        _add(errors, "$.references", "must be an array")
        references = []
    reference_keys: dict[tuple[str, str], int] = {}
    for index, reference in enumerate(references):
        path = f"$.references[{index}]"
        _validate_reference(reference, path, errors)
        if isinstance(reference, Mapping):
            kind = reference.get("kind")
            reference_path = reference.get("path")
            if isinstance(kind, str) and isinstance(reference_path, str):
                key = (kind, reference_path)
                if key in reference_keys:
                    _add(errors, path, f"(kind, path) duplicates references[{reference_keys[key]}]")
                reference_keys[key] = index

    if "provenance" in record:
        _validate_provenance(record["provenance"], "$.provenance", errors)

    if raise_on_error and errors:
        raise SchemaValidationError(errors)
    return tuple(errors)


def _safe_relative_posix_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value or ":" in value:
        return False
    if value.startswith("/"):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _normalize_identity_value(value: Any, *, language: bool = False) -> Any:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if language:
            normalized = normalized.strip().replace("_", "-").lower()
        return normalized
    return value


def _normalized_record_identity(record_identity: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(record_identity, Mapping):
        raise TypeError("record_identity must be a complete object")
    normalized: dict[str, str] = {}
    for field in _RECORD_IDENTITY_FIELDS:
        if field not in record_identity:
            raise ValueError(f"record identity field {field} is required")
        value = _normalize_identity_value(record_identity[field])
        if not _non_empty_string(value):
            raise ValueError(f"record identity field {field} must be a non-empty string")
        if field == "platform" and value not in {"android", "windows"}:
            raise ValueError("record identity field platform must be android or windows")
        normalized[field] = value
    return normalized


def record_identity(record: Mapping[str, Any]) -> dict[str, str]:
    """Return the canonical v2 record identity fields.

    This uses the same NFC normalization as ``artifact_id``.  It also keeps
    the complete-identity checks in one schema-owned helper for callers that
    compare records after validation.
    """
    return _normalized_record_identity(record)


def artifact_identity_key_v1(
    name: str,
    component_slot: str,
    *,
    part: int | None = None,
    language: str | None = None,
    route_from: str | None = None,
    route_to: str | None = None,
) -> str:
    """Return the deterministic, versioned identity key for an artifact.

    Classification fields such as kind, package_type, and delivery_mode are
    intentionally absent.  JSON encoding avoids delimiter ambiguity between
    identity components.
    """

    values = {
        "name": _normalize_identity_value(name),
        "component_slot": _normalize_identity_value(component_slot),
        "part": _normalize_identity_value(part),
        "language": _normalize_identity_value(language, language=True),
        "route_from": _normalize_identity_value(route_from),
        "route_to": _normalize_identity_value(route_to),
    }
    if not _non_empty_string(values["name"]):
        raise ValueError("identity field name must be a non-empty string")
    if not _non_empty_string(values["component_slot"]):
        raise ValueError("identity field component_slot must be a non-empty string")
    if values["part"] is not None and (not _is_int(values["part"]) or values["part"] < 1):
        raise ValueError("identity field part must be a positive integer or null")
    if values["language"] is not None:
        if not _non_empty_string(values["language"]):
            raise ValueError("identity field language must be a non-empty string or null")
        if values["component_slot"] != "voice":
            raise ValueError("identity field language is only allowed for voice artifacts")
    for field in ("route_from", "route_to"):
        if values[field] is not None and not _non_empty_string(values[field]):
            raise ValueError(f"identity field {field} must be a non-empty string or null")
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def artifact_identity_key(
    name: str,
    component_slot: str,
    *,
    part: int | None = None,
    language: str | None = None,
    route_from: str | None = None,
    route_to: str | None = None,
) -> str:
    """Alias for the v1 identity-key API."""

    return artifact_identity_key_v1(
        name,
        component_slot,
        part=part,
        language=language,
        route_from=route_from,
        route_to=route_to,
    )


def artifact_id(value: Mapping[str, Any] | str, record_identity: Mapping[str, Any]) -> str:
    """Generate an artifact id from an artifact mapping or identity key."""

    if isinstance(value, Mapping):
        key = artifact_identity_key(
            value.get("name"),
            value.get("component"),
            part=value.get("part"),
            language=value.get("language"),
            route_from=value.get("route_from"),
            route_to=value.get("route_to"),
        )
    elif isinstance(value, str) and value:
        key = value
    else:
        raise TypeError("artifact_id requires an artifact mapping or identity key")
    normalized_record_identity = _normalized_record_identity(record_identity)
    material = json.dumps(
        {"record_identity": normalized_record_identity, "identity_key": key},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ARTIFACT_ID_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


from backend.legacy_record_normalizer import normalize_legacy_record  # noqa: E402

__all__ = [
    "ARTIFACT_FIELDS",
    "ARTIFACT_ID_PREFIX",
    "BASE_URL_FIELDS",
    "CHECKSUM_FIELDS",
    "CURRENT_FIELDS",
    "IDENTITY_ALGORITHM",
    "LEGACY_ARTIFACT_FIELDS",
    "LEGACY_CURRENT_FIELDS",
    "LEGACY_RECORD_FIELDS",
    "PROVENANCE_FIELDS",
    "RECORD_FIELDS",
    "RECORD_IDENTITY_FIELDS",
    "SCHEMA_VERSION",
    "URL_FIELDS",
    "Diagnostic",
    "LegacyNormalizationError",
    "SchemaValidationError",
    "artifact_id",
    "artifact_identity_key",
    "artifact_identity_key_v1",
    "normalize_legacy_record",
    "record_identity",
    "validate_v2_record",
]
