import unittest
from copy import deepcopy
from unittest.mock import patch

from probe_adapters.common import ProbeError
from probe_adapters.service import PCRecordCompatibilityError, current_from_result, pc_v2_current_from_result, probe


class PCV2Tests(unittest.TestCase):
    def test_probe_passes_expected_size_and_redirects_to_pc_adapter(self):
        source = "https://autopatchcn.yuanshen.com/client/a.zip"
        final = "https://autopatchcn.yuanshen.com/client/final.zip"
        with patch("probe_adapters.service.probe_url", return_value=(206, {
            "content-range": "bytes 0-15/12", "x-cos-hash-crc64ecma": "1234",
        }, final, b"PK\x03\x04")) as mocked:
            result = probe(source, vendor="mihoyo", game_id="hk4e", platform="pc", expected_size=12)
        self.assertEqual(result["platform"], "windows")
        self.assertTrue(result["available"])
        self.assertEqual(result["crc64"], "1234")
        mocked.assert_called_once_with(source, 10)

    def test_bh3_archive_range_failure_uses_official_storage_metadata(self):
        source = "https://autopatchcn.bh3.com/client/game.7z"
        error = ProbeError(
            "reset", returncode=56, status=206, final_url=source,
            headers={"content-range": "bytes 0-15/100"},
        )
        head_headers = {
            "content-length": "100",
            "x-oss-storage-class": "Archive",
            "x-oss-hash-crc64ecma": "5678",
        }
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head", return_value=(200, head_headers, source),
        ) as head_probe:
            result = probe(
                source, vendor="mihoyo", game_id="bh3", platform="windows",
                expected_size=100,
            )
        head_probe.assert_called_once_with(source, 10)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "oss_archive_not_restored")
        self.assertIsNone(result["http_code"])
        self.assertEqual(result["metadata_http_code"], 200)
        self.assertEqual(result["crc64"], "5678")

    def test_probe_rejects_redirect_to_non_pc_url(self):
        source = "https://autopatchcn.yuanshen.com/client/a.zip"
        with patch("probe_adapters.service.probe_url", return_value=(206, {}, "https://evil.test/a.zip", b"PK\x03\x04")):
            with self.assertRaises(ProbeError):
                probe(source, vendor="mihoyo", game_id="hk4e", platform="windows")

    def test_bh3_403_range_failure_keeps_http_code_without_head(self):
        source = "https://autopatchcn.bh3.com/client/game.7z"
        error = ProbeError("reset", returncode=56, status=403, final_url=source)
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
        ) as head_probe:
            result = probe(source, vendor="mihoyo", game_id="bh3", platform="windows")
        head_probe.assert_not_called()
        self.assertIs(result["available"], False)
        self.assertEqual(result["http_code"], 403)
        self.assertEqual(result["reason"], "HTTP 403")
        self.assertEqual(result["source_kind"], "live_probe")
        self.assertIsNone(result["metadata_http_code"])

    def test_current_conversion_preserves_inputs_and_only_owned_fields(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "domain_id": "hk4e-pc",
                    "platform": "windows", "channel": "official", "version": "7.0"}
        target = "https://autopatchcn.yuanshen.com/mirror/a.zip"
        result = {"url": "https://autopatchcn.yuanshen.com/mirror/final.zip",
                  "available": True, "http_code": 206, "checked_at": "2026-08-29T00:00:00Z", "observed_size": 12,
                  "etag": "etag", "crc64": "crc", "last_modified": "Sat, 29 Aug 2026 00:00:00 GMT",
                  "reason": "ignored", "confidence": "ignored", "md5": "ignored",
                  "metadata_http_code": 200, "expected_size": 99, "bytes_received": 16,
                  "file_time": "ignored", "source_kind": "ignored", "transport_returncode": 0}
        original_identity, original_result = deepcopy(identity), deepcopy(result)
        expected = {
            "state": "available", "http_code": 206, "checked_at": "2026-08-29T00:00:00Z",
            "response_size": 12, "etag": "etag", "crc64": "crc",
            "last_modified": "Sat, 29 Aug 2026 00:00:00 GMT",
            "final_url": "https://autopatchcn.yuanshen.com/mirror/final.zip",
        }
        for convert in (pc_v2_current_from_result, current_from_result):
            with self.subTest(convert=convert.__name__):
                self.assertEqual(convert(identity, target, result), expected)
                self.assertEqual(identity, original_identity)
                self.assertEqual(result, original_result)

    def test_current_states_and_final_url_same_is_omitted(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "platform": "windows"}
        target = "https://autopatchcn.yuanshen.com/client/a.zip"
        for available in (True, False, None):
            result = {"url": target, "available": available,
                      "http_code": 404 if available is False else 200, "checked_at": "2026-08-29T00:00:00Z", "size": 10}
            for convert in (pc_v2_current_from_result, current_from_result):
                with self.subTest(available=available, convert=convert.__name__):
                    current = convert(identity, target, result)
                    self.assertEqual(current["state"], "available" if available is True else "unavailable" if available is False else "unknown")
                    self.assertNotIn("final_url", current)

    def test_current_conversion_needs_only_identity_and_evidence(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "platform": "windows"}
        original = deepcopy(identity)
        url = "https://autopatchcn.yuanshen.com/client/game.zip"
        result = {"url": url, "available": True, "http_code": 206, "size": 12}
        self.assertEqual(pc_v2_current_from_result(identity, url, result), {
            "state": "available", "http_code": 206, "response_size": 12,
        })
        self.assertEqual(identity, original)
        with self.assertRaises(PCRecordCompatibilityError):
            pc_v2_current_from_result(identity, url, {**result, "url": "https://evil.test/game.zip"})

    def test_current_rejects_bad_metadata_and_unofficial_redirects(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "platform": "windows"}
        target = "https://autopatchcn.yuanshen.com/client/a.zip"
        base = {"url": target, "available": True}
        bad = [dict(base, http_code=-1), dict(base, http_code=True), dict(base, checked_at="not-date"),
               dict(base, checked_at="2026-08-29T00:00:00+00:00"), dict(base, observed_size=-1),
               dict(base, etag=""), dict(base, url="ftp://autopatchcn.yuanshen.com/a.zip"),
               dict(base, url="https://evil.test/a.zip")]
        for item in bad:
            for convert in (pc_v2_current_from_result, current_from_result):
                with self.subTest(item=item, convert=convert.__name__):
                    with self.assertRaises((PCRecordCompatibilityError, ProbeError)):
                        convert(identity, target, item)


if __name__ == "__main__":
    unittest.main()
