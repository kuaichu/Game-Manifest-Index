import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import persist_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import hypergryph_game_packages as hg


AUTH = "auth_key=1790964096-" + "a" * 32 + "-0-" + "b" * 32
ROTATED_AUTH = "auth_key=1790967696-" + "c" * 32 + "-0-" + "d" * 32


def fixture(game="arknights"):
    code, host, prefix = hg.GAME_IDENTITIES[game]
    version = "77.0.0" if game == "arknights" else "1.5.3"
    major = ".".join(version.split(".")[:2])
    base = f"https://{host}/{code}/{major}/update/1/1/Windows/{version}_testToken/packs/"
    packs = [{"url": base + prefix + "official.zip." + f"{part:03}"
              + ("?" + AUTH if game == "endfield" else ""),
              "md5": "A" * 32, "package_size": str(part * 10)} for part in (1, 2)]
    payload = {"seq": "5", "proxy_rsps": [{"kind": "get_latest_game", "get_latest_game_rsp": {
        "version": version, "client_version": "999.0.0", "pkg": {"packs": packs, "total_size": "999"},
        "patch": {"packs": [{"url": "https://invalid.example/patch"}]},
        "pre_patch": {"version": "999.0.0", "pkg": {"packs": []}},
    }}]}
    return hg.HypergryphPackageCollection(game, hg.SOURCE_URL, payload)


def packs(collection):
    return collection.payload["proxy_rsps"][0]["get_latest_game_rsp"]["pkg"]["packs"]


