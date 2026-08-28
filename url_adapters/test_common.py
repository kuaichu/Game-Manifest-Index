import unittest
from unittest.mock import patch

from url_adapters.common import endpoint, version_from_url, read_small, AdapterError


class CommonAdapterTests(unittest.TestCase):
    def test_all_official_endpoints_are_fixed_https_urls(self):
        expected = {
            ("mihoyo", "hk4e"): "https://api-takumi.mihoyo.com/event/download_porter/link/ys_cn/official/android_default",
            ("mihoyo", "hkrpg"): "https://api-takumi.mihoyo.com/event/download_porter/link/hkrpg_cn/official/android_default",
            ("mihoyo", "nap"): "https://api-takumi.mihoyo.com/event/download_porter/link/nap_cn/official/android_default",
            ("mihoyo", "bh3"): "https://api-takumi.mihoyo.com/event/download_porter/link/bh3_cn/bh3/android_official",
            ("mihoyo", "bh2"): "https://www.benghuai.com/download/latest",
            ("hypergryph", "endfield"): "https://launcher.hypergryph.com/game/latest/6LL0KJuqHBVz33WK/1/1",
            ("hypergryph", "arknights"): "https://launcher.hypergryph.com/game/latest/GzD1CpaWgmSq1wew/1/1",
            ("kuro", "wuwa"): "https://download.kurogames.com/mc_WnGtDn85y8lJB4mTmYHYuNjIl9n6YGVm/official/cn/zh-Hans/android_app.json",
            ("kuro", "pns"): "https://download.kurogames.com/pns/official/cn/zh-Hans/androidpc_app.json",
            ("perfectworld", "tof"): "https://static.games.wanmei.com/public/commonData/gamesData/gameDownload/ht-gameDownload.js",
            ("perfectworld", "p5x"): "https://static.games.wanmei.com/public/commonData/gamesData/gameDownload/p5x-gameDownload.js",
            ("perfectworld", "nte"): "https://static.games.wanmei.com/public/commonData/gamesData/gameDownload/yh-gameDownload.js",
        }
        self.assertEqual(len(expected), 12)
        for (vendor, game), url in expected.items():
            self.assertEqual(endpoint(vendor, game), url)

    def test_version_parser(self):
        self.assertEqual(version_from_url("https://cdn.example/x-v7.0.1.apk"), "7.0.1")
        self.assertIsNone(version_from_url("https://cdn.example/latest.apk"))

    @patch("url_adapters.common.curl")
    def test_read_small_uses_fail_and_one_mib_limit(self, curl):
        curl.return_value = "body"
        self.assertEqual(read_small("https://example.test/a", 12), "body")
        curl.assert_called_once_with(["--fail", "--max-filesize", "1048576", "https://example.test/a"], 12)

    def test_probe_dependency_is_lazy(self):
        import sys
        self.assertNotIn("probe_adapters.service", sys.modules)


if __name__ == "__main__":
    unittest.main()
