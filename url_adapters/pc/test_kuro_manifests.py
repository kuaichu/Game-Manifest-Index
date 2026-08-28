import gzip
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import validate_v2_record
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import kuro_manifests as km


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def index(resource=None, delete_files=None):
    value = {"resource": resource if resource is not None else [
        {"dest": "Client/bin/game.dat", "md5": "A" * 32, "size": 4}
    ]}
    if delete_files is not None:
        value["deleteFiles"] = delete_files
    return value


def fixture(patch_versions=("3.5.0", "3.4.0")):
    full = index(delete_files=[])
    patch_documents = {
        version: index(
            resource=[{"dest": f"patch/{version}.dat", "md5": "b" * 32, "size": 2}],
            delete_files=[f"old/{version}.dat"],
        )
        for version in patch_versions
    }
    patches = []
    for version, document in patch_documents.items():
        patches.append({
            "version": version,
            "indexFile": f"resource/{version}.json",
            "baseUrl": f"files/patch/{version}/",
            "indexFileMd5": hashlib.md5(encoded(document)).hexdigest(),
            "size": 3,
            "unCompressSize": 5,
            "ext": {},
        })
    config = {
        "version": "3.6.0",
        "indexFile": "resource/full.json",
        "baseUrl": "files/",
        "indexFileMd5": hashlib.md5(encoded(full)).hexdigest(),
        "patchType": "differential",
        "size": 10,
        "unCompressSize": 20,
        "patchConfig": patches,
    }
    cdns = ["https://one.test/root/", "https://two.test/root/", "https://three.test/root/"]
    launcher = {"default": {"config": config, "cdnList": [
        {"P": order, "K1": 0, "K2": 0, "url": url} for order, url in enumerate(cdns)
    ]}}
    return launcher, full, patch_documents


def collected(patch_versions=("3.5.0", "3.4.0")):
    launcher, full, patch_documents = fixture(patch_versions)
    _, config, cdns = km._launcher(launcher)
    documents = [(None, km._index_document(
        full, version=config["version"], route_from=None,
        selected_url=km._safe_url(cdns[0], config["indexFile"]),
    ))]
    for patch_config in config["patchConfig"]:
        version = patch_config["version"]
        documents.append((version, km._index_document(
            patch_documents[version], version=config["version"], route_from=version,
            selected_url=km._safe_url(cdns[0], patch_config["indexFile"]),
        )))
    return km.KuroManifestCollection(config["version"], config, cdns, documents)


class KuroCollectionTests(unittest.TestCase):
    def test_only_wuwa_and_positive_timeout_are_supported(self):
        for game_id in ("pns", "unknown"):
            with self.subTest(game_id=game_id), self.assertRaisesRegex(AdapterError, "只支持 wuwa"):
                km.collect(game_id, 1)
        for timeout in (0, -1, True):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(AdapterError, "正整数"):
                km.collect("wuwa", timeout)

    def test_collect_falls_back_between_official_candidates_and_checks_md5(self):
        launcher, full, patches = fixture(("3.5.0",))
        with patch.object(km, "read_small", side_effect=[
            encoded(launcher).decode("latin-1"),
            "invalid-json",
            encoded(full).decode("latin-1"),
            encoded(patches["3.5.0"]).decode("latin-1"),
        ]) as reader:
            result = km.collect("wuwa", 5)
        self.assertEqual(result.version, "3.6.0")
        self.assertEqual([route for route, _ in result.documents], [None, "3.5.0"])
        self.assertEqual(len(reader.call_args_list), 4)
        self.assertIn("https://two.test/root/resource/full.json", reader.call_args_list[2].args[0])

        wrong = json.loads(json.dumps(launcher))
        wrong["default"]["config"]["indexFileMd5"] = "0" * 32
        with patch.object(km, "read_small", side_effect=[
            encoded(wrong).decode("latin-1"),
            encoded(full).decode("latin-1"),
            encoded(full).decode("latin-1"),
            encoded(full).decode("latin-1"),
        ]), self.assertRaisesRegex(AdapterError, "全部失败"):
            km.collect("wuwa", 5)

    def test_collect_accepts_gzip_encoded_launcher_and_index(self):
        launcher, full, _ = fixture(())
        launcher_body = gzip.compress(encoded(launcher)).decode("latin-1")
        index_body = gzip.compress(encoded(full)).decode("latin-1")
        with patch.object(km, "read_small", side_effect=[launcher_body, index_body]):
            result = km.collect("wuwa", 5)
        self.assertEqual(result.version, "3.6.0")
        self.assertEqual(result.documents[0][1]["resource"][0]["dest"], "Client/bin/game.dat")

    def test_collect_rejects_invalid_or_oversized_gzip(self):
        invalid = b"\x1f\x8bnot-gzip".decode("latin-1")
        oversized = gzip.compress(b"x" * (km.MAX_JSON_BYTES + 1)).decode("latin-1")
        for body, message in ((invalid, "gzip"), (oversized, "2MiB")):
            with self.subTest(message=message), patch.object(km, "read_small", return_value=body):
                with self.assertRaisesRegex(AdapterError, message):
                    km.collect("wuwa", 5)

    def test_launcher_and_direct_collection_validation_are_strict(self):
        launcher, _, _ = fixture()
        bad_launchers = [
            {},
            {"default": {"config": None, "cdnList": []}},
            {"default": {**launcher["default"], "cdnList": []}},
        ]
        for value in bad_launchers:
            with self.subTest(value=value), self.assertRaises(AdapterError):
                km._launcher(value)
        duplicate_patch = json.loads(json.dumps(launcher))
        duplicate_patch["default"]["config"]["patchConfig"][1]["version"] = "3.5.0"
        with self.assertRaisesRegex(AdapterError, "version"):
            km._launcher(duplicate_patch)
        duplicate_cdn = json.loads(json.dumps(launcher))
        duplicate_cdn["default"]["cdnList"][1]["url"] = duplicate_cdn["default"]["cdnList"][0]["url"]
        with self.assertRaisesRegex(AdapterError, "重复"):
            km._launcher(duplicate_cdn)

        base = collected()
        invalid = [
            (object(), "类型"),
            (replace(base, launcher_url="https://third-party.test"), "launcher_url"),
            (replace(base, version="../bad"), "version"),
            (replace(base, documents=base.documents[:-1]), "documents"),
            (replace(base, documents=[("wrong", base.documents[0][1]), *base.documents[1:]]), "route"),
        ]
        for value, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(AdapterError, message):
                km.organize(value)


