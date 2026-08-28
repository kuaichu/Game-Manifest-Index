import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.schema_v2 import artifact_id
from probe_adapters.common import ProbeError
from probe_adapters.service import PCRecordCompatibilityError, apply_pc_v2_result, apply_result, probe


def record():
    identity = {"vendor": "mihoyo", "game_id": "hk4e", "domain_id": "hk4e-pc", "platform": "windows", "channel": "official", "version": "7.0"}
    artifacts = []
    for index, name in enumerate(("a.zip", "b.zip")):
        item = {
            "kind": "package", "component": "game", "package_type": "full",
            "delivery_mode": "file_manifest" if index else "direct", "name": name,
            "size": 10, "checksum": {"md5": str(index + 1) * 32},
            "urls": [
                {
                    "url": f"https://autopatchcn.yuanshen.com/client/{name}",
                    "provider": "mihoyo", "source_kind": "official", "priority": 0,
                    "current": {"state": "available", "http_code": 206},
                },
                {
                    "url": f"https://autopatchcn.yuanshen.com/mirror/{name}",
                    "provider": "mihoyo", "source_kind": "official", "priority": 1,
                },
            ],
            "source": {
                "source_kind": "official_sync", "source_name": "fixture",
                "source_url": "https://hyp-api.mihoyo.com/source",
            },
        }
        if index:
            item["manifest"] = {
                "path": "manifests/7.0/b.json",
                "base_urls": [{
                    "url": "https://autopatchcn.yuanshen.com/resources/",
                    "provider": "mihoyo", "source_kind": "official", "priority": 0,
                }],
            }
        item["artifact_id"] = artifact_id(item, record_identity=identity)
        artifacts.append(item)
    return {
        "schema_version": 2, **identity, "version_code": None, "file_time": None,
        "is_visible": False, "artifacts": artifacts,
        "references": [{
            "kind": "chunk_manifest", "path": "chunk-manifests/7.0.json",
            "source": {"source_kind": "official_sync", "source_name": "fixture"},
        }],
        "provenance": {"source_kind": "official_sync", "source_name": "test"},
    }


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

    def test_apply_exact_target_preserves_everything_else_and_allowed_current(self):
        value = record()
        original = deepcopy(value)
        result = {"artifact_index": 0, "url_index": 1, "target_url": value["artifacts"][0]["urls"][1]["url"], "url": "https://autopatchcn.yuanshen.com/mirror/final.zip",
                  "available": True, "http_code": 206, "checked_at": "2026-08-29T00:00:00Z", "observed_size": 12,
                  "etag": "etag", "crc64": "crc", "last_modified": "Sat, 29 Aug 2026 00:00:00 GMT",
                  "reason": "ignored", "confidence": "ignored", "md5": "ignored",
                  "metadata_http_code": 200, "expected_size": 99, "bytes_received": 16,
                  "file_time": "ignored", "source_kind": "ignored", "transport_returncode": 0}
        updated = apply_result(value, result)
        self.assertEqual(value, original)
        current = updated["artifacts"][0]["urls"][1]["current"]
        self.assertEqual(set(current), {"state", "http_code", "checked_at", "response_size", "etag", "crc64", "last_modified", "final_url"})
        self.assertEqual(updated["artifacts"][0]["urls"][0], original["artifacts"][0]["urls"][0])
        updated["artifacts"][0]["urls"][1].pop("current")
        original["artifacts"][0]["urls"][1].pop("current", None)
        self.assertEqual(updated, original | {})

    def test_apply_states_and_final_url_same_is_omitted(self):
        for available in (True, False, None):
            value = record()
            target = value["artifacts"][0]["urls"][0]["url"]
            result = {"artifact_index": 0, "url_index": 0, "target_url": target, "url": target, "available": available,
                      "http_code": 404 if available is False else 200, "checked_at": "2026-08-29T00:00:00Z", "size": 10}
            current = apply_pc_v2_result(value, result)["artifacts"][0]["urls"][0]["current"]
            self.assertEqual(current["state"], "available" if available is True else "unavailable" if available is False else "unknown")
            self.assertNotIn("final_url", current)

    def test_apply_rejects_bad_indexes_target_and_metadata(self):
        value = record()
        target = value["artifacts"][0]["urls"][0]["url"]
        base = {"artifact_index": 0, "url_index": 0, "target_url": target, "url": target, "available": True}
        bad = [dict(base, artifact_index=1), dict(base, url_index=True), dict(base, target_url="https://other.test/a.zip"),
               dict(base, http_code=-1), dict(base, http_code=True), dict(base, checked_at="not-date"), dict(base, checked_at="2026-08-29T00:00:00+00:00"),
               dict(base, observed_size=-1), dict(base, etag=""), dict(base, url="ftp://autopatchcn.yuanshen.com/a.zip"),
               dict(base, url="https://evil.test/a.zip")]
        for item in bad:
            with self.subTest(item=item):
                with self.assertRaises((PCRecordCompatibilityError, ProbeError, ValueError)):
                    apply_pc_v2_result(value, item)


if __name__ == "__main__":
    unittest.main()
