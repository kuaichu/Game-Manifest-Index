import unittest

from probe_adapters.android import manjuu_syncstation
from probe_adapters.common import file_time

STORED_030_URL = (
    "https://syncstation.manjuu.com/azurpromilia/android/c000/"
    "20260826152754_dhefqecywkreazfa/AzurPromilia_0.3.0.2634121_SC000_20260826152754_8b37.apk"
)
LIVE_101_URL = (
    "https://syncstation.manjuu.com/azurpromilia/android/c000/"
    "20261109164612_sample/AzurPromilia_1.0.1.2645521_SC000_20261109164612_5079.apk"
)
L2_APK_URL = LIVE_101_URL.replace("syncstation.manjuu.com", "l2-syncstation.manjuu.com")


class ManjuuSyncstationProbeTests(unittest.TestCase):
    def test_adapter_constants_and_url_time(self) -> None:
        self.assertEqual(manjuu_syncstation.NAME, "manjuu_syncstation")
        self.assertTrue(manjuu_syncstation.URL_TIME)
        self.assertEqual(
            manjuu_syncstation.HOSTS,
            {"syncstation.manjuu.com", "l2-syncstation.manjuu.com"},
        )
        self.assertEqual(file_time(STORED_030_URL, {}, manjuu_syncstation.URL_TIME), "2026-08-26T07:27:54Z")

    def test_matches_official_android_apk_urls_and_url_only_dispatch(self) -> None:
        urls = (
            STORED_030_URL,
            LIVE_101_URL,
            L2_APK_URL,
            STORED_030_URL.replace("syncstation.manjuu.com", "syncstation.manjuu.com:443"),
        )
        identities = (
            ("manjuu", "azurpromilia"),
            ("manjuu", None),
            (None, "azurpromilia"),
            (None, None),
        )
        for url in urls:
            for vendor, game_id in identities:
                with self.subTest(url=url, vendor=vendor, game_id=game_id):
                    self.assertTrue(manjuu_syncstation.matches(vendor, game_id, url))

    def test_matches_rejects_wrong_identity_pc_paths_and_unsafe_urls(self) -> None:
        for vendor, game_id in (
            ("mihoyo", "azurpromilia"),
            ("kuro", "azurpromilia"),
            ("manjuu", "azurlane"),
            ("manjuu", "wuwa"),
        ):
            with self.subTest(vendor=vendor, game_id=game_id):
                self.assertFalse(manjuu_syncstation.matches(vendor, game_id, STORED_030_URL))

        invalid_urls = (
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/manifest.json",
            "https://l2-syncstation.manjuu.com/azurpromilia/pg_chunk/c000/chunk_001.pak",
            "https://syncstation.manjuu.com/azurpromilia/pg_chunk/c000/fake.apk",
            "https://syncstation.manjuu.com/azurpromilia/windows/c000/AzurPromilia.apk",
            STORED_030_URL + "?sign=abc",
            STORED_030_URL + "?",
            STORED_030_URL + "#section",
            STORED_030_URL + "#",
            STORED_030_URL.replace("https://", "http://"),
            STORED_030_URL.replace("https://", "ftp://"),
            STORED_030_URL.replace("https://", "https://user:pass@"),
            STORED_030_URL.replace("syncstation.manjuu.com", "syncstation.manjuu.com:8443"),
            STORED_030_URL.replace("syncstation.manjuu.com", "syncstation.manjuu.com:badport"),
            "https://[::1/azurpromilia/android/c000/game.apk",
            STORED_030_URL.replace("syncstation.manjuu.com", "cdn.manjuu.com"),
            STORED_030_URL.replace("syncstation.manjuu.com", "syncstation.manjuu.com.evil.example"),
            STORED_030_URL[:-4] + ".zip",
            STORED_030_URL[:-4] + ".json",
            "https://syncstation.manjuu.com/azurpromilia/android/../pg_chunk/evil.apk",
            "https://syncstation.manjuu.com/azurpromilia/android/%2e%2e/pg_chunk/evil.apk",
            STORED_030_URL + "\n",
        )
        for url in invalid_urls:
            for identity in (("manjuu", "azurpromilia"), (None, None)):
                with self.subTest(url=url, identity=identity):
                    self.assertFalse(manjuu_syncstation.matches(*identity, url))

    def test_availability_classifies_pk_headers_errors_and_html_challenges(self) -> None:
        filename = "AzurPromilia_1.0.1.2645521_SC000_20261109164612_5079.apk"
        for status in (200, 206):
            for signature in (b"PK\x03\x04\x14\x00", b"PK\x05\x06\x00\x00", b"PK\x07\x08\x00\x00"):
                with self.subTest(status=status, signature=signature):
                    self.assertTrue(
                        manjuu_syncstation.availability(
                            status,
                            filename,
                            signature,
                            observed_size=1448044017,
                            expected_size=1448044017,
                            transport_returncode=0,
                            bytes_received=len(signature),
                        )
                    )

        for status in (404, 410):
            with self.subTest(status=status):
                self.assertFalse(manjuu_syncstation.availability(status, filename, b""))

        for status in (200, 206):
            for html_prefix in (b"<html><body>Denied</body></html>", b"  <!DOCTYPE html>\n<html>"):
                with self.subTest(status=status, html_prefix=html_prefix):
                    self.assertFalse(manjuu_syncstation.availability(status, filename, html_prefix))

        for status in (200, 206):
            for bad_prefix in (b"", b"PK", b"PK\x01\x02", b'{"code":403}', b"\x00\x01\x02\x03"):
                with self.subTest(status=status, bad_prefix=bad_prefix):
                    self.assertIsNone(manjuu_syncstation.availability(status, filename, bad_prefix))

        self.assertIsNone(manjuu_syncstation.availability(206, "AzurPromilia.zip", b"PK\x03\x04"))
        for status in (403, 429, 500, 502, 503):
            with self.subTest(status=status):
                self.assertIsNone(manjuu_syncstation.availability(status, filename, b"PK\x03\x04"))


if __name__ == "__main__":
    unittest.main()
