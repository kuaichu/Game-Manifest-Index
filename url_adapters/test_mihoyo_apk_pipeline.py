import ast
from collections.abc import Mapping
from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id, normalize_legacy_record, validate_v2_record
from url_adapters.android.mihoyo_apk_organizer import (
    MihoyoApkCollection,
    MihoyoApkOrganizationError,
    organize_apk,
)
from url_adapters.android import mihoyo_download_porter


MIHOYO_GAMES = (
    ("hk4e", "MiHoYo official Android download_porter"),
    ("hkrpg", "MiHoYo official Android download_porter"),
    ("nap", "MiHoYo official Android download_porter"),
    ("bh3", "MiHoYo official BH3 Android download_porter"),
    ("bh2", "MiHoYo official BH2 Android download page"),
)


def record(game_id="hk4e", **overrides):
    base = {
        "vendor": "mihoyo",
        "game_id": game_id,
        "platform": "android",
        "channel": "official",
        "version": "7.0.0",
        "version_code": 700,
        "filename": f"{game_id}_7.0.0.apk",
        "url": f"https://cdn.example.test/{game_id}_7.0.0.apk",
        "size": 12,
        "checksum": {"etag": "e", "crc64": "c", "md5": "a" * 32},
        "file_time": None,
        "status": {"http_code": 206, "available": True, "last_checked_at": "2026-08-27T00:00:00Z"},
    }
    base.update(overrides)
    return base


def _legacy_organize_mihoyo_reference(collection: MihoyoApkCollection) -> dict:
    source = deepcopy(dict(collection.record))
    source["provenance"] = {
        "source_kind": "official_sync",
        "source_name": collection.source_name,
        "source_url": collection.source_url,
    }
    output = normalize_legacy_record(source)
    artifact = output["artifacts"][0]
    candidate = artifact["urls"][0]
    candidate["url"] = source["url"]
    candidate["provider"] = "mihoyo"
    candidate["source_kind"] = "official"
    candidate["priority"] = 0
    status = source["status"]
    current = dict(candidate.get("current") or {})
    current["state"] = "available"
    if status.get("http_code") is not None:
        current["http_code"] = status["http_code"]
    if status.get("last_checked_at") is not None:
        current["checked_at"] = status["last_checked_at"]
    size = source.get("size")
    if size is not None:
        artifact["size"] = size
        current["response_size"] = size
    checksum = source.get("checksum")
    if isinstance(checksum, Mapping):
        if checksum.get("etag") is not None:
            current["etag"] = checksum["etag"]
        if checksum.get("crc64") is not None:
            current["crc64"] = checksum["crc64"]
    candidate["current"] = current
    output["references"] = []
    validate_v2_record(output)
    return output