class KuroOrganizationTests(unittest.TestCase):
    def test_record_maps_full_and_patches_with_three_cdns(self):
        source = collected()
        record = km.organize(source)
        validate_v2_record(record)
        self.assertEqual(len(record["artifacts"]), 3)
        full, *patches = record["artifacts"]
        self.assertEqual((full["kind"], full["package_type"], full["delivery_mode"]),
                         ("package", "full", "file_manifest"))
        self.assertEqual([item["route_from"] for item in patches], ["3.5.0", "3.4.0"])
        self.assertTrue(all(item["route_to"] == "3.6.0" for item in patches))
        self.assertEqual(len(full["urls"]), 3)
        self.assertEqual(len(full["manifest"]["base_urls"]), 3)
        self.assertTrue(all("current" not in item for item in full["manifest"]["base_urls"]))
        self.assertNotIn("checksum", full)
        forbidden = ("kuro_manifest", "attributes", "status", "evidence_status", "indexFileMd5")
        serialized = json.dumps(record)
        self.assertTrue(all(field not in serialized for field in forbidden))

    def test_index_normalization_rejects_unsafe_duplicate_and_bad_fields(self):
        invalid = [
            ({"resource": [{"dest": "../x", "md5": "a" * 32, "size": 0}]}, "dest"),
            ({"resource": [{"dest": "a//b", "md5": "a" * 32, "size": 0}]}, "dest"),
            ({"resource": [{"dest": "x", "md5": "bad", "size": 0}]}, "md5"),
            ({"resource": [{"dest": "x", "md5": "a" * 32, "size": True}]}, "size"),
            ({"resource": [{"dest": "x", "md5": "a" * 32, "size": 0},
                           {"dest": "x", "md5": "b" * 32, "size": 1}]}, "重复"),
            ({"resource": [], "deleteFiles": ["x", "x"]}, "重复"),
        ]
        for payload, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(AdapterError, message):
                km._index_document(payload, version="1.0.0", route_from=None,
                                   selected_url="https://cdn.test/index.json")

    def test_artifact_identity_is_stable_for_cdn_and_size_changes(self):
        first = km.organize(collected())["artifacts"][0]
        source = collected()
        changed_config = dict(source.config)
        changed_config["size"] = 999
        changed = replace(source, config=changed_config,
                          cdns=["https://other.test/root/", *source.cdns[1:]])
        changed_documents = []
        for route, document in changed.documents:
            item_config = changed_config if route is None else next(
                item for item in changed_config["patchConfig"] if item["version"] == route
            )
            updated = dict(document)
            updated["provenance"] = dict(
                updated["provenance"],
                source_url=km._safe_url("https://other.test/root/", item_config["indexFile"]),
            )
            changed_documents.append((route, updated))
        changed = replace(changed, documents=changed_documents)
        second = km.organize(changed)["artifacts"][0]
        self.assertEqual(first["artifact_id"], second["artifact_id"])


class KuroPersistenceTests(unittest.TestCase):
    def test_documents_and_record_are_written_and_references_preserved(self):
        source = collected(("3.5.0",))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = km.organize(source)
            existing["references"] = [{
                "kind": "chunk_manifest", "path": "chunk-manifests/3.6.0.json",
                "source": {"source_kind": "official_sync", "source_name": "existing"},
            }]
            persist_v2_record(existing, root)
            path = km.discover_collection(source, root)
            record = json.loads(path.read_text(encoding="utf-8"))
            full = root / "kuro/wuwa/pc/manifests/3.6.0/full.json"
            patch_path = root / "kuro/wuwa/pc/manifests/3.6.0/patches/3.5.0.json"
            full_exists = full.is_file()
            patch_exists = patch_path.is_file()
        self.assertTrue(full_exists)
        self.assertTrue(patch_exists)
        self.assertEqual(record["references"], existing["references"])

    def test_record_failure_keeps_existing_record_and_leaves_orphan_documents(self):
        source = collected(("3.5.0",))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = persist_v2_record(km.organize(source), root)
            before = record_path.read_bytes()
            with patch.object(km, "persist_v2_record", side_effect=VersionStoreError("blocked")):
                with self.assertRaisesRegex(AdapterError, "blocked"):
                    km.discover_collection(source, root)
            self.assertEqual(record_path.read_bytes(), before)
            self.assertTrue((root / "kuro/wuwa/pc/manifests/3.6.0/full.json").exists())

    def test_atomic_replace_failure_keeps_old_document_and_cleans_temp(self):
        source = collected(())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            km.discover_collection(source, root)
            target = root / "kuro/wuwa/pc/manifests/3.6.0/full.json"
            before = target.read_bytes()
            with patch.object(km.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(AdapterError, "安全写入"):
                    km.discover_collection(source, root)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(target.parent.glob(target.name + ".*")), [])

    def test_symlinked_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            try:
                os.symlink(external, root / "kuro", target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(AdapterError, "不安全"):
                km.discover_collection(collected(()), root)


if __name__ == "__main__":
    unittest.main()
