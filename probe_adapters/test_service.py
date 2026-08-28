import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.schema_v2 import artifact_id
from probe_adapters.common import ProbeError
from probe_adapters.service import apply_result, probe


def v2_record() -> dict:
    identity = {
        "vendor": "mihoyo", "game_id": "hk4e", "domain_id": "hk4e-android",
        "platform": "android", "channel": "official", "version": "7.0.0",
    }
    artifact = {
        "kind": "apk", "component": "game", "package_type": "full",
        "delivery_mode": "direct", "name": "game.apk",
        "urls": [{
            "url": "https://example.test/old.apk", "provider": "mihoyo",
            "source_kind": "official", "priority": 0,
        }],
    }
    artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
    return {
        "schema_version": 2, **identity, "version_code": None,
        "file_time": "manual-date", "artifacts": [artifact], "references": [],
    }


class ProbeServiceTests(unittest.TestCase):
    def test_bh3_retired_host_is_static_and_does_not_use_network(self):
        url = "https://app.bh3.com/public/Android/old.apk"
        with patch("probe_adapters.service.probe_url") as range_probe, patch("probe_adapters.service.probe_head") as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3")
        range_probe.assert_not_called()
        head_probe.assert_not_called()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "retired_official_host")
        self.assertIsNone(result["http_code"])

    def test_bh3_archive_range_failure_uses_head_metadata_without_faking_http_code(self):
        url = "https://bundle.bh3.com/public/Android/archived.apk"
        error = ProbeError("archived", returncode=56, status=403, final_url=url,
                           headers={}, body=b"<Error><Code>InvalidObjectState</Code></Error>")
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
            return_value=(200, {"content-length": "123", "x-oss-storage-class": "Archive"}, url),
        ) as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3", expected_size=123)
        head_probe.assert_called_once_with(url, 10)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "oss_archive_not_restored")
        self.assertEqual(result["metadata_http_code"], 200)
        self.assertIsNone(result["http_code"])

    def test_non_bh3_range_failure_does_not_use_head(self):
        url = "https://autopatchcn.yuanshen.com/game.apk"
        error = ProbeError("failed", returncode=56, status=403, final_url=url)
        with patch("probe_adapters.service.probe_url", side_effect=error), patch("probe_adapters.service.probe_head") as head_probe:
            with self.assertRaises(ProbeError):
                probe(url, vendor="mihoyo", game_id="hk4e")
        head_probe.assert_not_called()

    def test_bh3_readable_range_does_not_use_head(self):
        url = "https://bundle.bh3.com/public/Android/readable.apk"
        with patch("probe_adapters.service.probe_url", return_value=(206, {"content-type": "application/vnd.android.package-archive"}, url, b"PK\x03\x04" + b"x" * 12)), patch("probe_adapters.service.probe_head") as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3")
        head_probe.assert_not_called()
        self.assertTrue(result["available"])
    def test_non_positive_timeout_is_rejected(self):
        for value in (0, -1, True, "10"):
            with self.subTest(value=value), patch("probe_adapters.service.probe_url") as run:
                with self.assertRaises(Exception):
                    probe("https://example.test/a.apk", timeout=value)
                run.assert_not_called()
    def test_dispatches_from_the_final_url_after_discovery_redirect(self) -> None:
        entry = "https://api-takumi.mihoyo.com/event/download_porter/link/ys_cn/official/android_default"
        final = "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk"
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {"content-type": "application/vnd.android.package-archive"},
            final,
            b"PK\x03\x04",
        )):
            result = probe(entry, vendor="mihoyo", game_id="hk4e")
        self.assertEqual(result["adapter"], "mihoyo_autopatch")
        self.assertEqual(result["url"], final)

    def test_probes_apk_prefix_and_normalizes_metadata(self) -> None:
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {
                "content-type": "application/vnd.android.package-archive",
                "content-range": "bytes 0-0/123",
                "etag": '"etag-value"',
                "last-modified": "Mon, 03 Aug 2026 09:25:07 GMT",
            },
            "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk",
            b"PK\x03\x04",
        )):
            result = probe(
                "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk",
                vendor="mihoyo",
                game_id="hk4e",
                timeout=1,
            )
        self.assertEqual(result["adapter"], "mihoyo_autopatch")
        self.assertIs(result["available"], True)
        self.assertEqual(result["size"], 123)
        self.assertEqual(result["etag"], "etag-value")
        self.assertEqual(result["file_time"], "2026-08-03T07:53:01Z")

    def test_only_404_and_410_are_definitely_unavailable(self) -> None:
        url = "https://static.benghuai.com/Download/v9_7/game.apk"
        with patch("probe_adapters.service.probe_url", return_value=(404, {}, url, b"")):
            self.assertIs(probe(url, vendor="mihoyo", game_id="bh2")["available"], False)
        with patch("probe_adapters.service.probe_url", return_value=(403, {}, url, b"")):
            self.assertIsNone(probe(url, vendor="mihoyo", game_id="bh2")["available"])

    def test_mihoyo_autopatch_rejects_a_successful_plain_text_placeholder(self) -> None:
        url = "https://autopatchcn.bhsr.com/client/cn/token/gw_An/StarRail_1.5.0.apk"
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {"content-type": "text/plain", "content-range": "bytes 0-2/3"},
            url,
            b">.<",
        )):
            result = probe(url, vendor="mihoyo", game_id="hkrpg")

        self.assertEqual(result["size"], 3)
        self.assertIs(result["available"], False)

    def test_apply_result_only_updates_probe_owned_fields(self) -> None:
        record = v2_record()
        updated = apply_result(record, {
            "url": "https://example.test/final.apk", "size": 123,
            "etag": "etag", "crc64": "crc", "md5": "md5",
            "http_code": 206, "available": True, "checked_at": "2026-08-24T00:00:00Z",
            "file_time": "2026-08-03T00:00:00Z",
            "target_url": "https://example.test/old.apk",
        })
        current = updated["artifacts"][0]["urls"][0]["current"]
        self.assertEqual(updated["artifacts"][0]["urls"][0]["url"], "https://example.test/old.apk")
        self.assertEqual(current["state"], "available")
        self.assertEqual(current["response_size"], 123)
        self.assertEqual(current["final_url"], "https://example.test/final.apk")
        self.assertEqual(updated["file_time"], "manual-date")
        self.assertNotIn("url", updated)
        self.assertNotIn("status", updated)

    def test_apply_result_requires_exact_target_and_preserves_record(self):
        record = v2_record()
        original = deepcopy(record)
        result = {"target_url": "https://example.test/old.apk", "url": "https://example.test/old.apk",
                  "available": True, "http_code": 200, "checked_at": "2026-08-24T00:00:00Z",
                  "observed_size": 9, "size": 8, "md5": "bad", "reason": "x", "confidence": "low"}
        updated = apply_result(record, result)
        current = updated["artifacts"][0]["urls"][0]["current"]
        self.assertEqual(current["response_size"], 9)
        self.assertNotIn("md5", current)
        self.assertNotIn("reason", current)
        self.assertNotIn("confidence", current)
        self.assertEqual(record, original)
        self.assertEqual(updated["artifacts"][0]["artifact_id"], original["artifacts"][0]["artifact_id"])
        with self.assertRaises(Exception):
            apply_result(record, {**result, "target_url": "https://example.test/missing.apk"})

    def test_apply_result_falls_back_to_size_when_observed_size_is_none(self):
        record = v2_record()
        updated = apply_result(record, {"target_url": "https://example.test/old.apk", "url": "https://example.test/old.apk",
                                        "available": True, "observed_size": None, "size": 8})
        self.assertEqual(updated["artifacts"][0]["urls"][0]["current"]["response_size"], 8)

    def test_legacy_record_writeback_is_rejected(self):
        with self.assertRaises(Exception):
            apply_result({"platform": "android", "url": "x"}, {"target_url": "x"})


if __name__ == "__main__":
    unittest.main()
