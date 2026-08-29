import unittest

from probe_adapters.common import ProbeError
from probe_adapters.pc import (
    hypergryph_arknights,
    hypergryph_endfield,
    kuro_cdn,
    mihoyo_autopatch,
    mihoyo_bh3_cdn,
    perfectworld_patcher,
)
from probe_adapters.pc.mihoyo_package_common import availability as hoyo_availability
from probe_adapters.registry import adapter_for


class PCAdapterTests(unittest.TestCase):
    def test_endfield_official_mirror_patch_and_resource_urls(self):
        urls = (
            "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.0/update/1/1/Windows/"
            "1.0.14_bJBg3b40frDq9bOB/patches/1.0.13/"
            "Beyond_Release_v1d0-Rel-cn-5157154-10_prod_obt_official_1_0_13.zip.001",
            "https://github.com/AetherArchive/beyond-hg-archive/releases/download/tag/"
            "1.1.9_RfPNtRXLwX2my3ep_patches_1.0.14_"
            "Beyond_Release_v1d0-Rel-cn-5157154-11_prod_obt_official_1_0_14.zip.001",
            "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.2/update/1/1/Windows/"
            "1.2.4_zGLFQ3WQTaGk3ocM/patches/30cT6Ahh66/1.1.9/v2/"
            "Beyond_Release_v1d1-Rel-cn-5769412-7_prod_obt_official_1_1_9_BDECv_v2.zip.001",
            "https://github.com/AetherArchive/beyond-hg-archive/releases/download/pkg/"
            "Beyond_Release_v1d3-Rel-cn-7123154-1_prod_obt_official.zip.001",
            "https://github.com/AetherArchive/beyond-hg-archive/releases/download/pkg00001/"
            "1.4.4_a11bc198dcd71ae1_patches_2RFzrqDEmp_v3_"
            "tm8rLW5hjS6wSihE_1_4_4_1_3_3.zip.001",
            "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.0/resource/Windows/initial/"
            "5793042-32_pUten9sPsmW2Xh8D/files/VFS/07A1BB91/"
            "872C74CD14DB0F9D81789B343A26C123.chk",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(
                    adapter_for("hypergryph", "endfield", url, platform="windows").NAME,
                    "hypergryph_endfield_pc",
                )

    def test_matchers_and_platform_dispatch(self):
        cases = [
            (
                "hypergryph",
                "arknights",
                "https://ak.hycdn.cn/GzD1CpaWgmSq1wew/75.0/update/1/1/Windows/"
                "75.0.0_on1FEr6BLTxmDmQD/packs/production_075-75.0.0-d68d1242a14-40-HG.zip.001",
                "hypergryph_arknights_pc",
            ),
            (
                "hypergryph",
                "endfield",
                "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.0/update/1/1/Windows/"
                "1.0.13_XMK5AwnQ7IUS3nUH/packs/"
                "Beyond_Release_v1d0-Rel-cn-5157154-10_prod_obt_official.zip.001",
                "hypergryph_endfield_pc",
            ),
            (
                "mihoyo",
                "bh3",
                "http://bundle.bh3.com/tmp/pc/BH3_v3.8.0_12d334ef92e.7z",
                "mihoyo_bh3_cdn",
            ),
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

    def test_historical_pc_matchers_reject_wrong_identity_or_url_shape(self):
        arknights = (
            "https://ak.hycdn.cn/GzD1CpaWgmSq1wew/75.0/update/1/1/Windows/"
            "75.0.0_on1FEr6BLTxmDmQD/packs/production_075-75.0.0-d68d1242a14-40-HG.zip.001"
        )
        endfield = (
            "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.0/update/1/1/Windows/"
            "1.0.13_XMK5AwnQ7IUS3nUH/packs/"
            "Beyond_Release_v1d0-Rel-cn-5157154-10_prod_obt_official.zip.001"
        )
        mirror = (
            "https://github.com/AetherArchive/beyond-hg-archive/releases/download/tag/"
            "Beyond_Release_v1d0-Rel-cn-5157154-10_prod_obt_official.zip.001"
        )
        bh3 = "http://bundle.bh3.com/tmp/pc/BH3_v3.8.0_12d334ef92e.7z"
        cases = (
            ("hypergryph", "endfield", arknights),
            ("mihoyo", "arknights", arknights),
            ("hypergryph", "arknights", endfield),
            ("hypergryph", "endfield", endfield.replace("beyond.hycdn.cn", "ak.hycdn.cn")),
            ("hypergryph", "endfield", endfield.replace("https://", "http://")),
            ("hypergryph", "endfield", endfield.replace("/Windows/", "/Android/")),
            (
                "hypergryph",
                "endfield",
                endfield.rsplit("/", 1)[0] + "/unrelated_file.zip.001",
            ),
            ("hypergryph", "endfield", endfield + "?auth_key=secret"),
            ("hypergryph", "endfield", endfield + "#fragment"),
            ("hypergryph", "endfield", endfield.replace("https://", "https://u:p@")),
            ("hypergryph", "endfield", mirror.replace("AetherArchive", "OtherArchive")),
            ("hypergryph", "endfield", mirror.replace("/releases/download/tag/", "/raw/main/")),
            ("mihoyo", "bh3", bh3.replace("bundle.bh3.com", "app.bh3.com")),
            ("mihoyo", "bh3", bh3.replace("/tmp/pc/", "/client/")),
            ("mihoyo", "bh3", bh3 + "?x=1"),
        )
        for vendor, game, url in cases:
            with self.subTest(url=url), self.assertRaises(ProbeError):
                adapter_for(vendor, game, url, platform="windows")
        self.assertFalse(
            hypergryph_arknights.matches(
                "hypergryph", "arknights", arknights.replace("/Windows/", "/Android/"),
            )
        )
        self.assertFalse(
            hypergryph_endfield.matches(
                "hypergryph", "endfield", endfield.replace("/Windows/", "/Android/"),
            )
        )
        with self.assertRaises(ProbeError):
            adapter_for("hypergryph", "arknights", arknights, platform="linux")

    def test_endfield_resource_and_archive_availability_requires_observation(self):
        self.assertTrue(hypergryph_endfield.availability(206, "a.zip.001", b"PK\x03\x04"))
        self.assertFalse(hypergryph_endfield.availability(200, "a.zip.001", b"plain"))
        self.assertTrue(
            hypergryph_endfield.availability(
                206, "a.zip.002", b"", observed_size=10, expected_size=10,
            )
        )
        self.assertFalse(
            hypergryph_endfield.availability(
                206, "a.zip.002", b"", observed_size=9, expected_size=10,
            )
        )
        self.assertTrue(
            hypergryph_endfield.availability(
                206, "A.chk", b"not-a-zip", observed_size=10, expected_size=10,
            )
        )
        self.assertIsNone(
            hypergryph_endfield.availability(
                206, "A.chk", b"not-a-zip", observed_size=9, expected_size=10,
            )
        )
        self.assertIsNone(hypergryph_endfield.availability(403, "A.chk", b""))
        self.assertFalse(hypergryph_endfield.availability(404, "A.blc", b""))
        self.assertFalse(hypergryph_endfield.availability(410, "A.chk", b""))

    def test_bh3_legacy_http_availability_needs_response_evidence(self):
        self.assertTrue(mihoyo_bh3_cdn.availability(200, "BH3_v3.8.0_x.7z", b"7z\xbc\xaf\x27\x1c"))
        self.assertFalse(mihoyo_bh3_cdn.availability(404, "BH3_v3.8.0_x.7z", b""))
        self.assertFalse(mihoyo_bh3_cdn.availability(410, "BH3_v3.8.0_x.7z", b""))
        self.assertIsNone(mihoyo_bh3_cdn.availability(403, "BH3_v3.8.0_x.7z", b""))

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
