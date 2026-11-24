from hashlib import md5
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from backend.schema_v2 import artifact_id
from url_adapters.android import manjuu_azurpromilia as adapter
from url_adapters.common import AdapterError

APK_URL = (
    "https://syncstation.manjuu.com/azurpromilia/android/c000/20261109164612_sample/"
    "AzurPromilia_1.0.1.2645521_SC000_20261109164612_5079.apk"
)
SOURCE_URL = "https://api-grp.manjuu.com/activity/web/download/info"
API_URL = "https://api-grp.manjuu.com/activity/web/download/info?gameId=35"


def response(url=APK_URL, code=0):
    return json.dumps({"code": code, "data": {"nativeAndroidDownloadUrl": url}})


class ManjuuAzurPromiliaTest(unittest.TestCase):
    def test_discovery_signs_the_query_and_writes_a_canonical_record_and_index(self):
        headers = {
            "content-range": "bytes 0-15/1448044017",
            "last-modified": "Mon, 09 Nov 2026 08:48:03 GMT",
            "x-oss-hash-crc64ecma": "2210715407191419173",
        }
        stamp = "1795526174212"
        with (
            TemporaryDirectory() as folder,
            patch.object(adapter, "time_ns", return_value=int(stamp) * 1_000_000),
            patch.object(adapter, "curl", return_value=response()) as curl,
            patch.object(adapter, "probe_url", return_value=(206, headers, APK_URL, b"PK\x03\x04")),
        ):
            path = adapter.discover_v2("azurpromilia", Path(folder), 12)
            self.assertEqual(path.relative_to(folder).as_posix(), "manjuu/azurpromilia/android/1.0.1.2645521.json")
            args, timeout = curl.call_args.args
            self.assertEqual((args[-1], timeout), (API_URL, 12))
            self.assertIn(f"timestamp: {stamp}", args)
            self.assertIn("sign: " + md5(f"{stamp}gameId=35".encode(), usedforsecurity=False).hexdigest(), args)
            record = json.loads(path.read_text(encoding="utf-8"))
            artifact = record["artifacts"][0]
            self.assertEqual(record["file_time"], "2026-11-09T08:48:03Z")
            self.assertEqual(record["provenance"]["source_url"], SOURCE_URL)
            self.assertEqual(artifact["artifact_id"], artifact_id(artifact, record))
            self.assertEqual(artifact["size"], 1_448_044_017)
            self.assertEqual(artifact["urls"][0]["current"]["http_code"], 206)
            index = json.loads(path.with_name("index.json").read_text(encoding="utf-8"))
            self.assertEqual([row["version"] for row in index["versions"]], ["1.0.1.2645521"])

    def test_discovery_falls_back_to_apk_filename_timestamp_without_last_modified(self):
        headers = {
            "content-range": "bytes 0-15/1448044017",
            "x-oss-hash-crc64ecma": "2210715407191419173",
        }
        with (
            TemporaryDirectory() as folder,
            patch.object(adapter, "curl", return_value=response()),
            patch.object(adapter, "probe_url", return_value=(206, headers, APK_URL, b"PK\x03\x04")),
        ):
            path = adapter.discover_v2("azurpromilia", Path(folder), 12)
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["file_time"], "2026-11-09T08:46:12Z")

    def test_invalid_or_unofficial_download_metadata_never_reaches_cdn(self):
        for payload in (
            response(code=1),
            response(url=""),
            response(url=APK_URL.replace("syncstation.manjuu.com", "third-party.example")),
            response(url=APK_URL.replace("1.0.1.2645521", "latest")),
        ):
            with (
                self.subTest(payload=payload),
                TemporaryDirectory() as folder,
                patch.object(adapter, "curl", return_value=payload),
                patch.object(adapter, "probe_url") as probe,
            ):
                with self.assertRaises(AdapterError):
                    adapter.discover_v2("azurpromilia", Path(folder), 12)
                probe.assert_not_called()
                self.assertFalse(list(Path(folder).iterdir()))

    def test_a_cdn_error_page_is_not_written_as_an_apk(self):
        with (
            TemporaryDirectory() as folder,
            patch.object(adapter, "curl", return_value=response()),
            patch.object(adapter, "probe_url", return_value=(200, {"content-length": "100"}, APK_URL, b"<html>")),
        ):
            with self.assertRaises(AdapterError):
                adapter.discover_v2("azurpromilia", Path(folder), 12)
            self.assertFalse(list(Path(folder).iterdir()))


if __name__ == "__main__":
    unittest.main()
