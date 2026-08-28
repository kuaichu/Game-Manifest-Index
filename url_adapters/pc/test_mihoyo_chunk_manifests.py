import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import mihoyo_chunk_manifests as chunks
from url_adapters.pc import mihoyo_game_packages
from url_adapters.pc.mihoyo_package_organizer import GAME_IDENTITIES, MihoyoPackageCollection, package_source_url


SECRET = "SECRET_NOT_FOR_OUTPUT"


def manifest(matching_field="game", marker="1"):
    return {
        "category_id": "7", "category_name": "main",
        "manifest": {"id": f"manifest-{marker}", "checksum": f"checksum-{marker}",
                     "compressed_size": "10", "uncompressed_size": 20},
        "matching_field": matching_field,
        "stats": {"compressed_size": "11", "file_count": 2, "chunk_count": "3"},
        "deduplicated_stats": {"chunk_count": "1"},
        "manifest_download": {"url_prefix": "https://cdn.example.test/manifests/",
                              "url_suffix": ".bin", "compression": 0, "encryption": 1,
                              "password": SECRET},
        "chunk_download": {"url_prefix": "https://cdn.example.test/chunks/",
                           "compression": 0, "encryption": 0, "password": SECRET},
    }


def responses(game_id="hk4e", tag="5.5.0", manifests=None):
    hoyoplay_id, biz = GAME_IDENTITIES[game_id]
    branches = {"retcode": 0, "data": {"game_branches": [{
        "game": {"id": hoyoplay_id, "biz": biz},
        "main": {"branch": "main", "package_id": "package-id", "password": SECRET,
                 "tag": tag, "diff_tags": ["5.4.0"]},
    }]}}
    build = {"retcode": 0, "data": {"build_id": "build-id", "tag": tag,
                                      "manifests": manifests if manifests is not None else [manifest()]}}
    return branches, build


def collection(game_id="hk4e", tag="5.5.0", manifests=None):
    _, build = responses(game_id, tag, manifests)
    return chunks.MihoyoChunkCollection(
        game_id=game_id, hoyoplay_game_id=GAME_IDENTITIES[game_id][0], branch="main",
        package_id="package-id", tag=tag, diff_tags=["5.4.0"], build_id="build-id",
        manifests=build["data"]["manifests"],
    )


def package_collection(game_id="hk4e", version="5.5.0"):
    hoyoplay_id, biz = GAME_IDENTITIES[game_id]
    return MihoyoPackageCollection(
        game_id=game_id, hoyoplay_game_id=hoyoplay_id, source_url=package_source_url(game_id),
        payload={"retcode": 0, "data": {"game_packages": [{
            "game": {"id": hoyoplay_id, "biz": biz},
            "main": {"major": {"version": version, "game_pkgs": [{
                "url": f"https://cdn.example.test/Game_{version}.zip", "md5": "a" * 32,
                "size": "12", "decompressed_size": "20",
            }], "audio_pkgs": []}, "patches": []}, "pre_download": None,
        }]}},
    )


class ChunkCollectionTests(unittest.TestCase):
    def test_collect_four_ids_and_keeps_secret_only_in_second_request(self):
        for game_id in GAME_IDENTITIES:
            branches, build = responses(game_id)
            with self.subTest(game_id=game_id), patch.object(
                chunks, "read_small", side_effect=[json.dumps(branches), json.dumps(build)]
            ) as reader:
                result = chunks.collect(game_id, 3)
            self.assertEqual(parse_qs(urlsplit(reader.call_args_list[0].args[0]).query), {
                "launcher_id": ["jGHBHlcOq1"], "game_ids[]": [GAME_IDENTITIES[game_id][0]],
            })
            build_query = parse_qs(urlsplit(reader.call_args_list[1].args[0]).query)
            self.assertEqual(build_query["password"], [SECRET])
            self.assertEqual(build_query["plat_app"], ["ddxf5qt290cg"])
            self.assertNotIn(SECRET, repr(result))
            self.assertEqual(result.source_url, chunks.BUILD_URL)

    def test_collect_rejects_invalid_json_response_and_build_shape(self):
        branches, build = responses()
        cases = [(["{"], "getGameBranches"),
                 ([json.dumps(branches), "{"], "getBuild"),
                 ([json.dumps({"retcode": None, "data": {}})], "retcode"),
                 ([json.dumps({"retcode": 0})], "data"),
                 ([json.dumps({"retcode": 0, "data": []})], "data")]
        for side_effect, message in cases:
            with self.subTest(message=message), patch.object(chunks, "read_small", side_effect=side_effect), self.assertRaisesRegex(AdapterError, message):
                chunks.collect("hk4e")
        bad_builds = [{**build, "data": {**build["data"], "tag": "other"}},
                      {**build, "data": {**build["data"], "manifests": []}},
                      {**build, "data": {**build["data"], "build_id": ""}}]
        for bad in bad_builds:
            with self.subTest(bad=bad["data"]), patch.object(
                chunks, "read_small", side_effect=[json.dumps(branches), json.dumps(bad)]
            ), self.assertRaises(AdapterError):
                chunks.collect("hk4e")
        wrong = json.loads(json.dumps(branches))
        wrong["data"]["game_branches"][0]["game"]["biz"] = "hk4e_global"
        with patch.object(chunks, "read_small", return_value=json.dumps(wrong)), self.assertRaisesRegex(AdapterError, "唯一 main"):
            chunks.collect("hk4e")

    def test_direct_collection_identity_and_safe_tag_are_strict(self):
        base = collection()
        invalid = [(object(), "类型"), (replace(base, game_id="unknown"), "不支持"),
                   (replace(base, hoyoplay_game_id="wrong"), "不匹配"),
                   (replace(base, branch=""), "branch"),
                   (replace(base, source_url="https://third-party.test"), "source_url"),
                   (replace(base, diff_tags=[""]), "diff_tags"), (replace(base, manifests=[]), "manifests")]
        for value, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(AdapterError, message):
                chunks.organize(value)
        for tag in ("..", "bad.", "bad ", "bad\x01", "COM1", "bad/name"):
            with self.subTest(tag=tag), self.assertRaisesRegex(AdapterError, "tag"):
                chunks.organize(replace(base, tag=tag))


