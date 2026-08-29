import copy
import unittest
import unicodedata

from backend.schema_v2 import (
    LegacyNormalizationError,
    SchemaValidationError,
    artifact_id,
    artifact_identity_key,
    artifact_identity_key_v1,
    normalize_legacy_record,
    validate_v2_record,
)


def make_artifact(**overrides):
    artifact = {
        "artifact_id": "placeholder",
        "kind": "package",
        "component": "game",
        "package_type": "full",
        "delivery_mode": "direct",
        "name": "game.apk",
        "urls": [{"url": "https://example.test/game.apk", "provider": "test", "source_kind": "official", "priority": 0}],
    }
    artifact.update(overrides)
    return artifact


def make_record(**overrides):
    record = {
        "schema_version": 2,
        "vendor": "test",
        "game_id": "game",
        "domain_id": "game-android",
        "platform": "android",
        "channel": "official",
        "version": "1.0.0",
        "version_code": None,
        "file_time": None,
        "artifacts": [make_artifact()],
        "references": [],
    }
    record.update(overrides)
    record_identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    for artifact in record["artifacts"]:
        if isinstance(artifact, dict) and artifact.get("name") and artifact.get("component"):
            artifact["artifact_id"] = artifact_id(artifact, record_identity=record_identity)
    return record


