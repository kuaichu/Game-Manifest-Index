import unittest

from probe_adapters.common import file_time
from probe_adapters.pc import manjuu_syncstation as adapter


class ManjuuSyncstationProbeAdapterTests(unittest.TestCase):
    def test_matches_official_pg_chunk_and_pg_item_v2_pc_urls(self):
        self.assertEqual(adapter.NAME, "manjuu_syncstation_pc")
        self.assertTrue(adapter.URL_TIME)
        self.assertEqual(adapter.HOSTS, {"syncstation.manjuu.com", "l2-syncstation.manjuu.com"})

        paths = (
            "/azurpromilia/pg_chunk/c000/20260826163112_astsnkiwfuggldku/3778b521-315d-42e4-85bb-bbbc97db4d7b",
            "/azurpromilia/pg_item_v2/c000/20260826174804_dghyfulumbjceiap/mf-d7ceac1d-59b2-4588-85bc-4487f021b12a.txt",
        )
        identities = (("manjuu", "azurpromilia"), (None, None), ("manjuu", None), (None, "azurpromilia"))
        for host in ("syncstation.manjuu.com", "l2-syncstation.manjuu.com", "syncstation.manjuu.com:443"):
            for path in paths:
                url = f"https://{host}{path}"
                for vendor, game_id in identities:
                    with self.subTest(url=url, vendor=vendor, game_id=game_id):
                        self.assertTrue(adapter.matches(vendor, game_id, url))

    def test_rejects_android_apks_runtime_targets_and_unsafe_urls(self):
        valid = (
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/"
            "20260826163112_astsnkiwfuggldku/3778b521-315d-42e4-85bb-bbbc97db4d7b"
        )
        invalid_urls = (
            "https://syncstation.manjuu.com/azurpromilia/pg_package/c000/AzurPromilia.apk",
            "https://l2-syncstation.manjuu.com/azurpromilia/android/c000/AzurPromilia.apk",
            valid + ".apk",
            "https://syncstation.manjuu.com/azurpromilia/pg_item_v2/target/c000_20260826175730_b3AtNzkwMDM=/file.r",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/../secret/file",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/%2e%2e/secret/file",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/./file",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000//file",
            valid.replace("https://", "http://"),
            valid.replace("https://", "https://u:p@"),
            valid.replace(".com/", ".com:8443/"),
            valid.replace(".com/", ".com.evil.example/"),
            valid + "?token=1",
            valid + "?",
            valid + "#frag",
            valid + "#",
            valid + "\n",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(adapter.matches("manjuu", "azurpromilia", url))
                self.assertFalse(adapter.matches(None, None, url))

        for vendor, game_id in (("mihoyo", "azurpromilia"), ("manjuu", "wuwa")):
            self.assertFalse(adapter.matches(vendor, game_id, valid))

    def test_availability_handles_status_html_challenge_and_expected_sizes(self):
        self.assertIs(adapter.availability(206, "segment", b"\x00\x01\x02\x03", observed_size=100, expected_size=100), True)
        self.assertIs(adapter.availability(200, "mf-test.txt", b"base64payload===", observed_size=15000, expected_size=None), True)
        self.assertIs(adapter.availability(206, "segment", b"\x00\x01\x02\x03", observed_size=None, expected_size=100), True)
        self.assertIsNone(adapter.availability(206, "segment", b"\x00\x01\x02\x03", observed_size=99, expected_size=100))
        self.assertIsNone(adapter.availability(206, "segment", b""))
        self.assertIsNone(adapter.availability(200, "mf-test.txt", b""))
        self.assertIs(adapter.availability(404, "segment", b""), False)
        self.assertIs(adapter.availability(410, "mf-test.txt", b""), False)
        self.assertIsNone(adapter.availability(500, "segment", b"error"))
        self.assertIsNone(adapter.availability(403, "segment", b"forbidden"))
        self.assertIs(adapter.availability(200, "segment", b"<html><body>challenge</body></html>"), False)
        self.assertIs(adapter.availability(206, "mf-test.txt", b"  <!DOCTYPE html><html></html>"), False)
        self.assertIs(
            adapter.availability(
                206, "segment", b"abcd",
                observed_size=16, expected_size=16, transport_returncode=0, bytes_received=16,
            ),
            True,
        )

    def test_url_time_extracts_utc_timestamp_from_cdn_path(self):
        url = (
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/"
            "20260826163112_astsnkiwfuggldku/3778b521-315d-42e4-85bb-bbbc97db4d7b"
        )
        self.assertEqual(file_time(url, {}, adapter.URL_TIME), "2026-08-26T08:31:12Z")


if __name__ == "__main__":
    unittest.main()