class MihoyoPipelineTests(unittest.TestCase):
    def test_organizer_emits_canonical_official_record(self):
        output = organize_apk(MihoyoApkCollection("https://official.example.test/hk4e", record()))
        validate_v2_record(output)
        self.assertEqual(output["provenance"]["source_kind"], "official_sync")
        self.assertEqual(output["artifacts"][0]["urls"][0]["provider"], "mihoyo")

    def test_discover_persists_v2_record(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            mihoyo_download_porter, "fetch_record", return_value=record()
        ), patch.object(mihoyo_download_porter, "endpoint", return_value="https://official.example/hk4e"):
            path = mihoyo_download_porter.discover("hk4e", Path(directory), 3)
            self.assertTrue(path.exists())
            validate_v2_record(json.loads(path.read_text(encoding="utf-8")))

    def test_organizer_failure_is_wrapped_with_cause(self):
        expected = MihoyoApkOrganizationError("bad collection")
        with patch.object(mihoyo_download_porter, "organize_apk", side_effect=expected):
            with self.assertRaises(mihoyo_download_porter.AdapterError) as raised:
                mihoyo_download_porter.discover_collection(object(), Path("unused"))
        self.assertIs(raised.exception.__cause__, expected)

    def test_native_organizer_matches_legacy_reference_across_all_mihoyo_games_and_optional_fields(self):
        variants = (
            ("full", lambda raw: raw),
            (
                "full_with_sha256_and_file_time",
                lambda raw: {
                    **raw,
                    "file_time": "2026-08-27T01:02:03Z",
                    "checksum": {"etag": "e2", "crc64": "99", "md5": "a" * 32, "sha256": "b" * 64},
                },
            ),
            ("size_none", lambda raw: {**raw, "size": None}),
            ("size_omitted", lambda raw: {k: v for k, v in raw.items() if k != "size"}),
            ("size_zero", lambda raw: {**raw, "size": 0}),
            ("checksum_none", lambda raw: {**raw, "checksum": None}),
            ("checksum_omitted", lambda raw: {k: v for k, v in raw.items() if k != "checksum"}),
            ("checksum_all_null", lambda raw: {**raw, "checksum": {"etag": None, "crc64": None, "md5": None}}),
            ("checksum_etag_only", lambda raw: {**raw, "checksum": {"etag": "only-etag"}}),
            ("checksum_md5_only", lambda raw: {**raw, "checksum": {"md5": "c" * 32}}),
            ("version_code_none", lambda raw: {**raw, "version_code": None}),
            ("version_code_omitted", lambda raw: {k: v for k, v in raw.items() if k != "version_code"}),
            ("file_time_omitted", lambda raw: {k: v for k, v in raw.items() if k != "file_time"}),
            ("minimal_status_and_visibility", lambda raw: {**raw, "status": {"available": True}, "is_visible": False}),
        )
        for game_id, source_name in MIHOYO_GAMES:
            for variant_name, transform in variants:
                with self.subTest(game_id=game_id, variant=variant_name):
                    collection = MihoyoApkCollection(
                        source_url=f"https://official.example.test/{game_id}",
                        record=transform(record(game_id)),
                        source_name=source_name,
                    )
                    output = organize_apk(collection)
                    expected = _legacy_organize_mihoyo_reference(collection)
                    self.assertEqual(output, expected)
                    self.assertEqual(json.dumps(output), json.dumps(expected))
                    artifact = output["artifacts"][0]
                    self.assertEqual(artifact["artifact_id"], artifact_id(artifact, output))
                    self.assertNotIn("source", artifact)
                    if "checksum" in artifact:
                        self.assertNotIn("etag", artifact["checksum"])

    def test_organizer_rejects_invalid_inputs_with_mihoyo_error(self):
        invalid_collections = (
            object(),
            MihoyoApkCollection("ftp://bad.example/hk4e", record()),
            MihoyoApkCollection("https://official.example.test/hk4e", []),  # type: ignore[arg-type]
            MihoyoApkCollection("https://official.example.test/hk4e", record(vendor="kuro")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(platform="windows")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(channel="bilibili")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(filename="game.zip")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(url="not-a-url")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(status={"available": False})),
            MihoyoApkCollection("https://official.example.test/hk4e", record(references=[{"kind": "chunk_manifest", "path": "a"}])),
            MihoyoApkCollection("https://official.example.test/hk4e", record(version="")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(game_id="")),
            MihoyoApkCollection("https://official.example.test/hk4e", record(size=-1)),
            MihoyoApkCollection("https://official.example.test/hk4e", record(checksum={"sha1": "abc"})),
            MihoyoApkCollection("https://official.example.test/hk4e", record(status={"available": True, "extra": 1})),
            MihoyoApkCollection("https://official.example.test/hk4e", record(unexpected_field=1)),
        )
        for item in invalid_collections:
            with self.subTest(item=item):
                with self.assertRaises(MihoyoApkOrganizationError):
                    organize_apk(item)  # type: ignore[arg-type]

    def test_android_adapters_do_not_import_legacy_normalizer_or_private_schema_symbols(self):
        android_dir = Path(__file__).resolve().parent / "android"
        py_files = sorted(android_dir.glob("*.py"))
        self.assertTrue(py_files)
        for path in py_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "backend.legacy_record_normalizer", str(path))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertNotEqual(module, "backend.legacy_record_normalizer", str(path))
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "normalize_legacy_record", str(path))
                        if module.startswith("backend"):
                            self.assertFalse(alias.name.startswith("_"), f"{path}: {alias.name}")


if __name__ == "__main__":
    unittest.main()