class ChunkOrganizationTests(unittest.TestCase):
    def test_organize_normalizes_components_numbers_and_removes_secrets(self):
        source = collection(manifests=[manifest("game", "g"), manifest("zh-cn", "v"), manifest("resource", "r")])
        document = chunks.organize(source)
        items = document["manifests"]
        self.assertEqual([(item["component"], item["language"]) for item in items],
                         [("game", None), ("voice", "zh-cn"), ("resource", None)])
        self.assertEqual(items[0]["category"]["id"], 7)
        self.assertEqual(items[0]["manifest"]["compressed_size"], 10)
        self.assertEqual(items[0]["stats"]["chunk_count"], 3)
        self.assertEqual(items[0]["deduplicated_stats"]["chunk_count"], 1)
        for item in items:
            for recipe in (item["manifest_download"], item["chunk_download"]):
                self.assertEqual(set(recipe), {"url_prefix", "url_suffix", "compression", "encryption"})
        serialized = json.dumps(document, ensure_ascii=False)
        self.assertNotIn(SECRET, serialized)
        self.assertNotIn("password", serialized)
        record = chunks._record(source)
        validate_v2_record(record)
        self.assertNotIn(SECRET, json.dumps(record, ensure_ascii=False))

    def test_organize_rejects_invalid_manifest_stats_and_recipes(self):
        base = manifest()
        invalid = [({**base, "manifest": None}, "manifest"), ({**base, "stats": []}, "stats"),
                   ({key: value for key, value in base.items() if key != "manifest_download"}, "manifest_download"),
                   ({**base, "manifest_download": {"url_prefix": "http://bad"}}, "https URL"),
                   ({**base, "manifest_download": {"url_prefix": "https://user:secret@cdn.test"}}, "https URL"),
                   ({**base, "chunk_download": {"url_prefix": "https://cdn.test", "compression": True}}, "compression")]
        for item, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex(AdapterError, message):
                chunks.organize(collection(manifests=[item]))


class ChunkPersistenceTests(unittest.TestCase):
    def test_chunk_refresh_preserves_existing_artifacts_and_provenance(self):
        source = collection()
        existing = chunks._record(source)
        artifact = {"kind": "package", "component": "game", "package_type": "full",
                    "delivery_mode": "archive", "name": "Game.zip", "urls": [{
                        "url": "https://cdn.example.test/Game.zip", "provider": "mihoyo",
                        "source_kind": "official", "priority": 0}]}
        artifact["artifact_id"] = artifact_id(artifact, existing)
        existing["artifacts"] = [artifact]
        existing["provenance"] = {"source_kind": "manual", "source_name": "keep"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            persist_v2_record(existing, root)
            path = chunks.discover_collection(source, root)
            updated = json.loads(path.read_text(encoding="utf-8"))
            document = json.loads((root / "mihoyo/hk4e/pc/chunk-manifests/5.5.0.json").read_text(encoding="utf-8"))
        self.assertEqual(updated["artifacts"], existing["artifacts"])
        self.assertEqual(updated["provenance"], existing["provenance"])
        self.assertEqual(updated["references"][0]["build_id"], "build-id")
        validate_v2_record(updated)
        self.assertNotIn(SECRET, json.dumps(document, ensure_ascii=False))

    def test_archive_refresh_preserves_existing_chunk_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks.discover_collection(collection(), root)
            path = mihoyo_game_packages.discover_collection(package_collection(), root)
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["references"][0]["kind"], "chunk_manifest")
        self.assertEqual(record["references"][0]["build_id"], "build-id")
        self.assertEqual({item["kind"] for item in record["artifacts"]}, {"package"})

    def test_record_failure_leaves_old_record_unchanged_and_manifest_orphan(self):
        source = collection()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = persist_v2_record(chunks._record(source), root)
            before = record_path.read_bytes()
            with patch.object(chunks, "persist_v2_record", side_effect=VersionStoreError("blocked")):
                with self.assertRaisesRegex(AdapterError, "blocked"):
                    chunks.discover_collection(source, root)
            self.assertEqual(record_path.read_bytes(), before)
            manifest_path = root / "mihoyo/hk4e/pc/chunk-manifests/5.5.0.json"
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["build_id"], "build-id")

    def test_atomic_replace_failure_keeps_previous_manifest_and_cleans_temp(self):
        source = collection()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunks.discover_collection(source, root)
            target = root / "mihoyo/hk4e/pc/chunk-manifests/5.5.0.json"
            before = target.read_bytes()
            with patch.object(chunks.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(AdapterError, "安全写入"):
                    chunks.discover_collection(replace(source, build_id="new-build"), root)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(target.parent.glob(target.name + ".*")), [])

    def test_symlinked_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            try:
                os.symlink(external, root / "mihoyo", target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            with self.assertRaisesRegex(AdapterError, "不安全"):
                chunks.discover_collection(collection(), root)


if __name__ == "__main__":
    unittest.main()
