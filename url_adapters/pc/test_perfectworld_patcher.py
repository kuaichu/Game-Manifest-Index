import io
import json
import os
import tempfile
import unittest
import zipfile
import zlib
from dataclasses import replace
from pathlib import Path
from urllib.parse import urljoin
from unittest.mock import patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from backend.schema_v2 import validate_v2_record
from backend.version_store import VersionStoreError, persist_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import perfectworld_patcher as pw


def protected(payload: bytes, seed: str) -> bytes:
    key = seed.encode()[:16].ljust(16, b"0")
    iv = b"PatcherSDK".ljust(16, b"0")
    return pw.MAGIC + len(payload).to_bytes(4, "little") + AES.new(key, AES.MODE_CBC, iv).encrypt(pad(zlib.compress(payload), 16))


def archive(profile: pw.Profile, encrypted=False, files=None, patches=True) -> bytes:
    files = files or [("Client/game.dat", "a" * 32, "4")]
    res = "<ResList>" + "".join(f'<Res filename="{name}" md5="{md5}" filesize="{size}" />' for name, md5, size in files) + "</ResList>"
    patch = '<PatchList><Patch oldfile="' + "b" * 32 + '.1" newfile="' + "c" * 32 + '.2" patch="' + "d" * 32 + '.3" v="1" /></PatchList>' if patches else "<PatchList />"
    res_data = protected(res.encode(), profile.key_seed) if encrypted else res.encode()
    patch_data = protected(patch.encode(), profile.key_seed) if encrypted else patch.encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ResList.bin", res_data)
        zf.writestr("PatchList.bin", patch_data)
    return stream.getvalue()


def config(version="1.2.3") -> bytes:
    return f"<Config><ResVersion>{version}</ResVersion><ResSize>99</ResSize><Hash>abc</Hash><Compressed>true</Compressed><Encrypt>true</Encrypt><BaseVerson>1.2.2</BaseVerson></Config>".encode()