class HypergryphPackageTests(unittest.TestCase):
    def test_complete_packages_both_games_keep_canonical_path_and_no_probe_claim(self):
        for game in hg.GAMES:
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                collection = fixture(game)
                record = hg.organize(collection)
                validate_v2_record(record)
                self.assertEqual(record["domain_id"], game + "-pc")
                self.assertEqual(record["platform"], "windows")
                self.assertEqual(record["version"], "77.0.0" if game == "arknights" else "1.5.3")
                self.assertEqual(record["provenance"]["source_url"], hg.SOURCE_URL)
                self.assertEqual(record["provenance"]["source_kind"], "official_sync")
                self.assertEqual([item["part"] for item in record["artifacts"]], [1, 2])
                for artifact in record["artifacts"]:
                    self.assertEqual(artifact["artifact_id"], artifact_id(artifact, record))
                    self.assertEqual(artifact["checksum"], {"md5": "a" * 32})
                    self.assertNotIn("current", artifact["urls"][0])
                    self.assertEqual(artifact["kind"], "package")
                    self.assertEqual(artifact["source"]["source_url"], hg.SOURCE_URL)
                path = hg.discover_collection(collection, Path(tmp))
                self.assertEqual(path, Path(tmp) / "hypergryph" / game / "pc" / (record["version"] + ".json"))
                self.assertFalse((path.parent / "index.json").exists())

    def test_collect_posts_official_request_and_limits_transport(self):
        for game in hg.GAMES:
            with self.subTest(game=game), patch.object(hg, "curl", return_value=json.dumps(fixture(game).payload)) as curl:
                result = hg.collect(game, 17)
                self.assertEqual(result.game_id, game)
                args, timeout = curl.call_args.args
                self.assertEqual(timeout, 17)
                self.assertEqual(args[-1], hg.SOURCE_URL)
                self.assertEqual(args[args.index("--max-filesize") + 1], "1048576")
                self.assertEqual(args[args.index("--proto") + 1], "=https")
                self.assertNotIn("-L", args)
                self.assertNotIn("--insecure", args)
                req = json.loads(args[args.index("--data") + 1])
                request = req["proxy_reqs"][0]["get_latest_game_req"]
                self.assertEqual(request, {"appcode": hg.GAME_IDENTITIES[game][0], "channel": "1",
                                           "sub_channel": "1", "version": "", "launcher_appcode": hg.LAUNCHER_APPCODE})

    def test_api_and_transport_errors_never_write(self):
        invalid_payloads = ["not json", "[]", json.dumps({"code": 403}),
                            json.dumps({"proxy_rsps": []}), "x" * 1048577]
        bad = deepcopy(fixture().payload)
        bad["proxy_rsps"].append(deepcopy(bad["proxy_rsps"][0]))
        invalid_payloads.append(json.dumps(bad))
        for raw in invalid_payloads:
            with self.subTest(raw=raw[:30]), tempfile.TemporaryDirectory() as tmp:
                with patch.object(hg, "curl", return_value=raw), self.assertRaises(AdapterError):
                    hg.discover("arknights", Path(tmp))
                self.assertEqual(list(Path(tmp).iterdir()), [])
        with patch.object(hg, "curl", side_effect=AdapterError("timeout")), self.assertRaisesRegex(AdapterError, "timeout"):
            hg.collect("endfield", 1)
        with patch.object(hg, "curl") as curl:
            for game, timeout in [("missing", 30), ("arknights", True), ("endfield", 0)]:
                with self.assertRaises(AdapterError):
                    hg.collect(game, timeout)
            curl.assert_not_called()

    def test_bad_metadata_rejected_before_write(self):
        mutations = [
            lambda c: packs(c)[0].update(md5="bad"),
            lambda c: packs(c)[0].update(package_size=-1),
            lambda c: packs(c)[0].update(package_size=True),
            lambda c: packs(c)[0].update(package_size="1.2"),
            lambda c: packs(c).append(deepcopy(packs(c)[0])),
            lambda c: packs(c).pop(0),
            lambda c: c.payload["proxy_rsps"][0]["get_latest_game_rsp"].update(version="../77"),
            lambda c: c.payload["proxy_rsps"][0]["get_latest_game_rsp"]["pkg"].update(total_size=-1),
        ]
        for mutate in mutations:
            collection = fixture()
            mutate(collection)
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(AdapterError):
                    hg.discover_collection(collection, Path(tmp))
                self.assertEqual(list(Path(tmp).iterdir()), [])
        collection = fixture()
        original = packs(collection)[0]["url"]
        invalid_urls = [original.replace("https://", "http://"), original.replace("ak.hycdn.cn", "evil.example"),
                        original.replace("https://", "https://u:p@"), original + "#fragment", original + "?auth_key=secret",
                        original.replace("/Windows/", "/Android/"), original.replace("/GzD1CpaWgmSq1wew/", "/other/"),
                        original.replace("/packs/", "/packs/../"), original.replace("production_", "bad%2Fproduction_"),
                        original.replace(".001", ".000"), original + "\n"]
        for url in invalid_urls:
            with self.subTest(url=url):
                invalid = fixture()
                packs(invalid)[0]["url"] = url
                with self.assertRaises(AdapterError):
                    hg.organize(invalid)

    def test_id_stable_for_reorder_changed_metadata_and_signed_rotation(self):
        collection = fixture("endfield")
        before = hg.organize(collection)
        packs(collection).reverse()
        for pack in packs(collection):
            pack.update(url=pack["url"].replace(AUTH, ROTATED_AUTH), md5="e" * 32, package_size="0")
        after = hg.organize(collection)
        self.assertEqual([item["artifact_id"] for item in before["artifacts"]],
                         [item["artifact_id"] for item in after["artifacts"]])
        self.assertTrue(all(ROTATED_AUTH in item["urls"][0]["url"] for item in after["artifacts"]))

    def test_repeat_and_rotation_preserve_manual_content_and_history(self):
        collection = fixture("endfield")
        existing = hg.organize(collection)
        existing["is_visible"] = False
        existing["version_code"] = 123
        existing["references"] = [{"kind": "chunk_manifest", "path": "manifests/history.json"}]
        existing["provenance"] = {"source_kind": "third_party_history", "source_name": "historical import"}
        current = {"state": "available", "http_code": 206, "checked_at": "2026-10-02T00:00:00Z"}
        first = existing["artifacts"][0]
        first["source"] = deepcopy(existing["provenance"])
        first["urls"][0]["current"] = current
        manual_url = {"url": "https://example.test/manual.zip.001", "provider": "manual", "source_kind": "manual",
                      "priority": 3, "current": deepcopy(current)}
        first["urls"].append(manual_url)
        unrelated = {"kind": "package", "component": "other", "package_type": "full", "delivery_mode": "archive",
                     "name": "manual.zip", "urls": [deepcopy(manual_url)], "source": {"source_kind": "manual"}}
        unrelated["artifact_id"] = artifact_id(unrelated, existing)
        existing["artifacts"].append(unrelated)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = persist_v2_record(existing, root)
            hg.discover_collection(collection, root)
            repeated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(repeated, existing)
            initial_bytes = path.read_bytes()
            hg.discover_collection(collection, root)
            self.assertEqual(path.read_bytes(), initial_bytes)
            for pack in packs(collection):
                pack["url"] = pack["url"].replace(AUTH, ROTATED_AUTH)
            hg.discover_collection(collection, root)
            rotated = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(rotated["is_visible"])
            self.assertEqual(rotated["version_code"], 123)
            self.assertEqual(rotated["provenance"], existing["provenance"])
            self.assertEqual(rotated["references"], existing["references"])
            self.assertEqual(rotated["artifacts"][-1], unrelated)
            changed = rotated["artifacts"][0]
            self.assertEqual(changed["source"], first["source"])
            self.assertEqual(changed["urls"][1], manual_url)
            self.assertEqual(len(changed["urls"]), 2)
            self.assertIn(ROTATED_AUTH, changed["urls"][0]["url"])
            self.assertNotIn("current", changed["urls"][0])

    def test_signed_query_validation(self):
        invalid_queries = ["auth_key=secret", AUTH + "&other=1", AUTH + "&" + AUTH, AUTH.replace("auth_key", "auth%5Fkey"),
                           AUTH.replace("-0-", "--"), AUTH + "%26", "other=1"]
        for query in invalid_queries:
            with self.subTest(query=query):
                invalid = fixture("endfield")
                packs(invalid)[0]["url"] = packs(invalid)[0]["url"].split("?")[0] + "?" + query
                with self.assertRaises(AdapterError):
                    hg.organize(invalid)


if __name__ == "__main__":
    unittest.main()