class SchemaV2Tests(unittest.TestCase):
    def test_resource_artifact_has_strict_file_semantics(self):
        resource = {
            "kind": "resource",
            "component": "resource",
            "name": "Windows/Client/data.bin",
            "size": 12,
            "checksum": {"md5": "a" * 32},
            "urls": [{"url": "https://example.test/data.bin", "provider": "test", "source_kind": "official", "priority": 0}],
        }
        value = make_record(platform="windows", domain_id="endfield-resources", artifacts=[resource])
        validate_v2_record(value)
        for key, invalid_value in (
            ("component", "game"), ("package_type", "full"), ("delivery_mode", "direct"),
            ("part", 1), ("name", "../data.bin"), ("size", -1),
            ("checksum", {"sha256": "b" * 64}), ("urls", []),
        ):
            with self.subTest(key=key):
                invalid = copy.deepcopy(resource)
                invalid[key] = invalid_value
                errors = validate_v2_record(
                    make_record(platform="windows", domain_id="endfield-resources", artifacts=[invalid]),
                    raise_on_error=False,
                )
                self.assertTrue(errors)

    def test_identity_is_stable_and_ignores_position_and_classification(self):
        record_identity = {
            "vendor": "test",
            "game_id": "game",
            "domain_id": "game-android",
            "platform": "android",
            "channel": "official",
            "version": "1.0.0",
        }
        key = artifact_identity_key("foo.zip", "game", part=1)
        left = make_artifact(name="foo.zip", component="game", kind="package", package_type="full", delivery_mode="direct")
        right = make_artifact(name="foo.zip", component="game", kind="apk", package_type="segment", delivery_mode="archive")
        self.assertEqual(key, artifact_identity_key("foo.zip", "game", part=1))
        self.assertEqual(artifact_id(left, record_identity=record_identity), artifact_id(right, record_identity=record_identity))
        record = make_record(artifacts=[right, left])
        errors = validate_v2_record(record, raise_on_error=False)
        self.assertTrue(any("identity duplicates" in error for error in errors))

    def test_android_flat_normalization(self):
        legacy = {
            "vendor": "vendor",
            "game_id": "game",
            "platform": "android",
            "channel": "official",
            "version": "1.0.0",
            "filename": "game.apk",
            "url": "https://example.test/game.apk",
            "size": 123,
            "checksum": {"md5": "a" * 32, "etag": "etag-1", "crc64": None},
            "status": {"http_code": 200, "available": True, "last_checked_at": "2026-08-27T00:00:00Z"},
        }
        result = normalize_legacy_record(legacy)
        validate_v2_record(result)
        self.assertEqual(result["domain_id"], "game-android")
        self.assertEqual(result["artifacts"][0]["kind"], "apk")
        self.assertEqual(result["artifacts"][0]["checksum"], {"md5": "a" * 32})
        self.assertEqual(result["artifacts"][0]["urls"][0]["current"]["etag"], "etag-1")
        self.assertNotIn("url", result)
        self.assertNotIn("status", result)

    def test_pc_attributes_and_checksum_pair_are_promoted(self):
        legacy = make_record(
            platform="windows",
            domain_id="game-pc",
            status={"http_code": None, "available": None, "last_checked_at": None},
            artifacts=[
                {
                    "kind": "package",
                    "name": "game.zip",
                    "checksum_type": "md5",
                    "checksum_value": "b" * 32,
                    "attributes": {"component": "game", "package_type": "segment", "delivery_mode": "direct", "part": 1},
                    "urls": [{"url": "https://example.test/game.zip", "provider": "test", "source_kind": "official", "priority": 0}],
                }
            ],
        )
        legacy.pop("schema_version")
        result = normalize_legacy_record(legacy)
        validate_v2_record(result)
        artifact = result["artifacts"][0]
        self.assertEqual(artifact["component"], "game")
        self.assertEqual(artifact["part"], 1)
        self.assertEqual(artifact["checksum"], {"md5": "b" * 32})
        self.assertNotIn("attributes", artifact)

    def test_strict_forbidden_and_unknown_fields(self):
        record = make_record(url="https://bad", adapter="legacy")
        record["unexpected"] = True
        record["artifacts"][0]["attributes"] = {}
        record["artifacts"][0]["urls"][0]["current"] = {"reason": "HTTP 200"}
        errors = validate_v2_record(record, raise_on_error=False)
        self.assertTrue(any("legacy field is forbidden" in error for error in errors))
        self.assertTrue(any("unknown field" in error for error in errors))
        with self.assertRaises(SchemaValidationError):
            validate_v2_record(record)

    def test_manifest_and_reference_paths_and_uniqueness(self):
        record = make_record(
            artifacts=[make_artifact(delivery_mode="file_manifest", manifest={"path": "../manifest.json"})],
            references=[
                {"kind": "chunk_manifest", "path": "chunks/1.json"},
                {"kind": "chunk_manifest", "path": "chunks/1.json"},
            ],
        )
        errors = validate_v2_record(record, raise_on_error=False)
        self.assertTrue(any("safe relative POSIX path" in error for error in errors))
        self.assertTrue(any("duplicates references" in error for error in errors))

    def test_etag_is_not_a_checksum_and_candidate_shape_is_required(self):
        record = make_record()
        record["artifacts"][0]["checksum"] = {"etag": "wrong-place"}
        record["artifacts"][0]["urls"][0].pop("provider")
        errors = validate_v2_record(record, raise_on_error=False)
        self.assertTrue(any("unknown field" in error and "etag" in error for error in errors))
        self.assertTrue(any("provider" in error and "required" in error for error in errors))

    def test_frozen_enums_and_part_constraint(self):
        for package_type in ("full", "segment", "optional", "differential"):
            artifact = make_artifact(package_type=package_type, delivery_mode="archive")
            if package_type == "segment":
                artifact["part"] = 1
            elif package_type == "differential":
                artifact.update(kind="patch", route_from="1.0.0", route_to="1.1.0")
            record = make_record(artifacts=[artifact])
            validate_v2_record(record)

        segmented = make_record(artifacts=[make_artifact(package_type="segment", part=1)])
        validate_v2_record(segmented)

        for field, value in (("kind", "part"), ("component", "music"), ("package_type", "patch"), ("delivery_mode", "chunked")):
            invalid = make_record()
            invalid["artifacts"][0][field] = value
            errors = validate_v2_record(invalid, raise_on_error=False)
            self.assertTrue(any(f"{field}" in error and "one of" in error for error in errors))

        invalid_part = copy.deepcopy(segmented)
        invalid_part["artifacts"][0]["part"] = 0
        errors = validate_v2_record(invalid_part, raise_on_error=False)
        self.assertTrue(any("part" in error and "positive integer" in error for error in errors))

    def test_identity_key_is_artifact_only_and_artifact_id_requires_record_identity(self):
        key = artifact_identity_key_v1("voice.pak", "voice", language=" EN_us ")
        self.assertEqual(key, artifact_identity_key_v1("voice.pak", "voice", language="en-US"))
        with self.assertRaises((TypeError, ValueError)):
            artifact_id(make_artifact())

    def test_identity_normalizes_nfc_and_artifact_id_shape_matches_algorithm(self):
        identity = {
            "vendor": "test",
            "game_id": "game",
            "domain_id": "game-android",
            "platform": "android",
            "channel": "official",
            "version": "1.0.0",
        }
        decomposed = "cafe\u0301.apk"
        composed = unicodedata.normalize("NFC", decomposed)
        left = make_artifact(name=decomposed)
        right = make_artifact(name=composed)
        self.assertEqual(artifact_id(left, identity), artifact_id(right, identity))
        self.assertRegex(artifact_id(left, identity), r"^a1_[0-9a-f]{32}$")

    def test_manifest_base_urls_forbid_current(self):
        record = make_record(artifacts=[make_artifact(
            delivery_mode="file_manifest",
            manifest={"path": "manifest.json", "base_urls": [{
                "url": "https://example.test/base",
                "provider": "test",
                "source_kind": "official",
                "priority": 0,
                "current": {"state": "available"},
            }]},
        )])
        errors = validate_v2_record(record, raise_on_error=False)
        self.assertTrue(any("base_urls[0].current" in error and "unknown" in error for error in errors))

    def test_current_state_and_final_url_rules(self):
        record = make_record()
        current = record["artifacts"][0]["urls"][0].setdefault("current", {})
        current["state"] = "available"
        current["final_url"] = "https://example.test/redirected.apk"
        validate_v2_record(record)

        invalid_state = copy.deepcopy(record)
        invalid_state["artifacts"][0]["urls"][0]["current"]["state"] = "maybe"
        errors = validate_v2_record(invalid_state, raise_on_error=False)
        self.assertTrue(any("state" in error and "one of" in error for error in errors))

        invalid_final_url = copy.deepcopy(record)
        invalid_final_url["artifacts"][0]["urls"][0]["current"]["final_url"] = invalid_final_url["artifacts"][0]["urls"][0]["url"]
        errors = validate_v2_record(invalid_final_url, raise_on_error=False)
        self.assertTrue(any("final_url" in error and "differ" in error for error in errors))

    def test_provenance_source_kind_enum(self):
        record = make_record(
            provenance={"source_kind": "official_sync"},
            references=[{"kind": "chunk_manifest", "path": "chunks.json", "source": {"source_kind": "manual"}}],
        )
        validate_v2_record(record)
        invalid = copy.deepcopy(record)
        invalid["provenance"]["source_kind"] = "git"
        invalid["references"][0]["source"]["source_kind"] = "import"
        errors = validate_v2_record(invalid, raise_on_error=False)
        self.assertTrue(any("provenance.source_kind" in error and "one of" in error for error in errors))
        self.assertTrue(any("source.source_kind" in error and "one of" in error for error in errors))

    def test_normalizer_does_not_modify_input(self):
        legacy = {
            "vendor": "vendor",
            "game_id": "game",
            "platform": "android",
            "channel": "official",
            "version": "1.0.0",
            "filename": "game.apk",
            "url": "https://example.test/game.apk",
            "checksum": {"md5": "c" * 32},
            "status": {"http_code": None, "available": None, "last_checked_at": None},
        }
        before = copy.deepcopy(legacy)
        normalize_legacy_record(legacy)
        self.assertEqual(legacy, before)

    def test_unsafe_or_ambiguous_legacy_data_reports_diagnostics(self):
        legacy = make_record(
            artifacts=[
                {
                    "kind": "package",
                    "name": "game.zip",
                    "attributes": {"component": "game", "package_type": "full", "evidence_status": "verified"},
                }
            ]
        )
        legacy.pop("schema_version")
        with self.assertRaises(LegacyNormalizationError) as context:
            normalize_legacy_record(legacy)
        self.assertTrue(any("evidence_status" in error for error in context.exception.diagnostics))

    def test_reference_source_must_be_compact_object(self):
        record = make_record(references=[{
            "kind": "chunk_manifest",
            "path": "chunks/1.json",
            "source": {
                "source_kind": "official_sync",
                "source_name": "upstream",
                "source_url": "https://example.test/source",
                "source_repo": "owner/repo",
                "source_commit": "abc123",
            },
        }])
        validate_v2_record(record)
        invalid = copy.deepcopy(record)
        invalid["references"][0]["source"] = "upstream"
        errors = validate_v2_record(invalid, raise_on_error=False)
        self.assertTrue(any("source" in error and "object" in error for error in errors))

    def test_manifest_base_urls_use_url_candidates(self):
        record = make_record(artifacts=[make_artifact(
            delivery_mode="file_manifest",
            manifest={
                "path": "manifests/game.json",
                "base_urls": [{
                    "url": "https://example.test/manifests",
                    "provider": "test",
                    "source_kind": "official",
                    "priority": 0,
                }],
            },
        )])
        validate_v2_record(record)
        invalid = copy.deepcopy(record)
        invalid["artifacts"][0]["manifest"]["base_urls"] = ["https://example.test/manifests"]
        errors = validate_v2_record(invalid, raise_on_error=False)
        self.assertTrue(any("base_urls[0]" in error and "object" in error for error in errors))

    def test_legacy_manifest_urls_and_base_urls_become_manifest_candidates(self):
        for legacy_field in ("manifest_urls", "base_urls"):
            with self.subTest(legacy_field=legacy_field):
                legacy = {
                    "vendor": "vendor",
                    "game_id": "game",
                    "platform": "windows",
                    "channel": "official",
                    "version": "1.0.0",
                    "artifacts": [{
                        "kind": "package",
                        "name": "game.zip",
                        "attributes": {
                            "component": "game",
                            "package_type": "full",
                            "delivery_mode": "file_manifest",
                            "manifest_path": "manifests/game.json",
                            legacy_field: ["https://example.test/files/"],
                        },
                    }],
                }
                result = normalize_legacy_record(legacy)
                manifest = result["artifacts"][0]["manifest"]
                self.assertEqual(manifest["path"], "manifests/game.json")
                self.assertEqual(manifest["base_urls"][0]["url"], "https://example.test/files/")
                self.assertNotIn("current", manifest["base_urls"][0])
                validate_v2_record(result)

    def test_route_part_is_blocked_during_legacy_normalization(self):
        legacy = {
            "vendor": "vendor",
            "game_id": "game",
            "platform": "windows",
            "channel": "official",
            "version": "1.0.0",
            "artifacts": [{
                "kind": "package",
                "name": "game.zip",
                "attributes": {
                    "component": "game",
                    "package_type": "full",
                    "delivery_mode": "direct",
                    "route_part": 1,
                },
            }],
        }
        with self.assertRaises(LegacyNormalizationError) as context:
            normalize_legacy_record(legacy)
        self.assertTrue(any("route_part" in error for error in context.exception.diagnostics))

    def test_record_identity_changes_id_but_classification_does_not(self):
        identity_a = {
            "vendor": "test",
            "game_id": "game",
            "domain_id": "game-android",
            "platform": "android",
            "channel": "official",
            "version": "1.0.0",
        }
        identity_b = dict(identity_a, version="2.0.0")
        first = make_artifact(kind="package", package_type="full", delivery_mode="direct")
        second = make_artifact(kind="patch", package_type="segment", delivery_mode="file_manifest")
        self.assertEqual(artifact_id(first, record_identity=identity_a), artifact_id(second, record_identity=identity_a))
        self.assertNotEqual(artifact_id(first, record_identity=identity_a), artifact_id(first, record_identity=identity_b))

    def test_valid_v2_preserves_visibility_and_provenance_without_adapter(self):
        record = make_record(
            is_visible=False,
            provenance={"source_kind": "legacy_migration", "source_name": "fixture", "imported_at": "2026-08-27T00:00:00Z"},
        )
        result = normalize_legacy_record(record)
        self.assertEqual(result, record)
        validate_v2_record(result)

    def test_v2_normalization_deep_copies_and_invalid_v2_raises_schema_error(self):
        record = make_record(
            provenance={"source_kind": "manual"},
            references=[{"kind": "chunk_manifest", "path": "chunks.json"}],
        )
        result = normalize_legacy_record(record)
        result["references"][0]["path"] = "changed.json"
        result["artifacts"][0]["urls"][0]["provider"] = "changed"
        self.assertEqual(record["references"][0]["path"], "chunks.json")
        self.assertEqual(record["artifacts"][0]["urls"][0]["provider"], "test")

        invalid = make_record()
        invalid["artifacts"][0]["adapter"] = "legacy"
        with self.assertRaises(SchemaValidationError):
            normalize_legacy_record(invalid)

    def test_part_and_segment_semantics_are_strict(self):
        valid = make_record(artifacts=[make_artifact(package_type="segment", part=1)])
        validate_v2_record(valid)

        invalid_part = make_record(artifacts=[make_artifact(part=1)])
        errors = validate_v2_record(invalid_part, raise_on_error=False)
        self.assertTrue(any("part" in error and "package segment" in error for error in errors))

        missing_part = make_record(artifacts=[make_artifact(package_type="segment")])
        errors = validate_v2_record(missing_part, raise_on_error=False)
        self.assertTrue(any("part" in error and "required" in error for error in errors))

    def test_artifact_source_is_compact_and_legacy_source_is_preserved(self):
        source = {
            "source_kind": "official_sync",
            "source_name": "upstream",
            "source_url": "https://example.test/source",
            "source_repo": "owner/repo",
            "source_commit": "abc123",
        }
        record = make_record(artifacts=[make_artifact(source=source)])
        validate_v2_record(record)

        legacy = copy.deepcopy(record)
        legacy.pop("schema_version")
        result = normalize_legacy_record(legacy)
        self.assertEqual(result["artifacts"][0]["source"], source)

        invalid = copy.deepcopy(record)
        invalid["artifacts"][0]["source"]["imported_at"] = "2026-08-27T00:00:00Z"
        errors = validate_v2_record(invalid, raise_on_error=False)
        self.assertTrue(any("source.imported_at" in error and "unknown" in error for error in errors))

        legacy_with_url_provenance = copy.deepcopy(legacy)
        legacy_with_url_provenance["artifacts"][0]["urls"][0]["provenance"] = source
        with self.assertRaises(LegacyNormalizationError) as context:
            normalize_legacy_record(legacy_with_url_provenance)
        self.assertTrue(any("provenance" in error for error in context.exception.diagnostics))

    def test_artifact_semantics_reject_nulls_and_wrong_scopes(self):
        for field, value in (
            ("manifest", None),
            ("checksum", {"md5": None}),
            ("part", None),
            ("language", None),
            ("route_from", None),
            ("route_to", None),
            ("size", None),
            ("decompressed_size", None),
        ):
            with self.subTest(field=field):
                record = make_record()
                record["artifacts"][0][field] = value
                errors = validate_v2_record(record, raise_on_error=False)
                self.assertTrue(any(f".{field}" in error for error in errors))

        voice = make_record(artifacts=[make_artifact(
            component="voice", language="en-US",
        )])
        validate_v2_record(voice)

        route_on_package = make_record()
        route_on_package["artifacts"][0]["route_from"] = "1.0.0"
        errors = validate_v2_record(route_on_package, raise_on_error=False)
        self.assertTrue(any("route_from" in error and "only allowed" in error for error in errors))

        language_on_game = make_record()
        language_on_game["artifacts"][0]["language"] = "en-US"
        errors = validate_v2_record(language_on_game, raise_on_error=False)
        self.assertTrue(any("language" in error and "voice" in error for error in errors))

        invalid_patch = make_record(artifacts=[make_artifact(
            kind="patch", package_type="full", route_from="1.0.0", route_to="1.1.0",
        )])
        errors = validate_v2_record(invalid_patch, raise_on_error=False)
        self.assertTrue(any("package_type" in error and "differential" in error for error in errors))

        invalid_differential = make_record(artifacts=[make_artifact(package_type="differential")])
        errors = validate_v2_record(invalid_differential, raise_on_error=False)
        self.assertTrue(any("kind" in error and "patch" in error for error in errors))

    def test_fixed_fields_urls_and_current_are_required_objects(self):
        empty_urls = make_record()
        empty_urls["artifacts"][0]["urls"] = []
        validate_v2_record(empty_urls)

        for field in ("version_code", "file_time", "artifacts", "references"):
            invalid = make_record()
            invalid.pop(field)
            errors = validate_v2_record(invalid, raise_on_error=False)
            self.assertTrue(any(field in error for error in errors))

        missing_urls = make_record()
        missing_urls["artifacts"][0].pop("urls")
        errors = validate_v2_record(missing_urls, raise_on_error=False)
        self.assertTrue(any("urls" in error and "required" in error for error in errors))

        null_current = make_record()
        null_current["artifacts"][0]["urls"][0]["current"] = None
        errors = validate_v2_record(null_current, raise_on_error=False)
        self.assertTrue(any("current" in error and "object" in error for error in errors))

        non_manifest = make_record()
        non_manifest["artifacts"][0]["manifest"] = {"path": "manifest.json"}
        errors = validate_v2_record(non_manifest, raise_on_error=False)
        self.assertTrue(any("manifest" in error and "file_manifest" in error for error in errors))

    def test_patch_requires_paired_routes_and_known_enums(self):
        valid = make_record(artifacts=[make_artifact(
            kind="patch",
            package_type="differential",
            delivery_mode="archive",
            route_from="1.0.0",
            route_to="1.1.0",
        )])
        validate_v2_record(valid)
        invalid = copy.deepcopy(valid)
        invalid["artifacts"][0].pop("route_to")
        invalid["artifacts"][0]["delivery_mode"] = "mystery"
        errors = validate_v2_record(invalid, raise_on_error=False)
        self.assertTrue(any("route_to" in error and "required" in error for error in errors))
        self.assertTrue(any("delivery_mode" in error and "one of" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