class PerfectWorldTests(unittest.TestCase):
    def test_decode_and_parse_encrypted_manifest(self):
        profile = pw.PROFILES["nte"]
        files, patches = pw.parse_reslist(archive(profile, encrypted=True), profile)
        self.assertEqual(files, [{"dest": "Client/game.dat", "md5": "a" * 32, "size": 4, "object": "a/" + "a" * 32 + ".4"}])
        self.assertEqual(patches[0]["patch"], "d" * 32 + ".3")
        self.assertEqual(patches[0]["object"], "d/" + "d" * 32 + ".3")

    def test_profiles_and_timeout_are_strict(self):
        for game in ("unknown", "wuwa"):
            with self.assertRaisesRegex(AdapterError, "只支持"):
                pw.collect(game, 1)
        with self.assertRaisesRegex(AdapterError, "正整数"):
            pw.collect("nte", 0)
        with self.assertRaisesRegex(pw.PerfectWorldError, "官方"):
            pw.fetch_bounded("https://example.test/x", 1, max_bytes=10)

    def test_collect_organize_and_persist_one_canonical_artifact(self):
        profile = pw.PROFILES["nte"]
        bodies = {profile.config_url: config(), profile.reslist_url("1.2.3"): archive(profile)}
        def fetch(url, timeout):
            self.assertEqual(timeout, 5)
            return bodies[url]
        collection = pw.collect("nte", 5, fetcher=fetch)
        record = pw.organize(collection)
        validate_v2_record(record)
        self.assertEqual(len(record["artifacts"]), 1)
        artifact = record["artifacts"][0]
        self.assertEqual((artifact["kind"], artifact["component"], artifact["package_type"], artifact["delivery_mode"]), ("package", "game", "full", "file_manifest"))
        self.assertNotIn("checksum", artifact)
        self.assertEqual(artifact["size"], 4)
        self.assertEqual(artifact["name"], "ResList.bin.zip")
        self.assertEqual(artifact["urls"][0]["url"], profile.reslist_url("1.2.3"))
        self.assertEqual(artifact["manifest"]["base_urls"][0]["url"], profile.root_url)
        self.assertEqual(urljoin(profile.root_url, "a/" + "a" * 32 + ".4"), "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/a/" + "a" * 32 + ".4")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = pw.organize(collection)
            existing["references"] = [{
                "kind": "chunk_manifest",
                "path": "chunk-manifests/1.2.3.json",
                "source": {"source_kind": "official_sync", "source_name": "existing"},
            }]
            persist_v2_record(existing, root)
            path = pw.discover_collection(collection, root)
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["references"], existing["references"])
            document_path = Path(directory) / "perfectworld/nte/pc/manifests/1.2.3/files.json"
            document = json.loads(document_path.read_text(encoding="utf-8"))
            self.assertEqual(document["files"][0]["object"], "a/" + "a" * 32 + ".4")
            self.assertEqual(document["patch_objects"][0]["oldfile"], "b" * 32 + ".1")
            self.assertEqual(document["patch_objects"][0]["object"], "d/" + "d" * 32 + ".3")
            self.assertEqual(urljoin(profile.root_url, document["patch_objects"][0]["object"]), "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/d/" + "d" * 32 + ".3")
            self.assertEqual(document["config"]["config_response_size"], len(config()))
            self.assertNotIn('"urls"', json.dumps(document))

        changed = replace(collection, config={**collection.config, "hash": "changed"}, config_size=999, reslist_size=888)
        self.assertEqual(record["artifacts"][0]["artifact_id"], pw.organize(changed)["artifacts"][0]["artifact_id"])

        invalid = [
            replace(collection, config={**collection.config, "unexpected": "x"}),
            replace(collection, config={**collection.config, "version": "other"}),
            replace(collection, config_url="https://evil.example/config.xml"),
            replace(collection, root_url=profile.root_url.rstrip("/")),
            replace(collection, files=[{**collection.files[0], "object": "a" * 32 + ".4"}]),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(AdapterError):
                pw.organize(value)

    def test_parser_rejects_unsafe_and_duplicate_entries(self):
        profile = pw.PROFILES["p5x"]
        for name in ("../bad", "a//b", "/root", "C:/bad", "https://bad"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(pw.PerfectWorldError, "不安全"):
                    pw.parse_reslist(archive(profile, files=[(name, "a" * 32, "1")], patches=False), profile)
        with self.assertRaisesRegex(pw.PerfectWorldError, "重复"):
            pw.parse_reslist(archive(profile, files=[("a", "a" * 32, "1"), ("a", "b" * 32, "2")], patches=False), profile)

    def test_atomic_document_failure_and_record_failure(self):
        profile = pw.PROFILES["tof"]
        bodies = {profile.config_url: config("6.3.3"), profile.reslist_url("6.3.3"): archive(profile)}
        collection = pw.collect("tof", 2, fetcher=lambda url, timeout: bodies[url])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pw.discover_collection(collection, root)
            target = root / "perfectworld/tof/pc/manifests/6.3.3/files.json"
            before = target.read_bytes()
            with patch.object(pw.os, "replace", side_effect=OSError("no")), self.assertRaisesRegex(AdapterError, "安全写入"):
                pw.discover_collection(collection, root)
            self.assertEqual(target.read_bytes(), before)
            with patch.object(pw, "persist_v2_record", side_effect=VersionStoreError("blocked")), self.assertRaisesRegex(AdapterError, "blocked"):
                pw.discover_collection(collection, root)

    def test_symlinked_output_directory_is_rejected(self):
        profile = pw.PROFILES["nte"]
        bodies = {profile.config_url: config(), profile.reslist_url("1.2.3"): archive(profile)}
        collection = pw.collect("nte", 2, fetcher=lambda url, timeout: bodies[url])
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            root = Path(directory)
            try:
                os.symlink(external, root / "perfectworld", target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(AdapterError, "不安全"):
                pw.discover_collection(collection, root)


if __name__ == "__main__":
    unittest.main()
