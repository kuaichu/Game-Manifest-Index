import base64
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
from unittest.mock import MagicMock, patch

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


def config(version="1.2.3", res_config=None) -> bytes:
    extra = "" if res_config is None else f"<ResConfig>{res_config}</ResConfig>"
    return f"<Config><ResVersion>{version}</ResVersion><ResSize>99</ResSize><Hash>abc</Hash><Compressed>true</Compressed><Encrypt>true</Encrypt><BaseVerson>1.2.2</BaseVerson>{extra}</Config>".encode()


def branch_config(branch="PC_140", **overrides) -> str:
    value = {"gameResUrl": ["https://yhcdn2.wmupd.com/clientRes", "https://yhcdn1.wmupd.com/clientRes"], "branchName": branch, "updateBranchName": "publish_Updata", "appId": 1289, **overrides}
    return base64.b64encode(json.dumps(value).encode()).decode()


class PerfectWorldTests(unittest.TestCase):
    def test_nte_dynamic_default_fetcher_uses_bounded_transport(self):
        profile = pw.PROFILES["nte"]
        active = replace(profile, base_path="/clientRes/PC_140", root_url="https://yhcdn1.wmupd.com/clientRes/PC_140/Res/")
        bodies = {profile.config_url: config("1.3.16", branch_config()), active.config_url: config("1.4.9", branch_config()), active.reslist_url("1.4.9"): archive(active)}
        calls = []
        def transport(request, timeout):
            url = request.full_url
            calls.append(url)
            body = bodies[url]
            response = MagicMock()
            response.status = 200
            response.headers = {"Content-Length": str(len(body))}
            response.geturl.return_value = url
            response.read.side_effect = io.BytesIO(body).read
            response.__enter__.return_value = response
            return response
        with patch.object(pw.urllib.request, "urlopen", side_effect=transport):
            collection = pw.collect("nte", 5)
        self.assertEqual(calls, list(bodies))
        self.assertEqual(collection.version, "1.4.9")

    def test_resconfig_rejection_never_requests_old_manifest(self):
        profile = pw.PROFILES["nte"]
        bad = ["not base64", base64.b64encode(b"[]").decode(), "A" * (pw.MAX_RESCONFIG_BYTES + 1)]
        bad += [branch_config(branch) for branch in ("../PC_140", "PC_140/evil", "PC_%31", "Windows55", "publish_PC", "PC_140?x", "PC_140#x")]
        bad += [branch_config(appId=value) for value in (1264, True, 1289.0, None)]
        bad += [branch_config(gameResUrl=urls) for urls in ([], ["https://yhcdn2.wmupd.com/clientRes"], "https://yhcdn1.wmupd.com/clientRes", ["https://evil.example/clientRes"], ["https://yhcdn1.wmupd.com/clientRes/../x"], ["https://yhcdn1.wmupd.com:444/clientRes"], ["https://yhcdn1.wmupd.com/clientRes?x"], ["https://yhcdn1.wmupd.com/clientRes%2f"]) ]
        duplicate = base64.b64encode(b'{"branchName":"PC_140","branchName":"PC_150","gameResUrl":[]}').decode()
        bad.append(duplicate)
        for value in bad:
            with self.subTest(value=value[:100]):
                calls = []
                def fetch(url, timeout):
                    calls.append(url)
                    return config("1.3.16", value)
                with self.assertRaisesRegex(AdapterError, "ResConfig"):
                    pw.collect("nte", 5, fetcher=fetch)
                self.assertEqual(calls, [profile.config_url])
        for raw in (b"<ResConfig />", b"<ResConfig>A</ResConfig><ResConfig>B</ResConfig>"):
            body = config().replace(b"</Config>", raw + b"</Config>")
            with self.assertRaisesRegex(AdapterError, "ResConfig"):
                pw.collect("nte", 5, fetcher=lambda url, timeout: body)

    def test_branch_chains_are_followed_and_bounded(self):
        profile = pw.PROFILES["nte"]
        def active(branch):
            return replace(profile, base_path=f"/clientRes/{branch}", root_url=f"https://{profile.host}/clientRes/{branch}/Res/")
        first, latest = active("PC_140"), active("PC_150")
        bodies = {profile.config_url: config("1.3.16", branch_config()), first.config_url: config("1.4.9", branch_config("PC_150")), latest.config_url: config("1.5.1", branch_config("PC_150")), latest.reslist_url("1.5.1"): archive(latest)}
        collection = pw.collect("nte", 5, fetcher=lambda url, timeout: bodies[url])
        self.assertEqual(collection.config_url, latest.config_url)
        bodies[latest.config_url] = config("1.5.1", branch_config("PC_140"))
        with self.assertRaisesRegex(AdapterError, "循环"):
            pw.collect("nte", 5, fetcher=lambda url, timeout: bodies[url])
        bodies[latest.config_url] = config("1.5.1", branch_config("PC_160"))
        bodies[active("PC_160").config_url] = config("1.6.1", branch_config("PC_170"))
        with self.assertRaisesRegex(AdapterError, "超过限制"):
            pw.collect("nte", 5, fetcher=lambda url, timeout: bodies[url])
        def failed_branch(url, timeout):
            if url != profile.config_url:
                raise AdapterError("官方请求失败")
            return config("1.3.16", branch_config())
        with self.assertRaisesRegex(AdapterError, "官方请求失败"):
            pw.collect("nte", 5, fetcher=failed_branch)

    def test_other_games_ignore_resconfig_and_keep_old_profiles(self):
        for game in ("p5x", "tof"):
            profile = pw.PROFILES[game]
            bodies = {profile.config_url: config(res_config="not-base64"), profile.reslist_url("1.2.3"): archive(profile)}
            collection = pw.collect(game, 5, fetcher=lambda url, timeout: bodies[url])
            self.assertEqual(collection.config_url, profile.config_url)
            self.assertIsNone(collection.bootstrap_config_url)
            self.assertNotIn("bootstrap_config_url", pw._document(collection))

    def test_manifest_url_matcher_rejects_unsafe_dynamic_urls(self):
        good = "https://yhcdn1.wmupd.com/clientRes/PC_150/Version/Windows/config.xml"
        self.assertIsNotNone(pw.manifest_profile_for_url(good, "nte"))
        self.assertIsNone(pw.manifest_profile_for_url(good, "p5x"))
        for url in (good + "?", good + "#", good.replace("PC_150", "%50C_150"), good.replace("PC_150", "../PC_150"), good.replace("yhcdn1", "yhcdn2"), good.replace("yhcdn1.wmupd.com", "yhcdn1.wmupd.com:444"), good.replace("https://", "https://u@"), good + "\n"):
            with self.subTest(url=url):
                self.assertIsNone(pw.manifest_profile_for_url(url, "nte"))

    def test_nte_bootstrap_discovers_current_and_future_branch(self):
        original = pw.PROFILES["nte"]
        for branch, version in (("PC_140", "1.4.9"), ("PC_150", "1.5.1")):
            with self.subTest(branch=branch):
                active = replace(original, base_path=f"/clientRes/{branch}", root_url=f"https://{original.host}/clientRes/{branch}/Res/")
                bodies = {original.config_url: config("1.3.16", branch_config(branch)), active.config_url: config(version, branch_config(branch)), active.reslist_url(version): archive(active, encrypted=True)}
                calls = []
                def fetch(url, timeout):
                    calls.append(url)
                    return bodies[url]
                collection = pw.collect("nte", 5, fetcher=fetch)
                self.assertEqual(calls, [original.config_url, active.config_url, active.reslist_url(version)])
                self.assertEqual(collection.version, version)
                self.assertEqual(collection.config_url, active.config_url)
                self.assertEqual(collection.root_url, active.root_url)
                self.assertEqual(collection.bootstrap_config_url, original.config_url)
                record = pw.organize(collection)
                self.assertEqual(record["provenance"]["source_url"], active.config_url)
                self.assertEqual(record["artifacts"][0]["urls"][0]["url"], active.reslist_url(version))
                with tempfile.TemporaryDirectory() as directory:
                    pw.discover_collection(collection, Path(directory))
                    document = json.loads((Path(directory) / f"perfectworld/nte/pc/manifests/{version}/files.json").read_text(encoding="utf-8"))
                    self.assertEqual(document["bootstrap_config_url"], original.config_url)
                for changed in (replace(collection, root_url=original.root_url), replace(collection, reslist_url=original.reslist_url(version)), replace(collection, bootstrap_config_url=None)):
                    with self.assertRaises(AdapterError):
                        pw.organize(changed)
        self.assertIs(pw.PROFILES["nte"], original)

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
