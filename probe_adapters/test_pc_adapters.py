import unittest

from probe_adapters.common import ProbeError
from probe_adapters.pc import kuro_cdn, mihoyo_autopatch, mihoyo_bh3_cdn, perfectworld_patcher
from probe_adapters.pc.mihoyo_package_common import availability as hoyo_availability
from probe_adapters.registry import adapter_for


class PCAdapterTests(unittest.TestCase):
    def test_matchers_and_platform_dispatch(self):
        cases = [
            ("mihoyo", "hk4e", "https://autopatchcn.yuanshen.com/client/a.zip", "mihoyo_autopatch"),
            ("mihoyo", "hkrpg", "https://autopatchcn.bhsr.com/client/a.7z.1", "mihoyo_autopatch"),
            ("mihoyo", "nap", "https://autopatchcn.juequling.com/client/a.bin", "mihoyo_autopatch"),
            ("mihoyo", "bh3", "https://app.bh3.com/client/a.zip", "mihoyo_bh3_cdn"),
            ("kuro", "wuwa", "https://pcdownload-aliyun.aki-game.com/a/indexFile.json", "kuro_cdn"),
            ("perfectworld", "nte", "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/config.xml", "perfectworld_patcher"),
            ("perfectworld", "p5x", "https://nsywl-client-dev1.wmupd.com/clientRes/CN_OB_OFFICIAL/Version/Windows/version/1.2.3/ResList.bin.zip", "perfectworld_patcher"),
        ]
        for vendor, game, url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(adapter_for(vendor, game, url, platform="windows").NAME, expected)
                self.assertEqual(adapter_for(vendor, game, url).NAME, expected)

    def test_rejects_unsafe_or_wrong_identity_urls(self):
        base = "https://autopatchcn.yuanshen.com/client/a.zip"
        for url in (
            base.replace("https://", "http://"),
            base.replace(".com/", ".com:444/"),
            base + "?x=1",
            base + "#x",
            base.replace("https://", "https://u:p@"),
            base.replace("yuanshen", "bhsr"),
        ):
            with self.subTest(url=url):
                with self.assertRaises(ProbeError):
                    adapter_for("mihoyo", "hk4e", url, platform="windows")

    def test_kuro_apk_pc_split_and_wrong_paths(self):
        apk = "https://pcdownload-aliyun.aki-game.com/a/game.apk"
        with self.assertRaises(ProbeError):
            adapter_for("kuro", "wuwa", apk, platform="windows")
        with self.assertRaises(ProbeError):
            adapter_for("kuro", "wuwa", "https://pcdownload-aliyun.aki-game.com/a/other.json", platform="windows")
        with self.assertRaises(ProbeError):
            adapter_for("kuro", "wuwa", "https://pcdownload-aliyun.aki-game.com/a/notindexFile.json", platform="windows")
        self.assertEqual(adapter_for(None, None, apk, platform="android").NAME, "shared_generic_apk")

    def test_mihoyo_availability_signatures_and_parts(self):
        self.assertTrue(hoyo_availability(200, "x.zip", b"PK\x03\x04"))
        self.assertTrue(hoyo_availability(206, "x.7z.1", b"7z\xbc\xaf\x27\x1c"))
        self.assertFalse(hoyo_availability(200, "x.zip", b"plain"))
        self.assertTrue(hoyo_availability(206, "x.zip.2", b"", expected_size=12, observed_size=12))
        self.assertFalse(hoyo_availability(206, "x.zip.2", b"", expected_size=12, observed_size=11))
        self.assertIsNone(hoyo_availability(206, "x.zip.2", b"", expected_size=None, observed_size=12))
        self.assertIsNone(hoyo_availability(200, "x.bin", b"anything"))
        self.assertFalse(hoyo_availability(404, "x.zip", b""))
        self.assertFalse(hoyo_availability(410, "x.zip", b""))
        self.assertIsNone(hoyo_availability(403, "x.zip", b""))

    def test_kuro_and_perfectworld_availability(self):
        self.assertTrue(kuro_cdn.availability(200, "indexFile.json", b""))
        self.assertTrue(kuro_cdn.availability(206, "resource.json", b""))
        self.assertFalse(kuro_cdn.availability(404, "resource.json", b""))
        self.assertFalse(kuro_cdn.availability(410, "resource.json", b""))
        self.assertIsNone(kuro_cdn.availability(403, "resource.json", b""))
        self.assertTrue(perfectworld_patcher.availability(200, "config.xml", b"<?xml"))
        self.assertFalse(perfectworld_patcher.availability(200, "config.xml", b"<html>"))
        self.assertTrue(perfectworld_patcher.availability(206, "ResList.bin.zip", b"PK\x03\x04"))
        self.assertFalse(perfectworld_patcher.availability(200, "ResList.bin.zip", b"<!doctype html>"))
        self.assertFalse(perfectworld_patcher.availability(410, "ResList.bin.zip", b""))
        self.assertIsNone(perfectworld_patcher.availability(403, "ResList.bin.zip", b""))
