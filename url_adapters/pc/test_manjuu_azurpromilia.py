import base64
from contextlib import redirect_stdout
import hashlib
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from backend.schema_v2 import validate_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import manjuu_azurpromilia as adapter

_SALT = "00000000-0000-0000-0000-000000000000"
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
        self.requests = []
        self.enterContext(patch.dict(os.environ, _ENV, clear=False))
        os.environ.pop(adapter.SALT_ENV, None)
        self.opener = Mock()

        def _open(req, timeout):
            self.requests.append((req, timeout))
            return BytesIO(self.bodies[req.full_url])

        self.opener.open.side_effect = _open
        self.enterContext(patch.object(adapter, "build_opener", return_value=self.opener))
        self._write_capture()

    def _write_capture(self, address=_ITEMS + "/mf-test.txt", remote=_FILES + "/folder/file.r", *, encrypt=True):
        specs = self.response["data"]["released"]["gamePackageList"]
        specs.clear()
        for mode, path, text in (
            (1, _CHUNK + "/ck-test.txt", f"1,3,{_MD5}\n0,0,3,{_MD5},{_CHUNK}/part\n"),
            (2, address, f"2,1,1\n0,0,{'0' * 32},folder\n1,5,{_MD5},folder\\file.r,{remote}\n"),
        ):
            body = _encrypt(text) if encrypt else text.encode("utf-8")
            specs.append({
                "packageType": mode, "downloadUrl": path,
                "fileSize": len(body), "fileMd5": hashlib.md5(body, usedforsecurity=False).hexdigest(),
            })
            self.bodies[f"{adapter.CDN}/{path}"] = body
        live_url = f"{adapter.PACKAGECONFIG_URL}?launcherId=93cdd43e096046138053253dc56d3562&uid="
        self.bodies[live_url] = json.dumps(self.response).encode("utf-8")
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

    def test_live_discover_signs_request_and_fetches_official_packageconfig(self):
        with patch.dict(os.environ, {adapter.SALT_ENV: _SALT}):
            target = adapter.discover("azurpromilia", self.output, 10)
        self.assertEqual(len(self.requests), 3)
        req, timeout = self.requests[0]
        self.assertEqual(timeout, 10)
        expected_query = "launcherId=93cdd43e096046138053253dc56d3562&uid="
        self.assertEqual(req.full_url, f"{adapter.PACKAGECONFIG_URL}?{expected_query}")
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["accept"], "application/json, text/plain, */*")
        self.assertEqual(headers["accept-encoding"], "identity")
        self.assertEqual(headers["user-agent"], "AzurPromiliaLauncher/1.0.1.1")
        self.assertEqual(headers["grp-app-id"], "354")
        self.assertEqual(headers["grp-platform"], "Launcher")
        self.assertEqual(headers["grp-channel-code"], "C000")
        self.assertEqual(headers["grp-sub-channel-code"], "SC000")
        self.assertEqual(headers["sdk-version"], "1.0.1.1")
        self.assertEqual(headers["channel-sdk-version"], "1.0.1.1")
        self.assertEqual(headers["grp-launcher-version-code"], "1.0.1.1")
        self.assertEqual(headers["lang"], "zh-Hans")
        self.assertRegex(headers["device-id"], r"^[0-9a-f]{32}$")
        self.assertRegex(headers["grp-trace-id"], r"^[0-9a-f]{32}$")
        self.assertRegex(headers["timestamp"], r"^\d+$")
        expected_sign = hashlib.md5(
            f"{headers['timestamp']}{expected_query}354C000{_SALT}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()
        self.assertEqual(headers["sign"], expected_sign)
        client_info = json.loads(headers["grp-client-info"])
        self.assertEqual(client_info, {
            "device_model": "Launcher",
            "device_os": "Linux",
            "app_version": "1.0.1.1",
            "grp_trace_id": headers["grp-trace-id"],
            "spec_device_info": {},
        })
        self.assertNotIn(" ", headers["grp-client-info"])
        record = json.loads(target.read_bytes())
        validate_v2_record(record)
        self.assertEqual(record["version"], "1.0.0.30")
        self.assertNotIn(_SALT.encode(), target.read_bytes())

    def test_live_discover_rejects_missing_salt_unsupported_game_and_network_failure(self):
        with self.assertRaisesRegex(AdapterError, adapter.SALT_ENV):
            adapter.discover("azurpromilia", self.output, 10)
        self.opener.open.assert_not_called()

        with patch.dict(os.environ, {adapter.SALT_ENV: _SALT}):
            with self.assertRaisesRegex(AdapterError, "不支持"):
                adapter.discover("other", self.output, 10)
            self.opener.open.assert_not_called()

            self.opener.open.side_effect = URLError("network down")
            with self.assertRaisesRegex(AdapterError, "无法请求蛮啾官方 PC packageconfig 接口") as ctx:
                adapter.discover("azurpromilia", self.output, 10)
            self.assertNotIn(_SALT, str(ctx.exception))

    def test_plaintext_csv_manifest_works_without_cipher_env_and_encrypted_requires_it(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(adapter.KEY_ENV, None)
            os.environ.pop(adapter.IV_ENV, None)
            with self.assertRaisesRegex(AdapterError, adapter.KEY_ENV):
                adapter.discover(self.capture, self.output, 10)

            self._write_capture(encrypt=False)
            target = adapter.discover(self.capture, self.output, 10)
            record = json.loads(target.read_bytes())
            validate_v2_record(record)
            self.assertEqual(record["version"], "1.0.0.30")

    def test_preserves_runtime_mutable_fields_while_rejecting_canonical_drift(self):
        target = adapter.discover(self.capture, self.output, 10)
        record = json.loads(target.read_bytes())
        record["is_visible"] = False
        current = {
            "state": "available",
            "http_code": 206,
            "checked_at": "2026-11-25T00:00:00Z",
            "response_size": 3,
        }
        record["artifacts"][0]["urls"][0]["current"] = current
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")

        self.assertEqual(adapter.discover(self.capture, self.output, 10), target)
        after = json.loads(target.read_bytes())
        self.assertIs(after["is_visible"], False)
        self.assertEqual(after["artifacts"][0]["urls"][0]["current"], current)

        after["file_time"] = "2026-11-24T12:00:00Z"
        target.write_text(json.dumps(after, indent=2) + "\n", encoding="utf8")
        with self.assertRaisesRegex(AdapterError, "内容不同"):
            adapter.discover(self.capture, self.output, 10)

    def test_live_mode_fast_skips_manifest_downloads_when_already_synced(self):
        with patch.dict(os.environ, {adapter.SALT_ENV: _SALT}):
            target = adapter.discover("azurpromilia", self.output, 10)
            self.assertEqual(len(self.requests), 3)

            self.requests.clear()
            self.bodies.pop(f"{adapter.CDN}/{_CHUNK}/ck-test.txt")
            self.bodies.pop(f"{adapter.CDN}/{_ITEMS}/mf-test.txt")

            second = adapter.discover("azurpromilia", self.output, 10)
            self.assertEqual(second, target)
            self.assertEqual(len(self.requests), 1)
            self.assertTrue(self.requests[0][0].full_url.startswith(adapter.PACKAGECONFIG_URL))

            # If index.json is missing, fast-skip falls through to full sync and restores index.json.
            index = target.with_name("index.json")
            index.unlink()
            self._write_capture()
            self.requests.clear()
            rebuilt = adapter.discover("azurpromilia", self.output, 10)
            self.assertEqual(rebuilt, target)
            self.assertEqual(len(self.requests), 3)
            self.assertTrue(index.is_file())

    def test_cli_main_dispatches_live_and_offline_modes_and_builds_tls_opener(self):
        ctx = adapter._ssl_context()
        self.assertIsNotNone(ctx)
        out = StringIO()
        with (
            patch.object(adapter, "discover", return_value=self.output / "1.0.0.30.json") as spy,
            redirect_stdout(out),
        ):
            self.output.mkdir(parents=True, exist_ok=True)
            (self.output / "1.0.0.30.json").write_text("{}", encoding="utf8")
            rc_live = adapter.main(["--output-root", str(self.output), "--timeout", "12"])
            rc_offline = adapter.main([
                "--packageconfig", str(self.capture),
                "--output-root", str(self.output),
                "--timeout", "15",
            ])
        self.assertEqual((rc_live, rc_offline), (0, 0))
        self.assertEqual(spy.call_args_list[0].args, ("azurpromilia", self.output, 12))
        self.assertEqual(spy.call_args_list[1].args, (self.capture, self.output, 15))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
