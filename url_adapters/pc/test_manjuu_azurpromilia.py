import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from backend.schema_v2 import validate_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import manjuu_azurpromilia as adapter

_KEY = b"k" * 24
_IV = b"i" * 16
_ENV = {adapter.KEY_ENV: _KEY.decode(), adapter.IV_ENV: _IV.decode()}
_CHUNK = "azurpromilia/pg_chunk/c000/test"
_ITEMS = "azurpromilia/pg_item_v2/c000/test"
_FILES = "azurpromilia/pg_item_v2/target/test"
_MD5 = "a" * 32


def _encrypt(plain: str) -> bytes:
    cipher = AES.new(_KEY, AES.MODE_CBC, _IV)
    return base64.b64encode(cipher.encrypt(pad(plain.encode(), AES.block_size)))


class ManjuuPCAdapterTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.output = self.root / "data"
        self.capture = self.root / "packageconfig.txt"
        self.response = {
            "code": 0, "data": {"downloadMode": 2, "released": {
                "versionCode": "1.0.0.30", "versionName": "1.0.0", "packageSize": 5,
                "gamePackageList": [], "domainList": [adapter.CDN],
            }},
        }
        self.bodies = {}
        self.enterContext(patch.dict(os.environ, _ENV))
        self.opener = Mock()
        self.opener.open.side_effect = lambda req, timeout: BytesIO(self.bodies[req.full_url])
        self.enterContext(patch.object(adapter, "build_opener", return_value=self.opener))
        self._write_capture()

    def _write_capture(self, address=_ITEMS + "/mf-test.txt", remote=_FILES + "/folder/file.r"):
        specs = self.response["data"]["released"]["gamePackageList"]
        specs.clear()
        for mode, path, text in (
            (1, _CHUNK + "/ck-test.txt", f"1,3,{_MD5}\n0,0,3,{_MD5},{_CHUNK}/part\n"),
            (2, address, f"2,1,1\n0,0,{'0' * 32},folder\n1,5,{_MD5},folder\\file.r,{remote}\n"),
        ):
            body = _encrypt(text)
            specs.append({
                "packageType": mode, "downloadUrl": path,
                "fileSize": len(body), "fileMd5": hashlib.md5(body, usedforsecurity=False).hexdigest(),
            })
            self.bodies[f"{adapter.CDN}/{path}"] = body
        self.capture.write_text(
            "GET /pc-launcher/client/gameversion/packageconfig HTTP/2\nCookie: test-only\n\n"
            "HTTP/2 200\nContent-Type: application/json\n\n" + json.dumps(self.response), encoding="utf8",
        )

    def test_imports_verified_manifests_and_repeated_import_is_stable(self):
        target = adapter.discover(self.capture, self.output, 10)
        r = json.loads(target.read_bytes())
        validate_v2_record(r)
        segment, full = r["artifacts"]
        self.assertEqual((r["version"], segment["part"], segment["size"], full["size"]), ("1.0.0.30", 1, 3, 5))
        self.assertEqual(full["manifest"]["base_urls"][0]["url"], adapter.CDN + "/" + _FILES + "/")
        document = target.parent / full["manifest"]["path"]
        self.assertEqual(json.loads(document.read_bytes())["resource"], [{"dest": "folder/file.r", "md5": _MD5, "size": 5}])
        index = target.with_name("index.json")
        self.assertEqual([x["version"] for x in json.loads(index.read_bytes())["versions"]], ["1.0.0.30"])
        before = [x.read_bytes() for x in (target, document, index)]
        self.assertEqual(adapter.discover(self.capture, self.output, 10), target)
        self.assertEqual([x.read_bytes() for x in (target, document, index)], before)
        self.assertFalse(any(b"test-only" in x or _KEY in x or _IV in x for x in before))

    def test_rejects_an_unofficial_manifest_before_making_network_requests(self):
        self._write_capture(address="https://example.invalid/mf-test.txt")
        with self.assertRaises(AdapterError):
            adapter.discover(self.capture, self.output)
        self.opener.open.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_rejects_a_bad_official_manifest_digest_without_writing_data(self):
        self.bodies[f"{adapter.CDN}/{_ITEMS}/mf-test.txt"] = b"broken"
        with self.assertRaisesRegex(AdapterError, "MD5"):
            adapter.discover(self.capture, self.output)
        self.assertFalse(self.output.exists())

    def test_detects_invalid_remote_path_and_does_not_make_a_partial_record(self):
        self._write_capture(remote=_FILES + "/other/file.r")
        with self.assertRaisesRegex(AdapterError, "CDN 路径"):
            adapter.discover(self.capture, self.output)
        self.assertFalse(self.output.exists())

    def test_does_not_replace_a_different_record_for_an_existing_version(self):
        target = adapter.discover(self.capture, self.output)
        record = json.loads(target.read_bytes())
        record["file_time"] = "2026-11-24T12:00:00Z"
        target.write_text(json.dumps(record), encoding="utf8")
        before = target.read_bytes()
        with self.assertRaisesRegex(AdapterError, "内容不同"):
            adapter.discover(self.capture, self.output)
        self.assertEqual(target.read_bytes(), before)

    def test_rolls_back_a_new_manifest_if_the_version_record_cannot_be_written(self):
        with patch.object(adapter, "write_v2_record", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                adapter.discover(self.capture, self.output)
        self.assertFalse(list(self.output.rglob("*.json")))

    def test_rejects_unsafe_or_symlinked_manifests_directory_before_writing_files(self):
        self.assertFalse(adapter._is_regular(self.root / "missing", directory=True))
        pc_dir = self.output / "manjuu" / "azurpromilia" / "pc"
        pc_dir.mkdir(parents=True)
        manifests = pc_dir / "manifests"
        manifests.write_bytes(b"not-a-directory")
        with self.assertRaisesRegex(AdapterError, "文件清单输出目录不安全"):
            adapter.discover(self.capture, self.output)
        self.assertEqual(manifests.read_bytes(), b"not-a-directory")
        self.assertFalse(list(self.output.rglob("*.json")))
        manifests.unlink()

        external = self.root / "external"
        external.mkdir()
        try:
            os.symlink(external, manifests, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink unavailable: {error}")
        with self.assertRaisesRegex(AdapterError, "文件清单输出目录不安全"):
            adapter.discover(self.capture, self.output)
        self.assertEqual(list(external.iterdir()), [])
        self.assertFalse(list(self.output.rglob("*.json")))

        linked_output = self.root / "linked-output"
        os.symlink(external, linked_output, target_is_directory=True)
        with self.assertRaisesRegex(AdapterError, "文件清单输出目录不安全"):
            adapter.discover(self.capture, linked_output)
        self.assertEqual(list(external.iterdir()), [])

    def test_validates_v2_record_in_discover_before_publish(self):
        events = []
        real_publish = adapter._publish
        with (
            patch.object(adapter, "validate_v2_record", side_effect=lambda r: (events.append("validate"), validate_v2_record(r))[1]),
            patch.object(adapter, "_publish", side_effect=lambda r, d, o: (events.append("publish"), real_publish(r, d, o))[1]),
        ):
            adapter.discover(self.capture, self.output)
        self.assertEqual(events, ["validate", "publish"])

        bad_output = self.root / "bad-output"
        with (
            patch.object(adapter, "artifact_id", return_value="invalid"),
            patch.object(adapter, "_publish", wraps=adapter._publish) as publish_spy,
        ):
            with self.assertRaises(AdapterError):
                adapter.discover(self.capture, bad_output)
        publish_spy.assert_not_called()
        self.assertFalse(bad_output.exists())


if __name__ == "__main__":
    unittest.main()
